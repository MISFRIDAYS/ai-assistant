"""จุดเริ่มของสมองบอทในแอป APK (Chaquopy)

- โค้ดบอทถูกแตกจาก assets ไปไว้ที่ files/bot (เขียนได้) → ระบบซ่อมตัวเองแก้โค้ดได้จริง
- ข้อมูล/คีย์อยู่ที่ files/data (ไม่หายตอนอัปเดตแอปหรือคืนค่าโค้ด)
- เริ่ม: Telegram (ถ้ามี token) · ผู้ช่วยเสียง (ถ้าเปิด) · ตรวจซ่อมตัวเองเบื้องหลัง
- แชทในแอป: chat(text) · ปุ่มไมค์: listen_once()
"""
import json
import os
import shutil
import sys
import threading
import time
import traceback

from java import jclass

Bridge = jclass("com.aibot.assistant.Bridge")

FILES = str(Bridge.filesDir())
BOT = os.path.join(FILES, "bot")
DATA = os.path.join(FILES, "data")
ENV = os.path.join(DATA, ".env")
STATE = os.path.join(DATA, "run_state.json")
_threads = {}
_ready = [False]


def log(*a):
    msg = " ".join(str(x) for x in a)
    try:
        Bridge.log(msg)
    except Exception:  # noqa: BLE001
        print(msg, flush=True)


# ============================================================ เตรียมโค้ด + สภาพแวดล้อม

def _rm_tree(path):
    """ลบโฟลเดอร์แม้ไฟล์ข้างในเป็นแบบอ่านอย่างเดียว"""
    import stat

    def onerr(fn, p, _exc):
        try:
            os.chmod(os.path.dirname(p), stat.S_IRWXU)
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerr)


