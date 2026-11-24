"""เสียง Microsoft Edge Neural (ฟรี เหมือนคน) แบบไม่ต้องใช้ไลบรารี edge-tts/aiohttp
(แอป APK ติดตั้ง aiohttp ไม่ได้ → เขียน websocket ด้วยไลบรารีมาตรฐานของ Python)
"""
import base64
import hashlib
import os
import socket
import ssl
import struct
import time
import uuid
from xml.sax.saxutils import escape

HOST = "speech.platform.bing.com"
TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
GEC_VERSION = os.environ.get("EDGE_GEC_VERSION", "1-143.0.3650.75")   # รุ่น Edge ที่เซิร์ฟเวอร์ยอมรับ (เปลี่ยนเป็นระยะ)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0")
_MUID = uuid.uuid4().hex.upper()
_skew = {"s": 0.0}            # เวลาเครื่องคลาดจากเซิร์ฟเวอร์ (แก้จากหัว Date ตอนโดนปฏิเสธ)


GEC_VERSION_V2 = os.environ.get("EDGE_GEC_VERSION_V2", "2-143.0.3650.75")
_drm_mod = {"m": None, "tried": False}


def _load_drm():
    """โหลดเฉพาะ edge_tts/drm.py (edge-tts 7.3+) โดยไม่ต้องมี aiohttp
    ตั้งแต่ ต.ค. 2026 Microsoft ไม่รับรหัสยืนยันแบบเก่า (v1) แล้ว ตอบ 403 ทุกครั้ง
    รหัสแบบใหม่ (v2) ซับซ้อนมาก จึงใช้โค้ดของ edge-tts ตัวจริงแทนการเขียนเอง"""
    if _drm_mod["tried"]:
        return _drm_mod["m"]
    _drm_mod["tried"] = True
    import importlib
    import importlib.util
    import sys
    import types
    stub_aio = made_pkg = False
    try:
        if "edge_tts.drm" in sys.modules:
            _drm_mod["m"] = sys.modules["edge_tts.drm"]
            return _drm_mod["m"]
        spec = importlib.util.find_spec("edge_tts")
        if spec is None:
            print("⚠️ ไม่พบ edge-tts ในแอป (ตอน build ไม่ได้ติดตั้ง) → ใช้รหัสยืนยันแบบเก่า Microsoft อาจตอบ 403",
                  flush=True)
            return None
        if "aiohttp" not in sys.modules:
            try:
                import aiohttp  # noqa: F401
            except ImportError:
                class _Stub(types.ModuleType):
                    def __getattr__(self, name):
                        return type(name, (Exception,), {})
                sys.modules["aiohttp"] = _Stub("aiohttp")
                stub_aio = True
        if "edge_tts" not in sys.modules:
            sys.modules["edge_tts"] = importlib.util.module_from_spec(spec)   # ไม่รัน __init__ (ที่ต้องใช้ aiohttp)
            made_pkg = True
        m = importlib.import_module("edge_tts.drm")
        if hasattr(m, "generate_sec_ms_gec_v2"):
            _drm_mod["m"] = m
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ โหลดรหัสยืนยันเสียง Microsoft แบบใหม่ไม่ได้: {str(e)[:120]}", flush=True)
    finally:
        if stub_aio:
            sys.modules.pop("aiohttp", None)
        if made_pkg:
            for k in [k for k in sys.modules if k == "edge_tts" or k.startswith("edge_tts.")]:
                sys.modules.pop(k, None)
    return _drm_mod["m"]


def sec_ms_gec_v1(now=None):
    ticks = (now if now is not None else time.time() + _skew["s"]) + 11644473600
    ticks -= ticks % 300
    ticks *= 10 ** 7
    return hashlib.sha256(f"{ticks:.0f}{TOKEN}".encode("ascii")).hexdigest().upper()


def sec_ms_gec(now=None):
    """คืน (รหัส, เวอร์ชัน) — ใช้แบบใหม่ v2 ถ้ามี edge-tts 7.3+ ไม่งั้นแบบเก่า v1"""
    ts = now if now is not None else time.time() + _skew["s"]
    m = _load_drm()
    if m is not None:
        try:
            return m.generate_sec_ms_gec_v2(ts), GEC_VERSION_V2
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ สร้างรหัสยืนยันแบบใหม่ไม่ได้: {str(e)[:120]}", flush=True)
    return sec_ms_gec_v1(ts), GEC_VERSION


def token_kind():
    return "v2 (ใหม่)" if _load_drm() is not None else "v1 (เก่า — Microsoft อาจปฏิเสธ 403)"


