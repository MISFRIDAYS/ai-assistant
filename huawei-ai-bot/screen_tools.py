"""ควบคุมหน้าจอแท็บเล็ต/มือถือผ่าน ADB ไร้สาย (Wireless debugging) ที่เชื่อมเข้าตัวเอง

ทำให้ AI: อ่านหน้าจอ, ดูภาพหน้าจอ, แตะ, ปัด, พิมพ์ข้อความ (รวมภาษาไทย), กดปุ่ม, รับ/วางสาย
ตั้งค่าครั้งแรก: ดู README หัวข้อ "ควบคุมหน้าจอ (ADB)"
"""
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET

import config

_state = {"serial": None, "checked": 0.0}

KEYS = {
    "back": 4, "home": 3, "recent": 187, "enter": 66, "delete": 67, "tab": 61, "search": 84,
    "call": 5, "endcall": 6, "wakeup": 224, "sleep": 223, "power": 26, "volume_up": 24,
    "volume_down": 25, "mute": 164, "play_pause": 85, "next": 87, "previous": 88, "paste": 279,
    "menu": 82, "escape": 111,
}

_MOCK_XML = """<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation="1">
<node text="" class="android.widget.FrameLayout" bounds="[0,0][2560,1600]" clickable="false" content-desc="" resource-id="">
<node text="แม่" class="android.widget.TextView" bounds="[100,200][400,260]" clickable="true" content-desc="" resource-id="jp.naver.line.android:id/name"/>
<node text="" class="android.widget.EditText" bounds="[100,1450][2200,1550]" clickable="true" content-desc="" resource-id="jp.naver.line.android:id/chat_input"/>
<node text="" class="android.widget.ImageView" bounds="[2250,1450][2400,1550]" clickable="true" content-desc="ส่ง" resource-id="jp.naver.line.android:id/send"/>
</node></hierarchy>"""


def _run(cmd, timeout=30, input_text=None):
    import phone_tools
    return phone_tools.run(cmd, timeout=timeout, input_text=input_text)


# ---------------------------------------------------------------- การเชื่อมต่อ ADB

def _devices():
    out = _run(["adb", "devices"])
    ok, stale = [], []
    for l in out.splitlines()[1:]:
        parts = l.split()
        if len(parts) < 2:
            continue
        if parts[1] == "device":
            ok.append(parts[0])
        elif parts[1] in ("offline", "unauthorized"):
            stale.append(parts[0])
    for s_ in stale:                       # การเชื่อมค้าง → ตัดแล้วต่อใหม่
        _run(["adb", "disconnect", s_], timeout=8)
    return ok


def _alive(serial):
    """เช็คว่า serial นี้ยังสั่งงานได้จริง (ไม่ใช่แค่ค้างอยู่ในรายการ)"""
    out = _run(["adb", "-s", serial, "shell", "echo", "ok"], timeout=6)
    return "ok" in out


def adb_serial(force=False):
    """คืน serial ของอุปกรณ์ที่เชื่อม ADB อยู่ (เชื่อมใหม่อัตโนมัติถ้าหลุด) หรือ None"""
    if config.MOCK_PHONE:
        return "mock"
    if config.ANDROID_APP:                       # แอป APK: "เชื่อมแล้ว" = เปิด Accessibility แล้ว
        import android_shim
        return android_shim.serial()
    if not config.ENABLE_ADB or shutil.which("adb") is None:
        return None
    # ใช้ค่าที่จำไว้ได้ไม่เกิน 20 วิ และต้องยัง alive จริง
    if _state["serial"] and not force and time.time() - _state["checked"] < 20:
        return _state["serial"]
    if _state["serial"] and _alive(_state["serial"]):
        _state["checked"] = time.time()
        return _state["serial"]
    _state["checked"] = time.time()
    _state["serial"] = None
    devs = _devices()
    if not devs:
        # ลองหาพอร์ตอัตโนมัติผ่าน mDNS แล้วลองที่อยู่ที่บันทึกไว้
        candidates = []
        for line in _run(["adb", "mdns", "services"], timeout=10).splitlines():
            if "_adb-tls-connect" in line:
                candidates.append(line.split()[-1])
        if config.ADB_ADDRESS:
            candidates.append(config.ADB_ADDRESS)
        candidates.append("127.0.0.1:5555")          # ค่าจากสคริปต์ เปิดADBให้แท็บเล็ต.bat
        saved = _saved_address()
        if saved:
            candidates.append(saved)
        for addr in candidates:
            _run(["adb", "connect", addr], timeout=10)
            devs = _devices()
            if devs:
                _save_address(addr)
                break
    _state["serial"] = devs[0] if devs else None
    if _state["serial"] and not _alive(_state["serial"]):
        _run(["adb", "disconnect", _state["serial"]], timeout=8)
        _run(["adb", "connect", _state["serial"]], timeout=10)
        if not _alive(_state["serial"]):
            _state["serial"] = None
    return _state["serial"]


