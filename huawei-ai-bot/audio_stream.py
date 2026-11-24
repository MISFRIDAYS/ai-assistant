"""ฟังไมค์แบบต่อเนื่อง + ตรวจจับว่าเริ่มพูด/พูดจบ (VAD) แบบเรียลไทม์

วิธีหลัก: PulseAudio (module-sles-source) → parec ส่งเสียงดิบ 16kHz ออกมาตลอด
           → ตัดเป็นประโยคทันทีที่ผู้ใช้หยุดพูด ~0.7 วินาที (ไม่ต้องรอครบเวลา)
วิธีสำรอง: ถ้า PulseAudio ใช้ไมค์ไม่ได้ จะอัดทีละท่อนสั้นด้วย termux-microphone-record
           แล้วตรวจความดังด้วย ffmpeg (ช้ากว่า แต่ยังไม่ต้องกดปุ่ม)
"""
import array
import glob
import collections
import math
import os
import shutil
import subprocess
import threading
import time
import wave

import config

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2

# ตั้งเป็น set() เมื่อลำโพงกำลังพูด → ไมค์จะไม่ฟัง (กันได้ยินเสียงตัวเอง)
SPEAKING = threading.Event()
_last_spoke = [0.0]


def mark_speaking(on):
    if on:
        SPEAKING.set()
    else:
        SPEAKING.clear()
        _last_spoke[0] = time.time()


def muted():
    return SPEAKING.is_set() or time.time() - _last_spoke[0] < 0.35


def rms(frame):
    a = array.array("h", frame)
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


def speech_stats(pcm, noise=0.0):
    """(วินาทีที่ดังเกินเสียงพื้นหลังชัดๆ, ความดังสูงสุด) — ใช้คัดเสียงเคาะ/เสียงลม/เสียงสั้นๆ ทิ้งก่อนส่งถอดเสียง
    ห้องมีพัดลม/แอร์ (noise สูง) → เกณฑ์ไม่เกิน 30% ของเสียงที่ดังที่สุด (ไม่งั้นนับได้แค่พยางค์ที่ดังสุด
    คำปลุกสั้นๆ อย่าง "โอเคผู้ช่วย" จะเหลือ 0.3 วิ แล้วโดนทิ้ง)"""
    levels = [rms(pcm[i:i + FRAME_BYTES]) for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES)]
    peak = max(levels, default=0.0)
    floor = max(config.VAD_MIN_RMS * 1.6, min(noise * 3.5, peak * 0.3))
    voiced = sum(1 for lv in levels if lv > floor)
    return voiced * FRAME_MS / 1000, peak


def is_speechy(pcm, noise=0.0, min_sec=None):
    sec, peak = speech_stats(pcm, noise)
    need = config.VOICE_MIN_SPEECH if min_sec is None else min_sec
    loud = max(config.VAD_MIN_RMS * 2.5, noise * 3.0)      # ห้องเสียงดัง: อย่าเข้มเกินจนไม่รับเสียงเจ้าของ
    if peak >= max(config.VAD_MIN_RMS * 8, noise * 6) and sec >= min(0.25, need):
        return True                                         # สั้นแต่ดังชัด (คำปลุก) → ถอดเสียงดู
    return sec >= need and peak >= loud


