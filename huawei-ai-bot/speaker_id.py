"""จำเสียงเจ้าของเครื่อง (ทำงานในเครื่อง ไม่ส่งเสียงไปไหน) — ใช้กรองให้บอทฟังเฉพาะเสียงคุณ

วิธี: แปลงเสียงเป็น "ลายเสียง" (MFCC: ลักษณะช่องเสียง/โทนเสียงของแต่ละคน) แล้วเทียบกับเสียงที่บันทึกไว้ตอนสอน
ข้อจำกัด: แยกเสียงคนละคน/ทีวี/เพลงได้ดี แต่คนเสียงคล้ายกันมาก (เช่น พี่น้อง) อาจหลุดผ่านได้บ้าง

สอนเสียง: bash enroll_voice.sh (พูด 6 ประโยค ~1 นาที)
ไฟล์: data/voiceprint.json
"""
import json
import os

import config

RATE = 16000
N_MFCC = 20
_cache = {"prof": None, "mtime": 0}


def _np():
    try:
        import numpy
        return numpy
    except ImportError:
        return None


def available():
    return _np() is not None or bool(config.ANDROID_APP)


def _path():
    return os.path.join(config.DATA_DIR, "voiceprint.json")


def _mel_filters(n_fft=512, n_mels=40, fmin=60, fmax=7600):
    import numpy as np
    def hz2mel(h):
        return 2595 * np.log10(1 + h / 700.0)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595.0) - 1)
    mels = np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2)
    bins = np.floor((n_fft + 1) * mel2hz(mels) / RATE).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(1, n_mels + 1):
        a, b, c = bins[i - 1], bins[i], bins[i + 1]
        for k in range(a, b):
            fb[i - 1, k] = (k - a) / max(1, b - a)
        for k in range(b, c):
            fb[i - 1, k] = (c - k) / max(1, c - b)
    return fb


def features(pcm):
    """PCM 16-bit 16kHz → เวกเตอร์ลายเสียง (หรือ None ถ้าเสียงพูดสั้นเกินไป)"""
    if _np() is None:                                   # แอป APK: คำนวณด้วย Kotlin (VoicePrint) เร็วกว่า
        import android_shim
        out = str(android_shim.bridge().voiceFeatures(bytes(pcm)) or "")
        return json.loads(out) if out else None
    import numpy as np
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if len(x) < RATE * 0.6:
        return None
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])                     # pre-emphasis
    flen, hop, n_fft = 400, 160, 512
    n = 1 + (len(x) - flen) // hop
    idx = np.arange(flen)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hamming(flen)
    energy = (frames ** 2).sum(axis=1)
    keep = energy > np.percentile(energy, 40)                       # เฉพาะช่วงที่มีเสียงพูด
    frames = frames[keep]
    if len(frames) < 40:
        return None
    pw = np.abs(np.fft.rfft(frames, n_fft)) ** 2 / n_fft
    mel = np.log(pw @ _mel_filters(n_fft).T + 1e-6)
    k = np.arange(mel.shape[1])
    dct = np.cos(np.pi / mel.shape[1] * (k[None, :] + 0.5) * np.arange(N_MFCC + 1)[:, None])
    mfcc = (mel @ dct.T)[:, 1:]                                    # ตัด c0 (ความดัง) ทิ้ง
    delta = np.diff(mfcc, axis=0)
    return np.concatenate([mfcc.mean(0), mfcc.std(0), delta.std(0)])


def _load():
    p = _path()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return None
    if _cache["prof"] is None or m != _cache["mtime"]:
        with open(p, encoding="utf-8") as f:
            _cache["prof"] = json.load(f)
        _cache["mtime"] = m
    return _cache["prof"]


def enrolled():
    return available() and _load() is not None


def _score(v, prof):
    """ระยะห่างแบบปรับสเกล → คะแนน 0-1 (1 = เหมือนมาก) — ไม่ต้องใช้ numpy"""
    mu, sd = prof["mean"], prof["std"]
    d2 = sum(((float(x) - m) / s) ** 2 for x, m, s in zip(v, mu, sd))
    return float(1.0 / (1.0 + (d2 / len(mu)) ** 0.5))