def adb_keepalive():
    """รันเบื้องหลัง: คอยเชื่อม ADB ให้ติดตลอด (ทุก 25 วิ) เผื่อหลุดตอนรีสตาร์ท/เปลี่ยน Wi-Fi"""
    import threading
    def _loop():
        while True:
            try:
                adb_serial(force=True)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(25)
    if config.ENABLE_ADB and not config.MOCK_PHONE and not config.ANDROID_APP and not _state.get("keepalive"):
        _state["keepalive"] = True
        threading.Thread(target=_loop, daemon=True).start()


def _addr_file():
    return os.path.join(config.DATA_DIR, "adb_address.txt")


def _saved_address():
    try:
        with open(_addr_file()) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _save_address(addr):
    with open(_addr_file(), "w") as f:
        f.write(addr)


NOT_CONNECTED = ("ERROR: ยังไม่ได้เชื่อม ADB — ให้ผู้ใช้เปิด ตั้งค่า > ระบบและการอัปเดต > ตัวเลือกนักพัฒนา > "
                 "การดีบักแบบไร้สาย (Wireless debugging) แล้วบอกพอร์ตที่แสดง (IP address & Port) "
                 "จากนั้นเรียก adb_connect ด้วยพอร์ตนั้น")
if config.ANDROID_APP:
    NOT_CONNECTED = ("ERROR: ยังไม่ได้เปิดสิทธิ์ 'คุมหน้าจอ' ของแอปผู้ช่วย — ให้ผู้ใช้เปิดแอป → 🔐 สิทธิ์ → "
                     "คุมหน้าจอ (Accessibility) → 'ผู้ช่วย AI — ควบคุมหน้าจอ' → เปิด")


def adb_shell(args, timeout=30, quote=False):
    """quote=True: ครอบแต่ละ argument กันเชลล์ฝั่งเครื่องตัดคำ (ข้อความมีช่องว่าง, ลิงก์มี & ?)"""
    serial = adb_serial()
    if not serial:
        return NOT_CONNECTED
    if config.MOCK_PHONE:
        if args[:2] == ["uiautomator", "dump"]:
            return _MOCK_XML
        return f"[MOCK] adb shell {' '.join(args)}"
    if quote:
        import shlex
        args = [shlex.quote(str(x)) for x in args]
    return _run(["adb", "-s", serial, "shell"] + list(args), timeout=timeout)


def adb_connect(a, ctx):
    port = str(a["port"]).strip()
    if a.get("pairing_code") and a.get("pairing_port"):
        res = _run(["adb", "pair", f"127.0.0.1:{a['pairing_port']}", str(a["pairing_code"])], timeout=20)
        if "Successfully" not in res and not config.MOCK_PHONE:
            return f"ERROR: จับคู่ไม่สำเร็จ: {res}"
    addr = port if ":" in port else f"127.0.0.1:{port}"
    res = _run(["adb", "connect", addr], timeout=15)
    serial = adb_serial(force=True)
    if serial:
        _save_address(addr)
        return f"เชื่อม ADB สำเร็จ ({serial})"
    return f"ERROR: เชื่อมไม่สำเร็จ: {res} — ถ้ายังไม่เคยจับคู่ ต้องทำ adb pair ก่อน (ดู README)"


# ---------------------------------------------------------------- อ่านหน้าจอ

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


_u2 = {"d": None, "t": 0.0}


