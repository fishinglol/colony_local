# Lifted from backend/app/json_store.py — no changes needed.
import json
from pathlib import Path
from threading import RLock
from typing import Any


class JsonStore:
    def __init__(self, path: Path, default: Any):
        self.path = path
        self.default = default
        self.lock = RLock()

    def read(self) -> Any:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.write(self.default)
            with self.path.open("r", encoding="utf-8") as handle:
                raw = handle.read()
            try:
                return json.loads(raw, strict=False)
            except Exception:
                try:
                    value, _ = json.JSONDecoder(strict=False).raw_decode(raw.lstrip())
                    self.write(value)
                    return value
                except Exception:
                    return self.default

    def write(self, value: Any) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
            tmp_path.replace(self.path)
