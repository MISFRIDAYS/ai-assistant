"""สั่งต่อในแอปที่เปิดอยู่ (ไม่ต้องบอกชื่อแอปซ้ำ)

อยู่ใน YouTube/Spotify:  "เปิดเพลงอื่น" · "เพลงต่อไป" · "หยุดเพลง" · "เล่นต่อ" · "เปิดเพลง X" · "เซิร์ช X"
อยู่ในห้องแชท LINE/IG/…:  "พิมพ์ว่า X" · "ตอบว่า X" · "บอกเขาว่า X"
อยู่ใน Shopee/TikTok/…:   "หา X" / "ค้นหา X"
และ "เปิด X ใน youtube" (ไม่ต้องมีคำว่าเพลง/คลิป)
ถ้าสั่งจากหน้าแอปผู้ช่วยเอง → ย้ายแอปผู้ช่วยไปด้านหลังก่อน แล้วดูว่าแอปที่ค้างอยู่ข้างหลังคืออะไร
"""
import re
import time

import config

OWN = "com.aibot.assistant"
MEDIA = {"com.google.android.youtube": "youtube", "com.google.android.apps.youtube.music": "youtube music",
         "com.spotify.music": "spotify"}
SEARCHABLE = {"com.shopee.th": "shopee", "com.lazada.android": "lazada", "com.ss.android.ugc.trill": "tiktok",
              "com.zhiliaoapp.musically": "tiktok", "com.facebook.katana": "facebook", "com.twitter.android": "x",
              "com.android.chrome": "chrome", "com.google.android.apps.maps": "maps", **MEDIA}
import chat_apps  # noqa: E402

CHAT = {p: k for p, k in chat_apps.PKG_APP.items() if k in chat_apps.DM_APPS}

_POL = r"(?:\s*(?:ให้หน่อย|หน่อย|ให้ที|ที|ครับ|ค่ะ|คะ|นะ|ด้วย|เลย|ซิ|สิ))*\s*$"
_NEXT = re.compile(r"^(?:(?:ช่วย)?\s*(?:เปิด|เล่น|ขอ|เปลี่ยน)?\s*(?:เป็น)?\s*(?:เพลง|คลิป|อัน)\s*(?:อื่น|ต่อไป|ถัดไป|ใหม่)|"
                   r"(?:ข้าม|สกิป|skip|next)\s*(?:เพลง|คลิป)?|(?:เพลง|คลิป)?\s*(?:ต่อไป|ถัดไป))" + _POL, re.I)
_PREV = re.compile(r"^(?:(?:ย้อน|กลับ)\s*(?:ไป)?\s*(?:เพลง|คลิป)\s*(?:ก่อนหน้า|ที่แล้ว)|(?:เพลง|คลิป)\s*(?:ก่อนหน้า|ที่แล้ว))" + _POL, re.I)
_PAUSE = re.compile(r"^(?:(?:หยุด|พัก|ปิด)\s*(?:เพลง|คลิป|วิดีโอ)\s*(?:ก่อน|ชั่วคราว)?|pause)" + _POL, re.I)
_RESUME = re.compile(r"^(?:เล่นต่อ|เปิดต่อ|ฟังต่อ|ดูต่อ|resume|play)" + _POL, re.I)
_PLAYQ = re.compile(r"^(?:ช่วย)?\s*(?:เปิด|เล่น|ฟัง|ดู|ขอ)\s*(?:เพลง|คลิป|วิดีโอ|วีดีโอ|mv|เอ็มวี)\s*(?:ของ)?\s*(?P<q>.+?)" + _POL, re.I)
_SEARCHQ = re.compile(r"^(?:ช่วย)?\s*(?:หา|ค้นหา|ค้น|เซิร์ช|เสิร์ช|search)\s*(?:คำว่า|เรื่อง)?\s*(?P<q>.+?)" + _POL, re.I)
_IN_MEDIA = re.compile(r"^(?:ช่วย)?\s*(?:เปิด|เล่น|ฟัง|ดู)\s*(?P<q>.+?)\s*(?:ใน|บน|ที่|ทาง)\s*(?:แอป)?\s*"
                       r"(?P<app>ยูทูป|ยูทูบ|youtube|spotify|สปอติฟาย|youtube music|ยูทูปมิวสิค)" + _POL, re.I)
