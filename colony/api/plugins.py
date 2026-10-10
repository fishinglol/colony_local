"""OpenClaw Plugins catalog & management endpoints.

Allows viewing categorized plugins with recommendations (recommended vs optional)
and toggling plugins on/off directly from Colony UI.
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..engine.openclaw import config_lock, read_config, write_config

logger = logging.getLogger(__name__)
router = APIRouter()

PLUGIN_CATALOG = [
    # ── 1. Web & Search ──────────────────────────────────────────────────────────
    {
        "id": "duckduckgo",
        "name": "DuckDuckGo Search",
        "category": "web",
        "category_title": "🌐 1. Web & Information Retrieval (การค้นหาเว็บและข้อมูลสด)",
        "icon": "🦆",
        "description": "ค้นหาเว็บสด ข้อมูลราคา ข่าวสารปัจจุบัน แบบ Real-time โดยไม่เก็บประวัติ",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ฟรี 100% ไม่ต้องใช้ API key ช่วยให้ AI ตอบเรื่องปัจจุบันได้ถูกต้อง",
        "requires_key": False,
    },
    {
        "id": "web-readability",
        "name": "Web Readability & Scraper",
        "category": "web",
        "category_title": "🌐 1. Web & Information Retrieval (การค้นหาเว็บและข้อมูลสด)",
        "icon": "📰",
        "description": "ดึงเนื้อหาจากลิงก์เว็บและแปลงเป็นข้อความอ่านง่าย ตัดโฆษณาและโค้ด HTML",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ช่วยให้ AI สรุปบทความจาก URL ได้กระชับและรวดเร็ว",
        "requires_key": False,
    },
    {
        "id": "brave",
        "name": "Brave Search API",
        "category": "web",
        "category_title": "🌐 1. Web & Information Retrieval (การค้นหาเว็บและข้อมูลสด)",
        "icon": "🦁",
        "description": "เครื่องมือค้นหาอิสระของ Brave สำหรับผลลัพธ์ความเป็นส่วนตัวสูง",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Brave Search API Key (ใช้ DuckDuckGo แทนได้ฟรี)",
        "requires_key": True,
        "key_hint": "BRAVE_API_KEY",
    },
    {
        "id": "tavily",
        "name": "Tavily AI Search",
        "category": "web",
        "category_title": "🌐 1. Web & Information Retrieval (การค้นหาเว็บและข้อมูลสด)",
        "icon": "🔍",
        "description": "Search Engine ที่ออกแบบมาสำหรับ AI Agents ค้นหาข้อมูลเชิงลึกและสรุปผล",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Tavily API Key เหมาะกับงานวิจัยเฉพาะทาง",
        "requires_key": True,
        "key_hint": "TAVILY_API_KEY",
    },
    {
        "id": "google",
        "name": "Google / Gemini Search",
        "category": "web",
        "category_title": "🌐 1. Web & Information Retrieval (การค้นหาเว็บและข้อมูลสด)",
        "icon": "🌐",
        "description": "ค้นหาผ่าน Google Search API หรือ Gemini Grounding",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Google Cloud หรือ Gemini API Key",
        "requires_key": True,
        "key_hint": "GEMINI_API_KEY",
    },

    # ── 2. Automation & Scheduling ───────────────────────────────────────────────
    {
        "id": "cron",
        "name": "Cron & Scheduled Tasks",
        "category": "automation",
        "category_title": "⏰ 2. Automation & Scheduling (งานอัตโนมัติ & การแจ้งเตือน)",
        "icon": "⏰",
        "description": "ระบบตั้งเวลาแจ้งเตือน นัดหมาย และสั่งรันงานอัตโนมัติในเบื้องหลัง",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ช่วยให้ AI สามารถเตือนความจำและทำงานตามกำหนดเวลาได้",
        "requires_key": False,
    },
    {
        "id": "automations",
        "name": "Background Automations",
        "category": "automation",
        "category_title": "⏰ 2. Automation & Scheduling (งานอัตโนมัติ & การแจ้งเตือน)",
        "icon": "⚡",
        "description": "รัน Workflow งานหลายขั้นตอนใน Background โดยไม่บล็อกหน้าแชต",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "เหมาะสำหรับงานที่ต้องใช้เวลา เช่น การค้นคว้าหรือรันสคริปต์ยาวๆ",
        "requires_key": False,
    },
    {
        "id": "heartbeat",
        "name": "System Heartbeat & Health",
        "category": "automation",
        "category_title": "⏰ 2. Automation & Scheduling (งานอัตโนมัติ & การแจ้งเตือน)",
        "icon": "💓",
        "description": "ตรวจเช็กความพร้อมและสุขภาพของ OpenClaw Gateway ตลอดเวลา",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ช่วยให้ระบบเชื่อมต่อได้อย่างราบรื่นและตรวจจับปัญหาได้ทันที",
        "requires_key": False,
    },

    # ── 3. Execution & Sandbox ───────────────────────────────────────────────────
    {
        "id": "bash",
        "name": "Shell / Terminal Execution",
        "category": "code",
        "category_title": "💻 3. Execution & Sandbox (การรันคำสั่ง & จัดการไฟล์)",
        "icon": "💻",
        "description": "รันคำสั่ง Terminal ในแซนด์บ็อกซ์ ปลอดภัย ควบคุมสิทธิ์ได้ (เหมาะสำหรับ Coder)",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำสำหรับ Coder",
        "recommendation_reason": "จำเป็นสำหรับการรันคำสั่ง, build, test, และจัดการสภาพแวดล้อมโปรเจกต์",
        "requires_key": False,
    },
    {
        "id": "document-extract",
        "name": "Document & PDF Extract",
        "category": "code",
        "category_title": "💻 3. Execution & Sandbox (การรันคำสั่ง & จัดการไฟล์)",
        "icon": "📄",
        "description": "อ่านและดึงเนื้อหาจากไฟล์ PDF, Word, และเอกสารสเปรดชีต",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ช่วยให้ AI สามารถอ่านเอกสารประกอบและสเปกงานที่แนบเข้ามาได้",
        "requires_key": False,
    },
    {
        "id": "browser",
        "name": "Chrome Browser Automation",
        "category": "code",
        "category_title": "💻 3. Execution & Sandbox (การรันคำสั่ง & จัดการไฟล์)",
        "icon": "🖥️",
        "description": "ควบคุม Chromium อัตโนมัติ เปิดเว็บจริง กรอกฟอร์ม คลิกปุ่ม ถ่าย Screenshot",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก (ใช้ทรัพยากรสูง)",
        "recommendation_reason": "เปิดเมื่อต้องการให้ AI ท่องเว็บแบบเสมือนคนจริง (กิน RAM เพิ่มขึ้น)",
        "requires_key": False,
    },

    # ── 4. Memory & Brain ────────────────────────────────────────────────────────
    {
        "id": "memory-core",
        "name": "Episodic Memory & Dreaming",
        "category": "memory",
        "category_title": "🧠 4. Memory & Brain (ระบบความจำ & สติปัญญา)",
        "icon": "🧠",
        "description": "บันทึกความจำระยะยาว จัดหมวดหมู่บันทึกรายวัน และสรุปสิ่งที่เรียนรู้แบบอัตโนมัติ",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "ช่วยให้ AI จำบริบท ความชอบ และสิ่งที่เคยคุยกันข้ามวันได้",
        "requires_key": False,
    },
    {
        "id": "active-memory",
        "name": "Active Context Retention",
        "category": "memory",
        "category_title": "🧠 4. Memory & Brain (ระบบความจำ & สติปัญญา)",
        "icon": "💭",
        "description": "ดึงข้อมูลความจำที่เกี่ยวข้องเข้ามาในบทสนทนาอย่างแม่นยำ",
        "recommendation": "recommended",
        "recommendation_label": "🟢 แนะนำเปิด",
        "recommendation_reason": "เพิ่มความฉลาดในการตอบคำถามโดยอ้างอิงข้อมูลเก่าของผู้ใช้",
        "requires_key": False,
    },
    {
        "id": "memory-wiki",
        "name": "Personal Knowledge Wiki",
        "category": "memory",
        "category_title": "🧠 4. Memory & Brain (ระบบความจำ & สติปัญญา)",
        "icon": "📚",
        "description": "จัดระเบียบองค์ความรู้และข้อมูลสำคัญในรูปแบบโครงสร้าง Wiki",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "เหมาะสำหรับผู้ที่ต้องการสร้างฐานความรู้ส่วนตัวขนาดใหญ่",
        "requires_key": False,
    },

    # ── 5. External Integrations ─────────────────────────────────────────────────
    {
        "id": "github",
        "name": "GitHub Integration",
        "category": "integrations",
        "category_title": "📱 5. External Integrations (แอปและช่องทางภายนอก)",
        "icon": "🐙",
        "description": "ดึงข้อมูล Issues, PRs, Commit โค้ด และเชื่อมโยงกับ GitHub Repo",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก (ต้องการ GitHub Token)",
        "recommendation_reason": "เปิดเมื่อต้องการให้ Coder จัดการ Git และ Pull Request ได้โดยตรง",
        "requires_key": True,
        "key_hint": "GITHUB_TOKEN",
    },
    {
        "id": "notion",
        "name": "Notion Workspace",
        "category": "integrations",
        "category_title": "📱 5. External Integrations (แอปและช่องทางภายนอก)",
        "icon": "📓",
        "description": "อ่านและเขียนข้อมูลใน Notion Database และหน้าเอกสาร",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Notion Integration Token",
        "requires_key": True,
        "key_hint": "NOTION_API_KEY",
    },
    {
        "id": "discord",
        "name": "Discord Bot Channel",
        "category": "integrations",
        "category_title": "📱 5. External Integrations (แอปและช่องทางภายนอก)",
        "icon": "💬",
        "description": "เชื่อมต่อบอทพูดคุยผ่านช่องทาง Discord Server",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Discord Bot Token สำหรับรับส่งข้อความภายนอก",
        "requires_key": True,
        "key_hint": "DISCORD_BOT_TOKEN",
    },
    {
        "id": "telegram",
        "name": "Telegram Bot Channel",
        "category": "integrations",
        "category_title": "📱 5. External Integrations (แอปและช่องทางภายนอก)",
        "icon": "✈️",
        "description": "เชื่อมต่อพูดคุยผ่าน Telegram Bot ส่วนตัวหรือกลุ่ม",
        "recommendation": "optional",
        "recommendation_label": "⚪ ทางเลือก",
        "recommendation_reason": "ต้องมี Telegram Bot Token จาก @BotFather",
        "requires_key": True,
        "key_hint": "TELEGRAM_BOT_TOKEN",
    },
]


class PluginToggleRequest(BaseModel):
    plugin_id: str
    enabled: bool


class BatchPluginToggleRequest(BaseModel):
    plugins: dict[str, bool]


@router.get("/openclaw/plugins")
def list_openclaw_plugins() -> dict[str, Any]:
    """Return categorized OpenClaw plugins with current enabled state and recommendations."""
    cfg = read_config()
    plugin_entries = cfg.get("plugins", {}).get("entries", {})
    web_search_enabled = cfg.get("tools", {}).get("web", {}).get("search", {}).get("enabled", True)

    results = []
    for item in PLUGIN_CATALOG:
        pid = item["id"]
        # Determine enabled state
        if pid == "duckduckgo":
            is_enabled = web_search_enabled and plugin_entries.get("duckduckgo", {}).get("enabled", True)
        elif pid in ("cron", "automations", "heartbeat", "bash", "memory-core", "active-memory"):
            # Stock core tools: enabled by default unless explicitly disabled
            p_entry = plugin_entries.get(pid, {})
            is_enabled = p_entry.get("enabled", True) if isinstance(p_entry, dict) else True
        else:
            p_entry = plugin_entries.get(pid, {})
            is_enabled = p_entry.get("enabled", False) if isinstance(p_entry, dict) else False

        entry = dict(item)
        entry["enabled"] = bool(is_enabled)
        results.append(entry)

    categories = [
        {"id": "web", "title": "🌐 1. Web & Search (ค้นหาเว็บ & ข้อมูลสด)", "count": sum(1 for r in results if r["category"] == "web")},
        {"id": "automation", "title": "⏰ 2. Automation & Scheduling (งานอัตโนมัติ & แจ้งเตือน)", "count": sum(1 for r in results if r["category"] == "automation")},
        {"id": "code", "title": "💻 3. Code & Sandbox (การรันโค้ด & จัดการไฟล์)", "count": sum(1 for r in results if r["category"] == "code")},
        {"id": "memory", "title": "🧠 4. Memory & Brain (ความจำ & สมอง)", "count": sum(1 for r in results if r["category"] == "memory")},
        {"id": "integrations", "title": "📱 5. External Channels & Integrations (แอปภายนอก)", "count": sum(1 for r in results if r["category"] == "integrations")},
    ]

    return {
        "status": "ok",
        "categories": categories,
        "plugins": results,
        "total_active": sum(1 for r in results if r["enabled"]),
        "total_available": len(results),
    }


@router.post("/openclaw/plugins")
def toggle_openclaw_plugin(req: PluginToggleRequest) -> dict[str, Any]:
    """Toggle a specific OpenClaw plugin on or off."""
    with config_lock:
        cfg = read_config()
        if "plugins" not in cfg:
            cfg["plugins"] = {}
        if "entries" not in cfg["plugins"]:
            cfg["plugins"]["entries"] = {}

        pid = req.plugin_id
        enabled = req.enabled

        # Handle special web search syncing
        if pid == "duckduckgo":
            if "tools" not in cfg:
                cfg["tools"] = {}
            if "web" not in cfg["tools"]:
                cfg["tools"]["web"] = {}
            if "search" not in cfg["tools"]["web"]:
                cfg["tools"]["web"]["search"] = {}
            cfg["tools"]["web"]["search"]["enabled"] = enabled
            cfg["tools"]["web"]["search"]["provider"] = "duckduckgo"
            cfg["plugins"]["entries"]["duckduckgo"] = {"enabled": enabled}
        else:
            cfg["plugins"]["entries"][pid] = {"enabled": enabled}

        write_config(cfg)
        logger.info("OpenClaw plugin '%s' set to enabled=%s", pid, enabled)
        return {"status": "ok", "plugin_id": pid, "enabled": enabled}


@router.post("/openclaw/plugins/batch")
def batch_toggle_plugins(req: BatchPluginToggleRequest) -> dict[str, Any]:
    """Batch update multiple plugin enabled states."""
    with config_lock:
        cfg = read_config()
        if "plugins" not in cfg:
            cfg["plugins"] = {}
        if "entries" not in cfg["plugins"]:
            cfg["plugins"]["entries"] = {}

        for pid, enabled in req.plugins.items():
            if pid == "duckduckgo":
                if "tools" not in cfg:
                    cfg["tools"] = {}
                if "web" not in cfg["tools"]:
                    cfg["tools"]["web"] = {}
                if "search" not in cfg["tools"]["web"]:
                    cfg["tools"]["web"]["search"] = {}
                cfg["tools"]["web"]["search"]["enabled"] = enabled
                cfg["tools"]["web"]["search"]["provider"] = "duckduckgo"
                cfg["plugins"]["entries"]["duckduckgo"] = {"enabled": enabled}
            else:
                cfg["plugins"]["entries"][pid] = {"enabled": enabled}

        write_config(cfg)
        logger.info("OpenClaw plugins batch updated: %s", req.plugins)
        return {"status": "ok", "updated": list(req.plugins.keys())}
