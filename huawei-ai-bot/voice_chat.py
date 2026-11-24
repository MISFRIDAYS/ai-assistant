"""คุยกับผู้ช่วยด้วยเสียงบนแท็บเล็ตโดยตรง (ไม่ต้องเปิด Telegram)

  python voice_chat.py --wake   ผู้ช่วยประจำเครื่อง: พูด "สวัสดีผู้ช่วย ..." เมื่อไหร่ก็ได้ (แนะนำ)
  python voice_chat.py          คุยต่อเนื่องทันที (พูดว่า "จบ" หรือเงียบนาน = หยุด)
  python voice_chat.py --once   ถามครั้งเดียว
  python voice_chat.py --test   ทดสอบไมค์แบบเรียลไทม์

ไมค์ฟังแบบเรียลไทม์: รู้เองว่าพูดจบเมื่อเงียบ ~0.7 วินาที / AI ตอบแบบสตรีม เริ่มพูดได้ตั้งแต่ประโยคแรก
"""
import re
import os
import sys
import threading
import time
import traceback

import audio_stream
import config
import agent
import ui
import voice
from telegram_api import Telegram

STOP_WORDS = ("จบ", "พอแล้ว", "หยุด", "เลิกคุย", "ไม่มีแล้ว", "บาย", "ลาก่อน", "แค่นี้")
YES_WORDS = ("ใช่", "ตกลง", "ยืนยัน", "เอา", "ได้", "โอเค", "ok", "ส่งเลย", "ทำเลย", "อนุญาต")
VOICE_HINT = ("[ผู้ใช้คุยด้วยเสียง (ข้อความถอดจากเสียง อาจสะกดเพี้ยน ให้ตีความตามบริบท) "
              "คำตอบจะถูกพูดออกลำโพง: พูดเหมือนคนคุยกันจริงๆ ต่อหน้า ประโยคสั้น เป็นธรรมชาติ 1-2 ประโยค "
              "ไม่ใช้รายการ/หัวข้อ/อีโมจิ/สัญลักษณ์ ไม่อ่านลิงก์ (บอกว่าส่งลิงก์ไว้ในแชทแล้ว) "
              "เขียนตัวเลขแบบที่คนพูด ถ้ามีรายละเอียดยาว ให้ใส่ต่อท้ายหลังคำตอบหลัก (จะไปอยู่ใน Telegram) "
              "ถ้าเป็นคำสั่งให้ทำอะไร ต้องเรียกเครื่องมือทำทันที ห้ามตอบแค่ว่า 'จะทำให้' "
              "คำที่มักถอดเพี้ยน: แชร์=แชท, ไอจี/IG=Instagram]")
LOCK = os.path.join(config.DATA_DIR, "voice_chat.pid")
MIC = None
MIC_MODE = ""


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def owner_chat_id():
    if config.ANDROID_APP:
        return "app"                       # แอป: พูดกับพิมพ์ใช้ประวัติแชทเดียวกัน → คุยต่อเนื่องข้ามกันได้
    return min(config.ALLOWED_USER_IDS) if config.ALLOWED_USER_IDS else 0


class VoiceCtx:
    """ให้ tool ต่างๆ ทำงานในโหมดเสียง (ขออนุญาตด้วยเสียง, ส่งรูปไป Telegram)"""
    via_voice = True                           # สั่งด้วยเสียง → ส่งข้อความต้องยืนยันก่อน (VOICE_CONFIRM_SEND)

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.speaker = None
        self.confirming = False
        self.hold = False
        self.tg = Telegram(config.TELEGRAM_BOT_TOKEN) if config.TELEGRAM_BOT_TOKEN else None

    def ask(self, question, timeout=12):
        """ถามด้วยเสียงแล้วฟังคำตอบ"""
        voice.say(question)
        return listen_text(timeout=timeout, beep=True) or None

    def notify(self, text):
        """ข้อความความคืบหน้า/ผลของงานยาวๆ ที่ทำเบื้องหลัง → ส่งเข้า Telegram"""
        try:
            if self.tg and self.chat_id:
                self.tg.send_message(self.chat_id, text)
        except Exception as e:  # noqa: BLE001
            log("notify error", e)

    def status(self, text):
        """เริ่มทำงาน (เรียก tool) → ถ้ายังไม่ได้พูดอะไร ให้ตอบรับทันที ผู้ใช้จะได้รู้ว่ากำลังทำ"""
        self.acting = True                       # กำลังสั่งงานเครื่อง → ห้ามนับเสียงตัวเอง ("โอเคครับ") เป็นการพูดแทรก
        sp = self.speaker
        if sp is not None and sp.count == 0 and not getattr(sp, "_acked", False):
            sp._acked = True
            import voice_profile
            sp.feed(voice_profile.ack_word() + " ")

    def send_photo(self, path):
        if self.tg and self.chat_id:
            try:
                self.tg.send_photo(self.chat_id, path)
            except Exception as e:  # noqa: BLE001
                log("send_photo:", e)

    def send_file(self, path, kind="document"):
        if self.tg and self.chat_id:
            self.tg.send_file(self.chat_id, path, kind=kind)

    def add_reminder(self, minutes, text):
        import bot
        return bot.add_reminder(self.chat_id, minutes, text)

    def confirm(self, description):
        """ขอยืนยันด้วยเสียง + ปุ่มใน Telegram พร้อมกัน (ตอบทางไหนก็ได้)"""
        import uuid
        self.confirming = True                 # หยุดตรวจการพูดแทรกชั่วคราว
        pid = "v" + uuid.uuid4().hex[:10]
        flag = os.path.join(config.DATA_DIR, f"vconfirm_{pid}.txt")
        msg = None
        try:
            if self.tg and self.chat_id:      # ปุ่มใน Telegram (บอท Telegram จะเขียนผลลงไฟล์ให้)
                try:
                    kb = {"inline_keyboard": [[{"text": "✅ อนุญาต", "callback_data": f"ok:{pid}"},
                                               {"text": "❌ ยกเลิก", "callback_data": f"no:{pid}"}]]}
                    msg = self.tg.send_message(self.chat_id, f"🎤⚠️ ขออนุญาต:\n\n{description}", reply_markup=kb)
                except Exception:  # noqa: BLE001
                    msg = None
            t0 = time.time()                   # รอให้พูดประโยคก่อนหน้าจบก่อน
            while self.speaker and not self.speaker.q.empty() and time.time() - t0 < 20:
                time.sleep(0.1)
            while audio_stream.SPEAKING.is_set() and time.time() - t0 < 30:
                time.sleep(0.1)
            short = description.split("\n")[0][:80]
            ok = None
            # พูดคำถามใน thread แยก แล้วคอยฟังไปพร้อมกัน → ตอบ "ตกลง" แทรกได้ทันทีไม่ต้องรอพูดจบ
            # (คำถามไม่มีคำว่า ตกลง/ยกเลิก เพื่อไม่ให้ไมค์ได้ยินเสียงบอทแล้วนึกว่าผู้ใช้ตอบ)
            th = threading.Thread(target=voice.say, args=(f"ขอยืนยันก่อนนะครับ {short}",), daemon=True)
            th.start()
            mic = get_mic()
            frames = mic.watch_interrupt(lambda: th.is_alive()) if hasattr(mic, "watch_interrupt") else None
            if frames:
                voice.stop_playing()
                pcm = mic.utterance(initial=frames, end_silence=0.5, max_seconds=4)
                ans = voice.transcribe_pcm(pcm) if pcm else ""
                log(f"🎤 ตอบยืนยัน (แทรก): {ans or '(ไม่ได้ยิน)'}")
                ok = yes_or_no(ans)
            th.join(timeout=30)
            for attempt in range(2):
                if ok is not None or os.path.exists(flag):
                    break
                ans = listen_text(timeout=7, beep=False, accurate=False)
                log(f"🎤 ตอบยืนยัน: {ans or '(ไม่ได้ยิน)'}")
                ok = yes_or_no(ans)
                if ok is None and attempt == 0 and not os.path.exists(flag):
                    voice.say("ตอบว่า ตกลง หรือ ยกเลิกครับ")
            if ok is None and os.path.exists(flag):       # ตอบผ่านปุ่ม Telegram
                ok = open(flag).read().strip() == "ok"
            ok = bool(ok)
            import voice_profile
            voice.ack(f"ได้{voice_profile.pol()}" if ok else f"ยกเลิกแล้ว{voice_profile.pol()}")     # ไม่รอพูดจบ ทำงานต่อทันที
            if msg and self.tg:
                try:
                    self.tg.edit_message_text(self.chat_id, msg["message_id"],
                                              f"{'✅ อนุญาตแล้ว' if ok else '❌ ยกเลิกแล้ว'}\n\n{description}")
                except Exception:  # noqa: BLE001
                    pass
            return ok
        finally:
            self.confirming = False
            try:
                os.remove(flag)
            except OSError:
                pass


