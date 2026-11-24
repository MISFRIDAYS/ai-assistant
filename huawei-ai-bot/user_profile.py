"""ข้อมูลส่วนตัวของเจ้าของเครื่อง สำหรับกรอกแบบฟอร์ม — เก็บในเครื่องนี้เท่านั้น ไม่ส่งให้ AI

- จับคู่ช่องในฟอร์มกับข้อมูลด้วยกฎในเครื่อง (ไม่ต้องให้ AI เห็นข้อมูลจริง)
- ไม่เก็บ: รหัสผ่าน, OTP, เลขบัตรเครดิต, CVV, PIN (ช่องพวกนี้จะถามทุกครั้ง)
- ไฟล์ data/profile.json ตั้งสิทธิ์ให้อ่านได้เฉพาะ Termux (600)

สั่ง: "จำข้อมูลของฉัน ชื่อ สมชาย" / "ข้อมูลของฉัน เบอร์ 0812345678" / /profile / "ลบข้อมูลของฉัน"
"""
import json
import os
import re

import config

# key → (ชื่อไทยที่แสดง, คำที่ใช้จับคู่กับช่องในฟอร์ม)
FIELDS = {
    "first_name": ("ชื่อ", r"ชื่อจริง|^ชื่อ$|^ชื่อ\s|first\s*name|given\s*name|^name$|ชื่อ\s*\(|fname"),
    "last_name": ("นามสกุล", r"นามสกุล|last\s*name|surname|family\s*name|lname"),
    "full_name": ("ชื่อ-นามสกุล", r"ชื่อ\s*[-–/]?\s*(และ\s*)?นามสกุล|ชื่อเต็ม|full\s*name|your\s*name"),
    "nickname": ("ชื่อเล่น", r"ชื่อเล่น|nick\s*name"),
    "phone": ("เบอร์โทร", r"เบอร์|โทรศัพท์|มือถือ|phone|mobile|tel\b|telephone"),
    "email": ("อีเมล", r"อีเมล|อีเมล์|e-?mail"),
    "address": ("ที่อยู่", r"ที่อยู่|address|บ้านเลขที่|street"),
    "subdistrict": ("ตำบล/แขวง", r"ตำบล|แขวง|sub-?district"),
    "district": ("อำเภอ/เขต", r"อำเภอ|เขต|district|amphoe"),
    "province": ("จังหวัด", r"จังหวัด|province|state"),
    "zipcode": ("รหัสไปรษณีย์", r"ไปรษณีย์|zip|postal|post\s*code"),
    "birthday": ("วันเกิด", r"วันเกิด|วัน\s*/?\s*เดือน\s*/?\s*ปีเกิด|birth|dob|date of birth"),
    "gender": ("เพศ", r"เพศ|gender|sex"),
    "occupation": ("อาชีพ", r"อาชีพ|occupation|job\s*title|position|ตำแหน่ง"),
    "company": ("บริษัท/ที่ทำงาน", r"บริษัท|ที่ทำงาน|company|organi[sz]ation|employer"),
    "line_id": ("LINE ID", r"line\s*id|ไลน์\s*ไอดี|ไอดีไลน์"),
}
# ช่องอ่อนไหว: ไม่เก็บ ไม่เดา ถามผู้ใช้ทุกครั้ง
SENSITIVE = re.compile(r"รหัสผ่าน|password|passcode|pin\b|otp|รหัส\s*otp|รหัสยืนยัน|verification code|"
                       r"บัตรเครดิต|เลขบัตร|card\s*number|cvv|cvc|security code|วันหมดอายุบัตร|expir", re.I)
_SAY = {v[0]: k for k, v in FIELDS.items()}
_SAY.update({"ชื่อจริง": "first_name", "เบอร์": "phone", "เบอร์โทรศัพท์": "phone", "มือถือ": "phone", "เมล": "email",
             "อีเมล์": "email", "เขต": "district", "อำเภอ": "district", "ตำบล": "subdistrict", "แขวง": "subdistrict",
             "ไปรษณีย์": "zipcode", "ไลน์": "line_id", "ไอดีไลน์": "line_id", "ที่ทำงาน": "company", "บริษัท": "company"})


