"""ระบบสกิล: บอทจดจำวิธีที่ทำสำเร็จ แล้วใช้ซ้ำ — ยิ่งใช้ยิ่งเร็วและแม่นขึ้น

1) จำตำแหน่งปุ่มในแอป (อัตโนมัติ)
   เช่น ปุ่ม "ข้อความ" ของ Instagram อยู่แถบซ้าย, ปุ่มส่งอยู่ขวาของช่องพิมพ์
   ครั้งหน้าลองตำแหน่งที่จำไว้ก่อน → ถ้าใช้ไม่ได้ ลืมทิ้งแล้วหาใหม่

2) จำขั้นตอนงาน (อัตโนมัติ + ผู้ใช้สอน)
   งานที่ AI ทำสำเร็จหลายขั้น จะถูกบันทึกเป็น "สกิล" (คำสั่ง → ลำดับเครื่องมือ)
   ครั้งหน้าสั่งคล้ายๆ กัน → แนบขั้นตอนที่เคยสำเร็จให้ AI ทำตาม (ไม่ต้องลองผิดลองถูก)
   ผู้ใช้สั่ง "จำวิธีนี้ไว้" = ปักหมุดสกิลล่าสุด / "วิธีนี้ผิด" = ลบทิ้ง / สอนเอง: "สอนสกิล: ... => ..."

ไฟล์: data/skills.json
"""
import json
import os
import re
import threading
import time

import config

_lock = threading.Lock()
MAX_SKILLS = 60
_FAIL_WORDS = ("error", "ไม่สำเร็จ", "ไม่เจอ", "ไม่ได้", "ไม่พบ", "ยกเลิก", "ไม่อนุญาต", "นานเกิน")


def _path():
    return os.path.join(config.DATA_DIR, "skills.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    d.setdefault("ui", {})
    d.setdefault("recipes", [])
    return d


def _save(d):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())


# ---------------------------------------------------------------- 1) ตำแหน่งปุ่ม

def ui_recall(app, kind):
    """คืน {"label","id","x","y","ok"} ที่เคยใช้สำเร็จ หรือ None"""
    with _lock:
        return _load()["ui"].get(f"{app}:{kind}")


def ui_learn(app, kind, e):
    with _lock:
        d = _load()
        k = f"{app}:{kind}"
        old = d["ui"].get(k) or {}
        d["ui"][k] = {"label": e.get("text") or e.get("desc") or "", "id": e.get("id", ""),
                      "x": e["x"], "y": e["y"], "ok": old.get("ok", 0) + 1, "t": int(time.time())}
        _save(d)


def ui_forget(app, kind):
    with _lock:
        d = _load()
        if d["ui"].pop(f"{app}:{kind}", None) is not None:
            _save(d)


def ui_match(app, kind, items):
    """หาปุ่มบนจอตอนนี้ที่ตรงกับที่จำไว้ (id/ชื่อเดียวกัน และอยู่ใกล้ตำแหน่งเดิม)"""
    m = ui_recall(app, kind)
    if not m or not items:
        return None
    best, dist = None, 1e9
    for e in items:
        same = (m["id"] and e.get("id") == m["id"]) or \
            (m["label"] and m["label"] in (e.get("text"), e.get("desc")))
        if not same:
            continue
        dd = abs(e["x"] - m["x"]) + abs(e["y"] - m["y"])
        if dd < dist:
            best, dist = e, dd
    return best if best is not None and dist < 250 else None


def get_pref(k):
    return _load().get("prefs", {}).get(k)


def set_pref(k, v):
    with _lock:
        d = _load()
        d.setdefault("prefs", {})[k] = v
        _save(d)


def add_names(names, key="contacts", limit=40):
    """จำชื่อคน/ห้องแชทที่เคยเห็น → ใช้ช่วยระบบถอดเสียงสะกดชื่อให้ถูก และช่วยเดาชื่อที่เพี้ยน"""
    names = [n.strip() for n in names if n and 1 < len(n.strip()) <= 30]
    if not names:
        return
    with _lock:
        d = _load()
        cur = d.setdefault("prefs", {}).get(key) or []
        for n in names:
            if n in cur:
                cur.remove(n)
            cur.insert(0, n)
        d["prefs"][key] = cur[:limit]
        _save(d)


