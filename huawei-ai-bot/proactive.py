"""ผู้ช่วยเชิงรุก (Proactive Assistant): ผู้ช่วยเป็นฝ่ายบอกก่อน ไม่ต้องรอให้สั่ง
1. สรุปตอนเช้า: ทักทาย + อากาศ + นัดวันนี้ + แชทที่ยังไม่ได้อ่าน (ครั้งแรกที่ใช้งานช่วงเช้า หรือสั่ง "สรุปเช้า")
2. เตือนก่อนนัด: อีก ~30 นาทีถึงนัด → บอกเอง (ครั้งเดียวต่อนัด)
4. แบตใกล้หมด (20% · 10%) / เครื่องร้อน → บอกเองครั้งเดียวต่อรอบ (PROACTIVE_BATTERY=0 ปิด)
3. สรุปแชทที่ยังไม่อ่าน: "มีใครทักมาบ้าง" · "ไลน์จากแม่ว่าอะไร" → อ่านให้ฟัง แล้วสั่ง "ตอบกลับว่า…" ได้ต่อทันที

นัดอ่านจากปฏิทินในเครื่อง (สิทธิ์ปฏิทิน) หรือ Google Calendar ที่เชื่อมไว้ · แชทอ่านจากแจ้งเตือนที่ค้างอยู่
ปิดได้: PROACTIVE=0 (ทั้งหมด) · PROACTIVE_EVENT_MIN=30 (เตือนก่อนนัดกี่นาที)
"""
import json
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta

import config

_say_q = queue.Queue()             # ข้อความที่อยากพูดเอง → โหมดเสียงหยิบไปพูดตอนว่าง
_lock = threading.Lock()


def on():
    return os.environ.get("PROACTIVE", "1").strip().lower() not in ("0", "false", "off", "no")


def _p():
    try:
        import voice_profile
        return voice_profile.pol()
    except Exception:  # noqa: BLE001
        return "ครับ"


def _now():
    try:
        import agent
        return agent.now_local().replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return datetime.now()


