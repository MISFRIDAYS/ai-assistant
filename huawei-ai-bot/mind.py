"""ความคิดและความจำของผู้ช่วย (ทำงานในเครื่อง ไม่เสียค่า AI เพิ่ม)

1. จำเอง: ฟังจากที่คุยกัน เช่น "ผมชื่อต้น" "ผมแพ้กุ้ง" "แฟนผมชื่อมิ้น" → จำไว้ใช้ตอบครั้งต่อไป
2. บันทึกประจำวัน: จดว่าวันนี้สั่งอะไรไปบ้าง → ถาม "วันนี้ทำอะไรไปบ้าง" "เมื่อวานสั่งอะไรไว้"
3. ความคิดของตัวเอง: คอยดูสถานการณ์แล้วทักเอง (เช้า: อากาศ+ฝน · แบตใกล้หมด/ชาร์จเต็ม · ดึกแล้วชวนพัก · วันเกิด)
4. ตัวตน + อารมณ์ตามเวลา/สถานการณ์ → ใส่ในพรอมต์ ให้ตอบต่อเนื่องเหมือนคนเดิมที่จำเรื่องราวได้
ปิดได้ที่ ⚙️ ตั้งค่า (MIND_ENABLED=0 / MEMORY_AUTO=0)
"""
import json
import os
import re
import threading
import time

import config

_lock = threading.Lock()
_state = {"started": False, "notify": None}


def _on(name, default="1"):
    return os.environ.get(name, default).strip() not in ("0", "false", "off", "")


def _p(name):
    return os.path.join(config.DATA_DIR, name)