_TYPE = re.compile(r"^(?:ช่วย)?\s*(?:พิมพ์|ตอบ|ตอบกลับ|บอก(?:เขา|เธอ|มัน)?|ส่ง)\s*(?:ข้อความ)?\s*(?:กลับ)?\s*(?:ไป)?\s*"
                   r"(?:ว่า|ไปว่า)\s*(?P<q>.+)$|^(?:ช่วย)?\s*พิมพ์\s+(?P<q2>.+)$", re.I)
_MEDIA_KEY = {"next": 87, "prev": 88, "pause": 127, "play": 126}


def current(reveal=True):
    """package ของแอปที่ผู้ใช้กำลังใช้ (ถ้าสั่งจากหน้าผู้ช่วย → ดูแอปที่อยู่ข้างหลัง)"""
    if config.MOCK_PHONE or not config.ANDROID_APP:
        return None
    import phone_tools
    fg = phone_tools._fg() or ""
    if fg == OWN and reveal:
        import android_shim
        android_shim.bridge().away()
        time.sleep(0.9)
        fg = phone_tools._fg() or ""
    return fg if fg and fg != OWN else None


def _key(code):
    import screen_tools
    screen_tools.adb_shell(["input", "keyevent", str(code)])


def _media(t):
    if _NEXT.match(t):
        return "next"
    if _PREV.match(t):
        return "prev"
    if _PAUSE.match(t):
        return "pause"
    if _RESUME.match(t):
        return "play"
    return None


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    if not t or len(t) > 160:
        return None
    import app_skills
    m = _IN_MEDIA.match(t)
    if m and not re.search(r"เพลง|คลิป|วิดีโอ|วีดีโอ", m.group("q")):      # มีคำว่าเพลง → app_skills ทำอยู่แล้ว
        return app_skills.play(m.group("q"), m.group("app"), ctx)
    act = _media(t)
    pq = _PLAYQ.match(t)
    sq = _SEARCHQ.match(t) if not re.search(r"\s(?:ใน|บน)\s*\S+$", t) else None   # "หา X ใน shopee" → app_skills
    ty = _TYPE.match(t) if not re.match(r"^ส่ง\S*\s*(?:ข้อความ)?\s*หา", t) else None   # "ส่งหาแม่ว่า" → ระบบส่งข้อความ
    if not (act or pq or sq or ty):
        return None
    if act:                                          # ปุ่มสื่อ ใช้ได้ทั้งเครื่อง ไม่ต้องสลับหน้า
        if current(reveal=False) or config.ANDROID_APP:
            _key(_MEDIA_KEY[act])
            return {"next": "⏭️ เพลงถัดไป", "prev": "⏮️ ย้อนเพลง", "pause": "⏸️ หยุดชั่วคราว", "play": "▶️ เล่นต่อ"}[act]
        return None
    if ty:                                           # พิมพ์ในห้องแชทที่ค้างไว้ (สั่งจากหน้าผู้ช่วยก็ได้)
        pkg = current(reveal=True)
        if pkg and (pkg.startswith("cn.wps") or pkg.startswith("com.kingsoft") or "notepad" in pkg or "keep" in pkg):
            import screen_tools                          # พิมพ์ในเอกสาร/โน้ตที่เปิดอยู่ (ไม่กดส่ง)
            msg = (ty.group("q") or ty.group("q2") or "").strip()
            r = screen_tools.type_text({"text": msg}, ctx)
            return "✍️ พิมพ์ในเอกสารแล้ว" if not str(r).startswith("ERROR") else str(r)
        if pkg in CHAT:
            import share_tools
            if share_tools.chat_open():
                msg = (ty.group("q") or ty.group("q2") or "").strip()
                return share_tools.send_here(msg, ctx) if msg else None
        return None
    pkg = current(reveal=False)                      # เปิดเพลง/ค้นหา: เฉพาะตอนอยู่ในแอปนั้นจริง (สั่งด้วยเสียง)
    if not pkg:
        return None
    if pq and pkg in MEDIA:
        return app_skills.play(pq.group("q"), MEDIA[pkg], ctx)
    if sq and pkg in SEARCHABLE:
        return app_skills.search(SEARCHABLE[pkg], sq.group("q"), ctx)
    return None