def _install_code(force=False):
    """แตกโค้ดบอทจากแอป (ครั้งแรก / อัปเดตแอป / คืนค่า) — โค้ดที่ซ่อมแล้วจะถูกแทนเมื่ออัปเดตแอปเวอร์ชันใหม่"""
    ver = str(Bridge.versionCode())
    try:                                                   # อัปเดต APK ทับ (เวอร์ชันเดิม) ก็ต้องได้โค้ดใหม่
        ctx = Bridge.INSTANCE.getApp()
        ver += "-" + str(ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).lastUpdateTime)
    except Exception:  # noqa: BLE001
        pass
    mark = os.path.join(BOT, ".app_version")
    cur = open(mark).read().strip() if os.path.exists(mark) else ""
    if not force and cur == ver and os.path.exists(os.path.join(BOT, "bot.py")):
        return False
    import fcntl
    os.makedirs(DATA, exist_ok=True)
    lock = open(os.path.join(DATA, ".install.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)                      # 2 โปรเซส (หลัก + ซ่อม) เริ่มพร้อมกัน → ทำทีละตัว
    try:
        cur = open(mark).read().strip() if os.path.exists(mark) else ""
        if not force and cur == ver and os.path.exists(os.path.join(BOT, "bot.py")):
            return False                                   # อีกโปรเซสติดตั้งให้แล้ว
        if os.path.isdir(BOT):
            try:                                           # สำรองโค้ดเดิม (พลาดก็ไม่เป็นไร ไม่ให้แอปเริ่มไม่ได้)
                root = os.path.join(DATA, "backups")
                bk = os.path.join(root, f"code-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}")
                os.makedirs(root, exist_ok=True)
                for root, dirs, files in os.walk(BOT):      # คัดลอกแค่เนื้อไฟล์ (ไม่เอาสิทธิ์ไฟล์ติดมา)
                    dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
                    out = os.path.join(bk, os.path.relpath(root, BOT))
                    os.makedirs(out, exist_ok=True)
                    for f in files:
                        shutil.copyfile(os.path.join(root, f), os.path.join(out, f))
                old = sorted(d for d in os.listdir(root) if d.startswith("code-"))
                for d in old[:-3]:                         # เก็บแค่ 3 ชุดล่าสุด
                    _rm_tree(os.path.join(root, d))
            except Exception as e:  # noqa: BLE001
                log(f"⚠️ สำรองโค้ดเดิมไม่สำเร็จ (ข้าม): {str(e)[:150]}")
            _rm_tree(BOT)
        n = Bridge.copyAssets("bot", BOT)
        with open(mark, "w") as f:
            f.write(ver)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    log(f"📦 ติดตั้งโค้ดบอท {n} ไฟล์ (เวอร์ชันแอป {ver})")
    return True


def rollback_code():
    """ย้อนโค้ดผู้ช่วยกลับเป็นชุดก่อนอัปเดตครั้งล่าสุด (สำรองไว้อัตโนมัติทุกครั้งที่อัปเดตแอป)"""
    root = os.path.join(DATA, "backups")
    try:
        cands = sorted((d for d in os.listdir(root) if d.startswith("code-")), reverse=True)
    except OSError:
        cands = []
    cands = [d for d in cands if os.path.exists(os.path.join(root, d, "bot.py"))]
    if not cands:
        return "⏪ ยังไม่มีโค้ดชุดก่อนให้ย้อน (จะมีหลังอัปเดตแอปครั้งถัดไป)"
    src = os.path.join(root, cands[0])
    mark = os.path.join(BOT, ".app_version")
    ver = open(mark).read().strip() if os.path.exists(mark) else ""
    try:
        tmp = BOT + ".new"
        if os.path.isdir(tmp):
            _rm_tree(tmp)
        for r, dirs, files in os.walk(src):
            out = os.path.join(tmp, os.path.relpath(r, src))
            os.makedirs(out, exist_ok=True)
            for f in files:
                shutil.copyfile(os.path.join(r, f), os.path.join(out, f))
        old = BOT + ".old"
        if os.path.isdir(old):
            _rm_tree(old)
        os.rename(BOT, old)
        os.rename(tmp, BOT)
        with open(mark, "w") as f:
            f.write(ver)                                   # ไม่ให้ระบบแตกโค้ดใหม่ทับจนกว่าจะอัปเดตแอปครั้งหน้า
        _rm_tree(old)
        _rm_tree(src)                                       # ใช้ชุดนี้แล้ว → ย้อนอีกครั้งจะได้ชุดเก่ากว่า
    except Exception as e:  # noqa: BLE001
        return f"⏪ ย้อนไม่สำเร็จ: {str(e)[:200]}"
    log(f"⏪ ย้อนโค้ดผู้ช่วยเป็นชุด {cands[0]}")
    mark_clean_exit()
    threading.Timer(1.5, Bridge.restartBot).start()
    when = cands[0][5:20].replace("-", " ")
    return f"⏪ ย้อนโค้ดผู้ช่วยกลับเป็นชุดก่อนอัปเดต ({when}) แล้ว — กำลังเริ่มใหม่\n(อัปเดตแอปครั้งหน้าจะได้โค้ดใหม่ตามปกติ)"


def setup():
    if _ready[0]:
        return
    os.makedirs(DATA, exist_ok=True)
    _install_code()
    os.environ["ANDROID_APP"] = "1"
    os.environ["BOT_DATA_DIR"] = DATA
    os.environ["BOT_ENV_FILE"] = ENV
    os.environ.setdefault("MOCK_PHONE", "0")
    os.environ.setdefault("SHARED_STORAGE", "/storage/emulated/0")
    os.environ.setdefault("ENABLE_ADB", "1")
    os.environ.setdefault("UI_ENABLED", "0")            # แอปมีหน้าจอของตัวเอง ไม่ต้องใช้การ์ดแจ้งเตือนแบบ Termux
    if not os.path.exists(ENV):
        seed = os.path.join(BOT, "tester_defaults.env")   # รุ่นสำหรับผู้ทดลอง: GitHub Actions ใส่คีย์ทดสอบ + ปิดฟีเจอร์เสี่ยงไว้ให้
        with open(ENV, "w") as f:
            if os.path.exists(seed):
                with open(seed, encoding="utf-8") as src:
                    f.write(src.read())
            else:
                f.write("LLM_PROVIDER=claude\nSELF_REPAIR=ask\n")
    if BOT not in sys.path:
        sys.path.insert(0, BOT)
    try:                                                   # เซิร์ฟเวอร์ไม่บอก charset → requests เดาเป็น Latin-1 → ไทยเพี้ยน
        import requests.models as _rm
        _orig_json = _rm.Response.json

        def _json_utf8(self, **kw):
            if (self.encoding or "").lower() in ("", "iso-8859-1", "latin-1"):
                self.encoding = "utf-8"
            return _orig_json(self, **kw)
        _rm.Response.json = _json_utf8
    except Exception:  # noqa: BLE001
        pass
    os.chdir(BOT)
    _ready[0] = True


def _cfg():
    setup()
    import config
    return config


# ============================================================ ช่องทางส่งข้อความ (แอป + Telegram)

class AppTG:
    """แทน Telegram เมื่อไม่ได้ใส่ token: ข้อความไปขึ้นหน้าแชทในแอป + แจ้งเตือน"""

    def send_message(self, chat_id, text, **kw):
        Bridge.post("bot", str(text))
        if not _app_visible():
            Bridge.postNotif(41, "ผู้ช่วย AI", str(text)[:500])
        return {"message_id": int(time.time())}

    def edit_message_text(self, chat_id, mid, text, **kw):
        return None

    def send_chat_action(self, chat_id, *a, **kw):
        return None

    def send_photo(self, chat_id, path, *a, **kw):
        Bridge.post("bot", f"🖼️ {path}")

    def send_file(self, chat_id, path, *a, **kw):
        Bridge.post("bot", f"📎 {path}")

    def send_voice(self, chat_id, path, *a, **kw):
        return None


def _app_visible():
    try:
        return bool(Bridge.appVisible())
    except Exception:  # noqa: BLE001
        return False


def _owner():
    c = _cfg()
    return sorted(c.ALLOWED_USER_IDS)[0] if c.ALLOWED_USER_IDS and c.TELEGRAM_BOT_TOKEN else None


def notify_all(text):
    """แจ้งเจ้าของ: หน้าแชทในแอป + Telegram (ถ้ามี)"""
    Bridge.post("bot", text)
    o = _owner()
    if o:
        try:
            import bot
            if bot.tg is not None and not isinstance(bot.tg, AppTG):
                bot.tg.send_message(o, text)
        except Exception:  # noqa: BLE001
            pass


class AppCtx:
    """บริบทของคำสั่งที่มาจากหน้าแชทในแอป"""
    ambient = False

    def __init__(self):
        self.chat_id = "app"
        self.hold = False
        self.status_msg = None

    def status(self, text):
        Bridge.post("status", str(text))
        if not _app_visible():                     # แอปถอยไปเบื้องหลังระหว่างทำงานบนจอ → แสดงแผงลอยแทน
            Bridge.assistant("think", str(text)[:120])

    def notify(self, text):
        Bridge.post("bot", str(text))

    def confirm(self, description):
        return bool(Bridge.confirm(str(description), int(_cfg().CONFIRM_TIMEOUT)))

    def ask(self, question, timeout=180):
        a = Bridge.ask(str(question), int(timeout))
        return None if a is None else str(a)

    def send_photo(self, path):
        Bridge.post("bot", f"🖼️ บันทึกภาพไว้ที่ {path}")

    def send_file(self, path, kind="document"):
        Bridge.post("bot", f"📎 ไฟล์อยู่ที่ {path}")

    def add_reminder(self, minutes, text):
        import bot
        return bot.add_reminder(_owner() or "app", minutes, text)


# ============================================================ เริ่ม / หยุด

def _alive(name):
    t = _threads.get(name)
    return t is not None and t.is_alive()


def _spawn(name, fn):
    if _alive(name):
        return
    t = threading.Thread(target=_guard, args=(name, fn), daemon=True, name=name)
    _threads[name] = t
    t.start()


RESTART_MAX_WAIT = 300          # รอสูงสุดกี่วินาทีก่อนเริ่มส่วนที่ล่มใหม่


def _restart_wait(fails):
    """ล่มติดกันยิ่งบ่อย ยิ่งรอนาน: 5, 10, 20, 40 … สูงสุด 5 นาที (กันวนล่มกินแบต)"""
    return min(RESTART_MAX_WAIT, 5 * 2 ** max(0, fails - 1))


def _guard(name, fn, sleep=time.sleep):
    """รันงานเบื้องหลัง — ล่ม/จบเอง → เริ่มใหม่อัตโนมัติ (เว้น SystemExit = ตั้งค่าไม่ครบ / ซ่อมแล้วย้อนโค้ด)"""
    fails = 0
    while True:
        t0 = time.time()
        try:
            fn()
            log(f"⚠️ {name} จบการทำงานเอง")
        except SystemExit as e:
            log(f"⚠️ {name} หยุด: {e}")
            return
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            log(f"❗ {name} ล่ม:\n{tb[-1500:]}")
            try:
                import self_heal
                self_heal.record(tb, crash=True)
                if self_heal.after_crash_in_app():
                    return
            except Exception:  # noqa: BLE001
                pass
        if time.time() - t0 > 600:              # ทำงานได้นานแล้วค่อยล่ม = ไม่ใช่วนล่ม → นับใหม่
            fails = 0
        fails += 1
        wait = _restart_wait(fails)
        log(f"🔁 เริ่ม {name} ใหม่ใน {wait} วิ (ครั้งที่ {fails})")
        _restarts[name] = _restarts.get(name, 0) + 1
        sleep(wait)


_restarts = {}                  # ชื่องาน → จำนวนครั้งที่เริ่มใหม่ (ไว้รายงานสุขภาพ)
_once = set()


def _telegram():
    import bot
    bot.main()


def voice_alive():
    return _alive("voice")


def start_voice():
    c = _cfg()
    import voice as _v
    if not _v.stt_available() or os.environ.get("VOICE_AUTOSTART", "1") == "0" or not Bridge.micAllowed():
        return False

    def run():
        import voice_chat
        try:
            os.remove(voice_chat.LOCK)
        except OSError:
            pass
        sys.argv = ["voice_chat.py", "--wake"]
        voice_chat.main()
    _spawn("voice", run)
    return True


def _check_last_run():
    """รอบที่แล้วปิดไม่ปกติ (ล่ม) หลังซ่อมโค้ดไม่นาน → ย้อนการซ่อมกลับ"""
    try:
        with open(STATE) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {"clean": True}
    with open(STATE, "w") as f:
        json.dump({"started": time.time(), "clean": False}, f)
    if st.get("clean", True):
        return
    import self_heal
    r = self_heal.after_exit(1)
    if r:
        log(r)
        Bridge.post("bot", r + " — กลับไปใช้โค้ดเดิมแล้ว กำลังเริ่มใหม่")
        mark_clean_exit()
        Bridge.restartBot()


def mark_clean_exit():
    try:
        with open(STATE, "w") as f:
            json.dump({"started": time.time(), "clean": True}, f)
    except OSError:
        pass


def start_bot():
    """เรียกจาก BotService ครั้งเดียวต่อโปรเซส"""
    c = _cfg()
    sys.stdout = sys.stderr = _LogFile(os.path.join(DATA, "bot.log"))
    _check_last_run()                                     # ต้องก่อนเขียน "=== start" (อ่าน traceback ของรอบที่แล้ว)
    print(f"=== start {time.ctime()} (แอป APK) ===", flush=True)
    import bot
    import self_heal
    if c.TELEGRAM_BOT_TOKEN:
        _spawn("telegram", _telegram)
    else:
        bot.tg = AppTG()                                  # เตือนความจำ/งานตามเวลา → ขึ้นในแอป
        _spawn("reminders", bot.reminder_loop)
    start_voice()
    if "heal" not in _once:                                # start_bot อาจถูกเรียกซ้ำตอนลองเริ่มใหม่ → ไม่เปิดลูปซ้อน
        _once.add("heal")
        self_heal.on_start(notify=notify_all, confirm=lambda d: bool(Bridge.confirm(str(d), 600)))
    import mind

    def mind_say(text):                                   # ความคิดของผู้ช่วย → แชท + แจ้งเตือน + Telegram
        notify_all(text)
        if not _app_visible():
            Bridge.postNotif(44, "💭 ผู้ช่วย AI", text)
    mind.start(mind_say)
    import app_brain
    app_brain.start(mind_say)          # รู้จักแอปทั้งเครื่อง + ศึกษาแอปใหม่อัตโนมัติ
    import autoreply

    def ar_say(text):                  # ตอบแชทแทนแล้ว → แจ้งเจ้าของ (แชทในแอป + แจ้งเตือน)
        Bridge.post("bot", text)
        if not _app_visible():
            Bridge.postNotif(45, "💬 ตอบกลับอัตโนมัติ", text)
    autoreply.start(ar_say)
    try:
        import app_index
        app_index.ensure_background()
    except Exception:  # noqa: BLE001
        pass
    if not c.ANTHROPIC_API_KEY and not c.GEMINI_API_KEY and not c.GROQ_API_KEY and not c.CLOUD_API_KEY \
            and c.LLM_PROVIDER != "ollama":
        Bridge.post("bot", "⚠️ ยังไม่ได้ใส่คีย์ AI — กด ⚙️ ตั้งค่า แล้วใส่คีย์ Claude หรือ Gemini ก่อนนะ")
    return True


class _LogFile:
    """print() ทั้งหมดของบอท → data/bot.log (ตัดเมื่อใหญ่เกิน)"""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, s):
        if not s:
            return 0
        with self.lock:
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) > 4_000_000:
                    data = open(self.path, "rb").read()[-800_000:]
                    open(self.path, "wb").write(data)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(s)
            except OSError:
                pass
        return len(s)

    def flush(self):
        pass


