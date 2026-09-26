"""Turn a provider failure into a message a normal person can act on (Thai, like the rest of the UI)."""
from ..llm.http import ProviderError


def explain(exc: ProviderError, model: str) -> str:
    status = exc.status
    if status == 429:
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
