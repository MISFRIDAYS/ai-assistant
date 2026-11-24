"""เสียง: แปลงเสียงเป็นข้อความ (Groq Whisper) และข้อความเป็นเสียงพูดภาษาไทย (Google TTS ผ่าน gTTS)

ใช้ได้แม้เครื่อง Huawei ไม่มีโปรแกรมเสียงพูด (TTS engine) ในตัว
"""
import math
import os
import json
import re
import shutil
import struct
import subprocess
import threading
import time
import wave

import requests

import config

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# ประโยคที่ Whisper ชอบ "หลอน" ออกมาเองตอนเงียบ
_HALLUCINATIONS = {
    "ขอบคุณครับ", "ขอบคุณค่ะ", "ขอบคุณที่รับชม", "ขอบคุณที่รับชมครับ", "ขอบคุณที่รับชมค่ะ",
    "ติดตามช่องของเราด้วยนะคะ", "subscribe", "thank you", "thanks for watching", "you", ".", "",
    "ฝากกดไลค์กดแชร์กดซับสไครบ์ด้วยนะครับ", "ซับไตเติ้ลโดย", "สวัสดีครับ ขอบคุณครับ",
}


# ประโยคที่ระบบถอดเสียงชอบ "แต่งขึ้นเอง" ตอนได้ยินแค่เสียงรบกวน
_HALLU_RX = re.compile(r"(ขอบคุณ(ที่|สำหรับการ)?รับชม|ติดตาม(ช่อง|ชม)|กด(ไลค์|ไลก์|แชร์|ซับ|ติดตาม)|ซับสไครบ์|subscribe|"
                       r"ซับไตเติ้ล|คำบรรยาย(โดย)?|แปลโดย|thanks? (you )?for watching|amara\.org|"
                       r"^\W*(อืม+|เอ่อ+|อ่า+|ฮะ|ห๊ะ|หือ|ฮือ|อ้า|โอ้|ว้าว|you|bye)\W*$)", re.I)


def _norm_t(t):
    return re.sub(r"[\s.,!?'\"“”()\-]+", "", (t or "").lower())


_MOJI = re.compile(r"[àÃâ][\u0080-\u00BF¸¹º]")


def fix_mojibake(text):
    """ไทยที่ถูกอ่านผิดรหัส (UTF-8 → Latin-1) เช่น 'à¸ªà¸§à¸±à¸ª' → 'สวัส' — กู้กลับเป็นภาษาไทย"""
    t = text or ""
    if not _MOJI.search(t):
        return t
    for enc in ("latin-1", "cp1252"):
        try:
            fixed = t.encode(enc).decode("utf-8")
            if re.search(r"[\u0E00-\u0E7F]", fixed):
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    try:
        return t.encode("latin-1", "ignore").decode("utf-8", "ignore") or t
    except Exception:  # noqa: BLE001
        return t


def _json_utf8(r):
    """อ่าน JSON เป็น UTF-8 เสมอ (บางครั้งเซิร์ฟเวอร์ไม่บอก charset → ไลบรารีเดาเป็น Latin-1 → ไทยเพี้ยน)"""
    c = getattr(r, "content", None)
    if isinstance(c, (bytes, bytearray)):
        return json.loads(c.decode("utf-8", "replace"))
    return r.json()


def _wake_only(n):
    """ข้อความ (ตัดช่องว่างแล้ว) เป็นแค่คำปลุก เช่น "ผู้ช่วย" "สวัสดีผู้ช่วย" — ห้ามทิ้งเป็นคำหลอน"""
    try:
        wakes = {_norm_t(w) for w in config.WAKE_WORDS}
    except Exception:  # noqa: BLE001
        wakes = set()
    return n in wakes or (n.endswith("ผู้ช่วย") and len(n) <= 14)


_REPEAT_SHORT = re.compile(r"(.{2,6})\1{3,}")         # คำซ้ำวนๆ "เปิดเปิดเปิดเปิด"
_REPEAT_LONG = re.compile(r"(.{4,24}?)\1{2,}")        # วลียาวซ้ำ 3 รอบ "ภรรยาสันทร์ภรรยาสันทร์ภรรยาสันทร์"


def is_hallucination(text, prompt=""):
    """ข้อความนี้น่าจะไม่ใช่คนพูดจริง (เสียงรบกวน → ระบบแต่งประโยคขึ้นเอง)"""
    t = (text or "").strip()
    if not t or t.lower().strip(" .!") in _HALLUCINATIONS or _HALLU_RX.search(t):
        return True
    n = _norm_t(t)
    if len(n) < 2:
        return True
    if _wake_only(n):                                      # เรียกชื่อเฉยๆ = คำพูดจริง (เคยถูกทิ้งเพราะอยู่ในคำใบ้)
        return False
    # ตัวอักษรภาษาอื่นที่ไม่ใช่ไทย/อังกฤษ (จีน ญี่ปุ่น เกาหลี รัสเซีย อาหรับ ฮินดี ฯลฯ) = ถอดเสียงเพี้ยน
    foreign = len(re.findall(r"[\u0400-\u04FF\u0590-\u06FF\u0900-\u0DFF\u0E80-\u0EFF\u1000-\u109F"
                             r"\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF\u00C0-\u024F]", t))
    if foreign >= 2 and foreign >= len(n) * 0.2:
        return True
    if _REPEAT_SHORT.search(n) or _REPEAT_LONG.search(n):
        return True
    pn = _norm_t(prompt)
    if pn and len(n) >= 4 and n in pn:                     # ท่องคำใบ้ (ชื่อแอป/ชื่อคน) ออกมาเอง
        return True
    if prompt_echo(t, prompt):
        return True
    return False


def _prompt_terms(prompt):
    """คำใบ้ → รายการคำ (ตัดช่องว่าง/วงเล็บแล้ว) ชื่อมีวงเล็บได้ทั้งตัวเต็ม นอกวงเล็บ และในวงเล็บ"""
    out = []
    for raw in re.split(r"[,，]", prompt or ""):
        raw = raw.strip()
        if not raw:
            continue
        parts = [raw]
        wake = (getattr(config, "STT_PROMPT", "") or "").strip()
        if wake and raw.startswith(wake) and raw != wake:  # "สวัสดีผู้ช่วย Heart" (คำปลุกติดชื่อแรก)
            parts = [wake, raw[len(wake):]]
        for p in parts:
            m = re.match(r"^(.*?)\((.*?)\)\s*$", p)
            for x in ([p, m.group(1), m.group(2)] if m else [p]):
                k = _norm_t(x)
                if len(k) >= 3 and k not in out:
                    out.append(k)
    return out


def prompt_echo(text, prompt):
    """ท่องรายชื่อจากคำใบ้ออกมาเป็นชุด เช่น "ไปที่แชท Haryaya, Wanchaporn, ภรรยา, Wanchaporn"
    (Whisper ชอบเอาชื่อในคำใบ้มาเรียงต่อกันเองเวลาเสียงไม่ชัด)"""
    terms = _prompt_terms(prompt)
    if not terms:
        return False
    n = _norm_t(text)
    hits = [k for k in terms if k in n]
    # ชื่อสั้นที่อยู่ในชื่อยาวที่เจอแล้ว ไม่นับซ้ำ ("ภรรยา" ใน "ภรรยาคนเจก")
    hits = [k for k in hits if not any(k != o and k in o for o in hits)]
    total = sum(n.count(k) for k in hits)
    if len(hits) >= 3 or total >= 4:
        return True
    if len(hits) >= 2 and total >= 3:
        return True
    # คำปลุกโผล่กลางข้อความ + มีชื่อจากคำใบ้ = ท่องคำใบ้
    # (เฉพาะคำปลุกแบบมีคำทัก เช่น "สวัสดีผู้ช่วย" ที่อยู่ถัดจากต้นประโยค — เรียกชื่อตอนต้นประโยคเป็นเรื่องปกติ)
    wakes = [_norm_t(w) for w in getattr(config, "WAKE_WORDS", []) if len(_norm_t(w)) >= 9]
    mid_wake = any(n.find(w, 6) >= 6 for w in wakes)
    names = [k for k in hits if not any(k in w or w in k for w in wakes)]
    return mid_wake and bool(names)