# ============================================================ จากหน้าแอป

def chat(text, voice=False):
    text = (text or "").strip()
    if not text:
        return ""
    setup()
    if _cfg().paused():
        return "⏸️ ผู้ช่วยปิดอยู่ — แตะปุ่ม ⏻ ด้านบนเพื่อเปิดก่อนนะ"
    if text == "__rollback__":
        return rollback_code()
    if text == "__factory__":
        _install_code(force=True)
        mark_clean_exit()
        threading.Timer(1.5, Bridge.restartBot).start()
        return "♻️ คืนโค้ดเป็นเวอร์ชันที่มากับแอปแล้ว (โค้ดเดิมสำรองไว้ใน data/backups) — กำลังเริ่มใหม่"
    import re
    import agent
    import providers
    if re.search(r"(ใช้|เป็น)\s*(ai|เอไอ|สมอง|โมเดล)\S*\s*(อะไร|ตัวไหน|ไหน)", text.lower()):
        providers.sync()
        return providers.status()
    t0 = time.time()
    try:
        ctx = AppCtx()
        if voice:                                          # คำสั่งจากปุ่มไมค์ → ถือเป็นคำสั่งเสียง (ถามยืนยันก่อนส่ง)
            ctx.voice = ctx.via_voice = True
        reply = agent.chat("app", [{"type": "text", "text": text}], ctx) or ""
        sw = agent.LAST_SWITCH
        if sw["t"] >= t0:                                  # ตัวหลักใช้ไม่ได้ระหว่างคำสั่งนี้ → บอกผู้ใช้ตรงๆ
            reply = (f"⚠️ {sw['from']} ใช้ไม่ได้ตอนนี้ ({sw['why'][:90]}) — ใช้ {sw['to']} แทนชั่วคราว\n\n" + reply)
        if reply and not _app_visible():                    # ผู้ใช้อยู่แอปอื่น (บอทเพิ่งไปทำงานบนจอ) → โชว์คำตอบบนแผงลอย
            Bridge.assistant("done", reply[:500])
        try:
            import perf
            kind = "quick" if getattr(agent, "LAST_QUICK", [0.0])[0] >= t0 else "chat"   # ตอบด้วยคำสั่งด่วน ≠ คำสั่ง AI
            perf.record(kind, text, total=time.time() - t0, ok=perf.looks_ok(reply))
        except Exception:  # noqa: BLE001
            pass
        return reply
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        log(tb[-1500:])
        try:
            import self_heal
            self_heal.record(tb)
        except Exception:  # noqa: BLE001
            pass
        return f"❗ เกิดข้อผิดพลาด: {e}"