def u2():
    """ตัวอ่าน/คุมจอแบบเร็ว (uiautomator2: อ่านจอ ~0.3 วิ แทน 2-5 วิ) — ไม่มีก็ใช้วิธีเดิม
    ติดตั้ง: bash setup_fast.sh"""
    if config.MOCK_PHONE or not config.FAST_SCREEN or config.ANDROID_APP:
        return None
    if _u2["d"] is not None:
        return _u2["d"]
    if time.time() - _u2["t"] < 120:               # เพิ่งลองแล้วไม่ได้ → รอ 2 นาทีค่อยลองใหม่
        return None
    _u2["t"] = time.time()
    try:
        import uiautomator2
    except ImportError:
        return None
    serial = adb_serial()
    if not serial:
        return None
    try:
        d = uiautomator2.connect(serial)
        d.window_size()
        _u2["d"] = d
        print("⚡ อ่าน/คุมจอแบบเร็ว (uiautomator2) พร้อมแล้ว", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ uiautomator2 ใช้ไม่ได้ ใช้วิธีเดิม ({str(e)[:80]})", flush=True)
        return None
    return _u2["d"]


def _u2_fail(e):
    print(f"⚠️ uiautomator2 หลุด → ใช้วิธีเดิมชั่วคราว ({str(e)[:60]})", flush=True)
    _u2["d"] = None
    _u2["t"] = time.time()


def _dump():
    d = u2()
    if d is not None:
        try:
            xml = d.dump_hierarchy(compressed=False)
            start = xml.find("<hierarchy")
            if start >= 0:
                return ET.fromstring(xml[start:] if not xml.lstrip().startswith("<?xml") else xml)
        except Exception as e:  # noqa: BLE001
            _u2_fail(e)
    return _dump_slow()


def _dump_slow():
    """อ่านโครงสร้างหน้าจอ — จำกัดเวลา: หน้าที่มีวิดีโอ/แอนิเมชันเล่นอยู่ (เช่น Reels) uiautomator จะรอไม่จบ"""
    out = ""
    for i in range(2):
        out = adb_shell(["uiautomator", "dump", "/dev/tty"], timeout=12)
        if out.startswith("ERROR: ยังไม่ได้เชื่อม"):
            raise RuntimeError(out)
        if "<?xml" not in out and "idle" not in out.lower() and "timeout" not in out.lower() \
                and "นานเกิน" not in out:
            # บางเครื่องเขียนลง /dev/tty ไม่ได้ ให้เขียนลงไฟล์แทน
            adb_shell(["uiautomator", "dump", "/sdcard/window_dump.xml"], timeout=12)
            out = adb_shell(["cat", "/sdcard/window_dump.xml"], timeout=8)
        start = out.find("<?xml")
        end = out.rfind("</hierarchy>")
        if start >= 0 and end > start:
            return ET.fromstring(out[start:end + len("</hierarchy>")])
        if i == 0:
            time.sleep(0.8)
    if "idle" in out.lower() or "นานเกิน" in out:
        raise RuntimeError("อ่านหน้าจอไม่ได้เพราะมีวิดีโอ/ภาพเคลื่อนไหวเล่นอยู่ — ใช้ screenshot ดูภาพแทน "
                           "หรือกดหยุดวิดีโอก่อน")
    raise RuntimeError(f"อ่านหน้าจอไม่ได้ (จอปิด/ล็อกอยู่?): {out[:150]}")


def _elements(root):
    items = []
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        rid = (n.get("resource-id") or "").split("/")[-1]
        clickable = n.get("clickable") == "true"
        editable = "EditText" in (n.get("class") or "")
        m = _BOUNDS.match(n.get("bounds") or "")
        if not m or not (text or desc or clickable or editable):
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        items.append({"text": text, "desc": desc, "id": rid, "x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
                      "click": clickable, "edit": editable, "box": (x1, y1, x2, y2),
                      "checkable": n.get("checkable") == "true", "checked": n.get("checked") == "true",
                      "password": n.get("password") == "true"})
    return items


def _screen_size(root):
    first = next(root.iter("node"), None)
    m = _BOUNDS.match(first.get("bounds") if first is not None else "")
    return (int(m.group(3)), int(m.group(4))) if m else (1600, 2560)


_last = {"items": []}

# ปุ่มที่กดแล้วมีผลจริงจัง → ขออนุญาตผู้ใช้ก่อน
SENSITIVE = ("โทร", "call", "ส่ง", "send", "โพสต์", "post", "แชร์", "share", "เผยแพร่", "publish",
             "ชำระ", "จ่าย", "pay", "ซื้อ", "buy", "สั่งซื้อ", "order", "ลบ", "delete", "remove",
             "โอน", "transfer", "ยืนยัน", "confirm", "วิดีโอคอล", "video call", "อัปโหลด", "upload")


def _label_at(x, y):
    """หาชื่อปุ่มที่พิกัดนี้ จากการอ่านหน้าจอครั้งล่าสุด"""
    best = None
    for e in _last["items"]:
        x1, y1, x2, y2 = e["box"]
        if x1 <= x <= x2 and y1 <= y <= y2:
            area = (x2 - x1) * (y2 - y1)
            if (e["text"] or e["desc"] or e["id"]) and (best is None or area < best[0]):
                best = (area, e)
    if not best:
        return ""
    e = best[1]
    return " / ".join(v for v in (e["text"], e["desc"], e["id"]) if v)


def _check_sensitive(label, ctx, action="แตะปุ่ม"):
    import permissions
    if permissions.need_confirm(ctx, permissions.category(label)):
        app = _current_app()
        if not ctx.confirm(f"{action} \"{label}\" ในแอป {app}"):
            return False
    return True


# ป๊อปอัปขอสิทธิ์ของระบบ (กล้อง/ไมค์/รูป/ตำแหน่ง/แจ้งเตือน ฯลฯ) — กดให้เลยระหว่างที่ผู้ช่วยกำลังทำงาน
_PERM_PKGS = ("permissioncontroller", "packageinstaller", "com.huawei.systemmanager", "com.hihonor.systemmanager",
              "com.huawei.permissioncontroller")
_ALLOW_BTN = re.compile(r"^\s*(อนุญาต|อนุญาตทุกครั้ง|อนุญาตเสมอ|อนุญาตตลอด|อนุญาตเฉพาะ.*|ขณะใช้(งาน)?แอป(นี้)?|"
                        r"เฉพาะครั้งนี้|ครั้งนี้เท่านั้น|allow|allow all|allow all the time|allow only while using the app|"
                        r"while using the app|only this time|ok)\s*$", re.I)
_NEVER_ALLOW = re.compile(r"ติดตั้ง|install|ผู้ดูแลอุปกรณ์|device admin|การช่วยเหลือพิเศษ|accessibility|"
                          r"ชำระ|payment|รหัสผ่าน|password|ลบ|delete", re.I)


def allow_permission_popup(items=None):
    """ถ้ามีป๊อปอัปขอสิทธิ์ของระบบอยู่ → แตะ "อนุญาต" ให้ (ไม่แตะเรื่องติดตั้งแอป/สิทธิ์ช่วยเหลือพิเศษ/การเงิน)
    คืนชื่อปุ่มที่กด หรือ None"""
    if not config.AUTO_ALLOW_PERMS or config.MOCK_PHONE:
        return None
    try:
        import phone_tools
        fg = (phone_tools._fg() or "").lower()
        if not any(k in fg for k in _PERM_PKGS):
            return None
        items = items if items is not None else _elements(_dump())
        page = " ".join((e["text"] or e["desc"] or "") for e in items)
        if _NEVER_ALLOW.search(page):
            return None
        btns = [e for e in items if e["click"] and _ALLOW_BTN.match(e["text"] or e["desc"] or "")
                and not re.search(r"ไม่|deny|don.?t", e["text"] or e["desc"] or "", re.I)]
        if not btns:
            return None
        pref = sorted(btns, key=lambda e: 0 if re.search(r"ขณะใช้|while using|อนุญาต$|^allow$",
                                                         e["text"] or e["desc"] or "", re.I) else 1)
        b = pref[0]
        adb_shell(["input", "tap", str(b["x"]), str(b["y"])])
        label = b["text"] or b["desc"]
        print(time.strftime("[%H:%M:%S]"), f"✅ กดอนุญาตสิทธิ์ให้แอปอัตโนมัติ: {label!r} ({fg})", flush=True)
        time.sleep(0.7)
        return label
    except Exception as e:  # noqa: BLE001
        print(f"[perm] {e}", flush=True)
        return None


def _current_app():
    out = adb_shell(["dumpsys", "window"], timeout=15)
    m = re.search(r"mCurrentFocus=.*?\s(\S+?)/", out)
    return m.group(1) if m else "ไม่ทราบ"


def read_screen(a, ctx):
    allowed = allow_permission_popup()
    root = _dump()
    w, h = _screen_size(root)
    app = adb_shell(["dumpsys", "window"], timeout=15)
    focus = re.search(r"mCurrentFocus=.*?\s(\S+/\S+)\}", app)
    lines = [f"แอปที่เปิดอยู่: {focus.group(1) if focus else 'ไม่ทราบ'} | จอ {w}x{h}"]
    if allowed:
        lines.append(f"(มีป๊อปอัปขอสิทธิ์ — กด \"{allowed}\" ให้แล้ว)")
    _last["items"] = _elements(root)
    pkg = focus.group(1).split("/")[0] if focus else ""
    for i, e in enumerate(_last["items"]):
        label = e["text"] or e["desc"] or ""
        if not label and e["click"] and pkg:
            try:
                import app_tasks
                learned = app_tasks.label_of(pkg, e, w, h)      # ไอคอนไม่มีชื่อ แต่เคยเรียนรู้ไว้
                if learned:
                    label = f"≈{learned} (ไอคอน)"
            except Exception:  # noqa: BLE001
                pass
        tags = []
        if e["click"]:
            tags.append("แตะได้")
        if e["edit"]:
            tags.append("ช่องพิมพ์")
        if e["desc"] and e["text"]:
            tags.append(f"desc={e['desc']}")
        if e["id"]:
            tags.append(f"id={e['id']}")
        lines.append(f"[{i}] \"{label[:80]}\" @({e['x']},{e['y']}) {' '.join(tags)}")
    out = "\n".join(lines)
    return out if len(out) < 7000 else out[:7000] + "\n...(ตัดบางส่วน)"


def screenshot(a, ctx):
    if not adb_serial():
        return NOT_CONNECTED
    path = os.path.join(config.DATA_DIR, "screen.png")
    if config.MOCK_PHONE:
        return {"text": "[MOCK] ถ่ายภาพหน้าจอแล้ว", "image_path": None}
    _run(["bash", "-c", f"adb -s {adb_serial()} exec-out screencap -p > '{path}'"], timeout=30)
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        return "ERROR: ถ่ายภาพหน้าจอไม่สำเร็จ"
    path = _shrink(path)
    return {"text": "ภาพหน้าจอปัจจุบัน", "image_path": path, "send_to_user": bool(a.get("send_to_user"))}


def _shrink(path):
    """ย่อภาพให้เล็กลง (ถ้ามี Pillow) เพื่อส่งให้ AI ได้เร็ว"""
    try:
        from PIL import Image
    except ImportError:
        return path
    img = Image.open(path).convert("RGB")
    img.thumbnail((1280, 1280))
    out = path.rsplit(".", 1)[0] + ".jpg"
    img.save(out, "JPEG", quality=70)
    return out


# ---------------------------------------------------------------- สั่งงานหน้าจอ

def tap(a, ctx):
    x, y = int(a["x"]), int(a["y"])
    label = _label_at(x, y)
    if label and not _check_sensitive(label, ctx):
        return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้ — ยกเลิกแล้ว"
    if a.get("long"):
        res = adb_shell(["input", "swipe", str(x), str(y), str(x), str(y), "800"])
    else:
        res = adb_shell(["input", "tap", str(x), str(y)])
    time.sleep(0.5)
    ok = allow_permission_popup()
    return (res or "OK") + (f" (กด \"{ok}\" ในป๊อปอัปขอสิทธิ์ให้แล้ว)" if ok else "")


def _scroll_find(q, rounds=2):
    """เลื่อนลงทีละหน้าเพื่อหาปุ่ม/ข้อความ (ไม่เจอ → เลื่อนกลับที่เดิม)"""
    if config.MOCK_PHONE:
        return None
    moved = 0
    try:
        for _ in range(rounds):
            swipe({"direction": "up"}, None)
            moved += 1
            time.sleep(0.6)
            items = _elements(_dump())
            hits = [e for e in items if q in (e["text"] or "").lower() or q in (e["desc"] or "").lower()]
            if hits:
                return hits[0]
    except Exception:  # noqa: BLE001
        return None
    for _ in range(moved):
        swipe({"direction": "down"}, None)
    return None


def tap_text(a, ctx):
    q = a["text"].strip().lower()
    items = _elements(_dump())
    exact = [e for e in items if q in (e["text"].lower(), e["desc"].lower())]
    hits = exact or [e for e in items if q in e["text"].lower() or q in e["desc"].lower()]
    if not hits:
        try:
            import app_tasks
            import phone_tools
            e = app_tasks.find_learned(phone_tools._fg() or "", q, items)   # ไอคอนที่เรียนรู้ชื่อไว้
            if e:
                adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
                time.sleep(0.5)
                return f"แตะไอคอน '{a['text']}' (ที่เรียนรู้ไว้) ที่ ({e['x']},{e['y']}) แล้ว"
        except Exception:  # noqa: BLE001
            pass
        hit = _scroll_find(q)                              # แก้ปัญหาเอง: เลื่อนหาในหน้า
        if hit:
            if hit.get("text") and not _check_sensitive(hit["text"], ctx):
                return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้ — ยกเลิกแล้ว"
            adb_shell(["input", "tap", str(hit["x"]), str(hit["y"])])
            time.sleep(0.5)
            return f"เลื่อนหาเจอแล้ว แตะ '{hit['text'] or hit['desc']}' ที่ ({hit['x']},{hit['y']})"
        v = vision_find(a["text"])                         # มองภาพหา (ปุ่มที่เป็นรูป/ชื่อไม่ตรง)
        if v:
            if v.get("text") and not _check_sensitive(v["text"], ctx):
                return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้ — ยกเลิกแล้ว"
            adb_shell(["input", "tap", str(v["x"]), str(v["y"])])
            time.sleep(0.6)
            return f"มองภาพหาเจอ แตะ '{v['text'] or a['text']}' ที่ ({v['x']},{v['y']}) แล้ว"
        return (f"ERROR: ไม่พบ '{a['text']}' (ลองเลื่อนหา+มองภาพแล้ว) — read_screen ดูชื่อปุ่มจริง "
                "หรือ press_key back แล้วเริ่มจากหน้าก่อน")
    idx = min(int(a.get("index", 0)), len(hits) - 1)
    e = hits[idx]
    _last["items"] = items
    if not _check_sensitive(e["text"] or e["desc"], ctx):
        return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้ — ยกเลิกแล้ว"
    adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(0.5)
    more = f" (เจอทั้งหมด {len(hits)} ตำแหน่ง)" if len(hits) > 1 else ""
    return f"แตะ \"{e['text'] or e['desc']}\" ที่ ({e['x']},{e['y']}) แล้ว{more}"


_THAI_MARK = re.compile(r"[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]")


def _clusters(text):
    """แบ่งข้อความเป็นตัวอักษรที่เห็นจริง (สระบน/ล่าง/วรรณยุกต์ติดกับพยัญชนะ)"""
    out = []
    for ch in text:
        if out and _THAI_MARK.match(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _human_type(b, text):
    """พิมพ์ทีละนิดแบบคนพิมพ์ (ช่องแชทเห็นว่ากำลังพิมพ์…) — รวมทั้งหมดไม่เกิน ~4 วินาที · ปิดได้ HUMAN_TYPING=0"""
    import random
    if os.environ.get("HUMAN_TYPING", "1") == "0" or len(text) > 400 or len(text) < 3:
        return bool(b.typeText(text, False))
    cl = _clusters(text)
    step = max(1, len(cl) // 35)
    i = min(step, len(cl))
    if not b.typeText("".join(cl[:i]), False):
        return False
    try:
        via_ime = b.lastViaIme() is True
    except Exception:  # noqa: BLE001
        via_ime = False
    if via_ime:                                   # พิมพ์ผ่านคีย์บอร์ดผู้ช่วย → ต่อท้ายส่วนที่เหลือทีเดียว (ไม่พิมพ์ซ้ำ)
        rest = "".join(cl[i:])
        return not rest or bool(b.imeType(rest, False))
    while i < len(cl):
        n = step + random.choice((0, 0, 1)) if step > 1 else random.choice((1, 1, 2))
        i = min(len(cl), i + n)
        prev = cl[i - 1] if i else ""
        time.sleep(random.uniform(0.05, 0.13) + (0.25 if prev in (" ", ",", ".") and random.random() < 0.3 else 0))
        if not b.typeText("".join(cl[:i]), False):     # ใส่ข้อความที่พิมพ์มาแล้วทั้งก้อน (ไม่พึ่งค่าค้างในช่อง)
            return bool(b.typeText(text, False))
    return True


def _longpress_paste(b):
    """แอปที่วาดช่องพิมพ์เอง (WPS, Docs ฯลฯ) ใส่ข้อความตรงๆ ไม่ได้ → กดค้างกลางหน้าเอกสาร แล้วกด "วาง" """
    try:
        items = _elements(_dump())
        w, h = _screen_size(_dump())
        x, y = w // 2, int(h * 0.4)
        b.longTap(x, y, 700)
        time.sleep(1.0)
        items = _elements(_dump())
        hit = [e for e in items if re.fullmatch(r"\s*(วาง|Paste|แปะ)\s*", e["text"] or e["desc"] or "", re.I)]
        if hit:
            b.tap(hit[0]["x"], hit[0]["y"])
            time.sleep(0.5)
            return "OK"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: พิมพ์ไม่ได้ ({e})"
    return "ERROR: แอปนี้ไม่ให้พิมพ์ผ่านระบบ — ข้อความอยู่ในคลิปบอร์ดแล้ว กดค้างตรงที่จะพิมพ์แล้วเลือก \"วาง\" ได้เลย"


def type_text(a, ctx):
    text = a["text"]
    import permissions
    if a.get("press_enter") and permissions.need_confirm(ctx, "message") and \
            not ctx.confirm(f"พิมพ์แล้วกด Enter (ส่ง) ในแอป {_current_app()}:\n{text}"):
        return "ผู้ใช้ไม่อนุญาต — ยกเลิกแล้ว"
    if config.ANDROID_APP:                         # แอป: ใส่ข้อความตรงเข้าช่อง (ไทย/อีโมจิได้ทันที)
        import android_shim
        b = android_shim.bridge()
        if _human_type(b, text):
            res = "OK"
        else:
            b.clipboardSet(text)
            time.sleep(0.2)
            res = "OK" if b.paste() else _longpress_paste(b)
    elif text.isascii() and len(text) < 200:
        safe = text.replace("\\", "\\\\").replace(" ", "%s")
        for ch in "\"'`$&|;<>()*?!#~":
            safe = safe.replace(ch, "\\" + ch)
        res = adb_shell(["input", "text", safe])
    else:  # ภาษาไทย/อีโมจิ: ใส่ตรงเข้าช่องที่เลือกอยู่ (เร็ว) / ไม่ได้ → คลิปบอร์ดแล้ววาง
        res = ""
        d = u2()
        done = False
        if d is not None:
            try:
                el = d(focused=True)
                if el.exists:
                    el.set_text(text)                 # ใส่ทั้งข้อความทีเดียว (แทนข้อความเก่าที่ค้าง)
                    done, res = True, "OK"
            except Exception as e:  # noqa: BLE001
                _u2_fail(e)
        if not done:
            _run(["termux-clipboard-set"], input_text=text)
            time.sleep(0.3)
            res = adb_shell(["input", "keyevent", str(KEYS["paste"])])
    if res.startswith("ERROR"):
        return f"ERROR: พิมพ์ไม่สำเร็จ ({res[:80]})"
    if a.get("press_enter"):                       # ช่องค้นหา → Enter
        adb_shell(["input", "keyevent", str(KEYS["enter"])])
        time.sleep(0.5)
        return f"พิมพ์แล้วกด Enter: {text[:100]}"
    time.sleep(0.5)
    if not a.get("send", True):
        return f"พิมพ์ไว้แล้ว (ยังไม่ส่ง): {text[:100]}"
    if getattr(ctx, "hold", False):
        return f"พิมพ์ไว้แล้ว ยังไม่กดส่งตามที่ผู้ใช้ขอให้รอ: {text[:100]} — บอกผู้ใช้ว่าสั่ง 'ส่งเลย' ได้"
    return f"พิมพ์แล้ว: {text[:100]} → " + _press_send(ctx)


_SEND_WORDS = ("ส่ง", "send", "โพสต์", "post", "ตอบกลับ", "reply", "เผยแพร่", "share now", "แชร์เลย")


def _press_send(ctx):
    """หาปุ่มส่งบนจอแล้วแตะ (ใช้ id ที่มีคำว่า send ก่อน → ข้อความ/คำอธิบายที่ตรงตัว)"""
    import permissions
    if permissions.need_confirm(ctx, "message") and not ctx.confirm(f"กดส่งข้อความในแอป {_current_app()}"):
        return "ผู้ใช้ไม่อนุญาตให้ส่ง — พิมพ์ค้างไว้"
    items = _elements(_dump()) if not config.MOCK_PHONE else _elements(ET.fromstring(_MOCK_XML))
    cands = [e for e in items if not e["edit"] and "send" in e["id"].lower()]
    cands += [e for e in items if not e["edit"] and
              (e["text"].strip().lower() in _SEND_WORDS or e["desc"].strip().lower() in _SEND_WORDS)]
    if not cands:
        return "หาปุ่มส่งไม่เจอ — ใช้ read_screen หาไอคอนส่ง (ลูกศร/เครื่องบินกระดาษ) แล้ว tap ตามพิกัด"
    e = cands[0]
    adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(0.6)
    return f"กดส่งแล้ว ✅ (ปุ่ม {e['text'] or e['desc'] or e['id']})"


def press_key(a, ctx):
    key = a["key"]
    code = KEYS.get(key, key)
    return adb_shell(["input", "keyevent", str(code)]) or "OK"


def swipe(a, ctx):
    root = _dump() if not config.MOCK_PHONE else ET.fromstring(_MOCK_XML)
    w, h = _screen_size(root)
    cx, cy = w // 2, h // 2
    dx, dy = int(w * 0.3), int(h * 0.3)
    d = a["direction"]
    # direction = ทิศที่นิ้วลาก (up = เลื่อนดูเนื้อหาด้านล่าง)
    pts = {"up": (cx, cy + dy, cx, cy - dy), "down": (cx, cy - dy, cx, cy + dy),
           "left": (cx + dx, cy, cx - dx, cy), "right": (cx - dx, cy, cx + dx, cy)}[d]
    res = adb_shell(["input", "swipe"] + [str(p) for p in pts] + ["300"])
    time.sleep(0.5)
    return res or "OK"


_ANSWER = re.compile(r"(รับสาย|ตอบรับ|^รับ$|\banswer\b|\baccept\b|answer_button|accept_call)", re.I)
_DECLINE = re.compile(r"(วางสาย|ปฏิเสธ|ตัดสาย|จบการโทร|\bdecline\b|\breject\b|\bend call\b|\bhang ?up\b|"
                      r"end_call|endcall|decline_button)", re.I)


def _tap_call_button(want, avoid):
    """หาปุ่มรับ/วางสายบนจอ (สายโทรศัพท์ + LINE/Messenger/WhatsApp/IG) แล้วแตะ"""
    try:
        items = _elements(_dump())
    except RuntimeError:
        return None
    for e in items:
        parts = [e["text"].strip(), e["desc"].strip(), e["id"]]
        if any(p and avoid.search(p) for p in parts):
            continue
        if any(p and want.search(p) for p in parts):
            adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
            return e["text"] or e["desc"] or e["id"]
    return None


def answer_call(a, ctx):
    """รับสาย: สายโทรศัพท์ → ปุ่ม CALL / สายจากแอป → หาปุ่ม 'รับสาย' บนจอหรือในแจ้งเตือน"""
    adb_shell(["input", "keyevent", str(KEYS["wakeup"])])
    time.sleep(0.4)
    hit = _tap_call_button(_ANSWER, _DECLINE)
    if hit:
        return f"รับสายแล้ว (แตะ {hit})"
    adb_shell(["cmd", "statusbar", "expand-notifications"])       # สายจากแอปมักมีปุ่มรับในแจ้งเตือน
    time.sleep(0.8)
    hit = _tap_call_button(_ANSWER, _DECLINE)
    if hit:
        return f"รับสายแล้ว (แตะ {hit} ในแจ้งเตือน)"
    adb_shell(["cmd", "statusbar", "collapse"])
    adb_shell(["input", "keyevent", str(KEYS["call"])])            # สายโทรศัพท์ปกติ
    return "ส่งคำสั่งรับสายแล้ว (ถ้าเป็นสายจากแอปแล้วยังไม่รับ แปลว่าหาปุ่มรับสายไม่เจอ)"


def end_call(a, ctx):
    hit = _tap_call_button(_DECLINE, _ANSWER)
    if hit:
        return f"วางสายแล้ว (แตะ {hit})"
    return adb_shell(["input", "keyevent", str(KEYS["endcall"])]) or "OK"




def wake_screen(a, ctx):
    adb_shell(["input", "keyevent", str(KEYS["wakeup"])])
    adb_shell(["wm", "dismiss-keyguard"])
    return "ปลุกหน้าจอแล้ว (ถ้าตั้งรหัสล็อกไว้ ผู้ใช้ต้องปลดล็อกเอง)"


def vision_find(target):
    """หาสิ่งบนจอจากคำบรรยายด้วยการ 'มองภาพ' (Gemini) — ใช้เมื่ออ่านจอแบบข้อความหาไม่เจอ
    เช่น ไอคอนไม่มีชื่อ, ชื่อสะกดเพี้ยน, แอปที่วาดจอเอง/เกม → คืน {"x","y","text"} หรือ None"""
    if not config.GEMINI_API_KEY or not adb_serial() or config.MOCK_PHONE:
        return None
    raw = os.path.join(config.DATA_DIR, "vision.png")
    _run(["bash", "-c", f"adb -s {adb_serial()} exec-out screencap -p > '{raw}'"], timeout=30)
    if not os.path.exists(raw) or os.path.getsize(raw) < 1000:
        return None
    try:
        from PIL import Image
        img = Image.open(raw)
        w, h = img.size
        img = img.convert("RGB")
        img.thumbnail((1280, 1280))
        small = raw.replace(".png", ".jpg")
        img.save(small, "JPEG", quality=75)
        data, mime = open(small, "rb").read(), "image/jpeg"
    except Exception:  # noqa: BLE001
        root = _dump()
        w, h = _screen_size(root)
        data, mime = open(raw, "rb").read(), "image/png"
    import gemini_client
    t0 = time.time()
    try:
        hit = gemini_client.locate(data, target, mime=mime)
    except Exception as e:  # noqa: BLE001
        print(f"[vision] error: {e}", flush=True)
        return None
    print(f"[vision] '{target[:50]}' → {hit} ({time.time() - t0:.1f}s)", flush=True)
    if not hit:
        return None
    return {"x": int(hit[0] * w), "y": int(hit[1] * h), "text": hit[2], "desc": "", "id": "", "edit": False,
            "click": True, "box": (0, 0, 0, 0)}


def tap_visual(a, ctx):
    e = vision_find(a["target"])
    if not e:
        return (f"ERROR: มองไม่เห็น '{a['target']}' บนจอ" if config.GEMINI_API_KEY
                else "ERROR: ต้องมี Gemini API key ถึงจะหาด้วยการมองภาพได้ (bash set_key.sh)")
    if e["text"] and not _check_sensitive(e["text"], ctx):
        return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้ — ยกเลิกแล้ว"
    adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(0.6)
    return f"แตะ '{e['text'] or a['target']}' ที่ ({e['x']},{e['y']}) แล้ว (หาด้วยการมองภาพ)"


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "adb_connect": (adb_connect, "เชื่อม ADB ไร้สายเข้าเครื่องตัวเอง ใส่พอร์ตจากหน้า Wireless debugging "
                    "(ถ้าจับคู่ครั้งแรกให้ใส่ pairing_port และ pairing_code ด้วย)",
                    _obj({"port": {"type": "string"}, "pairing_port": {"type": "string"},
                          "pairing_code": {"type": "string"}}, ["port"]), False),
    "read_screen": (read_screen, "อ่านสิ่งที่อยู่บนหน้าจอตอนนี้: ข้อความ ปุ่ม ช่องพิมพ์ พร้อมพิกัด (x,y) สำหรับ tap",
                    _obj(), False),
    "screenshot": (screenshot, "ถ่ายภาพหน้าจอให้ AI ดู (send_to_user=true ถ้าผู้ใช้ขอดูภาพด้วย)",
                   _obj({"send_to_user": {"type": "boolean"}}), False),
    "tap": (tap, "แตะหน้าจอที่พิกัด x,y (long=true คือกดค้าง)",
            _obj({"x": {"type": "integer"}, "y": {"type": "integer"}, "long": {"type": "boolean"}}, ["x", "y"]), False),
    "tap_text": (tap_text, "แตะปุ่ม/ข้อความบนหน้าจอที่มีคำนี้ (index เลือกตัวที่เท่าไหร่ถ้าเจอหลายตัว)",
                 _obj({"text": {"type": "string"}, "index": {"type": "integer"}}, ["text"]), False),
    "type_text": (type_text, "พิมพ์ข้อความลงช่องที่เลือกอยู่ (รองรับภาษาไทย) แล้วกดปุ่มส่งให้เองอัตโนมัติ "
                             "(send=false = แค่พิมพ์ไว้ไม่ส่ง, press_enter=true = ช่องค้นหา กด Enter แทน)",
                  _obj({"text": {"type": "string"}, "send": {"type": "boolean"},
                        "press_enter": {"type": "boolean"}}, ["text"]), False),
    "tap_visual": (tap_visual, "แตะสิ่งบนจอจากคำบรรยาย โดยให้ AI มองภาพหน้าจอ — ใช้เมื่อ tap_text หาไม่เจอ "
                               "(ไอคอนไม่มีชื่อ, ชื่อสะกดไม่ตรง, เกม) เช่น target='ไอคอนรูปหัวใจใต้โพสต์แรก'",
                   _obj({"target": {"type": "string"}}, ["target"]), False),
    "press_key": (press_key, "กดปุ่มระบบ",
                  _obj({"key": {"type": "string", "enum": list(KEYS)}}, ["key"]), False),
    "swipe": (swipe, "ปัดหน้าจอ: up=เลื่อนลงดูเนื้อหาถัดไป, down=เลื่อนขึ้น/ดึงแถบแจ้งเตือน, left/right",
              _obj({"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}}, ["direction"]), False),
    "answer_call": (answer_call, "รับสายโทรศัพท์ที่กำลังเรียกเข้า", _obj(), False),
    "end_call": (end_call, "วางสาย / ตัดสาย", _obj(), False),
    "wake_screen": (wake_screen, "ปลุกหน้าจอให้สว่าง", _obj(), False),
}
