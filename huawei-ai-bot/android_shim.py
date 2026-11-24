"""โหมดแอป APK: แปลงคำสั่งเดิม (adb shell / termux-* / am / settings ...) → ระบบ Android ผ่าน Bridge (Kotlin)

โค้ดบอทส่วนอื่นเรียก phone_tools.run([...]) เหมือนเดิมทุกอย่าง — ไฟล์นี้ทำหน้าที่เป็น "ADB + Termux:API จำลอง"
ด้วยสิทธิ์ของแอป: Accessibility (อ่านจอ/แตะ/พิมพ์), Notification Listener (อ่าน/ตอบแจ้งเตือน), API ระบบ
คำสั่งที่แอปทำเองไม่ได้ (เช่น เปิด/ปิด Wi-Fi ตรงๆ) จะคืน ERROR → โค้ดเดิมจะเปิดหน้าตั้งค่าแล้วกดให้แทน
"""
import json
import os
import re
import shlex
import subprocess
import time

B = None                      # Bridge (Kotlin) — เทสต์แทนด้วยตัวจำลองได้
_vfs = {}                     # ไฟล์จำลองบน /sdcard (เช่น ผล uiautomator dump)


def bridge():
    global B
    if B is None:
        from java import jclass  # มีเฉพาะในแอป (Chaquopy)
        B = jclass("com.aibot.assistant.Bridge")
    return B


NOT_READY = ("ERROR: ยังไม่ได้เปิดสิทธิ์ 'คุมหน้าจอ' ของแอปผู้ช่วย — เปิดแอป → 🔐 สิทธิ์ → คุมหน้าจอ (Accessibility) "
             "→ เลือก 'ผู้ช่วย AI — ควบคุมหน้าจอ' → เปิด")


def serial():
    """แทน adb serial: พร้อมเมื่อเปิด Accessibility แล้ว"""
    try:
        return "app" if bridge().a11yOn() else None
    except Exception:  # noqa: BLE001
        return None


def _s(x):
    return "" if x is None else str(x)


def _ok(b, msg="OK"):
    return msg if b else "ERROR: ทำไม่สำเร็จ"


# ================================================================ ทางเข้าหลัก

def run(cmd, timeout=30, input_text=None):
    cmd = [str(c) for c in cmd]
    if not cmd:
        return ""
    head = os.path.basename(cmd[0])
    try:
        if head == "adb":
            return _adb(cmd[1:])
        if head.startswith("termux-"):
            return termux(head, cmd[1:], input_text)
        if head in ("bash", "sh") and len(cmd) >= 3 and cmd[1] == "-c":
            return _sh_c(cmd[2], timeout)
        return shell(cmd, timeout)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _adb(a):
    if a[:1] == ["-s"]:
        a = a[2:]
    if not a:
        return ""
    sub = a[0]
    if sub == "devices":
        return "List of devices attached\n" + ("app\tdevice\n" if serial() else "")
    if sub in ("connect", "disconnect", "pair", "kill-server", "start-server", "mdns", "reconnect"):
        return "already connected to app" if sub == "connect" else ""
    if sub in ("shell", "exec-out"):
        return shell(a[1:])
    return f"ERROR: adb {sub} ไม่รองรับในโหมดแอป"


