"""ควบคุมระบบเครื่อง: Wi-Fi, บลูทูธ, โหมดเครื่องบิน, ความสว่าง, หมุนจอ, สลับแอป, แบ่งจอ,
แถบตั้งค่าด่วน, สกรีนช็อต/อัดจอ, ล็อกจอ ฯลฯ — ใช้คำสั่งตรง (เร็วกว่าการแตะทีละปุ่ม)
ส่วนใหญ่ต้องเชื่อม ADB (บางอย่างใช้ Termux:API ได้เลย)
"""
import os
import time

import config

KEY = {"home": 3, "back": 4, "recent": 187, "power": 26, "lock": 223, "wake": 224, "split": 187,
       "notifications": 83, "settings": 176, "brightness_up": 221, "brightness_down": 220,
       "volume_up": 24, "volume_down": 25, "mute": 164, "assist": 219, "search": 84,
       "app_switch": 187, "menu": 82, "screenshot": 120, "camera": 27, "play_pause": 85}


def _sh(args, timeout=30):
    import phone_tools
    return phone_tools._sh(args, timeout=timeout)


def _run(args, timeout=30):
    import phone_tools
    return phone_tools.run(args, timeout=timeout)


def _adb():
    import screen_tools
    return bool(screen_tools.adb_serial())


_BAD = ("error", "exception", "permission", "denied", "not allowed", "unknown command", "usage:",
        "killed", "not found", "failure", "failed", "no service", "invalid", "can't find service",
        "please grant", "not permitted", "no shell command implementation")


def _ok(out):
    low = (out or "").lower()
    return not any(b in low for b in _BAD)


def _first_ok(cmds, adb=True):
    """ลองคำสั่งทีละแบบจนเจอแบบที่ไม่ error คืน (สำเร็จไหม, ข้อความสุดท้าย)"""
    last = ""
    for c in cmds:
        out = _sh(c) if adb else _run(c)
        if _ok(out):
            return True, out
        last = out
    return False, last


def _settings(ns, key, val):
    return _sh(["settings", "put", ns, key, str(val)])


def _get(ns, key):
    v = _sh(["settings", "get", ns, key]).strip()
    return v if v.lstrip("-").replace(".", "", 1).isdigit() else None


def _state(kind):
    """อ่านสถานะจริงจากเครื่อง (ต้องมี ADB) คืน True/False หรือ None ถ้าอ่านไม่ได้"""
    if kind == "wifi":
        low = _sh(["cmd", "wifi", "status"]).lower()
        if "wifi is enabled" in low:
            return True
        if "wifi is disabled" in low:
            return False
    key = {"wifi": "wifi_on", "bluetooth": "bluetooth_on", "airplane": "airplane_mode_on",
           "data": "mobile_data", "dnd": "zen_mode"}.get(kind)
    if not key:
        return None
    v = _get("global", key)
    return None if v is None else v != "0"


def _wait_state(kind, want, secs=5):
    """รอให้สถานะเปลี่ยนตามที่สั่ง คืน True=สำเร็จ False=ไม่เปลี่ยน None=อ่านสถานะไม่ได้"""
    for i in range(int(secs / 0.7) + 1):
        st = _state(kind)
        if st is None:
            return None
        if st == want:
            return True
        time.sleep(0.7)
    return False


def _open_settings(action):
    """เปิดหน้าตั้งค่าให้ผู้ใช้แตะเอง (ใช้ได้แม้ไม่มี ADB)"""
    out = _sh(["am", "start", "--user", "0", "-a", action])
    if not _ok(out):
        out = _run(["am", "start", "-a", action])
    return _ok(out)


_NO_ADB = "ต่อ ADB ไว้จะสั่งได้ตรงๆ (รัน เปิดADBให้แท็บเล็ต.bat บนคอม หรือสั่ง adb_connect)"


