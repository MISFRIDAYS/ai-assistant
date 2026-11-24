"""เมนูคำสั่งแบบกดเลือก: เลือกแอป → เลือกสิ่งที่จะทำ → กรอกช่องที่ต้องใช้ → ได้ประโยคคำสั่งภาษาไทย
(ประโยคที่ได้วิ่งผ่านระบบคำสั่งปกติ — ด่านยืนยัน/ความปลอดภัยทำงานเหมือนพิมพ์เอง)
"""
import json
import re

# ช่องกรอก: key → ป้ายในฟอร์ม
F = {"name": "ชื่อคน (เช่น แม่, ภรรยา)", "text": "ข้อความ", "q": "คำค้น", "topic": "เรื่อง",
     "place": "สถานที่", "song": "ชื่อเพลง/ศิลปิน", "page": "หน้าที่จะไป", "task": "สิ่งที่จะให้ทำ"}

_KINDS = [
    ("chat", r"line|naver|instagram|messenger|orca|facebook\.katana|whatsapp|telegram|discord|wechat|viber|"
             r"twitter|threads|com\.zhiliaoapp|tiktok|ไลน์|ไอจี|อินสตา|เฟส"),
    ("note", r"notepad|notes?\b|keep|memo|บันทึก|โน้ต"),
    ("office", r"wps|office|docs|word|excel|sheets|slides|powerpoint"),
    ("music", r"spotify|joox|music|เพลง|soundcloud|deezer|apple\.music"),
    ("video", r"youtube|netflix|viu|wetv|iqiyi|bilibili|disney|vimeo|video"),
    ("browser", r"chrome|browser|firefox|opera|edge|brave|duckduckgo|เบราว์เซอร์"),
    ("maps", r"maps|petal\.?maps|waze|grab|bolt|lineman|แผนที่"),
    ("shop", r"shopee|lazada|tiktok\.shop|amazon|temu|aliexpress"),
    ("camera", r"camera|กล้อง"),
    ("gallery", r"gallery|photos|แกลเลอรี|รูปภาพ"),
    ("settings", r"^com\.android\.settings$|settings|ตั้งค่า"),
]
_SOCIAL_FEED = re.compile(r"instagram|facebook\.katana|tiktok|zhiliaoapp|twitter|threads", re.I)
_CALLABLE = re.compile(r"line|naver|messenger|orca|whatsapp|telegram|facebook|instagram|discord|wechat|viber", re.I)


def kind_of(pkg, label="", cat=""):
    s = f"{pkg} {label}".lower()
    for k, rx in _KINDS:
        if re.search(rx, s, re.I):
            return k
    return {"audio": "music", "video": "video", "maps": "maps", "productivity": "office",
            "image": "gallery", "social": "chat"}.get(cat or "", "other")


def _a(title, template, *fields):
    return {"title": title, "template": template, "fields": [{"key": f, "label": F[f]} for f in fields]}