def _path():
    return os.path.join(config.DATA_DIR, "profile.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(d):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(_path(), 0o600)
    except OSError:
        pass


def set_field(key, value):
    if key not in FIELDS or not value:
        return False
    d = load()
    d[key] = value.strip()
    if key in ("first_name", "last_name") and d.get("first_name") and d.get("last_name"):
        d.setdefault("full_name", f"{d['first_name']} {d['last_name']}")
    save(d)
    return True


def value_for(label):
    """ช่องในฟอร์ม (ป้ายชื่อ/คำใบ้) → (key, ค่าที่จำไว้) / ("sensitive", None) / (None, None)"""
    lab = (label or "").strip().lower()
    if not lab:
        return None, None
    if SENSITIVE.search(lab):
        return "sensitive", None
    d = load()
    order = ["full_name", "last_name", "nickname", "first_name"] + [k for k in FIELDS
                                                                     if k not in ("full_name", "last_name", "nickname", "first_name")]
    for k in order:
        if re.search(FIELDS[k][1], lab, re.I):
            v = d.get(k)
            if k == "full_name" and not v and d.get("first_name"):
                v = f"{d['first_name']} {d.get('last_name', '')}".strip()
            return k, v
    return None, None


def _mask(v):
    v = str(v)
    return v if len(v) <= 3 else v[:2] + "•" * (len(v) - 4) + v[-2:]


def show():
    d = load()
    if not d:
        return ("🔒 ยังไม่ได้บันทึกข้อมูลส่วนตัว\nบันทึกได้แบบนี้: \"จำข้อมูลของฉัน ชื่อ สมชาย\" / "
                "\"จำข้อมูลของฉัน เบอร์ 0812345678\" / \"จำข้อมูลของฉัน อีเมล a@b.com\"\n"
                "(เก็บในเครื่องนี้เท่านั้น ไม่ส่งให้ AI · ไม่เก็บรหัสผ่าน/บัตรเครดิต/OTP)")
    lines = ["🔒 ข้อมูลของคุณที่ใช้กรอกฟอร์ม (เก็บในเครื่องนี้เท่านั้น):"]
    for k, (th, _) in FIELDS.items():
        if d.get(k):
            lines.append(f"• {th}: {_mask(d[k])}")
    lines.append("\nแก้: \"จำข้อมูลของฉัน <หัวข้อ> <ค่า>\" · ลบทั้งหมด: \"ลบข้อมูลของฉัน\"")
    return "\n".join(lines)


_SET = re.compile(r"^(?:จำ|บันทึก|ตั้ง)?\s*ข้อมูล(?:ส่วนตัว)?(?:ของ)?(?:ฉัน|ผม|เรา|หนู)\s*[:：]?\s*(?P<rest>.+)$")
_DEL = re.compile(r"^(?:ลบ|ลืม|ล้าง)\s*ข้อมูล(?:ส่วนตัว)?(?:ของ)?(?:ฉัน|ผม|เรา|หนู)")
_SHOW = re.compile(r"^(?:ดู|แสดง)?\s*ข้อมูล(?:ส่วนตัว)?(?:ของ)?(?:ฉัน|ผม|เรา|หนู)\s*(?:มีอะไรบ้าง|หน่อย)?$")


def handle_text(text):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    if not t:
        return None
    if _DEL.match(t):
        try:
            os.remove(_path())
        except OSError:
            pass
        return "🗑️ ลบข้อมูลส่วนตัวที่ใช้กรอกฟอร์มแล้ว"
    if _SHOW.match(t):
        return show()
    m = _SET.match(t)
    if not m:
        return None
    rest = m.group("rest")
    if SENSITIVE.search(rest):
        return "🔒 ข้อมูลนี้ (รหัสผ่าน/OTP/บัตรเครดิต) ไม่เก็บเพื่อความปลอดภัย — เวลากรอกฟอร์มจะถามทุกครั้ง"
    saved = []
    for part in re.split(r"\s*[,\n]\s*", rest):          # "ชื่อ สมชาย, เบอร์ 081..."
        for say in sorted(_SAY, key=len, reverse=True):
            mm = re.match(rf"^{re.escape(say)}\s*(?:คือ|=|:|เป็น)?\s*(?P<v>.+)$", part.strip(), re.I)
            if mm:
                key = _SAY[say]
                if set_field(key, mm.group("v")):
                    saved.append(FIELDS[key][0])
                break
    if not saved:
        return ("บอกหัวข้อด้วยนะ เช่น \"จำข้อมูลของฉัน ชื่อ สมชาย\" (หัวข้อที่มี: "
                + ", ".join(v[0] for v in FIELDS.values()) + ")")
    return f"🔒 บันทึกแล้ว: {', '.join(saved)} (เก็บในเครื่องนี้เท่านั้น)"