def _sh_c(script, timeout=30):
    """คำสั่งแบบ sh -c ที่โค้ดเดิมใช้"""
    m = re.search(r"exec-out screencap -p > '([^']+)'", script)
    if m:
        return _ok(bridge().screenshot(m.group(1)))
    if "mCurrentFocus" in script or "mFocusedApp" in script:
        return _focus()
    if "SurfaceOrientation" in script:
        return f"SurfaceOrientation: {bridge().rotation()}"
    if "dumpsys window" in script:
        return _focus()
    try:                                                    # อย่างอื่น: รันด้วย sh ของเครื่องตามสิทธิ์แอป
        p = subprocess.run(["/system/bin/sh", "-c", script], capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _focus():
    pkg = _s(bridge().currentPackage())
    act = _s(bridge().currentActivity()) or ".Main"
    return f"  mCurrentFocus=Window{{0 u0 {pkg}/{act}}}\n  mFocusedApp=ActivityRecord{{0 u0 {pkg}/{act} t1}}"


def _split(args):
    """args อาจถูก shlex.quote มา (quote=True) หรือเป็นสตริงเดียวทั้งก้อน → แยกกลับเป็นคำ"""
    if len(args) == 1 and " " in args[0]:
        try:
            return shlex.split(args[0])
        except ValueError:
            return args[0].split()
    if any(a.startswith("'") and a.endswith("'") and len(a) > 1 for a in args):
        try:
            return shlex.split(" ".join(args))
        except ValueError:
            pass
    return list(args)


# ================================================================ shell

def shell(args, timeout=30):
    a = _split([str(x) for x in args])
    if not a:
        return ""
    if a[0] in ("sh", "bash") and len(a) >= 3 and a[1] == "-c":
        return _sh_c(a[2], timeout)
    c = a[0]
    fn = _SHELL.get(c)
    if fn:
        return fn(a[1:])
    return f"ERROR: คำสั่ง {c} ไม่รองรับในโหมดแอป"


def _input(a):
    b = bridge()
    if not a:
        return ""
    if a[0] in ("touchscreen", "keyboard"):
        a = a[1:]
    op = a[0]
    if op == "tap":
        return _ok(b.tap(int(float(a[1])), int(float(a[2]))), "")
    if op == "swipe":
        x1, y1, x2, y2 = (int(float(v)) for v in a[1:5])
        ms = int(a[5]) if len(a) > 5 else 300
        if abs(x1 - x2) < 10 and abs(y1 - y2) < 10:            # swipe จุดเดียว = กดค้าง
            return _ok(b.longTap(x1, y1, ms), "")
        return _ok(b.swipe(x1, y1, x2, y2, ms), "")
    if op == "keyevent":
        codes = [x for x in a[1:] if not x.startswith("--")]
        ok = True
        for k in codes:
            ok = _key(k) and ok
        return _ok(ok, "")
    if op == "text":
        t = " ".join(a[1:]).replace("%s", " ")
        return _ok(b.typeText(t, True), "")
    return f"ERROR: input {op} ไม่รองรับ"


_KEYNAMES = {"KEYCODE_HOME": 3, "KEYCODE_BACK": 4, "KEYCODE_ENTER": 66, "KEYCODE_DEL": 67, "KEYCODE_APP_SWITCH": 187,
             "KEYCODE_VOLUME_UP": 24, "KEYCODE_VOLUME_DOWN": 25, "KEYCODE_VOLUME_MUTE": 164, "KEYCODE_POWER": 26,
             "KEYCODE_PASTE": 279, "KEYCODE_CALL": 5, "KEYCODE_ENDCALL": 6, "KEYCODE_MEDIA_PLAY_PAUSE": 85,
             "KEYCODE_MOVE_END": 123, "KEYCODE_SLEEP": 223, "KEYCODE_WAKEUP": 224}


def _key(k):
    code = _KEYNAMES.get(k.upper(), None) if not k.lstrip("-").isdigit() else int(k)
    if code is None:
        return False
    if code == 224:
        return True
    return bool(bridge().key(code))


def _uiautomator(a):
    if a[:1] != ["dump"]:
        return "ERROR: uiautomator ไม่รองรับ"
    xml = _s(bridge().dump())
    if not xml:
        return NOT_READY if not serial() else "ERROR: null root node returned by UiTestAutomationBridge."
    path = next((x for x in a[1:] if x.startswith("/")), "/sdcard/window_dump.xml")
    if path == "/dev/tty":
        return xml + "UI hierchary dumped to: /dev/tty"
    _vfs[path] = xml
    return f"UI hierchary dumped to: {path}"


def _cat(a):
    out = []
    for p in a:
        if p in _vfs:
            out.append(_vfs[p])
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out.append(f.read())
        except OSError as e:
            out.append(f"cat: {p}: {e.strerror}")
    return "".join(out)


def _rm(a):
    for p in a:
        if p.startswith("-"):
            continue
        _vfs.pop(p, None)
        try:
            os.remove(p)
        except OSError:
            pass
    return ""


def _am(a):
    b = bridge()
    if not a:
        return ""
    op, rest = a[0], a[1:]
    if op in ("start", "start-activity", "startservice", "broadcast"):
        it = {"extras": {}, "streams": []}
        i = 0
        while i < len(rest):
            f = rest[i]
            nxt = rest[i + 1] if i + 1 < len(rest) else ""
            if f in ("--user", "-f", "--activity-clear-task"):
                i += 2 if f != "--activity-clear-task" else 1
                continue
            if f in ("-W", "-S", "-R", "--activity-new-task", "--grant-read-uri-permission"):
                i += 1
                continue
            if f == "-a":
                it["action"] = nxt
            elif f == "-d":
                it["data"] = nxt
            elif f == "-t":
                it["type"] = nxt
            elif f == "-n":
                it["component"] = nxt
            elif f == "-p":
                it["package"] = nxt
            elif f == "-c":
                it["category"] = nxt
            elif f in ("--es", "--ez", "--ei", "--el"):
                k = nxt
                v = rest[i + 2] if i + 2 < len(rest) else ""
                if f in ("--el", "--ei") and v.lstrip("-").isdigit():
                    it.setdefault("extras_long" if f == "--el" else "extras_int", {})[k] = int(v)
                elif f == "--ez":
                    it.setdefault("extras_bool", {})[k] = v.lower() in ("1", "true")
                else:
                    it["extras"][k] = v
                i += 3
                continue
            elif f == "--eu":
                k, v = nxt, rest[i + 2] if i + 2 < len(rest) else ""
                if k.endswith("STREAM"):
                    it["streams"].append(v)
                else:
                    it["extras"][k] = v
                i += 3
                continue
            elif f == "--eua":
                k, v = nxt, rest[i + 2] if i + 2 < len(rest) else ""
                it["streams"] += [x for x in v.split(",") if x]
                i += 3
                continue
            elif not f.startswith("-") and "data" not in it and ("://" in f or ":" in f):
                it["data"] = f
                i += 1
                continue
            else:
                i += 1
                continue
            i += 2
        if op == "broadcast":
            it["broadcast"] = True
        return _s(b.startIntent(json.dumps(it)))
    if op == "force-stop":
        return force_stop(rest[-1]) if rest else ""
    if op in ("kill", "kill-all"):
        if op == "kill" and rest:
            b.killBackground(rest[-1])
        else:
            b.killAll()
        return ""
    return f"ERROR: am {op} ไม่รองรับในโหมดแอป"


_FORCE = re.compile(r"^(บังคับหยุด|บังคับให้หยุด|force stop|stop)$", re.I)
_OKBTN = re.compile(r"^(ตกลง|ok|บังคับหยุด|force stop|หยุด)$", re.I)


def _find_tap(rx, tries=6):
    import screen_tools
    for _ in range(tries):
        try:
            items = screen_tools._elements(screen_tools.ET.fromstring(_s(bridge().dump())))
        except Exception:  # noqa: BLE001
            items = []
        for e in items:
            label = (e["text"] or e["desc"]).strip()
            if rx.match(label) and e.get("click", True):
                bridge().tap(e["x"], e["y"])
                return True
        for e in items:                                    # ข้อความอยู่ในปุ่มลูก (ปุ่มกดไม่ได้เอง)
            if rx.match((e["text"] or e["desc"]).strip()):
                bridge().tap(e["x"], e["y"])
                return True
        time.sleep(0.6)
    return False


def force_stop(pkg):
    """แอปทั่วไปสั่งปิดแอปอื่นไม่ได้ → เปิดหน้า 'ข้อมูลแอป' แล้วกด 'บังคับหยุด' → 'ตกลง' ให้"""
    b = bridge()
    b.killBackground(pkg)
    if not b.appDetails(pkg):
        return "ERROR: เปิดหน้าข้อมูลแอปไม่ได้"
    time.sleep(1.2)
    if not _find_tap(_FORCE):
        b.key(4)
        return "ERROR: ไม่เจอปุ่มบังคับหยุด (แอปอาจปิดอยู่แล้ว)"
    time.sleep(0.8)
    _find_tap(_OKBTN, tries=3)
    time.sleep(0.5)
    b.key(4)
    return ""


def _monkey(a):
    pkg = a[a.index("-p") + 1] if "-p" in a else ""
    if not pkg:
        return "ERROR: ไม่ได้ระบุแอป"
    return "Events injected: 1" if bridge().launch(pkg) else "** No activities found to run, monkey aborted."


def _cmd(a):
    b = bridge()
    if not a:
        return ""
    svc = a[0]
    if svc == "statusbar":
        op = a[1] if len(a) > 1 else ""
        if op == "expand-notifications":
            return _ok(b.key(83), "")
        if op == "expand-settings":
            return _ok(b.quickSettings(), "")
        if op == "collapse":
            return _ok(b.collapseShade(), "")
    if svc == "package":
        if "resolve-activity" in a:
            url = a[a.index("-d") + 1] if "-d" in a else ""
            r = _s(b.resolve(url))
            return f"priority=0 preferredOrder=0\n{r}"
        if "query-activities" in a:
            return "\n".join(f"  {l.split('|')[1]}/{l.split('|')[2]}"
                             for l in _s(b.launcherApps()).splitlines() if l.count("|") == 2)
    if svc == "notification" and len(a) > 2 and a[1] == "set_dnd":
        return _ok(b.dnd(a[2] not in ("off", "0", "false")), "")
    if svc == "media_session" and "volume" in a:
        st = {"3": "music", "2": "ring", "4": "alarm", "5": "notification", "1": "system", "0": "call"}
        stream = st.get(a[a.index("--stream") + 1], "music") if "--stream" in a else "music"
        if "--set" in a:
            return _ok(b.setVolume(stream, int(a[a.index("--set") + 1])), "")
        if "--adjust" in a:
            d = a[a.index("--adjust") + 1]
            return _ok(b.key(24 if d in ("raise", "up") else 25), "")
        v = json.loads(_s(b.volumes()))
        cur = next((x for x in v if x["stream"] == stream), v[0])
        return f"volume is {cur['volume']} in range [0..{cur['max_volume']}]"
    if svc == "wifi" and len(a) > 1 and a[1] == "status":
        return "Wifi is enabled" if b.wifiEnabled() else "Wifi is disabled"
    return f"ERROR: cmd {svc} ต้องใช้สิทธิ์ ADB (โหมดแอปจะเปิดหน้าตั้งค่าแล้วกดให้แทน)"


def _settings(a):
    b = bridge()
    if len(a) >= 3 and a[0] == "get":
        return _s(b.settingsGet(a[1], a[2]))
    if len(a) >= 4 and a[0] == "put":
        ok = b.settingsPut(a[1], a[2], a[3])
        if not ok and a[1] == "system" and not b.canWriteSettings():
            return "ERROR: ยังไม่ได้ให้สิทธิ์ 'ปรับความสว่าง/ตั้งค่าเครื่อง' (แอปผู้ช่วย → 🔐 สิทธิ์)"
        return "" if ok else f"ERROR: แอปตั้งค่า {a[1]} {a[2]} ตรงๆ ไม่ได้"
    return "ERROR: settings"


def _pm(a):
    if a[:2] == ["list", "packages"]:
        return _s(bridge().listPackages("-3" in a))
    return ""


def _dumpsys(a):
    b = bridge()
    what = a[0] if a else ""
    if what == "window":
        return _focus()
    if what == "meminfo":
        m = json.loads(_s(b.memInfo()))
        return f"Total RAM: {m['total'] // 1024:,}K\n Free RAM: {m['avail'] // 1024:,}K"
    if what == "battery":
        bt = json.loads(_s(b.battery()))
        return f"  level: {bt['percentage']}\n  status: {bt['status']}"
    if what == "input":
        return f"SurfaceOrientation: {b.rotation()}"
    return ""


def _getprop(a):
    if not a:
        return f"[ro.product.manufacturer]: [{bridge().prop('ro.product.manufacturer')}]"
    return _s(bridge().prop(a[0]))


def _wm(a):
    if a[:1] == ["size"]:
        return f"Physical size: {_s(bridge().screenSize())}"
    return ""


def _screencap(a):
    path = next((x for x in a if x.startswith("/")), None)
    if not path:
        return "ERROR: ต้องระบุไฟล์"
    return _ok(bridge().screenshot(path), "")


def _content(a):
    if "query" in a and "--where" in a:
        m = re.search(r"_data='([^']+)'", a[a.index("--where") + 1])
        if m:
            uri = _s(bridge().mediaUri(m.group(1)))
            mm = re.search(r"/(\d+)$", uri)
            return f"Row: 0 _id={mm.group(1)}" if mm else "No result found."
    return "No result found."


def _echo(a):
    return " ".join(a)


def _noop(a):
    return ""


def _unsupported(name):
    return lambda a: f"ERROR: {name} ไม่รองรับในโหมดแอป"


_SHELL = {
    "input": _input, "uiautomator": _uiautomator, "cat": _cat, "rm": _rm, "am": _am, "monkey": _monkey,
    "cmd": _cmd, "settings": _settings, "pm": _pm, "dumpsys": _dumpsys, "getprop": _getprop, "wm": _wm,
    "screencap": _screencap, "content": _content, "echo": _echo, "appops": _noop, "svc": _unsupported("svc"),
    "getevent": _unsupported("getevent"), "screenrecord": _unsupported("การอัดจอ"), "pkill": _noop,
    "pulseaudio": _unsupported("pulseaudio"), "pactl": _unsupported("pactl"), "parec": _unsupported("parec"),
}


# ================================================================ termux-*

def _opt(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default


def _nid(s):
    """id แจ้งเตือนแบบข้อความ (เช่น ai_ui) → ตัวเลขคงที่"""
    s = str(s or "0")
    if s.isdigit():
        return int(s) % 10000 + 50000
    return sum((i + 1) * ord(c) for i, c in enumerate(s)) % 10000 + 60000


def termux(head, a, input_text=None):
    b = bridge()
    if head == "termux-battery-status":
        return _s(b.battery())
    if head == "termux-notification-list":
        return _s(b.notifications())
    if head == "termux-volume":
        if len(a) >= 2:
            return _ok(b.setVolume(a[0], int(a[1])), "")
        return _s(b.volumes())
    if head == "termux-brightness":
        v = a[0] if a else "128"
        ok = b.brightness(-1 if v == "auto" else int(v))
        return "" if ok else "ERROR: ยังไม่ได้ให้สิทธิ์ 'ปรับความสว่าง/ตั้งค่าเครื่อง' (แอปผู้ช่วย → 🔐 สิทธิ์)"
    if head == "termux-torch":
        return _ok(b.torch((a[0] if a else "on") == "on"), "")
    if head == "termux-vibrate":
        b.vibrate(int(_opt(a, "-d", "300")))
        return ""
    if head == "termux-tts-speak":
        text = input_text or " ".join(x for x in a if not x.startswith("-"))
        return _ok(b.speak(text, True), "")
    if head == "termux-clipboard-get":
        return _s(b.clipboardGet())
    if head == "termux-clipboard-set":
        b.clipboardSet(input_text if input_text is not None else " ".join(a))
        return ""
    if head == "termux-open-url":
        return _ok(b.openUrl(a[0] if a else ""), "")
    if head == "termux-open":
        p = a[-1] if a else ""
        return _ok(b.openUrl(p if "://" in p else _s(b.mediaUri(p))), "")
    if head == "termux-notification":
        nid = _nid(_opt(a, "--id", "0"))
        b.postNotif(nid, _opt(a, "-t", _opt(a, "--title", "ผู้ช่วย AI")), _opt(a, "-c", _opt(a, "--content", "")))
        return ""
    if head == "termux-notification-remove":
        if a:
            b.cancelNotif(_nid(a[0]))
        return ""
    if head == "termux-toast":
        b.toast(input_text or " ".join(a))
        return ""
    if head == "termux-media-player":
        op = a[0] if a else "info"
        if op == "play" and len(a) > 1:
            return _ok(b.play(a[1], False), "Now Playing")
        if op == "stop":
            b.stopPlay()
            return "Stopped playback"
        if op == "info":
            return "Status: Playing" if b.playing() else "No track currently!"
        return ""
    if head == "termux-media-scan":
        for p in a:
            if not p.startswith("-"):
                b.mediaUri(p)
        return "Scanning"
    if head == "termux-wifi-connectioninfo":
        return _s(b.wifiInfo())
    if head == "termux-location":
        return _s(b.location())
    if head == "termux-contact-list":
        return _s(b.contacts())
    if head == "termux-sms-list":
        return _s(b.smsList(int(_opt(a, "-l", "10"))))
    if head == "termux-sms-send":
        num = _opt(a, "-n", "")
        text = input_text or " ".join(x for i, x in enumerate(a) if x != "-n" and (i == 0 or a[i - 1] != "-n"))
        return "" if b.smsSend(num, text) else "ERROR: ส่ง SMS ไม่ได้ (ยังไม่ได้ให้สิทธิ์ SMS?)"
    if head == "termux-call-log":
        return _s(b.callLog(int(_opt(a, "-l", "10"))))
    if head == "termux-telephony-call":
        return _ok(b.call(a[0] if a else ""), "")
    if head == "termux-share":
        p = a[-1] if a else ""
        uri = _s(b.mediaUri(p))
        return _s(b.startIntent(json.dumps({"action": "android.intent.action.SEND", "type": "*/*", "streams": [uri]})))
    if head in ("termux-wake-lock", "termux-wake-unlock", "termux-setup-storage"):
        return ""
    return f"ERROR: {head} ไม่รองรับในโหมดแอป"


# ================================================================ ไมค์ / เสียง

def jbytes(arr):
    """byte[] จาก Java → bytes"""
    if arr is None:
        return b""
    try:
        return bytes(arr)
    except (TypeError, ValueError):
        return bytes((x & 0xFF) for x in arr)


# ================================================================ เปิด/ปิด Wi-Fi บลูทูธ ฯลฯ (แตะปุ่มในแผงควบคุมให้)

_TILES = {
    "wifi": r"(wi-?fi|wlan|ไวไฟ)",
    "bluetooth": r"(บลูทูธ|bluetooth)",
    "airplane": r"(โหมดเครื่องบิน|เครื่องบิน|airplane|aeroplane|flight mode)",
    "data": r"(ข้อมูลมือถือ|อินเทอร์เน็ตมือถือ|ข้อมูลเซลลูลาร์|เครือข่ายมือถือ|mobile data|cellular|ข้อมูลเครือข่าย)",
    "location": r"(ตำแหน่ง|location|gps)",
    "hotspot": r"(ฮอตสปอต|hotspot|จุดเชื่อมต่อ|จุดฮอตสปอต)",
    "nfc": r"^nfc",
    "rotate": r"(หมุนอัตโนมัติ|หมุนหน้าจอ|auto.?rotate|การหมุน)",
    "dnd": r"(ห้ามรบกวน|do not disturb)",
    "flashlight": r"(ไฟฉาย|flashlight|torch)",
}
_PANELS = {"wifi": "android.settings.panel.action.WIFI", "data": "android.settings.panel.action.INTERNET_CONNECTIVITY",
           "bluetooth": "android.settings.BLUETOOTH_SETTINGS", "airplane": "android.settings.AIRPLANE_MODE_SETTINGS",
           "location": "android.settings.LOCATION_SOURCE_SETTINGS", "nfc": "android.settings.NFC_SETTINGS"}


def sys_state(kind):
    """True / False / None (อ่านไม่ได้)"""
    try:
        v = _s(bridge().sysState(kind))
    except Exception:  # noqa: BLE001
        return None
    return True if v == "1" else (False if v == "0" else None)


def _screen_items():
    import screen_tools
    root = screen_tools.ET.fromstring(_s(bridge().dump()))
    w, h = screen_tools._screen_size(root)
    return screen_tools._elements(root), w, h


def _tile(items, rx):
    lab = lambda e: (e.get("desc") or "") + " " + (e.get("text") or "")  # noqa: E731
    hits = [e for e in items if e.get("click") and re.search(rx, lab(e), re.I)]
    if hits:
        return min(hits, key=lambda e: (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1]))
    labels = [e for e in items if re.search(rx, lab(e), re.I)]
    for l in labels:                                   # ป้ายชื่อใต้ไอคอน → ปุ่มที่ครอบป้ายนั้น (เล็กที่สุด)
        boxes = [e for e in items if e.get("click") and e["box"][0] <= l["x"] <= e["box"][2]
                 and e["box"][1] <= l["y"] <= e["box"][3]]
        if boxes:
            return min(boxes, key=lambda e: (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1]))
    return labels[0] if labels else None


