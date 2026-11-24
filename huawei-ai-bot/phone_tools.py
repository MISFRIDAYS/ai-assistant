"""คำสั่งควบคุมมือถือ Huawei ผ่าน Termux:API

แต่ละ tool = (ฟังก์ชัน, คำอธิบายให้ Claude, input_schema, ต้องขออนุญาตก่อนหรือไม่)
ฟังก์ชันรับ (args: dict, ctx) และคืนค่าเป็น str หรือ dict {"text":..., "image_path":...}
"""
import json
import re
import os
import shutil
import subprocess
import time

import config

# ---------------------------------------------------------------- helpers

_MOCK = {
    "termux-battery-status": '{"health":"GOOD","percentage":78,"plugged":"UNPLUGGED","status":"DISCHARGING","temperature":31.2}',
    "termux-location": '{"latitude":13.7563,"longitude":100.5018,"accuracy":20.0,"provider":"network"}',
    "termux-wifi-connectioninfo": '{"ssid":"Home-WiFi","ip":"192.168.1.23","rssi":-55,"link_speed_mbps":433}',
    "termux-sms-list": '[{"number":"+66812345678","received":"2026-10-25 09:12","body":"ทดสอบข้อความ"}]',
    "termux-contact-list": '[{"name":"แม่","number":"0812345678"},{"name":"สมชาย","number":"0898765432"}]',
    "termux-call-log": '[{"name":"แม่","phone_number":"0812345678","type":"INCOMING","date":"2026-10-25 08:00","duration":"120"}]',
    "termux-clipboard-get": "ข้อความในคลิปบอร์ด",
    "termux-volume": '[{"stream":"music","volume":7,"max_volume":15},{"stream":"ring","volume":5,"max_volume":15}]',
    "termux-notification-list": '[{"packageName":"jp.naver.line.android","title":"แม่","content":"กินข้าวยัง"}]',
    "getprop": "HUAWEI",
}


def run(cmd, timeout=30, input_text=None):
    """รันคำสั่งแล้วคืน stdout (หรือข้อความ error ที่อ่านเข้าใจได้)"""
    if config.MOCK_PHONE:
        return _MOCK.get(cmd[0], f"[MOCK] ran: {' '.join(cmd)}")
    if config.ANDROID_APP:                       # แอป APK: แปลงเป็นคำสั่งของแอป (Accessibility/API ระบบ)
        import android_shim
        return android_shim.run(cmd, timeout=timeout, input_text=input_text)
    if shutil.which(cmd[0]) is None and os.path.exists(f"/system/bin/{cmd[0]}"):
        cmd = [f"/system/bin/{cmd[0]}"] + list(cmd[1:])  # คำสั่งระบบ Android เช่น am, cmd, getprop
    if shutil.which(cmd[0]) is None:
        if cmd[0].startswith("termux-"):
            return (f"ERROR: ไม่พบคำสั่ง {cmd[0]} — ติดตั้งด้วย `pkg install termux-api` "
                    "และติดตั้งแอป Termux:API จาก F-Droid ให้ครบ")
        return f"ERROR: ไม่พบคำสั่ง {cmd[0]}"
    is_api = os.path.basename(cmd[0]).startswith("termux-") and cmd[0] not in ("termux-open-url",)
    if is_api:
        timeout = max(timeout, 60)          # ห้ามตัดคำสั่ง Termux:API กลางคัน (จะขึ้น error สีแดง)
    try:
        if is_api:
            import termux_lock
            with termux_lock.termux_api():
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
        else:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
    except subprocess.TimeoutExpired:
        return f"ERROR: คำสั่งใช้เวลานานเกิน {timeout} วินาที"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0 and not out:
        return f"ERROR (code {p.returncode}): {err or 'ไม่มีรายละเอียด'}"
    return out or err or "OK"


def _truncate(s, n=3500):
    return s if len(s) <= n else s[:n] + f"\n...(ตัดเหลือ {n} ตัวอักษร จากทั้งหมด {len(s)})"


# ---------------------------------------------------------------- ข้อมูลเครื่อง

def battery_status(a, ctx):
    return run(["termux-battery-status"])


def device_info(a, ctx):
    props = {
        "brand": "ro.product.brand",
        "model": "ro.product.model",
        "android_version": "ro.build.version.release",
        "emui_or_harmony": "ro.build.version.emui",
        "build": "ro.build.display.id",
    }
    info = {k: run(["getprop", p]) for k, p in props.items()}
    info["storage"] = run(["df", "-h", "/data"]) if not config.MOCK_PHONE else "64G free"
    return json.dumps(info, ensure_ascii=False)


def get_location(a, ctx):
    provider = a.get("provider", "network")
    return run(["termux-location", "-p", provider, "-r", "once"], timeout=60)


def wifi_info(a, ctx):
    return run(["termux-wifi-connectioninfo"])


# ---------------------------------------------------------------- SMS / โทร / รายชื่อ

def list_sms(a, ctx):
    n = str(int(a.get("limit", 10)))
    box = a.get("box", "inbox")
    return _truncate(run(["termux-sms-list", "-l", n, "-t", box]))


def send_sms(a, ctx):
    return run(["termux-sms-send", "-n", a["number"], a["text"]])


def make_call(a, ctx):
    return run(["termux-telephony-call", a["number"]])


def find_contact(a, ctx):
    raw = run(["termux-contact-list"], timeout=60)
    if raw.startswith("ERROR"):
        return raw
    try:
        contacts = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    q = a.get("query", "").lower()
    hits = [c for c in contacts if q in c.get("name", "").lower() or q in c.get("number", "")]
    return json.dumps(hits[:20], ensure_ascii=False) if hits else "ไม่พบรายชื่อที่ตรงกัน"


def call_log(a, ctx):
    return _truncate(run(["termux-call-log", "-l", str(int(a.get("limit", 10)))]))


def list_notifications(a, ctx):
    import notify_watch
    raw = run(["termux-notification-list"], timeout=20)
    if raw.startswith("ERROR") or not raw.strip().startswith("["):
        return (f"{raw[:200]}\nอ่านแจ้งเตือนไม่ได้ — ให้สิทธิ์: ตั้งค่า > การแจ้งเตือน > "
                "การเข้าถึงการแจ้งเตือน > เปิด Termux:API")
    return _truncate(notify_watch.format_list(raw))


# ---------------------------------------------------------------- ฮาร์ดแวร์

def torch(a, ctx):
    return run(["termux-torch", "on" if a.get("on") else "off"])


def get_volume(a, ctx):
    return run(["termux-volume"])


def set_volume(a, ctx):
    return run(["termux-volume", a["stream"], str(int(a["volume"]))])


def volume_step(a, ctx):
    """เพิ่ม/ลดเสียงทีละขั้นด้วยปุ่มเสียง (ใช้ได้แน่นอนผ่าน ADB) / mute = ปิดเสียง"""
    import screen_tools
    d = a.get("direction", "down")
    n = max(1, min(15, int(a.get("steps", 3))))
    if screen_tools.adb_serial():
        if d == "mute":
            res = _sh(["cmd", "media_session", "volume", "--stream", "3", "--set", "0"])
            if not _launch_ok(res):
                _sh(["input", "keyevent"] + ["25"] * 15)
            return "ปิดเสียงแล้ว"
        _sh(["input", "keyevent"] + [("24" if d == "up" else "25")] * n)
        return f"{'เพิ่ม' if d == 'up' else 'ลด'}เสียงแล้ว"
    try:                                               # ไม่มี ADB → Termux:API
        vols = json.loads(run(["termux-volume"]))
        cur = next((x["volume"] for x in vols if x.get("stream") == "music"), 7)
    except (ValueError, TypeError, StopIteration):
        cur = 7
    nv = 0 if d == "mute" else max(0, min(15, cur + (n if d == "up" else -n)))
    run(["termux-volume", "music", str(nv)])
    return f"ตั้งเสียงเป็น {nv}/15 แล้ว"


def set_brightness(a, ctx):
    """ชื่อเดิม (เก็บไว้ให้ใช้ได้) — ส่งต่อไปใช้ระบบความสว่างตัวใหม่ที่ตรวจผลจริง"""
    import system_tools
    return system_tools.brightness({"level": str(a.get("level", ""))}, ctx)


def vibrate(a, ctx):
    return run(["termux-vibrate", "-d", str(int(a.get("ms", 800)))])


def speak(a, ctx):
    """พูดออกลำโพง: ใช้เสียง Google TTS (ไม่ต้องมี TTS ในเครื่อง) ถ้าไม่ได้ค่อยใช้ของเครื่อง"""
    import voice
    try:
        voice.say(a["text"], wait=False)
        return "กำลังพูดออกลำโพงแล้ว"
    except Exception as e:  # noqa: BLE001
        res = run(["termux-tts-speak", a["text"]], timeout=60)
        return f"{res} (gTTS ใช้ไม่ได้: {e})"


