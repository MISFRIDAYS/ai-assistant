"""จุดเริ่มต้นของบอท: python bot.py"""
import base64
import json
import os
import threading
import time
import traceback
import uuid
from datetime import timedelta

import agent
import config
import phone_tools
import voice
from telegram_api import Telegram

tg = None
_pending = {}  # id -> {"event", "ok", "chat_id"}
_ask_waiters = {}  # chat_id -> {"event", "answer"} (กำลังรอคำตอบจาก ctx.ask)
_reminder_lock = threading.Lock()
REMINDER_FILE = os.path.join(config.DATA_DIR, "reminders.json")


def _save_inbox(data, name):
    """เก็บรูป/คลิปที่ผู้ใช้ส่งมา ไว้ส่งต่อเข้าแอปอื่นภายหลัง"""
    import re as _re
    try:
        inbox = os.path.join(config.DATA_DIR, "inbox")
        os.makedirs(inbox, exist_ok=True)
        p = os.path.join(inbox, _re.sub(r"[^\w.\-ก-๙]", "_", name)[:80])
        with open(p, "wb") as f:
            f.write(data)
        return p
    except OSError:
        return None


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------------------------------------------------------------- เตือนความจำ

def _load_reminders():
    try:
        with open(REMINDER_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_reminders(items):
    with open(REMINDER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


def add_reminder(chat_id, minutes, text):
    due = time.time() + minutes * 60
    with _reminder_lock:
        items = _load_reminders()
        items.append({"chat_id": chat_id, "due": due, "text": text})
        _save_reminders(items)
    return (agent.now_local() + timedelta(minutes=minutes)).strftime("%d/%m %H:%M")


def _run_due(r):
    """ถึงเวลา: เตือน หรือให้ AI ทำงาน แล้วส่งเข้า Telegram (+ พูดออกลำโพง)"""
    if r.get("kind") == "task":
        tg.send_message(r["chat_id"], f"🤖 งานตามเวลา: {r['text']}")
        try:
            reply = agent.chat(r["chat_id"], f"[งานตามเวลาที่ผู้ใช้ตั้งไว้ ทำเลยไม่ต้องถาม] {r['text']}",
                               Ctx(r["chat_id"]))
        except Exception as e:  # noqa: BLE001
            reply = f"❗ ทำงานไม่สำเร็จ: {e}"
        tg.send_message(r["chat_id"], reply)
        spoken = reply
    else:
        tg.send_message(r["chat_id"], f"⏰ เตือนความจำ: {r['text']}")
        phone_tools.run(["termux-notification", "-t", "⏰ เตือนความจำ", "-c", r["text"],
                         "--sound", "--vibrate", "500,300,500"])
        spoken = f"เตือนความจำครับ {r['text']}"
    if config.SPEAK_SCHEDULED and r.get("speak", True):
        try:
            voice.say(voice.clean_for_speech(spoken, limit=config.VOICE_MAX_SPEAK))
        except Exception as e:  # noqa: BLE001
            log("speak error:", e)


def reminder_loop():
    import extras
    while True:
        try:
            with _reminder_lock:
                items = _load_reminders()
                now = time.time()
                due = [r for r in items if r["due"] <= now]
                if due:
                    keep = [r for r in items if r["due"] > now]
                    keep += [n for n in (extras.reschedule(r) for r in due) if n]   # งานรายวัน → รอบถัดไป
                    _save_reminders(keep)
            for r in due:
                threading.Thread(target=_safe, args=(_run_due, r), daemon=True).start()
            owner = min(config.ALLOWED_USER_IDS) if config.ALLOWED_USER_IDS else None
            for msg_text in extras.check_device_alerts():
                if owner:
                    tg.send_message(owner, msg_text)
                phone_tools.run(["termux-notification", "-t", "ผู้ช่วย", "-c", msg_text])
        except Exception:  # noqa: BLE001
            log("reminder error", traceback.format_exc())
        time.sleep(15)


# ---------------------------------------------------------------- context ที่ส่งให้ tools

class Ctx:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.status_msg = None
        self.hold = False

    def status(self, text):
        tg.send_chat_action(self.chat_id)

    def send_photo(self, path):
        try:
            tg.send_photo(self.chat_id, path)
        except Exception as e:  # noqa: BLE001
            log("send_photo error", e)

    def add_reminder(self, minutes, text):
        return add_reminder(self.chat_id, minutes, text)

    def send_file(self, path, kind="document"):
        tg.send_file(self.chat_id, path, kind=kind)

    def notify(self, text):
        """ข้อความความคืบหน้าระหว่างทำงานยาวๆ (เช่น โหมดควบคุมหน้าจอ)"""
        try:
            tg.send_message(self.chat_id, text)
        except Exception as e:  # noqa: BLE001
            log("notify error", e)

    def ask(self, question, timeout=180):
        """ถามผู้ใช้แล้วรอคำตอบเป็นข้อความถัดไปในแชท (ใช้ตอนกรอกฟอร์ม/ขั้นตอนที่ต้องถามข้อมูล)"""
        w = {"event": threading.Event(), "answer": None}
        _ask_waiters[self.chat_id] = w
        try:
            tg.send_message(self.chat_id, "❓ " + question + "\n(พิมพ์ตอบได้เลย · \"ข้าม\" = เว้นว่าง · \"ยกเลิก\" = หยุด)")
            w["event"].wait(timeout)
            return w["answer"]
        finally:
            _ask_waiters.pop(self.chat_id, None)

    def confirm(self, description):
        pid = uuid.uuid4().hex[:12]
        ev = threading.Event()
        _pending[pid] = {"event": ev, "ok": False, "chat_id": self.chat_id}
        kb = {"inline_keyboard": [[
            {"text": "✅ อนุญาต", "callback_data": f"ok:{pid}"},
            {"text": "❌ ยกเลิก", "callback_data": f"no:{pid}"},
        ]]}
        msg = tg.send_message(self.chat_id, f"⚠️ ขออนุญาตทำคำสั่งนี้:\n\n{description}", reply_markup=kb)
        answered = ev.wait(config.CONFIRM_TIMEOUT)
        ok = answered and _pending[pid]["ok"]
        _pending.pop(pid, None)
        if msg:
            mark = "✅ อนุญาตแล้ว" if ok else ("❌ ยกเลิกแล้ว" if answered else "⌛ หมดเวลา ยกเลิกแล้ว")
            tg.edit_message_text(self.chat_id, msg["message_id"], f"{mark}\n\n{description}")
        return ok


# ---------------------------------------------------------------- จัดการข้อความ

HELP = (
    "สวัสดีครับ ผมคือ {name} 🤖\n\n"
    "คุยหรือสั่งงานได้เลย เช่น\n"
    "• แบตเหลือเท่าไหร่\n• ตอนนี้อยู่ที่ไหน\n• เปิดไฟฉาย\n• อ่าน SMS ล่าสุด\n"
    "• ส่ง SMS หาแม่ว่าถึงบ้านแล้ว\n• ข่าววันนี้มีอะไรบ้าง\n• เตือนอีก 15 นาทีให้กินยา\n"
    "• ส่งรูปมาถามได้ด้วย\n\n"
    "คำสั่ง: /status สถานะ · /syscheck ตรวจการคุมระบบ · /diag youtube ตรวจการเปิดแอป · /listen ฟังตลอด (/listen off) · /voiceid จำเสียงเจ้าของ · /doctor ตรวจซ่อมตัวเอง · /fix <อาการ> ให้บอทแก้โค้ดตัวเอง · /rollback ย้อนการซ่อม · /learn instagram ศึกษาแอป · /flows ขั้นตอนที่สอนไว้ · /profile ข้อมูลกรอกฟอร์ม · /memory สิ่งที่จำไว้ · /usage ค่าใช้จ่าย · /balance ยอดคงเหลือ · /ai สลับ AI · /voice เปลี่ยนเสียง · /log · /reset ล้างแชท · /help"
)


def is_allowed(user_id):
    return user_id in config.ALLOWED_USER_IDS


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    user = msg.get("from", {})
    uid = user.get("id")
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if text.startswith("/id"):
        tg.send_message(chat_id, f"Telegram ID ของคุณคือ: {uid}")
        return
    if not is_allowed(uid):
        log(f"blocked user {uid} ({user.get('username')})")
        tg.send_message(chat_id, f"⛔ คุณยังไม่ได้รับอนุญาต\nTelegram ID ของคุณ: {uid}\n"
                                 "ให้เจ้าของเครื่องใส่เลขนี้ใน ALLOWED_USER_IDS ในไฟล์ .env")
        return
    if text.strip() in ("/on", "/off"):
        config.set_paused(text.strip() == "/off")
        tg.send_message(chat_id, "⏸️ ปิดผู้ช่วยแล้ว (เปิดใหม่: /on)" if text.strip() == "/off" else "▶️ เปิดผู้ช่วยแล้ว")
        return
    if config.paused():
        tg.send_message(chat_id, "⏸️ ผู้ช่วยปิดอยู่ — พิมพ์ /on หรือเปิดในแอป")
        return
    w = _ask_waiters.get(chat_id)
    if w and text and not text.startswith("/"):            # ตอบคำถามที่บอทถามค้างไว้ (เช่น ช่องในฟอร์ม)
        w["answer"] = text
        w["event"].set()
        return
    import prompts
    if text in ("/start", "/help"):
        tg.send_message(chat_id, prompts.help_text())
        return
    if text.startswith("/menu"):
        tg.send_message(chat_id, "📋 เลือกหมวด แล้วกดคำสั่งเพื่อใช้ได้เลย", reply_markup=prompts.menu_keyboard())
        return
    cmd = text.split()[0].split("@")[0] if text.startswith("/") else ""
    if cmd in prompts.SHORTCUTS:
        text = prompts.SHORTCUTS[cmd]
    if text.startswith("/status"):
        tg.send_message(chat_id, status_text())
        return
    if text.startswith("/voice"):
        import voice_profile
        voice_profile.sync()
        tg.send_message(chat_id, f"🔊 เสียงตอนนี้: {voice_profile.current_label()}\n"
                                 "เลือกเสียงใหม่ — กดแล้วแท็บเล็ตจะพูดตัวอย่างให้ฟังทันที",
                        reply_markup=voice_profile.keyboard())
        return
    if text.startswith("/ai"):
        import providers
        arg = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""
        if arg:
            tg.send_message(chat_id, providers.switch(arg))
        tg.send_message(chat_id, "🧠 เลือกสมอง AI (สลับฉุกเฉินได้ทันที)\n\n" + providers.status(),
                        reply_markup=providers.keyboard())
        return
    if text.startswith("/listen"):
        import quick
        arg = text[7:].strip().lower()
        tg.send_message(chat_id, quick.listen_mode("ปิดโหมดฟังตลอด" if arg in ("off", "ปิด") else "ฟังตลอด"))
        return
    if text.startswith("/voiceid"):
        import speaker_id
        if not speaker_id.available():
            msg = "ยังไม่ได้ติดตั้ง numpy — รันใน Termux: bash enroll_voice.sh (ติดตั้งให้เอง)"
        elif speaker_id.enrolled():
            p = speaker_id._load()
            msg = (f"🗣️ จำเสียงเจ้าของไว้แล้ว ({p['n']} ประโยค เกณฑ์ {p['threshold']} ความเข้มเพิ่ม {config.SPEAKER_STRICT:+})\n"
                   "สอนใหม่: bash enroll_voice.sh")
        else:
            msg = "ยังไม่ได้สอนเสียง — รันใน Termux: bash enroll_voice.sh (พูด 6 ประโยค ~1 นาที)"
        tg.send_message(chat_id, msg)
        return
    if text.startswith("/diag"):
        import diag_open
        app = text[5:].strip() or "youtube"
        tg.send_message(chat_id, f"🔎 กำลังตรวจการเปิด {app} (ประมาณ 20-40 วิ หน้าจอแท็บเล็ตจะขยับเอง)...")
        try:
            tg.send_message(chat_id, diag_open.run(app))
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat_id, f"❗ ตรวจไม่สำเร็จ: {e}")
        return
    if text.startswith("/doctor"):
        import self_heal
        tg.send_message(chat_id, "🩺 กำลังตรวจ…")
        tg.send_message(chat_id, self_heal.doctor())
        return
    if text.startswith("/fix"):
        import self_heal
        sym = text[4:].strip()
        tg.send_message(chat_id, "🛠️ กำลังซ่อม (วิเคราะห์ → ลองในสำเนา → รันเทสต์ ~2-5 นาที)…")
        c = Ctx(chat_id)
        r = self_heal.handle_text(f"ซ่อมตัวเอง {sym}" if len(sym) >= 4 else "ซ่อมบัค", c)
        tg.send_message(chat_id, r or "บอกอาการด้วย เช่น /fix ส่งข้อความ IG แล้วไม่กดส่ง")
        return
    if text.startswith("/rollback"):
        import self_heal
        tg.send_message(chat_id, self_heal.handle_text("ย้อนการซ่อม") or "")
        return
    if text.startswith("/profile"):
        import user_profile
        tg.send_message(chat_id, user_profile.show())
        return
    if text.startswith("/flows"):
        import app_learn
        tg.send_message(chat_id, app_learn.list_flows())
        return
    if text.startswith("/learn"):
        import app_learn
        app = text[6:].strip()
        if not app:
            tg.send_message(chat_id, "ใส่ชื่อแอปด้วย เช่น /learn instagram")
            return
        tg.send_message(chat_id, f"📚 กำลังศึกษา {app} (แตะดูทีละแท็บ ~30 วิ ไม่กดปุ่มเสี่ยง)...")
        try:
            tg.send_message(chat_id, app_learn.explore(app, Ctx(chat_id)))
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat_id, f"❗ ศึกษาไม่สำเร็จ: {e}")
        return
    if text.startswith("/syscheck"):
        import system_tools
        tg.send_message(chat_id, system_tools.diagnose())
        return
    if text.startswith("/log"):
        tg.send_message(chat_id, "```\n" + tail_logs() + "\n```")
        return
    if text.startswith("/memory"):
        import extras
        mem = extras.memories()
        tg.send_message(chat_id, "🧠 สิ่งที่จำไว้:\n" + "\n".join(f"- {m['text']}" for m in mem)
                        if mem else "🧠 ยังไม่ได้จำอะไรไว้ (บอกว่า 'จำไว้ว่า...' ได้เลย)")
        return
    if text.startswith("/usage"):
        import extras
        rep, usd = extras.usage_report(days=7)
        tg.send_message(chat_id, f"📊 การใช้งาน 7 วัน (ประมาณ ${usd:.2f} ≈ {extras.baht(usd)})\n{rep}\n\n"
                                 + extras.balance_text())
        return
    if text.startswith("/balance"):
        import extras
        arg = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
        if arg:
            try:
                v = float(arg.replace("$", "").replace("US", "").replace(",", "").strip())
                if not 0 <= v < 10000:
                    raise ValueError
            except ValueError:
                tg.send_message(chat_id, "พิมพ์ยอดเป็นดอลลาร์ตามหน้าเว็บ เช่น /balance 4.85")
                return
            extras.set_balance(v)
            tg.send_message(chat_id, "✅ ตั้งยอดแล้ว\n" + extras.balance_text())
        else:
            tg.send_message(chat_id, extras.balance_text())
        return
    if text == "/reset":
        agent.reset_history(chat_id)
        tg.send_message(chat_id, "🧹 ล้างความจำแชทแล้ว")
        return

    content = []
    is_voice = bool(msg.get("voice") or msg.get("audio"))
    if is_voice:
        media = msg.get("voice") or msg.get("audio")
        tg.send_chat_action(chat_id, "typing")
        try:
            data, fpath = tg.download_file(media["file_id"])
            ext = os.path.splitext(fpath)[1] or ".ogg"
            local = os.path.join(config.DATA_DIR, f"voice_in{ext}")
            with open(local, "wb") as f:
                f.write(data)
            mime = {".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mp3",
                    ".m4a": "audio/mp4", ".wav": "audio/wav"}.get(ext.lower(), "audio/ogg")
            text = voice.transcribe(local)                     # Groq เร็ว
            if voice.use_gemini_stt() and voice.needs_accurate(text):
                text = voice.transcribe_accurate(local, mime=mime) or text   # บอกข้อความ → Gemini แม่น
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat_id, f"❗ ฟังเสียงไม่ได้: {e}")
            return
        if not text:
            tg.send_message(chat_id, "🎤 ไม่ได้ยินเสียงพูดเลยครับ ลองใหม่อีกครั้งนะ")
            return
        tg.send_message(chat_id, f"🎤 ได้ยินว่า: {text}")
        content.append({"type": "text", "text": "[ผู้ใช้พูดด้วยเสียง: ตอบสั้น 1-3 ประโยค เป็นภาษาพูด "
                                                 "ไม่ใช้รายการ/markdown/อีโมจิ]"})
    if msg.get("document"):
        doc = msg["document"]
        if doc.get("file_size", 0) > 20_000_000:
            tg.send_message(chat_id, "📎 ไฟล์ใหญ่เกิน 20MB (ลิมิตของ Telegram bot) — ย่อไฟล์หรือวางไว้ในเครื่องแล้วสั่งให้อ่านแทน")
            return
        tg.send_chat_action(chat_id, "typing")
        try:
            import files_tools
            data, _ = tg.download_file(doc["file_id"])
            content += files_tools.from_telegram(data, doc.get("file_name") or "file")
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat_id, f"❗ อ่านไฟล์ไม่ได้: {e}")
            return
        text = text or "ช่วยสรุปไฟล์นี้ให้หน่อย"
    if msg.get("photo"):
        data, _ = tg.download_file(msg["photo"][-1]["file_id"])
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(data).decode()}})
        saved = _save_inbox(data, f"photo_{int(time.time())}.jpg")
        if saved:
            content.append({"type": "text", "text": f"[รูปนี้บันทึกไว้ที่ {saved} — ส่งต่อเข้าแอปได้ด้วย send_to_app]"})
        text = text or "ช่วยดูรูปนี้หน่อย"
    media = msg.get("video") or msg.get("animation") or msg.get("video_note") or msg.get("audio")
    if media:
        if media.get("file_size", 0) > 20_000_000:
            tg.send_message(chat_id, "🎬 ไฟล์ใหญ่เกิน 20MB (ลิมิตของ Telegram bot) — วางไฟล์ไว้ในเครื่องแล้วสั่งด้วยชื่อไฟล์แทน")
            return
        data, _ = tg.download_file(media["file_id"])
        ext = ".mp3" if msg.get("audio") else ".mp4"
        saved = _save_inbox(data, media.get("file_name") or f"video_{int(time.time())}{ext}")
        content.append({"type": "text", "text": f"[ผู้ใช้ส่ง{'เสียง' if msg.get('audio') else 'วิดีโอ'}มา "
                                                f"บันทึกไว้ที่ {saved} — ส่งต่อเข้าแอปได้ด้วย send_to_app]"})
        text = text or "ได้รับไฟล์แล้ว รอคำสั่งว่าจะให้ส่งไปที่ไหน"
    if not text and not content:
        tg.send_message(chat_id, "ตอนนี้รองรับข้อความและรูปภาพครับ")
        return
    content.append({"type": "text", "text": text})

    log(f"{uid}: {text[:80]}")
    t0 = time.time()
    done = threading.Event()

    def typing():  # แสดง "กำลังพิมพ์..." ต่อเนื่องจนกว่าจะตอบเสร็จ
        while not done.is_set():
            tg.send_chat_action(chat_id)
            done.wait(4)
    threading.Thread(target=typing, daemon=True).start()
    import extras
    spent0 = extras.spent_counter()
    try:
        reply = agent.chat(chat_id, content, Ctx(chat_id))
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        import self_heal
        self_heal.record(traceback.format_exc())
        reply = f"❗ เกิดข้อผิดพลาด: {e}"
    finally:
        done.set()
    try:
        footer = extras.cost_footer(extras.spent_counter() - spent0)   # ค่าใช้จ่ายครั้งนี้ + ยอดคงเหลือ
    except Exception:  # noqa: BLE001
        footer = ""
    tg.send_message(chat_id, reply + (f"\n\n{footer}" if footer else ""))
    log(f"ตอบเสร็จใน {time.time() - t0:.1f} วินาที")
    if (is_voice and config.VOICE_REPLY) or config.SPEAK_ON_DEVICE:
        speak_reply(chat_id, reply, send_telegram=is_voice and config.VOICE_REPLY)