def _date():
    return time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())


def full_voice(v):
    """th-TH-NiwatNeural → Microsoft Server Speech Text to Speech Voice (th-TH, NiwatNeural)"""
    if v.startswith("Microsoft"):
        return v
    parts = v.split("-")
    return f"Microsoft Server Speech Text to Speech Voice ({parts[0]}-{parts[1]}, {'-'.join(parts[2:])})"


def ssml(text, voice, rate="+0%", pitch="+0Hz"):
    return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
            f"<voice name='{full_voice(voice)}'><prosody pitch='{pitch}' rate='{rate}' volume='+0%'>"
            f"{escape(text)}</prosody></voice></speak>")


# ---------------------------------------------------------------- websocket ขั้นต่ำ

class WS:
    def __init__(self, host, path, headers, timeout=15):
        raw = socket.create_connection((host, 443), timeout=timeout)
        self.s = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
               f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"] + [f"{k}: {v}" for k, v in headers.items()]
        self.s.sendall(("\r\n".join(req) + "\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = self.s.recv(4096)
            if not c:
                break
            resp += c
        head, _, self.buf = resp.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101" not in status:
            self.close()
            raise ConnectionError(f"edge tts: {status} | {head.decode(errors='replace')[:300]}")

    def _read(self, n):
        while len(self.buf) < n:
            c = self.s.recv(65536)
            if not c:
                raise ConnectionError("edge tts: ปิดการเชื่อมต่อกลางคัน")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, data, opcode=1):
        if isinstance(data, str):
            data = data.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        """→ (opcode, payload) ต่อเฟรมย่อยให้ครบแล้ว"""
        msg, op0 = b"", None
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 9:                         # ping → pong
                self.send(data, 10)
                continue
            if op == 8:
                return 8, data
            if op in (1, 2):
                op0 = op
            msg += data
            if fin:
                return op0 or op, msg

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# ---------------------------------------------------------------- สังเคราะห์เสียง

def synth(text, path, voice="th-TH-NiwatNeural", rate="+0%", pitch="+0Hz", timeout=20):
    try:
        return _synth(text, path, voice, rate, pitch, timeout)
    except ConnectionError as e:
        if "403" in str(e) and abs(_skew["s"]) > 30:        # นาฬิกาคลาด → แก้แล้วลองใหม่ 1 ครั้ง
            return _synth(text, path, voice, rate, pitch, timeout)
        raise


def _synth(text, path, voice, rate, pitch, timeout):
    conn = uuid.uuid4().hex
    gec, ver = sec_ms_gec()
    q = (f"/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={TOKEN}"
         f"&Sec-MS-GEC={gec}&Sec-MS-GEC-Version={ver}&ConnectionId={conn}")
    headers = {"Pragma": "no-cache", "Cache-Control": "no-cache",
               "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
               "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": f"muid={_MUID};"}
    try:
        ws = WS(HOST, q, headers, timeout)
    except ConnectionError as e:
        _fix_clock(str(e))
        raise ConnectionError(f"{str(e).splitlines()[0][:120]} (รหัสยืนยัน {ver[:2]}…)") from e
    try:
        ws.send(f"X-Timestamp:{_date()}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false",'
                '"wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n')
        ws.send(f"X-RequestId:{uuid.uuid4().hex}\r\nContent-Type:application/ssml+xml\r\n"
                f"X-Timestamp:{_date()}Z\r\nPath:ssml\r\n\r\n" + ssml(text, voice, rate, pitch))
        audio = bytearray()
        t0 = time.time()
        while time.time() - t0 < timeout:
            op, data = ws.recv()
            if op == 2 and len(data) >= 2:
                hl = struct.unpack(">H", data[:2])[0]
                if b"Path:audio" in data[2:2 + hl]:
                    audio += data[2 + hl:]
            elif op == 1 and b"Path:turn.end" in data:
                break
            elif op == 8:
                break
    finally:
        ws.close()
    if len(audio) < 500:
        raise ConnectionError("edge tts: ไม่ได้เสียงกลับมา")
    with open(path, "wb") as f:
        f.write(audio)
    return path


def _fix_clock(err):
    """เซิร์ฟเวอร์ปฏิเสธเพราะนาฬิกาเครื่องคลาด → ใช้เวลาจากหัว Date ของเซิร์ฟเวอร์"""
    import email.utils
    for line in err.split("\r\n"):
        if line.lower().startswith("date:"):
            try:
                srv = email.utils.parsedate_to_datetime(line[5:].strip()).timestamp()
                _skew["s"] = srv - time.time()
            except (TypeError, ValueError):
                pass
