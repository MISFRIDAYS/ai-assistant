"""สลับสมอง AI ฉุกเฉิน: /ai (มีปุ่มกด) หรือพูด/พิมพ์ "สลับไปใช้ claude"
มีผลทันทีทั้งบอท Telegram และโหมดเสียง (คนละโปรเซส → สื่อสารผ่านไฟล์) และจำไว้ใน .env
"""
import os
import re

import config

NAMES = {
    "ollama": "🖥️ คอมที่บ้าน (Ollama) — ฟรี",
    "claude": "🧠 Claude — ฉลาดสุด (เสียเงิน)",
    "gemini": "✨ Gemini — ฟรีตามโควตา",
    "groq": "⚡ Groq — ฟรี เร็ว (เครื่องมือจำกัด)",
    "cloud": "☁️ Cloud AI — รายเดือน (Qwen3.5 / Kimi K3)",
}
ALIASES = {
    "claude": "claude", "คลอด": "claude", "คล็อด": "claude", "เคลาด์": "claude", "แอนโทรปิก": "claude",
    "gemini": "gemini", "เจมิไน": "gemini", "เจมินี่": "gemini", "เจมินาย": "gemini", "google": "gemini",
    "groq": "groq", "กร็อก": "groq", "กร๊อก": "groq", "โกรก": "groq",
    "ollama": "ollama", "โอลามา": "ollama", "โอลาม่า": "ollama", "คอม": "ollama", "คอมพิวเตอร์": "ollama",
    "ฟรี": "ollama", "local": "ollama",
    "cloud": "cloud", "คลาวด์": "cloud", "chutes": "cloud", "ชูท": "cloud", "qwen": "cloud", "คิวเวน": "cloud",
    "kimi": "cloud", "คิมิ": "cloud", "รายเดือน": "cloud",
}
_last = {"mtime": 0.0}


def _file():
    return os.path.join(config.DATA_DIR, "provider.txt")


def sync():
    """อ่านค่าที่สลับไว้ (อีกโปรเซสอาจเพิ่งสลับ) — เรียกก่อนคุยทุกครั้ง ถูกมาก (แค่ stat ไฟล์)"""
    try:
        mt = os.path.getmtime(_file())
    except OSError:
        return config.LLM_PROVIDER
    if mt != _last["mtime"]:
        _last["mtime"] = mt
        try:
            name = open(_file(), encoding="utf-8").read().strip()
        except OSError:
            name = ""
        if name in NAMES and name != config.LLM_PROVIDER:
            config.LLM_PROVIDER = name
            _reset_fallback()
    return config.LLM_PROVIDER


def _reset_fallback():
    try:
        import agent
        agent._fallback_until[0] = 0.0
    except Exception:  # noqa: BLE001
        pass


def ready(name):
    """(ใช้ได้ไหม, เหตุผล)"""
    if name == "claude":
        return bool(config.ANTHROPIC_API_KEY), "ยังไม่ได้ใส่ ANTHROPIC_API_KEY ใน .env"
    if name == "gemini":
        return bool(config.GEMINI_API_KEY), "ยังไม่ได้ใส่ GEMINI_API_KEY (รัน bash set_key.sh)"
    if name == "groq":
        return bool(config.GROQ_API_KEY), "ยังไม่ได้ใส่ GROQ_API_KEY (รัน bash set_groq.sh)"
    if name == "cloud":
        return bool(config.CLOUD_API_KEY), "ยังไม่ได้ใส่คีย์ Cloud AI (⚙️ ตั้งค่า → ☁️ Cloud AI)"
    if name == "ollama":
        if not config.OLLAMA_URL:
            return False, "ยังไม่ได้ตั้งคอม (รัน bash set_ollama.sh)"
        import ollama_client
        ok, why = ollama_client.ping(timeout=3)
        return ok, why
    return False, "ไม่รู้จัก"


def _save_env(name):
    env = os.environ.get("BOT_ENV_FILE") or os.path.join(config.BASE_DIR, ".env")   # แอป APK เก็บ .env แยก
    try:
        lines = open(env, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    lines = [l for l in lines if not l.startswith("LLM_PROVIDER=")] + [f"LLM_PROVIDER={name}"]
    with open(env, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def switch(name):
    name = ALIASES.get((name or "").strip().lower(), (name or "").strip().lower())
    if name not in NAMES:
        return f"ไม่รู้จัก '{name}' — เลือกได้: " + ", ".join(NAMES)
    ok, why = ready(name)
    if not ok:
        return f"สลับไป {name} ไม่ได้: {why}"
    with open(_file(), "w", encoding="utf-8") as f:
        f.write(name)
    _last["mtime"] = os.path.getmtime(_file())
    config.LLM_PROVIDER = name
    _reset_fallback()
    try:
        _save_env(name)
    except OSError:
        pass
    return f"✅ สลับไปใช้ {NAMES[name]} แล้ว"


def status():
    cur = sync()
    lines = [f"สมองที่ใช้อยู่: {NAMES.get(cur, cur)}", f"ตัวสำรองอัตโนมัติ: {config.LLM_FALLBACK}", ""]
    for n, label in NAMES.items():
        ok, why = ready(n) if n != "ollama" else ((True, "") if config.OLLAMA_URL else (False, "ยังไม่ได้ตั้ง"))
        lines.append(f"{'👉' if n == cur else ('✅' if ok else '⚪')} {label}" + ("" if ok else f" — {why}"))
    return "\n".join(lines)


def keyboard():
    cur = config.LLM_PROVIDER
    return {"inline_keyboard": [[{"text": ("👉 " if n == cur else "") + NAMES[n].split(" —")[0],
                                  "callback_data": f"ai:{n}"}] for n in NAMES]}


_SAY = re.compile(r"(สลับ|เปลี่ยน|ใช้|switch)\s*(ไป|เป็น|to)?\s*(ใช้)?\s*(สมอง|ai|เอไอ|โมเดล)?\s*(\S+)", re.I)


def from_text(text):
    """'สลับไปใช้ claude' → ข้อความผลการสลับ / None ถ้าไม่ใช่คำสั่งสลับ"""
    t = " ".join((text or "").lower().split())
    t = re.sub(r"(ครับ|ค่ะ|คะ|หน่อย|ที|ให้|นะ)+$", "", t).strip()
    if len(t) > 40:
        return None
    m = _SAY.fullmatch(t)
    if not m:
        return None
    target = ALIASES.get(m.group(5))
    if not target:
        return None
    return switch(target)
