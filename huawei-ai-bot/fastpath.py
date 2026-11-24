"""ทางด่วน: งานที่สั่งบ่อย ทำให้เสร็จเร็ว (ไม่ให้ AI ไล่เรียกเครื่องมือทีละขั้น)

ไม่ใช้ AI เลย (1-3 วิ):      อ่านแจ้งเตือน · ตรวจเช็คเครื่อง · ตอบแชทคนที่ทักมา
ใช้ AI รอบเดียว (5-15 วิ):  หาข้อมูล/ข่าว/อากาศ (ค้นเว็บให้ก่อน) · อ่าน/สรุป/วิเคราะห์ไฟล์ (อ่านไฟล์ให้ก่อน)
"""
import json
import os
import re
import time



def _p():
    import voice_profile
    return voice_profile.pol()


def _clean(text):
    t = re.sub(r"\[[^\]]*\]", " ", text or "")
    return " ".join(t.split()).strip()


def _log(*a):
    print(time.strftime("[%H:%M:%S]"), "🚀", *a, flush=True)


# ---------------------------------------------------------------- แจ้งเตือน

_NOTIF = re.compile(r"(แจ้งเตือน|notification|ใครทัก|มีใครทัก|ใครส่งข้อความ|ข้อความเข้า|แชทเข้า|มีข้อความ|"
                    r"ข้อความใหม่|แชทใหม่|ใครแชท|อ่านข้อความ|อ่านแชท)", re.I)


def _notif_items():
    import phone_tools
    raw = phone_tools.run(["termux-notification-list"], timeout=20)
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return None, raw
    return [n for n in items if not str(n.get("packageName", "")).startswith("com.termux")], raw


def notifications():
    import notify_watch
    items, raw = _notif_items()
    if items is None:
        return ("อ่านแจ้งเตือนไม่ได้ — เปิดสิทธิ์: ตั้งค่า > การแจ้งเตือน > การเข้าถึงการแจ้งเตือน > Termux:API "
                f"({str(raw)[:80]})")
    if not items:
        return f"ตอนนี้ไม่มีการแจ้งเตือนค้างอยู่{_p()}"
    chats, other = [], []
    for n in items:
        app = notify_watch.APP_NAMES.get(n.get("packageName"), n.get("packageName", "").split(".")[-1])
        title = (n.get("title") or "").strip()
        body = (n.get("content") or "").strip().replace("\n", " ")
        if not title and not body:
            continue
        line = f"• [{app}] {title}" + (f": {body[:90]}" if body else "")
        (chats if app in notify_watch.CHAT_APPS else other).append(line)
    out = []
    if chats:
        out.append(f"💬 แชท/ข้อความ ({len(chats)}):\n" + "\n".join(chats[:10]))
    if other:
        out.append(f"🔔 อื่นๆ ({len(other)}):\n" + "\n".join(other[:8]))
    if chats:
        out.append("ตอบได้เลย เช่น: ตอบ [ชื่อ] ว่า [ข้อความ]")
    return "\n\n".join(out) or f"ไม่มีการแจ้งเตือนที่อ่านได้{_p()}"


# ---------------------------------------------------------------- ตรวจเช็คเครื่อง

_HEALTH = re.compile(r"((เช็ค|เช็ก|ตรวจ|ดู)\s*(สภาพ|สุขภาพ|สถานะ)?\s*(ตัว)?เครื่อง|เครื่อง\s*(ร้อน|ช้า|ค้าง|อืด|หน่วง)|"
                     r"สถานะเครื่อง|สุขภาพเครื่อง|แรมเหลือ|พื้นที่เหลือ|ความจุเหลือ)")


def _num(s, pat):
    m = re.search(pat, s or "")
    return float(m.group(1)) if m else None


_DEEP = re.compile(r"(ร้อน|อุณหภูมิ|cpu|แอปไหน|กินแรม|ละเอียด)", re.I)
_last_q = [""]