NO_WORDS = ("ไม่", "ยกเลิก", "อย่า", "หยุด", "ไม่เอา", "no", "cancel", "เลิก")
YES_WORDS2 = ("ตกลง", "ยืนยัน", "ใช่", "โอเค", "ได้", "เอา", "ส่ง", "พิมพ์", "ทำเลย", "อนุญาต", "ok", "yes",
              "เยส", "โอเค", "ถูก")
# คำรับเฉยๆ นับเป็น "ตกลง" เฉพาะตอนตอบสั้นๆ คำเดียว (ไม่งั้นไมค์ได้ยินเสียงบอทเอง "…นะครับ" แล้วนึกว่าผู้ใช้ตอบรับ)
YES_WEAK = ("ครับ", "ค่ะ", "คะ", "จ้า", "อืม", "อือ", "ฮะ")
# เสียงบอทเองที่ไมค์ได้ยิน (คำถามยืนยัน / อ่านทวนข้อความ) — ไม่ใช่คำตอบของผู้ใช้
_OWN_PROMPT = ("ขอยืนยัน", "ใช่ไหม", "จะส่งหา", "ตอบว่าตกลง", "กดส่งข้อความ")


def yes_or_no(text):
    """True = ยืนยัน, False = ยกเลิก, None = ฟังไม่ออก"""
    t = _norm(text or "").lower()
    if not t:
        return None
    if any(w in t for w in _OWN_PROMPT):
        return None
    if any(w in t for w in NO_WORDS):
        return False
    if any(w in t for w in YES_WORDS2):
        return True
    if len(t) <= 5 and any(t.startswith(w) for w in YES_WEAK):
        return True
    return None


MIC_HOLD = [0.0]     # ปุ่มไมค์/แผงผู้ช่วยกำลังใช้ไมค์ถึงเวลานี้ → ลูปคำปลุกห้ามปิดไมค์ (แม้ตั้ง "ปิดไมค์" ไว้)


def hold_mic(seconds=45):
    MIC_HOLD[0] = time.time() + seconds


def get_mic():
    global MIC, MIC_MODE
    if MIC is not None and hasattr(MIC, "reader_dead") and hasattr(MIC, "restart") \
            and MIC.reader_dead() and not getattr(MIC, "closed", False):
        log(f"🎙️ ไมค์หลุด ({getattr(MIC, 'dead', '') or 'ตัวอ่านหยุด'}) → เปิดใหม่")
        try:
            MIC.restart()
        except Exception as e:  # noqa: BLE001
            log("เปิดไมค์ใหม่ไม่ได้:", e)
            MIC = None
    if MIC is None:
        MIC, MIC_MODE = audio_stream.open_mic()
        names = {"realtime": "เรียลไทม์ (PulseAudio)", "realtime-amr": "เรียลไทม์ (AMR สตรีม)",
                 "chunk": "สำรอง (อัดทีละท่อน — ช้า)", "mock": "จำลอง"}
        log(f"🎙️ โหมดไมค์: {names.get(MIC_MODE, MIC_MODE)}")
        for w in audio_stream._why:
            log("   ↳", w)
    return MIC


_gate_log = [0.0]


def owner_voice(pcm, lenient=None):
    """เสียงนี้เป็นของเจ้าของเครื่องไหม (ถ้ายังไม่ได้สอนเสียง = ผ่านหมด ยกเว้นแอปที่บังคับลงทะเบียนเสียง)"""
    if getattr(config, "REQUIRE_VOICE_ENROLL", False) and not _ENROLLING[0]:
        try:
            import speaker_id
            if not speaker_id.enrolled():
                if time.time() - _gate_log[0] > 60:
                    _gate_log[0] = time.time()
                    log("🔒 ยังไม่ได้ลงทะเบียนเสียง — ไม่รับคำสั่งเสียงจนกว่าจะลงทะเบียนในแอป")
                return False
        except Exception as e:  # noqa: BLE001
            log("enroll check error:", e)
    if not config.SPEAKER_VERIFY:
        return True
    try:
        import speaker_id
        # โหมดคำปลุกผ่อนเกณฑ์ลงนิดหน่อย (มีคำว่า "ผู้ช่วย" กรองอีกชั้น) / ฟังตลอดใช้เกณฑ์เต็ม
        if lenient is None:
            lenient = 0.0 if always_listen() else 0.04
        ok, score = speaker_id.check(pcm, lenient=lenient)
    except Exception as e:  # noqa: BLE001
        log("speaker check error:", e)
        return True
    if score is not None:
        th = speaker_id.last.get("th")
        log(("🗣️ เสียงเจ้าของ" if ok else "🔇 ไม่ใช่เสียงเจ้าของ"), f"(คะแนน {score} / ต้องได้ {th})")
    return ok


_COMMANDISH = re.compile(r"(เปิด|ปิด|ส่ง|พิมพ์|ตอบ|โทร|รับสาย|วางสาย|ค้นหา|หาให้|ช่วย|ขอ|เช็ค|เช็ก|ดู|อ่าน|ลด|เพิ่ม|"
                         r"เล่น|หยุด|ถ่าย|จำ|ลืม|บอก|ตั้ง|ปลุก|เตือน|อากาศ|ข่าว|ราคา|กี่โมง|แบต|ไหม|มั้ย|หรือเปล่า|"
                         r"ป่าว|อะไร|ยังไง|เท่าไหร่|ที่ไหน|ใคร|ทำไม|แปล|สรุป|ผู้ช่วย|กรอก|ฟอร์ม|ขั้นตอน|ศึกษา|เรียนรู้|ข้อมูล|ข้าม|ยกเลิก|จบ|ซ่อม|ย้อน|แก้บัค)")


