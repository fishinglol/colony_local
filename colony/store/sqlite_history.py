"""Colony Local — SQLite conversation and session history store.

Implements the OpenClaw-style SQLite session storage layer while maintaining full
compatibility with Colony Local's conversation history format.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import get_settings


def _get_db_path() -> Path:
    data_dir = get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "colony.sqlite"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            topic_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            channel TEXT DEFAULT 'auto',
            role_id TEXT,
            role_name TEXT,
            model TEXT,
            decided_by TEXT,
            confidence REAL,
            attachments_json TEXT,
            created_at TEXT NOT NULL,
            order_seq INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv_seq ON messages(conversation_id, order_seq);
        """)


def append_exchange_sqlite(
    *,
    conversation_id: str,
    user_message: str | None,
    assistant_response: dict[str, Any],
    channel: str = "auto",
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    user_msg_id = f"msg_{uuid4().hex}" if user_message is not None else None
    assistant_msg_id = f"msg_{uuid4().hex}"

    with get_connection() as conn:
        # Ensure conversation exists
        cur = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,))
        if not cur.fetchone():
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, (user_message or "")[:64] or "New Chat", now, now),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

        # Get next sequence number
        seq_cur = conn.execute(
            "SELECT COALESCE(MAX(order_seq), 0) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        max_seq = seq_cur.fetchone()[0]

        # Insert User Message
        if user_message is not None:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, channel, attachments_json, created_at, order_seq
                ) VALUES (?, ?, 'user', ?, ?, ?, ?, ?)
                """,
                (
                    user_msg_id,
                    conversation_id,
                    user_message,
                    channel,
                    json.dumps(attachments or []),
                    now,
                    max_seq + 1,
                ),
            )
            max_seq += 1

        # Insert Assistant Message
        conn.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, content, channel, role_id, role_name, model,
                decided_by, confidence, created_at, order_seq
            ) VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assistant_msg_id,
                conversation_id,
                assistant_response.get("reply", ""),
                channel,
                assistant_response.get("role_id"),
                assistant_response.get("role_name"),
                assistant_response.get("model"),
                assistant_response.get("decided_by"),
                assistant_response.get("confidence"),
                now,
                max_seq + 1,
            ),
        )

    return user_msg_id, assistant_msg_id


def list_messages_sqlite(conversation_id: str) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY order_seq ASC",
            (conversation_id,),
        ).fetchall()

        result = []
        for r in rows:
            attachments = []
            if r["attachments_json"]:
                try:
                    attachments = json.loads(r["attachments_json"])
                except Exception:
                    attachments = []
            item = {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "channel": r["channel"],
                "created_at": r["created_at"],
            }
            if r["role"] == "assistant":
                item.update({
                    "role_id": r["role_id"],
                    "role_name": r["role_name"],
                    "model": r["model"],
                    "decided_by": r["decided_by"],
                    "confidence": r["confidence"],
                })
            elif attachments:
                item["attachments"] = attachments
            result.append(item)
        return result
