"""อ่านรายชื่อจากหน้ารายการแชทของทุกแอป (LINE, Messenger, Instagram, WhatsApp, Telegram)
→ จำว่าใครอยู่แอปไหน ตั้งแต่วันแรก ไม่ต้องรอให้เขาทักมาก่อน

ปลอดภัย: แค่เปิดหน้ารายการแชทแล้ว "อ่าน" ชื่อ ไม่กดเข้าแชท ไม่พิมพ์ ไม่ส่งอะไร
สั่ง: "จำรายชื่อจากแชท" / "อ่านรายชื่อทุกแอป" / "สแกนรายชื่อ" (ปุ่มในหน้า 👥 คนที่จำได้)
"""
import re
import threading
import time

import config

APPS = [("line", "jp.naver.line.android"), ("messenger", "com.facebook.orca"),
        ("instagram", "com.instagram.android"), ("whatsapp", "com.whatsapp"), ("telegram", "org.telegram.messenger")]
PAGES = 4                                   # เลื่อนดูกี่หน้าต่อแอป

_CMD = re.compile(r"^(ช่วย)?\s*(จำ|อ่าน|สแกน|ดึง|อัปเดต|อัพเดท)\s*(รายชื่อ|ชื่อคน|รายชื่อคน)\s*(จาก|ใน|ทุก)?\s*"
                  r"(แชท|แอป|ทุกแอป|แชททุกแอป|ทั้งหมด)?", re.I)
_NOT_NAME = re.compile(
    r"^(แชท|chats?|ข้อความ|messages?|inbox|ค้นหา|search|ทั้งหมด|all|คำขอ|requests?|primary|general|หลัก|ทั่วไป|"
    r"notes?|โน้ต|stories|สตอรี่|ช่อง|channels?|ชุมชน|communities|calls?|โทร|สาย|updates?|อัปเดต|status|สถานะ|"
    r"เพื่อน|friends|หน้าหลัก|home|ข่าว|news|today|voom|วูม|wallet|วอลเล็ท|ตั้งค่า|settings|archived|เก็บถาวร|"
    r"active now|กำลังใช้งาน|ออนไลน์|online|เมื่อวาน|yesterday|วันนี้|you|คุณ|ฉัน|me|meta ai|ai)$", re.I)
_TIME = re.compile(r"^(\d{1,2}[:.]\d{2}(\s*(น\.|am|pm))?|\d{1,2}/\d{1,2}(/\d{2,4})?|\d+\s*(นาที|ชม\.?|ชั่วโมง|วัน|"
                   r"สัปดาห์|w|d|h|m|min|hr)s?(\s*ที่แล้ว|\s*ago)?|(จ|อ|พ|พฤ|ศ|ส|อา)\.|"
                   r"(mon|tue|wed|thu|fri|sat|sun)\w*|\d+)$", re.I)
_state = {"running": False, "last": ""}


def _p():
    try:
        import voice_profile
        return voice_profile.pol()
    except Exception:  # noqa: BLE001
        return "ครับ"


def _clean(t):
    t = re.sub(r"\s*\(\d+\)$", "", (t or "").strip())         # "กลุ่มงาน (25)" → "กลุ่มงาน"
    t = re.sub(r"^(ออนไลน์|online)\s*[·•]?\s*", "", t, flags=re.I)
    return t.strip()