def _toggle(kind, label, on, adb_cmds, api_cmds=(), settings_action=None):
    """สั่งเปิด/ปิด แล้วตรวจสถานะจริง — ไม่ตอบว่า 'ทำแล้ว' ถ้ายังไม่ได้ทำจริง"""
    want = "เปิด" if on else "ปิด"
    reason = ""
    if config.ANDROID_APP:                       # แอป APK: แตะปุ่มในแผงควบคุมให้ + ตรวจสถานะด้วย API ของระบบ
        import android_shim
        return android_shim.qs_toggle(kind, label, on)
    if _adb():
        if _state(kind) == on:
            return f"{label} {want}อยู่แล้ว"
        ok, out = _first_ok(adb_cmds)
        st = _wait_state(kind, on)
        if st or (st is None and ok):
            return f"{want} {label} แล้ว"
        reason = "ระบบไม่ยอมให้สั่งผ่าน ADB" if ok else f"คำสั่งถูกปฏิเสธ: {out[:80]}"
    if api_cmds:
        ok, out = _first_ok(api_cmds, adb=False)
        if ok and (not _adb() or _wait_state(kind, on) is not False):   # มี ADB → ตรวจซ้ำว่าเปลี่ยนจริง
            return f"{want} {label} แล้ว"
        reason = reason or f"Termux:API สั่งไม่ได้: {out[:80]}"
    reason = reason or "ยังไม่ได้เชื่อม ADB"
    if settings_action and _open_settings(settings_action):
        hint = "" if _adb() else f" — {_NO_ADB}"
        return f"สั่ง{want} {label} ตรงๆ ไม่ได้ ({reason}) เลยเปิดหน้าตั้งค่า {label} ให้แล้ว แตะสวิตช์ได้เลย{hint}"
    return f"ERROR: {want} {label} ไม่สำเร็จ ({reason}) — {_NO_ADB}"


def _restore_later(minutes, fn, on):
    """ตั้งเวลาเปิดกลับอัตโนมัติ (กันบอทหลุดเน็ตถาวร)"""
    import threading
    t = threading.Timer(minutes * 60, lambda: fn({"on": on}, None))
    t.daemon = True
    t.start()


def _need_adb():
    return None if _adb() else f"ERROR: คำสั่งนี้ต้องเชื่อม ADB ก่อน — {_NO_ADB}"


# ---------------------------------------------------------------- การเชื่อมต่อ

def wifi(a, ctx):
    on = bool(a.get("on", True))
    res = _toggle("wifi", "Wi-Fi", on,
                  [["svc", "wifi", "enable" if on else "disable"],
                   ["cmd", "wifi", "set-wifi-enabled", "enabled" if on else "disabled"]],
                  [["termux-wifi-enable", "true" if on else "false"]],
                  "android.settings.panel.action.WIFI")
    mins = a.get("minutes")
    if not on and mins and not res.startswith("ERROR") and "ตรงๆ ไม่ได้" not in res:
        _restore_later(float(mins), wifi, True)
        res += f" (จะเปิดกลับเองใน {mins} นาที)"
    elif not on and not res.startswith("ERROR"):
        res += " — ระหว่างนี้บอท Telegram จะติดต่อไม่ได้จนกว่าจะเปิด Wi-Fi กลับ"
    return res