_SETTINGS_PAGE = {"wifi": "android.settings.WIFI_SETTINGS", "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
                  "location": "android.settings.LOCATION_SOURCE_SETTINGS", "airplane": "android.settings.AIRPLANE_MODE_SETTINGS",
                  "nfc": "android.settings.NFC_SETTINGS", "hotspot": "android.settings.WIRELESS_SETTINGS"}


def _switch_in(items, rx, h):
    """สวิตช์ในหน้าตั้งค่า: แถวที่มีชื่อตรง rx → สวิตช์ในแถวนั้น / ไม่งั้นสวิตช์บนสุดของหน้า"""
    sws = [e for e in items if e.get("checkable") or re.search(r"switch|toggle|checkbox", e.get("id") or "", re.I)]
    if not sws:
        return None
    lab = lambda e: (e.get("text") or "") + " " + (e.get("desc") or "")  # noqa: E731
    for l in [e for e in items if re.search(rx, lab(e), re.I) and not e.get("checkable")]:
        row = [w for w in sws if abs(w["y"] - l["y"]) < max(60, (l["box"][3] - l["box"][1]))]
        if row:
            return row[0]
    top = [w for w in sws if w["y"] < h * 0.5]
    return min(top or sws, key=lambda e: e["y"])


def settings_switch(kind, label, on):
    """เปิดหน้าตั้งค่าของระบบนั้น → แตะสวิตช์ → ตรวจผลจริง → ย้อนกลับ (แม่นกว่าแตะในแผงควบคุมของ HarmonyOS)
    คืนข้อความ หรือ None ถ้าทำไม่ได้"""
    b = bridge()
    act = _SETTINGS_PAGE.get(kind)
    if not act or not b.openSettings(act):
        return None
    want = "เปิด" if on else "ปิด"
    done = None
    try:
        for attempt in range(3):
            time.sleep(1.3 if attempt == 0 else 1.0)
            items, w, h = _screen_items()
            sw = _switch_in(items, _TILES.get(kind, re.escape(label)), h)
            if not sw:
                continue
            if sw.get("checkable") and bool(sw.get("checked")) == bool(on):
                done = f"{label} {want}อยู่แล้ว"
                break
            b.tap(sw["x"], sw["y"])
            time.sleep(1.5)
            # บางเครื่องถามยืนยัน (เช่น โหมดเครื่องบิน/ฮอตสปอต) → กด "เปิด/ตกลง"
            items, w, h = _screen_items()
            ok_btn = [e for e in items if e.get("click") and re.fullmatch(r"\s*(เปิด|ตกลง|ยืนยัน|OK|Turn on|Allow|อนุญาต)\s*",
                                                                          (e.get("text") or e.get("desc") or ""), re.I)]
            if ok_btn and on:
                b.tap(ok_btn[0]["x"], ok_btn[0]["y"])
                time.sleep(1.2)
            st = sys_state(kind)
            if st is None or st == on:
                done = f"{want} {label} แล้ว"
                break
    except Exception as e:  # noqa: BLE001
        print(f"[toggle] {kind}: {e}", flush=True)
    finally:
        b.key(4)                                           # ออกจากหน้าตั้งค่า กลับหน้าเดิม
    return done


