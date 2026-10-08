"""Turn a provider failure into a message a normal person can act on (Thai, like the rest of the UI)."""
from ..llm.http import ProviderError


def _kaggle_hint(status: int | None, model: str) -> str:
    if status == 401:
        return "ยังไม่ได้ใส่ URL ของ Kaggle server เปิด **Settings** แล้ววาง URL ที่ notebook พิมพ์ออกมา"
    if status in (400, 404):
        return (f"Kaggle server ไม่มีโมเดล `{model[len('kaggle/'):]}` ตรวจชื่อโมเดล (กด ✎) "
                "หรือเพิ่มชื่อนี้ในรายการ MODELS ของ notebook แล้วรันใหม่")
    if status == 500:
        return (f"Kaggle server ตอบกลับว่าโมเดล `{model[len('kaggle/'):]}` ทำงานไม่ได้ (server ยังเปิดอยู่) "
                "อาจเป็นเพราะหน่วยความจำ GPU ไม่พอหรือโหลดโมเดลไม่สำเร็จ ลองเปลี่ยนไปใช้โมเดลอื่น")
    return ("ติดต่อ Kaggle server ไม่ได้ notebook อาจหยุดไปแล้ว (Kaggle ปิด session เองเมื่อครบเวลา) "
            "เปิด notebook รันใหม่ แล้ววาง URL ใหม่ใน **Settings**")


def _ollama_hint(status: int | None, model: str, exc: ProviderError) -> str:
    from ..config import get_settings
    settings = get_settings()
    base_url = settings.ollama_base_url
    msg = str(exc).lower()
    clean_model = model[len("ollama/"):] if model.startswith("ollama/") else model

    if "connection refused" in msg or "errno 61" in msg or "10061" in msg or "cannot connect" in msg:
        return (
            f"เชื่อมต่อไปยัง Ollama ที่ `{base_url}` ไม่ได้ (Connection refused) — "
            "หากรันในเครื่องให้เปิด Terminal พิมพ์ `ollama serve` หรือเปิดแอป Ollama ก่อน "
            "หรือหากใช้ Cloud/Remote API ให้เข้าไปตั้งค่า **Ollama Base URL** ใน **Settings**"
        )
    if status == 404:
        return (
            f"Ollama server ไม่มีโมเดล `{clean_model}` "
            f"ให้ลองสั่ง `ollama pull {clean_model}` ใน Terminal หรือเลือกโมเดลอื่น"
        )
    if status in (401, 403):
        return "Ollama API Key ไม่ถูกต้อง ตรวจสอบใน **Settings** ว่าวาง key ถูกต้องหรือไม่"
    if status is not None and status >= 500:
        return (
            f"Ollama ตอบกลับว่าโมเดล `{clean_model}` ทำงานขัดข้อง (status {status}) "
            "อาจเป็นเพราะหน่วยความจำ GPU/RAM ไม่พอหรือโหลดโมเดลไม่สำเร็จ"
        )
    return f"เรียกโมเดล Ollama `{clean_model}` ไม่สำเร็จ ({exc})"


def explain(exc: ProviderError, model: str) -> str:
    status = exc.status
    if "openclaw" in str(exc).lower() or "18789" in str(exc):
        hint = (
            "เชื่อมต่อไปยัง OpenClaw Gateway ไม่ได้ — "
            "กรุณาเปิด Terminal แล้วรัน `pnpm openclaw gateway` เพื่อเริ่มต้นระบบหลังบ้าน"
        )
    elif model.startswith("kaggle/"):
        hint = _kaggle_hint(status, model)
    elif model.startswith("ollama/") or "ollama" in str(exc).lower() or (exc.provider_message and "ollama" in exc.provider_message.lower()):
        hint = _ollama_hint(status, model, exc)
    elif status == 429:
        hint = (f"โมเดล `{model}` ถูกจำกัดจำนวนครั้งชั่วคราว (โมเดลฟรีมักเป็นแบบนี้เพราะทุกคนใช้โควตากลางร่วมกัน) "
                "ระบบลองซ้ำให้แล้วแต่ยังไม่ผ่าน ลองส่งใหม่อีกสักครู่ หรือกด **Ask another agent** ใต้ข้อความของคุณเพื่อให้ agent ตัวอื่นตอบแทน")
    elif status == 403 and "agentic" in (exc.provider_message or "").lower():
        hint = (f"โมเดลฟรี `{model}` เปิดให้ใช้เฉพาะในแอปประเภท coding agent จึงใช้ในแชทแบบนี้ไม่ได้ "
                "กด ✎ ที่ agent นี้แล้วเลือกโมเดลอื่น (ปุ่ม **Test this model** ช่วยเช็กก่อนได้)")
    elif status == 401:
        hint = "OpenRouter ไม่รับ API key นี้ ตรวจที่ **Settings** ว่าวาง key ถูกและยังไม่ถูกลบ"
    elif status == 403:
        hint = "OpenRouter ไม่อนุญาตให้ใช้โมเดลนี้ (ไม่ได้รับอนุญาต) ตรวจ API key ที่ **Settings** หรือเลือกโมเดลอื่น"
        if exc.provider_message:
            hint += f" — OpenRouter แจ้งว่า: {exc.provider_message[:160]}"
    elif status == 402:
        hint = "เครดิตบัญชี OpenRouter ไม่พอสำหรับโมเดลนี้ เติมเครดิต หรือเปลี่ยน agent ไปใช้โมเดลฟรี"
    elif status == 400 and any(w in (exc.provider_message or "").lower() for w in ("context length", "context window", "too long", "too many tokens", "maximum context")):
        hint = (f"ข้อความนี้ยาวเกิน context ของโมเดล `{model}` (ดูตัววัด **Context** ที่มุมขวาบน) "
                "ลองย่อข้อความ เริ่มแชทใหม่ หรือกด **Ask another agent** เพื่อให้ agent ที่ context ใหญ่กว่าตอบแทน")
    elif status in (400, 404):
        hint = f"OpenRouter ไม่รู้จักหรือเรียกโมเดล `{model}` ไม่ได้ ตรวจชื่อโมเดลของ agent นี้ (กด ✎ เพื่อแก้) หรือเลือกจาก dropdown"
    elif status is not None and status >= 500:
        hint = f"ฝั่งผู้ให้บริการของ `{model}` ขัดข้องชั่วคราว ลองใหม่อีกครั้ง หรือกด **Ask another agent**"
    elif status is None:
        hint = "เชื่อมต่ออินเทอร์เน็ตหรือ OpenRouter ไม่ได้ ตรวจการเชื่อมต่อแล้วลองใหม่"
    else:
        hint = "เรียก AI ไม่สำเร็จ ลองใหม่อีกครั้ง"
    code = f" (รหัส {status})" if status else ""
    return f"⚠️ {hint}{code}"