def names_on_screen(items, width):
    """แถวรายการแชท = กล่องที่กดได้กว้างเกินครึ่งจอ → ข้อความบนสุดในแถว (ที่ไม่ใช่เวลา/ตัวเลข) คือชื่อ"""
    rows = [e for e in items if e.get("click") and (e["box"][2] - e["box"][0]) > width * 0.5
            and 60 <= (e["box"][3] - e["box"][1]) <= 420]
    out = []
    for r in rows:
        x1, y1, x2, y2 = r["box"]
        inside = [e for e in items if e is not r and e.get("text")
                  and x1 <= e["x"] <= x2 and y1 <= e["y"] <= y2]
        inside.sort(key=lambda e: (e["box"][1], e["box"][0]))
        for e in inside:
            t = _clean(e["text"])
            if not t or _TIME.match(t) or _NOT_NAME.match(t):
                continue
            if 2 <= len(t) <= 40 and "\n" not in t and not t.endswith(("…", "...")) and \
                    not re.search(r"^(คุณ|you)\s*[:：]|ส่ง(รูป|สติกเกอร์|ข้อความ)|sent (a|an) |https?://", t, re.I):
                out.append(t)
            break                                   # เอาแค่ข้อความบนสุดของแถว (ชื่อ) ข้ามข้อความตัวอย่างแชท
    seen, res = set(), []
    for n in out:
        if n.lower() not in seen:
            seen.add(n.lower())
            res.append(n)
    return res


def _installed():
    import phone_tools
    have = {c.split("/")[0] for c in phone_tools._launcher_components()}
    return [(k, p) for k, p in APPS if p in have]


def scan(ctx=None, apps=None, pages=PAGES):
    """เปิดหน้ารายการแชททีละแอป → อ่านชื่อ → เลื่อน → จำ คืนสรุป"""
    import contacts
    import phone_tools
    import screen_tools
    if _state["running"]:
        return f"กำลังอ่านรายชื่ออยู่แล้ว รอสักครู่{_p()}"
    if not config.MOCK_PHONE and not screen_tools.adb_serial() and not config.ANDROID_APP:
        return screen_tools.NOT_CONNECTED
    _state["running"] = True
    report, total = [], 0
    try:
        for key, pkg in (apps or _installed()):
            got = []
            try:
                res = phone_tools.open_app({"app": key, "page": "chat"}, ctx)
                if str(res).startswith("ERROR"):
                    report.append(f"{key}: เปิดไม่ได้")
                    continue
                time.sleep(1.5)
                for i in range(pages):
                    root = screen_tools._dump()
                    w, _h = screen_tools._screen_size(root)
                    items = screen_tools._elements(root)
                    if phone_tools._fg() not in ("", pkg):     # หลุดออกจากแอป (เด้งไปที่อื่น) → หยุด
                        break
                    new = [n for n in names_on_screen(items, w) if n not in got]
                    got += new
                    if i and not new:
                        break                                    # เลื่อนแล้วไม่มีชื่อใหม่ = สุดรายการ
                    screen_tools.swipe({"direction": "up"}, ctx)
                    time.sleep(0.8)
            except Exception as e:  # noqa: BLE001
                report.append(f"{key}: อ่านไม่ได้ ({str(e)[:60]})")
                continue
            for n in got:
                contacts.learn(n, pkg, "scan")
            total += len(got)
            report.append(f"{contacts.APP_LABEL.get(key, key)} {len(got)} คน")
        contacts.flush()
        try:
            phone_tools._sh(["input", "keyevent", "3"])             # กลับหน้าโฮม
        except Exception:  # noqa: BLE001
            pass
    finally:
        _state["running"] = False
    _state["last"] = time.strftime("%Y-%m-%d %H:%M")
    if not report:
        return f"ไม่พบแอปแชทที่รองรับในเครื่อง{_p()}"
    return f"👥 อ่านรายชื่อเสร็จแล้ว จำเพิ่ม {total} รายชื่อ{_p()} — " + " · ".join(report) + \
        " (ดูได้ที่ 🧭 สั่งแบบเลือก → 👥 คนที่จำได้)"


def scan_async(ctx=None, notify=None):
    def go():
        msg = scan(ctx)
        if notify:
            try:
                notify(msg)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=go, daemon=True).start()


def handle_text(text, ctx=None):
    t = " ".join((text or "").split()).strip()
    if _CMD.match(t) and re.search(r"แชท|แอป|ทั้งหมด|ทุก|สแกน|อัป|อัพ", t):
        return scan(ctx)
    return None