def _stats(V):
    n = len(V)
    mu = [sum(col) / n for col in zip(*V)]
    sd = [(sum((x - m) ** 2 for x in col) / n) ** 0.5 + abs(m) * 0.08 + 0.5 for col, m in zip(zip(*V), mu)]
    return mu, sd                                                  # +ค่าเผื่อ กันหารด้วยค่าเล็กเกิน


def enroll(samples):
    """samples = list ของ PCM ประโยคต่างๆ จากเจ้าของ → บันทึกลายเสียง + เกณฑ์อัตโนมัติ"""
    vecs = [[float(x) for x in v] for v in (features(s) for s in samples) if v is not None]
    if len(vecs) < 3:
        raise ValueError("เสียงสั้น/เบาเกินไป ได้ตัวอย่างไม่พอ (ต้องการอย่างน้อย 3 ประโยค)")
    mu, sd = _stats(vecs)
    prof = _build(vecs, len(vecs))
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(prof, f)
    _cache["prof"] = None
    return prof


MARGIN = 0.13          # เผื่อเสียงจริงต่างจากตอนสอน (ระยะ/เสียงรอบข้าง/พูดเร็ว)
MAX_LEARNED = 24       # เก็บเสียงจากการใช้งานจริงได้สูงสุดกี่ประโยค
last = {"score": None, "th": None}


def _build(vecs, n_enrolled):
    """สร้างโปรไฟล์จากเวกเตอร์ทั้งหมด: ค่าเฉลี่ย/การกระจาย + เกณฑ์จากการทดสอบแบบไม่รวมตัวเอง"""
    mu, sd = _stats(vecs)
    scores = []
    for i in range(len(vecs)):                                     # ทดสอบแบบไม่รวมตัวเอง
        rmu, rsd = _stats(vecs[:i] + vecs[i + 1:])
        scores.append(_score(vecs[i], {"mean": rmu, "std": rsd}))
    lo = sorted(scores)[min(1, len(scores) - 1)] if len(scores) >= 8 else min(scores)   # ตัดตัวที่แย่สุดทิ้งเมื่อมีมากพอ
    return {"mean": mu, "std": sd, "n": n_enrolled, "vecs": vecs, "self": scores,
            "threshold": round(max(0.2, lo - MARGIN), 3)}


def adapt(pcm):
    """เสียงที่ผ่านแล้ว (เจ้าของเรียก 'ผู้ช่วย' แล้วสั่งงาน) → เก็บไว้เรียนรู้เสียงจริงตอนใช้งาน
    ทำให้ระยะ/ห้อง/ไมค์จริงถูกนับรวม เสียงเจ้าของจะโดนปฏิเสธน้อยลงเรื่อยๆ"""
    prof = _load() if available() else None
    if not prof or "vecs" not in prof:
        return False
    try:
        v = features(pcm)
    except Exception:  # noqa: BLE001
        return False
    if v is None:
        return False
    n = int(prof.get("n", 0))
    vecs = [list(map(float, x)) for x in prof["vecs"]]
    learned = vecs[n:] + [[float(x) for x in v]]
    new = _build(vecs[:n] + learned[-MAX_LEARNED:], n)
    new["learned"] = len(learned[-MAX_LEARNED:])
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(new, f)
    _cache["prof"] = None
    return True


def check(pcm, lenient=0.0):
    """คืน (เป็นเจ้าของไหม, คะแนน) — ถ้ายังไม่ได้สอนเสียง ถือว่าผ่าน · lenient = ผ่อนเกณฑ์ลง"""
    prof = _load() if available() else None
    if not prof:
        return True, None
    try:
        v = features(pcm)
    except Exception:  # noqa: BLE001
        return True, None
    if v is None:
        return True, None                                          # สั้นเกินตัดสิน → ไม่บล็อก
    s = _score(v, prof)
    th = prof["threshold"] + config.SPEAKER_STRICT - lenient
    last["score"], last["th"] = round(s, 3), round(th, 3)
    return s >= th, round(s, 3)


def near(gap=0.12):
    """เสียงล่าสุดเกือบผ่าน (อาจเป็นเจ้าของที่พูดไกล/เสียงต่างจากตอนสอน)"""
    s, th = last["score"], last["th"]
    return s is not None and th is not None and s >= th - gap


def forget():
    try:
        os.remove(_path())
    except OSError:
        pass
