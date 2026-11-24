"""เลือกเสียง/บุคลิกผู้ช่วย: /voice (มีปุ่ม) — มีผลทั้งบอทและโหมดเสียง (คนละโปรเซส → ไฟล์ voice.json) และจำใน .env"""
import json
import os
import random

import config

PRESETS = {
    "male": {"label": "👨 ชาย นุ่มๆ เป็นกันเอง (แนะนำ)", "TTS_ENGINE": "edge", "TTS_VOICE": "th-TH-NiwatNeural",
             "TTS_RATE": "+5%", "TTS_PITCH": "-2Hz", "BOT_GENDER": "male"},
    "female": {"label": "👩 หญิง สดใส อบอุ่น", "TTS_ENGINE": "edge", "TTS_VOICE": "th-TH-PremwadeeNeural",
               "TTS_RATE": "+5%", "TTS_PITCH": "+0Hz", "BOT_GENDER": "female"},
    "male_slow": {"label": "👨 ชาย ใจเย็น พูดช้าลง", "TTS_ENGINE": "edge", "TTS_VOICE": "th-TH-NiwatNeural",
                  "TTS_RATE": "-5%", "TTS_PITCH": "-4Hz", "BOT_GENDER": "male"},
    "gemini_male": {"label": "✨ Gemini ชาย (เหมือนคนที่สุด ช้ากว่า)", "TTS_ENGINE": "gemini",
                    "GEMINI_TTS_VOICE": "Puck", "BOT_GENDER": "male"},
    "gemini_female": {"label": "✨ Gemini หญิง (เหมือนคนที่สุด ช้ากว่า)", "TTS_ENGINE": "gemini",
                      "GEMINI_TTS_VOICE": "Aoede", "BOT_GENDER": "female"},
}
_KEYS = ("TTS_ENGINE", "TTS_VOICE", "TTS_RATE", "TTS_PITCH", "GEMINI_TTS_VOICE", "BOT_GENDER")
_last = {"mtime": 0.0}


def _file():
    return os.path.join(config.DATA_DIR, "voice.json")


def sync():
    """โหลดเสียงที่เลือกไว้ (อีกโปรเซสอาจเพิ่งเปลี่ยน) — แค่ stat ไฟล์ ถูกมาก"""
    try:
        mt = os.path.getmtime(_file())
    except OSError:
        return
    if mt == _last["mtime"]:
        return
    _last["mtime"] = mt
    env = os.environ.get("BOT_ENV_FILE") or os.path.join(config.BASE_DIR, ".env")
    try:
        if os.path.getmtime(env) > mt:        # ตั้งเสียงใหม่ในหน้าตั้งค่าแอปทีหลัง → ค่าในแอปชนะ ลบไฟล์เก่าทิ้ง
            os.remove(_file())
            return
    except OSError:
        pass
    try:
        d = json.load(open(_file(), encoding="utf-8"))
    except (OSError, ValueError):
        return
    for k in _KEYS:
        if k in d:
            setattr(config, k, d[k])


def apply(name):
    p = PRESETS.get(name)
    if not p:
        return None
    d = {k: p[k] for k in _KEYS if k in p}
    if d.get("TTS_ENGINE") == "gemini" and not config.GEMINI_API_KEY:
        return "ใช้เสียง Gemini ต้องมี GEMINI_API_KEY ก่อน (รัน bash set_key.sh)"
    for k, v in d.items():
        setattr(config, k, v)
    with open(_file(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    _last["mtime"] = os.path.getmtime(_file())
    _save_env(d)
    return f"✅ เปลี่ยนเป็น {p['label']} แล้ว"


def _save_env(d):
    env = os.path.join(config.BASE_DIR, ".env")
    try:
        lines = open(env, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    lines = [l for l in lines if l.split("=", 1)[0] not in d] + [f"{k}={v}" for k, v in d.items()]
    with open(env, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def current_label():
    for p in PRESETS.values():
        if p["TTS_ENGINE"] == config.TTS_ENGINE and p.get("BOT_GENDER") == config.BOT_GENDER and (
                p.get("TTS_VOICE") == config.TTS_VOICE if p["TTS_ENGINE"] == "edge"
                else p.get("GEMINI_TTS_VOICE") == config.GEMINI_TTS_VOICE) and \
                (p["TTS_ENGINE"] != "edge" or p.get("TTS_RATE") == config.TTS_RATE):
            return p["label"]
    return f"{config.TTS_ENGINE} / {config.TTS_VOICE} ({config.TTS_RATE})"


def keyboard():
    return {"inline_keyboard": [[{"text": p["label"], "callback_data": f"voice:{n}"}] for n, p in PRESETS.items()]}


# ---------------------------------------------------------------- คำลงท้าย/คำตอบรับ ตามเพศ

def pol():
    if os.environ.get("POLITE", "ครับ").strip() == "ครับ":
        return "ครับ"                          # ผู้ใช้ตั้งให้ลงท้าย "ครับ" อย่างเดียว (ค่าเริ่มต้น)
    return "ค่ะ" if config.BOT_GENDER == "female" else "ครับ"


def me():
    return "ฉัน" if config.BOT_GENDER == "female" else "ผม"


_ACKS = ("ได้เลย{p}", "โอเค{p}", "จัดให้{p}", "ได้{p}", "รับทราบ{p}", "แป๊บนึงนะ{p}", "ได้เลย")


def ack_word():
    """คำตอบรับที่ไม่ซ้ำกันทุกครั้ง (ฟังเป็นคนกว่า 'ได้ครับ' ตลอด)"""
    return random.choice(_ACKS).format(p=pol())


def sample():
    return (f"สวัสดี{pol()} นี่เสียงใหม่ของ{me()}เอง ฟังเป็นยังไงบ้าง "
            f"ถ้ายังไม่ชอบ ลองเลือกเสียงอื่นดูได้นะ{pol()}")