def actions(pkg, label, cat=""):
    """ตัวเลือกของแอปนี้ — template ใช้ {app} + ช่องกรอก"""
    k = kind_of(pkg, label, cat)
    out = [_a("📲 เปิดแอป", "เปิด {app}")]
    if k == "chat":
        out += [_a("💬 ไปที่แชท", "ไปที่แชท {name} ใน {app}", "name"),
                _a("✉️ ส่งข้อความ", "ส่งข้อความหา {name} ใน {app} ว่า {text}", "name", "text"),
                _a("📖 อ่านแชทล่าสุด", "อ่านแชทล่าสุดของ {name} ใน {app}", "name")]
        if _CALLABLE.search(pkg):
            out += [_a("📞 โทร", "โทรหา {name} ใน {app}", "name"),
                    _a("🎥 วิดีโอคอล", "วิดีโอคอลหา {name} ใน {app}", "name")]
        if _SOCIAL_FEED.search(pkg):
            out += [_a("📰 สรุปฟีด", "สรุปฟีด {app}"), _a("🔎 ค้นหา", "ค้นหา {q} ใน {app}", "q")]
    elif k == "note":
        out += [_a("📝 จดโน้ตใหม่", "จดโน้ตว่า {text}", "text"),
                _a("✍️ ให้ AI เขียนโน้ต", "เขียนโน้ตเรื่อง {topic}", "topic")]
    elif k == "office":
        out += [_a("📄 สร้างไฟล์ Word", "สร้างเอกสารเรื่อง {topic}", "topic"),
                _a("📊 ทำสไลด์", "ทำสไลด์เรื่อง {topic}", "topic"),
                _a("🗒️ เอกสารเปล่า", "เปิด {app} แล้วสร้างเอกสารใหม่")]
    elif k == "music":
        out += [_a("▶️ เล่นเพลง", "เปิดเพลง {song} ใน {app}", "song"),
                _a("⏭️ เพลงถัดไป", "เพลงถัดไป"), _a("⏸️ หยุด/เล่นต่อ", "หยุดเพลง")]
    elif k == "video":
        out += [_a("🔎 ค้นหาคลิป", "ค้นหา {q} ใน {app}", "q"), _a("▶️ เปิดคลิป", "เปิด {q} ใน {app}", "q")]
    elif k == "browser":
        out += [_a("🔎 ค้นเว็บ", "ค้นหา {q} ใน {app}", "q")]
    elif k == "maps":
        out += [_a("🧭 นำทาง", "นำทางไป {place} ใน {app}", "place"),
                _a("📍 ค้นหาสถานที่", "ค้นหา {place} ใน {app}", "place")]
    elif k == "shop":
        out += [_a("🔎 ค้นหาสินค้า", "ค้นหา {q} ใน {app}", "q"), _a("🛒 ดูตะกร้า", "เปิด {app} ไปที่ตะกร้า")]
    elif k == "camera":
        out += [_a("📷 ถ่ายรูป", "ถ่ายรูป"), _a("👀 ดูว่าเห็นอะไร", "เห็นอะไรบ้าง")]
    elif k == "gallery":
        out += [_a("🖼️ ดูรูปล่าสุด", "เปิดรูปล่าสุดใน {app}")]
    elif k == "settings":
        out += [_a("⚙️ ไปหน้าตั้งค่า", "เปิดหน้าตั้งค่า {page}", "page")]
    out += [_a("🧭 ไปหน้า…", "เปิด {app} ไปที่หน้า {page}", "page"),
            _a("✨ ให้ทำอย่างอื่น", "ใน {app} {task}", "task"),
            _a("📚 ศึกษาแอปนี้", "ศึกษาแอป {app}"),
            _a("✖️ ปิดแอป", "ปิดแอป {app}")]
    return out


_TOP = re.compile(r"line|instagram|messenger|facebook|youtube|tiktok|notepad|wps|chrome|spotify|shopee|lazada|maps", re.I)


def build(pkg, title_or_index, values):
    """สร้างประโยคคำสั่งจากตัวเลือกที่กด (ใช้ทดสอบ/เรียกจาก Kotlin ได้)"""
    import app_brain
    e = app_brain.apps().get(pkg) or {}
    label = e.get("label") or pkg
    acts = actions(pkg, label, e.get("cat", ""))
    a = acts[title_or_index] if isinstance(title_or_index, int) else next(x for x in acts if x["title"] == title_or_index)
    vals = {k: (values or {}).get(k, "").strip() for k in F}
    return re.sub(r"\s+", " ", a["template"].format(app=label, **vals)).strip()


def catalog():
    """JSON ให้หน้าแอป: [{pkg, label, kind, actions}] แอปยอดนิยมขึ้นก่อน (ไม่รวมแอประบบที่ไม่มีหน้าจอ)"""
    import app_brain
    out = []
    for pkg, e in app_brain.apps().items():
        label = e.get("label") or pkg
        if e.get("sys") and not re.search(r"camera|gallery|settings|notepad|music|video|browser|clock|calendar",
                                          pkg, re.I):
            continue
        out.append({"pkg": pkg, "label": label, "kind": kind_of(pkg, label, e.get("cat", "")),
                    "actions": actions(pkg, label, e.get("cat", ""))})
    out.sort(key=lambda a: (0 if _TOP.search(a["pkg"]) else 1, a["label"].lower()))
    return json.dumps(out, ensure_ascii=False)