def health():
    import phone_tools
    try:
        info = json.loads(phone_tools.device_health({"quick": not _DEEP.search(_last_q[0])}, None))
    except (ValueError, TypeError):
        return None
    lines = [f"📱 สภาพเครื่องตอนนี้{_p()}"]
    icons = {"แบต": "🔋", "แรม": "🧠", "พื้นที่": "💾", "อุณหภูมิ CPU": "🌡️", "เปิดเครื่องมาแล้ว": "⏱️",
             "แอปที่ใช้แรมมากสุด": "📊"}
    for k, v in info.items():
        lines.append(f"{icons.get(k, '•')} {k}: {v}")
    tips = []
    bat_t = _num(info.get("แบต", ""), r"อุณหภูมิ\s*([\d.]+)")
    cpu_t = _num(info.get("อุณหภูมิ CPU", ""), r"([\d.]+)")
    ram = _num(info.get("แรม", ""), r"\((\d+)%\)")
    disk = _num(info.get("พื้นที่", ""), r"(\d+)%")
    pct = _num(info.get("แบต", ""), r"^(\d+)%")
    if (bat_t and bat_t >= 40) or (cpu_t and cpu_t >= 70):
        tips.append("เครื่องค่อนข้างร้อน — พักเครื่อง/ถอดเคส/หยุดเล่นเกมสักพัก")
    if ram and ram >= 85:
        tips.append("แรมใกล้เต็ม — สั่ง 'ล้างแรม' ได้เลย")
    if disk and disk >= 90:
        tips.append("พื้นที่ใกล้เต็ม — ลบคลิป/รูปที่ไม่ใช้ หรือแอปที่ไม่ได้ใช้")
    if pct is not None and pct <= 20 and "ชาร์จ" not in info.get("แบต", ""):
        tips.append("แบตต่ำ — เสียบชาร์จด้วย")
    lines.append("\n💡 " + ("\n💡 ".join(tips) if tips else "ทุกอย่างปกติดี"))
    return "\n".join(lines)


# ---------------------------------------------------------------- ตอบแชทคนที่ทักมา (ไม่ระบุแอป → ดูจากแจ้งเตือน)

_REPLY = re.compile(r"^(?:ช่วย)?\s*(?:ตอบ(?:กลับ)?|รีพลาย)\s*(?:แชท|ข้อความ)?\s*(?:ของ|ให้|หา|ไปหา)?\s*(?P<to>.+?)\s*"
                    r"(?:ว่า|บอกว่า)\s*(?P<msg>.+)$")
import chat_apps  # noqa: E402

# package → แอปที่ใช้ส่งข้อความ (แอป Facebook ส่งข้อความผ่าน Messenger)
_PKG_APP = {p: ("messenger" if k == "facebook" else k) for p, k in chat_apps.PKG_APP.items() if k in chat_apps.DM_APPS}
_LATEST = ("ล่าสุด", "คนล่าสุด", "แชทล่าสุด", "คนที่ทักมา", "คนที่ทักล่าสุด", "เมื่อกี้")


def reply_chat(text, ctx):
    m = _REPLY.match(_clean(text))
    if not m:
        return None
    import quick
    if re.search(quick._DM_APP, m.group("to"), re.I):
        return None                                   # ระบุแอปมาแล้ว → quick.dm จัดการ
    to, msg = m.group("to").strip(), m.group("msg").strip()
    items, _ = _notif_items()
    items = [n for n in (items or []) if n.get("packageName") in _PKG_APP or "gbox" in str(n.get("packageName"))]
    if any(w in to for w in _LATEST):
        hit = items[0] if items else None
    else:
        q = to.replace(" ", "").lower()
        hit = next((n for n in items if q in (n.get("title") or "").replace(" ", "").lower()), None)
    if not hit:
        return (f"ยังไม่รู้ว่า {to} ทักมาทางแอปไหน{_p()} — บอกแอปด้วยได้ไหม เช่น: ตอบ {to} ในไอจี ว่า {msg}")
    app = _PKG_APP.get(hit.get("packageName"))
    if not app:
        return f"เห็น {hit.get('title')} ทักมาทางแอปใน GBox — บอกชื่อแอปด้วย เช่น: ตอบ {to} ในไอจี ว่า {msg}"
    name = re.sub(r"\s*\(\d+.*\)$", "", (hit.get("title") or to)).strip()
    import share_tools
    res = share_tools.send_dm({"app": app, "to": name, "text": msg}, ctx)
    _log(f"reply {app} → {name}: {res[:120]}")
    if res.startswith("ERROR"):
        return "ส่งไม่สำเร็จ: " + res[6:].strip()
    return res.split(" (")[0] + f" {_p()}"


