"""จำว่าแต่ละคนคุยกันในแอปไหน — "ส่งข้อความหาภรรยา(คนเจก) ว่า…" ไม่ต้องบอกว่า instagram

เรียนรู้จาก: ส่งข้อความ/โทรสำเร็จ (น้ำหนักมาก) · แจ้งเตือนที่คนนั้นทักมา (น้ำหนักน้อย) · ผู้ใช้สอน "ภรรยาอยู่ในไอจี"
ข้อมูลอยู่ที่ data/contacts.json (ในเครื่อง)
"""
import json
import os
import re
import threading
import time

import config

_PATH = os.path.join(config.DATA_DIR, "contacts.json")
_lock = threading.RLock()
_db = {"d": None}
WEIGHT = {"sent": 5.0, "call": 5.0, "taught": 50.0, "notif": 1.0, "scan": 2.0}
import chat_apps  # noqa: E402

APP_KEYS = chat_apps.PKG_APP                 # package → ชื่อแอป (ตารางกลางอยู่ใน chat_apps.py)
APP_WORDS = chat_apps.WORDS                  # ชื่อแอป → คำเรียก regex


def norm(name):
    return re.sub(r"[\s\-_.()（）\[\]]+", "", (name or "").lower())


def _load():
    with _lock:
        if _db["d"] is None:
            try:
                with open(_PATH, encoding="utf-8") as f:
                    _db["d"] = json.load(f)
            except (OSError, ValueError):
                _db["d"] = {}
        return _db["d"]


def _save():
    with _lock:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_load(), f, ensure_ascii=False)
        os.replace(tmp, _PATH)


def learn(name, app, how="sent"):
    """จำว่าคนนี้อยู่ในแอปนี้"""
    app = APP_KEYS.get(app, app)
    k = norm(name)
    if not k or len(k) < 2 or not app or len(k) > 40:
        return
    with _lock:
        e = _load().setdefault(k, {"name": name.strip(), "apps": {}, "last": "", "t": 0})
        e["apps"][app] = round(e["apps"].get(app, 0) + WEIGHT.get(how, 1.0), 1)
        if how in ("sent", "call", "taught"):
            e["last"], e["name"] = app, name.strip()
        e["t"] = time.time()
        if len(_load()) > 3000:                           # ลบคนที่นานมากแล้ว
            for old in sorted(_load(), key=lambda x: _load()[x].get("t", 0))[:300]:
                _load().pop(old, None)
    if how not in ("notif", "scan"):
        _save()


def flush():
    _save()


def app_for(name):
    """แอปที่คุยกับคนนี้บ่อยที่สุด (หรือ None)"""
    d = _load()
    k = norm(name)
    if not k:
        return None
    e = d.get(k)
    if not e:                                             # ชื่อสั้น/ยาวกว่าที่จำ เช่น "ภรรยา" ↔ "ภรรยา(คนเจก)"
        cands = [v for kk, v in d.items() if len(k) >= 3 and (k in kk or kk in k)]
        if len(cands) != 1:
            return None
        e = cands[0]
    if e.get("last") and e["apps"].get(e["last"], 0) >= max(e["apps"].values()) * 0.5:
        return e["last"]
    return max(e["apps"], key=e["apps"].get) if e.get("apps") else None


def known_name(name):
    """ชื่อเต็มที่จำไว้ เช่น 'ภรรยา' → 'ภรรยา(คนเจก)'"""
    d = _load()
    k = norm(name)
    if k in d:
        return d[k]["name"]
    cands = [v["name"] for kk, v in d.items() if len(k) >= 3 and (k in kk or kk in k)]
    return cands[0] if len(cands) == 1 else None


APP_LABEL = {"line": "LINE", "instagram": "Instagram", "messenger": "Messenger", "facebook": "Facebook",
             "whatsapp": "WhatsApp", "telegram": "Telegram", "sms": "SMS", "discord": "Discord", "viber": "Viber",
             "wechat": "WeChat"}


def catalog(limit=300):
    """รายชื่อทุกคนที่จำได้ (ล่าสุดก่อน) + แอปที่คุย เรียงจากใช้บ่อย → ให้หน้าเลือกคำสั่ง/เสียงใช้"""
    out = []
    for e in sorted(_load().values(), key=lambda v: v.get("t", 0), reverse=True)[:limit]:
        apps = sorted((e.get("apps") or {}).items(), key=lambda x: x[1], reverse=True)
        if not apps:
            continue
        best = e.get("last") if e.get("last") in dict(apps) else apps[0][0]
        out.append({"name": e.get("name", ""), "best": best,
                    "apps": [{"app": a, "label": APP_LABEL.get(a, a), "score": sc} for a, sc in apps]})
    return out


def forget(name):
    with _lock:
        k = norm(name)
        hit = _load().pop(k, None)
    if hit:
        _save()
    return bool(hit)


_LIST = re.compile(r"^(ดู)?\s*(รายชื่อ|คน)\s*(ที่)?\s*(จำ|รู้จัก)(ไว้|ได้)?(ทั้งหมด)?(บ้าง)?|^ใคร(อยู่|คุย)(ใน)?แอปไหน(บ้าง)?",
                   re.I)
_FORGET = re.compile(r"^ลืม\s*(?:รายชื่อ|ชื่อ)?\s*(?P<n>.+?)\s*(?:ไป|ด้วย|ซะ)?\s*(?:นะ|ครับ|ค่ะ)?$")


_TEACH = re.compile(r"^(?:จำไว้ว่า)?\s*(?P<n>.+?)\s*(?:อยู่|คุย(?:กัน)?|ใช้|ติดต่อ)(?:ใน|ทาง|ผ่าน)\s*(?:แอป)?\s*(?P<a>" +
                    "|".join(APP_WORDS.values()) + r")\s*(?:นะ|น่ะ|ครับ)?$", re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip()
    if _LIST.search(t):
        cat = catalog()
        if not cat:
            return "ยังไม่ได้จำใครเลย — พอมีคนทักมาหรือสั่งส่งข้อความหาใคร ผู้ช่วยจะจำให้เอง"
        lines = [f"👥 จำได้ {len(cat)} คน (ล่าสุดก่อน):"]
        for c in cat[:25]:
            lines.append(f"• {c['name']} — " + ", ".join(a["label"] for a in c["apps"][:3]))
        if len(cat) > 25:
            lines.append(f"…และอีก {len(cat) - 25} คน (ดูทั้งหมดในปุ่ม 🧭 สั่งแบบเลือก → 👥 คนที่จำได้)")
        return "\n".join(lines)
    m = _FORGET.match(t)
    if m and norm(m.group("n")) in _load():
        forget(m.group("n"))
        return f"ลืม {m.group('n')} แล้ว"
    m = _TEACH.match(t)
    if not m:
        return None
    app = next(k for k, rx in APP_WORDS.items() if re.fullmatch(rx, m.group("a"), re.I))
    learn(m.group("n"), app, "taught")
    return f"👌 จำแล้ว — {m.group('n')} คุยใน {app} ครั้งหน้าสั่งแค่ \"ส่งหา {m.group('n')} ว่า…\" ได้เลย"