def known_names():
    p = _load().get("prefs", {})
    out = []
    for k in ("contacts", "inbox_names"):
        for n in p.get(k) or []:
            if n not in out:
                out.append(n)
    for k, v in p.items():
        if k.startswith("alias:") and isinstance(v, str) and v not in out:
            out.append(v)
    return out


def vocab(max_chars=300):
    """คำเฉพาะสำหรับระบบถอดเสียง: ชื่อคนที่เคยแชท"""
    s = ", ".join(known_names())
    return s[:max_chars]


# ---------------------------------------------------------------- 2) ขั้นตอนงาน

def _grams(t):
    t = re.split(r"(?<!ชื่อ)ว่า|บอกว่า", t or "", maxsplit=1)[0]     # ตัดตัวข้อความที่จะส่งออก เทียบแค่ "รูปแบบคำสั่ง"
    t = re.sub(r"[\s\[\]().,!?\"'“”:;]+", "", t.lower())
    t = re.sub(r"(ครับ|ค่ะ|คะ|หน่อย|ให้ที|ด้วย|นะ|จ้า)", "", t)
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def _sim(a, b):
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _clean_request(text):
    t = re.sub(r"\[[^\]]*\]", " ", text or "")
    return " ".join(t.split())[:200]


def _steps_text(steps):
    out = []
    for s in steps:
        args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (s.get("args") or {}).items())
        out.append(f"{s['tool']}({args})")
    return " → ".join(out)


_SEND_INTENT = re.compile(r"(ส่ง|พิมพ์|ทัก|ตอบ|โพสต์|แชร์|เขียน|คอมเมนต์)")
_DOERS = {"send_dm", "type_text", "send_to_app", "share_text", "screen_task", "ask_ai_app"}


def _complete(req, steps, trace=None):
    """สกิลที่ดี: งานส่ง/พิมพ์ ต้องมีขั้นลงมือส่งจริง (และถ้ามีผลลัพธ์ ต้องยืนยันว่าส่งแล้ว)"""
    if not _SEND_INTENT.search(req or ""):
        return True
    if not any(st["tool"] in _DOERS for st in steps):
        return False
    if trace is not None:
        return any(("กดส่งแล้ว" in str(t.get("result", ""))) or ("✅" in str(t.get("result", ""))) for t in trace)
    return True


def prune():
    """ลบสกิลเสียที่จำไว้ก่อนหน้า (ไม่ปักหมุด + งานส่งข้อความที่ไม่มีขั้นส่งจริง)"""
    with _lock:
        d = _load()
        keep = [r for r in d["recipes"] if r.get("pinned") or r.get("how") or _complete(r["request"], r["steps"])]
        n = len(d["recipes"]) - len(keep)
        if n:
            d["recipes"] = keep
            _save(d)
        return n


def record(request, trace):
    """บันทึกงานที่ทำสำเร็จ: trace = [{"tool","args","result"}] (เฉพาะงาน 2 ขั้นขึ้นไป ที่ไม่มีขั้นไหนพัง)"""
    req = _clean_request(request)
    if not req or len(trace) < 2 or len(trace) > 12:
        return None
    if any(any(w in str(s.get("result", "")).lower()[:160] for w in _FAIL_WORDS) for s in trace):
        return None
    steps = [{"tool": s["tool"], "args": s.get("args") or {}} for s in trace
             if s["tool"] not in ("read_screen", "screenshot")]           # ขั้นอ่านจอไม่ต้องจำ
    if len(steps) < 2:
        return None
    if not _complete(req, steps, trace):
        return None                     # งานยังไม่จบจริง (เช่น เปิดแอปแล้วหยุด) → ห้ามจำ ไม่งั้นครั้งหน้าทำตามแล้วหยุดอีก
    with _lock:
        d = _load()
        for r in d["recipes"]:
            if _sim(r["request"], req) >= 0.6 and _steps_text(r["steps"]) == _steps_text(steps):
                r["ok"] = r.get("ok", 0) + 1
                r["t"] = int(time.time())
                d["last"] = r["id"]
                _save(d)
                return r
        rid = max([r["id"] for r in d["recipes"]] or [0]) + 1
        r = {"id": rid, "request": req, "steps": steps, "ok": 1, "pinned": False, "t": int(time.time())}
        d["recipes"].append(r)
        if len(d["recipes"]) > MAX_SKILLS:               # ลบอันที่ไม่ปักหมุดและใช้น้อย/เก่าสุด
            d["recipes"].sort(key=lambda x: (x.get("pinned"), x.get("ok", 0), x.get("t", 0)), reverse=True)
            d["recipes"] = d["recipes"][:MAX_SKILLS]
        d["last"] = rid
        _save(d)
        return r