def take_photo(a, ctx):
    cam = "1" if a.get("camera") == "front" else "0"
    path = os.path.join(config.DATA_DIR, f"photo_{int(time.time())}.jpg")
    res = run(["termux-camera-photo", "-c", cam, path], timeout=40)
    if config.MOCK_PHONE:
        return {"text": "[MOCK] ถ่ายรูปแล้ว", "image_path": None}
    if not os.path.exists(path):
        return f"ERROR: ถ่ายรูปไม่สำเร็จ {res}"
    return {"text": "ถ่ายรูปแล้ว และส่งให้ผู้ใช้ทาง Telegram แล้ว", "image_path": path}


def show_notification(a, ctx):
    return run(["termux-notification", "-t", a.get("title", config.BOT_NAME), "-c", a["content"]])


# ---------------------------------------------------------------- คลิปบอร์ด / แอป / ปลุก

def get_clipboard(a, ctx):
    return run(["termux-clipboard-get"])


def set_clipboard(a, ctx):
    return run(["termux-clipboard-set"], input_text=a["text"])


_LAUNCH_FAIL = ("error", "unable to resolve", "does not exist", "exception", "no activities found",
                "not found", "permission denial", "aborted", "ยังไม่ได้เชื่อม adb")


def _launch_ok(out):
    low = (out or "").lower()
    return not any(k in low for k in _LAUNCH_FAIL)


def _log(*a):
    print("[open]", *a, flush=True)


def still_home(wait=0.0):
    """จอยังเป็นหน้าโฮม/หน้าแอปล่าสุด (เปิดแอปไม่ขึ้น) — รอได้ถึง wait วิ / อ่านไม่ได้ = ถือว่าไม่ใช่"""
    end = time.time() + wait
    while True:
        fg = (_fg() or "").lower()
        if "launcher" not in fg:
            return False
        if time.time() >= end:
            return True
        time.sleep(0.4)