def message_echo(msg):
    """ข้อความที่จะส่งให้คนอื่น ดูเหมือนระบบถอดเสียงแต่งขึ้นเองไหม (ท่องรายชื่อ/คำปลุก/วลีซ้ำ) → True = ห้ามส่ง"""
    t = (msg or "").strip()
    if not t:
        return False
    n = _norm_t(t)
    if len(n) >= 12 and _REPEAT_LONG.search(n):
        return True
    try:
        prompt = _stt_prompt()
    except Exception:  # noqa: BLE001
        prompt = getattr(config, "STT_PROMPT", "")
    return prompt_echo(t, prompt)


class VoiceError(Exception):
    pass


def _api(args, **kw):
    """เรียก Termux:API ทีละคำสั่ง (กันชนกันจนขึ้น error สีแดง) และไม่ตัดกลางคัน"""
    import termux_lock
    kw["timeout"] = max(kw.get("timeout", 30), 60)
    kw.setdefault("capture_output", True)
    with termux_lock.termux_api():
        return subprocess.run(args, **kw)


# ---------------------------------------------------------------- เสียง → ข้อความ

def nano_stt_ready():
    """ถอดเสียงผ่าน NanoGPT ได้ไหม (ใช้คีย์ Cloud AI เมื่อที่อยู่เป็น NanoGPT หรือคีย์ NANO_API_KEY แยก)"""
    return bool(_nano_key())


def _nano_key():
    k = os.environ.get("NANO_API_KEY", "").strip()
    if k:
        return k
    if config.CLOUD_API_KEY and "nano-gpt" in (config.CLOUD_BASE_URL or ""):
        return config.CLOUD_API_KEY
    return ""


def cf_stt_ready():
    """Cloudflare Workers AI (ฟรีวันละ ~200 นาทีเสียง) — ต้องมี Account ID + API Token"""
    return bool(config.CF_ACCOUNT_ID and config.CF_API_TOKEN)


_READY = {"groq": lambda: bool(config.GROQ_API_KEY), "cloudflare": cf_stt_ready, "nano": nano_stt_ready}
class _OffMap(dict):
    """ตัวถอดเสียงที่เพิ่งใช้ไม่ได้ (คีย์ผิด/โควตาหมด) → ข้ามชั่วคราว · จำลงไฟล์ด้วย
    (เดิมจำแค่ในหน่วยความจำ → ทุกครั้งที่บอทเริ่มใหม่ ประโยคแรกเสียเวลาลองคีย์ที่รู้ว่าใช้ไม่ได้ซ้ำ)"""

    def _path(self):
        return os.path.join(config.DATA_DIR, "stt_off.json")

    def load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
            now = time.time()
            self.update({k: float(v) for k, v in d.items() if float(v) > now})
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return self

    def _save(self):
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump({k: v for k, v in self.items() if v > time.time()}, f)
        except (OSError, TypeError, ValueError):
            pass

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._save()

    def pop(self, k, *a):
        r = super().pop(k, *a)
        self._save()
        return r


_off = _OffMap().load()


def stt_chain():
    """ลำดับตัวถอดเสียงที่จะลอง: ตัวที่เลือก → ฟรีก่อน (Groq, Cloudflare) → NanoGPT (จ่ายตามใช้)"""
    order = ["groq", "cloudflare", "nano"]
    want = config.STT_PROVIDER
    if want in order:
        order.remove(want)
        order.insert(0, want)
    elif not config.GROQ_API_KEY:
        order = ["cloudflare", "nano", "groq"]
    ready = [e for e in order if _READY[e]()]
    now = time.time()
    return [e for e in ready if _off.get(e, 0) <= now] or ready


def stt_engine():
    """ตัวถอดเสียงหลัก: 'groq' | 'cloudflare' | 'nano' | '' (ไม่มี)"""
    c = stt_chain()
    return c[0] if c else ""


def stt_available():
    return bool(stt_engine())


def _transcribe_cf(path):
    """ถอดเสียงด้วย Cloudflare Workers AI (Whisper Large v3 Turbo) — ฟรีตามโควตารายวัน"""
    import base64
    with open(path, "rb") as f:
        raw = f.read()
    url = (f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/run/"
           f"{config.CF_STT_MODEL}")
    hdr = {"Authorization": f"Bearer {config.CF_API_TOKEN}"}
    b64 = base64.b64encode(raw).decode()
    t0 = time.time()
    prompt = _stt_prompt()
    body = {"audio": b64, "language": "th", "task": "transcribe", "vad_filter": True,
            "initial_prompt": prompt, "condition_on_previous_text": False}
    r = _session("cf").post(url, headers=hdr, json=body, timeout=60)
    if r.status_code == 400 and "audio" in r.text.lower():           # บางรุ่นรับรูปแบบ {body, contentType}
        body["audio"] = {"body": b64, "contentType": "audio/wav"}
        r = _session("cf").post(url, headers=hdr, json=body, timeout=60)
    low = r.text.lower()
    if r.status_code in (401, 403):
        _off["cloudflare"] = time.time() + 24 * 3600         # คีย์ผิด → ไม่ลองซ้ำทุกประโยค (เสียเวลาเปล่า) พัก 6 ชม.
        print(f"⚠️ Cloudflare ตอบ {r.status_code}: {r.text[:200]}", flush=True)
        raise VoiceError("Cloudflare: Account ID หรือ API Token ไม่ถูกต้อง (ต้องเป็น token แบบ Workers AI) — "
                         "พักใช้ 24 ชม. แก้ที่ ⚙️ → 🎤 เสียง → ✏️ แก้คีย์ Cloudflare")
    if r.status_code != 200 and (r.status_code == 429 or any(k in low for k in ("neuron", "allocation", "limit"))):
        _off["cloudflare"] = time.time() + 3600
        raise VoiceError(f"Cloudflare: โควตาฟรีวันนี้หมด/ถูกจำกัด ({r.status_code}) — พัก 1 ชม.")
    if r.status_code != 200:
        raise VoiceError(f"Cloudflare STT {r.status_code}: {r.text[:200]}")
    data = _json_utf8(r)
    res = data.get("result") or data
    text = fix_mojibake((res.get("text") or "").strip())
    _last["stt_time"] = time.time() - t0
    segs = res.get("segments") if isinstance(res.get("segments"), list) else []
    return _judge(text, [x for x in segs if isinstance(x, dict)], prompt, "Cloudflare")


def _transcribe_nano(path):
    """ถอดเสียงด้วย NanoGPT (Whisper-Large-V3) — คิดเงินจากยอดคงเหลือตามความยาวเสียง"""
    name = os.path.basename(path)
    if name.endswith(".oga"):
        name = name[:-4] + ".ogg"
    t0 = time.time()
    with open(path, "rb") as f:
        r = _session("nano").post(
            config.NANO_STT_URL, headers={"x-api-key": _nano_key(), "Authorization": f"Bearer {_nano_key()}"},
            files={"file": (name, f)}, data={"model": config.NANO_STT_MODEL, "language": "th"}, timeout=60)
    if r.status_code in (402, 429) and ("subscription-only" in r.text or "subscription_only" in r.text):
        _off["nano"] = time.time() + 12 * 3600           # คีย์แบบใช้แพ็กเท่านั้น → ถอดเสียงไม่ได้ ไม่ต้องลองซ้ำ
        raise VoiceError("NanoGPT: คีย์ตั้งเป็น Subscription only ถอดเสียงไม่ได้ (ถอดเสียงต้องจ่ายตามใช้) — "
                         "ใช้ Groq/Cloudflare ถอดเสียงแทน")
    if r.status_code == 402 or "insufficient" in r.text.lower() or "subscription_only" in r.text:
        raise VoiceError("NanoGPT: ยอดเงินไม่พอสำหรับถอดเสียง — เติมเงินเล็กน้อย และตั้งคีย์เป็น "
                         "\"Subscription first\" (หน้า API keys)")
    if r.status_code != 200:
        raise VoiceError(f"NanoGPT STT {r.status_code}: {r.text[:200]}")
    data = _json_utf8(r)
    text = fix_mojibake((data.get("text") or "").strip())
    _last["stt_time"] = time.time() - t0
    return _judge(text, data.get("segments") or [], "", "NanoGPT")