def chat_file(path, mime="", caption=""):
    """ไฟล์ที่แนบในแอป (📎) → วิเคราะห์/สรุป แล้วเก็บในประวัติแชท (ถามต่อได้)"""
    setup()
    if _cfg().paused():
        return "⏸️ ผู้ช่วยปิดอยู่ — แตะปุ่ม ⏻ เพื่อเปิดก่อนนะ"
    import agent
    import media
    try:
        reply = media.analyze_file(str(path), str(mime or ""), str(caption or ""), AppCtx())
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc()[-1500:])
        return f"❗ วิเคราะห์ไฟล์ไม่สำเร็จ: {e}"
    try:
        h = agent.load_history("app")
        stamp = {"type": "text", "text": f"[เวลา: {agent.now_local().strftime('%a %d/%m/%Y %H:%M')}]"}
        agent._append_user(h, [stamp, {"type": "text", "text": f"[ส่งไฟล์ {os.path.basename(str(path))} ({mime})] {caption}".strip()}])
        h.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        agent.save_history("app", agent.trim_history(h))
    except Exception:  # noqa: BLE001
        pass
    return reply


def listen_once():
    """ปุ่มไมค์ในแอป: ฟังหนึ่งประโยค → ข้อความ (ถ้าไม่ได้ยิน จะบอกสาเหตุที่ตรวจเจอ)"""
    c = _cfg()
    import audio_stream
    import voice
    import voice_chat
    try:                                                   # ระบบรู้จำเสียงของเครื่อง (Google) ก่อน — แม่น ฟรี
        import google_stt
        if Bridge.micAllowed():
            g = google_stt.listen(8.0, user_started=True)
            if g:
                return g
            if g == "":
                raise RuntimeError("ไม่ได้ยินเสียงพูด — กดแล้วพูดได้เลย")
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        log("google stt:", e)
    if not voice.stt_available() and not c.GEMINI_API_KEY:
        raise RuntimeError("ยังไม่มีตัวแปลงเสียงเป็นข้อความ — กด ⚙️ ตั้งค่า แล้วใส่คีย์ Groq หรือเลือกถอดเสียงด้วย NanoGPT")
    if not Bridge.micAllowed():
        raise RuntimeError("แอปยังไม่ได้รับสิทธิ์ไมค์ — กด 🔐 สิทธิ์")
    voice_chat.hold_mic(30)
    mic = voice_chat.get_mic()
    if getattr(mic, "silent_for", lambda: 0)() > 2 and hasattr(mic, "restart"):
        log("🎙️ ไมค์เงียบสนิท → เปิดตัวอัดเสียงใหม่")
        mic.restart()
        time.sleep(0.4)
    prev_owner = getattr(mic, "owner", None)
    mic.owner = threading.get_ident()                  # จองไมค์ (ผู้ช่วยเสียงเบื้องหลังจะไม่แย่งเสียง)
    mic.peak = 0.0
    try:
        mic.flush()
        voice.beep()
        pcm = mic.utterance(wait_timeout=8, max_seconds=15, end_silence=c.VAD_END_SILENCE)
    finally:
        mic.owner = prev_owner
    thresh = max(mic.noise * 2.8, c.VAD_MIN_RMS)
    log(f"🎤 ปุ่มไมค์: {'ได้เสียง %.1f วิ' % (len(pcm) / 32000) if pcm else 'ไม่ได้ยิน'} "
        f"(ดังสุด {mic.peak:.0f}, เกณฑ์ {thresh:.0f}, เงียบสนิท {mic.silent_for():.0f} วิ)")
    if not pcm:
        if mic.silent_for() > 3 or mic.peak < 1:
            raise RuntimeError("ไมค์ได้แต่ความเงียบ — ระบบอาจปิดไมค์ของแอป: ปิดแอปแล้วเปิดใหม่ "
                               "หรือ ตั้งค่า > แอป > ผู้ช่วย AI > สิทธิ์ > ไมโครโฟน = อนุญาตเสมอ")
        raise RuntimeError(f"ไม่ได้ยินเสียงพูด (ดังสุด {mic.peak:.0f} ต้องเกิน {thresh:.0f}) — "
                           "พูดใกล้ไมค์อีกนิด หรือพูดหลังเสียงติ๊ด")
    text = voice.transcribe_pcm(pcm, accurate=True)
    if not text:
        raise RuntimeError("ได้ยินเสียงแต่แปลงเป็นข้อความไม่ได้ — ลองพูดชัดๆ อีกครั้ง")
    return text