def _state():
    try:
        with open(os.path.join(config.DATA_DIR, "proactive.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(os.path.join(config.DATA_DIR, "proactive.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass


def _once(key):
    """จริงครั้งเดียวต่อ key (เก็บไว้ 3 วัน)"""
    with _lock:
        d = _state()
        if key in d:
            return False
        cut = time.time() - 3 * 86400
        d = {k: v for k, v in d.items() if v >= cut}
        d[key] = time.time()
        _save(d)
        return True


# ================================================================ นัดหมาย

def events(start, end):
    """นัดในช่วงเวลา → [{"title","start": datetime,"allDay": bool,"location"}] หรือ None ถ้าอ่านไม่ได้เลย"""
    out = None
    if config.ANDROID_APP and not config.MOCK_PHONE:
        try:
            import android_shim
            raw = str(android_shim.bridge().calendarEvents(int(start.timestamp() * 1000), int(end.timestamp() * 1000)))
            data = json.loads(raw)
            if isinstance(data, list):
                out = [{"title": e.get("title") or "(ไม่มีชื่อ)", "start": datetime.fromtimestamp(e["begin"] / 1000),
                        "allDay": bool(e.get("allDay")), "location": e.get("location") or ""} for e in data]
        except Exception as e:  # noqa: BLE001
            print(f"[proactive] calendar: {e}", flush=True)
    if out is None:
        try:
            import appoint
            if appoint.connected():
                evs = appoint._post({"action": "list", "start": start.isoformat(), "end": end.isoformat()}).get("events") or []
                out = []
                for e in evs:
                    s = datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone(appoint._tz()).replace(tzinfo=None)
                    out.append({"title": e.get("title") or "(ไม่มีชื่อ)", "start": s, "allDay": bool(e.get("allDay")),
                                "location": e.get("location") or ""})
        except Exception as e:  # noqa: BLE001
            print(f"[proactive] gcal: {e}", flush=True)
    if out is not None:
        out.sort(key=lambda e: (not e["allDay"], e["start"]))
    return out


def _fmt_event(e):
    when = "ทั้งวัน" if e["allDay"] else f"{e['start']:%H:%M}"
    return f"{when} {e['title']}" + (f" ที่ {e['location']}" if e.get("location") else "")


def agenda_line(day_offset=0):
    """ข้อความสั้นๆ ของนัดวันนี้/พรุ่งนี้ (None = อ่านปฏิทินไม่ได้)"""
    now = _now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    evs = events(day0, day0 + timedelta(days=1))
    if evs is None:
        return None
    label = "วันนี้" if day_offset == 0 else "พรุ่งนี้"
    if day_offset == 0:
        evs = [e for e in evs if e["allDay"] or e["start"] >= now - timedelta(minutes=30)]
    if not evs:
        return f"📅 {label}ไม่มีนัด"
    return f"📅 {label}มี {len(evs)} นัด: " + " · ".join(_fmt_event(e) for e in evs[:5])


# ================================================================ แชทที่ยังไม่อ่าน

_CHAT_PKGS = None


def unread(who=None, app=None):
    """แจ้งเตือนแชทที่ค้างอยู่ → [{"app","title","content"}] (รวมคนเดียวกัน)"""
    import notify_watch
    import phone_tools
    try:
        items = json.loads(phone_tools.run(["termux-notification-list"], timeout=30))
    except (ValueError, TypeError):
        return None
    merged = {}
    for n in items or []:
        name = notify_watch.APP_NAMES.get(n.get("packageName"), "")
        if name not in notify_watch.CHAT_APPS:
            continue
        title = (n.get("title") or "").strip()
        body = (n.get("content") or "").strip()
        if not title or not body or notify_watch._SKIP_TITLES.match(title):
            continue
        if app and notify_watch.APP_KEY.get(name) != app:
            continue
        if who and who not in title and title not in who:
            continue
        k = (name, title)
        if k in merged:
            if body not in merged[k]["content"]:
                merged[k]["content"] += " / " + body
        else:
            merged[k] = {"app": name, "title": title, "content": body, "packageName": n.get("packageName"),
                         "key": n.get("key") or ""}
    return list(merged.values())


def unread_line(max_people=4):
    got = unread()
    if not got:
        return None if got is None else ""
    people = [f"{u['title']} ({u['app']})" for u in got[:max_people]]
    more = f" และอีก {len(got) - max_people} คน" if len(got) > max_people else ""
    return f"💬 มีข้อความที่ยังไม่อ่านจาก " + ", ".join(people) + more


# ================================================================ สรุปตอนเช้า

def _greet(h):
    if h < 11:
        return "☀️ อรุณสวัสดิ์"
    if h < 17:
        return "🌤️ สวัสดีตอนบ่าย"
    return "🌙 สวัสดีตอนเย็น"


def briefing(full=True):
    """สรุปวันนี้: ทักทาย · อากาศ · นัด · แชทค้าง"""
    now = _now()
    lines = [f"{_greet(now.hour)}{_p()} วันนี้{_TH_DAY[now.weekday()]}ที่ {now.day} {_TH_MON[now.month - 1]}"]
    try:
        import info
        w = info.weather(None, 0)
        if w and not w.startswith("ERROR"):
            lines.append(w.strip())
    except Exception:  # noqa: BLE001
        pass
    a = agenda_line(0)
    if a:
        lines.append(a)
    elif full:
        lines.append("📅 ยังอ่านปฏิทินไม่ได้ (เปิดสิทธิ์ปฏิทินในหน้า สิทธิ์ของผู้ช่วย)")
    try:
        u = unread_line()
        if u:
            lines.append(u + " — ถามได้ว่า \"ใครทักมาว่าอะไร\"")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


_TH_DAY = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
_TH_MON = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
           "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


# ================================================================ คิดเองเป็นรอบ (เรียกจาก mind ทุก ~5 นาที)

def event_alerts(lead_min=None):
    """นัดที่ใกล้ถึง (ภายใน lead นาที) ที่ยังไม่เคยเตือน → ข้อความ"""
    lead = lead_min or int(os.environ.get("PROACTIVE_EVENT_MIN", "30"))
    now = _now()
    evs = events(now, now + timedelta(minutes=lead + 1)) or []
    out = []
    for e in evs:
        if e["allDay"] or e["start"] < now or e["start"] > now + timedelta(minutes=lead + 1):
            continue
        if not _once(f"ev|{e['title']}|{e['start']:%Y%m%d%H%M}"):
            continue
        mins = max(1, round((e["start"] - now).total_seconds() / 60))
        out.append(f"⏰ อีก {mins} นาทีมีนัด \"{e['title']}\" ตอน {e['start']:%H:%M}"
                   + (f" ที่ {e['location']}" if e.get("location") else "") + f" นะ{_p()}")
    return out


def _forget(prefix):
    with _lock:
        d = _state()
        if any(k.startswith(prefix) for k in d):
            _save({k: v for k, v in d.items() if not k.startswith(prefix)})


def battery_alerts():
    """แบตใกล้หมด (20% · 10%) ตอนไม่ได้ชาร์จ / เครื่องร้อน → บอกเอง ครั้งเดียวต่อรอบการใช้แบต
    เสียบชาร์จแล้ว = เริ่มนับใหม่ · ปิดได้: PROACTIVE_BATTERY=0"""
    if os.environ.get("PROACTIVE_BATTERY", "1").strip().lower() in ("0", "off", "false", "no"):
        return []
    import phone_tools
    try:
        b = json.loads(phone_tools.battery_status({}, None) or "")
        pct = int(float(b.get("percentage")))
    except (ValueError, TypeError, AttributeError):
        return []
    status = str(b.get("status", "")).upper()
    out = []
    if status in ("CHARGING", "FULL"):
        _forget("bat|")                                   # ชาร์จแล้ว → รอบหน้าแบตลดอีกค่อยเตือนใหม่
    else:
        for lvl in (10, 20):
            if pct <= lvl:
                if _once(f"bat|{lvl}"):
                    out.append(f"แบตเหลือ {pct}% แล้ว{' ใกล้หมดมาก' if lvl == 10 else ''} เสียบชาร์จด้วยนะ{_p()}")
                break
    try:
        temp = float(b.get("temperature"))
    except (TypeError, ValueError):
        temp = None
    if temp is not None and temp >= 42 and _once(f"hot|{_now():%Y%m%d%H}"):
        out.append(f"เครื่องร้อน {round(temp)} องศาแล้ว พักเครื่องหรือถอดเคสสักครู่นะ{_p()}")
    return out


def tick():
    """หนึ่งรอบความคิด → รายการข้อความที่ควรบอกผู้ใช้ตอนนี้"""
    if not on() or config.paused():
        return []
    msgs = []
    try:
        msgs += event_alerts()
    except Exception as e:  # noqa: BLE001
        print(f"[proactive] alerts: {e}", flush=True)
    try:
        msgs += battery_alerts()
    except Exception as e:  # noqa: BLE001
        print(f"[proactive] battery: {e}", flush=True)
    now = _now()
    if 6 <= now.hour < 11 and _once(f"brief|{now:%Y%m%d}"):
        try:
            msgs.append(briefing(full=False))
        except Exception as e:  # noqa: BLE001
            print(f"[proactive] brief: {e}", flush=True)
    for m in msgs:
        if _say_q.qsize() < 10:
            _say_q.put((time.time(), m))
    return msgs


def pending_speech():
    """ข้อความที่รอให้โหมดเสียงพูด (ดึงออกทั้งหมด)"""
    got = []
    while not _say_q.empty():
        t, m = _say_q.get_nowait()
        if time.time() - t < 15 * 60:                   # เก่าเกิน 15 นาที (ไม่ได้เปิดโหมดเสียง) → ไม่พูดย้อนหลัง
            got.append(m)
    if not got or os.environ.get("PROACTIVE_SPEAK", "1").strip() in ("0", "off", "false"):
        return []
    try:
        import notify_watch
        if notify_watch._quiet_now():                    # ช่วงเวลาห้ามรบกวนที่ตั้งไว้ → ไม่พูด (ยังขึ้นในแชท)
            return []
    except Exception:  # noqa: BLE001
        pass
    return got


def spoken(text):
    """ตัดอีโมจิ/เครื่องหมายที่ไม่ควรอ่านออกเสียง"""
    t = re.sub(r"[☀️🌤🌙📅💬⏰🌧☔🌡️💨]+", "", text)
    t = t.replace(" · ", ", ").replace("\n", " ")
    t = re.sub(r"\(.*?\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ================================================================ คำสั่ง

_BRIEF = re.compile(r"^(?:ช่วย)?\s*(?:สรุป(?:ตอน)?เช้า|สรุปวันนี้|บรีฟ(?:วันนี้)?|briefing|วันนี้มีอะไรบ้าง|"
                    r"สรุปให้ฟังหน่อยวันนี้|มีอะไรใหม่(?:บ้าง)?|อรุณสวัสดิ์(?:ผู้ช่วย)?)"
                    r"\s*(?:หน่อย|ให้หน่อย|ที|ครับ|ค่ะ|คะ|นะ)*$", re.I)
import chat_apps  # noqa: E402

_APP_RX = chat_apps.rx(("line", "instagram", "messenger", "facebook", "whatsapp", "telegram"))
_WHO_SAID = re.compile(r"^(?:(?P<app>" + _APP_RX + r")\s*)?(?:จาก|ของ)?\s*(?P<who>.+?)\s*"
                       r"(?:ทัก(?:มา)?|ส่ง(?:มา)?|พิมพ์มา|บอก)?\s*(?:ว่า)\s*(?:อะไร|ไง|ยังไง)"
                       r"(?:\s*(?:ใน|ทาง)\s*(?P<app2>" + _APP_RX + r"))?\s*(?:บ้าง|หน่อย|ครับ|ค่ะ|คะ|นะ)*$", re.I)
_ANY_UNREAD = re.compile(r"^(?:มี)?(?:ใคร|คน)?\s*(?:ทัก|ส่งข้อความ|แชท)\s*(?:มา)?\s*(?:หา(?:ผม|ฉัน|เรา)?)?\s*(?:บ้าง|ไหม|มั้ย)|"
                         r"^(?:สรุป|อ่าน)\s*(?:แชท|ข้อความ)\s*(?:ที่)?\s*(?:ยังไม่(?:ได้)?อ่าน|ค้าง|ใหม่)?|"
                         r"^มี(?:แชท|ข้อความ)\s*(?:ใหม่)?\s*(?:ไหม|มั้ย|บ้าง|อะไรบ้าง)", re.I)


def _read_out(got, who_label=None):
    if not got:
        return f"ไม่มีข้อความค้างจาก{who_label}{_p()}" if who_label else f"ไม่มีแชทที่ยังไม่อ่าน{_p()}"
    lines = []
    for u in got[:5]:
        c = u["content"] if len(u["content"]) <= 160 else u["content"][:160] + "…"
        lines.append(f"• {u['title']} ({u['app']}): {c}")
    more = f"\n(และอีก {len(got) - 5} คน)" if len(got) > 5 else ""
    try:
        import notify_watch
        notify_watch.remember_last(dict(got[0]))           # "ตอบกลับว่า…" จะตอบคนแรกที่อ่านให้ฟัง
    except Exception:  # noqa: BLE001
        pass
    head = f"💬 ข้อความที่ยังไม่อ่าน {len(got)} คน{_p()}\n" if len(got) > 1 else ""
    return head + "\n".join(lines) + more + f"\nจะตอบ บอกได้เลย เช่น \"ตอบกลับว่า เดี๋ยวโทรกลับ\""


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?!.")
    if not t or len(t) > 80:
        return None
    if _BRIEF.match(t):
        return briefing()
    m = _WHO_SAID.match(t)
    if m:
        who = m.group("who").strip()
        who = re.sub(r"^(?:ข้อความ|แชท)\s*(?:จาก|ของ)?\s*", "", who).strip()
        app = chat_apps.key(m.group("app") or m.group("app2") or "", dm=True)    # "เฟส" = messenger
        generic = re.fullmatch(r"(?:ใคร|คน|มีใคร|ใครบ้าง)", who)
        chat_cue = app or re.search(r"ทัก|ส่ง(?:มา)?\s*ว่า|พิมพ์มา|แชท|ข้อความ", t)
        if generic and chat_cue:
            got = unread()
            if got is None:
                return f"อ่านแจ้งเตือนไม่ได้{_p()} — เปิดสิทธิ์ \"อ่านการแจ้งเตือน\" ให้ผู้ช่วยก่อน"
            return _read_out(got)
        if who and chat_cue and not generic and not re.fullmatch(r"(?:เขา|มัน|นี่|นั่น|อัน)", who):
            got = unread(who=who, app=app)
            if got is None:
                return f"อ่านแจ้งเตือนไม่ได้{_p()} — เปิดสิทธิ์ \"อ่านการแจ้งเตือน\" ให้ผู้ช่วยก่อน"
            return _read_out(got, who)
    if _ANY_UNREAD.match(t):
        got = unread()
        if got is None:
            return f"อ่านแจ้งเตือนไม่ได้{_p()} — เปิดสิทธิ์ \"อ่านการแจ้งเตือน\" ให้ผู้ช่วยก่อน"
        return _read_out(got)
    return None