NANO_WAKE_PER_HOUR = int(os.environ.get("NANO_WAKE_PER_HOUR", "40"))   # รอคำปลุกด้วย NanoGPT (เสียเงิน) ได้กี่ครั้ง/ชม.
_nano_wake = []


def nano_wake_ok():
    """ตอนรอคำปลุก (ยังไม่รู้ว่าเรียกผู้ช่วยไหม) ใช้ตัวถอดเสียงที่เสียเงินได้ไม่เกิน NANO_WAKE_PER_HOUR ครั้ง/ชม.
    — ตัวฟรี (Groq/Cloudflare) ไม่จำกัด · คำสั่งหลังเรียกผู้ช่วยแล้วไม่จำกัด"""
    now = time.time()
    _nano_wake[:] = [t for t in _nano_wake if now - t < 3600]
    if NANO_WAKE_PER_HOUR > 0 and len(_nano_wake) >= NANO_WAKE_PER_HOUR:
        return False
    _nano_wake.append(now)
    return True


def transcribe(path, wake=False):
    """คืนข้อความจากไฟล์เสียง (m4a/ogg/mp3/wav) หรือ "" ถ้าไม่มีเสียงพูด — ลองตามลำดับ stt_chain()
    wake=True: กำลังรอคำปลุก → จำกัดการใช้ตัวที่เสียเงิน"""
    if config.MOCK_PHONE:
        return "ทดสอบ"
    chain = stt_chain()
    if not chain:
        raise VoiceError("ยังไม่มีตัวแปลงเสียงเป็นข้อความ — ⚙️ ตั้งค่า → 🎤 เสียง → เลือก Cloudflare (ฟรี) "
                         "หรือใส่คีย์ Groq")
    fn = {"groq": lambda p: _transcribe_groq(p), "cloudflare": _transcribe_cf, "nano": _transcribe_nano}
    err = None
    retried = False
    for i, eng in enumerate(chain):
        if eng == "nano" and wake and not nano_wake_ok():
            _last["why"] = "ครบโควตาถอดเสียงแบบเสียเงินตอนรอคำปลุกชั่วโมงนี้"
            print("🎚️ ข้าม NanoGPT ตอนรอคำปลุก (ครบโควตาชั่วโมงนี้ ประหยัดเงิน)", flush=True)
            return ""
        try:
            if eng == "groq":
                _last["engine"] = "Groq"
            _last["why"] = ""
            text = fn[eng](path)
            # ถอดออกมาเป็นภาษาแปลก/แต่งเอง (ไม่ใช่เงียบ) และมีตัวถอดเสียงอีกตัว → ให้ตัวถัดไปลองฟังซ้ำ 1 ครั้ง
            if (not text and not retried and _last.get("why") == "ข้อความแต่งเอง/ภาษาแปลก"
                    and i + 1 < len(chain) and (_last.get("sec") or 1.0) >= 0.8):
                retried = True
                print(f"🔁 {eng} ถอดเพี้ยน → ให้ {chain[i + 1]} ฟังซ้ำ", flush=True)
                continue
            return text
        except Exception as e:  # noqa: BLE001
            err = e
            if i + 1 < len(chain):
                print(f"⚠️ ถอดเสียงด้วย {eng} ไม่ได้ → ใช้ {chain[i + 1]}: {str(e)[:120]}", flush=True)
    if err is None or retried:
        return ""
    raise err if isinstance(err, VoiceError) else VoiceError(str(err))


import collections as _collections

HISTORY = _collections.deque(maxlen=30)       # ผลถอดเสียงล่าสุด (ไว้ดูว่าไมค์มีปัญหาตรงไหน: "รายงานไมค์")


def _seg_bad(x, prompt):
    try:
        if float(x.get("no_speech_prob", 0) or 0) > 0.6 or float(x.get("avg_logprob", 0) or 0) < -1.0 \
                or float(x.get("compression_ratio", 0) or 0) > 2.6:
            return True
    except (TypeError, ValueError):
        return False
    st = (x.get("text") or "").strip()
    n, pn = _norm_t(st), _norm_t(prompt)
    if not n:
        return True
    if _wake_only(n):
        return False
    return (pn and len(n) >= 4 and n in pn) or prompt_echo(st, prompt) or bool(_REPEAT_LONG.search(n))


def _trim_segments(segs, text, prompt):
    """หลายช่วง: ตัดช่วงที่ไม่ใช่คำพูด/ท่องคำใบ้ทิ้ง เก็บเฉพาะช่วงที่ดี (เดิมช่วงดีช่วงเดียวพาช่วงขยะผ่านไปด้วย)"""
    if not segs or len(segs) < 2 or not all(isinstance(x, dict) and "text" in x for x in segs):
        return segs, text
    keep = [x for x in segs if not _seg_bad(x, prompt)]
    if not keep or len(keep) == len(segs):
        return segs, text
    new = " ".join((x.get("text") or "").strip() for x in keep).strip()
    print(f"✂️ ตัดช่วงเสียงที่ไม่ใช่คำพูด {len(segs) - len(keep)} ช่วง: {text[:60]!r} → {new[:60]!r}", flush=True)
    return keep, new


