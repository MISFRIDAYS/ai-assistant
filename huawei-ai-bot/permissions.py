"""นโยบายขออนุญาต: อะไรทำได้เลย อะไรต้องถามก่อน

- ส่งข้อความ/โพสต์/แชร์/คอมเมนต์  → ทำได้เลย (AUTO_SEND=1) ยกเว้นผู้ใช้บอก "รอคำสั่งก่อนส่ง"
- โทร/วิดีโอคอล                     → ถามก่อน (AUTO_CALL=0) ปรับได้
- จ่ายเงิน/ซื้อ/โอน/ลบ              → ถามก่อนเสมอ
"""
import re

import config

ALWAYS = ("ชำระ", "จ่าย", "pay", "ซื้อ", "buy", "สั่งซื้อ", "order", "checkout", "ลบ", "delete", "remove",
          "โอน", "transfer", "ถอนเงิน", "withdraw", "ยกเลิกบัญชี", "log out", "ออกจากระบบ")
CALLS = ("โทร", "call", "วิดีโอคอล", "video call", "วีดีโอคอล")
MESSAGING = ("ส่ง", "send", "โพสต์", "post", "แชร์", "share", "เผยแพร่", "publish", "คอมเมนต์", "comment",
             "ตอบกลับ", "reply", "อัปโหลด", "upload", "ยืนยัน", "confirm", "ทวีต", "tweet", "story", "สตอรี่")

# ผู้ใช้บอกว่า "อย่าเพิ่งส่ง รอฟังคำสั่งก่อน"
HOLD = re.compile(r"(รอ\s*(ฟัง)?\s*คำสั่ง|อย่าเพิ่ง\s*(ส่ง|โพสต์|แชร์|กด)|ยังไม่ต้อง\s*(ส่ง|โพสต์|กด)|"
                  r"ไม่ต้อง\s*ส่ง|ถาม(ผม|ฉัน|หนู|เรา)?\s*ก่อน|รอ(ผม|ฉัน)?\s*ก่อน|ให้ดูก่อน|เดี๋ยว(ผม|ฉัน)?\s*(สั่ง|กด)\s*เอง|"
                  r"ยังไม่ส่ง|พิมพ์ไว้\s*ก่อน|แค่พิมพ์)")

TOOL_CATEGORY = {"send_sms": "message", "make_call": "call", "type_text_enter": "message"}


def wants_hold(text):
    return bool(HOLD.search(text or ""))


def category(label):
    low = (label or "").lower()
    if any(k in low for k in ALWAYS):
        return "always"
    if any(k in low for k in CALLS):
        return "call"
    if any(k in low for k in MESSAGING):
        return "message"
    return None


def need_confirm(ctx, cat):
    """ต้องถามผู้ใช้ก่อนไหม"""
    if cat is None or ctx is None:
        return False
    hold = getattr(ctx, "hold", False)
    if cat == "always":
        return True
    if cat == "message":
        if getattr(ctx, "send_ok", None):
            return False                   # อ่านทวนข้อความแล้วผู้ใช้ตอบยืนยันแล้ว
        if getattr(ctx, "via_voice", False) and getattr(config, "VOICE_CONFIRM_SEND", True):
            return True                    # สั่งด้วยเสียงอาจฟังผิด → ถามก่อนส่งเสมอ
        return hold or not config.AUTO_SEND
    if cat == "call":
        return hold or not config.AUTO_CALL
    return True