_panel = threading.Lock()


def panel_listen():
    """แผงผู้ช่วยแบบ Google Assistant (Quick Settings / แจ้งเตือน / ปุ่ม 🎤 บนแผง):
    ฟัง → ตอบด้วยเสียง → ฟังต่อได้เลยโดยไม่ต้องเรียกชื่อ จนกว่าจะเงียบ"""
    setup()
    if not _panel.acquire(blocking=False):
        return False

    def run():
        import ui
        import voice_chat
        mic = None
        try:
            ui.listening()
            voice_chat.hold_mic(90)                    # ลูปคำปลุกห้ามปิดไมค์ระหว่างแผงฟัง
            mic = voice_chat.get_mic()
            mic.owner = threading.get_ident()
            try:
                text = listen_once()
            except Exception as e:  # noqa: BLE001
                if voice_chat.mic_closed(e):              # กดปิดไมค์เอง → ปิดแผงเงียบๆ
                    log("panel_listen: ไมค์ถูกปิด")
                    return
                Bridge.assistant("error", str(e))
                return
            ui.heard(text)
            ctx = voice_chat.VoiceCtx(voice_chat.owner_chat_id())
            voice_chat.conversation(ctx, first_text=text)
        except Exception as e:  # noqa: BLE001
            if voice_chat.mic_closed(e):
                log("panel_listen: ไมค์ถูกปิด")
                return
            log("panel_listen:\n" + traceback.format_exc()[-1200:])
            Bridge.assistant("error", "เกิดข้อผิดพลาด ลองใหม่อีกครั้ง")
        finally:
            if mic is not None:
                mic.owner = None
            ui.idle()
            _panel.release()
    threading.Thread(target=run, daemon=True, name="panel").start()
    return True


