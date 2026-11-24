"""ล็อกข้ามโปรแกรม: ให้เรียก Termux:API ทีละคำสั่ง
(บอท Telegram + ผู้ช่วยเสียง + ตัวอ่านแจ้งเตือน เรียกพร้อมกันบ่อยๆ จะทำให้ Termux:API ขึ้นหน้าจอแดง error)

รอคิวได้ไม่เกิน WAIT วินาที — ถ้ามีคำสั่งค้างถือล็อกไว้ จะทำต่อเลย (ดีกว่าบอทเงียบไปทั้งตัว)"""
import contextlib
import fcntl
import os
import threading
import time

import config

_tlock = threading.Lock()
WAIT = 20


@contextlib.contextmanager
def termux_api():
    path = os.path.join(config.DATA_DIR, "termux_api.lock")
    got_t = _tlock.acquire(timeout=WAIT)
    f = None
    locked = False
    try:
        f = open(path, "a")
        t0 = time.time()
        while time.time() - t0 < WAIT:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                time.sleep(0.2)
        if not locked:
            print(f"⚠️ รอคิว Termux:API เกิน {WAIT} วิ → ทำต่อเลย", flush=True)
        yield
    finally:
        if f is not None:
            if locked:
                try:
                    fcntl.flock(f, fcntl.LOCK_UN)
                except OSError:
                    pass
            f.close()
        if got_t:
            _tlock.release()