def _voice_sample(chat_id):
    """ตัวอย่างเสียงใหม่: พูดออกลำโพงแท็บเล็ต + ส่งไฟล์เสียงเข้า Telegram"""
    import voice_profile
    path = voice.synthesize(voice_profile.sample())
    try:
        tg.send_voice(chat_id, path)
    except Exception as e:  # noqa: BLE001
        log("send sample error:", e)
    voice.play(path)


def speak_reply(chat_id, reply, send_telegram=True):
    try:
        path = voice.synthesize(reply)
    except Exception as e:  # noqa: BLE001
        log("tts error:", e)
        return
    try:
        if send_telegram:
            tg.send_chat_action(chat_id, "record_voice")
            tg.send_voice(chat_id, path)
        if config.SPEAK_ON_DEVICE:
            voice.play(path)
    except Exception as e:  # noqa: BLE001
        log("voice reply error:", e)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


_started_at = time.time()


def status_text():
    try:
        import providers
        providers.sync()
    except Exception:  # noqa: BLE001
        pass
    import extras
    import screen_tools
    up = int(time.time() - _started_at)
    voice_pid = os.path.join(config.DATA_DIR, "voice_chat.pid")
    voice_on = False
    try:
        os.kill(int(open(voice_pid).read()), 0)
        voice_on = True
    except Exception:  # noqa: BLE001
        pass
    _, usd = extras.usage_report(days=1)
    _b = extras.balance()
    _bal = (f"≈ {extras.baht(max(0, _b['usd']))}" if _b.get("usd") is not None else "ยังไม่ตั้ง (/balance 4.85)")
    try:
        b = json.loads(phone_tools.run(["termux-battery-status"]))
        batt = f"{b.get('percentage')}% {b.get('temperature')}°C"
    except Exception:  # noqa: BLE001
        batt = "-"
    _m = {"gemini": config.GEMINI_MODEL, "groq": config.GROQ_MODEL,
          "ollama": config.OLLAMA_MODEL, "cloud": config.CLOUD_MODEL}.get(config.LLM_PROVIDER, config.CLAUDE_MODEL)
    ai = f"{config.LLM_PROVIDER} ({_m})"
    if config.LLM_PROVIDER == "ollama" or config.LLM_FALLBACK == "ollama":
        import ollama_client
        ok, why = ollama_client.ping()
        ai += f"\n• คอม (Ollama): {'🟢' if ok else '🔴'} {why}"
    if config.LLM_FALLBACK and config.LLM_FALLBACK != "none":
        ai += f"\n• ตัวสำรอง: {config.LLM_FALLBACK}"
    return (f"🤖 สถานะผู้ช่วย\n"
            f"• บอท Telegram: ทำงาน {up // 3600} ชม. {up % 3600 // 60} นาที\n"
            f"• ผู้ช่วยเสียง: {'🟢 ฟังอยู่' if voice_on else '⚪ ปิดอยู่'}\n"
            f"• ควบคุมหน้าจอ (ADB): {'🟢 เชื่อมแล้ว' if screen_tools.adb_serial() else '⚪ ยังไม่เชื่อม'}\n"
            f"• AI: {ai}\n"
            f"• แบต: {batt}\n"
            f"• ค่าใช้จ่ายวันนี้: ≈ {extras.baht(usd)} (${usd:.3f})\n"
            f"• ยอด API คงเหลือ: {_bal}\n"
            f"• ความจำ: {len(extras.memories())} เรื่อง\n\n"
            f"/memory ดูสิ่งที่จำไว้ · /usage ค่าใช้จ่าย · /balance ยอดคงเหลือ · /ai สลับ AI · /voice เปลี่ยนเสียง · /log ดู log · /reset ล้างแชท")


