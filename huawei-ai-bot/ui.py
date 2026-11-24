"""UI แบบ Google Assistant: การ์ดเด้งบนหน้าจอตอนพูด แสดงสถานะแบบเรียลไทม์
(ฟัง → ได้ยินว่า... → กำลังคิด → ตอบ...) ผ่านการแจ้งเตือนที่อัปเดตสด

สำคัญ: Termux:API รับคำสั่งพร้อมกันเยอะๆ ไม่ได้ (จะขึ้นหน้าจอแดง "Termux:API Error / Connection refused")
→ ทุกการอัปเดตส่งผ่าน worker ตัวเดียว ทำทีละคำสั่ง และอัปเดตไม่ถี่กว่า UI_MIN_INTERVAL
   ถ้ามีหลายสถานะมารัวๆ จะแสดงแค่สถานะล่าสุด
"""
import subprocess
import threading
import time

import config

_NID = "ai_ui"
_cv = threading.Condition()
_pending = {"op": None}          # สถานะล่าสุดที่รอแสดง (ของเก่าที่ยังไม่ได้แสดงจะถูกทับ)
_state = {"last": "", "hide_at": 0.0, "started": False, "shown": False}


def _enabled():
    return config.UI_ENABLED and not config.MOCK_PHONE


def _call(args):
    """เรียก Termux:API แบบรอจนเสร็จ (ห้ามตัดกลางคัน ไม่งั้น Termux:API จะ error)"""
    if config.ANDROID_APP:                     # แอป APK: แสดงเป็นแจ้งเตือนของแอปเอง
        try:
            import android_shim
            android_shim.run(args)
        except Exception:  # noqa: BLE001
            pass
        return
    import termux_lock
    try:
        with termux_lock.termux_api():
            subprocess.run(args, capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def _submit(op):
    if config.ANDROID_APP:                     # แอป APK: ป๊อปอัปลอยของแอป (เร็ว ไม่ต้องผ่านคิวแจ้งเตือน)
        try:
            import android_shim
            b = android_shim.bridge()
            if op[0] == "remove":
                b.popupHide()
            else:
                _, title, content, ongoing = op
                b.popupShow(str(title), str(content)[:400], bool(ongoing))
        except Exception:  # noqa: BLE001
            pass
        return
    if not _enabled():
        return
    start()
    with _cv:
        _pending["op"] = op
        _cv.notify()


def _worker():
    last_sent = 0.0
    while True:
        with _cv:
            while _pending["op"] is None:
                _cv.wait(timeout=1.0)
                if _state["hide_at"] and time.time() >= _state["hide_at"] and _pending["op"] is None:
                    _state["hide_at"] = 0.0
                    _pending["op"] = ("remove",)
            op, _pending["op"] = _pending["op"], None
        wait = config.UI_MIN_INTERVAL - (time.time() - last_sent)
        if wait > 0:
            time.sleep(wait)
            with _cv:                       # ระหว่างรอ มีสถานะใหม่กว่ามา → ใช้อันใหม่
                if _pending["op"] is not None:
                    op, _pending["op"] = _pending["op"], None
        if op[0] == "remove":
            if _state["shown"]:
                _call(["termux-notification-remove", _NID])
                _state["shown"] = False
        else:
            _, title, content, ongoing = op
            args = ["termux-notification", "--id", _NID, "-t", title, "-c", content[:400],
                    "--priority", "high", "--alert-once"]
            if ongoing:
                args.append("--ongoing")
            args += ["--button1", "หยุด", "--button1-action", f"bash {config.BASE_DIR}/stop_all.sh"]
            _call(args)
            _state["shown"] = True
        last_sent = time.time()


def start():
    if _enabled() and not _state["started"]:
        _state["started"] = True
        threading.Thread(target=_worker, daemon=True).start()


def _show(title, content, ongoing=True):
    _state["hide_at"] = 0.0
    _submit(("show", title, content, ongoing))


def _app(state, text=""):
    """แอป APK: แผงผู้ช่วยด้านล่างจอแบบ Google Assistant"""
    try:
        import android_shim
        android_shim.bridge().assistant(state, str(text or "")[:600])
    except Exception:  # noqa: BLE001
        pass
    return True


def listening():
    if config.ANDROID_APP:
        return _app("listen")
    _show("🎙️ กำลังฟัง…", "พูดได้เลยครับ")


def heard(text):
    if config.ANDROID_APP:
        return _app("heard", text)
    _show("💬 คุณพูดว่า", text or "…")


def thinking(text=""):
    if config.ANDROID_APP:
        return _app("think", text)
    _show("🤔 กำลังคิด…", text or "สักครู่นะครับ")


def speaking(text):
    if config.ANDROID_APP:
        _state["last"] = text
        return _app("speak", text)
    if text == _state["last"]:
        return
    _state["last"] = text
    _show("🤖 ผู้ช่วย", text)


def done(text=""):
    """แสดงคำตอบค้างไว้สักครู่ แล้วหายเอง"""
    if config.ANDROID_APP:
        return _app("done", text or _state["last"])
    _show("🤖 ผู้ช่วย", text or _state["last"], ongoing=False)
    _state["hide_at"] = time.time() + config.UI_LINGER


def idle():
    """ซ่อนการ์ด (รอคำปลุก)"""
    if config.ANDROID_APP:
        return _app("idle")
    _state["hide_at"] = 0.0
    _submit(("remove",))
