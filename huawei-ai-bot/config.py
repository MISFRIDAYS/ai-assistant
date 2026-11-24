"""โหลดค่าตั้งค่าจากไฟล์ .env (ไม่ต้องใช้ไลบรารีเพิ่ม)"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ANDROID_APP=1: รันในแอป APK (คุมจอด้วย Accessibility แทน ADB/Termux) — ข้อมูลอยู่ในโฟลเดอร์ของแอป
ANDROID_APP = os.environ.get("ANDROID_APP", "") == "1"
DATA_DIR = os.environ.get("BOT_DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


_load_env(os.environ.get("BOT_ENV_FILE") or os.path.join(BASE_DIR, ".env"))


def _bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")      # ฉลาด; เร็ว+ถูก: claude-haiku-4-5
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude").strip().lower()    # claude | gemini | groq | ollama | cloud
LLM_FALLBACK = os.environ.get("LLM_FALLBACK", "groq").strip().lower()      # groq | gemini | none
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Ollama บนคอมที่บ้าน (ฟรี ไม่จำกัด) — ตั้งด้วย bash set_ollama.sh
OLLAMA_URL = os.environ.get("OLLAMA_URL", "").strip()                 # เช่น http://192.168.1.50:11434
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b").strip()
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()       # Ollama Cloud (OLLAMA_URL=https://ollama.com)
# Cloud AI จ่ายรายเดือน (API แบบ OpenAI: Chutes / NanoGPT / Synthetic ฯลฯ)
CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY", "").strip()
CLOUD_BASE_URL = os.environ.get("CLOUD_BASE_URL", "").strip() or "https://llm.chutes.ai/v1"
_NANO = "nano-gpt" in CLOUD_BASE_URL                                  # NanoGPT ใช้ชื่อรุ่นคนละแบบกับ Chutes
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "").strip() or (
    "moonshotai/kimi-k2.5" if _NANO else "Qwen/Qwen3.5-397B-A17B-TEE")   # NanoGPT: K2.5 ตอบไวสุดในแพ็ก
CLOUD_MODEL_BACKUP = os.environ.get("CLOUD_MODEL_BACKUP", "").strip() or (
    "qwen/qwen3.5-397b-a17b" if _NANO else "moonshotai/Kimi-K3-TEE")
CLOUD_VISION_MODEL = os.environ.get("CLOUD_VISION_MODEL", "").strip()   # ว่าง = ใช้ตัวหลัก/สำรอง
CLOUD_VISION = os.environ.get("CLOUD_VISION", "1").strip().lower() not in ("0", "false", "no", "off")
CLOUD_THINK = os.environ.get("CLOUD_THINK", "0").strip().lower() in ("1", "true", "yes", "on")
CLOUD_TIMEOUT = int(os.environ.get("CLOUD_TIMEOUT", "15"))   # ไม่มีข้อมูลตอบกลับเกินกี่วิ → สลับไปรุ่นสำรอง
# นาฬิกา (ผ่าน Gadgetbridge) — เปิดด้วย bash setup_watch.sh
WATCH_ENABLED = os.environ.get("WATCH_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
GADGETBRIDGE_PKG = os.environ.get("GADGETBRIDGE_PKG", "nodomain.freeyourgadget.gadgetbridge").strip()
GADGETBRIDGE_DB = os.environ.get("GADGETBRIDGE_DB", "").strip()          # ว่าง = ค้นหาเอง
WATCH_SYNC_MIN = int(os.environ.get("WATCH_SYNC_MIN", "15"))           # ซิงก์/ตรวจชีพจรทุกกี่นาที (0 = ปิด)
WATCH_HR_HIGH = int(os.environ.get("WATCH_HR_HIGH", "120"))            # เตือนเมื่อชีพจรสูงกว่า
WATCH_HR_LOW = int(os.environ.get("WATCH_HR_LOW", "40"))               # เตือนเมื่อชีพจรต่ำกว่า
# ยอดเงิน API:แสดงค่าใช้จ่าย/ยอดคงเหลือท้ายข้อความทุกครั้ง (ตั้งยอดด้วย /balance)
SHOW_BALANCE = os.environ.get("SHOW_BALANCE", "1").strip().lower() in ("1", "true", "yes", "on")
LOW_BALANCE_USD = float(os.environ.get("LOW_BALANCE_USD", "1.0"))     # เตือนเมื่อเหลือน้อยกว่านี้ (ดอลลาร์)
USD_THB = float(os.environ.get("USD_THB", "33.5"))                    # ใช้เมื่อดึงเรตสดไม่ได้
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))         # บริบทต่อคำขอ (เครื่องมือครบไม่ถูกตัด)
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "24h").strip()  # ค้างโมเดลในการ์ดจอ (เล่นเกมหนักๆ ลดเป็น 10m)
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "90"))           # คอมไม่ตอบภายในกี่วินาที → ใช้ตัวสำรอง
LOCAL_MAX_STEPS = int(os.environ.get("LOCAL_MAX_STEPS", "10"))        # รอบเรียกเครื่องมือสูงสุดของโมเดลเล็ก
# กล้องหน้า: ให้ผู้ช่วยมองผู้ใช้ ใส่ใจความรู้สึก (ภาพไม่ส่งเข้า Telegram ไม่เก็บสะสม)
CAMERA_ENABLED = os.environ.get("CAMERA_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
FRONT_CAMERA_ID = int(os.environ.get("FRONT_CAMERA_ID", "1"))         # กล้องหน้า (ถ้าได้กล้องหลังให้ลอง 0)
MOOD_ON_WAKE = os.environ.get("MOOD_ON_WAKE", "0").strip().lower() in ("1", "true", "yes", "on")
MOOD_CHECK_MIN = int(os.environ.get("MOOD_CHECK_MIN", "0"))           # ตรวจสีหน้าทุกกี่นาที (0 = ปิด)
FILE_READ_CHARS = int(os.environ.get("FILE_READ_CHARS", "12000"))     # อ่านไฟล์ได้ครั้งละกี่ตัวอักษร
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "0").strip().lower() in ("1", "true", "yes", "on")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "auto")                   # auto = เลือกรุ่น llama ที่ใช้ได้เอง
GEMINI_THINKING = _bool("GEMINI_THINKING", "0")       # 1 = ให้ Gemini คิดละเอียด (ฉลาดขึ้นแต่ช้า)
GEMINI_STT_MODEL = os.environ.get("GEMINI_STT_MODEL", "gemini-flash-lite-latest")   # รุ่นเล็ก เร็ว
# ถอดเสียงคำสั่ง:
#   auto   = ใช้ Groq (เร็ว) ก่อน ถ้าเป็นการบอกให้พิมพ์/ส่งข้อความ ค่อยใช้ Gemini ถอดซ้ำให้แม่น (แนะนำ)
#   groq   = เร็วสุดเสมอ / gemini = แม่นสุดเสมอ (ช้ากว่า)
STT_ENGINE = os.environ.get("STT_ENGINE", "auto").strip().lower()
# คำเฉพาะที่ใช้บ่อย (ชื่อคน/แอป/แบรนด์) ช่วยให้ถอดเสียงถูก — คั่นด้วย ,
STT_VOCAB = os.environ.get("STT_VOCAB", "Claude, Gemini, Instagram, Facebook, LINE, YouTube, TikTok, "
                           "Messenger, Telegram, Shopee, Lazada, ROV, GBox, CapCut")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))
# งบ AI ที่เสียเงินต่อวัน (USD) — ใช้เกินแล้วสลับไปตัวฟรี (Gemini/Groq/Ollama) จนถึงเที่ยงคืน บอทยังทำงานต่อ 24 ชม.
# 0 = ไม่จำกัด · 0.5 ≈ 17 บาท/วัน (≈ 500 บาท/เดือนสูงสุด)
DAILY_BUDGET_USD = float(os.environ.get("DAILY_BUDGET_USD", "0.5"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "15"))                    # รอบเรียกเครื่องมือสูงสุดต่อ 1 คำสั่ง (AI ใหญ่)
AUTOREPLY_DAILY_MAX = int(os.environ.get("AUTOREPLY_DAILY_MAX", "60"))  # ตอบแชทแทนด้วย AI ได้กี่ข้อความ/วัน (0 = ไม่จำกัด)
REPAIR_DAILY_MAX = int(os.environ.get("REPAIR_DAILY_MAX", "3"))       # ให้ AI ซ่อมโค้ดได้กี่ครั้ง/วัน
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}
ENABLE_WEB_SEARCH = _bool("ENABLE_WEB_SEARCH", "1")
# จำนวนครั้งที่ค้นเว็บได้ต่อ 1 คำถาม (ยิ่งมากยิ่งแพง) — 2 พอสำหรับอากาศ/ข่าว/ราคา
WEB_SEARCH_MAX_USES = int(os.environ.get("WEB_SEARCH_MAX_USES", "2"))
# อายุแคช: "1h" = แคช system+เครื่องมือ 1 ชม. (ถามห่างกันไม่ต้องเขียนแคชใหม่ ถูกลงมาก)
#          "5m" = แคชสั้นแบบเดิม (เหมาะถ้าใช้นานๆครั้งเกิน 1 ชม.ต่อครั้ง)
CACHE_TTL = os.environ.get("CACHE_TTL", "1h")
ENABLE_SHELL = _bool("ENABLE_SHELL", "1")
VOICE_CONFIRM_SEND = _bool("VOICE_CONFIRM_SEND", "1")   # สั่งด้วยเสียง: ส่ง/โพสต์/แชร์ ต้องยืนยันก่อน (กันฟังผิดแล้วส่งเลย)
AUTO_SEND = _bool("AUTO_SEND", "1")      # ส่งข้อความ/โพสต์/แชร์ได้เลยไม่ต้องถาม (ยกเว้นสั่งให้รอ)
AUTO_CALL = _bool("AUTO_CALL", "0")      # โทรได้เลยไม่ต้องถาม
AUTO_ALLOW_PERMS = _bool("AUTO_ALLOW_PERMS", "1")   # ระหว่างทำงาน เจอป๊อปอัปขอสิทธิ์ของแอป → กด "อนุญาต" ให้เลย
DEVICE_ALERTS = _bool("DEVICE_ALERTS", "1")             # แจ้งเตือนแบตใกล้หมด/ชาร์จเต็ม/เครื่องร้อน
BATTERY_LOW = int(os.environ.get("BATTERY_LOW", "15"))
SPEAK_SCHEDULED = _bool("SPEAK_SCHEDULED", "1")         # งานตามเวลา → พูดออกลำโพงด้วย
MOCK_PHONE = _bool("MOCK_PHONE", "0")
ENABLE_ADB = _bool("ENABLE_ADB", "1")
# ชุดตัดต่อวิดีโอ (list_media/video_info/edit_video) — ปิดไว้เพื่อลดเครื่องมือ/ค่าใช้จ่าย
# อยากใช้ตัดต่อวิดีโอเมื่อไหร่ ตั้ง ENABLE_VIDEO=1 ใน .env
ENABLE_VIDEO = _bool("ENABLE_VIDEO", "0")
# เครื่องมือที่ปิดใช้งาน (AI จะมองไม่เห็นและเรียกไม่ได้ ช่วยลดโทเค่น)
# แก้ได้ที่ .env เช่น DISABLED_TOOLS=send_sms,make_call  (เว้นว่าง = เปิดหมด)
DISABLED_TOOLS = {
    t.strip() for t in os.environ.get(
        "DISABLED_TOOLS",
        "list_sms,send_sms,make_call,find_contact,call_log,remember,forget,set_alarm,set_brightness"
    ).split(",") if t.strip()
}

# ----- เสียง -----
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
STT_MODEL = os.environ.get("STT_MODEL", "whisper-large-v3")     # แม่นภาษาไทยกว่า turbo
TTS_LANG = os.environ.get("TTS_LANG", "th")
TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge")                 # edge = เสียงคน (แนะนำ), google = สำรอง
TTS_VOICE = os.environ.get("TTS_VOICE", "th-TH-NiwatNeural")      # ชาย; หญิง: th-TH-PremwadeeNeural
TTS_RATE = os.environ.get("TTS_RATE", "+10%")                      # ความเร็วพูด (เร็วเกินจะฟังเหมือนหุ่นยนต์)
TTS_PITCH = os.environ.get("TTS_PITCH", "-2Hz")
# เสียง Gemini (เหมือนคนที่สุด กำหนดน้ำเสียงได้ แต่ช้ากว่า) — ใช้เมื่อ TTS_ENGINE=gemini, โควตาหมดจะกลับไปใช้ edge เอง
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Puck")
TTS_STYLE = os.environ.get("TTS_STYLE", "Speak natural, warm, friendly conversational Thai like a close friend, "
                                        "relaxed pace, gentle and expressive")
BOT_GENDER = os.environ.get("BOT_GENDER", "male").strip().lower()   # male = ครับ / female = ค่ะ
VOICE_TO_TELEGRAM = _bool("VOICE_TO_TELEGRAM", "1")               # คุยด้วยเสียง → ส่งคำตอบเต็มเข้า Telegram
VOICE_MAX_SPEAK = int(os.environ.get("VOICE_MAX_SPEAK", "220"))   # พูดออกเสียงไม่เกินกี่ตัวอักษร
NOTIFY_ANNOUNCE = _bool("NOTIFY_ANNOUNCE", "1")                   # อ่านแจ้งเตือนใหม่ให้ฟัง + ถามตอบกลับ
NOTIFY_APPS = os.environ.get("NOTIFY_APPS", "LINE,Messenger,Instagram,WhatsApp,Facebook,SMS,สายเรียกเข้า")
NOTIFY_QUIET = os.environ.get("NOTIFY_QUIET", "23:00-07:00")      # ช่วงเวลาห้ามพูด
NOTIFY_TELEGRAM = _bool("NOTIFY_TELEGRAM", "0")                   # ส่งแจ้งเตือนเข้า Telegram ด้วย
ALWAYS_LISTEN = os.environ.get("ALWAYS_LISTEN", "0").strip().lower() in ("1", "true", "yes", "on")  # ไม่ต้องเรียกคำปลุก
# ถอดเสียงคำสั่งด้วยระบบของเครื่อง (Google เหมือนปุ่มไมค์ในคีย์บอร์ด) — ฟรี แม่น · ไม่มี → ใช้ตัวเดิม
GOOGLE_STT = os.environ.get("GOOGLE_STT", "1").strip().lower() in ("1", "true", "yes", "on", "auto")
GOOGLE_STT_LANG = os.environ.get("GOOGLE_STT_LANG", "th-TH").strip()
SPEAKER_VERIFY = os.environ.get("SPEAKER_VERIFY", "1").strip().lower() in ("1", "true", "yes", "on")  # ฟังเฉพาะเสียงเจ้าของ
SPEAKER_STRICT = float(os.environ.get("SPEAKER_STRICT", "0"))
# แอปบนมือถือ: ต้องลงทะเบียนเสียงก่อน ถึงจะรับคำสั่งเสียง (ปิดได้ด้วย REQUIRE_VOICE_ENROLL=0)
REQUIRE_VOICE_ENROLL = ANDROID_APP and os.environ.get("REQUIRE_VOICE_ENROLL", "1").strip().lower() in ("1", "true", "yes", "on")       # +0.05 = เข้มขึ้น / -0.05 = ผ่อนลง
FAST_SCREEN = os.environ.get("FAST_SCREEN", "1").strip().lower() in ("1", "true", "yes", "on")  # ใช้ uiautomator2 ถ้ามี
ROUTER = os.environ.get("ROUTER", "1").strip().lower() in ("1", "true", "yes", "on")   # AI แยกเจตนา → ระบบลงมือเอง
QUICK_COMMANDS = _bool("QUICK_COMMANDS", "1")
UI_ENABLED = _bool("UI_ENABLED", "1")                             # การ์ดสถานะแบบ Assistant (ฟัง/คิด/ตอบ)
UI_LINGER = float(os.environ.get("UI_LINGER", "6"))
UI_MIN_INTERVAL = float(os.environ.get("UI_MIN_INTERVAL", "1.2"))  # อัปเดตการ์ดไม่ถี่กว่านี้ (กัน Termux:API error)              # แสดงคำตอบค้างไว้กี่วินาที                     # คำสั่งง่ายๆ ทำทันทีไม่ต้องรอ AI
VOICE_REPLY = _bool("VOICE_REPLY", "1")                  # ส่งข้อความเสียงมา → ตอบกลับเป็นเสียงด้วย
SPEAK_ON_DEVICE = _bool("SPEAK_ON_DEVICE", "0")          # พูดคำตอบออกลำโพงแท็บเล็ตทุกครั้ง
VOICE_LISTEN_SECONDS = int(os.environ.get("VOICE_LISTEN_SECONDS", "5"))
VOICE_GREETING = _bool("VOICE_GREETING", "0")            # พูด "ว่ายังไงครับ" ก่อนฟัง (ช้าลงนิดหน่อย)
# คำที่ช่วยให้ระบบฟังชื่อแอป/คำเฉพาะได้ถูกต้อง
# ใส่น้อยๆ พอ: ถ้าใส่ชื่อแอปเยอะ ระบบจะเดาเป็นชื่อในนี้ตอนฟังไม่ชัด (เช่น เปิด YouTube → เปิด ROV)
STT_PROMPT = os.environ.get("STT_PROMPT", "สวัสดีผู้ช่วย")
# ถอดเสียงด้วยอะไร: auto = Groq → Cloudflare → NanoGPT / groq / cloudflare / nano (ใช้คีย์ Cloud AI ของ NanoGPT, จ่ายตามใช้ ~฿0.02/นาที)
STT_PROVIDER = os.environ.get("STT_PROVIDER", "auto").strip().lower()
NANO_STT_MODEL = os.environ.get("NANO_STT_MODEL", "Whisper-Large-V3").strip()
# Cloudflare Workers AI (ฟรีวันละ ~200 นาทีเสียง): dash.cloudflare.com → Account ID + API Token (เทมเพลต Workers AI)
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
CF_STT_MODEL = os.environ.get("CF_STT_MODEL", "@cf/openai/whisper-large-v3-turbo").strip()
NANO_STT_URL = os.environ.get("NANO_STT_URL", "https://api.nano-gpt.com/api/v1/audio/transcriptions").strip()
WAKE_WORDS = [w.strip() for w in os.environ.get("WAKE_WORDS", "เฮ้ยผู้ช่วย,สวัสดีผู้ช่วย,หวัดดีผู้ช่วย,เฮ้ผู้ช่วย,โอเคผู้ช่วย,โอเครผู้ช่วย,okผู้ช่วย,ผู้ช่วย,ผู้ช้วย,ผู่ช่วย,ผู้ชวย,ผู้ข่วย").split(",") if w.strip()]
WAKE_MIN_DB = float(os.environ.get("WAKE_MIN_DB", "-35"))
VAD_MIN_RMS = float(os.environ.get("VAD_MIN_RMS", "60"))          # ความดังขั้นต่ำที่นับว่าเป็นเสียงพูด
VOICE_MIN_SPEECH = float(os.environ.get("VOICE_MIN_SPEECH", "0.4"))   # ต้องมีเสียงพูดชัดๆ อย่างน้อยกี่วินาที (กันเสียงรบกวน)
VAD_END_SILENCE = float(os.environ.get("VAD_END_SILENCE", "0.9"))  # เงียบกี่วินาทีถือว่าพูดจบ
BARGE_IN = _bool("BARGE_IN", "0")                                  # พูดแทรกตอน AI กำลังพูดได้
BARGE_IN_FACTOR = float(os.environ.get("BARGE_IN_FACTOR", "2.0"))  # ต้องดังกว่าเสียงลำโพงที่ไมค์ได้ยินกี่เท่า
BARGE_IN_MS = int(os.environ.get("BARGE_IN_MS", "250"))            # ต้องพูดต่อเนื่องนานกี่ ms ถึงนับว่าพูดแทรก
VOICE_BEEP = _bool("VOICE_BEEP", "0")                              # 1 = มีเสียงติ๊ดก่อนฟัง
WAKE_EACH_TIME = os.environ.get("WAKE_EACH_TIME", "0").strip().lower() in ("1", "true", "yes", "on")  # ต้องเรียก "เฮ้ยผู้ช่วย" ทุกคำสั่ง
FOLLOWUP_SECONDS = float(os.environ.get("FOLLOWUP_SECONDS", "8"))  # หลังตอบ รอฟังคำถามต่อโดยไม่ต้องเรียกชื่อ
FOLLOWUP_LENIENT = float(os.environ.get("FOLLOWUP_LENIENT", "0.06"))  # ช่วงฟังต่อ: ผ่อนเกณฑ์เสียงเจ้าของได้แค่นี้ (มาก = คนอื่นพูดก็ผ่าน)
ADB_ADDRESS = os.environ.get("ADB_ADDRESS", "")
BOT_NAME = os.environ.get("BOT_NAME", "ผู้ช่วย Huawei")
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "20"))
CONFIRM_TIMEOUT = int(os.environ.get("CONFIRM_TIMEOUT", "120"))
TIMEZONE_OFFSET_HOURS = float(os.environ.get("TIMEZONE_OFFSET_HOURS", "7"))


def paused():
    """ผู้ใช้กดปิดผู้ช่วยไว้ (ปุ่ม ⏻ ในแอป หรือ /off) → ไม่ฟังไมค์ ไม่ทำงานเบื้องหลัง"""
    return os.path.exists(os.path.join(DATA_DIR, "paused"))


def mic_off():
    """ผู้ใช้ปิดไมค์สั่งเสียงไว้ (ปุ่ม 🎤 ในหน้าต่างลอย) — แชทพิมพ์ยังใช้ได้"""
    return os.path.exists(os.path.join(DATA_DIR, "mic_off"))


def set_mic_off(on):
    p = os.path.join(DATA_DIR, "mic_off")
    if on:
        open(p, "w").close()
    elif os.path.exists(p):
        os.remove(p)


def set_paused(on):
    p = os.path.join(DATA_DIR, "paused")
    if on:
        open(p, "w").close()
    elif os.path.exists(p):
        os.remove(p)

# ปฏิทิน: Google Apps Script ของผู้ใช้ (google_calendar_script.gs) → นัดหมาย/บันทึกงานลง Google Calendar
GCAL_URL = os.environ.get("GCAL_URL", "").strip()
GCAL_SECRET = os.environ.get("GCAL_SECRET", "").strip()
