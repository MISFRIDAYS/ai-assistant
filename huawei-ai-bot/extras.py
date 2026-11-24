"""ความสามารถเสริม:
- ความจำระยะยาว ("จำไว้ว่า...") ใส่ในสมองบอททุกครั้ง
- งานตามเวลา: เตือนรายวัน / ให้ AI ทำงานตามเวลา (เช่น สรุปข่าว+อากาศทุกเช้า 7 โมง)
- นับการใช้ token และประมาณค่าใช้จ่าย
- แจ้งเตือนแบตใกล้หมด / ชาร์จเต็ม / เครื่องร้อน
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

import config

_lock = threading.Lock()


def _path(name):
    return os.path.join(config.DATA_DIR, name)


def _load(name, default):
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(name, data):
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(name))


# ---------------------------------------------------------------- ความจำระยะยาว

def memories():
    return _load("memory.json", [])


def memory_prompt():
    items = memories()
    if not items:
        return ""
    lines = "\n".join(f"- {m['text']}" for m in items[-60:])
    return f"\n\nสิ่งที่ผู้ใช้เคยบอกให้จำไว้ (ใช้ประกอบการตอบเสมอ):\n{lines}"


def remember(a, ctx):
    text = a["text"].strip()
    with _lock:
        items = memories()
        if any(m["text"] == text for m in items):
            return "จำไว้แล้วตั้งแต่ก่อนหน้านี้"
        items.append({"id": uuid.uuid4().hex[:6], "text": text, "t": time.strftime("%Y-%m-%d")})
        _save("memory.json", items[-200:])
    return f"จำแล้ว: {text}"


def forget(a, ctx):
    q = (a.get("query") or "").strip().lower()
    with _lock:
        items = memories()
        if q in ("ทั้งหมด", "all", "*"):
            _save("memory.json", [])
            return f"ลืมทั้งหมดแล้ว ({len(items)} เรื่อง)"
        keep = [m for m in items if q not in m["text"].lower()]
        _save("memory.json", keep)
    n = len(items) - len(keep)
    return f"ลืมแล้ว {n} เรื่อง" if n else "ไม่พบเรื่องที่ตรงกัน"


# ---------------------------------------------------------------- งานตามเวลา

def _now():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS)))


def _next_time(hhmm, repeat, after=None):
    """เวลาครั้งถัดไป (epoch) ของ HH:MM ตามรอบ daily/weekdays/weekends/once"""
    h, m = [int(x) for x in hhmm.split(":")]
    base = after or _now()
    cand = base.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= base:
        cand += timedelta(days=1)
    for _ in range(8):
        wd = cand.weekday()
        if (repeat == "weekdays" and wd >= 5) or (repeat == "weekends" and wd < 5):
            cand += timedelta(days=1)
            continue
        break
    return cand.timestamp()


def schedule(a, ctx):
    hhmm = a["time"].strip().replace(".", ":")
    if ":" not in hhmm:
        hhmm += ":00"
    repeat = a.get("repeat", "once")
    kind = a.get("kind", "remind")
    item = {"id": uuid.uuid4().hex[:6], "chat_id": ctx.chat_id, "due": _next_time(hhmm, repeat),
            "text": a["text"], "kind": kind, "repeat": repeat, "time": hhmm,
            "speak": bool(a.get("speak", kind == "task"))}
    import bot
    with bot._reminder_lock:
        items = bot._load_reminders()
        items.append(item)
        bot._save_reminders(items)
    when = {"once": "ครั้งเดียว", "daily": "ทุกวัน", "weekdays": "ทุกวันจันทร์-ศุกร์",
            "weekends": "ทุกเสาร์-อาทิตย์"}.get(repeat, repeat)
    what = "ให้ AI ทำงาน" if kind == "task" else "เตือน"
    return f"ตั้งแล้ว (รหัส {item['id']}): {what} '{a['text']}' เวลา {hhmm} {when}"


def list_schedules(a, ctx):
    import bot
    items = [r for r in bot._load_reminders() if r.get("chat_id") == ctx.chat_id]
    if not items:
        return "ยังไม่มีงานหรือการเตือนที่ตั้งไว้"
    out = []
    for r in sorted(items, key=lambda r: r["due"]):
        when = time.strftime("%d/%m %H:%M", time.gmtime(r["due"] + config.TIMEZONE_OFFSET_HOURS * 3600))
        out.append(f"[{r.get('id', '-')}] {when} {r.get('repeat', 'once')} "
                   f"{'🤖' if r.get('kind') == 'task' else '⏰'} {r['text']}")
    return "\n".join(out)


def cancel_schedule(a, ctx):
    import bot
    q = a["id_or_text"].strip().lower()
    with bot._reminder_lock:
        items = bot._load_reminders()
        keep = [r for r in items if not (r.get("chat_id") == ctx.chat_id and
                                         (r.get("id") == q or q in r["text"].lower()))]
        bot._save_reminders(keep)
    n = len(items) - len(keep)
    return f"ยกเลิกแล้ว {n} รายการ" if n else "ไม่พบรายการที่ตรงกัน"


def reschedule(item):
    """งานที่ทำซ้ำ → คำนวณรอบถัดไป (คืน None ถ้าเป็นครั้งเดียว)"""
    if item.get("repeat", "once") == "once" or not item.get("time"):
        return None
    nxt = dict(item)
    nxt["due"] = _next_time(item["time"], item["repeat"], after=_now() + timedelta(minutes=1))
    return nxt


# ---------------------------------------------------------------- นับการใช้งาน

PRICES = {  # USD ต่อ 1 ล้าน token (input, output) — ประมาณการ (ollama/groq/gemini ฟรี)
    "ollama:": (0.0, 0.0), "groq:": (0.0, 0.0), "cloud:": (0.0, 0.0),   # cloud = จ่ายรายเดือนแล้ว
    "haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0), "gemini": (0.0, 0.0),
}


def _price(model):
    return next((v for n, v in PRICES.items() if n in model.lower()), (3.0, 15.0))


def _cost(model, m):
    """ราคา USD จากตัวนับ: in/out/cache(อ่าน)/w5m,w1h(เขียนแคช)/search(ค้นเว็บ)"""
    p_in, p_out = _price(model)
    usd = (m.get("in", 0) * p_in + m.get("cache", 0) * p_in * 0.1 + m.get("w5m", 0) * p_in * 1.25
           + m.get("w1h", 0) * p_in * 2.0 + m.get("out", 0) * p_out) / 1e6
    if p_in > 0:
        usd += m.get("search", 0) * 0.01                    # ค้นเว็บ $10 ต่อ 1,000 ครั้ง
    return usd


def _counts(usage):
    """แปลง usage จาก API เป็นตัวนับ (เขียนแคช 5 นาที = 1.25 เท่า, 1 ชม. = 2 เท่าของราคา input)"""
    cc = usage.get("cache_creation") or {}
    w1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
    w5m = int(cc.get("ephemeral_5m_input_tokens") or 0)
    if not cc:
        w5m = int(usage.get("cache_creation_input_tokens") or 0)
    return {"in": int(usage.get("input_tokens") or 0), "out": int(usage.get("output_tokens") or 0),
            "cache": int(usage.get("cache_read_input_tokens") or 0), "w5m": w5m, "w1h": w1h,
            "search": int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0)}


def record_usage(who, usage):
    model = {"Gemini": config.GEMINI_MODEL, "Groq": f"groq:{config.GROQ_MODEL}",
             "Ollama": f"ollama:{config.OLLAMA_MODEL}", "Cloud": f"cloud:{config.CLOUD_MODEL}"}.get(
        who, config.CLAUDE_MODEL)
    day = time.strftime("%Y-%m-%d")
    c = _counts(usage)
    usd = _cost(model, c)
    with _lock:
        data = _load("usage.json", {})
        d = data.setdefault(day, {})
        m = d.setdefault(model, {"in": 0, "out": 0, "cache": 0, "calls": 0})
        for k, v in c.items():
            m[k] = m.get(k, 0) + v
        m["calls"] += 1
        for k in sorted(data)[:-35]:      # เก็บแค่ ~1 เดือน
            data.pop(k)
        _save("usage.json", data)
        if usd > 0:
            b = _load("balance.json", {})
            b["spent_total"] = b.get("spent_total", 0.0) + usd          # ตัวนับสะสม (ใช้หาค่าครั้งนี้)
            if b.get("usd") is not None:
                b["usd"] = b["usd"] - usd
            _save("balance.json", b)
    return usd


def spent_today():
    """ค่า AI ที่เสียเงินจริงวันนี้ (USD)"""
    d = _load("usage.json", {}).get(time.strftime("%Y-%m-%d"), {})
    return sum(_cost(m, v) for m, v in d.items())


def over_budget():
    """True = ใช้ AI ที่เสียเงินเกินงบวันนี้แล้ว (DAILY_BUDGET_USD)"""
    lim = getattr(config, "DAILY_BUDGET_USD", 0) or 0
    if lim <= 0:
        return False
    try:
        return spent_today() >= lim
    except Exception:  # noqa: BLE001
        return False


def usage_report(days=1):
    data = _load("usage.json", {})
    keys = sorted(data)[-days:]
    total_usd, lines = 0.0, []
    for k in keys:
        for model, m in data[k].items():
            usd = _cost(model, m)
            total_usd += usd
            w, search = m.get("w5m", 0) + m.get("w1h", 0), m.get("search", 0)
            extra = f" เขียนแคช {w:,}" if w else ""
            extra += f" ค้นเว็บ {search} ครั้ง" if search else ""
            lines.append(f"{k} {model}: {m['calls']} ครั้ง, in {m['in']:,} cache {m['cache']:,}{extra} "
                         f"out {m['out']:,} ≈ ${usd:.3f}")
    return "\n".join(lines) or "ยังไม่มีการใช้งาน", total_usd


# ---------------------------------------------------------------- ยอดเงิน API คงเหลือ
# Anthropic ไม่มี API ให้อ่านยอดเครดิต → ผู้ใช้ตั้งยอดจากหน้าเว็บครั้งเดียว แล้วบอทหักตามที่ใช้จริง

_rate = {"v": None, "t": 0.0}


def usd_thb():
    """อัตราแลกเปลี่ยน USD→บาท (ดึงใหม่วันละครั้ง ถ้าดึงไม่ได้ใช้ค่าใน .env)"""
    if _rate["v"] and time.time() - _rate["t"] < 86400:
        return _rate["v"]
    cached = _load("fx.json", {})
    if cached.get("v") and time.time() - cached.get("t", 0) < 86400:
        _rate.update(cached)
        return _rate["v"]
    if not config.MOCK_PHONE:
        try:
            import requests
            v = float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=8).json()["rates"]["THB"])
            if 20 < v < 60:
                _rate.update(v=v, t=time.time())
                _save("fx.json", dict(_rate))
                return v
        except Exception:  # noqa: BLE001
            pass
    return cached.get("v") or config.USD_THB


def baht(usd):
    v = usd * usd_thb()
    return f"฿{v:,.2f}" if abs(v) < 10 else f"฿{v:,.0f}" if abs(v) >= 100 else f"฿{v:,.1f}"


def spent_counter():
    return _load("balance.json", {}).get("spent_total", 0.0)


def set_balance(usd):
    with _lock:
        b = _load("balance.json", {})
        b.update(usd=float(usd), set_at=time.strftime("%Y-%m-%d %H:%M"), warned=False, out=False)
        _save("balance.json", b)


def mark_out_of_credit():
    with _lock:
        b = _load("balance.json", {})
        b.update(usd=0.0, out=True)
        _save("balance.json", b)


def balance():
    """คืน dict: usd (None ถ้ายังไม่ตั้ง), set_at, out"""
    return _load("balance.json", {})


def balance_text():
    b = balance()
    if b.get("usd") is None:
        return ("💰 ยังไม่ได้ตั้งยอดเงินคงเหลือ\n"
                "ดูยอด Credit ที่ console.anthropic.com แล้วพิมพ์ เช่น /balance 4.85")
    left = max(0.0, b["usd"])
    status = "🔴 เครดิตหมดแล้ว" if b.get("out") else ("🟠 ใกล้หมด" if left < config.LOW_BALANCE_USD else "🟢")
    return (f"💰 ยอด API Claude คงเหลือ ≈ {baht(left)} (${left:.2f}) {status}\n"
            f"ตั้งยอดล่าสุดเมื่อ {b.get('set_at', '-')} · เรต 1$ = {usd_thb():.2f} บาท\n"
            "ตัวเลขนี้บอทคำนวณเอง อาจคลาดเคลื่อนเล็กน้อย — เติมเงินแล้วพิมพ์ /balance <ยอดใหม่> เพื่อตั้งใหม่")


def cost_footer(cost_usd):
    """บรรทัดท้ายข้อความหลังคุยแต่ละครั้ง (คืน '' ถ้าไม่ต้องแสดง)"""
    if not config.SHOW_BALANCE:
        return ""
    usd_thb()                       # ดึงเรตก่อนล็อก (อาจต้องใช้เน็ต)
    with _lock:
        b = _load("balance.json", {})
        if b.get("usd") is None:
            if cost_usd <= 0 or b.get("hinted"):
                return ""
            b["hinted"] = True
            _save("balance.json", b)
            return f"💸 ครั้งนี้ {baht(cost_usd)} · ตั้งยอดคงเหลือเพื่อติดตาม: /balance 4.85"
        left = max(0.0, b["usd"])
        line = (f"💸 ครั้งนี้ {baht(cost_usd)} · คงเหลือ ≈ {baht(left)}" if cost_usd > 0
                else f"🆓 ครั้งนี้ฟรี · คงเหลือ ≈ {baht(left)}")
        if b.get("out"):
            line += "\n🔴 เครดิต Claude หมดแล้ว — เติมที่ console.anthropic.com แล้วพิมพ์ /balance <ยอดใหม่>"
        elif left < config.LOW_BALANCE_USD and not b.get("warned"):
            b["warned"] = True
            _save("balance.json", b)
            line += "\n🟠 ใกล้หมดแล้ว — เติมได้ที่ console.anthropic.com"
        return line


# ---------------------------------------------------------------- แจ้งเตือนสภาพเครื่อง

_alert = {"low": False, "full": False, "hot": False, "t": 0.0}


def check_device_alerts():
    """คืนข้อความแจ้งเตือน (ถ้ามี) — เรียกทุก 5 นาที"""
    if not config.DEVICE_ALERTS or time.time() - _alert["t"] < 300:
        return []
    _alert["t"] = time.time()
    import phone_tools
    try:
        b = json.loads(phone_tools.run(["termux-battery-status"]))
    except Exception:  # noqa: BLE001
        return []
    out = []
    pct, temp = b.get("percentage", 100), b.get("temperature", 30)
    plugged = b.get("plugged") not in (None, "UNPLUGGED")
    if pct <= config.BATTERY_LOW and not plugged:
        if not _alert["low"]:
            out.append(f"🔋 แบตเหลือ {pct}% แล้ว เสียบชาร์จด้วยนะครับ")
            _alert["low"] = True
    elif pct > config.BATTERY_LOW + 5 or plugged:
        _alert["low"] = False
    if plugged and pct >= 100:
        if not _alert["full"]:
            out.append("🔌 ชาร์จเต็ม 100% แล้วครับ ถอดสายได้")
            _alert["full"] = True
    elif not plugged:
        _alert["full"] = False
    if temp >= 45:
        if not _alert["hot"]:
            out.append(f"🌡️ เครื่องร้อน {temp:.0f}°C — ลองปิดแอปที่ไม่ใช้ หรือพักเครื่องสักครู่")
            _alert["hot"] = True
    elif temp < 41:
        _alert["hot"] = False
    return out


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "api_balance": (lambda a, ctx: balance_text(), "ดูยอดเงิน API Claude คงเหลือ (บาท) เมื่อผู้ใช้ถามว่าเครดิต/เงินเหลือเท่าไหร่",
                    _obj(), False),
    "remember": (remember, "จำข้อมูลของผู้ใช้ไว้ถาวร (ชื่อ ความชอบ ชื่อเล่นคนรู้จัก นิสัยการใช้งาน) "
                           "ใช้เมื่อผู้ใช้บอก 'จำไว้ว่า...' หรือบอกข้อมูลส่วนตัวที่ควรจำ",
                 _obj({"text": {"type": "string", "description": "ประโยคสั้นๆ เช่น 'แม่ชื่อสมศรี เบอร์ 081...'"}},
                      ["text"]), False),
    "forget": (forget, "ลืมเรื่องที่เคยจำ (ใส่คำค้น หรือ 'ทั้งหมด')",
               _obj({"query": {"type": "string"}}, ["query"]), False),
    "schedule": (schedule,
                 "ตั้งงานตามเวลา: kind=remind เตือนข้อความ / kind=task ให้ AI ทำงานตามคำสั่งเมื่อถึงเวลา "
                 "(เช่น 'สรุปข่าวและอากาศวันนี้') ส่งผลเข้า Telegram และพูดออกลำโพง; repeat=once/daily/weekdays/weekends",
                 _obj({"time": {"type": "string", "description": "HH:MM แบบ 24 ชม. เช่น 07:00"},
                       "text": {"type": "string", "description": "ข้อความเตือน หรือคำสั่งให้ AI ทำ"},
                       "kind": {"type": "string", "enum": ["remind", "task"]},
                       "repeat": {"type": "string", "enum": ["once", "daily", "weekdays", "weekends"]},
                       "speak": {"type": "boolean", "description": "พูดออกลำโพงแท็บเล็ตด้วย"}},
                      ["time", "text"]), False),
    "list_schedules": (list_schedules, "ดูงาน/การเตือนที่ตั้งไว้ทั้งหมด", _obj(), False),
    "cancel_schedule": (cancel_schedule, "ยกเลิกงาน/การเตือน (ใส่รหัส หรือคำในข้อความ)",
                        _obj({"id_or_text": {"type": "string"}}, ["id_or_text"]), False),
}