def _judge(text, segs, prompt, engine):
    """ตัดสินว่าข้อความที่ถอดได้ "เป็นคำพูดจริง" ไหม (ใช้เกณฑ์เดียวกันทุกตัวถอดเสียง) → ข้อความ หรือ "" """
    _last["engine"] = engine
    _last["dropped"] = ""
    _last["no_speech"], _last["logprob"] = None, None
    why = ""
    segs, text = _trim_segments(segs, text, prompt)
    if segs:
        try:
            nsp = min(float(x.get("no_speech_prob", 0) or 0) for x in segs)
            lp = max(float(x.get("avg_logprob", 0) or 0) for x in segs)
            cr = max(float(x.get("compression_ratio", 0) or 0) for x in segs)
            _last["no_speech"], _last["logprob"] = round(nsp, 2), round(lp, 2)
            if nsp > 0.6 or lp < -1.0 or cr > 2.6:
                why = f"ไม่ใช่เสียงพูด (no_speech={nsp:.2f} logprob={lp:.2f})"
                _last["dropped"] = text           # ถ้าเป็นคำปลุก ("เฮ้ยผู้ช่วย" สั้นๆ มักมั่นใจต่ำ) ยังเอามาใช้ได้
        except (TypeError, ValueError, AttributeError):
            pass
    if not why and is_hallucination(text, prompt):
        why = "ข้อความแต่งเอง/ภาษาแปลก"
    _last["why"] = why
    HISTORY.append({"t": time.strftime("%H:%M:%S"), "engine": engine, "text": text[:80], "kept": not why,
                    "why": why, "nsp": _last["no_speech"], "lp": _last["logprob"],
                    "sec": _last.get("sec"), "peak": _last.get("peak")})
    try:
        with open(os.path.join(config.DATA_DIR, "mic.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({**HISTORY[-1], "t": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass
    if why:
        print(f"🔇 {why} ทิ้ง: {text[:40]!r} [{engine}]", flush=True)
        return ""
    return text


def _transcribe_groq(path):
    name = os.path.basename(path)
    if name.endswith(".oga"):
        name = name[:-4] + ".ogg"
    prompt = _stt_prompt()
    with open(path, "rb") as f:
        r = _session("groq").post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": (name, f)},
            data={"model": config.STT_MODEL, "language": "th", "temperature": "0",
                  "response_format": "verbose_json", "prompt": prompt},
            timeout=60,
        )
    if r.status_code != 200:
        raise VoiceError(f"Groq {r.status_code}: {r.text[:300]}")
    data = _json_utf8(r)
    text = fix_mojibake((data.get("text") or "").strip())
    return _judge(text, data.get("segments") or [], prompt, "Groq")


def transcribe_segments(path):
    """ถอดเสียงพร้อมเวลา (สำหรับทำซับ) คืน [{"start", "end", "text"}]"""
    if config.MOCK_PHONE:
        return [{"start": 0.0, "end": 1.5, "text": "ทดสอบซับ"}]
    if not config.GROQ_API_KEY:
        raise VoiceError("ต้องใส่ GROQ_API_KEY ก่อน")
    with open(path, "rb") as f:
        r = _session("groq").post(
            GROQ_URL, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": (os.path.basename(path), f)},
            data={"model": config.STT_MODEL, "language": "th", "temperature": "0",
                  "response_format": "verbose_json"}, timeout=300)
    if r.status_code != 200:
        raise VoiceError(f"Groq {r.status_code}: {r.text[:300]}")
    segs = _json_utf8(r).get("segments") or []
    return [{"start": float(s["start"]), "end": float(s["end"]), "text": fix_mojibake(s.get("text", ""))}
            for s in segs if (s.get("text") or "").strip() and s.get("no_speech_prob", 0) < 0.8]


# ---------------------------------------------------------------- ข้อความ → เสียง

def clean_for_speech(text, limit=600):
    t = re.sub(r"https?://\S+", "", text)
    t = re.sub(r"📎 แหล่งที่มา:.*", "", t, flags=re.S)
    t = re.sub(r"[*_`#>|]", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️✅❗⚠]", "", t)  # อีโมจิ
    t = re.sub(r"฿\s*([\d,.]+)", r"\1 บาท", t)                  # ฿158 → 158 บาท
    t = re.sub(r"\$\s*([\d,.]+)", r"\1 ดอลลาร์", t)
    t = re.sub(r"(\d)\s*°\s*C", r"\1 องศา", t)
    t = re.sub(r"(\d)\s*%", r"\1 เปอร์เซ็นต์", t)
    t = re.sub(r"\s*[≈~]\s*", " ประมาณ ", t)
    t = re.sub(r"\s*&\s*", " และ ", t)
    t = re.sub(r"\(([^)]{0,40})\)", r", \1,", t)                # วงเล็บ → เว้นจังหวะ
    t = re.sub(r"[\[\]{}<>=+^\\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t[:limit]


def more_note():
    """ประโยคบอกว่าคำตอบเต็มอยู่ที่ไหน (แอป → บนจอ · Termux/Telegram → ในแชท Telegram)"""
    try:
        import voice_profile
        p = voice_profile.pol()
    except Exception:  # noqa: BLE001
        p = "ครับ"
    if config.ANDROID_APP:
        return f"ที่เหลือดูบนจอได้เลย{p}"
    return f"รายละเอียดเพิ่มเติมส่งเข้า Telegram แล้ว{p}"


def speakable(text, limit=None):
    """คำตอบยาว (สรุปฟีด/เช็คเครื่อง/รายการ) → พูดแค่ช่วงแรกจนจบประโยค แล้วบอกว่าที่เหลืออยู่ไหน
    (เดิมคำสั่งด่วนพูดยาวได้ถึง 600 ตัวอักษร ~40 วิ ขณะที่คำตอบ AI ตัดที่ VOICE_MAX_SPEAK)"""
    limit = config.VOICE_MAX_SPEAK if limit is None else limit
    t = clean_for_speech(text or "", limit=2000)
    if not limit or len(t) <= limit:
        return t
    lines = [ln.strip() for ln in re.split(r"\n+", text or "") if clean_for_speech(ln)]
    out = ""
    for ln in lines:                                   # ตัดตามบรรทัด/ข้อ ไม่ตัดกลางประโยค
        c = clean_for_speech(ln)
        if out and len(out) + len(c) + 1 > limit:
            break
        out = f"{out} {c}".strip()
    if not out or len(out) > limit + 60:              # บรรทัดเดียวยาวมาก → ตัดที่ช่องว่างใกล้ limit
        cut = t.rfind(" ", 0, limit)
        out = t[:cut if cut > limit // 2 else limit]
    return f"{out.rstrip(' ,')} {more_note()}"


_clean = {"t": 0.0, "lock": threading.Lock()}


def _cleanup_old():
    """ลบไฟล์เสียงเก่าเกิน 10 นาที (ทำนาทีละครั้ง และกันชนกันหลาย thread)"""
    if time.time() - _clean["t"] < 60 or not _clean["lock"].acquire(blocking=False):
        return
    try:
        _clean["t"] = time.time()
        for old in os.listdir(config.DATA_DIR):
            if not old.startswith("tts_"):
                continue
            fp = os.path.join(config.DATA_DIR, old)
            try:
                if time.time() - os.path.getmtime(fp) > 600:
                    os.remove(fp)
            except OSError:
                pass
    finally:
        _clean["lock"].release()


def synthesize(text, path=None):
    """สร้างไฟล์ mp3 เสียงพูดภาษาไทย คืน path"""
    try:
        import voice_profile
        voice_profile.sync()                  # เสียงที่เลือกด้วย /voice (อาจเลือกจากอีกโปรเซส)
    except Exception:  # noqa: BLE001
        pass
    text = clean_for_speech(text)
    if not text:
        raise VoiceError("ไม่มีข้อความให้พูด")
    path = path or os.path.join(config.DATA_DIR, f"tts_{int(time.time() * 1000)}.mp3")
    _cleanup_old()
    if config.MOCK_PHONE:
        with open(path, "wb") as f:
            f.write(b"ID3mock")
        return path
    if config.TTS_ENGINE == "gemini" and config.GEMINI_API_KEY and time.time() >= _gem_err["until"]:
        try:
            _gemini_tts(text, path)        # เหมือนคนที่สุด (กำหนดน้ำเสียงได้) แต่ช้ากว่า
            if os.path.getsize(path) > 500:
                _tts_used("Gemini " + config.GEMINI_TTS_VOICE)
                return path
        except Exception as e:  # noqa: BLE001
            _gem_err["until"] = time.time() + (3600 if "429" in str(e) or "quota" in str(e).lower() else 300)
            print(f"⚠️ เสียง Gemini ใช้ไม่ได้ ใช้เสียง Microsoft แทนชั่วคราว: {str(e)[:120]}", flush=True)
    if _edge_err.get("fails", 0) >= 3 and time.time() - _edge_err.get("t", 0) > 600:
        _edge_err["fails"] = 0                       # ลองเสียงคนใหม่ทุก 10 นาที (เน็ตหลุดชั่วคราว)
    if config.TTS_ENGINE in ("edge", "gemini") and _edge_err.get("fails", 0) < 3:
        try:
            _edge_tts(text, path)          # เสียงคนจริง (Microsoft Neural) เป็นธรรมชาติกว่ามาก
            if os.path.getsize(path) > 500:
                _edge_err["fails"] = 0
                _tts_used("Microsoft " + config.TTS_VOICE.replace("th-TH-", "").replace("Neural", ""))
                return path
        except Exception as e:  # noqa: BLE001
            _edge_err["fails"] = _edge_err.get("fails", 0) + (3 if isinstance(e, ImportError) or "403" in str(e) else 1)
            _edge_err["t"] = time.time()
            _note_edge_error(e)
    # เสียง Microsoft ใช้ไม่ได้ → ใช้ Google ทันที (เร็ว ~0.3 วิ) ไม่ใช้ Gemini เพราะช้าหลายวินาทีต่อประโยค
    # ทำให้เสียงพูดตามหลังข้อความบนจอ (ใช้ Gemini เฉพาะเมื่อผู้ใช้เลือกเสียง Gemini เอง)
    try:
        audio = _google_tts(text)          # สำรอง: Google (เสียงแข็งกว่า)
        with open(path, "wb") as f:
            f.write(audio)
        _tts_used("Google (สำรอง)")
        return path
    except Exception:  # noqa: BLE001
        pass
    try:
        from gtts import gTTS
    except ImportError as e:
        raise VoiceError("ยังไม่ได้ติดตั้ง gTTS: pip install gTTS") from e
    gTTS(text=text, lang=config.TTS_LANG).save(path)
    return path


_edge_err = {"shown": False}
_gem_err = {"until": 0.0}
TTS_LAST = {"engine": "", "t": 0.0, "fallback_warned": False}


def _tts_used(engine):
    """จำว่าเสียงล่าสุดมาจากไหน — ถ้าตกไปใช้เสียงสำรอง บอกใน log ครั้งเดียว (เสียงสำรองจะฟังแข็ง/ช้ากว่า)"""
    if "สำรอง" in engine and not TTS_LAST["fallback_warned"]:
        TTS_LAST["fallback_warned"] = True
        print("⚠️ เสียง Microsoft ใช้ไม่ได้ตอนนี้ → พูดด้วยเสียงสำรองของ Google (ฟังแข็งกว่า) จะลองเสียงเดิมใหม่ใน 10 นาที",
              flush=True)
    elif "สำรอง" not in engine:
        TTS_LAST["fallback_warned"] = False
    TTS_LAST.update(engine=engine, t=time.time())


def _gemini_tts(text, path):
    """Gemini TTS: ได้ PCM 24kHz → WAV → แปลงเป็น mp3 ถ้ามี ffmpeg (ส่ง Telegram ได้)"""
    import base64
    import subprocess
    import wave
    import gemini_client
    body = {"contents": [{"parts": [{"text": f"{config.TTS_STYLE}: {text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": config.GEMINI_TTS_VOICE}}}}}
    data = gemini_client._post(config.GEMINI_TTS_MODEL, body, timeout=60)
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    inline = next((p["inlineData"] for p in parts if p.get("inlineData")), None)
    if not inline:
        raise VoiceError("Gemini ไม่ได้ส่งเสียงกลับมา")
    rate = int((re.search(r"rate=(\d+)", inline.get("mimeType", "")) or [0, 24000])[1])
    wav = path.rsplit(".", 1)[0] + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(base64.b64decode(inline["data"]))
    if path.endswith(".mp3") and shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "64k", path], timeout=30)
        if os.path.exists(path) and os.path.getsize(path) > 500:
            os.remove(wav)
            return
    os.replace(wav, path)                     # เล่นได้ทั้ง play-audio/termux-media-player


def _note_edge_error(e):
    if not _edge_err["shown"]:
        _edge_err["shown"] = True
        print(f"⚠️ เสียงแบบคน (edge-tts) ใช้ไม่ได้ → ใช้เสียงสำรอง: {str(e).splitlines()[0][:120]}", flush=True)


def _edge_tts(text, path):
    """Microsoft Edge Neural TTS (ฟรี) — th-TH-NiwatNeural (ชาย) / th-TH-PremwadeeNeural (หญิง)"""
    import edge_ws
    if config.ANDROID_APP:                    # แอป APK: ไม่มี aiohttp → ใช้ตัวที่เขียนเอง (+ รหัสยืนยัน v2 จาก edge-tts)
        edge_ws.synth(text, path, config.TTS_VOICE, config.TTS_RATE, config.TTS_PITCH)
        return
    try:
        import asyncio
        import edge_tts
        edge_tts.Communicate  # noqa: B018
    except (ImportError, AttributeError):
        edge_ws.synth(text, path, config.TTS_VOICE, config.TTS_RATE, config.TTS_PITCH)
        return

    async def go():
        c = edge_tts.Communicate(text, config.TTS_VOICE, rate=config.TTS_RATE, pitch=config.TTS_PITCH)
        with open(path, "wb") as f:
            async for chunk in c.stream():
                if chunk.get("type") == "audio":
                    f.write(chunk["data"])
    try:
        asyncio.run(go())
    except Exception as e:  # noqa: BLE001
        if "403" not in str(e):
            raise
        # edge-tts รุ่นเก่า (ก่อน 7.3) ใช้รหัสยืนยันแบบเก่า → Microsoft ปฏิเสธ: ลองตัวที่เขียนเอง
        print("⚠️ edge-tts รุ่นนี้เก่าไป (403) แนะนำ: pip install -U edge-tts", flush=True)
        edge_ws.synth(text, path, config.TTS_VOICE, config.TTS_RATE, config.TTS_PITCH)


_sessions = {}


def _session(name):
    """การเชื่อมต่อที่เปิดค้างไว้ใช้ซ้ำ (ประหยัดเวลาเชื่อมต่อ HTTPS ใหม่ ~0.3-0.5 วินาทีต่อครั้ง)"""
    s = _sessions.get(name)
    if s is None:
        s = _sessions[name] = requests.Session()
    return s


def _google_tts(text):
    """เรียก Google TTS ตรง (วิธีเดียวกับ gTTS) ผ่าน session ที่เปิดค้างไว้ ท่อนละไม่เกิน 100 ตัวอักษร"""
    import base64
    import json
    import urllib.parse
    s = _session("tts")
    s.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
                      "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    out = b""
    parts = [text[i:i + 100] for i in range(0, len(text), 100)]
    for part in parts:
        param = json.dumps([part, config.TTS_LANG, None, "null"], separators=(",", ":"))
        rpc = json.dumps([[["jQ1olc", param, None, "generic"]]], separators=(",", ":"))
        r = s.post("https://translate.google.com/_/TranslateWebserverUi/data/batchexecute",
                   data=f"f.req={urllib.parse.quote(rpc)}&", timeout=10)
        m = re.search(r'jQ1olc","\[\\"(.*?)\\"]', r.text)
        if r.status_code != 200 or not m:
            raise VoiceError(f"Google TTS {r.status_code}")
        out += base64.b64decode(m.group(1))
    return out


def warmup():
    """เปิดการเชื่อมต่อไว้ล่วงหน้า (ให้ครั้งแรกไม่ช้า) — เรียกใน thread แยก"""
    def _w():
        import voice_profile
        p = voice_profile.pol()
        for phrase in (p, f"ได้{p}", f"ได้เลย{p}", f"โอเค{p}", f"จัดให้{p}", f"รับทราบ{p}", f"แป๊บนึงนะ{p}", "ได้เลย",
                       f"ไว้คุยกันใหม่นะ{p}"):   # เตรียมเสียงตอบรับทุกคำไว้ (ตอบรับทันที ไม่ต้องรอสร้างเสียง)
            try:
                _cached(phrase)
            except Exception:  # noqa: BLE001
                pass
        if not config.GROQ_API_KEY:
            return
        for fn in (lambda: _google_tts("ครับ"),
                   lambda: _session("groq").get("https://api.groq.com/openai/v1/models",
                                                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                                                timeout=10)):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
    if not config.MOCK_PHONE:
        threading.Thread(target=_w, daemon=True).start()


def _player():
    if config.ANDROID_APP:
        return "app"
    if shutil.which("play-audio"):
        return "play-audio"
    if shutil.which("termux-media-player"):
        return "termux-media-player"
    return None


def play(path, wait=True, mute_mic=True):
    """เล่นไฟล์เสียงออกลำโพงของเครื่อง
    mute_mic=True: ไมค์หยุดฟังระหว่างเล่น (กันได้ยินเสียงตัวเอง)
    mute_mic=False: ไมค์ฟังต่อ (ใช้กับคำสั้นๆ อย่าง "ครับ" → ผู้ใช้พูดต่อได้ทันที)"""
    import audio_stream
    if config.MOCK_PHONE:
        return
    if mute_mic:
        audio_stream.mark_speaking(True)
    try:
        _play(path, wait)
    finally:
        if mute_mic:
            audio_stream.mark_speaking(False)


def ack(text=None):
    """ตอบรับสั้นๆ แบบไม่บล็อก และไม่ปิดไมค์ → ผู้ใช้พูดคำสั่งต่อได้เลยไม่ต้องรอ"""
    if text is None:
        import voice_profile
        text = voice_profile.pol()

    def _go():
        try:
            play(_cached(text), mute_mic=False)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_go, daemon=True).start()