def teach(trigger, how):
    """ผู้ใช้สอนเอง: 'สอนสกิล: ส่งการบ้าน => เปิด LINE ห้อง ม.6/2 แล้วส่งไฟล์ล่าสุด'"""
    with _lock:
        d = _load()
        rid = max([r["id"] for r in d["recipes"]] or [0]) + 1
        r = {"id": rid, "request": trigger.strip()[:200], "steps": [], "how": how.strip()[:500], "ok": 0,
             "pinned": True, "t": int(time.time())}
        d["recipes"].append(r)
        d["last"] = rid
        _save(d)
        return r


def find(request, threshold=0.45):
    """สกิลที่ใกล้กับคำสั่งนี้ที่สุด หรือ None"""
    prune()
    req = _clean_request(request)
    best, score = None, 0.0
    for r in _load()["recipes"]:
        s = _sim(r["request"], req) + (0.08 if r.get("pinned") else 0) + min(0.06, 0.02 * r.get("ok", 0))
        if s > score:
            best, score = r, s
    return best if best and score >= threshold else None


def hint(request):
    """ข้อความแนบให้ AI: ขั้นตอนที่เคยทำสำเร็จกับคำสั่งคล้ายกัน"""
    r = find(request)
    if not r:
        return None
    with _lock:
        d = _load()
        d["used"] = r["id"]
        _save(d)
    how = r.get("how") or _steps_text(r["steps"])
    return (f"[สกิลที่เคยทำสำเร็จ (#{r['id']}) กับคำสั่งคล้ายกัน \"{r['request'][:80]}\": {how[:600]} — "
            "ทำตามขั้นตอนนี้ได้เลย เปลี่ยนเฉพาะชื่อ/ข้อความให้ตรงกับคำสั่งใหม่ ถ้าขั้นไหนใช้ไม่ได้ค่อยหาวิธีอื่น]")


def failed_used():
    """งานรอบนี้ล้มเหลวทั้งที่ใช้สกิล → ลดความเชื่อมั่น (ไม่ปักหมุด + พลาดบ่อย = ลบ)"""
    with _lock:
        d = _load()
        rid = d.pop("used", None)
        for r in list(d["recipes"]):
            if r["id"] == rid and not r.get("pinned"):
                r["ok"] = r.get("ok", 0) - 1
                if r["ok"] <= -1:
                    d["recipes"].remove(r)
        _save(d)


def clear_used():
    with _lock:
        d = _load()
        if d.pop("used", None) is not None:
            _save(d)


def pin_last():
    with _lock:
        d = _load()
        rid = d.get("used") or d.get("last")
        for r in d["recipes"]:
            if r["id"] == rid:
                r["pinned"] = True
                _save(d)
                return r
    return None


def delete(rid=None):
    with _lock:
        d = _load()
        rid = rid or d.get("used") or d.get("last")
        n = len(d["recipes"])
        d["recipes"] = [r for r in d["recipes"] if r["id"] != rid]
        if len(d["recipes"]) != n:
            _save(d)
            return rid
    return None