def tool(name, arg=""):
    """เมนู 🧰 ในแอป เรียกฟังก์ชันตรง (ไม่ผ่าน AI) คืนข้อความ/JSON"""
    setup()
    if _cfg().paused() and name not in ("profile_get", "flows", "memories", "history") and not name.startswith("ar_"):
        return "⏸️ ผู้ช่วยปิดอยู่ — แตะปุ่ม ⏻ เพื่อเปิดก่อนนะ"
    ctx = AppCtx()
    arg = str(arg or "")
    try:
        if name == "learn_all":
            import app_learn
            return app_learn.explore_all(ctx)
        if name == "learn_app":                         # arg = "ชื่อแอป|package"
            import app_learn
            label, _, pkg = arg.partition("|")
            return app_learn.explore(pkg or label, ctx, key=label.lower(), label=label)
        if name == "record_start":
            import app_learn
            r = app_learn.record_start(arg or "ขั้นตอนใหม่", ctx)
            if r.startswith("🎬"):
                Bridge.recordNotify(True, arg)
            return r
        if name == "record_stop":
            import app_learn
            Bridge.recordNotify(False, "")
            return app_learn.record_stop(ctx)
        if name == "flows":
            import skills
            return json.dumps(sorted((skills.get_pref("flows") or {}).keys()), ensure_ascii=False)
        if name == "play_flow":
            import app_learn
            return app_learn.replay(arg, ctx)
        if name == "forget_flow":
            import app_learn
            return app_learn.forget_flow(arg)
        if name == "fill_form":
            import forms
            Bridge.away()
            return forms.fill(ctx)
        if name == "profile_get":
            import user_profile
            d = user_profile.load()
            return json.dumps([[k, v[0], d.get(k, "")] for k, v in user_profile.FIELDS.items()], ensure_ascii=False)
        if name == "profile_set":
            import user_profile
            vals = json.loads(arg or "{}")
            d = user_profile.load()
            for k, v in vals.items():
                if k in user_profile.FIELDS:
                    if v:
                        d[k] = v
                    else:
                        d.pop(k, None)
            user_profile.save(d)
            return "🔒 บันทึกข้อมูลของคุณแล้ว (เก็บในเครื่องเท่านั้น)"
        if name == "memories":
            import extras
            return json.dumps([m["text"] for m in extras.memories()][-80:], ensure_ascii=False)
        if name == "forget_memory":
            import extras
            return extras.forget({"query": arg}, ctx)
        if name == "history":
            return heal_history()
        if name == "voice_enroll":                         # สอนเสียงเจ้าของ (ฟังเฉพาะเสียงคุณ)
            import voice_chat

            def run_enroll():
                notify_all(voice_chat.enroll_app(lambda t: (Bridge.post("bot", t), Bridge.assistant("listen", t))))
                Bridge.assistant("done", "")
            threading.Thread(target=run_enroll, daemon=True).start()
            return "🎙️ เริ่มสอนเสียง — พูดตามประโยคที่ขึ้นทีละประโยค ด้วยเสียงปกติ (6 ประโยค)"
        if name == "voice_forget":
            import speaker_id
            speaker_id.forget()
            return "ลืมเสียงแล้ว — ตอนนี้ฟังทุกเสียงที่เรียก \"เฮ้ยผู้ช่วย\""
        if name.startswith("ar_"):                           # ตอบกลับอัตโนมัติ
            import autoreply
            if name == "ar_get":
                c = autoreply.cfg()
                return json.dumps({k: c[k] for k in ("enabled", "away", "away_auto_min", "disclose", "rules")},
                                  ensure_ascii=False)
            if name == "ar_save":
                autoreply.upsert(json.loads(arg))
                return "✅ บันทึกกฎแล้ว"
            if name == "ar_delete":
                autoreply.delete(arg)
                return "🗑️ ลบกฎแล้ว"
            if name == "ar_set":                              # arg = '{"away": true}' ฯลฯ
                with autoreply._lock:
                    autoreply.cfg().update({k: v for k, v in json.loads(arg).items()
                                            if k in ("enabled", "away", "away_auto_min", "disclose")})
                autoreply.save()
                return "OK"
            if name == "ar_summary":
                return autoreply.summary(mark=False)
        if name in ("face_enroll", "face_who", "camera_look"):
            import vision
            return {"face_enroll": vision.enroll_owner, "face_who": vision.who_is_there,
                    "camera_look": vision.look}[name](ctx, arg)
        return f"ไม่รู้จักคำสั่ง {name}"
    except Exception as e:  # noqa: BLE001
        log(f"tool {name}: " + traceback.format_exc()[-800:])
        return f"❗ ทำไม่สำเร็จ: {e}"