_current = {"proc": None}


def stop_playing():
    """หยุดเสียงที่กำลังพูดอยู่ทันที (ใช้ตอนผู้ใช้พูดแทรก)"""
    _current["cancel_at"] = time.time()
    proc = _current.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    if _player() == "termux-media-player":
        _api(["termux-media-player", "stop"])
    elif _player() == "app":
        import android_shim
        android_shim.bridge().stopPlay()


def _play(path, wait=True):
    p = _player()
    if p == "app":
        import android_shim
        if not path or not os.path.exists(path) or os.path.getsize(path) < 200:
            print(f"🔇 ไม่มีไฟล์เสียง ข้ามการพูด: {path}", flush=True)
            return
        android_shim.bridge().play(path, bool(wait))
        return
    if p == "play-audio":
        proc = subprocess.Popen(["play-audio", path])
        _current["proc"] = proc
        if wait:
            proc.wait(timeout=180)
    elif p == "termux-media-player":
        _api(["termux-media-player", "play", path])
        if wait:
            time.sleep(0.8)
            for _ in range(360):
                info = _api(["termux-media-player", "info"],
                                      text=True, timeout=10).stdout
                if "Playing" not in info:
                    break
                time.sleep(0.5)
    else:
        raise VoiceError("ไม่มีโปรแกรมเล่นเสียง: pkg install play-audio")


