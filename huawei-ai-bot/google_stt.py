"""ถอดเสียงคำสั่งด้วยระบบรู้จำเสียงของเครื่อง (ตัวเดียวกับปุ่มไมค์ในคีย์บอร์ด Gboard)

ฟรี แม่นกับภาษาไทย แต่ฟังได้ทีละประโยค → ใช้ฟังคำสั่ง "หลังเรียกผู้ช่วยแล้ว" และปุ่มไมค์ในแอป
ส่วนการฟังคำปลุก + ตรวจเสียงเจ้าของ ยังใช้ไมค์ของแอปเหมือนเดิม
ใช้ไม่ได้ (ไม่มีบริการของ Google / ไม่มีเน็ต / ภาษาไม่รองรับ) → คืน None ให้ใช้ตัวถอดเสียงเดิม (Groq/NanoGPT)
"""
import json
import time

import config

_S = {"avail": None, "checked": 0.0, "off_until": 0.0, "empty_bg": 0}
_LONG_OFF = ("unavailable", "language_unsupported", "language_unavailable", "permission")


def _log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def _bridge():
    import android_shim
    return android_shim.bridge()


def available():
    """มีระบบรู้จำเสียงของเครื่องไหม (จำผล 10 นาที)"""
    if not (config.ANDROID_APP and config.GOOGLE_STT):
        return False
    if time.time() < _S["off_until"]:
        return False
    if _S["avail"] is None or time.time() - _S["checked"] > 600:
        try:
            _S["avail"] = bool(_bridge().googleSttAvailable())
        except Exception:  # noqa: BLE001
            _S["avail"] = False
        _S["checked"] = time.time()
        _log("🎙️ ระบบรู้จำเสียงของเครื่อง:", "ใช้ได้ → ถอดคำสั่งด้วย Google" if _S["avail"]
             else "ไม่มี → ใช้ตัวถอดเสียงเดิม")
    return _S["avail"]


def _app_visible():
    try:
        return bool(_bridge().appVisible())
    except Exception:  # noqa: BLE001
        return True


def listen(timeout=8.0, user_started=False):
    """ฟังหนึ่งประโยค → ข้อความ ("" = ไม่มีใครพูด) / None = ใช้ไม่ได้ ให้ใช้ตัวเดิม
    user_started = ผู้ใช้กดปุ่มไมค์/แผงผู้ช่วยเอง (ไม่ใช่ฟังเบื้องหลัง) → ไม่ปิด Google เพราะ "ไม่ได้ยิน" """
    if not available():
        return None
    t0 = time.time()
    try:
        r = json.loads(str(_bridge().googleListen(int(timeout * 1000), config.GOOGLE_STT_LANG)))
    except Exception as e:  # noqa: BLE001
        _log("🎙️ Google ถอดเสียงไม่สำเร็จ:", e)
        _S["off_until"] = time.time() + 300
        return None
    err = r.get("err") or ""
    if not r.get("ok"):
        # ชนกัน/ยุ่งชั่วคราว (busy, client) = พักแค่ 30 วิ · ไม่มีบริการ/ภาษาไม่รองรับ = 60 นาที · อื่นๆ 2 นาที
        secs = 3600 if err in _LONG_OFF else (30 if err in ("busy", "client", "timeout") else 120)
        _S["off_until"] = time.time() + secs
        _log(f"🎙️ Google ใช้ไม่ได้ ({err}) → ใช้ตัวถอดเสียงเดิม {secs // 60 or secs} {'นาที' if secs >= 60 else 'วิ'}")
        return None
    text = (r.get("text") or "").strip()
    # บางเครื่องไม่ให้ระบบรู้จำเสียงใช้ไมค์ตอนแอปอยู่เบื้องหลัง (ได้แต่ความเงียบ) → ใช้ตัวเดิมตอนอยู่เบื้องหลัง
    if not text and not user_started and not _app_visible():
        _S["empty_bg"] += 1
        if _S["empty_bg"] >= 2:
            _S["off_until"] = time.time() + 1800
            _log("🎙️ Google ไม่ได้ยินอะไรตอนแอปอยู่เบื้องหลัง 2 ครั้งติด → ใช้ตัวเดิม 30 นาที")
    elif text:
        _S["empty_bg"] = 0
    _log(f"🎤 (Google {time.time() - t0:.1f}s)", text or "(ไม่ได้ยิน)")
    return text