def always_listen():
    """โหมดฟังตลอด (ไม่ต้องเรียกคำปลุก): เปิดใน .env ALWAYS_LISTEN=1 หรือสั่ง 'ฟังตลอด'"""
    return config.ALWAYS_LISTEN or os.path.exists(os.path.join(config.DATA_DIR, "always_listen"))


def set_always(on):
    p = os.path.join(config.DATA_DIR, "always_listen")
    if on:
        open(p, "w").close()
    elif os.path.exists(p):
        os.remove(p)


def listen_text(timeout=None, beep=True, max_seconds=15.0, accurate=True, check_owner=True):
    """ฟังจนผู้ใช้พูดจบ แล้วคืนข้อความ ("" ถ้าไม่มีใครพูดภายใน timeout)"""
    if beep:
        voice.beep()
    ui.listening()
    g = None
    # ระบบเสียงของ Google ไม่ส่งเสียงดิบกลับมา → ตรวจว่าเป็นเสียงเจ้าของไม่ได้
    # ใช้เฉพาะตอนเพิ่งเรียก "ผู้ช่วย" (ผ่านการตรวจเสียงแล้ว) · ช่วงฟังต่อหลังตอบ ใช้ไมค์ของแอปที่ตรวจเสียงได้
    if not check_owner or not config.SPEAKER_VERIFY:
        try:                                             # มีระบบรู้จำเสียงของเครื่อง (Google) → แม่นกว่า ฟรี
            import google_stt
            g = google_stt.listen(timeout if timeout else 8.0)
        except Exception as e:  # noqa: BLE001
            log("google stt error:", e)
            g = None
    if g is not None:
        if g:
            ui.thinking()
            ui.heard(g)
            voice._last.update(engine="Google", dropped="")
        else:
            ui.idle()
        return g
    t0 = time.time()
    end_sil = max(1.2, config.VAD_END_SILENCE)          # เว้นจังหวะคิดระหว่างพูดได้ ไม่ตัดเร็วเกิน
    while True:
        left = None if timeout is None else timeout - (time.time() - t0)
        if left is not None and left <= 0.3:
            ui.idle()
            return ""
        pcm = get_mic().utterance(wait_timeout=left, max_seconds=max_seconds, end_silence=end_sil)
        if not pcm:
            ui.idle()
            return ""
        # เสียงสั้นๆ (เสียง "ครับ" ของบอทเอง/เคาะ/เสียงคนอื่น) → ไม่จบการฟัง ฟังต่อจนหมดเวลา
        if audio_stream.is_speechy(pcm, getattr(get_mic(), "noise", 0.0)) and \
                (not check_owner or owner_voice(pcm, lenient=config.FOLLOWUP_LENIENT)):
            break
    ui.thinking()
    t1 = time.time()
    text = voice.transcribe_pcm(pcm, accurate=accurate)
    if text:
        ui.heard(text)
    log(f"🎤 ({len(pcm) / 32000:.1f}s เสียง, แปลง {time.time() - t1:.1f}s {voice._last['engine']})",
        text or "(ไม่ใช่คำพูด)")
    return text


class Interrupted(Exception):
    pass