def _chunks(text, first=80, size=220):
    """แบ่งข้อความเป็นท่อนสั้นๆ (ท่อนแรกสั้นสุด จะได้เริ่มพูดเร็ว)"""
    words, out, cur = text.split(" "), [], ""
    for w in words:
        limit = first if not out else size
        if cur and len(cur) + len(w) + 1 > limit:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def _cached(text):
    """ประโยคสั้นที่ใช้บ่อย (เช่น "ครับ", "ไว้คุยกันใหม่นะครับ") เก็บไฟล์ไว้ใช้ซ้ำ ไม่ต้องสร้างใหม่"""
    import hashlib
    d = os.path.join(config.DATA_DIR, "tts_cache")
    os.makedirs(d, exist_ok=True)
    key = f"{config.TTS_ENGINE}|{config.TTS_VOICE}|{config.GEMINI_TTS_VOICE}|{config.TTS_RATE}|{config.TTS_PITCH}|{text}"
    path = os.path.join(d, hashlib.md5(key.encode()).hexdigest() + ".mp3")
    if not os.path.exists(path):
        synthesize(text, path)
    return path


def say(text, wait=True):
    """พูดข้อความออกลำโพงของเครื่อง: สร้างเสียงท่อนถัดไปไปพร้อมกับเล่นท่อนปัจจุบัน → เริ่มพูดเร็วขึ้น"""
    if not wait:
        import threading
        threading.Thread(target=say, args=(text, True), daemon=True).start()
        return None
    import polite
    text = clean_for_speech(polite.fix(text))
    if not text:
        return None
    if len(text) <= 40:
        play(_cached(text))
        return None
    from concurrent.futures import ThreadPoolExecutor
    parts = _chunks(text)
    started = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(synthesize, p) for p in parts]
        for fut in futures:
            path = fut.result()
            try:
                if _current.get("cancel_at", 0) >= started:   # ถูกสั่งหยุด (ผู้ใช้พูดแทรก)
                    continue
                play(path)
            finally:
                _remove(path)
    return None


class Speaker:
    """รับข้อความทีละนิด (จาก AI ที่กำลังพิมพ์) → ตัดเป็นท่อน → สร้างเสียงล่วงหน้า → พูดต่อกันทันที"""

    # ตัดเฉพาะจบประโยคจริง (ตัดสั้นเกินไป → แต่ละท่อนลงเสียงท้ายยาวเหมือนจบประโยค ฟังลากยาวเป็นช่วงๆ)
    ENDS = (".", "!", "?", "\n", "ครับ ", "ค่ะ ")
    MIN_CUT = 25                    # ท่อนสั้นกว่านี้ อย่าเพิ่งตัด รวมกับประโยคถัดไป

    def __init__(self, max_chars=0):
        import queue
        from concurrent.futures import ThreadPoolExecutor
        self.max_chars = max_chars      # พูดแค่ช่วงแรก ที่เหลือดูใน Telegram (0 = พูดทั้งหมด)
        self.chars = 0
        self.truncated = False
        self.buf = ""
        self.count = 0
        self.spoken = []
        self.stopped = False
        self.first_play = 0.0
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.q = queue.Queue()
        self.t = threading.Thread(target=self._player, daemon=True)
        self.t.start()

    def feed(self, delta):
        self.buf += delta
        while True:
            limit = 70 if self.count == 0 else 200
            cut = -1
            for e in self.ENDS:
                i = self.buf.find(e, self.MIN_CUT if self.count else 4)
                if i >= 0 and (cut < 0 or i < cut):
                    cut = i + len(e)
            if cut > limit + 40:
                cut = -1
            if cut < 0 and len(self.buf) > limit:
                sp = self.buf.rfind(" ", 0, limit + 40)
                cut = sp + 1 if sp > 20 else -1
            if cut <= 0:
                break
            self._emit(self.buf[:cut])
            self.buf = self.buf[cut:]

    def busy(self):
        """ยังมีเสียงรอพูดหรือกำลังพูดอยู่"""
        return self.t.is_alive() and not self.stopped

    def stop(self):
        """ผู้ใช้พูดแทรก: หยุดพูดทันที ทิ้งประโยคที่เหลือ"""
        self.stopped = True
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except Exception:  # noqa: BLE001
                break
        self.q.put(None)
        stop_playing()

    def _emit(self, text):
        if self.stopped or self.truncated:
            return
        text = clean_for_speech(text)
        if len(text) < 2:
            return
        if self.max_chars and self.chars >= self.max_chars:
            self.truncated = True
            text = more_note()
        self.chars += len(text)
        self.count += 1
        self.spoken.append(text)
        fut = self.pool.submit(_cached if len(text) <= 12 else synthesize, text)
        self.q.put((fut, len(text) > 12))

    def _player(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            fut, temp = item
            if self.stopped:
                continue
            try:
                path = fut.result()
                if not self.stopped:
                    if not self.first_play:
                        self.first_play = time.time()
                    play(path)
                if temp:
                    _remove(path)
            except Exception:  # noqa: BLE001
                pass

    def close(self):
        """ส่งท่อนสุดท้ายเข้าคิว (ไม่รอให้พูดจบ)"""
        self._emit(self.buf)
        self.buf = ""
        self.q.put(None)

    def finish(self):
        """พูดส่วนที่เหลือ แล้วรอจนพูดจบ"""
        self.close()
        self.t.join(timeout=300)
        self.pool.shutdown(wait=False)


def normalize_pcm(pcm, target_peak=22000, max_gain=None):
    """ขยายเสียงที่เบาให้ดังพอ (ไมค์ MatePad ผ่าน PulseAudio ได้เสียงเบามาก ทำให้ฟังผิดบ่อย)
    คืน (pcm ใหม่, gain ที่ใช้, peak เดิม)"""
    import array
    a = array.array("h", pcm)
    if not a:
        return pcm, 1.0, 0
    # ใช้ค่าสูงช่วง 99.5% แทนค่าสูงสุด (กันเสียงกระแทกครั้งเดียวทำให้ขยายไม่ได้)
    srt = sorted(abs(x) for x in a[::4])
    peak = srt[int(len(srt) * 0.995)] if srt else 0
    if peak < 1:
        return pcm, 1.0, peak
    if max_gain is None:                       # ไมค์ของแอป (AudioRecord) ดังพอแล้ว → ขยายน้อย กันขยายเสียงรบกวนจนถอดผิด
        max_gain = 6.0 if config.ANDROID_APP else 50.0
    gain = min(max_gain, target_peak / peak)
    if gain <= 1.1:
        return pcm, 1.0, peak
    out = array.array("h", (max(-32767, min(32767, int(x * gain))) for x in a))
    return out.tobytes(), gain, peak


def _highpass_np(pcm, k, block=256):
    """กรองเสียงต่ำแบบเดียวกับ highpass แต่คำนวณทีละก้อนด้วย numpy
    y[n] = k·y[n-1] + k·(x[n]-x[n-1])  →  ในก้อนหนึ่ง y = k^i·(y0 + Σ k^(1-j)·dx[j])"""
    import numpy as np
    x = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype="<i2").astype(np.float64)
    if not len(x):
        return pcm
    dx = np.diff(x, prepend=0.0)
    out = np.empty_like(x)
    i = np.arange(1, block + 1, dtype=np.float64)
    pw = k ** i                                   # k^1 .. k^block
    inv = k ** (1 - i)                            # k^(1-j)
    y0 = 0.0
    for s in range(0, len(x), block):
        d = dx[s:s + block]
        m = len(d)
        y = pw[:m] * (y0 + np.cumsum(inv[:m] * d))
        out[s:s + m] = y
        y0 = y[-1]
    return np.clip(out, -32767, 32767).astype("<i2").tobytes()