def write_wav(pcm, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return path


# ---------------------------------------------------------------- PulseAudio

def _sh(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


def _mic_sources():
    code, out = _sh(["pactl", "list", "short", "sources"])
    names = [l.split("\t")[1] for l in out.splitlines() if "\t" in l]
    # ".monitor" = เสียงที่ออกลำโพง ไม่ใช่ไมค์
    return [n for n in names if not n.endswith(".monitor")]


def _pa_ok():
    return _sh(["pactl", "info"], timeout=5)[0] == 0


def _ensure_pulse_daemon():
    """เปิด PulseAudio ให้ติด (ถ้าค้างจากรอบก่อน → ปิดแล้วเปิดใหม่ / ลบไฟล์ค้าง)"""
    if _pa_ok():
        return True
    _sh(["pulseaudio", "-k"])
    time.sleep(0.5)
    for attempt in range(2):
        code, out = _sh(["pulseaudio", "--start", "--exit-idle-time=-1"])
        for _ in range(15):
            if _pa_ok():
                return True
            time.sleep(0.3)
        # ไฟล์ค้างจากรอบก่อนที่ถูกปิดไม่เรียบร้อย
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        for pat in (os.path.join(prefix, "var/run/pulse*"), os.path.join(prefix, "tmp/pulse-*"),
                    os.path.expanduser("~/.config/pulse/*-runtime")):
            for p in glob.glob(pat):
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else _rm(p)
        _why.append(f"PulseAudio: เปิดไม่ติดรอบ {attempt + 1} ({out.strip()[:120]})")
    return _pa_ok()


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def start_pulseaudio():
    """เปิด PulseAudio พร้อมไมค์ (module-sles-source) คืนชื่อ source ของไมค์ หรือ None"""
    if not shutil.which("pulseaudio") or not shutil.which("parec"):
        _why.append("PulseAudio: ยังไม่ได้ติดตั้ง (pkg install pulseaudio)")
        return None
    if not _ensure_pulse_daemon():
        return None
    srcs = _mic_sources()
    if not srcs:
        code, out = _sh(["pactl", "load-module", "module-sles-source"])
        if code != 0:
            _why.append(f"PulseAudio: โหลดไมค์ไม่ได้ ({out.strip()[:150]})")
        time.sleep(0.5)
        srcs = _mic_sources()
    return srcs[0] if srcs else None


_why = []


class MicStream:
    """อ่านเสียงดิบจากไมค์ตลอดเวลา (ใน thread แยก) แล้วตัดเป็นประโยค — แบบ PulseAudio"""

    GRACE = 0.35   # หลังลำโพงพูดจบ รออีกกี่วินาทีค่อยเริ่มฟัง (กันเสียงสะท้อน)

    def __init__(self):
        _sh(["pkill", "-f", "parec -d"])           # ปิดตัวฟังเก่าที่ค้างอยู่ (ไม่งั้นตัวใหม่ได้แต่ความเงียบ)
        self.source = start_pulseaudio()
        if not self.source:
            raise RuntimeError("PulseAudio ใช้ไมค์ไม่ได้")
        self.proc = subprocess.Popen(
            ["parec", "-d", self.source, "--raw", "--format=s16le", f"--rate={RATE}",
             "--channels=1", "--latency-msec=60"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self._start_reader()

    def _start_reader(self):
        import queue
        self.noise = 200.0
        self.q = queue.Queue(maxsize=2000)
        self.dead = None
        self.last_sound = time.time()
        self._rt = threading.Thread(target=self._reader, daemon=True)
        self._rt.start()

    def reader_dead(self):
        """ตัวอ่านเสียงตายแล้ว (ไมค์หลุด) → ต้องเปิดใหม่ ไม่งั้นได้แต่ความเงียบไปตลอด"""
        rt = getattr(self, "_rt", None)
        return bool(getattr(self, "dead", None)) or (rt is not None and not rt.is_alive())

    def _read_exact(self):
        buf = b""
        while len(buf) < FRAME_BYTES:
            chunk = self.proc.stdout.read(FRAME_BYTES - len(buf))
            if not chunk:
                raise RuntimeError("ไมค์หยุดส่งเสียง")
            buf += chunk
        return buf

    def _reader(self):
        """อ่านตลอดเวลา ไม่ให้เสียงค้างท่อ แต่ละท่อนติดป้ายว่า "ลำโพงกำลังพูดอยู่ไหม" """
        try:
            while True:
                frame = self._read_exact()
                if any(frame):
                    self.last_sound = time.time()
                speaking = SPEAKING.is_set() or time.time() - _last_spoke[0] < self.GRACE
                if self.q.full():
                    self.q.get_nowait()
                self.q.put((frame, speaking))
        except Exception as e:  # noqa: BLE001
            self.dead = str(e)
            self.q.put(None)

    def silent_for(self):
        """ไมค์ส่งแต่ศูนย์ล้วนมากี่วินาทีแล้ว (Android ปิดไมค์ของแอปเบื้องหลัง = ได้ศูนย์ล้วน)"""
        return time.time() - getattr(self, "last_sound", time.time())

    def close(self):
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        while not self.q.empty():
            self.q.get_nowait()

    def _get(self, timeout):
        import queue
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            raise RuntimeError(f"ไมค์หยุดส่งเสียง: {self.dead}")
        return item

    def _frame(self, timeout=1.0):
        """ท่อนเสียงถัดไปที่ลำโพงไม่ได้พูดอยู่ (ช่วงลำโพงพูด = ข้าม)"""
        t0 = time.time()
        while True:
            item = self._get(timeout)
            if item is None or time.time() - t0 > timeout:
                return b"\x00\x00" * FRAME_SAMPLES
            frame, speaking = item
            if not speaking:
                return frame

    def watch_interrupt(self, active, factor=None, paused=None):
        """ระหว่างที่ AI กำลังคิด/พูด คอยฟังว่าผู้ใช้พูดแทรกไหม
        ช่วงลำโพงพูด: เทียบกับระดับเสียงลำโพงที่ไมค์ได้ยิน (ค่าสูงช่วง 90% ใน 2 วินาทีล่าสุด)
        ต้องดังกว่า factor เท่า ต่อเนื่อง BARGE_IN_MS จึงนับว่าพูดแทรก
        คืนเสียงช่วงที่พูดแทรก (list ของท่อน) หรือ None เมื่อ active() เป็น False"""
        factor = factor or config.BARGE_IN_FACTOR
        echo_levels = collections.deque(maxlen=70)    # ระดับเสียงลำโพงล่าสุด ~2 วินาที
        run = collections.deque(maxlen=20)
        pending = []                                  # ระดับเสียงช่วงที่กำลังดังผิดปกติ
        loud = 0
        need = max(3, int(config.BARGE_IN_MS / FRAME_MS))
        self.last_barge = None
        while active():
            if paused and paused():
                self._get(0.1)                        # อ่านทิ้ง (ไม่ให้เสียงช่วงหยุดฟังค้างคิว แล้วถูกนับทีหลัง)
                loud, pending = 0, []
                run.clear()
                continue
            item = self._get(0.2)
            if item is None:
                continue
            frame, speaking = item
            level = rms(frame)
            run.append(frame)
            if speaking:
                if len(echo_levels) < 30:             # ยังเก็บข้อมูลเสียงลำโพงไม่พอ → ยังไม่ตัดสิน
                    echo_levels.append(level)
                    loud, pending = 0, []
                    continue
                ref = sorted(echo_levels)[int(len(echo_levels) * 0.9)]
                thresh = max(ref * factor, config.VAD_MIN_RMS * 3)
            else:
                thresh = max(self.noise * 4, config.VAD_MIN_RMS * 2)
            if level > thresh:
                loud += 1
                pending.append(level)
            else:
                if speaking:                          # เก็บเฉพาะช่วงปกติเป็นค่าอ้างอิงเสียงลำโพง
                    echo_levels.extend(pending)
                    echo_levels.append(level)
                loud, pending = 0, []
            if loud >= need:
                self.last_barge = (int(level), int(thresh))
                return list(run)
        return None

    def check_alive(self, seconds=2.5):
        """ตรวจว่าได้เสียงจริง (ไม่ใช่ศูนย์ล้วน ซึ่งแปลว่าไมค์ถูกบล็อก)"""
        peak, got = 0.0, 0
        t0 = time.time()
        while time.time() - t0 < seconds:
            f = self._frame(timeout=seconds)
            if any(f):
                got += 1
            peak = max(peak, rms(f))
        return got > 5 and peak > 1.0


    NOISE_CAP = None        # เพดานเสียงพื้นหลัง (แอป APK ตั้งไว้) — ไม่ให้เกณฑ์สูงจนเสียงเจ้าของไม่ผ่าน

    def _track_noise(self, level):
        """ประมาณเสียงพื้นหลังจากช่วงที่เบาที่สุด (15%) ใน ~4 วินาทีล่าสุด
        → ห้องเงียบ/มีพัดลม/แอร์ ปรับเองได้ ไม่ค้างว่า "กำลังพูด" ตลอดเวลา
        มีเพดาน (แอป) และไม่เกิน 35% ของเสียงพูดล่าสุด (เดิมเกณฑ์ไต่สูงเกินเสียงพูดจนเรียกไม่ติด)"""
        if level <= 0:                              # ท่อนเงียบสนิท (ไมค์ถูกจองโดยคนอื่น) ไม่ใช่เสียงห้อง
            return
        if not hasattr(self, "_levels"):
            self._levels = collections.deque(maxlen=130)
            self._n = 0
        self._levels.append(level)
        self._n += 1
        if self._n % 10 == 0 and len(self._levels) >= 30:
            n = max(5.0, sorted(self._levels)[int(len(self._levels) * 0.15)])
            cap = self.NOISE_CAP
            sp = getattr(self, "speech_peak", 0.0)
            if sp > 0:
                cap = min(cap, sp * 0.35) if cap else sp * 0.35
            if cap:
                n = min(n, max(cap, 5.0))
            self.noise = n

    def reset_noise(self, value=None):
        self._levels = collections.deque(maxlen=130)
        self._n = 0
        if value is not None:
            self.noise = value

    def utterance(self, wait_timeout=None, max_seconds=15.0, end_silence=0.7, min_speech=0.25,
                  initial=None):
        """รอจนผู้ใช้พูดแล้วหยุด คืน PCM bytes ของประโยคนั้น (หรือ None ถ้าเกิน wait_timeout)
        initial = เสียงที่ได้มาแล้ว (กรณีผู้ใช้พูดแทรก) → ฟังต่อจากนั้นจนพูดจบ"""
        pre = collections.deque(maxlen=17)          # เก็บเสียงก่อนเริ่มพูด 0.5 วินาที (ไม่ให้พยางค์แรกหาย)
        voiced, speech, silence, loud_run = [], 0, 0, 0
        upeak = 0.0                                  # เสียงพูดที่ดังที่สุดในประโยคนี้
        started = False
        t0 = time.time()
        end_frames = int(end_silence * 1000 / FRAME_MS)
        max_frames = int(max_seconds * 1000 / FRAME_MS)
        if initial:
            started, voiced, speech = True, list(initial), len(initial)
        elif hasattr(self, "q") and self.q.qsize() > 170:
            # ค้างเกิน 5 วินาที → เก็บไว้แค่ 1 วินาทีล่าสุด
            # (ไม่ทิ้งหมด! เสียงที่ผู้ใช้พูดระหว่างระบบกำลังแปลงคำปลุก ต้องไม่หาย)
            while self.q.qsize() > 33:
                self.q.get_nowait()
        while True:
            frame = self._frame()
            if muted() and not started:
                pre.clear()
                t0 = time.time() if wait_timeout else t0
                continue
            level = rms(frame)
            self._track_noise(level)                # (มีเพดาน — ไม่ให้เกณฑ์ไต่เกินเสียงพูด)
            thresh = max(self.noise * 2.8, config.VAD_MIN_RMS)
            if not started:
                pre.append(frame)
                loud_run = loud_run + 1 if level > thresh else 0
                if loud_run >= 3:
                    started = True
                    voiced = list(pre)
                    speech, silence = loud_run, 0
                elif wait_timeout and time.time() - t0 > wait_timeout:
                    return None
                continue
            voiced.append(frame)
            # ห้องมีพัดลม/ทีวีเบาๆ: เสียงพื้นหลังสูงกว่าเกณฑ์ตลอด → ไม่เคย "เงียบ" จนฟังยาวเต็ม 15 วิ
            # → พอพูดไปได้สักพัก ถ้าเสียงลดเหลือไม่ถึง 22% ของเสียงพูดที่ดังสุด ก็นับว่าเงียบแล้ว
            if level > upeak and level > thresh:
                upeak = level
            quiet = level <= thresh or (speech >= 15 and level < upeak * 0.22)
            if not quiet:
                speech += 1
                silence = 0
            else:
                silence += 1
            if silence >= end_frames or len(voiced) >= max_frames:
                if speech * FRAME_MS / 1000 < min_speech:   # เสียงสั้นๆ เช่น เคาะโต๊ะ → ข้าม
                    started, voiced, pre, loud_run = False, [], collections.deque(maxlen=17), 0
                    continue
                if upeak > 0:                                # จำความดังเสียงพูดล่าสุด (ไว้จำกัดเพดานเสียงพื้นหลัง)
                    old = getattr(self, "speech_peak", 0.0)
                    self.speech_peak = upeak if not old else old * 0.6 + upeak * 0.4
                return b"".join(voiced)


class AmrStream(MicStream):
    """ฟังเรียลไทม์แบบไม่ใช้ PulseAudio: termux-microphone-record อัดเป็น AMR-WB ยาวต่อเนื่อง
    แล้ว ffmpeg ถอดเสียงจากไฟล์ที่กำลังโตขึ้นเรื่อยๆ ออกมาเป็นเสียงดิบทันที"""

    GRACE = 0.6

    def __init__(self):
        if not shutil.which("ffmpeg") or not shutil.which("termux-microphone-record"):
            raise RuntimeError("ต้องมี ffmpeg และ termux-api")
        self.path = os.path.join(config.DATA_DIR, "live.amr")
        _sh(["termux-microphone-record", "-q"])
        try:
            os.remove(self.path)
        except OSError:
            pass
        code, out = _sh(["termux-microphone-record", "-f", self.path, "-e", "amr_wb",
                         "-r", "16000", "-c", "1", "-l", "0"])
        if "error" in out.lower():
            raise RuntimeError(out)
        self.recorder_out = out.strip()
        sizes = []
        for _ in range(15):                       # ดูว่าไฟล์โตขึ้นเรื่อยๆ แบบเรียลไทม์ไหม
            sizes.append(os.path.getsize(self.path) if os.path.exists(self.path) else 0)
            time.sleep(0.1)
        if sizes[-1] <= 9:
            _sh(["termux-microphone-record", "-q"])
            raise RuntimeError(f"ไฟล์ AMR ไม่โต (ขนาด {sizes[::5]}) recorder: {out.strip()[:120]}")
        self.errlog = os.path.join(config.DATA_DIR, "amr_ffmpeg.log")
        cmd = (f"tail -c +1 -f '{self.path}' | ffmpeg -hide_banner -loglevel error -fflags nobuffer "
               f"-probesize 64 -analyzeduration 0 -f amr -i pipe:0 -f s16le -ar {RATE} -ac 1 pipe:1 "
               f"2>'{self.errlog}'")
        self.proc = subprocess.Popen(["bash", "-c", cmd], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0, start_new_session=True)
        self._start_reader()

    def check_alive(self, seconds=3.0):
        ok = super().check_alive(seconds)
        if not ok:
            try:
                err = open(self.errlog, encoding="utf-8", errors="replace").read().strip()[-200:]
            except OSError:
                err = ""
            size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
            _why.append(f"AmrStream: ไม่ได้เสียง (ไฟล์ {size} ไบต์) ffmpeg: {err or '-'}")
        return ok

    def close(self):
        import signal
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
        _sh(["termux-microphone-record", "-q"])


# ---------------------------------------------------------------- วิธีสำรอง

class ChunkMic:
    """อัดทีละ 2 วินาทีต่อกันไปเรื่อยๆ ด้วย termux-microphone-record แล้วรวมท่อนที่มีเสียงพูด"""

    CHUNK = 2

    def __init__(self):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("วิธีสำรองต้องใช้ ffmpeg: pkg install ffmpeg")
        self.i = 0

    def close(self):
        _sh(["termux-microphone-record", "-q"])

    def _chunk(self):
        import voice
        self.i = (self.i + 1) % 20
        path = os.path.join(config.DATA_DIR, f"chunk_{self.i}.m4a")
        voice.record(self.CHUNK, path)
        db = voice.loudness_db(path)
        return path, (db is not None and db >= config.WAKE_MIN_DB)

    def watch_interrupt(self, active, factor=None, paused=None):
        while active():                 # โหมดสำรองพูดแทรกไม่ได้
            time.sleep(0.2)
        return None

    def utterance(self, wait_timeout=None, max_seconds=15.0, **_):
        t0 = time.time()
        parts = []
        while True:
            if muted():
                time.sleep(0.2)
                continue
            path, loud = self._chunk()
            if loud:
                parts.append(path)
                if len(parts) * self.CHUNK >= max_seconds:
                    break
            elif parts:
                break
            elif wait_timeout and time.time() - t0 > wait_timeout:
                return None
        out = os.path.join(config.DATA_DIR, "utterance.wav")
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        for p in parts:
            args += ["-i", p]
        args += ["-filter_complex", f"concat=n={len(parts)}:v=0:a=1", "-ar", str(RATE), "-ac", "1",
                 "-f", "s16le", "-"]
        pcm = subprocess.run(args, capture_output=True, timeout=30).stdout
        return pcm or None


class MockMic:
    interrupt_frames = None

    def utterance(self, initial=None, **_):
        return b"\x00\x10" * RATE

    def watch_interrupt(self, active, factor=None, paused=None):
        while active():
            if self.interrupt_frames:
                f, self.interrupt_frames = self.interrupt_frames, None
                return f
            time.sleep(0.02)
        return None

    def close(self):
        pass


class AndroidMic(MicStream):
    """โหมดแอป APK: อ่านเสียงจาก AudioRecord ของแอป (ไม่ต้องใช้ PulseAudio/Termux)"""

    def __init__(self):
        import android_shim
        self.b = android_shim.bridge()
        if not self.b.micAllowed():
            raise RuntimeError("แอปยังไม่ได้รับสิทธิ์ไมค์ (เปิดแอป → 🔐 สิทธิ์)")
        if not self.b.micStart():
            raise RuntimeError(f"เปิดไมค์ไม่ได้: {self.b.micError()}")
        self.proc = None
        self.closed = False
        self.owner = None          # thread ที่จองไมค์อยู่ (ปุ่มไมค์ในแอป) — คนอื่นได้ความเงียบชั่วคราว
        self.peak = 0.0
        self._start_reader()
        self.noise = 40.0          # AudioRecord ของแอปเสียงเบากว่า PulseAudio → เริ่มเกณฑ์ต่ำ

    NOISE_CAP = 120.0

    def _frame(self, timeout=1.0):
        if self.owner is not None and threading.get_ident() != self.owner:
            time.sleep(FRAME_MS / 1000)
            return b"\x00\x00" * FRAME_SAMPLES
        f = super()._frame(timeout)
        lv = rms(f)
        if lv > self.peak:
            self.peak = lv
        return f

    def restart(self):
        """สร้างตัวอัดเสียงใหม่ (ระบบปิดไมค์ตอนแอปอยู่เบื้องหลัง → เปิดใหม่ตอนแอปอยู่หน้าจอ)
        ตัวอ่านเสียงตายแล้ว → เริ่มตัวอ่านใหม่ด้วย · ล้างค่าเสียงพื้นหลังเก่า (ไมค์ใหม่ระดับเสียงไม่เท่าเดิม)"""
        try:
            self.b.micStop()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
        ok = False
        try:
            ok = bool(self.b.micStart())
        except Exception as e:  # noqa: BLE001
            print(f"🎙️ เปิดไมค์ใหม่ไม่ได้: {e}", flush=True)
        if not ok:
            try:
                print(f"🎙️ เปิดไมค์ใหม่ไม่สำเร็จ: {self.b.micError()}", flush=True)
            except Exception:  # noqa: BLE001
                pass
        if self.reader_dead():
            self.closed = False
            self._start_reader()                       # ตั้ง noise ใหม่ด้วย
            print("🎙️ ตัวอ่านเสียงหลุด → เริ่มใหม่แล้ว", flush=True)
        self.noise = 40.0
        self.reset_noise()
        self.speech_peak = 0.0
        self.last_sound = time.time()
        return ok

    def _read_exact(self):
        import android_shim
        buf = b""
        while len(buf) < FRAME_BYTES:
            if self.closed:
                raise RuntimeError("ปิดไมค์แล้ว")
            chunk = android_shim.jbytes(self.b.micRead(1000))
            if not chunk:
                if not self.b.micAllowed():
                    raise RuntimeError("ไมค์ถูกปิดสิทธิ์")
                continue
            buf += chunk
        return buf[:FRAME_BYTES]

    def close(self):
        self.closed = True
        try:
            self.b.micStop()
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        super().flush()
        try:
            self.b.micFlush()
        except Exception:  # noqa: BLE001
            pass


def open_mic():
    """เลือกวิธีฟังที่ดีที่สุดที่เครื่องรองรับ"""
    if config.MOCK_PHONE:
        return MockMic(), "mock"
    if config.ANDROID_APP:
        return AndroidMic(), "realtime-app"
    for cls, name in ((MicStream, "realtime"), (AmrStream, "realtime-amr")):
        m = None
        try:
            m = cls()
            alive = m.check_alive()
        except Exception as e:  # noqa: BLE001
            _why.append(f"{cls.__name__}: {e}")
            alive = False
        if alive:
            return m, name
        if m is not None:
            m.close()                       # ปล่อยไมค์คืน ไม่งั้นโหมดถัดไปจะอัดไม่ได้
        elif cls is AmrStream:
            _sh(["termux-microphone-record", "-q"])
        if cls is MicStream and m is not None:
            _why.append("PulseAudio: ได้แต่ความเงียบ (Termux อาจไม่มีสิทธิ์ไมค์)")
    return ChunkMic(), "chunk"


def diagnose():
    """python audio_stream.py — ตรวจว่าทำไมโหมดเรียลไทม์ใช้ไม่ได้"""
    print("pulseaudio:", shutil.which("pulseaudio"), "| parec:", shutil.which("parec"),
          "| ffmpeg:", shutil.which("ffmpeg"))
    print("ไมค์ PulseAudio:", start_pulseaudio())
    print(_sh(["pactl", "list", "short", "sources"])[1][:500])
    m, mode = open_mic()
    print("ผล:", mode)
    for w in _why:
        print(" -", w)
    if mode.startswith("realtime"):
        print("พูดอะไรก็ได้ 5 วินาที...")
        t0 = time.time()
        while time.time() - t0 < 5:
            lv = rms(m._frame())
            print(f"\r{int(lv):5d} " + "█" * min(40, int(lv / 100)) + " " * 40, end="", flush=True)
        print()
    m.close()


if __name__ == "__main__":
    diagnose()
