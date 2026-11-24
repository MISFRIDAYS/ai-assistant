"""รูทีนด้วยเสียง: พูดประโยคเดียว → ผู้ช่วยทำหลายอย่างต่อกัน
- ใช้: "โหมดนอน" · "เริ่มรูทีนออกจากบ้าน" · "รูทีนตื่นนอน"
- สร้างเอง: "สร้างรูทีน นอน: ตั้งปลุก 6 โมง แล้ว เปิดโหมดห้ามรบกวน แล้ว ลดแสงจอ"
           "จำไว้นะ ถ้าบอกว่า ถึงบ้าน ให้ เปิดไวไฟ แล้ว เปิดเพลงสบายๆ"
- ดู/ลบ: "มีรูทีนอะไรบ้าง" · "รูทีนนอนมีอะไรบ้าง" · "ลบรูทีน นอน"
แต่ละขั้นเป็นคำสั่งธรรมดา: ทำด้วยคำสั่งด่วนก่อน (เร็ว ไม่ใช้ AI) ทำไม่ได้ค่อยให้ AI ทำ
ข้อมูล: data/routines.json
"""
import json
import os
import re
import threading
import time

import config

DEFAULTS = {
    "นอน": ["เปิดโหมดห้ามรบกวน", "ลดแสงจอ", "พรุ่งนี้มีนัดอะไรบ้าง"],
    "ตื่นนอน": ["ปิดโหมดห้ามรบกวน", "สรุปวันนี้"],
    "ออกจากบ้าน": ["อากาศวันนี้", "วันนี้มีนัดอะไรบ้าง", "แบตเหลือเท่าไหร่"],
    "ถึงบ้าน": ["เปิดไวไฟ", "มีใครทักมาบ้าง"],
    "ทำงาน": ["เปิดโหมดห้ามรบกวน", "วันนี้มีนัดอะไรบ้าง"],
}
MAX_STEPS = 8
_depth = threading.local()


def _p():
    try:
        import voice_profile
        return voice_profile.pol()
    except Exception:  # noqa: BLE001
        return "ครับ"