def highpass(pcm, cutoff=120):
    """ตัดเสียงทุ้มต่ำ (เสียงพัดลม/แอร์/เคาะโต๊ะ) ให้เสียงพูดชัดขึ้น"""
    import array
    import math
    a = array.array("h", pcm)
    if not a:
        return pcm
    rc = 1.0 / (2 * math.pi * cutoff)
    dt = 1.0 / 16000
    k = rc / (rc + dt)
    try:
        return _highpass_np(pcm, k)            # เร็วกว่าลูปทีละตัวอย่างหลายสิบเท่า (ประโยค 5 วิ = 80,000 ตัวอย่าง)
    except ImportError:
        pass
    out = array.array("h", bytes(len(pcm)))
    py = px = 0.0
    for i, x in enumerate(a):
        y = k * (py + x - px)
        px, py = x, y
        out[i] = max(-32767, min(32767, int(y)))
    return out.tobytes()


def _vocab():
    """คำเฉพาะช่วยถอดเสียง: ค่าตั้งต้น + ชื่อคน/ห้องแชทที่บอทเคยเห็น (จำเองจากการใช้งาน)"""
    try:
        import skills
        names = skills.vocab()
    except Exception:  # noqa: BLE001
        names = ""
    return ", ".join(x for x in (config.STT_VOCAB, names) if x)


def _stt_prompt(max_chars=60):
    """คำใบ้ให้ Whisper: คำปลุก + ชื่อคนที่คุยล่าสุด (ทั้งชื่อ ไม่ตัดกลางชื่อ · สั้น — ชื่อเยอะเกิน Whisper ชอบท่องออกมาเอง)"""
    names = []
    try:
        import skills
        used = 0
        for nm in skills.known_names():
            nm = (nm or "").strip()
            if not nm or nm in names:
                continue
            if used + len(nm) > max_chars:
                break
            names.append(nm)
            used += len(nm) + 2
    except Exception:  # noqa: BLE001
        pass
    return ", ".join([x for x in [config.STT_PROMPT] + names if x])


def use_gemini_stt():
    return config.STT_ENGINE in ("gemini", "auto") and bool(config.GEMINI_API_KEY) and not config.MOCK_PHONE


# คำที่บอกว่าผู้ใช้กำลัง "บอกข้อความ" ให้พิมพ์/ส่ง → ต้องถอดให้ตรงทุกคำ
_DICTATION = re.compile(r"(พิมพ์|บอก|ตอบ|ส่ง|เขียน|โพสต์|คอมเมนต์|คอมเม้น|แคปชั่น|แคปชัน|ข้อความ|แชท|แชต|"
                        r"ไลน์|line|ig|อินสตา|เฟส|messenger|caption|comment|type)", re.I)


def needs_accurate(text):
    """ข้อความนี้ควรถอดซ้ำแบบแม่น (Gemini) ไหม"""
    if config.STT_ENGINE == "gemini":
        return True
    if config.STT_ENGINE != "auto" or not text:
        return False
    return bool(_DICTATION.search(text)) or bool(re.search(r"[A-Za-z]{3,}", text))


def transcribe_accurate(path_or_wav, mime="audio/wav"):
    """ถอดเสียงแบบแม่น (Gemini) ถ้าใช้ไม่ได้ค่อยใช้ Groq"""
    if use_gemini_stt() and time.time() > _last.get("gem_stt_off", 0):
        try:
            import gemini_client
            data = path_or_wav
            if isinstance(path_or_wav, str):
                with open(path_or_wav, "rb") as f:
                    data = f.read()
            t0 = time.time()
            text = fix_mojibake(gemini_client.transcribe(data, mime=mime, vocab=_vocab()))
            _last["engine"], _last["stt_time"] = "Gemini", time.time() - t0
            if text and is_hallucination(text, f"{config.STT_PROMPT}, {_vocab()}"):   # ตรวจเหมือนตัวถอดเสียงอื่น
                print(f"🗑️ Gemini ถอดได้ข้อความแต่งเอง/ท่องรายชื่อ → ทิ้ง: {text[:80]}", flush=True)
                _last["why"] = "ข้อความแต่งเอง/ภาษาแปลก"
                return ""
            return text
        except Exception as e:  # noqa: BLE001
            _last["gem_stt_off"] = time.time() + 3600      # พักใช้ Gemini 1 ชม. ไม่ให้ทุกประโยคเสียเวลาลองซ้ำ
            print(f"⚠️ ถอดเสียงด้วย Gemini ไม่ได้ → ใช้ Groq (พัก Gemini 1 ชม.): {str(e)[:120]}", flush=True)
    if isinstance(path_or_wav, str):
        _last["engine"] = "Groq"
        return transcribe(path_or_wav)
    raise VoiceError("ไม่มีไฟล์เสียง")


def transcribe_pcm(pcm, accurate=False, wake=False):
    """accurate=True: ใช้ Gemini (แม่นกับไทยปนอังกฤษ/ชื่อเฉพาะ ช้ากว่า ~1 วินาที) / False: Groq (เร็ว)"""
    import audio_stream
    pcm = highpass(pcm)
    _last["sec"] = round(len(pcm) / 32000, 1)
    pcm, gain, peak = normalize_pcm(pcm)
    _last["gain"], _last["peak"] = gain, peak
    path = os.path.join(config.DATA_DIR, "utterance.wav")
    audio_stream.write_wav(pcm, path)
    t0 = time.time()
    _last["engine"] = "Groq"
    text = transcribe(path, wake=wake)            # เร็ว (~0.5 วิ)
    if _last.get("engine") in ("NanoGPT", "Cloudflare"):
        accurate = False                          # NanoGPT = Whisper ตัวใหญ่อยู่แล้ว ไม่ต้องถอดซ้ำ
    if accurate and use_gemini_stt() and needs_accurate(text):
        better = transcribe_accurate(path)        # แม่น (เฉพาะตอนบอกข้อความให้พิมพ์/ส่ง)
        if better:
            _last["engine"] = "Groq+Gemini"
            text = better
    _last["stt_time"] = time.time() - t0
    return text


_last = {"gain": 1.0, "peak": 0, "engine": "Groq", "stt_time": 0.0}