def set_enabled(on):
    """ปุ่ม ⏻ ในแอป: ปิด = หยุดฟังไมค์/งานเบื้องหลัง (ประหยัดแบต) · เปิด = กลับมาทำงาน"""
    c = _cfg()
    c.set_paused(not on)
    if on:
        start_voice()
    log("▶️ เปิดผู้ช่วย" if on else "⏸️ ปิดผู้ช่วย")
    return True


def enabled():
    return not _cfg().paused()


def contact_catalog():
    """รายชื่อคนที่ผู้ช่วยจำได้ทุกแอป (ให้หน้าสั่งแบบเลือก)"""
    setup()
    import contacts
    return json.dumps(contacts.catalog(), ensure_ascii=False)


def command_catalog():
    """เมนูคำสั่งแบบกดเลือก (แอป → สิ่งที่จะทำ → ช่องกรอก)"""
    setup()
    import app_brain
    import cmdmenu
    if not app_brain.apps():
        try:
            app_brain.sync()
        except Exception:  # noqa: BLE001
            pass
    return cmdmenu.catalog()


def mic_enabled():
    return not _cfg().mic_off()


def set_mic(on):
    """ปุ่ม 🎤 ในหน้าต่างลอย: ปิด = หยุดฟังคำสั่งเสียง (พิมพ์คุยได้ตามเดิม)"""
    c = _cfg()
    c.set_mic_off(not on)
    if on:
        start_voice()
    log("🎤 เปิดไมค์สั่งเสียง" if on else "🔇 ปิดไมค์สั่งเสียง")
    return True