def listing():
    d = _load()
    if not d["recipes"] and not d["ui"]:
        return ("🧠 ยังไม่มีสกิล — ใช้งานไปเรื่อยๆ บอทจะจำวิธีที่ทำสำเร็จเอง\n"
                "สอนเองได้: สอนสกิล: [คำสั่ง] => [วิธีทำ]")
    lines = ["🧠 สกิลที่บอทจำไว้:"]
    for r in sorted(d["recipes"], key=lambda x: (not x.get("pinned"), -x.get("ok", 0))):
        how = r.get("how") or _steps_text(r["steps"])
        lines.append(f"{'📌' if r.get('pinned') else '•'} #{r['id']} \"{r['request'][:50]}\" (สำเร็จ {r.get('ok', 0)} ครั้ง)\n"
                     f"   {how[:140]}")
    if d["ui"]:
        lines.append("\n📍 ตำแหน่งปุ่มที่จำไว้: " + ", ".join(
            f"{k} ('{v['label'][:12]}' {v['ok']} ครั้ง)" for k, v in list(d["ui"].items())[:12]))
    lines.append("\nลบ: /skill_del เลข · ปักหมุดอันล่าสุด: พิมพ์ 'จำวิธีนี้ไว้' · ลบอันล่าสุด: 'วิธีนี้ผิด'")
    return "\n".join(lines)


# ---------------------------------------------------------------- คำสั่งพิมพ์/พูด

_PIN = re.compile(r"^(จำวิธีนี้(ไว้)?|จำไว้เลย|วิธีนี้ดี(มาก)?|ทำแบบนี้แหละ|ถูกแล้ว)")
_BAD = re.compile(r"^(วิธีนี้ผิด|ลืมวิธีนี้|อย่าทำแบบนี้(อีก)?|ทำผิด(วิธี)?)")
_NICK = re.compile(r"^(?:จำชื่อ|ชื่อเล่น|เวลาพูดว่า|ถ้าพูดว่า)\s*[:：]?\s*(?P<s>.+?)\s*(?:=|คือ|หมายถึง|ให้หมายถึง)\s*(?P<r>.+)$")
_TEACH = re.compile(r"^สอนสกิล\s*[:：]?\s*(?P<t>.+?)\s*(=>|->|ให้ทำ|คือ)\s*(?P<h>.+)$")


def handle_nick(text):
    """สอนชื่อเล่น: 'จำชื่อ เมีย = ภรรยา(คนเจก)'"""
    t = " ".join((text or "").split())
    m = _NICK.match(t)
    if not m:
        return None
    import share_tools
    spoken, real = m.group("s").strip(" '\""), m.group("r").strip(" '\"")
    set_pref(f"alias:*:{share_tools._loose(spoken)}", real)
    add_names([real])
    return f"📌 จำแล้ว: พูดว่า \"{spoken}\" = แชทของ \"{real}\""


def handle_text(text):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    if not t:
        return None
    if _PIN.match(t):
        r = pin_last()
        return f"📌 จำวิธีนี้แล้ว (สกิล #{r['id']}) ครั้งหน้าจะทำแบบนี้เลย" if r else None
    if _BAD.match(t):
        rid = delete()
        return f"🗑️ ลบสกิล #{rid} แล้ว ครั้งหน้าจะลองวิธีอื่น" if rid else "ยังไม่มีสกิลล่าสุดให้ลบ"
    m = _NICK.match(t)
    if m:
        import share_tools
        spoken, real = m.group("s").strip(" '\""), m.group("r").strip(" '\"")
        set_pref(f"alias:*:{share_tools._loose(spoken)}", real)
        add_names([real])
        return f"📌 จำแล้ว: พูดว่า \"{spoken}\" = แชทของ \"{real}\""
    m = _TEACH.match(t)
    if m:
        r = teach(m.group("t"), m.group("h"))
        return f"📌 จำสกิล #{r['id']} แล้ว: เมื่อสั่ง \"{r['request']}\" จะทำตามนี้ → {r['how']}"
    return None