def rotate_auto(on):
    """หมุนจออัตโนมัติ: เขียนค่าระบบตรง (ต้องมีสิทธิ์ "แก้ไขการตั้งค่าระบบ") → ไม่ได้ค่อยแตะในแผงควบคุม"""
    b = bridge()
    want = "เปิด" if on else "ปิด"
    if b.canWriteSettings():
        b.settingsPut("system", "accelerometer_rotation", "1" if on else "0")
        time.sleep(0.3)
        if sys_state("rotate") == bool(on):
            return f"{want}หมุนจออัตโนมัติแล้ว" + ("" if on else " (ล็อกจอไว้แล้ว)")
    r = qs_toggle("rotate", "หมุนอัตโนมัติ", on)
    if not str(r).startswith("ERROR"):
        return r
    b.requestWriteSettings()
    return "ขอสิทธิ์ \"แก้ไขการตั้งค่าระบบ\" ก่อน — เปิดสวิตช์ให้ผู้ช่วยในหน้าที่เด้งขึ้นมา แล้วสั่งใหม่อีกครั้ง"


def qs_toggle(kind, label, on):
    """แอปทั่วไปสั่ง Wi-Fi/บลูทูธตรงๆ ไม่ได้ (Android 10+) → เปิดแผงควบคุมแล้วแตะปุ่มให้ แล้วตรวจผลจริง"""
    b = bridge()
    want = "เปิด" if on else "ปิด"
    if not b.a11yOn():
        return NOT_READY
    if sys_state(kind) == on:
        return f"{label} {want}อยู่แล้ว"
    if kind == "dnd" and b.dndAllowed():
        b.dnd(bool(on))
        return f"{want} {label} แล้ว"
    if kind in _SETTINGS_PAGE:                          # วิธีหลัก: หน้าตั้งค่าของระบบนั้น (แน่นอนกว่าแผงควบคุม)
        r = settings_switch(kind, label, on)
        if r:
            return r
    rx = _TILES.get(kind, re.escape(label))
    tapped = False
    try:
        b.quickSettings()
        time.sleep(1.0)
        for attempt in range(3):
            items, w, h = _screen_items()
            t = _tile(items, rx)
            if t:
                b.tap(t["x"], t["y"])
                tapped = True
                break
            if attempt == 0:                           # อาจอยู่หน้าสองของแผง → ปัดซ้าย
                b.swipe(int(w * 0.8), int(h * 0.25), int(w * 0.2), int(h * 0.25), 250)
            time.sleep(0.8)
    finally:
        time.sleep(1.2)
        b.collapseShade()
    st = sys_state(kind)
    if tapped and (st == on or st is None):
        return f"{want} {label} แล้ว" + ("" if st is not None else " (ตรวจสถานะไม่ได้ ดูที่แถบด้านบนอีกที)")
    # สำรอง: เปิดหน้าตั้งค่าแล้วแตะสวิตช์ตัวแรก
    action = _PANELS.get(kind)
    if action and b.openSettings(action):
        time.sleep(1.6)
        try:
            items, w, h = _screen_items()
            sw = [e for e in items if e.get("click") and re.search(r"(switch|toggle|checkbox)", e.get("id") or "", re.I)]
            if sw:
                b.tap(sw[0]["x"], sw[0]["y"])
                time.sleep(1.2)
                if sys_state(kind) in (on, None):
                    b.key(4)
                    return f"{want} {label} แล้ว (ผ่านหน้าตั้งค่า)"
        except Exception:  # noqa: BLE001
            pass
        return f"แตะปุ่ม{label}ให้ไม่สำเร็จ เลยเปิดหน้าตั้งค่า {label} ไว้ให้แล้ว แตะสวิตช์ได้เลย"
    return f"ERROR: {want} {label} ไม่สำเร็จ (ไม่เจอปุ่ม {label} ในแผงควบคุม)"
