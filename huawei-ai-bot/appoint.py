"""นัดหมาย + บันทึกงานซ่อม (Massjoyfix) ลง Google Calendar ด้วยเสียง

พูด "สร้างนัด" → ผู้ช่วยถามทีละข้อ: วันไหน · กี่โมงถึงกี่โมง · เรื่องอะไร · สำคัญระดับไหน → อ่านทวน → "ใช่" → ลงปฏิทิน
พูด "บันทึกงาน" → ถาม: เลข Job · ชื่อลูกค้า · สถานะ · รายละเอียด · ค่าใช้จ่ายทั้งหมด → อ่านทวน → ลงปฏิทิน

ลง Google Calendar ผ่าน Google Apps Script ของผู้ใช้เอง (GCAL_URL + GCAL_SECRET, ดู google_calendar_script.gs)
ยังไม่ได้เชื่อม → เปิดหน้าสร้างนัดของแอปปฏิทินพร้อมกรอกให้ (ผู้ใช้กดบันทึกเอง)
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import config

TTL = 300                       # คุยค้างไว้นานสุด 5 นาที
_S = {}                         # บทสนทนาที่กำลังถาม {"kind", "data", "ask", "t", "confirm"}

PRIORITIES = {"ด่วนมาก": ("11", 60), "สูง": ("6", 30), "ปกติ": ("9", 15), "ต่ำ": ("8", 10)}   # สี Google + เตือนก่อนกี่นาที
STATUSES = {"ทำงานเสร็จแล้ว": "10", "ยกเลิกซ่อม": "8", "รอส่งเคลม": "5", "ตรวจเช็คแล้ว": "7"}

FIELDS = {
    "appt": [("date", "นัดวันไหนครับ"), ("time", "กี่โมงถึงกี่โมงครับ"), ("title", "นัดเรื่องอะไรครับ"),
             ("priority", "สำคัญระดับไหนครับ ด่วนมาก สูง ปกติ หรือต่ำ")],
    "job": [("job_no", "เลข Job อะไรครับ"), ("customer", "ลูกค้าชื่ออะไรครับ"),
            ("status", "สถานะอะไรครับ ทำงานเสร็จแล้ว ยกเลิกซ่อม รอส่งเคลม หรือตรวจเช็คแล้ว"),
            ("detail", "รายละเอียดการซ่อมว่าอะไรครับ"), ("cost", "ค่าใช้จ่ายทั้งหมดกี่บาทครับ")],
}

_START_APPT = re.compile(r"^(ช่วย)?\s*(สร้าง|เพิ่ม|ลง|จด|ตั้ง|ทำ|บันทึก)\s*(นัด|นัดหมาย|อีเว้?น(ท์|ต์)?|event|กิจกรรม)"
                         r"|^(ลง|เพิ่ม)\s*(ใน)?\s*(ปฏิทิน|calendar|คาเลนเดอร์)|^นัดหมาย", re.I)
_START_JOB = re.compile(r"^(ช่วย)?\s*(บันทึก|ลง|ปิด|จด)\s*(งาน|จ็อบ|จ๊อบ|job|งานซ่อม)|^(งานซ่อม|จ็อบ|job)\s*(เสร็จ|ยกเลิก|ส่งเคลม|ตรวจ)",
                        re.I)
_CANCEL = re.compile(r"^(ยกเลิก|ไม่เอา|ไม่ต้อง|พอ|หยุด|cancel|ช่างมัน|เลิก)(แล้ว)?\s*(ครับ|ค่ะ|นะ)?$", re.I)
_YES = re.compile(r"^(ใช่|ใช่ๆ|ช่าย|ช้าย|ไช่|ใช|ใช้|ชัย|ใช่แล้ว|เออ|อือ|อืม|ได้เลย|ถูกแล้ว|โอเค้|โอเคร|โอเคๆ|ถูก|ถูกต้อง|โอเค|ok|okay|ได้|ตกลง|ยืนยัน|เอาเลย|จัดไป|ลงเลย|บันทึกเลย|เยส|yes|ครับผม|ค่ะ|ครับ)"
                  r"(แล้ว|เลย|ครับ|ค่ะ|นะ|\s)*$", re.I)
_LIST = re.compile(r"(วันนี้|พรุ่งนี้|สัปดาห์นี้|อาทิตย์นี้)\s*(มี)?\s*(นัด|ตาราง|งาน)(อะไร)?|"
                   r"^(ดู|เช็ค|เช็ก)\s*(นัด|ตาราง|ปฏิทิน)", re.I)
_TEST = re.compile(r"^(ทดสอบ|เช็ค|เช็ก)\s*(ปฏิทิน|calendar|คาเลนเดอร์)", re.I)

_TH_DAYS = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
_TH_MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def _tz():
    return timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS))


def _now():
    return datetime.now(_tz())


def _p():
    try:
        import voice_profile
        return voice_profile.pol()
    except Exception:  # noqa: BLE001
        return "ครับ"


# ---------------------------------------------------------------- เข้าใจคำตอบ

def _llm_extract(kind, text, data, ask):
    """ให้ AI แปลงคำพูดเป็นข้อมูล (วันที่/เวลาภาษาพูด เช่น "บ่ายสอง" "วันศุกร์หน้า") — ไม่ได้ก็คืน {}"""
    now = _now()
    if kind == "appt":
        schema = ('{"date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM", "title": "เรื่องที่นัด", '
                  '"priority": "ด่วนมาก|สูง|ปกติ|ต่ำ", "location": "สถานที่"}')
        rules = ("บ่ายโมง=13:00 บ่ายสอง=14:00 สี่โมงเย็น=16:00 หกโมงเย็น=18:00 ทุ่มนึง=19:00 เที่ยง=12:00 "
                 "สิบโมง=10:00 (ถ้าไม่บอกเช้า/บ่ายและเป็น 1-6 โมง ให้เดาเป็นบ่าย) "
                 "ถ้าบอกแค่เวลาเริ่ม ให้ end เป็น null")
    else:
        schema = ('{"job_no": "เลขงาน", "customer": "ชื่อลูกค้า", '
                  '"status": "ทำงานเสร็จแล้ว|ยกเลิกซ่อม|รอส่งเคลม|ตรวจเช็คแล้ว", "detail": "รายละเอียดการซ่อม", '
                  '"cost": ตัวเลขบาท}')
        rules = "เสร็จ/ซ่อมเสร็จ=ทำงานเสร็จแล้ว ยกเลิก=ยกเลิกซ่อม เคลม=รอส่งเคลม ตรวจ/เช็คแล้ว=ตรวจเช็คแล้ว ไม่มีค่าใช้จ่าย=0"
    system = ("แปลงคำพูดภาษาไทยเป็น JSON เท่านั้น ห้ามอธิบาย ห้ามเดาข้อมูลที่ไม่ได้พูด (ใส่ null) "
              f"วันนี้คือ {_TH_DAYS[now.weekday()]} {now:%Y-%m-%d} เวลา {now:%H:%M} "
              f"รูปแบบ: {schema} กฎ: {rules}")
    hint = f"(ผู้ใช้กำลังตอบคำถามเรื่อง: {ask}) " if ask else ""
    prompt = f"{hint}ข้อมูลที่มีแล้ว: {json.dumps(data, ensure_ascii=False)}\nคำพูด: {text}"
    try:
        import agent
        out = ""
        if config.GROQ_API_KEY:                 # Groq เร็วกว่ามาก (~0.5 วิ) งานแปลงวันที่/เวลาเล็กๆ แบบนี้พอ
            try:
                import groq_client
                r = groq_client.create_message(system, [{"role": "user", "content": prompt}], None, 300)
                out = agent._collect_text(r.get("content") or [])
            except Exception as e:  # noqa: BLE001
                print(f"[appoint] Groq ใช้ไม่ได้ ใช้ AI หลัก: {str(e)[:80]}", flush=True)
        if not out:
            res, _ = agent.call_llm([{"role": "user", "content": prompt}], None, system=system)
            out = agent._collect_text(res.get("content") or [])
        m = re.search(r"\{.*\}", out, re.S)
        d = json.loads(m.group(0)) if m else {}
        return {k: v for k, v in d.items() if v not in (None, "", "null")}
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ appoint: AI แปลงคำพูดไม่ได้ ใช้วิธีพื้นฐาน: {str(e)[:100]}", flush=True)
        return {}


_NUM = {"หนึ่ง": 1, "นึง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9,
        "สิบ": 10, "สิบเอ็ด": 11, "สิบสอง": 12}


def _local_date(t):
    now = _now().date()
    if "มะรืน" in t:
        return now + timedelta(days=2)
    if "พรุ่งนี้" in t:
        return now + timedelta(days=1)
    if "วันนี้" in t:
        return now
    for i, d in enumerate(_TH_DAYS):
        short = d.replace("วัน", "").replace("บดี", "")
        if short in t:
            n = (i - now.weekday()) % 7 or 7
            if "หน้า" in t and n < 7:
                n += 7 if "สัปดาห์หน้า" in t or "อาทิตย์หน้า" in t else 0
            return now + timedelta(days=n)
    m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{1,2})(?:\s*[/\-]\s*(\d{2,4}))?", t)
    if m:
        y = int(m.group(3)) if m.group(3) else now.year
        y = y - 543 if y > 2400 else (y + 2000 if y < 100 else y)
        try:
            return datetime(y, int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            return None
    m = re.search(r"(?:วันที่\s*)?(\d{1,2})\s*(ม\.?ค|มกรา|ก\.?พ|กุมภา|มี\.?ค|มีนา|เม\.?ย|เมษา|พ\.?ค|พฤษภา|มิ\.?ย|มิถุนา|"
                  r"ก\.?ค|กรกฎา|ส\.?ค|สิงหา|ก\.?ย|กันยา|ต\.?ค|ตุลา|พ\.?ย|พฤศจิกา|ธ\.?ค|ธันวา)", t)
    if m:
        keys = ["มก", "กุ", "มีน", "เม", "พฤษ", "มิ", "กร", "สิ", "กัน", "ตุ", "พฤศ", "ธั"]
        short = ["ม.ค", "ก.พ", "มี.ค", "เม.ย", "พ.ค", "มิ.ย", "ก.ค", "ส.ค", "ก.ย", "ต.ค", "พ.ย", "ธ.ค"]
        word = m.group(2)
        mon = next((i + 1 for i, k in enumerate(keys) if word.startswith(k)), None)
        if mon is None:
            w = word if "." in word else word[0] + "." + word[1:]
            mon = next((i + 1 for i, k in enumerate(short) if w.startswith(k)), None)
        if mon:
            d = datetime(now.year, mon, int(m.group(1))).date()
            return d if d >= now else datetime(now.year + 1, mon, int(m.group(1))).date()
    return None


def _one_time(s):
    s = s.strip()
    m = re.search(r"(\d{1,2})[:.](\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    half = 30 if "ครึ่ง" in s else 0
    if "เที่ยงคืน" in s:
        return 0, half
    if "เที่ยง" in s:
        return 12, half
    m = re.search(r"(\d{1,2})|(สิบสอง|สิบเอ็ด|สิบ|หนึ่ง|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)", s)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1) else _NUM[m.group(2)]
    if "ทุ่ม" in s:
        return 18 + n, half
    if "ตี" in s:
        return n, half
    if "บ่าย" in s:
        return (12 + n if n < 12 else n), half
    if "เย็น" in s or "ค่ำ" in s:
        return (12 + n if n < 12 else n), half
    if "โมง" in s or "นาฬิกา" in s or m.group(1):
        if 1 <= n <= 6 and "เช้า" not in s and "นาฬิกา" not in s and not m.group(1):
            return 12 + n, half
        return n, half
    return None


def _local_times(t):
    parts = re.split(r"\s*(?:ถึง|-|–|ถึงเวลา|จนถึง)\s*", t, maxsplit=1)
    a = _one_time(parts[0]) if parts else None
    b = _one_time(parts[1]) if len(parts) > 1 else None
    fmt = lambda x: f"{x[0] % 24:02d}:{x[1]:02d}" if x else None  # noqa: E731
    return fmt(a), fmt(b)


def _local_priority(t):
    if re.search(r"ด่วนมาก|ด่วนที่สุด|สำคัญมาก|ด่วนสุด", t):
        return "ด่วนมาก"
    if re.search(r"ด่วน|สูง|สำคัญ", t) and "ไม่" not in t:
        return "สูง"
    if re.search(r"ต่ำ|ไม่ด่วน|ไม่สำคัญ|เล็กน้อย", t):
        return "ต่ำ"
    if re.search(r"ปกติ|ธรรมดา|กลาง", t):
        return "ปกติ"
    return None


def _local_status(t):
    if "ยกเลิก" in t:
        return "ยกเลิกซ่อม"
    if "เคลม" in t:
        return "รอส่งเคลม"
    if re.search(r"ตรวจ|เช็ค|เช็ก", t):
        return "ตรวจเช็คแล้ว"
    if "เสร็จ" in t:
        return "ทำงานเสร็จแล้ว"
    return None


def _local_cost(t):
    if re.search(r"ไม่มี(ค่าใช้จ่าย)?|ฟรี|ไม่เสีย|ศูนย์บาท", t):
        return 0
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", t)
    return float(m.group(1).replace(",", "")) if m else None


def _merge(kind, text, data, ask):
    """รวมข้อมูลจากคำพูดใหม่ (AI ก่อน แล้วเสริมด้วยกฎพื้นฐาน)"""
    got = dict(_llm_extract(kind, text, data, ask) or {})
    t = text.strip()
    if kind == "appt":
        if "date" not in got and (ask in (None, "date") or re.search(r"วัน|พรุ่งนี้|มะรืน|\d+\s*/", t)):
            d = _local_date(t)
            if d:
                got["date"] = d.isoformat()
        if "start" not in got and (ask in (None, "time") or re.search(r"โมง|ทุ่ม|\d[:.]\d\d|เที่ยง", t)):
            a, b = _local_times(t)
            if a:
                got["start"] = a
                if b:
                    got["end"] = b
        if "priority" not in got and ask in (None, "priority"):
            pr = _local_priority(t)
            if pr:
                got["priority"] = pr
        if "title" not in got and ask == "title":
            got["title"] = t
        if got.get("priority") not in PRIORITIES:
            got.pop("priority", None)
    else:
        if "job_no" not in got:
            m = re.search(r"(?:job|จ็อบ|จ๊อบ|เลข(?:ที่)?|เบอร์)\s*(?:ที่)?\s*([A-Za-z]*-?\d[\w\-]*)", t, re.I)
            if m:
                got["job_no"] = m.group(1)
            elif ask == "job_no":
                m = re.search(r"([A-Za-z]*-?\d[\w\-]*)", t)
                if m:
                    got["job_no"] = m.group(1)
        if "status" not in got and ask in (None, "status"):
            st = _local_status(t)
            if st:
                got["status"] = st
        if "cost" not in got and ask == "cost":
            c = _local_cost(t)
            if c is not None:
                got["cost"] = c
        if "customer" not in got and ask == "customer":
            got["customer"] = re.sub(r"^(ชื่อ|ลูกค้า|ลูกค้าชื่อ|คุณ)\s*", "", t)
        if "detail" not in got and ask == "detail":
            got["detail"] = t
        if got.get("status") not in STATUSES:
            got.pop("status", None)
        if "cost" in got:
            try:
                got["cost"] = float(str(got["cost"]).replace(",", ""))
            except ValueError:
                got.pop("cost")
    if kind == "appt" and ask == "time" and data.get("start") and not data.get("end"):
        if got.get("start") and not got.get("end") and got["start"] != data["start"]:
            got["end"] = got.pop("start")                   # ถามเวลาจบ ตอบมาเวลาเดียว = เวลาจบ
        elif got.get("start") == data["start"]:
            got.pop("start")
        m = re.search(r"(\d+|หนึ่ง|นึง|สอง|สาม|ครึ่ง)\s*ชั่วโมง|ชั่วโมงเดียว", t)
        if m and not got.get("end"):                        # "ชั่วโมงเดียว" "สองชั่วโมง" "ครึ่งชั่วโมง"
            w = m.group(1) or "1"
            mins = 30 if w == "ครึ่ง" else 60 * (int(w) if w.isdigit() else _NUM.get(w, 1))
            h, mi = map(int, data["start"].split(":"))
            e = h * 60 + mi + mins
            got["end"] = f"{(e // 60) % 24:02d}:{e % 60:02d}"
    data.update(got)
    return data


def _missing(kind, data):
    for f, q in FIELDS[kind]:
        if f == "time":
            if not data.get("start"):
                return f, q
            if not data.get("end"):
                return f, f"เริ่ม {data['start']} น. แล้วจบกี่โมงครับ"
        elif data.get(f) in (None, ""):
            return f, q
    return None, None


# ---------------------------------------------------------------- สรุป/อ่านทวน

def _thai_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{_TH_DAYS[d.weekday()]}ที่ {d.day} {_TH_MONTHS[d.month]}"


def _money(x):
    x = float(x or 0)
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def _summary(kind, d):
    if kind == "appt":
        s = f"นัด {d['title']} {_thai_date(d['date'])} เวลา {d['start']} ถึง {d['end']} น. ความสำคัญ {d['priority']}"
        return s + (f" ที่ {d['location']}" if d.get("location") else "")
    return (f"Job {d['job_no']} ลูกค้า {d['customer']} สถานะ {d['status']} "
            f"รายละเอียด {d['detail']} ค่าใช้จ่ายทั้งหมด {_money(d['cost'])} บาท")


def _event(kind, d):
    tz = _tz()
    if kind == "appt":
        start = datetime.fromisoformat(f"{d['date']}T{d['start']}:00").replace(tzinfo=tz)
        end = datetime.fromisoformat(f"{d['date']}T{d['end']}:00").replace(tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)                       # 22:00 ถึง 01:00
        color, remind = PRIORITIES.get(d.get("priority"), PRIORITIES["ปกติ"])
        title = ("🔴 " if d.get("priority") == "ด่วนมาก" else "🟠 " if d.get("priority") == "สูง" else "") + d["title"]
        return {"title": title, "start": start.isoformat(), "end": end.isoformat(), "color": color,
                "reminderMin": remind, "location": d.get("location", ""),
                "description": f"ความสำคัญ: {d.get('priority', 'ปกติ')}\nสร้างโดยผู้ช่วย AI"}
    now = _now().replace(second=0, microsecond=0)
    title = f"[{d['status']}] Job {d['job_no']} · {d['customer']} · {_money(d['cost'])} บาท"
    desc = (f"เลข Job: {d['job_no']}\nชื่อลูกค้า: {d['customer']}\nสถานะ: {d['status']}\n"
            f"รายละเอียดการซ่อม: {d['detail']}\nค่าใช้จ่ายทั้งหมด: {_money(d['cost'])} บาท\n"
            f"ระบบ: Massjoyfix (mass.joyfix.net)\nบันทึกโดยผู้ช่วย AI {now:%Y-%m-%d %H:%M}")
    return {"title": title, "start": now.isoformat(), "end": (now + timedelta(minutes=30)).isoformat(),
            "color": STATUSES.get(d["status"], "9"), "description": desc,
            "key": f"job-{d['job_no']}-{d['status']}"}


# ---------------------------------------------------------------- ส่งเข้า Google Calendar

def connected():
    return bool(config.GCAL_URL and config.GCAL_SECRET)


def _post(payload, timeout=25):
    import requests
    body = dict(payload, secret=config.GCAL_SECRET)
    r = requests.post(config.GCAL_URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "text/plain;charset=utf-8"}, timeout=timeout, allow_redirects=True)
    try:
        d = r.json()
    except ValueError as e:
        low = r.text[:400].lower()
        if "sign in" in low or "accounts.google" in low:
            raise RuntimeError("Google ขอให้ล็อกอิน — ตอน Deploy ต้องตั้ง Who has access เป็น Anyone") from e
        raise RuntimeError(f"Google Calendar ตอบไม่ถูกต้อง ({r.status_code})") from e
    if not d.get("ok"):
        raise RuntimeError("รหัสลับไม่ตรงกับในสคริปต์" if d.get("error") == "secret" else str(d.get("error"))[:120])
    return d


def _open_insert(ev):
    """ยังไม่เชื่อม Google → เปิดหน้าสร้างนัดของแอปปฏิทินพร้อมกรอกให้ (ผู้ใช้กดบันทึกเอง)"""
    import phone_tools
    begin = int(datetime.fromisoformat(ev["start"]).timestamp() * 1000)
    end = int(datetime.fromisoformat(ev["end"]).timestamp() * 1000)
    installed = {c.split("/")[0] for c in phone_tools._launcher_components()}
    pkg = next((p for p in phone_tools.ALT_PKGS["calendar"] if p in installed), "")
    args = ["am", "start", "-a", "android.intent.action.INSERT", "-d", "content://com.android.calendar/events",
            "--el", "beginTime", str(begin), "--el", "endTime", str(end),
            "--es", "title", ev["title"], "--es", "description", ev.get("description", "")]
    if ev.get("location"):
        args += ["--es", "eventLocation", ev["location"]]
    if pkg:
        args += ["-p", pkg]
    res = phone_tools._sh(args)
    out = getattr(res, "stdout", res) or ""
    if "Error" in str(out):
        raise RuntimeError(str(out)[:150])


def create(kind, d):
    ev = _event(kind, d)
    if connected():
        res = _post(dict(ev, action="create"))
        _log(kind, d, "google")
        if res.get("dup"):
            return f"รายการนี้มีในปฏิทินแล้ว ไม่ลงซ้ำ{_p()}"
        return f"ลง Google Calendar แล้ว{_p()} — {_summary(kind, d)}"
    _open_insert(ev)
    _log(kind, d, "intent")
    return (f"เปิดหน้าสร้างนัดในแอปปฏิทินพร้อมกรอกให้แล้ว กดบันทึกด้วยนะ{_p()} "
            f"(เชื่อม Google Calendar ในหน้าตั้งค่า จะลงให้เลยไม่ต้องกด)")


def _log(kind, d, via):
    try:
        with open(os.path.join(config.DATA_DIR, "calendar_log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "via": via, **d},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def list_events(text):
    if not connected():
        try:                                            # ไม่ได้เชื่อม Google Calendar → อ่านปฏิทินในเครื่องแทน
            import proactive
            if "พรุ่งนี้" in text:
                line = proactive.agenda_line(1)
            elif re.search(r"สัปดาห์|อาทิตย์", text):
                line = None
            else:
                line = proactive.agenda_line(0)
            if line:
                return line
        except Exception:  # noqa: BLE001
            pass
        return (f"ยังอ่านปฏิทินไม่ได้{_p()} — เปิดสิทธิ์ปฏิทินในหน้า สิทธิ์ของผู้ช่วย "
                "หรือเชื่อม Google Calendar ที่ ⚙️ ตั้งค่า → 📅 Google Calendar")
    now = _now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "พรุ่งนี้" in text:
        start, end, label = day0 + timedelta(days=1), day0 + timedelta(days=2), "พรุ่งนี้"
    elif re.search(r"สัปดาห์|อาทิตย์", text):
        start, end, label = day0, day0 + timedelta(days=7), "7 วันนี้"
    else:
        start, end, label = day0, day0 + timedelta(days=1), "วันนี้"
    evs = _post({"action": "list", "start": start.isoformat(), "end": end.isoformat()}).get("events") or []
    if not evs:
        return f"{label}ไม่มีนัด{_p()}"
    lines = [f"{label}มี {len(evs)} นัด{_p()}"]
    for e in evs[:10]:
        s = datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone(_tz())
        when = "ทั้งวัน" if e.get("allDay") else f"{s:%H:%M}"
        day = "" if label != "7 วันนี้" else f"{_TH_DAYS[s.weekday()].replace('วัน', '')} "
        lines.append(f"• {day}{when} {e['title']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- บทสนทนา

def active():
    return bool(_S) and time.time() - _S.get("t", 0) < TTL


def _ask_next():
    f, q = _missing(_S["kind"], _S["data"])
    _S["t"] = time.time()
    if f:
        _S["ask"] = f
        _S["confirm"] = False
        return q
    _S["ask"] = None
    _S["confirm"] = True
    return f"สรุป {_summary(_S['kind'], _S['data'])} — ถูกต้องไหม{_p()} (บอก \"ใช่\" เพื่อบันทึก หรือบอกส่วนที่จะแก้)"


def start(kind, text):
    _S.clear()
    _S.update(kind=kind, data={}, ask=None, confirm=False, t=time.time())
    body = re.sub(_START_APPT if kind == "appt" else _START_JOB, "", text, count=1).strip()
    if body:
        _merge(kind, body, _S["data"], None)
    return _ask_next()


def handle_text(text, ctx=None):
    t = (text or "").strip()
    if not t:
        return None
    if _TEST.match(t):
        if not connected():
            return "ยังไม่ได้เชื่อม Google Calendar — ⚙️ ตั้งค่า → 📅 Google Calendar → 🔗 เชื่อม"
        try:
            d = _post({"action": "ping"})
            return f"✅ เชื่อม Google Calendar แล้ว (ปฏิทิน: {d.get('cal', '?')})"
        except Exception as e:  # noqa: BLE001
            return f"❗ เชื่อม Google Calendar ไม่ได้: {e}"
    if active():
        if _CANCEL.match(t):
            _S.clear()
            return f"ยกเลิกแล้ว{_p()}"
        kind = _S["kind"]
        if _S.get("confirm"):
            if _YES.match(t):
                data = dict(_S["data"])
                _S.clear()
                try:
                    return create(kind, data)
                except Exception as e:  # noqa: BLE001
                    return f"ลงปฏิทินไม่สำเร็จ: {e}"
            _merge(kind, t, _S["data"], None)        # แก้บางส่วน "เปลี่ยนเป็นบ่ายสาม"
            return _ask_next()
        _merge(kind, t, _S["data"], _S.get("ask"))
        return _ask_next()
    if _START_JOB.search(t):
        return start("job", t)
    if _START_APPT.search(t):
        return start("appt", t)
    if _LIST.search(t):
        try:
            return list_events(t)
        except Exception as e:  # noqa: BLE001
            return f"ดูปฏิทินไม่ได้: {e}"
    return None
