"""แก้ปัญหาเองเมื่อทำไม่สำเร็จ — ระบบสำเร็จรูป (สร้างเอกสาร/โน้ต/โทร/เข้าแชท/ตั้งค่า) ล้ม → ส่งต่อให้ AI ลองวิธีอื่นทันที
แทนที่จะบอกผู้ใช้ว่า "ทำไม่ได้" ตั้งแต่ครั้งแรก
"""
import re
import time

ACTION_MODS = {"app_tasks", "social", "inapp", "device", "app_skills", "media", "screen_context"}
_FAIL = re.compile(r"^(ERROR|❗|❌)|ไม่เจอ|หาไม่|ไม่สำเร็จ|ไม่ได้ \(|ทำไม่ได้|ยังไม่ถึง|ไม่พบปุ่ม|เข้า.*ไม่ได้", re.I)
_OK_HINT = re.compile(r"✅|แล้ว \(|เสร็จแล้ว|เรียบร้อย")
_state = {"t": 0.0, "said": "", "why": "", "mod": ""}

PLAYBOOK = (
    "[โหมดแก้ปัญหา] ระบบสำเร็จรูปลองทำคำสั่งนี้แล้วไม่สำเร็จ: {why}\n"
    "อย่าเพิ่งยอมแพ้ ให้แก้ปัญหาเองทีละขั้นด้วยเครื่องมือ:\n"
    "0) วิธีที่แม่นที่สุด: เรียก screen_task(goal=เป้าหมายเต็มประโยค) ให้ระบบมองภาพหน้าจอจริงแล้วทำทีละขั้นเอง\n"
    "1) read_screen ดูว่าตอนนี้อยู่หน้าไหน มีปุ่มชื่ออะไรจริงๆ (ไอคอนที่ขึ้น ≈ คือชื่อที่เรียนรู้ไว้)\n"
    "2) มีป๊อปอัป/โฆษณา/หน้าต้อนรับบัง → แตะ ข้าม/ปิด/ภายหลัง ก่อน\n"
    "3) หาปุ่มไม่เจอ → swipe เลื่อนหา / tap_visual(target=คำบรรยายรูปร่างปุ่ม) / press_key back แล้วเริ่มจากหน้าก่อน\n"
    "4) อยู่ผิดหน้า → open_app(app, fresh=true) เริ่มจากหน้าแรกของแอปใหม่\n"
    "5) แอปไม่ให้พิมพ์ → ใช้ทางอื่น (แชร์ข้อความ/สร้างไฟล์แล้วเปิด) หรือบอกผู้ใช้ให้วางจากคลิปบอร์ด\n"
    "ลองได้ไม่เกิน 6 ขั้น ถ้ายังไม่ได้ บอกสั้นๆ ว่าติดตรงไหน และเสนอทางเลือกที่ทำได้"
)


def is_failure(mod_name, text):
    if mod_name not in ACTION_MODS or not isinstance(text, str):
        return False
    head = text[:160]
    return bool(_FAIL.search(head)) and not _OK_HINT.search(head[:40])


def note(mod_name, said, why):
    _state.update(t=time.time(), said=(said or "").strip(), why=str(why)[:300], mod=mod_name)
    print(f"[recovery] {mod_name} ทำไม่สำเร็จ → ให้ AI แก้ปัญหาต่อ: {str(why)[:100]}", flush=True)


def pending(said):
    """คำสั่งนี้เพิ่งล้มไป (ยังไม่ส่งต่อ AI) → ข้ามระบบสำเร็จรูป ไม่ลองซ้ำให้เสียเวลา"""
    s = re.sub(r"\[[^\]]*\]", " ", said or "").strip()
    return bool(_state["why"]) and time.time() - _state["t"] < 20 and bool(s) and \
        (_state["said"] in s or s in _state["said"])


def consume(said):
    """คำสั่งนี้เพิ่งล้มในระบบสำเร็จรูปไหม → ข้อความโหมดแก้ปัญหา (ครั้งเดียว)"""
    if time.time() - _state["t"] > 20 or not _state["why"]:
        return ""
    s = re.sub(r"\[[^\]]*\]", " ", said or "").strip()
    if _state["said"] and s and _state["said"] not in s and s not in _state["said"]:
        return ""
    why = _state["why"]
    _state.update(t=0.0, why="")
    return PLAYBOOK.format(why=why)