def beep(freq=880, ms=150):
    """เสียงติ๊ดบอกว่า "เริ่มฟังแล้ว" (แท็บเล็ตไม่มีระบบสั่น)"""
    path = os.path.join(config.DATA_DIR, f"beep_{freq}.wav")
    if not os.path.exists(path):
        rate = 16000
        n = int(rate * ms / 1000)
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            fade = max(1, n // 10)
            frames = b"".join(
                struct.pack("<h", int(12000 * min(1, i / fade, (n - i) / fade) *
                                      math.sin(2 * math.pi * freq * i / rate)))
                for i in range(n))
            w.writeframes(frames)
    try:
        play(path)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- อัดเสียง

def record(seconds, path=None):
    """อัดเสียงจากไมค์ของเครื่อง คืน path ของไฟล์ m4a"""
    path = path or os.path.join(config.DATA_DIR, "listen.m4a")
    if config.MOCK_PHONE:
        with open(path, "wb") as f:
            f.write(b"mock")
        return path
    _remove(path)
    out = _api(["termux-microphone-record", "-f", path, "-l", str(int(seconds))],
                         capture_output=True, text=True, timeout=20).stdout
    if "error" in out.lower():
        raise VoiceError(f"อัดเสียงไม่ได้: {out.strip()} (ให้สิทธิ์ไมโครโฟนกับ Termux:API)")
    time.sleep(seconds + 0.3)
    _api(["termux-microphone-record", "-q"])
    # รอให้เขียนไฟล์เสร็จ
    last = -1
    for _ in range(20):
        size = os.path.getsize(path) if os.path.exists(path) else 0
        if size and size == last:
            break
        last = size
        time.sleep(0.25)
    if not os.path.exists(path) or os.path.getsize(path) < 500:
        raise VoiceError("ไฟล์เสียงว่างเปล่า ไมค์อาจถูกบล็อกตอนปิดจอ")
    return path


def loudness_db(path):
    """ความดังสูงสุดของไฟล์ (dB) ใช้ ffmpeg ถ้ามี — คืน None ถ้าตรวจไม่ได้"""
    if config.MOCK_PHONE or not shutil.which("ffmpeg"):
        return None
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True, timeout=30).stderr
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", out)
    return float(m.group(1)) if m else None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def mic_report():
    """สรุปผลถอดเสียงล่าสุด → ใช้ดูว่าไมค์พลาดเพราะอะไร (สั่ง "รายงานไมค์")"""
    if not HISTORY:
        return "🎤 ยังไม่มีข้อมูลการฟัง — พูดสั่งงานสัก 3-5 ครั้งก่อน แล้วสั่ง \"รายงานไมค์\" ใหม่"
    rows = list(HISTORY)[-15:]
    kept = sum(1 for r in rows if r["kept"])
    lines = [f"🎤 รายงานไมค์ ({len(rows)} ครั้งล่าสุด · ใช้ได้ {kept} · ทิ้ง {len(rows) - kept})",
             f"ตัวถอดเสียง: {stt_engine() or 'ไม่มี'} · ภาษา th"]
    for r in rows:
        conf = "" if r["lp"] is None else f" ความมั่นใจ {r['lp']}"
        lines.append(f"{'✅' if r['kept'] else '🔇'} {r['t']} [{r['engine']}] {r.get('sec') or '?'}วิ"
                     f"{conf} — {r['text'] or '(ว่าง)'}" + (f" ({r['why']})" if r["why"] else ""))
    lows = sum(1 for r in rows if (r.get("peak") or 0) and r["peak"] < 1500)
    tips = []
    if lows >= 3:
        tips.append("เสียงเบามากหลายครั้ง → พูดใกล้แท็บเล็ตขึ้น หรือ ⚙️ ความเข้มงวดเป็น \"ไว\"")
    if sum(1 for r in rows if "แปลก" in r["why"]) >= 3:
        tips.append("ถอดเป็นภาษาแปลกบ่อย → เสียงรอบข้างดัง/อยู่ไกล หรือลองเปลี่ยนตัวถอดเสียงเป็น Groq")
    if not os.path.exists(os.path.join(config.DATA_DIR, "voiceprint.json")) and config.SPEAKER_VERIFY:
        tips.append("ยังไม่ได้สอนเสียงเจ้าของ → สั่ง \"สอนเสียงฉัน\" จะช่วยไม่ให้ตอบเสียงทีวี/คนอื่น")
    if tips:
        lines.append("💡 " + " · ".join(tips))
    return "\n".join(lines)


def cf_check():
    """ตรวจคีย์ Cloudflare ทีละขั้น แล้วบอกว่าพลาดตรงไหน (สั่ง "ทดสอบ cloudflare")"""
    import io
    import wave as _wave
    acc, tok = config.CF_ACCOUNT_ID, config.CF_API_TOKEN
    if not acc or not tok:
        return "☁️ ยังไม่ได้ใส่ Account ID / API Token ของ Cloudflare (⚙️ → 🎤 เสียง → ✏️ แก้คีย์ Cloudflare)"
    out = [f"☁️ ตรวจ Cloudflare — Account ID ยาว {len(acc)} ตัว (ต้องเป็น 32), Token ยาว {len(tok)} ตัว"]
    if len(acc) != 32 or not re.fullmatch(r"[0-9a-fA-F]{32}", acc):
        out.append("❌ Account ID ไม่ถูกรูปแบบ — ต้องเป็นตัวอักษร a-f/ตัวเลข 32 ตัว (คัดลอกจากหน้า Workers AI → Use REST API)")
    if tok != tok.strip() or " " in tok:
        out.append("❌ Token มีช่องว่างติดมา — ลบช่องว่างออกแล้วใส่ใหม่")
    h = {"Authorization": f"Bearer {tok.strip()}"}
    ok_tok = False
    for url in (f"https://api.cloudflare.com/client/v4/accounts/{acc}/tokens/verify",
                "https://api.cloudflare.com/client/v4/user/tokens/verify"):
        try:
            r = _session("cf").get(url, headers=h, timeout=15)
            if r.status_code == 200 and '"active"' in r.text:
                ok_tok = True
                break
        except Exception:  # noqa: BLE001
            continue
    out.append("✅ Token ใช้งานได้" if ok_tok else "❌ Token ไม่ถูกต้อง/หมดอายุ/ถูกลบ — สร้างใหม่จากหน้า Workers AI → Use REST API")
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    import base64
    try:
        r = _session("cf").post(f"https://api.cloudflare.com/client/v4/accounts/{acc.strip()}/ai/run/{config.CF_STT_MODEL}",
                                headers=h, json={"audio": base64.b64encode(buf.getvalue()).decode()}, timeout=30)
        if r.status_code == 200:
            out.append("✅ เรียกถอดเสียง Whisper ได้แล้ว — ใช้งานได้!")
            _off.pop("cloudflare", None)
        else:
            msg = re.sub(r"\s+", " ", r.text)[:200]
            hint = ""
            if r.status_code in (401, 403):
                hint = " → token ไม่มีสิทธิ์ Workers AI หรือ Account ID ไม่ตรงกับบัญชีของ token"
            elif r.status_code == 404:
                hint = " → Account ID ผิด หรือชื่อรุ่นถอดเสียงไม่มี"
            out.append(f"❌ เรียกถอดเสียงไม่ได้ ({r.status_code}){hint}\n   {msg}")
    except Exception as e:  # noqa: BLE001
        out.append(f"❌ เชื่อมต่อ Cloudflare ไม่ได้: {str(e)[:120]}")
    return "\n".join(out)


def voice_test():
    """"ทดสอบเสียง": สร้างเสียงตัวอย่าง บอกว่าใช้เสียงอะไร/ช้าเร็วแค่ไหน + ตัวถอดเสียงที่ใช้อยู่"""
    try:
        import voice_profile
        voice_profile.sync()
        sample = voice_profile.sample()
    except Exception:  # noqa: BLE001
        sample = "สวัสดีครับ นี่คือเสียงทดสอบ"
    lines = ["🔊 ทดสอบเสียง"]
    t0 = time.time()
    try:
        path = synthesize(sample)
        ms = int((time.time() - t0) * 1000)
        lines.append(f"• เสียงที่ได้ยิน: {TTS_LAST.get('engine') or '?'} (สร้างเสียง {ms} มิลลิวินาที)")
        play(path)
        _remove(path)
    except Exception as e:  # noqa: BLE001
        lines.append(f"• สร้างเสียงไม่ได้: {str(e)[:120]}")
    lines.append(f"• ตั้งไว้: {config.TTS_ENGINE} / {config.TTS_VOICE} / ความเร็ว {config.TTS_RATE}")
    try:
        import edge_ws
        lines.append(f"• รหัสยืนยันเสียง Microsoft: {edge_ws.token_kind()}")
    except Exception:  # noqa: BLE001
        pass
    if "สำรอง" in (TTS_LAST.get("engine") or ""):
        lines.append("⚠️ ตอนนี้เสียง Microsoft ใช้ไม่ได้ เลยใช้เสียงสำรอง (ฟังแข็ง/ช้ากว่า) — "
                     "ลองใหม่ใน 10 นาที หรือเช็คเน็ต/เวลาเครื่องให้ตรง")
    chain = stt_chain()
    names = {"groq": "Groq (Whisper large-v3 แม่นสุด)", "cloudflare": "Cloudflare (Whisper turbo ฟรี)",
             "nano": "NanoGPT (Whisper large-v3 จ่ายตามใช้)"}
    lines.append("• ถอดเสียงด้วย: " + (" → ".join(names.get(c, c) for c in chain) or "ยังไม่มี ⚠️"))
    if chain and chain[0] == "cloudflare" and config.GROQ_API_KEY:
        lines.append("💡 มีคีย์ Groq อยู่แล้ว เลือก Groq เป็นตัวหลักจะถอดภาษาไทยแม่นกว่า (⚙️ → 🎤 เสียง)")
    elif chain and chain[0] == "cloudflare":
        lines.append("💡 ถ้าถอดผิดบ่อย ใส่คีย์ Groq (ฟรี) จะแม่นกว่า Cloudflare")
    return "\n".join(lines)