def answer(text, ctx):
    """ส่งให้ AI แล้วพูดคำตอบทันทีที่ AI เริ่มพิมพ์ (สตรีม)
    ระหว่างนั้นคอยฟังว่าผู้ใช้พูดแทรกไหม → ถ้าพูดแทรก หยุดพูดทันทีแล้วคืน "คำพูดใหม่" ของผู้ใช้"""
    content = [{"type": "text", "text": VOICE_HINT}, {"type": "text", "text": text}]
    t0 = time.time()
    first = []
    speaker = voice.Speaker(max_chars=config.VOICE_MAX_SPEAK)
    ctx.speaker = speaker
    ui.thinking()
    cancel = threading.Event()
    result = {}

    buf = [""]

    def on_text(delta):
        if cancel.is_set():
            raise Interrupted()
        if not first:
            first.append(time.time())
            log(f"⚡ AI เริ่มตอบใน {first[0] - t0:.1f}s")
        speaker.feed(delta)
        buf[0] += delta
        ui.speaking(buf[0])

    def run():
        try:
            result["reply"] = agent.chat(ctx.chat_id, content, ctx, on_text=on_text)
            if result["reply"] and not buf[0] and not cancel.is_set():
                speaker.feed(result["reply"])    # คำตอบที่ไม่ได้สตรีม (เช่น ระบบลงมือเอง) ก็ต้องพูดออกมา
        except Interrupted:
            result["reply"] = "(ถูกพูดแทรก)"
        except Exception as e:  # noqa: BLE001
            result["error"] = e
        finally:
            speaker.close()

    ctx.acting = False
    th = threading.Thread(target=run, daemon=True)
    th.start()
    frames = None
    if config.BARGE_IN:
        # ระหว่างบอทกำลังทำงานหลายขั้น (เปิดแอป → หาแชท → พิมพ์ → ส่ง) ไม่รับการพูดแทรก
        # ไม่งั้นไมค์ได้ยินเสียง "โอเคครับ" ของบอทเอง แล้วยกเลิกงานกลางทาง (ตอบโอเคแต่ไม่ทำต่อ)
        frames = get_mic().watch_interrupt(lambda: th.is_alive() or speaker.busy(),
                                           paused=lambda: ctx.confirming or (getattr(ctx, "acting", False)
                                                                             and th.is_alive()))
    else:
        th.join()
    if frames:
        cancel.set()
        speaker.stop()
        log("✋ ผู้ใช้พูดแทรก", f"(เสียง/เกณฑ์ = {getattr(get_mic(), 'last_barge', None)})")
        pcm = get_mic().utterance(initial=frames, end_silence=config.VAD_END_SILENCE)
        new_text = voice.transcribe_pcm(pcm, accurate=True) if pcm else ""
        log("🎤 (พูดแทรก)", new_text or "(ฟังไม่ออก)")
        # พูดต่อจากประโยคเดิม (เว้นจังหวะนิดเดียวแล้วบอทตัดว่าจบ) → รวมเป็นคำสั่งเดียว
        if new_text and not getattr(ctx, "acting", False) and time.time() - t0 < 12 and \
                re.match(r"^\s*(แล้ว|และ|ต่อ|กับ|ด้วย|พร้อม|ไปที่|ที่|ส่ง|พิมพ์|ว่า|บอกว่า)", new_text):
            merged = f"{text} {new_text}".strip()
            log("🔗 รวมเป็นคำสั่งเดียว:", merged)
            return merged
        return new_text
    speaker.t.join(timeout=300)
    ui.done(result.get("reply", "") or buf[0])
    if "error" in result:
        import traceback
        log("❗ answer error:", "".join(traceback.format_exception(
            type(result["error"]), result["error"], result["error"].__traceback__))[-1200:])
        import self_heal
        self_heal.note(result["error"])
        if not buf[0]:                      # ยังไม่ได้พูดอะไรเลย → ขอโทษสั้นๆ (ไม่ทำให้ทั้งระบบตาย)
            voice.say("ขอโทษครับ คำสั่งนี้มีปัญหา ลองใหม่อีกทีได้ไหมครับ")
        return None
    if config.VOICE_TO_TELEGRAM and ctx.tg and ctx.chat_id and result.get("reply"):
        try:                                   # ส่งบทสนทนาฉบับเต็มเข้า Telegram (อ่านย้อนหลัง/กดลิงก์ได้)
            ctx.tg.send_message(ctx.chat_id, f"🎤 {text}\n\n{result['reply']}")
        except Exception as e:  # noqa: BLE001
            log("telegram:", e)
    log(f"🤖 ({time.time() - t0:.1f}s ทั้งหมด)", result.get("reply", "")[:120])
    try:
        import perf
        stt = voice._last.get("stt_time") or 0.0
        st = {"stt": stt, "first_token": (first[0] - t0 + stt) if first else None,
              "first_sound": (speaker.first_play - t0 + stt) if speaker.first_play else None,
              "total": time.time() - t0 + stt}
        perf.record("voice", text, engine=voice._last.get("engine", ""), ok=perf.looks_ok(result.get("reply")),
                    **{k: v for k, v in st.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- คำสั่งด่วน (ไม่ต้องรอ AI)

_POLITE = r"(ให้หน่อย|หน่อย|ให้ที|ที|ด้วย|ครับ|ค่ะ|คะ|นะ|จ้า|เลย|ให้)*$"


def quick_command(text, ctx):
    """คำสั่งง่ายๆ ที่ทำได้ทันที (~0.3 วินาที) คืนคำตอบที่จะพูด หรือ None ถ้าต้องให้ AI คิด"""
    import phone_tools
    import quick
    import voice_profile
    import appoint
    import send_confirm
    d = send_confirm.handle_text(text, ctx) or appoint.handle_text(text, ctx)   # กำลังถามตอบอยู่ → คำตอบมาที่นี่ก่อน
    if d:
        return d
    d = quick.listen_mode(text)
    if d:
        return d
    import app_learn
    import forms
    import user_profile
    import app_skills
    import info
    import self_heal
    import mind
    import vision
    import device
    import social
    import inapp
    import app_brain
    import plugins
    import autoreply
    import contacts
    import app_tasks
    import media
    import screen_context
    import app_test
    import contact_scan
    import perf
    import proactive
    import routines
    for mod in (routines, proactive, self_heal, user_profile, contacts, autoreply, contact_scan, screen_context, app_test, perf, app_learn, forms, social, inapp, app_tasks, media, app_skills, device, app_brain, plugins, info, vision, mind):   # ซ่อมตัวเอง · ข้อมูลของฉัน · เรียนรู้แอป · ฟอร์ม
        try:
            d = mod.handle_text(text) if mod is user_profile else mod.handle_text(text, ctx)
        except Exception as e:  # noqa: BLE001
            self_heal.note(e)
            d = f"ทำไม่สำเร็จ: {e}"
        if d:
            import recovery
            if recovery.is_failure(mod.__name__, d):
                recovery.note(mod.__name__, text, d)
                return None
            return d

    def _ack():                               # งานส่งข้อความใช้ ~10-20 วิ → ตอบรับก่อน ผู้ใช้จะรู้ว่ากำลังทำ
        try:
            voice.say(f"{voice_profile.ack_word()} กำลังส่งให้", wait=False)
        except Exception:  # noqa: BLE001
            pass
    d = quick.dm(text, ctx, on_start=_ack)    # "ส่งข้อความหาต้นในไอจีว่า..." → ทำจริงทุกขั้น ไม่ผ่าน AI
    if d:
        return d
    import fastpath
    d = fastpath.direct(text, ctx)            # แจ้งเตือน · เช็คเครื่อง · ตอบแชทคนที่ทักมา
    if d:
        return d
    t = _norm(text).lower()
    prev = None
    while prev != t:                          # ตัดคำเติมหน้าประโยค: "โอเค เอ่อ เข้า instagram"
        prev = t
        t = re.sub(r"^(โอเค|ok|okay|เอ่อ|อ่า|อืม|เออ|แล้วก็|งั้น|ช่วย|ขอ)\s*", "", t).strip()
    if not t or len(t) > 40:
        return None
    if re.match(r"^(เปิด)ไฟฉาย" + _POLITE, t):
        phone_tools.torch({"on": True}, ctx)
        return "เปิดไฟฉายแล้วครับ"
    if re.match(r"^(ปิด)ไฟฉาย" + _POLITE, t):
        phone_tools.torch({"on": False}, ctx)
        return "ปิดไฟฉายแล้วครับ"
    if re.match(r"^(ตอนนี้)?(กี่โมง|เวลาเท่าไหร่|เวลาเท่าไร)" + _POLITE, t):
        n = agent.now_local()
        return f"ตอนนี้ {n.hour} นาฬิกา {n.minute} นาทีครับ"
    if re.match(r"^(แบต|แบตเตอรี่)(เหลือ)?(เท่าไหร่|เท่าไร|กี่เปอร์เซ็นต์|กี่เปอร์)" + _POLITE, t):
        import json
        try:
            b = json.loads(phone_tools.battery_status({}, ctx))
            charging = "กำลังชาร์จอยู่" if b.get("plugged") not in (None, "UNPLUGGED") else ""
            return f"แบตเหลือ {b.get('percentage')} เปอร์เซ็นต์ครับ {charging}".strip()
        except Exception:  # noqa: BLE001
            return None
    m = re.match(r"^(เปิด|เข้า)(แอป|แอพ|แอ็พ)?(.+?)" + _POLITE, t)
    if m:
        name = m.group(3)
        key = phone_tools.ALIASES.get(name, name)
        known = key in phone_tools.COMMON_APPS or key in phone_tools.APP_LINKS
        if not known:
            installed = {c.split("/")[0] for c in phone_tools._launcher_components()}
            known = any(key in p.lower() for p in installed) and len(key) >= 3
        if not known:
            return None                      # ไม่แน่ใจ → ให้ AI จัดการ
        res = phone_tools.open_app({"app": key}, ctx)
        if res.startswith("ERROR") or "หลายแอป" in res:
            return None
        import voice_profile
        return voice_profile.ack_word()
    import quick                              # Wi-Fi บลูทูธ ความสว่าง ปิดแอป ล้างแรม ฯลฯ
    return quick.handle(text, ctx)


def is_stop(text):
    t = text.strip(" .!")
    return any(t.startswith(w) or t == w for w in STOP_WORDS)


def followup_ok(text):
    """ช่วงฟังต่อหลังตอบ (ไม่ต้องเรียกชื่อ): กันเสียงทีวี/คนคุยกัน/เสียงบอทเองถูกนับเป็นคำสั่ง"""
    try:
        import appoint
        import send_confirm
        if appoint.active() or send_confirm.active():                             # กำลังถามวัน/เวลา/เรื่องนัด → คำตอบสั้นๆ ("ใช่" "พรุ่งนี้") ก็รับ
            lp = voice._last.get("logprob")
            return len(_norm(text or "")) >= 2 and not (lp is not None and lp < -1.0)
    except Exception:  # noqa: BLE001
        pass
    t = re.sub(r"^\s*(ครับผม|ครับ|ค่ะ|คะ|อืม|เอ่อ|อ่า)[\s,.]*", "", text or "").strip()
    if len(_norm(t)) < 3:
        return False
    lp = voice._last.get("logprob")
    if lp is not None and lp < -0.8:                     # ฟังไม่ชัด → ไม่เดา
        return False
    if find_wake(t)[0] or is_stop(t):
        return True
    return bool(_COMMANDISH.search(t)) or len(_norm(t)) >= 14


def mic_closed(e):
    """ไมค์ถูกปิด/หยุดส่งเสียงระหว่างฟัง (ผู้ใช้กดปิดเอง) — ไม่ใช่บั๊กที่ต้องซ่อม"""
    return isinstance(e, RuntimeError) and str(e).startswith("ไมค์หยุดส่งเสียง")


def conversation(ctx, first_text=None, follow_timeout=None):
    """คุยต่อเนื่อง: ตอบแล้วฟังต่อโดยไม่ต้องเรียกชื่อ จนกว่าจะเงียบเกินเวลา"""
    follow_timeout = follow_timeout or config.FOLLOWUP_SECONDS
    text = first_text
    deadline = None
    just_called = first_text is None              # เพิ่งเรียก "เฮ้ยผู้ช่วย" แล้วรอคำสั่ง → ไม่ต้องเช็กเสียงเจ้าของซ้ำ
    while True:
        heard_follow = False
        if text is None:
            if deadline is None:
                deadline = time.time() + follow_timeout
            left = deadline - time.time()
            try:
                text = listen_text(timeout=left, beep=config.VOICE_BEEP, check_owner=not just_called) if left > 0.5 else ""
            except RuntimeError as e:
                if not mic_closed(e):
                    raise
                log("🎙️ ไมค์ถูกปิดระหว่างฟังต่อ → จบการคุย")     # ผู้ใช้กดปิดไมค์เอง ไม่ใช่บั๊ก
                return
            heard_follow = not just_called
            just_called = False
        if not text:
            return
        if heard_follow and not followup_ok(text):
            log("👂 (ฟังต่อ) ข้าม — น่าจะไม่ใช่คำสั่งถึงผู้ช่วย:", text[:60])
            text = None
            continue
        deadline = None
        # เสียง "ครับ" ของบอทเองที่ไมค์ได้ยิน (ตอนตอบรับแบบไม่ปิดไมค์) → ตัดทิ้ง
        text = re.sub(r"^\s*(ครับผม|ครับ|ค่ะ|คะ)[\s,.]*", "", text).strip()
        if not text:
            text = None
            continue
        if is_stop(text):
            import voice_profile
            voice.say(f"ได้{voice_profile.pol()} ไว้คุยกันใหม่นะ")
            return
        if config.QUICK_COMMANDS:
            tq = time.time()
            try:
                quick = quick_command(text, ctx)
            except Exception as e:  # noqa: BLE001
                log("quick error:", e)
                quick = None
            if quick:
                log("⚡ คำสั่งด่วน:", quick)
                try:
                    import perf
                    stt = voice._last.get("stt_time") or 0.0
                    perf.record("quick", text, stt=stt, total=time.time() - tq + stt, ok=perf.looks_ok(quick))
                except Exception:  # noqa: BLE001
                    pass
                ui.done(quick)                # ข้อความเต็มแสดงบนจอ
                voice.say(voice.speakable(quick))   # พูดแค่ช่วงแรก (ไม่อ่านรายการยาวทั้งหมด)
                if config.WAKE_EACH_TIME and not always_listen():
                    return                    # ต้องเรียก "เฮ้ยผู้ช่วย" ใหม่ทุกคำสั่ง (ไม่ฟังต่อเอง)
                text = None
                continue
        text = answer(text, ctx) or None      # ถ้าผู้ใช้พูดแทรก → ทำคำสั่งใหม่ต่อทันที
        if text is None and config.WAKE_EACH_TIME and not always_listen():
            return


def _norm(t):
    return re.sub(r"[\s,.!?ๆ]", "", t)


def _rest_after(text, norm_end):
    """คืนข้อความต้นฉบับ (มีเว้นวรรค) หลังตำแหน่งที่ norm_end ในข้อความแบบตัดช่องว่าง"""
    count = 0
    for pos, ch in enumerate(text):
        if count >= norm_end:
            rest = text[pos:]
            break
        if not re.match(r"[\s,.!?ๆ]", ch):
            count += 1
    else:
        rest = ""
    rest = rest.strip(" ,.!?")
    return re.sub(r"^(ครับ|ค่ะ|จ้า)\s*", "", rest).strip(" ,.!?")


# คำทัก/คำเติมที่พูดก่อนเรียกผู้ช่วยได้ ("เอ่อ เฮ้ย ผู้ช่วย") — นอกจากนี้ คำปลุกต้องอยู่ต้นประโยค
_LEAD = re.compile(r"^(?:เฮ้ย|เฮ้|เฮ|เห้ย|เห้|เฮย|โอเคร|โอเค|ok|okay|hey|hi|หวัดดี|สวัสดี|ดีจ้า|นี่|อ่า|เอ่อ|อืม|"
                   r"ครับ|ค่ะ|คะ|ว่าไง|จ้า|น้อง)*$", re.I)
# "ผู้ช่วย" ที่เป็นส่วนของตำแหน่งงาน ("ผู้ช่วยแพทย์") ไม่ใช่การเรียก
_ROLE_AFTER = re.compile(r"^(?:แพทย์|ผู้จัดการ|ศาสตราจารย์|ผู้อำนวยการ|พยาบาล|ทันตแพทย์|เภสัช|ช่าง|ครู|รัฐมนตรี|"
                         r"เลขา|เจ้าหน้าที่|ผู้กำกับ|ทนาย|ผู้ใหญ่บ้าน|นักวิจัย|ผู้สอน|ฝ่าย|ผู้ว่า|ส\.ส|หัวหน้า|ร้าน|เชฟ)")


def _wake_at(n, i, length):
    """คำปลุกที่ตำแหน่ง i นับไหม: ข้างหน้าต้องเป็นแค่คำทัก และข้างหลังไม่ใช่ชื่อตำแหน่งงาน"""
    return bool(_LEAD.match(n[:i])) and not _ROLE_AFTER.match(n[i + length:])


def find_wake(text):
    """คืน (เจอคำปลุก, คำสั่งที่พูดต่อท้าย) — ยอมให้สะกดเพี้ยนได้เล็กน้อย
    ต้องพูดต้นประโยค (มีคำทักนำหน้าได้) กันคำว่า "ผู้ช่วย" กลางประโยค/จากทีวีปลุกเอง"""
    import difflib
    n = _norm(text)
    if re.search(r"ผู้ช[่้]?[วอ]ย" + _ROLE_AFTER.pattern[1:], n):
        return False, ""                     # พูดถึงตำแหน่งงาน ("ผู้ช่วยแพทย์") ไม่ใช่เรียกผู้ช่วย
    for w in sorted(config.WAKE_WORDS, key=len, reverse=True):
        wn = _norm(w)
        i = n.find(wn)
        if i >= 0 and _wake_at(n, i, len(wn)):
            return True, _rest_after(text, i + len(wn))
    # ค้นแบบคล้าย: ดูช่วงต้นประโยค (คำปลุกมักอยู่ต้นประโยค)
    head = n[:20]
    for w in sorted(config.WAKE_WORDS, key=len, reverse=True):
        wn = _norm(w)
        if len(wn) < 9:          # คำสั้นๆ อย่าง "ผู้ช่วย" ต้องตรงเป๊ะ (กันสับสนกับ "ผู้ชาย")
            continue
        for L in (len(wn) - 1, len(wn), len(wn) + 1):
            for i in range(0, max(1, len(head) - L + 1)):
                if difflib.SequenceMatcher(None, head[i:i + L], wn).ratio() >= 0.78 and _wake_at(n, i, L):
                    return True, _rest_after(text, i + L)
    # เสียงเรียกที่ถอดเพี้ยนบ่อย: "เฮ้ย พุชไว", "เฮ้ บุชไว้", "เฮ้ย บูชัย" → ดูโครงพยัญชนะ ผ-ช-ว/ย หลังคำทัก
    m = _CALL.match(text.strip())
    if m and _WAKE_SKEL.match(_skeleton(m.group("w"))):
        return True, _rest_after(text, len(_norm(text[:m.end()])))
    return False, ""


_CALL = re.compile(r"^\s*(?:เฮ้ย|เฮ้|เฮ|เห้ย|เห้|เฮย|โอเค|โอเคร|ok|หวัดดี|สวัสดี|ดีจ้า|นี่)\s*(?P<w>[ก-๙A-Za-z]{2,8})")
# ต้องมี ว ตาม หรือเป็น "บูชัย" ที่ถอดเพี้ยนบ่อย ("พุชไว" "บุชเว้" ผ่าน · "พี่จ๋า" "พี่ชาย" ไม่ผ่าน)
_WAKE_SKEL = re.compile(r"^(?:[ผพบปฟ][ชซฉจ]ว|บชย)")


def _skeleton(word):
    """เอาเฉพาะพยัญชนะต้นๆ (ตัดสระ/วรรณยุกต์) — "พุชไว" → "พชว", "ผู้ช่วย" → "ผชวย" """
    return re.sub(r"[^ก-ฮ]", "", re.sub(r"[ะาำิีึืุูเแโใไๅ็่้๊๋์ั]", "", word))


def mic_watchdog(ctx):
    """แจ้งเตือนเมื่อ Android ปิดไมค์ (มักเกิดตอน Termux อยู่เบื้องหลัง/ปิดจอ)"""
    warned = False
    while True:
        time.sleep(5)
        mic = MIC
        if mic is None or not hasattr(mic, "silent_for"):
            continue
        blocked = mic.silent_for() > 8
        if blocked and not warned:
            warned = True
            msg = ("🎙️ ไมค์ถูกแอปอื่นใช้อยู่ชั่วคราว (เช่น กำลังโทร/อัดเสียง/วิดีโอคอล หรือแอปที่เปิดอยู่ขอใช้ไมค์) "
                   "— ปิดแอปนั้นแล้วผู้ช่วยจะกลับมาฟังเอง / พิมพ์สั่งผ่านปุ่มลอยได้ตลอด") if config.ANDROID_APP else \
                  ("🎙️ ไมค์ถูกระบบปิดชั่วคราว (Termux อยู่เบื้องหลัง) — เปิดหน้า Termux ค้างไว้ "
                   "หรือย่อเป็นหน้าต่างลอยเล็กๆ แล้วพูดได้ตามปกติ / สั่งผ่าน Telegram ได้ตลอด")
            log(msg)
            os.system("termux-notification --id aimic -t '🎙️ ผู้ช่วยฟังไม่ได้ตอนนี้' "
                      "-c 'เปิด Termux ค้างไว้ (หรือหน้าต่างลอย) เพื่อสั่งด้วยเสียง' >/dev/null 2>&1")
            if config.VOICE_TO_TELEGRAM and ctx.tg and ctx.chat_id:
                try:
                    ctx.tg.send_message(ctx.chat_id, msg)
                except Exception:  # noqa: BLE001
                    pass
        elif not blocked and warned:
            warned = False
            log("🎙️ ไมค์กลับมาใช้ได้แล้ว")
            os.system("termux-notification-remove aimic >/dev/null 2>&1")


def announce_notifications(ctx):
    """มีแจ้งเตือนใหม่ → อ่านให้ฟัง แล้วถามว่าจะตอบกลับไหม"""
    import notify_watch
    items = notify_watch.pending()
    if not items:
        return
    chats = [n for n in items if n["app"] in notify_watch.CHAT_APPS]
    if len(items) == 1:
        speech = notify_watch.describe(items[0])
    else:
        speech = f"มีแจ้งเตือนใหม่ {len(items)} รายการ " + " ".join(
            notify_watch.describe(n, max_len=60) + "," for n in items[:4])
    log("🔔", speech)
    if config.NOTIFY_TELEGRAM and ctx.tg and ctx.chat_id:
        try:
            ctx.tg.send_message(ctx.chat_id, "🔔 " + "\n".join(notify_watch.describe(n, 300) for n in items))
        except Exception:  # noqa: BLE001
            pass
    if not chats:
        voice.say(speech)
        return
    voice.say(speech + " จะตอบกลับไหมครับ")
    reply = listen_text(timeout=8, beep=False)
    if not reply or yes_or_no(reply) is False or is_stop(reply):
        voice.ack("โอเคครับ")
        return
    import share_tools
    msg = share_tools.reply_text(reply)
    if not msg or yes_or_no(reply) is True and len(msg) <= 4:      # "ตอบ" / "ใช่" เฉยๆ → ถามข้อความ
        voice.say("จะตอบว่าอะไรครับ")
        msg = share_tools.reply_text(listen_text(timeout=10, beep=False) or "")
        if not msg:
            voice.ack("โอเคครับ")
            return
    target = chats[0]
    for n in chats:                                                # พูดชื่อคนไหน → ตอบคนนั้น
        if (n.get("title") or "").strip() and n["title"].strip() in reply:
            target = n
    app = notify_watch.APP_KEY.get(target["app"])
    if not app:
        voice.say(f"ตอบ {target['app']} อัตโนมัติยังไม่ได้ครับ")
        return
    voice.say(f"ตอบ {target.get('title')} ว่า {msg} นะครับ", wait=False)
    log(f"💬 ตอบแจ้งเตือน {app} → {target.get('title')}: {msg!r}")
    res = share_tools.send_dm({"app": app, "to": target.get("title", ""), "text": msg}, ctx)
    log("💬", res[:150])
    voice.say("ส่งแล้วครับ" if not res.startswith("ERROR") else "ส่งไม่สำเร็จครับ " + res[6:80])
    conversation(ctx)


def wake_loop(ctx):
    global MIC
    log("👂 รอคำปลุก:", ", ".join(config.WAKE_WORDS))
    threading.Thread(target=mic_watchdog, args=(ctx,), daemon=True).start()
    ui.idle()
    import notify_watch
    notify_watch.start()
    recent = []
    voice.warmup()
    last_warm = time.time()
    while True:
        try:
            if config.paused() or config.mic_off():   # ปิดผู้ช่วย/ปิดไมค์ไว้ → ปล่อยไมค์ แล้วรอจนเปิดใหม่
                if time.time() < MIC_HOLD[0] or (MIC is not None and getattr(MIC, "owner", None) is not None):
                    time.sleep(1.0)                    # ปุ่มไมค์/แผงผู้ช่วยกำลังฟังอยู่ → ไม่ปิดไมค์กลางประโยค
                    continue
                if MIC is not None:
                    MIC.close()
                    MIC = None
                    log("⏸️ ปิดไมค์อยู่ — หยุดฟังคำสั่งเสียง")
                time.sleep(1.5)
                continue
            if config.NOTIFY_ANNOUNCE:
                announce_notifications(ctx)
            try:                                       # ผู้ช่วยเชิงรุก: สรุปเช้า/เตือนก่อนนัด → พูดเองตอนว่าง
                import proactive
                for m in proactive.pending_speech():
                    log("💡", m.replace("\n", " · ")[:120])
                    voice.say(proactive.spoken(m))
            except Exception as e:  # noqa: BLE001
                log("proactive say:", e)
            if _ENROLLING[0]:                          # กำลังสอนเสียง → ไม่แย่งไมค์
                time.sleep(0.5)
                continue
            pcm = get_mic().utterance(max_seconds=12 if always_listen() else 7.4, end_silence=config.VAD_END_SILENCE,
                                      wait_timeout=1.5)          # คืนทุก 1.5 วิ ถ้าเงียบ (เช็คงานอื่น/การสอนเสียง)
            if not pcm or len(pcm) / 32000 > (12 if always_listen() else 7.5):   # ยาวเกิน = ทีวี/คนคุยกัน
                continue
            if not audio_stream.is_speechy(pcm, getattr(get_mic(), "noise", 0.0),
                                           config.VOICE_MIN_SPEECH * (1.15 if always_listen() else 1.0)):
                if time.time() - _gate_log[0] > 20:          # บอกใน log ว่าทำไมไม่ตอบ (เสียงเบา/สั้นเกิน)
                    _gate_log[0] = time.time()
                    sec, peak = audio_stream.speech_stats(pcm, getattr(get_mic(), "noise", 0.0))
                    log(f"🎚️ เสียงเบา/สั้นเกิน ไม่ถอดเสียง (พูด {sec:.1f} วิ ดัง {int(peak)}) — ปรับ ⚙️ ความไวไมค์ เป็น \"ไว\" ได้")
                continue                              # เสียงเคาะ/ลม/เสียงสั้นๆ → ไม่ส่งถอดเสียงเลย
            is_owner = owner_voice(pcm)
            near = False
            if not is_owner:
                try:
                    import speaker_id
                    near = speaker_id.near()
                except Exception:  # noqa: BLE001
                    pass
            if not is_owner and ((always_listen() is False and len(pcm) / 32000 <= 3.5) or near):
                pass                                  # ประโยคสั้น/เสียงเกือบผ่าน → ถอดดูก่อน รับเฉพาะถ้ามีคำปลุก "ผู้ช่วย"
            elif not is_owner:                        # เสียงคนอื่น/ทีวี → ไม่แปลงเสียงเลย (ประหยัดโควตา)
                continue
            now = time.time()
            recent = [t for t in recent if now - t < 60]
            if len(recent) >= 20:                     # กันใช้โควตาเกิน (สูงสุด 20 ครั้ง/นาที)
                continue
            recent.append(now)
            always = always_listen()
            text = voice.transcribe_pcm(pcm, accurate=always, wake=not always)
            if not text:
                d = voice._last.get("dropped") or ""
                if d and is_owner and find_wake(d)[0]:    # คำปลุกที่ฟังไม่ชัด → รับเฉพาะเสียงเจ้าของ
                    log("👂 ได้ยินคำปลุก (เสียงไม่ชัด):", d[:40])
                    text = config.WAKE_WORDS[0] if config.WAKE_WORDS else "ผู้ช่วย"
                else:
                    continue
            hit, rest = find_wake(text)
            if not is_owner and not hit:
                continue                              # เสียงไม่ใช่เจ้าของ และไม่ได้เรียกผู้ช่วย → ไม่สนใจ
            if always and not hit:
                # โหมดฟังตลอด: ทุกประโยคจากเจ้าของ = คำสั่ง (ไม่ต้องเรียก "ผู้ช่วย")
                t = re.sub(r"^\s*(ครับผม|ครับ|ค่ะ|คะ|อืม|เอ่อ|อ่า)[\s,.]*", "", text).strip()
                if len(_norm(t)) < 3:
                    continue
                if (voice._last.get("logprob") or 0) < -0.75:   # ถอดเสียงไม่มั่นใจ (เสียงไกล/ทีวี) → ไม่เดาทำคำสั่ง
                    log("👂 (ฟังตลอด) ข้าม — ฟังไม่ชัด:", t[:60])
                    continue
                if not _COMMANDISH.search(t):        # ไม่มีคำสั่ง/คำถามเลย (คุยกัน/ทีวี) → ข้ามโดยไม่เรียก AI
                    log("👂 (ฟังตลอด) ข้าม — ไม่ใช่คำสั่ง:", t[:60])
                    continue
                log("👂 (ฟังตลอด) ได้ยิน:", t)
                try:
                    import screen_context
                    screen_context.scan_async()
                except Exception:  # noqa: BLE001
                    pass
                ctx.ambient = True
                ui.listening()
                conversation(ctx, first_text=t)
                ctx.ambient = False
                ui.idle()
                continue
            log("👂 ได้ยิน:", text, "→ ✨" if hit else "(ไม่ใช่คำปลุก)",
                f"[ดัง {voice._last['peak']}, ขยาย x{voice._last['gain']:.0f}]")
            if hit and is_owner:
                try:                                    # เรียนเสียงจริงของเจ้าของ (ระยะ/ห้อง/ไมค์ตอนใช้งาน)
                    import speaker_id
                    threading.Thread(target=speaker_id.adapt, args=(pcm,), daemon=True).start()
                except Exception:  # noqa: BLE001
                    pass
            if hit:
                try:                                    # ดูว่าตอนนี้จออยู่หน้าไหน (ทำคู่กับการฟังคำสั่ง)
                    import screen_context
                    screen_context.scan_async()
                except Exception:  # noqa: BLE001
                    pass
                ui.listening()
            if not hit:
                if time.time() - last_warm > 180:   # รักษาการเชื่อมต่อให้อุ่นไว้
                    voice.warmup()
                    last_warm = time.time()
                continue
            if len(rest) < 2:
                voice.ack("ครับ")              # ตอบรับแบบไม่รอ — พูดคำสั่งต่อได้ทันที
                time.sleep(0.5)                # ให้เสียง "ครับ" จบก่อน ไม่ให้ไมค์เก็บเสียงตัวเองแล้วตัดจบ
                rest = None
            elif voice.use_gemini_stt() and voice.needs_accurate(rest):
                # คำสั่งที่บอกข้อความให้พิมพ์/ส่ง → ถอดเสียงอีกรอบแบบแม่น (Gemini)
                try:
                    acc = voice.transcribe_accurate(os.path.join(config.DATA_DIR, "utterance.wav"))
                    if acc:
                        h2, r2 = find_wake(acc)
                        rest = r2 if h2 and len(r2) >= 2 else acc
                        log("🎯 ฟังละเอียด:", acc)
                except Exception as e:  # noqa: BLE001
                    log("stt:", e)
            conversation(ctx, first_text=rest)
            ui.idle()
            voice.beep(520, 180)                     # เสียง "ติ๊ด" ต่ำ = กลับไปรอคำปลุก
            voice.warmup()
            last_warm = time.time()
            log("👂 กลับไปรอคำปลุก")
        except voice.VoiceError as e:
            log("⚠️", e)
            time.sleep(3)
        except Exception as e:  # noqa: BLE001
            import traceback
            log("❗ wake_loop error (ข้ามไป):", traceback.format_exc()[-800:])
            import self_heal
            self_heal.record(traceback.format_exc())
            time.sleep(2)


ENROLL_LINES = [
    "สวัสดีครับ วันนี้อากาศดีมากเลย",
    "ช่วยเปิดไลน์แล้วส่งข้อความหาแม่หน่อย",
    "พรุ่งนี้ตอนเช้าฝนจะตกไหมนะ",
    "เปิดยูทูปแล้วหาเพลงสบายๆ ให้ฟังหน่อย",
    "เช็คแบตกับความร้อนของเครื่องให้หน่อย",
    "หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า สิบ",
]


_ENROLLING = [False]


def enroll_app(say):
    """สอนเสียงจากในแอป (ปุ่ม 🧰 → สอนเสียงฉัน) — พูดตาม 6 ประโยค → ต่อไปฟังเฉพาะเสียงคุณ"""
    import speaker_id
    _ENROLLING[0] = True
    try:
        time.sleep(1.0)                                   # ให้ลูปฟังคำปลุกหยุดใช้ไมค์ก่อน
        samples = []
        for i, line in enumerate(ENROLL_LINES, 1):
            for attempt in range(2):
                say(f"🎙️ ({i}/{len(ENROLL_LINES)}) พูดว่า: \"{line}\"")
                pcm = get_mic().utterance(wait_timeout=8, max_seconds=8, end_silence=0.9)
                if pcm and len(pcm) / 32000 >= 1.0:
                    samples.append(pcm)
                    break
                say("⚠️ ไม่ได้ยิน/สั้นไป ลองอีกครั้งนะครับ")
        try:
            prof = speaker_id.enroll(samples)
        except ValueError as e:
            return f"❌ {e}"
        return (f"✅ จำเสียงคุณแล้ว ({prof['n']} ประโยค) — ต่อไปผมจะฟังเฉพาะเสียงคุณ ไม่สนเสียงคนอื่น/ทีวี\n"
                "ถ้าเสียงคุณโดนปฏิเสธบ่อย ⚙️ ตั้ง SPEAKER_STRICT=-0.05 · ถ้าเสียงคนอื่นยังหลุด ตั้ง +0.05")
    finally:
        _ENROLLING[0] = False


def enroll_voice():
    """สอนให้บอทจำเสียงเจ้าของ: พูดตามประโยคที่ขึ้นบนจอ 6 ประโยค"""
    import speaker_id
    if not speaker_id.available():
        print("❌ ต้องติดตั้ง numpy ก่อน: pkg install python-numpy")
        return
    print("\n🎙️ สอนเสียงเจ้าของเครื่อง — พูดตามประโยคที่ขึ้น ด้วยเสียงปกติ ห่างเครื่องเท่าที่ใช้จริง\n")
    voice.say("เริ่มสอนเสียงนะครับ พูดตามประโยคที่ขึ้นบนจอทีละประโยค")
    samples = []
    for i, line in enumerate(ENROLL_LINES, 1):
        for attempt in range(2):
            print(f"[{i}/{len(ENROLL_LINES)}] พูดว่า:  \"{line}\"")
            voice.beep()
            pcm = get_mic().utterance(wait_timeout=8, max_seconds=8, end_silence=0.9)
            if pcm and len(pcm) / 32000 >= 1.0:
                samples.append(pcm)
                print("   ✅ ได้แล้ว")
                break
            print("   ⚠️ ไม่ได้ยิน/สั้นไป ลองอีกครั้ง")
    try:
        prof = speaker_id.enroll(samples)
    except ValueError as e:
        print("❌", e)
        voice.say("ยังได้เสียงไม่พอครับ ลองใหม่อีกครั้งนะ")
        return
    print(f"\n✅ จำเสียงแล้ว ({prof['n']} ประโยค) เกณฑ์ {prof['threshold']} · คะแนนตอนทดสอบ {[round(x, 2) for x in prof['self']]}")
    print("ปรับความเข้ม: SPEAKER_STRICT ใน .env (+0.05 = เข้มขึ้น ถ้าเสียงคนอื่นหลุดผ่าน / -0.05 = ผ่อนลง ถ้าเสียงคุณถูกปฏิเสธ)")
    voice.say("จำเสียงคุณได้แล้วครับ ต่อไปผมจะฟังเฉพาะเสียงคุณ")


def mic_test():
    m = get_mic()
    print(f"โหมด: {MIC_MODE} — พูดอะไรก็ได้ (Ctrl+C เพื่อออก)")
    if not MIC_MODE.startswith("realtime"):
        print("⚠️ ใช้โหมดเรียลไทม์ไม่ได้ ดูวิธีแก้ใน README")
        return
    while True:
        level = audio_stream.rms(m._frame())
        print(f"\rระดับเสียง {int(level):5d} " + "█" * min(40, int(level / 100)) + " " * 40, end="", flush=True)


def main():
    import voice as _v
    if not _v.stt_available() and not config.MOCK_PHONE:
        sys.exit("❌ ต้องใส่ GROQ_API_KEY หรือคีย์ NanoGPT ก่อน (ใช้แปลงเสียงเป็นข้อความ)")
    # กันเปิดซ้อนกันหลายตัว
    if os.path.exists(LOCK):
        try:
            pid = int(open(LOCK).read())
            os.kill(pid, 0)
            log("มีโหมดเสียงทำงานอยู่แล้ว (pid", pid, ")")
            return
        except (ValueError, OSError):
            pass
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    os.system("termux-wake-lock >/dev/null 2>&1")
    ctx = VoiceCtx(owner_chat_id())
    try:
        if "--test" in sys.argv:
            mic_test()
        elif "--enroll" in sys.argv:
            enroll_voice()
        elif "--wake" in sys.argv:
            wake_loop(ctx)
        elif "--once" in sys.argv:
            text = listen_text(timeout=8)
            if text:
                answer(text, ctx)
            else:
                voice.say("ไม่ได้ยินเลยครับ")
        else:
            if config.VOICE_GREETING:
                voice.say("ว่ายังไงครับ")
            conversation(ctx, follow_timeout=10)
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        try:
            voice.say("ขอโทษครับ เกิดข้อผิดพลาด")
        except Exception:  # noqa: BLE001
            pass
        log("❗", e)
    finally:
        if MIC:
            MIC.close()
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
