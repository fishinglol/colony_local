# Hand-off — Colony Local (สำหรับเจ้าของโปรเจ็ค)
_เขียนเมื่อ 2026-10-12 · สถานะโค้ดอยู่ที่ branch `feature/openclaw-architecture` · **ยังไม่ได้ commit อะไรเลย**_

## สรุปสั้นๆ
Coucou (แอป Swift ใน `coco_local/`) คุยกับ OpenClaw Gateway **ตรงๆ** แล้ว สำหรับแชทส่วนตัวของ agent และแชทรวม (# mix) ทั้งสถานะสด, เครื่องมือที่ใช้, การอนุมัติ, คำสั่ง `/`, และไฟล์แนบ (ภาพ/PDF) OpenClaw เป็นคนกั้นโฟลเดอร์และถามอนุมัติเอง Colony เหลือหน้าที่: จัดการ workspace/ทีม, เลือกว่าใครตอบ (decider), เก็บประวัติร่วม, จัดโฟลเดอร์ความจำ/skill และเป็นเส้นทางสำรอง

## สิ่งที่ทำเสร็จ (และทดสอบแล้ว)
| เรื่อง | ที่อยู่ในโค้ด |
|---|---|
| Skill ต่อ agent (เลือกโฟลเดอร์ / GitHub / ลบ / ให้ AI ติดตั้งจากแชท) | `engine/openclaw.py` (`add_skills`, `add_skills_from_github`), `api/agents.py`, แท็บ Skills ใน `ColonySettingsView.swift` |
| ตัวเชื่อม Gateway (WebSocket + กุญแจอุปกรณ์ใน Keychain) | `coco_local/NotchBuddy/Sources/App/Colony/GatewayClient.swift` |
| รอบแชทแบบ native (prepare → Gateway → finish) | `colony/core/native_turn.py`, `ColonyStore.runDirect` |
| # mix ผ่าน Gateway (decider อยู่ใน prepare) | `native_turn.prepare` |
| สิทธิ์/รั้วโฟลเดอร์/การอนุมัติโดย OpenClaw | `sessions.create {cwd, permissionMode}`; ปลั๊กอิน `engine/colony-gate/index.ts` ข้าม session `:native-` |
| เมนู `/` และไฟล์แนบภาพ/PDF | `GatewayClient.commands()`, `ColonyChatView.swift`, `native_turn.prepare` |
| สถานะสด + การ์ดอนุมัติใน Coucou | `ColonyStore`, `ApprovalView` (seam เล็กใน `IslandViewContent.swift`) |
| workspace ใหม่ได้โฟลเดอร์ของตัวเอง | `core/workspaces.py::_new_project_folder` (`PROJECTS_DIR`) |

เอกสารละเอียดอยู่ใน `activeContext.md` (สถานะ/เรื่องที่ค้าง), `systemPatterns.md` (สถาปัตยกรรม), `openclaw-capabilities.md` (การต่อ OpenClaw)

## วิธีรัน
```bash
cd ~/Desktop/Colony-Local
.venv/bin/colony --no-open          # เริ่ม Colony :8765 และ Gateway :18789 (รอ ~3 นาทีจนพร้อม)
.venv/bin/python -m pytest -q tests  # 152 ผ่าน
open <path ของ Coucou.app ที่ build แล้ว>
```
Build แอป: `cd coco_local/NotchBuddy && xcodebuild -scheme NotchBuddy -configuration Debug CODE_SIGNING_ALLOWED=NO build`
(เครื่องนี้ไม่มี xcodegen ไฟล์ใหม่ถูกเพิ่มใน `project.pbxproj` ด้วยสคริปต์ ถ้าติดตั้ง xcodegen ให้รันสร้างใหม่จาก `project.yml`)

## ต้องตัดสินใจ / ควรทำต่อ
1. **Commit**: ทุกอย่างยังไม่ได้ commit และ `coco_local/` เป็น repo แยก (untracked) ตัดสินใจว่าจะ vendor เข้ามาหรือเก็บแยก
2. **ความปลอดภัยของ Gateway**: ตั้ง `auth.mode=none` บน loopback โปรแกรมใดๆ ในเครื่องขอสิทธิ์แอดมินได้ ถ้าต้องการปิดช่องนี้ต้องตั้งรหัสผ่านแล้วให้แอปใช้รหัสนั้น
3. **Gateway ตายแล้วไม่ restart เอง** (watchdog ยังไม่ทำ) restart `colony` เพื่อแก้
4. **เส้นทางสำรอง** (`POST /api/messages` + colony-gate) ยังอยู่ เพราะหน้าเว็บ/Tauri ยังใช้ ถ้าจะตัดทิ้งต้องให้สองตัวนั้นมีตัวเชื่อม Gateway ของตัวเอง
5. **workspace "my business" ไม่มีโฟลเดอร์แล้ว** (ลบ `~/Desktop/my-business` ตามที่สั่ง) ตั้งใหม่ถ้าต้องการให้ agent แก้ไฟล์/รันคำสั่ง
6. Jev ฟรี = 1 คำขอ/นาที ถ้า # mix ช้าหรือเลือกผิด ให้เติมเครดิตหรือใช้ `JEV_MODEL=jev-1.13`

## ข้อควรระวัง (เคยทำให้เสียเวลา)
- หลัง restart Colony ต้องรอ ~3 นาที Gateway ถึงรับการเชื่อมต่อได้ (ก่อนหน้านั้นจะเห็น "Connection reset")
- ไบนารีทดสอบ Swift ที่คอมไพล์ใหม่ค้างที่ Keychain prompt ให้ใช้สำเนาที่เก็บกุญแจเป็นไฟล์
- ถ้าโฟลเดอร์ตั้งไว้ agent เขียนไฟล์ความจำร่วมเองไม่ได้ (นอกรั้ว) Colony จดให้เมื่อผู้ใช้สั่ง "จำไว้"
- ผลของคำสั่ง `/` ไม่ถูกส่งเป็นบริบทให้ agent อื่น (`drop_commands`) ถ้าเห็น agent พูดตามผล `/status` ให้ตรวจที่นี่
- หน้าเว็บของ OpenClaw (:18789/) เปิดไม่ได้ (503) ไม่กระทบแอป
- Skill ที่ติดตั้งมาก (เช่น 13 ตัว) เพิ่มรายการใน prompt ของ decider ถ้า decider เลือกผิด ให้ลดจำนวน

## ที่ยังไม่ได้ยืนยัน
- การไล่ใช้ทุกหน้าของ Coucou แบบ manual (ทดสอบผ่านสคริปต์ Swift/Node กับ Gateway จริง และภาพหน้าจอที่คุณส่ง)
- ความจำในโหมด "มีโฟลเดอร์" ผ่านแอปจริง และ # mix ที่หลาย agent ใช้โฟลเดอร์เดียวกัน
- ผลกับโมเดลอื่นนอกจาก gemma4:31b / gpt-oss:20b / nemotron (nemotron-3-nano มักไม่เรียกเครื่องมือ)
- Release build ต้องมี signing profile (ที่นี่ไม่มี)