# ---------------------------------------------------------------- ไม่ใช้ AI

def direct(text, ctx=None):
    """คืนคำตอบทันที หรือ None"""
    t = _clean(text)
    if not t or len(t) > 200:
        return None
    try:
        r = reply_chat(t, ctx)
        if r:
            return r
        if len(t) <= 60 and _NOTIF.search(t) and not re.search(r"(ปิด|เปิด|ตั้ง|ล้าง|ลบ)\s*(การ)?แจ้งเตือน", t):
            _log("notifications")
            return notifications()
        if len(t) <= 60 and _HEALTH.search(t):
            _log("health")
            _last_q[0] = t
            return health()
    except Exception as e:  # noqa: BLE001
        _log("direct error", e)
    return None


# ---------------------------------------------------------------- เตรียมข้อมูลให้ AI (ตอบรอบเดียว ไม่ต้องเรียกเครื่องมือ)

_SEARCH = re.compile(r"(หาข้อมูล|ค้นหา|ค้นข้อมูล|เสิร์ช|search|ข่าว|สภาพอากาศ|อากาศ|พยากรณ์|ฝนตก|ราคา|อัตราแลกเปลี่ยน|"
                     r"ผลบอล|หวย|ล่าสุดเกี่ยวกับ)", re.I)
_FILE = re.compile(r"(สรุป|อ่าน|วิเคราะห์)\s*(ไฟล์|เอกสาร|รายงาน|pdf|excel|word|ตาราง|สไลด์|ข้อมูลในไฟล์)\s*(?P<q>.*)",
                   re.I)
_DEVICE_WORDS = re.compile(r"(เปิด|ปิด)\s*(wifi|ไวไฟ|บลูทูธ|แอป|แอพ)")


def _file_query(q):
    q = re.sub(r"(\s*(ให้หน่อย|หน่อย|ให้ที|ด้วย|ครับ|ค่ะ|นะ|ให้ฟัง|ให้ดู))+$", "", q.strip())
    q = re.sub(r"^(ชื่อ|ที่ชื่อ)\s*", "", q).strip()
    return "" if q in ("ล่าสุด", "อันล่าสุด", "เมื่อกี้", "") else q


def prefetch(text):
    """คืน (คำอธิบายสั้น, ข้อมูลที่เตรียมให้ AI) หรือ None"""
    t = _clean(text)
    if not t or _DEVICE_WORDS.search(t):
        return None
    fm = _FILE.search(t)
    if fm:
        import files_tools
        q = _file_query(fm.group("q"))
        hits = files_tools.find(q, limit=3)
        if not hits:
            return None                                # หาไม่เจอ → ให้ AI ค้นต่อเอง
        path = hits[0][2]
        res = files_tools.tool_read({"path": path}, None)
        if isinstance(res, dict) or str(res).startswith("ERROR"):
            return None
        others = "".join(f"\n- {h[2]}" for h in hits[1:])
        _log(f"file {os.path.basename(path)}")
        return (f"อ่านไฟล์ {os.path.basename(path)}",
                f"[ระบบอ่านไฟล์ให้แล้ว (ไฟล์ที่ตรงที่สุด){' ไฟล์อื่นที่ใกล้เคียง:' + others if others else ''}]\n{res}")
    if _SEARCH.search(t) and len(t) <= 200 and "ไฟล์" not in t:
        import websearch
        t0 = time.time()
        try:
            res = websearch.search(t)
        except Exception as e:  # noqa: BLE001
            _log("search error", e)
            return None
        _log(f"search {time.time() - t0:.1f}s")
        return ("ค้นเว็บ", f"[ผลค้นเว็บที่ระบบค้นให้แล้ว เวลา {time.strftime('%d/%m/%Y %H:%M')}]\n{str(res)[:6000]}")
    return None


FAST_HINT = ("[ข้อมูลที่ต้องใช้อยู่ด้านล่างแล้ว ตอบจากข้อมูลนี้เลย ไม่ต้องเรียกเครื่องมือ "
             "สรุปให้กระชับ ตรงคำถาม เป็นข้อๆ ถ้าข้อมูลไม่พอให้บอกตามจริง]")