def bluetooth(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("bluetooth", "บลูทูธ", on,
                   [["svc", "bluetooth", "enable" if on else "disable"],
                    ["cmd", "bluetooth_manager", "enable" if on else "disable"]],
                   settings_action="android.settings.BLUETOOTH_SETTINGS")


def airplane(a, ctx):
    on = bool(a.get("on", True))
    res = _toggle("airplane", "โหมดเครื่องบิน", on,
                  [["cmd", "connectivity", "airplane-mode", "enable" if on else "disable"]],
                  settings_action="android.settings.AIRPLANE_MODE_SETTINGS")
    mins = a.get("minutes")
    if on and mins and not res.startswith("ERROR") and "ตรงๆ ไม่ได้" not in res:
        _restore_later(float(mins), airplane, False)
        res += f" (จะปิดโหมดเครื่องบินเองใน {mins} นาที)"
    return res


def mobile_data(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("data", "เน็ตมือถือ", on,
                   [["svc", "data", "enable" if on else "disable"],
                    ["cmd", "phone", "data", "enable" if on else "disable"]],
                   settings_action="android.settings.panel.action.INTERNET_CONNECTIVITY")


def location(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("location", "ตำแหน่ง (GPS)", on, [["settings", "put", "secure", "location_mode", "3" if on else "0"]],
                   settings_action="android.settings.LOCATION_SOURCE_SETTINGS")


def hotspot(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("hotspot", "ฮอตสปอต", on, [["cmd", "connectivity", "tether", "start" if on else "stop"]],
                   settings_action="android.settings.WIRELESS_SETTINGS")


def nfc(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("nfc", "NFC", on, [["svc", "nfc", "enable" if on else "disable"]],
                   settings_action="android.settings.NFC_SETTINGS")


def flashlight(a, ctx):
    import phone_tools
    return phone_tools.torch({"on": a.get("on", True)}, ctx)


# ---------------------------------------------------------------- จอภาพ

def _put_checked(ns, key, val):
    """settings put แล้วอ่านกลับว่าค่าเปลี่ยนจริง (ต้องมี ADB) คืน True/False/None"""
    out = _settings(ns, key, val)
    if not _ok(out):
        return False
    got = _get(ns, key)
    return None if got is None else got == str(val)


_granted = {"ok": False}


def _grant_termux_api():
    """ให้สิทธิ์ 'แก้ไขการตั้งค่าระบบ' กับ Termux:API ผ่าน ADB (ทำครั้งเดียว) — หลังจากนี้ปรับความสว่าง
    ได้แม้ ADB หลุด และไม่มีจอแดง Termux:API Error"""
    if _granted["ok"] or not _adb():
        return
    out = _sh(["appops", "get", "com.termux.api", "WRITE_SETTINGS"])
    if "allow" not in out.lower():
        _sh(["appops", "set", "com.termux.api", "WRITE_SETTINGS", "allow"])
    _granted["ok"] = True


def _parse_level(lvl, current):
    """'50%' / '128' / '+20%' / '-20%' / 'up' / 'down' → ค่า 1-255"""
    step = {"up": "+20%", "down": "-20%", "เพิ่ม": "+20%", "ลด": "-20%"}
    lvl = step.get(lvl, lvl)
    rel = lvl[:1] in "+-"
    n = float(lvl.lstrip("+").rstrip("%"))           # ValueError ถ้าไม่ใช่ตัวเลข
    delta = n * 255 / 100 if "%" in lvl else n
    val = current + delta if rel else delta
    return max(1, min(255, int(round(val))))


def brightness(a, ctx):
    lvl = str(a.get("level", "")).strip().lower().replace(" ", "")
    adb = _adb()
    if adb:
        _grant_termux_api()
    if lvl == "auto":
        if adb and _put_checked("system", "screen_brightness_mode", 1) is not False:
            if _get("system", "hw_screen_brightness_mode_value") is not None:
                _settings("system", "hw_screen_brightness_mode_value", 1)
            return "ตั้งความสว่างอัตโนมัติแล้ว"
        if _open_settings("android.settings.DISPLAY_SETTINGS"):
            return f"ตั้งความสว่างอัตโนมัติตรงๆ ไม่ได้ เปิดหน้าตั้งค่าจอให้แล้ว — {_NO_ADB}"
        return f"ERROR: ตั้งความสว่างอัตโนมัติไม่ได้ — {_NO_ADB}"
    cur = _get("system", "screen_brightness") if adb else None
    try:
        val = _parse_level(lvl, int(float(cur)) if cur else 128)
    except ValueError:
        return "ERROR: ระบุความสว่างเป็น 0-100%, 0-255, +20% / -20% หรือ auto"
    pct = round(val * 100 / 255)
    if adb:
        # ปิดโหมดอัตโนมัติก่อน ไม่งั้นระบบจะปรับทับ (Huawei มีคีย์ของตัวเองเพิ่มอีกตัว)
        _settings("system", "screen_brightness_mode", 0)
        if _get("system", "hw_screen_brightness_mode_value") is not None:
            _settings("system", "hw_screen_brightness_mode_value", 0)
        if _put_checked("system", "screen_brightness", val) is not False:
            return f"ตั้งความสว่าง {pct}% แล้ว"
    out = _run(["termux-brightness", str(val)])
    if _ok(out):
        return f"ตั้งความสว่าง {pct}% แล้ว"
    if "write_settings" in out.lower() and _open_settings("android.settings.action.MANAGE_WRITE_SETTINGS"):
        return ("ตั้งความสว่างไม่ได้ เพราะ Termux:API ยังไม่ได้รับสิทธิ์ 'แก้ไขการตั้งค่าระบบ' — "
                "เปิดหน้าตั้งสิทธิ์ให้แล้ว เลือก Termux:API แล้วเปิดสวิตช์ จากนั้นสั่งใหม่ได้เลย")
    return f"ERROR: ตั้งความสว่างไม่ได้ ({out[:80]}) — {_NO_ADB}"


def rotate(a, ctx):
    if config.ANDROID_APP and not a.get("orientation"):
        import android_shim
        return android_shim.rotate_auto(bool(a.get("auto", False)))
    err = _need_adb()
    if err:
        _open_settings("android.settings.DISPLAY_SETTINGS")
        return err + " (เปิดหน้าตั้งค่าจอให้แล้ว)"
    lock = not a.get("auto", False)
    if _put_checked("system", "accelerometer_rotation", 0 if lock else 1) is False:
        return "ERROR: ระบบไม่ยอมให้เปลี่ยนการหมุนจอ"
    if lock and a.get("orientation"):
        o = {"portrait": 0, "landscape": 1, "portrait_reverse": 2, "landscape_reverse": 3}.get(
            a["orientation"], 0)
        _settings("system", "user_rotation", o)
        return f"หมุนจอเป็นแนว{'ตั้ง' if o in (0, 2) else 'นอน'}แล้ว (ล็อกไว้)"
    return "ตั้งหมุนจออัตโนมัติแล้ว" if not lock else "ล็อกการหมุนจอแล้ว"


def lock_screen(a, ctx):
    err = _need_adb()
    if err:
        return err
    _sh(["input", "keyevent", str(KEY["power"])])
    return "ล็อกหน้าจอแล้ว"


def screen_timeout(a, ctx):
    sec = int(a.get("seconds", 60))
    err = _need_adb()
    if err:
        _open_settings("android.settings.DISPLAY_SETTINGS")
        return err + " (เปิดหน้าตั้งค่าจอให้แล้ว)"
    if _put_checked("system", "screen_off_timeout", sec * 1000) is False:
        return "ERROR: ระบบไม่ยอมให้เปลี่ยนเวลาดับจอ"
    return f"ตั้งดับหน้าจอหลังไม่ใช้งาน {sec} วินาทีแล้ว"


# ---------------------------------------------------------------- แถบ / หน้าต่าง

def panel(a, ctx):
    err = _need_adb()
    if err:
        return err
    which = a.get("which", "notifications")
    cmd = {"notifications": "statusbar expand-notifications", "quick_settings": "statusbar expand-settings",
           "collapse": "statusbar collapse"}.get(which, "statusbar expand-notifications")
    _sh(["cmd"] + cmd.split())
    return {"notifications": "เปิดแถบแจ้งเตือนแล้ว", "quick_settings": "เปิดแถบตั้งค่าด่วนแล้ว",
            "collapse": "ปิดแถบแล้ว"}[which]


def recent_apps(a, ctx):
    err = _need_adb()
    if err:
        return err
    _sh(["input", "keyevent", str(KEY["recent"])])
    return "เปิดหน้าแอปล่าสุดแล้ว"


def switch_last_app(a, ctx):
    err = _need_adb()
    if err:
        return err
    _sh(["input", "keyevent", str(KEY["recent"])])
    time.sleep(0.6)
    _sh(["input", "keyevent", str(KEY["recent"])])
    return "สลับไปแอปก่อนหน้าแล้ว"


def go_home(a, ctx):
    if _adb() and _ok(_sh(["input", "keyevent", str(KEY["home"])])):
        return "กลับหน้าโฮมแล้ว"
    out = _run(["am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"])
    return "กลับหน้าโฮมแล้ว" if _ok(out) else f"ERROR: กลับหน้าโฮมไม่ได้ ({out[:80]})"


def press(a, ctx):
    err = _need_adb()
    if err:
        return err
    k = a["button"]
    code = KEY.get(k, k)
    _sh(["input", "keyevent", str(code)])
    return f"กดปุ่ม {k} แล้ว"


def do_not_disturb(a, ctx):
    on = bool(a.get("on", True))
    return _toggle("dnd", "โหมดห้ามรบกวน", on,
                   [["cmd", "notification", "set_dnd", "priority" if on else "off"],
                    ["cmd", "notification", "set_dnd", "on" if on else "off"],
                    ["settings", "put", "global", "zen_mode", "1" if on else "0"]],
                   settings_action="android.settings.ZEN_MODE_SETTINGS")


# ---------------------------------------------------------------- ตรวจว่าเครื่องนี้สั่งอะไรได้บ้าง

def diagnose(a=None, ctx=None):
    """ตรวจแบบไม่เปลี่ยนการตั้งค่า: ADB, Termux:API, สิทธิ์ และอ่านสถานะปัจจุบัน"""
    lines = []
    adb = _adb()
    lines.append(f"{'🟢' if adb else '🔴'} ADB: {'เชื่อมแล้ว — สั่งระบบได้เต็มที่' if adb else 'ยังไม่เชื่อม — สั่งระบบได้จำกัด'}")
    api = _run(["termux-wifi-connectioninfo"])
    lines.append(f"{'🟢' if _ok(api) else '🔴'} Termux:API: {'ใช้ได้' if _ok(api) else api[:80]}")
    if adb:
        names = {"wifi": "Wi-Fi", "bluetooth": "บลูทูธ", "airplane": "โหมดเครื่องบิน",
                 "data": "เน็ตมือถือ", "dnd": "ห้ามรบกวน"}
        for k, n in names.items():
            st = _state(k)
            lines.append(f"   • {n}: {'เปิด' if st else 'ปิด' if st is False else 'อ่านไม่ได้'}")
        b = _get("system", "screen_brightness")
        lines.append(f"   • ความสว่าง: {int(b) * 100 // 255 if b and b.isdigit() else 'อ่านไม่ได้'}%")
        for name, cmd in (("svc", ["svc"]), ("cmd wifi", ["cmd", "wifi", "help"]),
                          ("cmd connectivity", ["cmd", "connectivity", "help"])):
            out = _sh(cmd)
            usable = bool(out.strip()) and "can't find service" not in out.lower() and "not found" not in out.lower()
            lines.append(f"   {'✅' if usable else '⚠️'} คำสั่ง {name}: {'มี' if usable else 'ไม่มีในเครื่องนี้'}")
    else:
        lines.append("   → Wi-Fi สั่งผ่าน Termux:API ได้ ส่วนบลูทูธ/โหมดเครื่องบิน/ห้ามรบกวน/หมุนจอ ต้องใช้ ADB")
        lines.append(f"   → {_NO_ADB}")
    return "ผลตรวจการควบคุมระบบ:\n" + "\n".join(lines)


# ---------------------------------------------------------------- บันทึกภาพ/วิดีโอหน้าจอ

def screen_record(a, ctx):
    err = _need_adb()
    if err:
        return err
    import screen_tools
    sec = min(180, int(a.get("seconds", 15)))
    remote = "/sdcard/screenrec_ai.mp4"
    _sh(["screenrecord", "--time-limit", str(sec), remote], timeout=sec + 15)
    out_dir = os.path.expanduser("~/storage/movies")
    os.makedirs(out_dir, exist_ok=True) if os.path.isdir(os.path.dirname(out_dir)) else None
    local = os.path.join(out_dir if os.path.isdir(out_dir) else config.DATA_DIR, "screenrec.mp4")
    _run_pull = __import__("phone_tools").run
    _run_pull(["adb", "-s", screen_tools.adb_serial(), "pull", remote, local], timeout=60)
    _sh(["rm", remote])
    if ctx is not None and hasattr(ctx, "send_file") and os.path.exists(local) and os.path.getsize(local) < 48e6:
        try:
            ctx.send_file(local, kind="video")
        except Exception:  # noqa: BLE001
            pass
    return f"อัดหน้าจอ {sec} วินาทีแล้ว → {local}"


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_on = {"on": {"type": "boolean"}}

TOOLS = {
    "wifi": (wifi, "เปิด/ปิด Wi-Fi (ปิดแล้วบอทจะหลุดเน็ต — ใส่ minutes เพื่อให้เปิดกลับเองอัตโนมัติ)",
             _obj({"on": {"type": "boolean"}, "minutes": {"type": "number"}}, ["on"]), False),
    "bluetooth": (bluetooth, "เปิด/ปิด บลูทูธ", _obj(_on, ["on"]), False),
    "airplane_mode": (airplane, "เปิด/ปิด โหมดเครื่องบิน (ใส่ minutes เพื่อให้ปิดเองอัตโนมัติ)",
                      _obj({"on": {"type": "boolean"}, "minutes": {"type": "number"}}, ["on"]), False),
    "system_check": (diagnose, "ตรวจว่าเครื่องนี้สั่งควบคุมระบบอะไรได้บ้าง (ADB, Termux:API, สถานะ Wi-Fi/บลูทูธ ฯลฯ) "
                     "ใช้เมื่อสั่งเปิด/ปิดระบบไม่สำเร็จ", _obj(), False),
    "mobile_data": (mobile_data, "เปิด/ปิด เน็ตมือถือ (ซิม)", _obj(_on, ["on"]), False),
    "brightness": (brightness, "ตั้งความสว่างหน้าจอ: level เป็น '50%', 0-255, 'auto' หรือปรับจากเดิม "
                               "'+20%' (เพิ่ม) / '-20%' (ลด)",
                   _obj({"level": {"type": "string"}}, ["level"]), False),
    "rotate_screen": (rotate, "ล็อก/ปลดล็อกการหมุนจอ หรือหมุนเป็นแนวตั้ง/นอน",
                      _obj({"auto": {"type": "boolean"}, "orientation":
                            {"type": "string", "enum": ["portrait", "landscape"]}}), False),
    "lock_screen": (lock_screen, "ล็อกหน้าจอ (ดับจอ)", _obj(), False),
    "screen_timeout": (screen_timeout, "ตั้งเวลาดับหน้าจอเมื่อไม่ใช้งาน (วินาที)",
                       _obj({"seconds": {"type": "integer"}}, ["seconds"]), False),
    "open_panel": (panel, "เปิดแถบแจ้งเตือน/แถบตั้งค่าด่วน หรือปิดแถบ",
                   _obj({"which": {"type": "string", "enum": ["notifications", "quick_settings", "collapse"]}}), False),
    "recent_apps": (recent_apps, "เปิดหน้าแอปที่เปิดล่าสุด (สำหรับสลับแอป/แบ่งจอ)", _obj(), False),
    "switch_last_app": (switch_last_app, "สลับกลับไปแอปก่อนหน้าทันที", _obj(), False),
    "go_home": (go_home, "กลับหน้าจอหลัก", _obj(), False),
    "press_button": (press, "กดปุ่มระบบ",
                     _obj({"button": {"type": "string", "enum": list(KEY)}}, ["button"]), False),
    "do_not_disturb": (do_not_disturb, "เปิด/ปิด โหมดห้ามรบกวน", _obj(_on, ["on"]), False),
    "location": (location, "เปิด/ปิด ตำแหน่ง GPS", _obj(_on, ["on"]), False),
    "hotspot": (hotspot, "เปิด/ปิด ฮอตสปอต (ปล่อยเน็ต)", _obj(_on, ["on"]), False),
    "nfc": (nfc, "เปิด/ปิด NFC", _obj(_on, ["on"]), False),
    "screen_record": (screen_record, "อัดวิดีโอหน้าจอ (วินาที) แล้วส่งให้ (ต้องเชื่อม ADB)",
                      _obj({"seconds": {"type": "integer"}}), False),
}