def _path():
    return os.path.join(config.DATA_DIR, "routines.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {k: list(v) for k, v in DEFAULTS.items()}


def save(d):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def _key(name):
    n = re.sub(r"^(?:โหมด|รูทีน|ตอน|เวลา)\s*", "", (name or "").strip())
    return re.sub(r"\s+", "", n).strip(" \"'“”:")


def split_steps(body):
    """'ตั้งปลุก 6 โมง แล้ว เปิดห้ามรบกวน, ลดแสงจอ' → ['ตั้งปลุก 6 โมง', 'เปิดห้ามรบกวน', 'ลดแสงจอ']"""
    parts = re.split(r"\s*(?:,|，|;|\n|แล้วก็|จากนั้น(?:ก็)?|ต่อด้วย|และ(?=\s)|\sแล้ว(?:\s|$)|ตามด้วย)\s*", body or "")
    out = []
    for s in parts:
        s = re.sub(r"^(?:ให้|ก็|ช่วย)\s*", "", s.strip(" .")).strip()
        s = re.sub(r"\s*(?:ด้วย|นะ|ครับ|ค่ะ|คะ)+$", "", s).strip()
        if len(s) >= 2:
            out.append(s)
    return out[:MAX_STEPS]


# ================================================================ ทำรูทีน

def _do_step(step, ctx):
    """ทำหนึ่งขั้น: คำสั่งด่วนก่อน → ไม่ได้ค่อยให้ AI"""
    import quick
    try:
        r = quick.handle(step, ctx)
    except Exception as e:  # noqa: BLE001
        r = f"ERROR: {e}"
    if r:
        return r
    try:
        import agent
        cid = getattr(ctx, "chat_id", None) or "routine"
        return agent._chat_locked(cid, [{"type": "text", "text": step}], ctx)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _ok(r):
    r = (r or "").strip()
    return bool(r) and not r.startswith("ERROR") and not re.search(r"ไม่สำเร็จ|ทำไม่ได้|ไม่ได้\s*\(", r[:80])


def run(name, ctx=None):
    d = load()
    k = _key(name)
    steps = d.get(k)
    if not steps:
        return None
    if getattr(_depth, "on", False):
        return f"ข้ามรูทีน \"{k}\" (เรียกรูทีนซ้อนกันไม่ได้)"
    _depth.on = True
    t0 = time.time()
    try:
        if ctx is not None and hasattr(ctx, "status"):
            try:
                ctx.status(f"▶️ รูทีน{k}")
            except Exception:  # noqa: BLE001
                pass
        results = []
        for s in steps:
            r = _do_step(s, ctx)
            results.append((s, r, _ok(r)))
    finally:
        _depth.on = False
    try:
        import perf
        perf.record("routine", f"รูทีน{k}", total=time.time() - t0, ok=all(ok for _, _, ok in results))
    except Exception:  # noqa: BLE001
        pass
    good = sum(1 for _, _, ok in results if ok)
    head = f"▶️ รูทีน \"{k}\" เสร็จ {good}/{len(results)} ขั้น{_p()}"
    lines = []
    for s, r, ok in results:
        short = re.sub(r"\s+", " ", (r or "")).strip()
        if len(short) > 220:
            short = short[:220] + "…"
        lines.append(f"{'✓' if ok else '✕'} {s}" + (f"\n   {short}" if short else ""))
    return head + "\n" + "\n".join(lines)


# ================================================================ คำสั่ง

_CREATE = re.compile(r"^(?:ช่วย)?\s*(?:สร้าง|ตั้ง|เพิ่ม|แก้)\s*(?:รูทีน|โหมด)\s*(?P<name>[^:：]+?)\s*(?:[:：]|ให้|คือ|ว่า)\s*(?P<body>.+)$")
_TEACH = re.compile(r"^(?:จำไว้(?:นะ|ว่า)?|ต่อไป|ทีหลัง)?\s*(?:ถ้า|เวลา|ตอนที่)\s*(?:ผม|ฉัน|หนู|เรา)?\s*(?:บอก|พูด|สั่ง)(?:ว่า)?\s*"
                    r"[\"“]?(?P<name>.+?)[\"”]?\s*(?:ให้|ก็ให้|ก็)\s*(?P<body>.+)$")
_DELETE = re.compile(r"^(?:ช่วย)?\s*(?:ลบ|ยกเลิก|เลิกใช้)\s*(?:รูทีน|โหมด)\s*(?P<name>.+?)\s*(?:ทิ้ง|ออก)?\s*(?:ที|หน่อย|ครับ|ค่ะ|นะ)*$")
_LIST = re.compile(r"^(?:มี)?\s*(?:รูทีน|โหมด)\s*(?:อะไรบ้าง|ทั้งหมด)|^(?:ดู|แสดง)\s*รูทีน(?:ทั้งหมด)?$")
_SHOW = re.compile(r"^(?:รูทีน|โหมด)\s*(?P<name>.+?)\s*(?:มี|ทำ)\s*(?:อะไรบ้าง|อะไร)$")
_RUN = re.compile(r"^(?:ช่วย)?\s*(?:เริ่ม|เปิด|ใช้|เข้า)?\s*(?:รูทีน|โหมด)\s*(?P<name>.+?)\s*(?:เลย|ที|หน่อย|ครับ|ค่ะ|คะ|นะ)*$")
_BARE = re.compile(r"^(?P<name>.+?)\s*(?:แล้ว)?\s*(?:ครับ|ค่ะ|คะ|นะ|จ้า)*$")
_NOT_ROUTINE = re.compile(r"ห้ามรบกวน|เครื่องบิน|ประหยัด|มืด|ถนอมสายตา|ไม่อยู่|ฟังตลอด|เงียบ|สั่น|นักพัฒนา|ปลอดภัย|หมุนจอ")


def _list_text(d):
    if not d:
        return f"ยังไม่มีรูทีน{_p()} — สร้างได้ เช่น \"สร้างรูทีน นอน: ตั้งปลุก 6 โมง แล้ว เปิดโหมดห้ามรบกวน\""
    lines = [f"▶️ รูทีนที่มี {len(d)} อัน{_p()}"]
    for k, v in d.items():
        lines.append(f"• {k}: " + " → ".join(v))
    lines.append("พูดชื่อรูทีน เช่น \"โหมดนอน\" เพื่อเริ่ม · \"ลบรูทีน …\" เพื่อลบ")
    return "\n".join(lines)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?!.")
    if not t or len(t) > 300:
        return None
    m = _CREATE.match(t) or _TEACH.match(t)
    if m:
        name, steps = _key(m.group("name")), split_steps(m.group("body"))
        if not name or not steps:
            return f"บอกชื่อรูทีนและสิ่งที่ต้องทำด้วย{_p()} เช่น \"สร้างรูทีน นอน: ตั้งปลุก 6 โมง แล้ว ลดแสงจอ\""
        d = load()
        d[name] = steps
        save(d)
        return (f"✓ บันทึกรูทีน \"{name}\" แล้ว{_p()} ({len(steps)} ขั้น)\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
                + f"\nพูดว่า \"โหมด{name}\" เพื่อเริ่ม")
    m = _DELETE.match(t)
    if m:
        d = load()
        k = _key(m.group("name"))
        if k not in d:
            return f"ไม่มีรูทีน \"{k}\"{_p()}"
        del d[k]
        save(d)
        return f"ลบรูทีน \"{k}\" แล้ว{_p()}"
    if _LIST.match(t):
        return _list_text(load())
    m = _SHOW.match(t)
    if m:
        d = load()
        k = _key(m.group("name"))
        if k in d:
            return f"รูทีน \"{k}\": " + " → ".join(d[k])
    d = load()
    m = _RUN.match(t)
    if m and _key(m.group("name")) in d:
        return run(m.group("name"), ctx)
    m = _BARE.match(t)                                  # พูดชื่อรูทีนเฉยๆ เช่น "ออกจากบ้าน" "นอนแล้วนะ"
    if m and len(t) <= 20 and not _NOT_ROUTINE.search(t):
        k = _key(m.group("name"))
        if k in d and k not in ("นอน", "ทำงาน"):      # คำสั้นที่พูดเล่นได้บ่อย → ต้องมี "โหมด/รูทีน" นำหน้า
            return run(k, ctx)
        k2 = re.sub(r"(?:แล้ว|ละ)$", "", k)
        if k2 in d and k2 != k and k2 not in ("ทำงาน",):  # "นอนแล้ว" "ถึงบ้านแล้ว"
            return run(k2, ctx)
    return None