def tail_logs(n=25):
    out = []
    for name in ("bot.log", "voice.log"):
        p = os.path.join(config.DATA_DIR, name)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-n:]
            out.append(f"== {name} ==\n" + "".join(lines))
        except OSError:
            pass
    return ("\n".join(out) or "ไม่มี log")[-3500:]


def handle_callback(cq):
    data = cq.get("data", "")
    uid = cq.get("from", {}).get("id")
    if not is_allowed(uid) or ":" not in data:
        tg.answer_callback(cq["id"], "ไม่ได้รับอนุญาต")
        return
    if data.startswith(("cat:", "run:")):          # เมนูคำสั่ง
        import prompts
        chat_id = cq["message"]["chat"]["id"]
        mid = cq["message"]["message_id"]
        tg.answer_callback(cq["id"])
        if data == "cat:back":
            tg.edit_message_text(chat_id, mid, "📋 เลือกหมวด", reply_markup=prompts.menu_keyboard())
        elif data.startswith("cat:"):
            name, kb = prompts.category_keyboard(int(data[4:]))
            tg.edit_message_text(chat_id, mid, f"{name} — กดเพื่อสั่งงาน", reply_markup=kb)
        else:
            _, i, j = data.split(":")
            p = prompts.prompt_at(int(i), int(j))
            if "..." in p:
                tg.send_message(chat_id, f"✏️ พิมพ์ต่อเองนะครับ เช่น: {p.replace('...', '___')}")
                return
            fake = {"chat": {"id": chat_id}, "from": cq["from"], "text": p}
            threading.Thread(target=_safe, args=(handle_message, fake), daemon=True).start()
        return
    if data.startswith("voice:"):
        import voice_profile
        res = voice_profile.apply(data[6:]) or "ไม่รู้จักเสียงนี้"
        tg.answer_callback(cq["id"], res[:190])
        cid = cq["message"]["chat"]["id"]
        tg.send_message(cid, res)
        if res.startswith("✅"):
            threading.Thread(target=_safe, args=(_voice_sample, cid), daemon=True).start()
        return
    if data.startswith("ai:"):
        import providers
        res = providers.switch(data[3:])
        tg.answer_callback(cq["id"], res[:190])
        tg.send_message(cq["message"]["chat"]["id"], res)
        return
    action, pid = data.split(":", 1)
    p = _pending.get(pid)
    if not p and pid.startswith("v"):          # คำขอจากโหมดเสียง (อีกโปรแกรมหนึ่ง) → ส่งผลผ่านไฟล์
        with open(os.path.join(config.DATA_DIR, f"vconfirm_{pid}.txt"), "w") as f:
            f.write(action)
        tg.answer_callback(cq["id"], "อนุญาตแล้ว" if action == "ok" else "ยกเลิกแล้ว")
        return
    if not p:
        tg.answer_callback(cq["id"], "คำขอนี้หมดอายุแล้ว")
        return
    p["ok"] = action == "ok"
    p["event"].set()
    tg.answer_callback(cq["id"], "อนุญาตแล้ว" if p["ok"] else "ยกเลิกแล้ว")