def _jload(name, default):
    try:
        with open(_p(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _jsave(name, data):
    tmp = _p(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _p(name))


# ================================================================ 1) จำเอง

_ME = r"(?:ผม|ฉัน|หนู|เรา|กู|เค้า|ข้า)"
_FACTS = [
    (re.compile(_ME + r"\s*ชื่อ(?:เล่น)?\s*(?:ว่า)?\s*([ก-๙A-Za-z]{2,20})"), "ผู้ใช้ชื่อ {}"),
    (re.compile(_ME + r"\s*(?:ชอบ|รัก|โปรด)\s*(.{2,40}?)(?:มาก|ที่สุด)?(?:นะ|ครับ|ค่ะ|จ้า)?$"), "ผู้ใช้ชอบ {}"),
    (re.compile(_ME + r"\s*(?:ไม่ชอบ|เกลียด)\s*(.{2,40}?)(?:นะ|ครับ|ค่ะ)?$"), "ผู้ใช้ไม่ชอบ {}"),
    (re.compile(_ME + r"\s*แพ้\s*(.{2,30}?)(?:นะ|ครับ|ค่ะ)?$"), "ผู้ใช้แพ้ {} (ระวังเรื่องอาหาร/ยา)"),
    (re.compile(r"วันเกิด(?:ของ)?" + _ME + r"?\s*(?:คือ|เป็น|ตรงกับ)?\s*(?:วันที่)?\s*(.{3,30}?)(?:นะ|ครับ|ค่ะ)?$"), "วันเกิดผู้ใช้: {}"),
    (re.compile(_ME + r"\s*อายุ\s*(\d{1,3})"), "ผู้ใช้อายุ {} ปี"),
    (re.compile(_ME + r"\s*(?:ทำงาน|เรียน)\s*(?:อยู่)?\s*(?:ที่)\s*(.{2,40}?)(?:นะ|ครับ|ค่ะ)?$"), "ผู้ใช้ทำงาน/เรียนที่ {}"),
    (re.compile(_ME + r"\s*(?:อยู่|พัก)\s*(?:ที่|แถว)\s*(.{2,40}?)(?:นะ|ครับ|ค่ะ)?$"), "ผู้ใช้อยู่แถว {}"),
    (re.compile(r"(แฟน|ภรรยา|เมีย|สามี|ผัว|แม่|พ่อ|ลูก|พี่สาว|พี่ชาย|น้องสาว|น้องชาย|เพื่อนสนิท)" + _ME + r"?\s*ชื่อ\s*([ก-๙A-Za-z]{2,20})"),
     "{0}ของผู้ใช้ชื่อ {1}"),
]
_QUESTION = re.compile(r"(ไหม|มั้ย|อะไร|ยังไง|เท่าไหร่|ใคร|หรือเปล่า|รึเปล่า|ป่ะ|\?)")


def observe(text):
    """อ่านประโยคผู้ใช้ → จำเรื่องส่วนตัวที่บอกมา คืนรายการที่จำใหม่"""
    if not _on("MEMORY_AUTO"):
        return []
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    if not t or len(t) > 160 or _QUESTION.search(t) or re.search(r"(จำไว้ว่า|ส่ง|พิมพ์|บอก.*ว่า)", t):
        return []
    import extras
    new = []
    relation = _FACTS[-1][0].search(t)
    for i, (rx, tpl) in enumerate(_FACTS):
        if i == 0 and relation:                       # "แฟนผมชื่อมิ้น" = ชื่อแฟน ไม่ใช่ชื่อผู้ใช้
            continue
        m = rx.search(t)
        if not m:
            continue
        groups = [re.sub(r"(นะ|ครับ|คับ|ค่ะ|คะ|จ้า|จ๊ะ|ฮะ|เลย|ด้วย)+$", "", g.strip(" ,.!")).strip() for g in m.groups()]
        if any(len(g) < 2 for g in groups):
            continue
        fact = tpl.format(*groups)
        r = extras.remember({"text": fact}, None)
        if r.startswith("จำแล้ว"):
            new.append(fact)
            print(f"[mind] 🧠 จำเอง: {fact}", flush=True)
    return new


# ================================================================ 2) บันทึกประจำวัน

def log_turn(said, reply):
    said = " ".join((said or "").split())[:200]
    if not said or said.startswith("["):
        return
    with _lock:
        try:
            with open(_p("diary.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "said": said, "reply": " ".join((reply or "").split())[:200]},
                                   ensure_ascii=False) + "\n")
            if os.path.getsize(_p("diary.jsonl")) > 800_000:
                lines = open(_p("diary.jsonl"), encoding="utf-8").readlines()[-2000:]
                open(_p("diary.jsonl"), "w", encoding="utf-8").writelines(lines)
        except OSError:
            pass


def diary(day_offset=0, limit=30):
    start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")) - day_offset * 86400
    end = start + 86400
    out = []
    try:
        with open(_p("diary.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if start <= e["t"] < end:
                    out.append(e)
    except OSError:
        pass
    return out[-limit:]


_DIARY = re.compile(r"(วันนี้|เมื่อวาน)\s*(?:เรา|ผม|ฉัน)?\s*(?:ทำ|สั่ง|คุย)\s*(?:อะไร)(?:ไป)?\s*(?:บ้าง|มั่ง)")


def handle_text(text, ctx=None):
    t = " ".join((text or "").split())
    m = _DIARY.search(t)
    if not m:
        return None
    off = 1 if m.group(1) == "เมื่อวาน" else 0
    items = diary(off)
    if not items:
        return f"{m.group(1)}ยังไม่มีอะไรที่สั่งไว้เลยครับ"
    lines = [f"• {time.strftime('%H:%M', time.localtime(e['t']))} {e['said'][:70]}" for e in items[-15:]]
    return f"📔 {m.group(1)}สั่งไป {len(items)} เรื่อง:\n" + "\n".join(lines)


# ================================================================ 3) ตัวตน + อารมณ์ (ใส่ในพรอมต์)

def mood():
    h = int(time.strftime("%H"))
    if 5 <= h < 11:
        return "สดใส กระฉับกระเฉงตอนเช้า"
    if 11 <= h < 14:
        return "อารมณ์ดี เป็นกันเอง"
    if 14 <= h < 18:
        return "ตั้งใจทำงาน"
    if 18 <= h < 23:
        return "ผ่อนคลาย อบอุ่น"
    return "พูดเบาๆ นุ่มนวล (ดึกแล้ว) ห่วงใยให้ผู้ใช้พักผ่อน"


def self_prompt(recent_turns=True):
    """ตัวตน + เรื่องล่าสุดที่คุยกัน → ให้ตอบต่อเนื่องเหมือนจำเรื่องราวได้
    recent_turns=False: ไม่ใส่เรื่องล่าสุด (พรอมต์ของงานบนเครื่องคงที่ → แคชได้ ประหยัดค่า AI)"""
    if not _on("MIND_ENABLED"):
        return ""
    recent = diary(0, 6) if recent_turns else []
    rec = "; ".join(e["said"][:50] for e in recent[:-1]) if len(recent) > 1 else ""
    return (f"\n\nตัวตนของคุณ: ผู้ช่วยที่มีความคิดเป็นของตัวเอง ใส่ใจ จำเรื่องของผู้ใช้ได้ "
            f"มีความเห็นของตัวเองเมื่อถูกถาม (บอกตรงๆ อย่างสุภาพ) อารมณ์ตอนนี้: {mood()}"
            + (f"\nเรื่องที่ผู้ใช้สั่ง/คุยวันนี้ก่อนหน้า: {rec}" if rec else ""))


# ================================================================ 4) ความคิดของตัวเอง (ทักเอง)

def _once(key):
    """ทำครั้งเดียวต่อวัน/ต่อเหตุการณ์"""
    d = _jload("mind_state.json", {})
    stamp = time.strftime("%Y-%m-%d")
    if d.get(key) == stamp:
        return False
    d[key] = stamp
    _jsave("mind_state.json", d)
    return True


def _battery():
    try:
        import phone_tools
        b = json.loads(phone_tools.run(["termux-battery-status"], timeout=20))
        return int(b.get("percentage", -1)), str(b.get("status", "")).upper()
    except Exception:  # noqa: BLE001
        return -1, ""


def think():
    """คิดหนึ่งรอบ → ข้อความที่อยากบอกผู้ใช้ (หรือ None)"""
    if not _on("MIND_ENABLED") or config.paused():
        return None
    now = time.localtime()
    hm = now.tm_hour * 60 + now.tm_min
    msgs = []
    pct, st = _battery()
    if 0 <= pct <= 15 and st not in ("CHARGING", "FULL") and _once(f"bat_low_{pct // 5}"):
        msgs.append(f"🔋 แบตเหลือ {pct}% แล้ว เสียบชาร์จหน่อยนะครับ")
    if pct >= 100 and st in ("CHARGING", "FULL") and _once("bat_full"):
        msgs.append("🔌 ชาร์จเต็ม 100% แล้วครับ ถอดสายได้เลย")
    try:                                             # ผู้ช่วยเชิงรุก: สรุปเช้า (อากาศ+นัด+แชท) · เตือนก่อนนัด
        import proactive
        pro = proactive.on()
        if pro:
            msgs += proactive.tick()
    except Exception as e:  # noqa: BLE001
        print(f"[mind] proactive: {e}", flush=True)
        pro = False
    if not pro and 6 * 60 + 30 <= hm <= 9 * 60 + 30 and _once("morning"):
        line = "☀️ อรุณสวัสดิ์ครับ"
        try:
            import info
            w = info.weather(None, 0)
            line += "\n" + w
        except Exception:  # noqa: BLE001
            pass
        try:
            import extras
            for m in extras.memories():
                mm = re.search(r"วันเกิดผู้ใช้: .*?(\d{1,2})\s*[/ ]\s*(\d{1,2}|[ก-๙.]+)", m["text"])
                if mm and int(mm.group(1)) == now.tm_mday and (not mm.group(2).isdigit() or int(mm.group(2)) == now.tm_mon):
                    line += "\n🎂 สุขสันต์วันเกิดนะครับ! ขอให้วันนี้เป็นวันที่ดีที่สุด"
        except Exception:  # noqa: BLE001
            pass
        msgs.append(line)
    if 16 * 60 <= hm <= 17 * 60 and _once("rain_evening"):
        try:
            import info
            w = info.weather(None, 0)
            m = re.search(r"โอกาสฝน (\d+)%", w)
            if m and int(m.group(1)) >= 70:
                msgs.append(f"☔ เย็นนี้โอกาสฝน {m.group(1)}% กลับบ้านพกร่มด้วยนะครับ")
        except Exception:  # noqa: BLE001
            pass
    if (23 * 60 + 30 <= hm or hm <= 30) and _once("late_night"):
        n = len(diary(0))
        if n:
            msgs.append(f"🌙 ดึกแล้วนะครับ วันนี้สั่งงานไป {n} เรื่อง พักผ่อนบ้างนะ")
    return "\n\n".join(msgs) or None


def _loop():
    time.sleep(90)
    while True:
        try:
            msg = think()
            if msg and _state["notify"]:
                _state["notify"](msg)
        except Exception as e:  # noqa: BLE001
            print(f"[mind] {e}", flush=True)
        time.sleep(120)                              # ทุก 2 นาที (เตือนก่อนนัดได้ตรงเวลา)


def start(notify):
    """เริ่มความคิดเบื้องหลัง (เรียกครั้งเดียว) notify(ข้อความ) = ส่งถึงผู้ใช้"""
    _state["notify"] = notify
    if not _state["started"]:
        _state["started"] = True
        threading.Thread(target=_loop, daemon=True, name="mind").start()
