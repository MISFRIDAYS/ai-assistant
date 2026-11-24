"""งานประจำวันแบบไม่ใช้ AI (ตอบใน 1-2 วิ ไม่เสียค่า API): ปลุก · จับเวลา · เตือนความจำ

ใช้คำสั่งของระบบ Android (แอปนาฬิกา) โดยตรง ไม่ต้องกดหน้าจอ
ตัวอย่าง:  "ปลุก 6 โมงครึ่ง" · "ตั้งปลุกตี 5" · "ปลุกบ่าย 2 ชื่อประชุม"
          "จับเวลา 5 นาที" · "ตั้งเวลา 1 ชั่วโมงครึ่ง" · "นับถอยหลัง 30 วิ"
          "อีก 10 นาทีเตือนให้ปิดเตา" · "เตือนกินยาตอน 2 ทุ่ม" · "เตือนให้โทรหาแม่ในอีก 1 ชั่วโมง"
คืนข้อความตอบ หรือ None (ไม่ใช่คำสั่งแบบนี้ → ส่งต่อให้ AI)
"""
import re
import time

_NUM = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7,
        "แปด": 8, "เก้า": 9, "สิบ": 10, "สิบเอ็ด": 11, "สิบสอง": 12, "ยี่สิบ": 20, "สามสิบ": 30,
        "สี่สิบห้า": 45, "สิบห้า": 15, "ยี่สิบห้า": 25}
_NW = "|".join(sorted(_NUM, key=len, reverse=True))
_N = rf"(\d+|{_NW})"


def _n(s):
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    return _NUM.get(s)


def _now():
    try:
        import agent
        return agent.now_local()
    except Exception:  # noqa: BLE001
        import datetime
        return datetime.datetime.now()


# ---------------------------------------------------------------- เวลาแบบไทย → (ชั่วโมง 0-23, นาที)

