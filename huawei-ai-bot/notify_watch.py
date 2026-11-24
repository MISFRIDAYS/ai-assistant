"""ติดตามการแจ้งเตือนใหม่ (LINE, Messenger, IG, FB, WhatsApp, SMS ...) แล้วรายงานด้วยเสียง + ถามว่าจะตอบกลับไหม

ต้องให้สิทธิ์: ตั้งค่า > การแจ้งเตือน > การเข้าถึงการแจ้งเตือน > Termux:API
"""
import json
import queue
import re
import threading
import time

import config

APP_NAMES = {
    "jp.naver.line.android": "LINE", "com.facebook.orca": "Messenger", "com.facebook.katana": "Facebook",
    "com.instagram.android": "Instagram", "com.whatsapp": "WhatsApp", "org.telegram.messenger": "Telegram",
    "com.google.android.apps.messaging": "SMS", "com.android.mms": "SMS", "com.huawei.message": "SMS",
    "com.android.incallui": "สายเรียกเข้า", "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok",
    "com.shopee.th": "Shopee", "com.lazada.android": "Lazada", "com.google.android.gm": "Gmail",
    "com.discord": "Discord", "com.twitter.android": "X",
}
CHAT_APPS = {"LINE", "Messenger", "Instagram", "WhatsApp", "Telegram", "SMS", "Facebook", "Discord", "X"}
_SKIP_TITLES = re.compile(r"^(\d+ ข้อความใหม่|\d+ new messages?|กำลังดาวน์โหลด|downloading|syncing|กำลังซิงค์)", re.I)

new_items = queue.Queue()
_seen = set()
_started = [False]


def _list():
    import phone_tools
    out = phone_tools.run(["termux-notification-list"], timeout=60)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _key(n):
    return f"{n.get('packageName')}|{n.get('title')}|{n.get('content')}"


def _quiet_now():
    q = config.NOTIFY_QUIET.strip()
    if not q or "-" not in q:
        return False
    import agent
    now = agent.now_local().strftime("%H:%M")
    a, b = [x.strip() for x in q.split("-", 1)]
    return (a <= now < b) if a < b else (now >= a or now < b)


def _wanted(n):
    pkg = n.get("packageName", "")
    if pkg in ("com.termux", "com.termux.api") or not (n.get("title") or n.get("content")):
        return False
    if config.NOTIFY_APPS.strip().lower() == "all":
        return True
    app = APP_NAMES.get(pkg, "")
    wanted = {x.strip().lower() for x in config.NOTIFY_APPS.split(",") if x.strip()}
    return app.lower() in wanted or pkg.lower() in wanted


def watcher():
    """ทำงานเบื้องหลัง: ทุก 6 วินาทีดูการแจ้งเตือน ถ้ามีใหม่ใส่คิวไว้ให้ผู้ช่วยเสียงพูด"""
    first = True
    while True:
        items = _list()
        if items is None:                       # ยังไม่ได้ให้สิทธิ์ / ใช้ไม่ได้
            time.sleep(60)
            continue
        for n in items:
            k = _key(n)
            if k in _seen:
                continue
            _seen.add(k)
            if first or not _wanted(n) or _SKIP_TITLES.match(n.get("title") or ""):
                continue                        # รอบแรก: ของเก่าที่ค้างอยู่ ไม่ต้องอ่าน
            n["app"] = APP_NAMES.get(n.get("packageName"), n.get("packageName", "").split(".")[-1])
            new_items.put(n)
            remember_last(n)
        if len(_seen) > 3000:
            _seen.clear()
            for n in items:
                _seen.add(_key(n))
        first = False
        time.sleep(10)


APP_KEY = {"LINE": "line", "Instagram": "instagram", "Messenger": "messenger", "Facebook": "messenger",
           "WhatsApp": "whatsapp", "Telegram": "telegram"}


def remember_last(n):
    """จำแชทล่าสุดที่ทักเข้ามา → "ตอบกลับว่า ..." จะได้ตอบถูกคน ถูกแอป"""
    key = APP_KEY.get(n.get("app") or APP_NAMES.get(n.get("packageName"), ""))
    title = (n.get("title") or "").strip()
    if not key or not title:
        return
    try:
        import skills
        skills.set_pref("last_notif", {"app": key, "to": title, "t": time.time(), "key": n.get("key") or "",
                                       "content": (n.get("content") or "")[:120]})
    except Exception:  # noqa: BLE001
        pass


def start():
    if config.NOTIFY_ANNOUNCE and not _started[0]:
        _started[0] = True
        threading.Thread(target=watcher, daemon=True).start()


def pending():
    """ดึงแจ้งเตือนใหม่ทั้งหมดที่รออยู่ (รวมจากคนเดียวกันเป็นรายการเดียว)"""
    got = []
    while not new_items.empty():
        got.append(new_items.get_nowait())
    if not got or _quiet_now():
        return []
    merged = {}
    for n in got:
        k = (n["app"], n.get("title"))
        if k in merged:
            merged[k]["content"] = (merged[k].get("content") or "") + " / " + (n.get("content") or "")
        else:
            merged[k] = dict(n)
    return list(merged.values())


def describe(n, max_len=120):
    text = (n.get("content") or "").strip()
    if len(text) > max_len:
        text = text[:max_len] + "..."
    who = (n.get("title") or "").strip()
    if n["app"] in CHAT_APPS:
        return f"มีข้อความ {n['app']} จาก {who} ว่า {text}"
    return f"มีแจ้งเตือนจาก {n['app']}: {who} {text}".strip()


def format_list(raw):
    """จัดรูปแบบผล termux-notification-list ให้อ่านง่าย (ใช้กับ tool list_notifications)"""
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not items:
        return "ไม่มีการแจ้งเตือนค้างอยู่"
    out = []
    for n in items:
        if n.get("packageName") in ("com.termux", "com.termux.api"):
            continue
        app = APP_NAMES.get(n.get("packageName"), n.get("packageName", ""))
        out.append(f"- [{app}] {n.get('title', '')}: {(n.get('content') or '')[:100]}")
    extra = len(out) - 15
    lines = out[:15]
    if extra > 0:
        lines.append(f"(และอีก {extra} รายการ)")
    return "\n".join(lines) or "ไม่มีการแจ้งเตือนค้างอยู่"