def _fg():
    """แอปที่อยู่หน้าจอตอนนี้ (package) หรือ None"""
    if config.MOCK_PHONE:
        return "mock.foreground"
    import screen_tools
    if not screen_tools.adb_serial():
        return None
    # กรองบนเครื่องเลย (dumpsys window ทั้งก้อนใหญ่มาก ส่งผ่าน ADB ช้า)
    out = screen_tools.adb_shell(["sh", "-c", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"],
                                 timeout=10, quote=True)
    m = re.search(r"mCurrentFocus=.*?\s([\w.]+)/", out) or re.search(r"mFocusedApp=.*?\s([\w.]+)/", out)
    return m.group(1) if m else None


def _moved(before, wait=3.0):
    """รอจนหน้าจอเปลี่ยนไปเป็นแอปอื่น (ไม่ใช่ Termux) → คืน package ใหม่ หรือ None ถ้าไม่เปลี่ยน"""
    if config.MOCK_PHONE:
        return "mock.foreground"
    t0 = time.time()
    seen = bool(before)
    while time.time() - t0 < wait:
        time.sleep(0.7)
        now = _fg()
        seen = seen or bool(now)
        if now and now != before and not now.startswith("com.termux"):
            return now
    return None if seen else "unknown"          # อ่านแอปหน้าจอไม่ได้เลย → ไม่ตัดสินว่าล้มเหลว


def _gboxish(pkg):
    return bool(pkg) and ("gbox" in pkg.lower())


def _open_link(url, verify=False):
    """เปิดลิงก์ → GBox/แอปที่รับลิงก์จะเปิดให้
    ลำดับ: termux-open-url (วิธีเดิมที่เปิด Instagram ใน GBox ได้) → ถ้าจอไม่เปลี่ยน ลองส่งผ่าน ADB"""
    import screen_tools
    adb = bool(screen_tools.adb_serial())
    before = _fg() if (verify and adb) else None
    if _gboxish(before):
        verify = False                  # อยู่ใน GBox อยู่แล้ว ลิงก์จะเปิดในหน้าต่างเดิม ตรวจจากชื่อแอปไม่ได้
    out = run(["termux-open-url", url])
    if _launch_ok(out) and (not verify or not adb or _moved(before)):
        return True, out
    if adb:
        out2 = screen_tools.adb_shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", url], quote=True)
        if _launch_ok(out2) and (not verify or _moved(before)):
            return True, out2
        return False, f"termux-open-url: {out[:60]} | adb: {out2[:80]}"
    return _launch_ok(out), out + " (ไม่ได้เชื่อม ADB)"


def open_url(a, ctx):
    ok, out = _open_link(a["url"])
    return f"เปิดลิงก์ {a['url']} แล้ว" if ok else f"ERROR: เปิดลิงก์ไม่ได้ ({out[:120]})"


COMMON_APPS = {
    "line": "jp.naver.line.android",
    "youtube": "com.google.android.youtube",
    "facebook": "com.facebook.katana",
    "messenger": "com.facebook.orca",
    "tiktok": "com.ss.android.ugc.trill",
    "shopee": "com.shopee.th",
    "lazada": "com.lazada.android",
    "grab": "com.grabtaxi.passenger",
    "chrome": "com.android.chrome",
    "camera": "com.huawei.camera",
    "gallery": "com.huawei.photos",
    "settings": "com.android.settings",
    "appgallery": "com.huawei.appmarket",
    "petal maps": "com.huawei.maps.app",
    "huawei music": "com.huawei.music",
    "calendar": "com.google.android.calendar",
    "google calendar": "com.google.android.calendar",
    "huawei calendar": "com.huawei.calendar",
    "clock": "com.android.deskclock",
    "calculator": "com.android.calculator2",
    "notes": "com.huawei.notepad",
    "files": "com.huawei.hidisk",
    "phone manager": "com.huawei.systemmanager",
    "rov": "com.garena.game.kgth",
    "free fire": "com.dts.freefireth",
    "pubg": "com.vng.pubgmobile",
    "claude": "com.anthropic.claude",
    "chatgpt": "com.openai.chatgpt",
    "gemini": "com.google.android.apps.bard",
}


def _sh(args, timeout=30, quote=False):
    """รันคำสั่งระบบ ถ้าเชื่อม ADB ไว้จะรันผ่าน ADB (สิทธิ์มากกว่า เปิดแอปจากเบื้องหลังได้)"""
    import screen_tools
    if screen_tools.adb_serial():
        if quote:
            return screen_tools.adb_shell(args, timeout=timeout, quote=True)
        return screen_tools.adb_shell(args, timeout=timeout)
    return run(args, timeout=timeout)


_app_cache = {"t": 0, "list": []}


def _launcher_components():
    """รายชื่อแอปทั้งหมดที่มีไอคอนบนหน้าจอหลัก ในรูป package/activity"""
    if time.time() - _app_cache["t"] < 300 and _app_cache["list"]:
        return _app_cache["list"]
    out = _sh(["cmd", "package", "query-activities", "--brief",
               "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"])
    comps = sorted({l.strip() for l in out.splitlines() if "/" in l and " " not in l.strip()})
    if not comps:  # เครื่องเก่า: ใช้รายชื่อ package แทน
        out = _sh(["pm", "list", "packages"])
        comps = sorted(l.replace("package:", "").strip() for l in out.splitlines() if l.startswith("package:"))
    if comps:
        _app_cache.update(t=time.time(), list=comps)
    return comps


def list_apps(a, ctx):
    comps = _launcher_components()
    if not comps:
        return f"อ่านรายชื่อแอปไม่ได้ แอปที่รู้จัก: {json.dumps(COMMON_APPS, ensure_ascii=False)}"
    pkgs = sorted({c.split("/")[0] for c in comps})
    q = a.get("query", "").lower().strip()
    if q:
        pkgs = [p for p in pkgs if q in p.lower()] or [f"ไม่พบ '{q}' — รายชื่อทั้งหมด:"] + pkgs
    return _truncate(f"แอปที่เปิดได้ ({len(pkgs)}):\n" + "\n".join(pkgs), 6000)


# แอปที่มักติดตั้งใน GBox (ระบบมองไม่เห็น) → เปิดผ่านลิงก์ แล้ว GBox/แอปที่รับลิงก์จะเปิดให้
APP_LINKS = {
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "youtube": "https://www.youtube.com", "tiktok": "https://www.tiktok.com",
    "messenger": "https://www.messenger.com", "x": "https://x.com", "twitter": "https://x.com",
    "threads": "https://www.threads.net", "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
    "whatsapp": "https://wa.me", "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com",
    "google": "https://www.google.com", "youtube music": "https://music.youtube.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com",
    "google translate": "https://translate.google.com", "translate": "https://translate.google.com",
    "chrome": "https://www.google.com", "play store": "https://play.google.com/store",
    "claude": "https://claude.ai/new", "chatgpt": "https://chatgpt.com", "gemini": "https://gemini.google.com",
}
# ชื่อที่แสดงใต้ไอคอน (ใช้แตะไอคอนใน GBox / หน้าโฮม เมื่อเปิดผ่าน package ไม่ได้)
APP_LABELS = {
    "youtube": ["YouTube"], "google": ["Google"], "chrome": ["Chrome", "Google Chrome"], "gmail": ["Gmail"],
    "google maps": ["Maps", "Google Maps", "แผนที่"], "maps": ["Maps", "Google Maps", "แผนที่"],
    "play store": ["Play Store", "Google Play Store", "Play สโตร์", "Google Play"],
    "youtube music": ["YT Music", "YouTube Music"], "google drive": ["Drive", "Google Drive", "ไดรฟ์"],
    "drive": ["Drive", "Google Drive", "ไดรฟ์"], "google translate": ["Translate", "แปลภาษา", "Google แปลภาษา"],
    "translate": ["Translate", "แปลภาษา", "Google แปลภาษา"], "facebook": ["Facebook"], "instagram": ["Instagram"],
    "tiktok": ["TikTok"], "messenger": ["Messenger"], "x": ["X"], "twitter": ["X", "Twitter"],
    "threads": ["Threads"], "whatsapp": ["WhatsApp"], "netflix": ["Netflix"], "spotify": ["Spotify"],
    "claude": ["Claude"], "chatgpt": ["ChatGPT"], "gemini": ["Gemini"], "line": ["LINE"],
}
# แอปพื้นฐานที่แต่ละยี่ห้อใช้ package ต่างกัน (เรียงตามที่อยากใช้ก่อน)
ALT_PKGS = {   # Google/AOSP · Huawei · Samsung · Xiaomi/Redmi (MIUI/HyperOS) · Vivo · Oppo/realme (ColorOS)
    "calendar": ("com.google.android.calendar", "com.huawei.calendar", "com.android.calendar",
                 "com.samsung.android.calendar", "com.xiaomi.calendar", "com.bbk.calendar", "com.coloros.calendar"),
    "clock": ("com.android.deskclock", "com.huawei.deskclock", "com.google.android.deskclock",
              "com.sec.android.app.clockpackage", "com.android.BBKClock", "com.coloros.alarmclock", "com.oplus.alarmclock"),
    "calculator": ("com.android.calculator2", "com.huawei.calculator", "com.google.android.calculator",
                   "com.sec.android.app.popupcalculator", "com.miui.calculator", "com.android.bbkcalculator",
                   "com.coloros.calculator", "com.oplus.calculator"),
    "notes": ("com.huawei.notepad", "com.example.android.notepad", "com.google.android.keep",
              "com.samsung.android.app.notes", "com.miui.notes", "com.android.notes", "com.coloros.note", "com.oplus.note"),
    "gallery": ("com.huawei.photos", "com.android.gallery3d", "com.google.android.apps.photos",
                "com.sec.android.gallery3d", "com.miui.gallery", "com.vivo.gallery", "com.coloros.gallery3d",
                "com.oplus.gallery"),
    "camera": ("com.huawei.camera", "com.android.camera", "com.google.android.GoogleCamera",
               "com.sec.android.app.camera", "com.oplus.camera", "com.oppo.camera"),
    "files": ("com.huawei.hidisk", "com.google.android.apps.nbu.files", "com.sec.android.app.myfiles",
              "com.mi.android.globalFileexplorer", "com.android.fileexplorer", "com.android.filemanager",
              "com.coloros.filemanager", "com.oplus.filemanager"),
}

class _Aliases(dict):
    """ชื่อเรียกแอป → ชื่อมาตรฐาน · ไม่มีในตาราง → ลองตารางแอปแชทกลาง (รู้จักสะกดเพี้ยน เช่น 'instragram')"""

    def get(self, k, default=None):
        if k in self:
            return self[k]
        if isinstance(k, str):
            import chat_apps
            c = chat_apps.key(k)
            if c:
                return c
        return default


ALIASES = _Aliases({
    "fb": "facebook", "เฟส": "facebook", "เฟสบุ๊ค": "facebook", "เฟซบุ๊ก": "facebook",
    "ig": "instagram", "ไอจี": "instagram", "อินสตาแกรม": "instagram",
    "ยูทูป": "youtube", "ยูทูบ": "youtube", "yt": "youtube", "ติ๊กต็อก": "tiktok", "ติ๊กตอก": "tiktok",
    "ไลน์": "line", "กล้อง": "camera", "ตั้งค่า": "settings", "แกลเลอรี่": "gallery", "เครื่องคิดเลข": "calculator",
    "อาร์โอวี": "rov", "ร็อฟ": "rov", "รอฟ": "rov", "ร๊อฟ": "rov", "โรฟ": "rov", "r.o.v": "rov",
    "realm of valor": "rov", "arena of valor": "rov", "ฟีฟาย": "free fire", "จีบ็อกซ์": "gbox", "จีบอกซ์": "gbox",
    "นาฬิกา": "clock", "ปฏิทิน": "calendar", "กูเกิลคาเลนเดอร์": "google calendar", "กูเกิ้ลคาเลนเดอร์": "google calendar",
    "กูเกิลปฏิทิน": "google calendar", "ปฏิทินกูเกิล": "google calendar", "คาเลนเดอร์": "calendar",
    "ปฏิทินหัวเว่ย": "huawei calendar", "แผนที่": "maps", "จีเมล": "gmail",
    "กูเกิล": "google", "กูเกิ้ล": "google", "กุเกิล": "google", "กุเกิ้ล": "google", "google search": "google",
    "ยูทู้ป": "youtube", "ยูทิวบ์": "youtube", "you tube": "youtube", "ยูทูปมิวสิค": "youtube music",
    "กูเกิลไดรฟ์": "google drive", "ไดรฟ์": "drive", "กูเกิลแปล": "google translate", "แปลภาษา": "translate",
    "โครม": "chrome", "เพลย์สโตร์": "play store", "ไอจี้": "instagram", "อินสตา": "instagram",
    "กูเกิลแมพ": "google maps", "กูเกิ้ลแมพ": "google maps", "แมพ": "maps",
    "อินสตาร์แกรม": "instagram", "อินสตราแกรม": "instagram", "อินสต้าแกรม": "instagram", "อินสต้า": "instagram",
    "อินสตาร์": "instagram", "อินสตาแกม": "instagram",
    "คลอด": "claude", "คล็อด": "claude", "เคลาด์": "claude", "เคลด": "claude", "คลอดด์": "claude", "claude ai": "claude",
    "แชทจีพีที": "chatgpt", "chat gpt": "chatgpt", "แชตจีพีที": "chatgpt", "gpt": "chatgpt",
    "เจมิไน": "gemini", "เจมินาย": "gemini", "google gemini": "gemini",
})


# หน้าภายในแอป (เปิดแอปแล้วแตะไปหน้านี้ให้เลย)
PAGE_LABELS = {
    "chat": ["Direct", "Messenger", "ข้อความ", "Messages", "Message", "แชท", "Chats", "Chat", "Inbox",
             "กล่องข้อความ", "DM", "การสนทนา"],
    "search": ["ค้นหา", "Search", "Search and explore", "สำรวจ", "Explore"],
    "profile": ["โปรไฟล์", "Profile", "บัญชี", "Account", "You", "ฉัน"],
    "notifications": ["การแจ้งเตือน", "Notifications", "Activity", "กิจกรรม", "แจ้งเตือน"],
    "home": ["หน้าหลัก", "Home", "หน้าแรก"],
}
# เข้าหน้าในแอปด้วยลิงก์ตรง (ไม่ต้องอ่าน/แตะหน้าจอ → เร็วและไม่พังตอนมีวิดีโอเล่น)
PAGE_LINKS = {
    ("instagram", "search"): "https://www.instagram.com/explore/",
    ("instagram", "notifications"): "https://www.instagram.com/accounts/activity/",
    ("facebook", "chat"): "https://www.facebook.com/messages/",
    ("facebook", "notifications"): "https://www.facebook.com/notifications/",
    ("messenger", "chat"): "https://www.messenger.com/",
    ("x", "chat"): "https://x.com/messages", ("twitter", "chat"): "https://x.com/messages",
    ("youtube", "search"): "https://www.youtube.com/results",
    ("tiktok", "chat"): "https://www.tiktok.com/messages",
}
PAGE_ALIASES = {"กล่องข้อความ": "chat", "ไดเร็กต์": "chat", "ไดเร็ก": "chat", "แชท": "chat", "แชต": "chat", "ข้อความ": "chat", "dm": "chat", "inbox": "chat", "ไดเร็ค": "chat",
                "direct": "chat", "messages": "chat", "ค้นหา": "search", "search": "search", "โปรไฟล์": "profile",
                "profile": "profile", "แจ้งเตือน": "notifications", "หน้าหลัก": "home", "หน้าแรก": "home"}


def _norm(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _tap_label(labels):
    """หาไอคอน/ข้อความที่ชื่อตรงกับ labels บนจอแล้วแตะ — คืนชื่อที่แตะ / None = ไม่เจอ / False = อ่านจอไม่ได้"""
    import screen_tools
    try:
        items = screen_tools._elements(screen_tools._dump())
    except Exception as e:  # noqa: BLE001
        _log("dump fail", e)
        return False
    want = [_norm(x) for x in labels]
    for strict in (True, False):
        for e in items:
            for v in (_norm(e["text"]), _norm(e["desc"])):
                if not v:
                    continue
                if (v in want) if strict else any(
                        v.startswith(w) and not v[len(w):len(w) + 1].isalnum() for w in want if len(w) > 2):
                    screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
                    return e["text"] or e["desc"]
    return None


def _via_home(labels, trace, pages=3):
    """แตะไอคอน (หรือทางลัดของ GBox) บนหน้าโฮม ไล่ดูทีละหน้า"""
    import screen_tools
    screen_tools.adb_shell(["input", "keyevent", "3"])
    time.sleep(0.6)
    screen_tools.adb_shell(["input", "keyevent", "3"])        # กดซ้ำ = กลับหน้าแรก
    time.sleep(1.2)
    for i in range(pages):
        hit = _tap_label(labels)
        if hit:
            time.sleep(1.5)
            return f"หน้าโฮม หน้า {i + 1} → แตะ {hit}"
        if hit is False:
            trace.append("อ่านหน้าโฮมไม่ได้ (จอล็อก/ปิดอยู่?)")
            return None
        try:
            screen_tools.swipe({"direction": "left"}, None)
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.8)
    screen_tools.adb_shell(["input", "keyevent", "3"])
    trace.append(f"ไม่เจอไอคอน {labels[0]} บนหน้าโฮม {pages} หน้า")
    return None


def open_app(a, ctx):
    page = (a.get("page") or "").strip().lower()
    page = PAGE_ALIASES.get(page, page)
    key = ALIASES.get(a["app"].strip().lower(), a["app"].strip()).lower()
    if page and (key, page) in PAGE_LINKS:
        ok, out = _open_link(PAGE_LINKS[(key, page)])
        if ok and config.ANDROID_APP:                 # ลิงก์ไปเปิดในเบราว์เซอร์ (ไม่มีแอปนี้) → ไม่นับว่าสำเร็จ
            time.sleep(1.2)
            if re.search(r"chrome|browser|webview|firefox|opera|edge", _fg() or "", re.I):
                _sh(["input", "keyevent", "4"])
                ok, out = False, "เปิดในเบราว์เซอร์แทน (ไม่มีแอปนี้ในเครื่อง)"
        _log(key, page, "page link", ok, out[:80])
        if ok:
            return f"เปิด {a['app']} เข้าหน้า {page} แล้ว (ลิงก์ตรง)"
    res = _open_app(a, ctx)
    if config.AUTO_ALLOW_PERMS and config.ANDROID_APP and not res.startswith("ERROR"):
        try:
            import screen_tools
            time.sleep(0.8)
            if screen_tools.allow_permission_popup():     # แอปเพิ่งเปิดแล้วขอสิทธิ์ → อนุญาตให้เลย
                screen_tools.allow_permission_popup()     # บางแอปขอต่อกันหลายสิทธิ์
        except Exception:  # noqa: BLE001
            pass
    if not page or res.startswith("ERROR") or res.startswith("เจอหลายแอป"):
        return res
    labels = PAGE_LABELS.get(page, [a["page"]])
    hit = None
    for _ in range(3):                          # แอปเพิ่งเปิด อาจยังโหลดไม่เสร็จ (ลองถี่ขึ้น)
        time.sleep(1.2)
        if page == "chat":                      # ปุ่มกล่องข้อความในแถบเมนู (ไม่แตะปุ่ม 'ข้อความ' กลางฟีด)
            import share_tools
            import screen_tools
            try:
                icon = share_tools._dm_icon(share_tools._items())
            except RuntimeError:
                hit = False
                break
            if icon:
                screen_tools.adb_shell(["input", "tap", str(icon["x"]), str(icon["y"])])
                hit = icon["text"] or icon["desc"]
                break
            continue
        hit = _tap_label(labels)
        if hit or hit is False:
            break
    if hit:
        time.sleep(1.0)
        return f"{res} → เข้าหน้า {a['page']} แล้ว (แตะ {hit})"
    why = "อ่านหน้าจอไม่ได้" if hit is False else "หาปุ่มไม่เจอ"
    return f"{res} แต่เข้าหน้า {a['page']} ไม่ได้ ({why}) — ใช้ read_screen ดูปุ่มแล้ว tap ต่อ"


def _open_app(a, ctx):
    import screen_tools
    name = ALIASES.get(a["app"].strip().lower(), a["app"].strip())
    key = name.lower()
    installed = {c.split("/")[0] for c in _launcher_components()}
    known_pkg = COMMON_APPS.get(key)
    has_adb = bool(screen_tools.adb_serial())
    labels = APP_LABELS.get(key) or [name]
    trace = []

    def fallback(why):
        """เปิดแอปตรงๆ ไม่ได้ → GBox → ไอคอนบนหน้าโฮม → ลิงก์"""
        trace.append(why)
        if key in APP_LINKS:
            ok, out = _open_link(APP_LINKS[key], verify=True)
            if ok:
                _log(name, trace, "link ok", _fg())
                return f"เปิด {name} แล้ว (ผ่านลิงก์ {APP_LINKS[key]} → GBox)"
            trace.append(f"ลิงก์: {out[:100]}")
        if has_adb:
            done = _via_home(labels, trace)       # แตะไอคอน/ทางลัดบนหน้าโฮม
            if done:
                _log(name, trace, done)
                return f"เปิด {name} แล้ว ({done})"
        _log(name, "FAIL", trace)
        hint = "" if has_adb else " — ADB หลุดอยู่ ลองสั่ง /syscheck หรือเชื่อม ADB ใหม่"
        return f"ERROR: เปิด {name} ไม่สำเร็จ (ลองแล้ว: {' | '.join(trace)[:300]}){hint}"

    native = known_pkg in installed or (not known_pkg and any(key in p.lower() for p in installed))
    if key in APP_LINKS and not native:
        return fallback("ไม่พบแอปนี้ในระบบ (น่าจะอยู่ใน GBox)")
    pkg = COMMON_APPS.get(key, name)
    if installed and pkg not in installed:          # แอปพื้นฐานมีหลายยี่ห้อ → ใช้ตัวที่มีในเครื่อง
        pkg = next((p for p in ALT_PKGS.get(key, ()) if p in installed), pkg)
    if installed and "." in pkg and pkg not in installed:
        similar = sorted(p for p in installed if any(k in p.lower() for k in key.split()))
        if similar:
            pkg = similar[0] if len(similar) == 1 else pkg
        if pkg not in installed:
            return (f"ERROR: ไม่พบ package {pkg} ในเครื่อง — ใช้ list_apps ดูรายชื่อแล้วเลือก package "
                    f"ที่ใกล้เคียง {similar[:10] if similar else ''}")
    if "." not in pkg:  # ชื่อทั่วไป → ให้คะแนนทุกแอป (ชื่อแสดง/ชื่อเรียกที่เรียนรู้/package) กำกวมก็ถาม
        import app_index
        found, why = app_index.resolve(name, ctx)
        if not found:
            return why or f"ERROR: ไม่พบแอป '{name}' ให้ใช้ list_apps ค้นหา package ก่อน"
        pkg = found
    fresh = a.get("fresh", True) if a.get("page") or a.get("task") else a.get("fresh", False)
    if fresh and config.ANDROID_APP and "." in pkg:      # งานในแอป: เริ่มที่หน้าแรกเสมอ (ไม่ค้างหน้าเดิมที่เปิดไว้)
        import android_shim
        if android_shim.bridge().launchFresh(pkg):
            time.sleep(1.2)
            if not still_home(wait=1.3):
                return f"เปิด {name} ({pkg}) ที่หน้าแรกแล้ว"
            trace.append("launchFresh แล้วจอยังเป็นหน้าโฮม")      # Android บล็อกการเปิดจากเบื้องหลัง → ลองผ่าน ADB
            _log(name, "launchFresh ไม่ขึ้น", _fg())
    comp = next((c for c in _launcher_components() if c.startswith(pkg + "/")), None)
    if comp:
        res = _sh(["am", "start", "--user", "0", "-n", comp])
    else:
        res = _sh(["am", "start", "--user", "0", "-a", "android.intent.action.MAIN",
                   "-c", "android.intent.category.LAUNCHER", "-p", pkg])
    if not _launch_ok(res) and not comp:
        res = _sh(["monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
    if not _launch_ok(res):
        if key in APP_LINKS:
            return fallback(f"am start: {res[:80]}")
        return f"ERROR: เปิด {name} ({pkg}) ไม่สำเร็จ: {res[:150]}"
    if trace and still_home(wait=1.5):                  # เปิดซ้ำแล้วจอยังเป็นหน้าโฮม → ไม่บอกว่าเปิดแล้ว
        if key in APP_LINKS:
            return fallback("am start แล้วจอยังเป็นหน้าโฮม")
        return f"ERROR: เปิด {name} ไม่ขึ้น (จอยังเป็นหน้าโฮม) — ลองแตะไอคอน {name} เองครั้งหนึ่งแล้วสั่งใหม่"
    return f"เปิด {name} ({comp or pkg}) แล้ว"


# ---------------------------------------------------------------- ดูแลเครื่อง

KEEP_ALIVE = ("com.termux", "com.termux.api", "com.termux.boot", "com.termux.widget", "launcher",
              "inputmethod", "systemui", "com.android.phone", "org.telegram", "jp.naver.line",
              "com.facebook.orca", "com.whatsapp", "com.huawei.android.launcher", "com.google.android.gms",
              "com.huawei.hwid", "com.huawei.systemmanager", "android")


def _meminfo():
    vals = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                vals[k] = int(v.split()[0]) // 1024     # MB
    except Exception:  # noqa: BLE001
        out = _sh(["cat", "/proc/meminfo"])
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                try:
                    vals[k] = int(v.split()[0]) // 1024
                except (ValueError, IndexError):
                    pass
    return vals


def _resolve_pkg(name):
    name = ALIASES.get(name.strip().lower(), name.strip())
    pkg = COMMON_APPS.get(name.lower(), name)
    if "." in pkg:
        return pkg
    hits = sorted({c.split("/")[0] for c in _launcher_components() if name.lower() in c.lower()})
    return hits[0] if hits else None


_CURRENT = ("current", "แอปนี้", "แอปที่เปิดอยู่", "หน้านี้", "อันนี้", "this", "แอพนี้", "ตัวนี้")


KNOWN_PKGS = {"instagram": "com.instagram.android", "facebook": "com.facebook.katana", "messenger": "com.facebook.orca",
              "youtube": "com.google.android.youtube", "tiktok": "com.ss.android.ugc.trill", "line": "jp.naver.line.android",
              "whatsapp": "com.whatsapp", "telegram": "org.telegram.messenger", "chrome": "com.android.chrome",
              "google": "com.google.android.googlequicksearchbox", "gmail": "com.google.android.gm",
              "google maps": "com.google.android.apps.maps", "maps": "com.google.android.apps.maps"}


def close_app(a, ctx):
    """ปิดแอป (force stop) — ใส่ชื่อแอปที่เห็นบนจอ, package, หลายแอปคั่นด้วย , หรือ 'แอปนี้' / 'ทั้งหมด'"""
    import app_index
    import screen_tools
    if not screen_tools.adb_serial():
        return "ERROR: ปิดแอปต้องเชื่อม ADB ก่อน (ใช้ไฟล์ เปิดADBให้แท็บเล็ต.bat)"
    names = [x.strip() for x in re.split(r"\s*(?:,|、|\sกับ\s|\sและ\s)\s*", a["app"]) if x.strip()] or [a["app"]]
    done, missing = [], []
    for name in names:
        low = name.lower()
        if low in ("all", "ทั้งหมด", "ทุกแอป", "ทุกแอพ"):
            return clean_ram({"aggressive": True}, ctx)
        if low in _CURRENT:
            pkg = app_index.foreground_pkg()
            if not pkg or pkg.startswith("com.termux") or "launcher" in pkg:
                missing.append(f"{name} (ตอนนี้อยู่หน้าโฮม/ไม่มีแอปเปิดอยู่)")
                continue
        else:
            key = ALIASES.get(low, low)
            pkg, _ = app_index.find(name)
            known = KNOWN_PKGS.get(key)
            if known and (not pkg or "gbox" in pkg):
                pkg = known                           # แอปที่รู้ package แน่นอน (เช่น Instagram) → ปิดตรงตัว
            if not pkg and low in APP_LINKS:        # แอปที่อยู่ใน GBox → ปิด GBox
                pkg, _ = app_index.find("gbox")
        if not pkg:
            missing.append(name)
            continue
        if pkg.startswith("com.termux"):
            missing.append(f"{name} (ปิดตัวผู้ช่วยเองไม่ได้)")
            continue
        _sh(["am", "force-stop", pkg])
        done.append(app_index.label_of(pkg))
    if name and low in _CURRENT and done:
        _sh(["input", "keyevent", "3"])                 # ปิดแอปปัจจุบันแล้วกลับหน้าโฮม
    msg = f"ปิดแล้ว: {', '.join(done)}" if done else ""
    if missing:
        msg += (" | " if msg else "") + f"ไม่พบ: {', '.join(missing)} (ลอง list_apps)"
    return msg or "ไม่มีแอปให้ปิด"


def clean_ram(a, ctx):
    """ล้างแรม: ปิดโปรเซสเบื้องหลัง (ปลอดภัย) / aggressive=ปิดแอปที่เปิดค้างไว้ด้วย (ยกเว้นแอปแชท)"""
    import screen_tools
    before = _meminfo().get("MemAvailable", 0)
    has_adb = bool(screen_tools.adb_serial())
    _sh(["am", "kill-all"])
    closed = []
    if a.get("aggressive") and has_adb:
        recents = _sh(["dumpsys", "activity", "recents"], timeout=20)
        pkgs = []
        for m in re.finditer(r"(?:realActivity|cmp)=\{?([\w.]+)/", recents):
            p = m.group(1)
            if p not in pkgs and not any(k in p for k in KEEP_ALIVE):
                pkgs.append(p)
        for p in pkgs[:25]:
            _sh(["am", "force-stop", p])
            closed.append(p)
    time.sleep(1.5)
    after = _meminfo().get("MemAvailable", 0)
    total = _meminfo().get("MemTotal", 0)
    note = "" if has_adb else " (ยังไม่ได้เชื่อม ADB จึงล้างได้แค่บางส่วน)"
    return (f"ล้างแรมแล้ว: ว่าง {before} → {after} MB (เพิ่ม {max(0, after - before)} MB จากทั้งหมด {total} MB)"
            + (f" ปิดแอป {len(closed)} ตัว: {', '.join(closed[:10])}" if closed else "") + note)


def device_health(a, ctx):
    """ตรวจสภาพเครื่อง: แบต อุณหภูมิ แรม พื้นที่ เวลาเปิดเครื่อง แอปที่กินแรม"""
    import screen_tools
    info = {}
    try:
        b = json.loads(run(["termux-battery-status"]))
        info["แบต"] = (f"{b.get('percentage')}% สุขภาพ {b.get('health')} อุณหภูมิ {b.get('temperature')}°C "
                      f"{'(กำลังชาร์จ)' if b.get('plugged') not in (None, 'UNPLUGGED') else ''}").strip()
    except Exception:  # noqa: BLE001
        pass
    m = _meminfo()
    if m.get("MemTotal"):
        used = m["MemTotal"] - m.get("MemAvailable", 0)
        info["แรม"] = f"ใช้ {used} / {m['MemTotal']} MB ({used * 100 // m['MemTotal']}%) ว่าง {m.get('MemAvailable')} MB"
    df = run(["df", "-h", "/data"]) if not config.MOCK_PHONE else "Filesystem Size Used Avail Use%\n/data 110G 60G 50G 55%"
    lines = [l for l in df.splitlines() if l.strip()]
    if len(lines) >= 2:
        parts = lines[-1].split()
        if len(parts) >= 5:
            info["พื้นที่"] = f"ใช้ {parts[2]} จาก {parts[1]} (ว่าง {parts[3]}, {parts[4]})"
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        info["เปิดเครื่องมาแล้ว"] = f"{int(up // 86400)} วัน {int(up % 86400 // 3600)} ชม."
    except Exception:  # noqa: BLE001
        pass
    if screen_tools.adb_serial() and not config.MOCK_PHONE and not a.get("quick"):
        temps = _sh(["sh", "-c", "for z in /sys/class/thermal/thermal_zone*; do "
                     "echo $(cat $z/type 2>/dev/null):$(cat $z/temp 2>/dev/null); done"], timeout=15)
        vals = []
        for line in temps.splitlines():
            if ":" in line:
                t, v = line.rsplit(":", 1)
                try:
                    c = int(v) / (1000 if int(v) > 1000 else 1)
                    if 15 < c < 120 and ("cpu" in t.lower() or "soc" in t.lower() or "tsens" in t.lower()):
                        vals.append(c)
                except ValueError:
                    pass
        if vals:
            info["อุณหภูมิ CPU"] = f"สูงสุด {max(vals):.0f}°C"
        mem = _sh(["dumpsys", "meminfo", "-s"], timeout=25)
        top = []
        grab = False
        for line in mem.splitlines():
            if "by process" in line:
                grab = True
                continue
            if grab:
                if not line.strip():
                    break
                mm = re.match(r"\s*([\d,]+)K: ([\w.:]+)", line)
                if mm:
                    top.append(f"{mm.group(2)} {int(mm.group(1).replace(',', '')) // 1024}MB")
            if len(top) >= 6:
                break
        if top:
            info["แอปที่ใช้แรมมากสุด"] = ", ".join(top)
    return json.dumps(info, ensure_ascii=False)


SHARE_LINKS = {
    "whatsapp": lambda t, to: f"https://wa.me/{to}?text={t}" if to else f"https://wa.me/?text={t}",
    "telegram": lambda t, to: f"https://t.me/share/url?url=%20&text={t}",
    "sms": lambda t, to: f"sms:{to or ''}?body={t}",
}


def share_text(a, ctx):
    """ส่งข้อความไปที่แอปแชท (เปิดแอปพร้อมข้อความที่พิมพ์ไว้ให้แล้ว ผู้ใช้เลือกห้อง/กดส่งเอง)
    ใช้ได้โดยไม่ต้องมี ADB"""
    from urllib.parse import quote
    app = ALIASES.get(a["app"].strip().lower(), a["app"].strip()).lower()
    text, to = a["text"], (a.get("to") or "").strip()
    if app in SHARE_LINKS:
        url = SHARE_LINKS[app](quote(text), to)
        ok, res = _open_link(url)
        return f"เปิด {app} พร้อมข้อความแล้ว ผู้ใช้ต้องกดส่งเอง {'' if ok else res[:120]}".strip()
    pkg = COMMON_APPS.get(app, app)
    if "." not in pkg:
        hits = [c.split("/")[0] for c in _launcher_components() if app in c.lower()]
        pkg = hits[0] if hits else pkg
    res = _sh(["am", "start", "--user", "0", "-a", "android.intent.action.SEND", "-t", "text/plain",
               "--es", "android.intent.extra.TEXT", text, "-p", pkg], quote=True)
    if "Error" in res or res.startswith("ERROR"):
        return f"ERROR: ส่งข้อความเข้า {pkg} ไม่ได้: {res[:200]}"
    return (f"เปิดหน้าส่งต่อของ {pkg} พร้อมข้อความแล้ว — ผู้ใช้ต้องเลือกห้องแชท/เพื่อน แล้วกดส่งเอง "
            f"(ถ้าอยากให้ส่งอัตโนมัติทั้งหมด ต้องเชื่อม ADB)")


_CLOCK_PKG = re.compile(r"clock|deskclock|alarm", re.I)
_CLOCK_OK = re.compile(r"^(?:บันทึก|ตกลง|เสร็จ(?:สิ้น)?|ยืนยัน|เรียบร้อย|เริ่ม(?:จับเวลา)?|save|ok|done|confirm|start|✓|✔)$", re.I)
_CLOCK_OK_ID = re.compile(r"save|done|confirm|ok_?(?:btn|button)?$|menu_ok|action_ok|btn_ok|start", re.I)
_CLOCK_NO = re.compile(r"ยกเลิก|cancel|ลบ|delete|discard", re.I)


def _confirm_clock(what):
    """แอปนาฬิกาบางยี่ห้อ (Huawei/Samsung/OPPO) ไม่สนคำขอ "ไม่ต้องแสดงหน้าจอ" แล้วเปิดหน้าตั้งค่าให้กดบันทึกเอง
    → ถ้าหน้านั้นค้างอยู่ กดปุ่มบันทึก/✓ ให้ · คืนข้อความบอกผล หรือ "" ถ้าไม่ต้องทำอะไร"""
    if config.MOCK_PHONE:
        return ""
    import screen_tools
    for _ in range(6):                                   # รอแอปนาฬิกาเปิด (สูงสุด ~3 วิ)
        time.sleep(0.5)
        fg = _fg() or ""
        if _CLOCK_PKG.search(fg):
            break
    else:
        return ""                                        # ไม่มีหน้าจอนาฬิกาเด้งขึ้น = ตั้งเสร็จในเบื้องหลังแล้ว
    time.sleep(0.6)
    try:
        items = screen_tools._elements(screen_tools._dump())
    except Exception as e:  # noqa: BLE001
        return f"(เปิดหน้า{what}ไว้ ถ้ายังไม่ขึ้นในรายการ ให้กดบันทึกเอง: {str(e)[:60]})"
    lab = lambda e: (e.get("text") or e.get("desc") or "").strip()  # noqa: E731
    btns = [e for e in items if not _CLOCK_NO.search(lab(e) + " " + (e.get("id") or ""))
            and (_CLOCK_OK.match(lab(e)) or _CLOCK_OK_ID.search(e.get("id") or ""))]
    if not btns:
        return ""                                        # อยู่หน้ารายการนาฬิกา (ตั้งแล้ว) ไม่มีอะไรต้องกด
    b = sorted(btns, key=lambda e: (not e.get("click"), e["y"]))[0]
    screen_tools.adb_shell(["input", "tap", str(b["x"]), str(b["y"])])
    print(time.strftime("[%H:%M:%S]"), f"⏰ กด {lab(b) or b.get('id')!r} ในแอปนาฬิกาให้แล้ว", flush=True)
    time.sleep(0.8)
    return "(กดบันทึกในแอปนาฬิกาให้แล้ว)"


def set_alarm(a, ctx):
    res = run([
        "am", "start", "--user", "0", "-a", "android.intent.action.SET_ALARM",
        "--ei", "android.intent.extra.alarm.HOUR", str(int(a["hour"])),
        "--ei", "android.intent.extra.alarm.MINUTES", str(int(a["minute"])),
        "--es", "android.intent.extra.alarm.MESSAGE", a.get("label", "ปลุก"),
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true",
    ])
    if "Error" in res or res.startswith("ERROR"):
        return res
    note = _confirm_clock("ตั้งปลุก")
    return f"ตั้งปลุก {int(a['hour']):02d}:{int(a['minute']):02d} แล้ว {note}".strip()


def set_timer(a, ctx):
    sec = int(float(a.get("seconds", 60)))
    if not 1 <= sec <= 24 * 3600:
        return "ERROR: เวลาจับต้องอยู่ระหว่าง 1 วินาที ถึง 24 ชั่วโมง"
    res = run([
        "am", "start", "--user", "0", "-a", "android.intent.action.SET_TIMER",
        "--ei", "android.intent.extra.alarm.LENGTH", str(sec),
        "--es", "android.intent.extra.alarm.MESSAGE", a.get("label", "จับเวลา"),
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true",
    ])
    if "Error" in res or res.startswith("ERROR"):
        return res
    note = _confirm_clock("จับเวลา")
    return f"เริ่มจับเวลา {sec // 60} นาที {sec % 60} วินาทีแล้ว {note}".replace(" 0 วินาที", "").strip()


def remind_me(a, ctx):
    minutes = float(a["minutes"])
    due = ctx.add_reminder(minutes, a["text"])
    return f"ตั้งเตือนแล้ว จะเตือนเวลา {due}"


def run_shell(a, ctx):
    out = run(["bash", "-c", a["command"]], timeout=int(a.get("timeout", 30)))
    return _truncate(out)


# ---------------------------------------------------------------- registry

def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "battery_status": (battery_status, "ดูสถานะแบตเตอรี่ (เปอร์เซ็นต์ ชาร์จอยู่ไหม อุณหภูมิ)", _obj(), False),
    "device_info": (device_info, "ดูข้อมูลเครื่อง รุ่น เวอร์ชัน Android/EMUI พื้นที่เก็บข้อมูล", _obj(), False),
    "get_location": (get_location, "ดูพิกัด GPS ปัจจุบันของมือถือ",
                     _obj({"provider": {"type": "string", "enum": ["network", "gps", "passive"]}}), False),
    "wifi_info": (wifi_info, "ดูข้อมูล Wi-Fi ที่เชื่อมต่ออยู่", _obj(), False),
    "list_sms": (list_sms, "อ่าน SMS ล่าสุด",
                 _obj({"limit": {"type": "integer"}, "box": {"type": "string", "enum": ["inbox", "sent", "all"]}}), False),
    "send_sms": (send_sms, "ส่ง SMS ไปยังเบอร์โทร (ต้องได้รับอนุญาต)",
                 _obj({"number": {"type": "string"}, "text": {"type": "string"}}, ["number", "text"]), True),
    "make_call": (make_call, "โทรออกไปยังเบอร์ (ต้องได้รับอนุญาต)",
                  _obj({"number": {"type": "string"}}, ["number"]), True),
    "find_contact": (find_contact, "ค้นหารายชื่อผู้ติดต่อด้วยชื่อหรือเบอร์",
                     _obj({"query": {"type": "string"}}, ["query"]), False),
    "call_log": (call_log, "ดูประวัติการโทรล่าสุด", _obj({"limit": {"type": "integer"}}), False),
    "list_notifications": (list_notifications, "อ่านการแจ้งเตือนที่ค้างอยู่บนมือถือ (LINE, แอปต่างๆ)", _obj(), False),
    "torch": (torch, "เปิด/ปิดไฟฉาย", _obj({"on": {"type": "boolean"}}, ["on"]), False),
    "get_volume": (get_volume, "ดูระดับเสียงทุกช่อง", _obj(), False),
    "volume_step": (volume_step, "เพิ่ม/ลด/ปิดเสียง ทีละขั้น", _obj({"direction": {"type": "string",
                    "enum": ["up", "down", "mute"]}, "steps": {"type": "integer"}}, ["direction"]), False),
    "set_volume": (set_volume, "ตั้งระดับเสียง",
                   _obj({"stream": {"type": "string", "enum": ["music", "ring", "alarm", "notification", "call", "system"]},
                         "volume": {"type": "integer"}}, ["stream", "volume"]), False),
    "set_brightness": (set_brightness, "ตั้งความสว่างหน้าจอ 0-255 หรือ 'auto'",
                       _obj({"level": {"type": "string", "description": "ตัวเลข 0-255 หรือ auto"}}, ["level"]), False),
    "vibrate": (vibrate, "สั่นเครื่อง", _obj({"ms": {"type": "integer"}}), False),
    "speak": (speak, "ให้มือถือพูดข้อความออกลำโพง (TTS)", _obj({"text": {"type": "string"}}, ["text"]), False),
    "take_photo": (take_photo, "ถ่ายรูปด้วยกล้องหลังหรือหน้า แล้วส่งรูปให้ผู้ใช้ (ต้องได้รับอนุญาต)",
                   _obj({"camera": {"type": "string", "enum": ["back", "front"]}}), True),
    "show_notification": (show_notification, "แสดงการแจ้งเตือนบนมือถือ",
                          _obj({"title": {"type": "string"}, "content": {"type": "string"}}, ["content"]), False),
    "get_clipboard": (get_clipboard, "อ่านข้อความในคลิปบอร์ด", _obj(), False),
    "set_clipboard": (set_clipboard, "คัดลอกข้อความลงคลิปบอร์ด", _obj({"text": {"type": "string"}}, ["text"]), False),
    "open_url": (open_url, "เปิดลิงก์บนมือถือ", _obj({"url": {"type": "string"}}, ["url"]), False),
    "list_apps": (list_apps, "ดูรายชื่อแอปที่ติดตั้ง (package name) ค้นด้วย query ได้",
                  _obj({"query": {"type": "string"}}), False),
    "open_app": (open_app, "เปิดแอป ใส่ชื่อทั่วไป (line, youtube, instagram, camera, settings ...) หรือ package name "
                           "| page = เปิดแล้วเข้าหน้านั้นต่อเลย (chat=แชท/DM, search, profile, notifications)",
                 _obj({"app": {"type": "string"},
                       "page": {"type": "string", "enum": ["chat", "search", "profile", "notifications", "home"]},
                       "fresh": {"type": "boolean", "description": "true = เริ่มที่หน้าแรกของแอป (ใช้เมื่อจะทำงานต่อในแอป)"}},
                      ["app"]), False),
    "diagnose_open": (lambda a, ctx: __import__("diag_open").run(a.get("app", "youtube")),
                      "ตรวจทีละขั้นว่าทำไมเปิดแอปไม่ได้ (ADB, GBox, ไอคอนบนจอ, อ่านหน้าจอ) ใช้เมื่อ open_app ล้มเหลว",
                      _obj({"app": {"type": "string"}}, ["app"]), False),
    "share_text": (share_text, "ส่งข้อความไปแอปแชท (LINE, Messenger, WhatsApp, Telegram, SMS ฯลฯ) โดยเปิดแอปพร้อม"
                   "ข้อความที่พิมพ์ไว้ให้ ผู้ใช้เลือกห้องและกดส่งเอง — ใช้วิธีนี้เมื่อไม่มี tool type_text",
                   _obj({"app": {"type": "string"}, "text": {"type": "string"},
                         "to": {"type": "string", "description": "เบอร์โทร (สำหรับ WhatsApp/SMS) ถ้ามี"}},
                        ["app", "text"]), False),
    "close_app": (close_app, "ปิดแอปใดก็ได้ (force stop): ชื่อที่เห็นบนจอ เช่น 'เครื่องคิดเลข', package, หลายแอปคั่นด้วย ',' "
                             "หรือ 'แอปนี้' = แอปที่เปิดอยู่ตอนนี้ / 'ทั้งหมด' = ปิดทุกแอป",
                  _obj({"app": {"type": "string"}}, ["app"]), False),
    "clean_ram": (clean_ram, "ล้างแรม/เคลียร์แอปเบื้องหลังให้เครื่องลื่น (aggressive=true ปิดแอปที่เปิดค้างด้วย ยกเว้นแอปแชท)",
                  _obj({"aggressive": {"type": "boolean"}}), False),
    "device_health": (device_health, "ตรวจสภาพเครื่อง: แบต สุขภาพแบต อุณหภูมิ แรม พื้นที่เก็บข้อมูล แอปที่กินแรม",
                      _obj(), False),
    "set_alarm": (set_alarm, "ตั้งนาฬิกาปลุกในแอปนาฬิกา",
                  _obj({"hour": {"type": "integer"}, "minute": {"type": "integer"}, "label": {"type": "string"}},
                       ["hour", "minute"]), False),
    "set_timer": (set_timer, "จับเวลา/นับถอยหลังในแอปนาฬิกา (ระบุเป็นวินาที)",
                  _obj({"seconds": {"type": "integer", "description": "จำนวนวินาที"}, "label": {"type": "string"}},
                       ["seconds"]), False),
    "remind_me": (remind_me, "ตั้งเตือนความจำ บอทจะส่งข้อความ Telegram + แจ้งเตือนบนมือถือเมื่อถึงเวลา",
                  _obj({"minutes": {"type": "number", "description": "อีกกี่นาทีนับจากตอนนี้"},
                        "text": {"type": "string"}}, ["minutes", "text"]), False),
}

import screen_tools  # noqa: E402  (ควบคุมหน้าจอผ่าน ADB)

import extras  # noqa: E402  (ความจำ/งานตามเวลา)
TOOLS.update(extras.TOOLS)
import system_tools  # noqa: E402  (ควบคุมระบบ wifi/บลูทูธ/จอ/สลับแอป)
TOOLS.update(system_tools.TOOLS)
import files_tools  # noqa: E402  (อ่าน/สรุปไฟล์ในเครื่อง)
TOOLS.update(files_tools.TOOLS)
import share_tools  # noqa: E402  (ส่งรูป/วิดีโอ/ไฟล์เข้าแอปไหนก็ได้ + สั่งแอป AI)
TOOLS.update(share_tools.TOOLS)
import app_skills  # noqa: E402  (ทักษะสำเร็จรูป: เปิดเพลง ค้นหาในแอป นำทาง)
TOOLS.update(app_skills.TOOLS)
import device  # noqa: E402
TOOLS.update(device.TOOLS)
import app_tasks  # noqa: E402
TOOLS.update(app_tasks.TOOLS)
import media  # noqa: E402
TOOLS.update(media.TOOLS)

if config.ENABLE_ADB:
    TOOLS.update(screen_tools.TOOLS)
    if os.environ.get("VISION_MODE", "1") != "0":
        import screen_task  # noqa: E402  (โหมดมองจอ: ทำงานหลายขั้นด้วยการดูภาพหน้าจอจริง)
        TOOLS.update(screen_task.TOOLS)


if config.ENABLE_SHELL:
    TOOLS["run_shell"] = (run_shell, "รันคำสั่ง bash ใน Termux บนมือถือ (ต้องได้รับอนุญาต) ใช้เมื่อไม่มี tool อื่นที่ตรง",
                          _obj({"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"]), True)


# เครื่องมือหลักที่ใช้บ่อย — ใช้กับโมเดลที่จำกัด token ต่อคำขอ (เช่น Groq ฟรี)
CORE_TOOLS = [
    "battery_status", "device_health", "clean_ram", "get_location",
    "list_sms", "send_sms", "make_call", "find_contact", "list_notifications",
    "torch", "set_volume", "brightness", "speak",
    "open_app", "close_app", "read_screen", "tap_text", "type_text", "swipe", "screen_task",
    "wifi", "bluetooth", "remember", "schedule", "remind_me", "set_alarm", "set_timer", "send_to_app", "send_dm",
]


# สำหรับโมเดลบนคอม (Ollama): ส่งเครื่องมือหลัก + กลุ่มที่เกี่ยวกับข้อความ → เลือกแม่นขึ้น ประมวลผลเร็วขึ้น
LOCAL_BASE = [
    "open_app", "close_app", "list_apps", "web_search", "wifi", "bluetooth", "torch", "brightness",
    "battery_status", "device_health", "clean_ram", "list_notifications", "speak", "set_volume",
    "remind_me", "schedule", "read_screen", "tap_text", "type_text", "go_home", "system_check", "api_balance",
    "screen_task",
]
LOCAL_GROUPS = [
    (("ทัก", "dm", "ไดเร็ก"), ["send_dm"]),
    (("จอ", "แตะ", "กด", "พิมพ์", "ส่ง", "แชท", "line", "ไลน์", "facebook", "เฟส", "ig", "อินสตา", "โพสต์", "แชร์",
      "คอมเมนต์", "เลื่อน", "ปัด", "แคป", "screenshot", "ข้อความ"),
     ["send_dm", "read_screen", "screenshot", "tap", "tap_text", "tap_visual", "type_text", "swipe", "press_key", "share_text",
      "adb_connect"]),
    (("โหมด", "หมุน", "ล็อก", "ล็อค", "ห้ามรบกวน", "เครื่องบิน", "เน็ต", "แถบ", "สลับ", "แอปล่าสุด", "ปุ่ม", "ดับจอ",
      "อัดจอ", "บันทึกหน้าจอ"),
     ["airplane_mode", "mobile_data", "rotate_screen", "lock_screen", "screen_timeout", "open_panel", "recent_apps",
      "switch_last_app", "press_button", "do_not_disturb", "screen_record"]),
    (("นาฬิกา", "ชีพจร", "หัวใจ", "ก้าว", "นอน", "หลับ", "สุขภาพ", "ออกซิเจน", "watch"),
     ["watch_health", "watch_notify", "watch_menu"]),
    (("คลิปบอร์ด", "คัดลอก", "ก๊อป", "copy", "วาง"), ["get_clipboard", "set_clipboard"]),
    (("เตือน", "ตั้งเวลา", "จับเวลา", "ปลุก", "ทุกวัน", "ทุกเช้า", "ทุกคืน", "งานที่ตั้ง", "ยกเลิก"),
     ["schedule", "list_schedules", "cancel_schedule", "remind_me", "set_alarm", "set_timer"]),
    (("รูป", "ภาพ", "คลิป", "วิดีโอ", "วีดีโอ", "ไฟล์", "อัพโหลด", "อัปโหลด", "upload", "แนบ", "แชร์", "ส่ง",
      "โพสต์", "สตอรี่", "claude", "คลอด", "chatgpt", "gpt", "gemini", "เจมิไน", "ถาม ai", "ถามเอไอ"),
     ["send_to_app", "send_dm", "ask_ai_app", "prepare_upload", "find_files", "take_photo", "screenshot"]),
    (("แบต", "เครื่อง", "ร้อน", "แรม", "พื้นที่", "ช้า", "รุ่น"), ["battery_status", "device_health", "clean_ram", "device_info"]),
    (("สาย", "โทร"), ["answer_call", "end_call"]),
    (("เสียง", "ลำโพง", "พูด", "สั่น", "ดัง", "เบา"), ["set_volume", "get_volume", "speak", "vibrate"]),
    (("ลิงก์", "url", "เว็บ", "http", "www"), ["open_url"]),
    (("ที่ไหน", "ตำแหน่ง", "พิกัด", "gps", "wi-fi ที่ต่อ", "ไวไฟที่ต่อ"), ["get_location", "wifi_info"]),
    (("แจ้งเตือน",), ["list_notifications", "show_notification"]),
    (("รัน", "shell", "คำสั่ง bash", "termux"), ["run_shell"]),
    (("ไฟล์", "เอกสาร", "pdf", "word", "excel", "สรุป", "อ่าน", "โฟลเดอร์", "ดาวน์โหลด", "download", "รายงาน",
      "ตาราง", "สไลด์"), ["find_files", "read_file"]),
    (("กล้อง", "หน้าฉัน", "หน้าผม", "เห็นฉัน", "เห็นผม", "มองฉัน", "มองผม", "ดูฉัน", "ดูผม", "อารมณ์", "เครียด",
      "เหนื่อย", "ความรู้สึก", "สีหน้า"), ["look_at_user"]),
]


def relevant_tool_specs(text):
    """ชุดเครื่องมือสำหรับโมเดลเล็ก: พื้นฐาน + กลุ่มที่คำในข้อความเกี่ยวข้อง (ใช้ชื่อ/รายละเอียดเต็ม)"""
    low = (text or "").lower()
    want = list(LOCAL_BASE)
    for words, names in LOCAL_GROUPS:
        if any(w in low for w in words):
            want += [n for n in names if n not in want]
    full = claude_tool_specs()
    by_name = {s.get("name"): s for s in full}
    return [by_name[n] for n in want if n in by_name]


def _strip_schema(sc):
    """ตัดคำอธิบายใน schema ออกเพื่อประหยัด token (เหลือแค่โครงสร้าง)"""
    out = {"type": sc.get("type", "object"), "properties": {}}
    for k, v in (sc.get("properties") or {}).items():
        nv = {"type": v.get("type", "string")}
        if v.get("enum"):
            nv["enum"] = v["enum"]
        out["properties"][k] = nv
    if sc.get("required"):
        out["required"] = sc["required"]
    return out


LEAN_TOOLS = [      # งานหลายขั้นในแอป (เครื่องมือน้อย = AI เลือกถูก + คำขอเล็ก พอดีโควตา Groq ฟรี)
    "play_media", "search_in_app", "navigate", "open_app", "close_app", "read_screen", "tap_text", "tap",
    "tap_visual", "type_text", "swipe", "press_key", "send_dm", "send_to_app", "find_files", "read_file",
    "list_notifications", "brightness", "volume_step",
]


def claude_tool_specs(core_only=False, lean=False):
    # core_only: ส่งเฉพาะเครื่องมือหลัก (ย่อคำอธิบาย) เพื่อลดขนาดคำขอให้พอดีลิมิต token
    # lean: ชุดเครื่องมือหลักสำหรับงานบนจอ (น้อย = AI เลือกถูก)
    off = config.DISABLED_TOOLS
    if lean:
        specs = [{"name": n, "description": TOOLS[n][1], "input_schema": TOOLS[n][2]}
                 for n in LEAN_TOOLS if n in TOOLS and n not in off]
        if config.ENABLE_WEB_SEARCH:
            specs.append({"type": "web_search_20250305", "name": "web_search", "max_uses": config.WEB_SEARCH_MAX_USES})
        return specs
    if core_only:
        specs = []
        for n in CORE_TOOLS:
            if n in TOOLS and n not in off:
                _, d, sc, _ = TOOLS[n]
                specs.append({"name": n, "description": d.split("(")[0].split(" — ")[0][:55],
                              "input_schema": _strip_schema(sc)})
    else:
        specs = [{"name": n, "description": d, "input_schema": s}
                 for n, (_, d, s, _) in TOOLS.items() if n not in off]
    if config.ENABLE_WEB_SEARCH:
        specs.append({"type": "web_search_20250305", "name": "web_search",
                      "max_uses": config.WEB_SEARCH_MAX_USES})
    return specs


def describe_action(name, args):
    """ข้อความสำหรับขออนุญาตผู้ใช้"""
    if name == "send_sms":
        return f"ส่ง SMS ถึง {args.get('number')}\nข้อความ: {args.get('text')}"
    if name == "make_call":
        return f"โทรออกไปที่ {args.get('number')}"
    if name == "take_photo":
        return f"ถ่ายรูปด้วยกล้อง{'หน้า' if args.get('camera') == 'front' else 'หลัง'}"
    if name == "type_text":
        return f"พิมพ์ข้อความลงในแอปที่เปิดอยู่:\n{args.get('text')}"
    if name == "run_shell":
        return f"รันคำสั่ง:\n{args.get('command')}"
    return f"{name} {json.dumps(args, ensure_ascii=False)}"