def heal_history():
    setup()
    import self_heal
    return self_heal.history_text() + "\n\n🐞 บัคล่าสุด:\n" + (self_heal.recent_errors() or "-")


# ============================================================ โปรเซสซ่อม (:heal) — รันเทสต์ในสำเนาโค้ด

def run_tests(stage, result_path):
    import contextlib
    import io
    import unittest
    os.chdir(stage)
    sys.path.insert(0, stage)
    for k in ("ANDROID_APP", "BOT_DATA_DIR", "BOT_ENV_FILE"):
        os.environ.pop(k, None)

    def run(suite):
        res = unittest.TestResult()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            suite.run(res)
        return res

    out = {"failed": [], "detail": "", "ran": 0}
    try:
        tdir = os.path.join(stage, "tests")
        # TestLoader ใหม่ทุกครั้ง: ตัวกลางของ Python 3.11 จำโฟลเดอร์จากรอบก่อน → "Start directory is not importable"
        res = run(unittest.TestLoader().discover(tdir, top_level_dir=tdir))
        still = []
        for t, tb in res.failures + res.errors:
            r2 = run(unittest.TestLoader().loadTestsFromName(t.id()))
            if r2.failures or r2.errors:
                still.append((t, tb))
        out = {"failed": [t.id() for t, _ in still], "ran": res.testsRun,
               "detail": "\n".join(t.id() + ":\n" + tb[-600:] for t, tb in still[:4])}
    except Exception:  # noqa: BLE001
        out = {"error": traceback.format_exc()[-800:]}
    with open(result_path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(result_path + ".tmp", result_path)