def _safe(fn, arg):
    try:
        fn(arg)
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        import self_heal
        self_heal.record(traceback.format_exc())


def check_config():
    key_for = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY",
               "ollama": "OLLAMA_URL", "cloud": "CLOUD_API_KEY"}.get(config.LLM_PROVIDER, "ANTHROPIC_API_KEY")
    need = ["TELEGRAM_BOT_TOKEN", key_for]
    missing = [k for k in need if not getattr(config, k)]
    if missing:
        raise SystemExit(f"❌ ยังไม่ได้ตั้งค่า {', '.join(missing)} ในไฟล์ .env")
    if not config.ALLOWED_USER_IDS:
        log("⚠️ ยังไม่ได้ตั้ง ALLOWED_USER_IDS — ส่ง /id หาบอทเพื่อดู ID แล้วใส่ในไฟล์ .env")


def main():
    global tg
    check_config()
    # กันเปิดบอทซ้อนกัน (สองตัวจะชนกันจน Telegram ไม่ตอบ: "Conflict")
    import fcntl
    lock_path = os.path.join(config.DATA_DIR, "bot.lock")
    _lock_f = open(lock_path, "w")
    try:
        fcntl.flock(_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("❌ มีบอทเปิดอยู่แล้ว (อย่าเปิดซ้อน) — หยุดก่อนด้วย bash stop_all.sh")
    _lock_f.write(str(os.getpid()))
    _lock_f.flush()
    tg = Telegram(config.TELEGRAM_BOT_TOKEN)
    try:
        tg._call("deleteWebhook", drop_pending_updates=False)  # กัน getUpdates ชนกับ webhook เก่า
    except Exception:  # noqa: BLE001
        pass
    me = tg.get_me()
    import prompts
    tg.set_commands(prompts.COMMANDS)          # กด / ในแชทจะเห็นเมนูคำสั่ง
    log(f"✅ บอท @{me['username']} พร้อมทำงาน (AI={config.LLM_PROVIDER}, mock={config.MOCK_PHONE})")
    threading.Thread(target=reminder_loop, daemon=True).start()
    if config.LLM_PROVIDER == "ollama":
        import ollama_client
        threading.Thread(target=ollama_client.warmup, daemon=True).start()   # โหลดโมเดลรอไว้ คำถามแรกไม่ช้า
    try:
        import self_heal                     # ซ่อมตัวเอง: ตรวจทุก 15 นาที + ซ่อมบัคที่เกิดซ้ำ + ย้อนกลับถ้าซ่อมแล้วพัง
        owner = sorted(config.ALLOWED_USER_IDS)[0] if config.ALLOWED_USER_IDS else None
        if owner and not config.ANDROID_APP:      # แอป APK: android_main ตั้งค่าเอง (แจ้งทั้งแอป + Telegram)
            import mind
            mind.start(lambda t: tg.send_message(owner, t))
            import app_brain
            app_brain.start(lambda t: tg.send_message(owner, t))
            self_heal.on_start(notify=lambda t: tg.send_message(owner, t), confirm=Ctx(owner).confirm)
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    try:
        import screen_tools
        screen_tools.adb_keepalive()         # คอยเชื่อม ADB ให้ติดตลอด
        import app_index
        app_index.ensure_background()        # สร้างรายชื่อแอป (ชื่อที่แสดงจริง) เบื้องหลัง
    except Exception:  # noqa: BLE001
        pass

    offset = None
    while True:
        try:
            updates = tg.get_updates(offset)
        except Exception as e:  # noqa: BLE001
            if "Conflict" in str(e):
                log("⚠️ มีบอทอีกตัวกำลังรันอยู่ (Conflict) — รอ 15 วิ แล้วลองใหม่ หยุดตัวซ้ำด้วย bash stop_all.sh")
                time.sleep(15)
            else:
                log("polling error:", e)
                time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            if "callback_query" in u:
                _safe(handle_callback, u["callback_query"])  # ตอบทันที ไม่ต้องรอ
            elif "message" in u:
                threading.Thread(target=_safe, args=(handle_message, u["message"]), daemon=True).start()


if __name__ == "__main__":
    main()