def parse_clock(t):
    """'6 โมงครึ่ง' '6 โมงเช้า' 'ตี 5' 'บ่าย 2' '1 ทุ่ม' 'เที่ยง' '06:30' '18.45' '6 นาฬิกา' → (h, m) / None"""
    t = re.sub(r"\s+", " ", t or "").strip()
    m = re.search(r"(?<!\d)([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)(?!\d)", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if re.search(r"(บ่าย|เย็น|ค่ำ|pm)", t) and h < 12:
            h += 12
        return h, mi
    if re.search(r"เที่ยงคืน", t):
        return 0, _mins(t)
    if re.search(r"เที่ยง(?:วัน|ตรง)?", t):
        return 12, _mins(t)
    m = re.search(rf"ตี\s*{_N}", t)
    if m and _n(m.group(1)) is not None and 1 <= _n(m.group(1)) <= 5:
        return _n(m.group(1)), _mins(t)
    m = re.search(rf"บ่าย\s*(?:โมง)?\s*{_N}?\s*(?:โมง)?", t)
    if m and re.search(r"บ่าย", t):
        n = _n(m.group(1)) if m.group(1) else 1
        if n is not None and 1 <= n <= 5:
            return 12 + n, _mins(t)
    m = re.search(rf"{_N}\s*ทุ่ม", t)
    if m and _n(m.group(1)) is not None and 1 <= _n(m.group(1)) <= 5:
        return 18 + _n(m.group(1)), _mins(t)
    if re.search(r"(?<!\d)ทุ่ม(?:นึง|หนึ่ง)?", t):
        return 19, _mins(t)
    m = re.search(rf"{_N}\s*(?:โมง|นาฬิกา)", t)
    if m and _n(m.group(1)) is not None:
        h = _n(m.group(1))
        if not 0 <= h <= 23:
            return None
        if re.search(r"(เย็น|บ่าย|ค่ำ)", t) and h < 12:
            h += 12 if h != 12 else 0
        elif h <= 5 and not re.search(r"(เช้า|นาฬิกา)", t):
            h += 12                          # "4 โมง" ภาษาพูด = 4 โมงเย็น (เช้าจะพูดว่า "ตี 4"/"4 โมงเช้า")
        return h, _mins(t)
    return None


def _mins(t):
    if "ครึ่ง" in t:
        return 30
    m = re.search(rf"(?:โมง|ทุ่ม|ตี\s*\S+|นาฬิกา|เที่ยง\S*)\s*{_N}\s*นาที", t)
    v = _n(m.group(1)) if m else None
    return v if v is not None and 0 <= v < 60 else 0


def parse_duration(t):
    """'5 นาที' '1 ชั่วโมงครึ่ง' '30 วิ' 'ชั่วโมงนึง' '2 ชม. 15 นาที' → วินาที / None"""
    t = re.sub(r"\s+", " ", t or "")
    total = 0
    found = False
    m = re.search(rf"{_N}?\s*(?:ชั่วโมง|ชม\.?)\s*(ครึ่ง)?", t)
    if m and (m.group(1) or re.search(r"ชั่วโมง(?:นึง|หนึ่ง)", t) or re.search(r"(?:อีก|ใน)\s*ชั่วโมง", t)):
        h = _n(m.group(1)) if m.group(1) else 1
        if h is not None:
            total += h * 3600 + (1800 if m.group(2) else 0)
            found = True
    m = re.search(rf"{_N}\s*นาที", t)
    if m and _n(m.group(1)) is not None:
        total += _n(m.group(1)) * 60
        found = True
    elif re.search(r"(ครึ่ง|ครื่ง)\s*นาที", t):
        total += 30
        found = True
    m = re.search(rf"{_N}\s*(?:วินาที|วิ)(?!\S*นาที)", t)
    if m and _n(m.group(1)) is not None:
        total += _n(m.group(1))
        found = True
    return total if found and 0 < total <= 24 * 3600 else None


def _only_duration(s):
    """ข้อความมีแต่ระยะเวลา (ตัวเลข/หน่วย) ไม่มีคำอื่นปน"""
    rest = re.sub(rf"{_N}|ชั่วโมง|ชม\.?|นาที|วินาที|วิ|ครึ่ง|นึง|อีก|ให้|ใน|\s", "", s or "")
    return rest == ""


# ---------------------------------------------------------------- คำสั่ง

_LEAD = r"^(?:ช่วย|ขอ|รบกวน)?\s*"
_TAIL = r"(?:\s*(?:ให้)?\s*(?:หน่อย|ด้วย|(?<!นา)ที|นะ|ครับ|ค่ะ|คะ|จ้า))*\s*$"
_ALARM = re.compile(_LEAD + r"(?:ตั้ง)?\s*(?:นาฬิกา)?ปลุก\s*(?:ฉัน|ผม|หนู|เรา)?\s*(?:ให้)?\s*(?:ตอน|เวลา|ตอนเวลา)?\s*"
                    r"(?P<when>.+?)(?:\s*(?:ชื่อ|ว่า|บอกว่า)\s*(?P<label>.+?))?" + _TAIL)
_TIMER = re.compile(_LEAD + r"(?:ตั้ง)?\s*(?:จับเวลา|ตั้งเวลา|นับถอยหลัง|ตั้งนาฬิกาจับเวลา|ไทเมอร์|timer)\s*(?P<d>.+?)" + _TAIL)
_REMIND_AFTER = re.compile(_LEAD + r"(?:อีก|ใน(?:อีก)?)\s*(?P<d>.+?(?:นาที|ชั่วโมง|ชม\.?|วินาที|วิ)(?:ครึ่ง)?)\s*"
                           r"(?:ช่วย)?\s*เตือน\s*(?:ฉัน|ผม|หนู|เรา)?\s*(?:ให้|ว่า)?\s*(?P<what>.+?)" + _TAIL)
_REMIND = re.compile(_LEAD + r"เตือน\s*(?:ฉัน|ผม|หนู|เรา)?\s*(?:ให้|ว่า)?\s*(?P<what>.+?)\s*"
                     r"(?:(?:ใน)?\s*(?:อีก)\s*(?P<d>.+?(?:นาที|ชั่วโมง|ชม\.?|วินาที|วิ)(?:ครึ่ง)?)|"
                     r"(?:ตอน|เวลา|ตอนเวลา)\s*(?P<at>.+?))" + _TAIL)


def _p():
    try:
        import quick
        return quick._p()
    except Exception:  # noqa: BLE001
        return "ครับ"


def _fmt_dur(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    out = (f"{h} ชั่วโมง " if h else "") + (f"{m} นาที " if m else "") + (f"{s} วินาที" if s else "")
    return out.strip()


def _run(name, args, ctx):
    import quick
    return quick._run(name, args, ctx)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?!.")
    if not t or len(t) > 90:
        return None
    m = _TIMER.match(t)
    if m and _only_duration(m.group("d")):              # "ตั้งเวลาปิดจอ 5 นาที" ไม่ใช่จับเวลา → ส่งต่อ
        sec = parse_duration(m.group("d"))
        if sec:
            r = _run("set_timer", {"seconds": sec}, ctx) or ""
            if r.startswith("ERROR") or "ไม่สำเร็จ" in r:
                return None                     # แอปนาฬิกาไม่รับ → ให้ AI ลองวิธีอื่น
            return f"⏱️ จับเวลา {_fmt_dur(sec)} แล้ว{_p()}"
    m = _REMIND_AFTER.match(t) or _REMIND.match(t)
    if m:
        what = re.sub(r"^(?:ให้|ว่า)\s*", "", m.group("what")).strip()
        minutes = None
        if m.groupdict().get("d"):
            sec = parse_duration(m.group("d"))
            minutes = sec / 60 if sec else None
        elif m.groupdict().get("at"):
            hm = parse_clock(m.group("at"))
            if hm:
                now = _now()
                due = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                if due <= now:
                    import datetime
                    due = due + datetime.timedelta(days=1)
                minutes = (due - now).total_seconds() / 60
        if minutes and what and ctx is not None and hasattr(ctx, "add_reminder"):
            r = _run("remind_me", {"minutes": round(minutes, 2), "text": what}, ctx) or ""
            if r.startswith("ERROR"):
                return None
            due = r.split("เวลา")[-1].strip() if "เวลา" in r else ""
            return f"🔔 ตั้งเตือน \"{what}\" แล้ว{_p()}" + (f" จะเตือนเวลา {due}" if due else "")
    m = _ALARM.match(t)
    if m:
        hm = None if "ทุก" in m.group("when") else parse_clock(m.group("when"))   # ปลุกซ้ำทุกวัน → ให้ AI ทำ
        if hm:
            label = (m.group("label") or "").strip() or "ปลุก"
            r = _run("set_alarm", {"hour": hm[0], "minute": hm[1], "label": label}, ctx) or ""
            if r.startswith("ERROR") or "ไม่สำเร็จ" in r:
                return None
            return f"⏰ ตั้งปลุก {hm[0]:02d}:{hm[1]:02d} น. แล้ว{_p()}" + (f" ({label})" if label != "ปลุก" else "")
    return None


def _selftest():                                      # python3 daily.py
    for s in ["6 โมงครึ่ง", "ตี 5", "บ่าย 2", "2 ทุ่ม", "เที่ยง", "06:30", "6 โมงเช้า", "5 โมงเย็น", "หกโมง"]:
        print(s, "→", parse_clock(s))
    for s in ["5 นาที", "1 ชั่วโมงครึ่ง", "30 วิ", "2 ชม. 15 นาที", "ชั่วโมงนึง"]:
        print(s, "→", parse_duration(s))
    print(time.strftime("%H:%M"))


if __name__ == "__main__":
    _selftest()
