"""คำสั่งด่วน: คำสั่งพื้นฐานทำทันทีโดยไม่ผ่าน AI (เร็ว ฟรี ไม่พลาด)

เปิด/ปิดแอป · Wi-Fi · บลูทูธ · ไฟฉาย · โหมดเครื่องบิน · ห้ามรบกวน · ความสว่าง · แบต · หน้าโฮม · ล้างแรม · ล็อกจอ
ประโยคที่ซับซ้อน (เช่น "เปิด YouTube แล้วหาเพลง...") จะไม่เข้าเงื่อนไข → ส่งให้ AI ตามปกติ
ถ้าทำไม่สำเร็จ (เช่น หาแอปไม่เจอ) คืน None → ส่งให้ AI ลองต่อ
"""
import json
import re
import time


def _p():
    import voice_profile
    return voice_profile.pol()

_LEAD = re.compile(r"^(ช่วย|ขอ|รบกวน|ผู้ช่วย|บอท|hey|โอเค|ok|okay|เอ่อ|อ่า|อืม|เออ|แล้วก็|งั้น)\s*", re.I)
_TAIL = re.compile(r"\s*(ครับ|คับ|ค่ะ|คะ|ค่า|จ้า|จ้ะ|นะ|น่ะ|หน่อย|ที|ด้วย|ให้|เลย|ซิ|สิ|เดี๋ยวนี้|ได้ไหม|ได้มั้ย|"
                   r"ได้ป่ะ|ไหม|มั้ย|[.!?。,~])$", re.I)

_SYS = {
    "wifi": ("wifi", "wi-fi", "wi fi", "ไวไฟ", "วายฟาย"),
    "bluetooth": ("bluetooth", "บลูทูธ", "บลูทูท", "บลูทู"),
    "torch": ("ไฟฉาย", "แฟลช", "flash"),
    "airplane_mode": ("โหมดเครื่องบิน", "โหมดบิน", "airplane mode"),
    "do_not_disturb": ("โหมดห้ามรบกวน", "ห้ามรบกวน", "dnd"),
    "mobile_data": ("เน็ตมือถือ", "ข้อมูลมือถือ", "อินเทอร์เน็ตมือถือ", "mobile data", "ดาต้า"),
    "location": ("gps", "จีพีเอส", "ตำแหน่ง", "โลเคชั่น", "location"),
    "hotspot": ("ฮอตสปอต", "hotspot", "ปล่อยเน็ต", "แชร์เน็ต"),
    "nfc": ("nfc", "เอ็นเอฟซี"),
}
# คำที่บอกว่าเป็นประโยคซับซ้อน → ให้ AI จัดการ
_COMPLEX = ("แล้ว", "และ", "ค้นหา", "หา ", "เล่น", "ส่ง", "พิมพ์", "เพลง", "คลิป", "วิดีโอ", "ใน ", "ไปที่",
            "ของ", "กับ", "หลัง", "ก่อน", "ถ้า", "เวลา", "นาที", "โมง", "?")


def _clean(t):
    t = re.sub(r"\[[^\]]*\]", " ", t or "")          # ตัดหมายเหตุระบบ [ ... ]
    t = " ".join(t.split()).strip().lower()
    prev = None
    while prev != t:
        prev = t
        t = _LEAD.sub("", t).strip()
        t = _TAIL.sub("", t).strip()
    return t


def _run(name, args, ctx):
    import phone_tools
    entry = phone_tools.TOOLS.get(name)
    if not entry:
        return None
    try:
        return str(entry[0](args, ctx))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _polish(res):
    if res is None:
        return None
    res = res.strip()
    if res.startswith("ERROR:"):
        res = "ทำไม่สำเร็จ: " + res[6:].strip()
    return res


def _battery(ctx):
    raw = _run("battery_status", {}, ctx) or ""
    try:
        b = json.loads(raw)
    except (ValueError, TypeError):
        return None
    st = {"CHARGING": "กำลังชาร์จ", "FULL": "ชาร์จเต็มแล้ว", "DISCHARGING": "ไม่ได้ชาร์จ",
          "NOT_CHARGING": "ไม่ได้ชาร์จ"}.get(str(b.get("status", "")).upper(), "")
    t = b.get("temperature")
    return (f"แบตเหลือ {b.get('percentage')}%" + (f" ({st})" if st else "")
            + (f" อุณหภูมิ {round(float(t))}°C" if t is not None else "") + f" {_p()}")


import chat_apps  # noqa: E402

# ชื่อแอปแชทในประโยค (ไทย/อังกฤษ/สะกดเพี้ยน) — ตารางกลางอยู่ใน chat_apps.py
_DM_APP = chat_apps.ANY
_DM = re.compile(r"(?:(?:ส่งข้อความ|ส่งแชท|ส่งไลน์|ส่ง|แชท)\s*(?:ไป)?\s*(?:หา|ให้|ถึง)|"
                 r"(?:ทัก|ตอบ)(?:กลับ)?(?:แชท|ข้อความ)?\s*(?:ไป)?\s*(?:หา|ให้)?)"
                 r"\s*(?P<to>.+?)\s*"
                 r"(?:(?<!ชื่อ)ว่า|บอกว่า|ข้อความว่า)\s*(?P<msg>.+)$", re.I)


# "ไปที่แชทของ heart แล้วเขียนข้อความว่า ..." / "ไปที่แชท ภรรยา แล้วพิมพ์ ฝันดี กดส่งที"
_DM2 = re.compile(r"(?:ห้อง)?(?:แชท|แชต|แชร์)\s*(?:ของ|กับ)?\s*(?P<to>.+?)\s*(?:แล้ว)?\s*(?:เขียน|พิมพ์|ส่ง)(?:ข้อความ)?\s*(?:(?<!ชื่อ)ว่า|บอกว่า)?"
                  r"\s*(?P<msg>.+?)\s*(?:(?:แล้ว)?\s*(?:กด)?\s*ส่ง\s*(?:ข้อความ)?\s*(?:ให้)?\s*(?:ที|หน่อย|ด้วย|เลย)?)?$")


def app_key(word):
    """คำที่พูด/พิมพ์ → ชื่อแอปมาตรฐาน ('instragram' → 'instagram', 'เฟส' → 'messenger')"""
    w = (word or "").strip().lower()
    return chat_apps.key(w, dm=True) or w


def _last_dm_app():
    try:
        import skills
        return skills.get_pref("dm_app")
    except Exception:  # noqa: BLE001
        return None


_HERE = re.compile(r"^(?:ช่วย)?\s*(?:พิมพ์|ส่ง|ตอบ|เขียน)(?:ข้อความ)?(?:กลับ)?(?:ไป)?\s*(?:ให้)?\s*(?:ว่า|บอกว่า)\s*(?P<msg>.+)$")
# ไม่มีคำว่า "ว่า": "พิมพ์ทำไรอยู่แล้วกดส่ง" (ใช้เฉพาะตอนเปิดห้องแชทค้างอยู่)
_HERE_LOOSE = re.compile(r"^(?:ช่วย)?\s*(?:พิมพ์|เขียน)(?:ข้อความ)?\s*(?:ไป)?\s*(?P<msg>.+)$"
                         r"|^(?:ช่วย)?\s*ตอบ(?:กลับ)?\s*(?:ไป)?\s*(?P<msg2>.+?)\s*(?:แล้ว)?\s*(?:กด)?\s*ส่ง\S{0,6}$")
_NOT_HERE = re.compile(r"(คำถาม|ทำไม|อะไร\s*ดี|ยังไง\s*ดี|รูป|ภาพ|ไฟล์|คลิป|วิดีโอ|^หา\s|\sหา\s|ใน(ไลน์|ไอจี|เฟส|ig|line|instagram|messenger|เมสเซนเจอร์)|"
                       r"ทาง(ไลน์|ไอจี|เฟส)|แอป|แอพ)", re.I)
_SEND_TAIL = re.compile(r"\s*(?:แล้ว\s*(?:ก็)?)?\s*(?:กด)?\s*ส่ง\s*(?:ข้อความ)?\s*(?:เลย|ให้|ที|ด้วย|หน่อย|นะ|ครับ|ค่ะ)*\s*$")


def _strip_send_tail(msg):
    """'ทำไรอยู่แล้วกดส่ง' → 'ทำไรอยู่'"""
    m = (msg or "").strip()
    prev = None
    while prev != m:
        prev = m
        m = _SEND_TAIL.sub("", m).strip()
        m = re.sub(r"\s*(ให้หน่อย|หน่อย|ให้ที|ด้วย)$", "", m).strip()
    return m


def dm(text, ctx=None, on_start=None):
    """'ส่งข้อความหาต้นในไอจีว่า ...' / 'เข้าไอจีแล้วส่งข้อความหาต้นว่า ...' → ส่งจริงโดยไม่ผ่าน AI
    (โมเดลเล็กชอบตอบว่า 'ส่งแล้ว' ทั้งที่ยังไม่ได้ส่ง) คืนผลตามจริง หรือ None ถ้าไม่ใช่คำสั่งแบบนี้"""
    raw = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    raw = re.sub(r"^(?:โอเค|ok|เอ่อ|อ่า|อืม|แล้วก็|งั้น|ช่วย)\s*", "", raw, flags=re.I)
    h = _HERE.match(raw)
    loose = None if h else _HERE_LOOSE.match(raw)
    if loose and _NOT_HERE.search(loose.group("msg") or loose.group("msg2") or ""):
        loose = None                         # มีผู้รับ/แอป/รูป/ไฟล์ → ไม่ใช่ "พิมพ์ในห้องที่เปิดอยู่"
    if h or loose:                           # "พิมพ์ว่า ..." / "พิมพ์ทำไรอยู่แล้วกดส่ง" ตอนเปิดห้องแชทค้างไว้
        import share_tools
        msg = _strip_send_tail(h.group("msg") if h else (loose.group("msg") or loose.group("msg2")))
        if not msg:
            return None
        if loose and not share_tools.chat_open():
            return None                      # ไม่ได้เปิดห้องแชท → ให้ตัวแยกเจตนาตีความแทน
        if on_start:
            on_start()
        res = share_tools.send_here(msg, ctx)
        if res.startswith("ERROR: ตอนนี้ไม่ได้เปิดห้องแชท"):
            r2 = share_tools.reply_last(msg, ctx)        # ไม่ได้เปิดห้องแชท → ตอบคนที่เพิ่งทักมา (แอปของเขา)
            if r2:
                res = r2
        print(time.strftime("[%H:%M:%S]"), f"💬 send_here {msg!r}: {res[:120]}", flush=True)
        return ("ส่งไม่สำเร็จ: " + res[6:].strip()) if res.startswith("ERROR") else res.split(" (")[0]
    res = _dm_regex(raw, ctx, on_start)
    if res is not None or not _DM_INTENT.search(raw) or re.search(r"(อ่าน|มี|ดู|เช็ค)\s*(ข้อความ|แชท)", raw):
        return res
    if re.match(r"^\s*(ช่วย)?\s*ตอบ", raw) and not re.search(_DM_APP, raw, re.I):
        return None                          # "ตอบแม่ว่า..." → ดูแอปจากแจ้งเตือน (fastpath.reply_chat)
    return None                              # ประโยควกวน → ให้ตัวแยกเจตนา (router) จัดการ


_DM_INTENT = re.compile(r"((ส่ง|พิมพ์|ทัก|ตอบ|บอก|เขียน).{0,60}(ข้อความ|แชท|แชต|แชร์|ไลน์|ไอจี|ig|instagram|อินสตา|"
                        r"เมสเซนเจอร์|messenger|เฟส)|(ข้อความ|แชท|แชต|แชร์|ไดเร็ก|dm).{0,60}(ส่ง|พิมพ์|บอก|ว่า))", re.I)


def _dm_llm(raw, ctx=None, on_start=None):
    """ประโยคพูดที่ยาว/วกวน/ถอดเสียงเพี้ยน จนแยกด้วยกฎไม่ได้ → ให้ AI แยก แอป/ผู้รับ/ข้อความ (1 รอบ ไม่ใช้เครื่องมือ)
    แล้วระบบส่งเองทุกขั้น (ไม่ปล่อยให้ AI กดเองทีละขั้น ซึ่งชอบหลง)"""
    import agent
    prompt = ("[งานแยกคำสั่ง ห้ามทำอย่างอื่น] ประโยคนี้มาจากเสียงพูด อาจถอดเพี้ยน (แชร์=แชท, ไอจี/IG=instagram, "
              "เฟส=messenger) แยกเป็น JSON บรรทัดเดียวเท่านั้น:\n"
              '{"app": "instagram|line|messenger|telegram|whatsapp|", "to": "ชื่อผู้รับตามที่พูด", '
              '"text": "ข้อความที่จะส่ง"}\n'
              "ถ้าไม่ได้บอกแอป ให้ app เป็น \"\" / ถ้าไม่ใช่คำสั่งส่งข้อความหาคน ให้ตอบ {}\n"
              f"ประโยค: {raw}")
    t0 = time.time()
    try:
        resp, who = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}], [])
    except Exception as e:  # noqa: BLE001
        print("dm_llm error:", e, flush=True)
        return None
    out = agent._collect_text(resp.get("content", []))
    print(time.strftime("[%H:%M:%S]"), f"🧩 แยกคำสั่งด้วย {who} ({time.time() - t0:.1f}s): {out[:150]!r}", flush=True)
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except ValueError:
        return None
    import share_tools
    to = share_tools.clean_name(str(j.get("to") or ""))
    msg = str(j.get("text") or "").strip()
    app = str(j.get("app") or "").strip().lower()
    app = app_key(app)
    explicit = bool(app)
    if not app and to:
        try:
            import contacts
            app = contacts.app_for(to)
        except Exception:  # noqa: BLE001
            app = None
    app = app or _last_dm_app()
    if not (app and to and msg) or len(to) > 40 or app not in chat_apps.DM_APPS:
        return None
    return _do_send(app, to, msg, ctx, on_start, explicit=explicit)


def _dm_regex(raw, ctx=None, on_start=None):
    head = re.split(r"(?<!ชื่อ)ว่า|บอกว่า", raw, maxsplit=1)[0]   # ชื่อแอปต้องอยู่ก่อนตัวข้อความ ("ชื่อว่า" ไม่นับ)
    am = re.search(_DM_APP, head, re.I)
    if am:
        app = app_key(am.group(1))
        rest = (raw[:am.start()] + " " + raw[am.end():]).strip()
    else:                                    # ไม่ได้บอกแอป → แอปที่คุยกับคนนี้ (จำไว้) หรือแอปที่ส่งล่าสุด
        app = None
        if not (_DM.search(raw) or _DM2.search(raw)):
            return None
        rest = raw
    rest = re.sub(r"^(?:ช่วย|ขอ)?\s*(?:เปิด|เข้า)\s*(?:ไป)?\s*(?:ใน|ที่)?\s*(?:แอป|แอพ)?\s*(?:แล้ว)?\s*", "", rest)
    rest = re.sub(r"\s*(?:ใน|ทาง|ผ่าน)\s*(?=ว่า|บอกว่า|$)", " ", rest)
    m = _DM.search(rest) or _DM2.search(rest)
    if not m:
        return None
    to = re.sub(r"\s*(?:ใน|ทาง|ผ่าน)$", "", m.group("to")).strip()
    import share_tools
    to = share_tools.clean_name(to)
    msg = re.sub(r"\s*(?:ให้หน่อย|หน่อย|ให้ด้วย)$", "", m.group("msg")).strip()
    if not to or not msg or len(to) > 40:
        return None
    explicit = app is not None
    if not app:
        try:
            import contacts
            app = contacts.app_for(to)
        except Exception:  # noqa: BLE001
            app = None
        app = app or _last_dm_app()
        if not app:
            return None
    return _do_send(app, to, msg, ctx, on_start, explicit=explicit)


def _do_send(app, to, msg, ctx, on_start=None, confirmed=False, explicit=True):
    if not confirmed:
        try:
            import send_confirm
            q = send_confirm.maybe_hold(app, to, msg, ctx, explicit)
            if q:
                return q                     # ถามก่อน (ชื่อกำกวม / อ่านทวนตอนสั่งด้วยเสียง)
            r = send_confirm.resolved()
            if r:
                app, to = r
        except Exception as e:  # noqa: BLE001
            print(f"[dm] ตรวจก่อนส่งไม่ได้: {e}", flush=True)
    if on_start:
        on_start()
    try:
        import share_tools
        res = share_tools.send_dm({"app": app, "to": to, "text": msg}, ctx)
    except Exception as e:  # noqa: BLE001
        res = f"ERROR: {e}"
    finally:
        if getattr(ctx, "send_ok", None):
            try:
                ctx.send_ok = None               # ยืนยันใช้ได้ครั้งเดียว
            except Exception:  # noqa: BLE001
                pass
    print(time.strftime("[%H:%M:%S]"), f"💬 send_dm {app} → {to}: {res[:150]}", flush=True)
    if res.startswith("ERROR"):
        return "ส่งไม่สำเร็จ: " + res[6:].strip()
    return res.split(" (")[0] + f" {_p()}"


_ALWAYS_ON = re.compile(r"^(?:เปิด)?\s*(?:โหมด)?\s*ฟัง\s*(?:ตลอด|ตลอดเวลา|ทุกคำ)|ไม่ต้อง\s*(?:รอ|เรียก)\s*(?:ชื่อ|คำปลุก)")
_ALWAYS_OFF = re.compile(r"^(?:ปิด|เลิก|หยุด)\s*(?:โหมด)?\s*ฟัง\s*(?:ตลอด|ตลอดเวลา)|(?:กลับไป)?ใช้คำปลุก|รอเรียกชื่อ")


def listen_mode(text):
    """'ฟังตลอด' = ไม่ต้องเรียกผู้ช่วย / 'ปิดโหมดฟังตลอด' = กลับไปรอคำปลุก"""
    import os
    import config
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    flag = os.path.join(config.DATA_DIR, "always_listen")
    if _ALWAYS_OFF.search(t):
        if os.path.exists(flag):
            os.remove(flag)
        return f"กลับไปรอคำปลุกแล้ว{_p()} เรียก \"ผู้ช่วย\" เมื่อต้องการ"
    if _ALWAYS_ON.search(t) and len(t) < 40:
        open(flag, "w").close()
        try:
            import speaker_id
            who = "" if speaker_id.enrolled() else (" (แนะนำให้สอนเสียงก่อน: bash enroll_voice.sh "
                                                    "จะได้ฟังเฉพาะเสียงคุณ)")
        except Exception:  # noqa: BLE001
            who = ""
        return f"เปิดโหมดฟังตลอดแล้ว{_p()} พูดสั่งได้เลยไม่ต้องเรียกชื่อ{who}"
    return None


PRIVATE = {"v": False}


def handle(text, ctx=None):
    """คืนข้อความตอบ ถ้าเป็นคำสั่งด่วนและทำสำเร็จ / คืน None ให้ส่งต่อ AI"""
    PRIVATE["v"] = False
    import appoint
    import send_confirm
    d = send_confirm.handle_text(text, ctx) or appoint.handle_text(text, ctx)   # กำลังถามตอบค้างอยู่ → มาก่อนทุกอย่าง
    if d:
        return d
    import providers
    sw = providers.from_text(re.sub(r"\[[^\]]*\]", " ", text or ""))   # "สลับไปใช้ claude"
    if sw:
        return sw
    d = listen_mode(text)
    if d:
        return d
    if re.search(r"^(สรุปผล(การ)?ทดสอบ|สรุปความเร็ว|รายงานความเร็ว|ความเร็ว(ผู้ช่วย|บอท|ระบบ)|ช้าตรงไหน)",
                 re.sub(r"\s+", "", re.sub(r"\[[^\]]*\]", " ", text or ""))):
        import perf
        return perf.summary(7)
    import daily
    d = daily.handle_text(text, ctx)              # ปลุก · จับเวลา · เตือน → ใช้แอปนาฬิกาโดยตรง ไม่ต้องใช้ AI
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
    import recovery
    if recovery.pending(text):                       # เพิ่งล้มในระบบสำเร็จรูป → ให้ AI แก้ต่อเลย ไม่ลองซ้ำ
        return None
    import proactive
    import routines
    for mod in (routines, proactive, self_heal, user_profile, contacts, autoreply, contact_scan, screen_context, app_test, perf, app_learn, forms, social, inapp, app_tasks, media, app_skills, device, app_brain, plugins, info, vision, mind):   # ซ่อมตัวเอง · ข้อมูลของฉัน · เรียนรู้แอป · ฟอร์ม
        try:
            d = mod.handle_text(text) if mod is user_profile else mod.handle_text(text, ctx)
        except Exception as e:  # noqa: BLE001
            self_heal.note(e)
            d = f"❗ {e}"
        if d:
            import recovery
            if recovery.is_failure(mod.__name__, d):        # ระบบสำเร็จรูปล้ม → ให้ AI แก้ปัญหาต่อ (ไม่ยอมแพ้ทันที)
                recovery.note(mod.__name__, text, d)
                return None
            PRIVATE["v"] = mod is user_profile           # ข้อมูลส่วนตัว → ไม่เก็บลงประวัติแชทที่ส่งให้ AI
            return d
    d = dm(text, ctx)
    if d:
        return d
    import fastpath
    d = fastpath.direct(text, ctx)          # แจ้งเตือน · เช็คเครื่อง · ตอบแชทคนที่ทักมา
    if d:
        return d
    raw = " ".join((text or "").lower().split())
    t = _clean(text)
    if not t or len(t) > 40:
        return None

    # เสียง / สาย
    if re.fullmatch(r"(ลด|เบา|หรี่)\s*เสียง\s*(ลง)?\s*(อีก)?\s*(นิด|หน่อย)?|เสียง\s*(เบา|ค่อย)\s*ลง|เบาลง(อีก)?(หน่อย)?", t):
        return _polish(_run("volume_step", {"direction": "down"}, ctx))
    if re.fullmatch(r"(เพิ่ม|เร่ง)\s*เสียง\s*(ขึ้น)?\s*(อีก)?\s*(นิด|หน่อย)?|เสียง\s*ดัง\s*ขึ้น|ดังขึ้น(อีก)?(หน่อย)?", t):
        return _polish(_run("volume_step", {"direction": "up"}, ctx))
    if re.fullmatch(r"(ปิดเสียง|ปิดเสียงเครื่อง|เงียบ|mute)", t):
        return _polish(_run("volume_step", {"direction": "mute"}, ctx))
    if re.fullmatch(r"(รับสาย|รับโทรศัพท์|รับเลย|กดรับ(สาย)?)", t):
        return _polish(_run("answer_call", {}, ctx))
    if re.fullmatch(r"(วางสาย|ตัดสาย|ไม่รับสาย|ปฏิเสธสาย|กดวาง(สาย)?)", t):
        return _polish(_run("end_call", {}, ctx))
    # ควบคุมจอแบบคนใช้: ย้อนกลับ / เลื่อน
    if re.fullmatch(r"(ย้อน|ถอย)?\s*กลับ(หน้า)?(ก่อนหน้า|เดิม)?|back|ย้อนกลับ", t):
        return _polish(_run("press_key", {"key": "back"}, ctx)) and f"ย้อนกลับแล้ว{_p()}"
    m2 = re.fullmatch(r"(เลื่อน|ปัด|สไลด์)\s*(จอ|หน้าจอ)?\s*(ลง|ขึ้น|ซ้าย|ขวา)\s*(อีก)?\s*(นิด|หน่อย)?", t)
    if m2:
        d = {"ลง": "up", "ขึ้น": "down", "ซ้าย": "left", "ขวา": "right"}[m2.group(3)]
        _run("swipe", {"direction": d}, ctx)
        return f"เลื่อน{m2.group(3)}ให้แล้ว{_p()}"
    # แบต
    if re.fullmatch(r"(แบต|แบตเตอรี่|battery)(เครื่อง)?\s*(เหลือ)?\s*(เท่าไหร่|เท่าไร|กี่เปอร์เซ็นต์|กี่%)?", t):
        return _battery(ctx)
    # หน้าโฮม / ล้างแรม / ล็อกจอ
    if re.fullmatch(r"(กลับ|ไป)?\s*(หน้าโฮม|หน้าหลัก|โฮม|home)", t):
        return _polish(_run("go_home", {}, ctx))
    if re.fullmatch(r"(ล้าง|เคลียร์|clear)\s*(แรม|ram|แอปเบื้องหลัง|แอพเบื้องหลัง)", t):
        res = _run("clean_ram", {}, ctx)
        return None if res is None or res.startswith("ERROR") else f"ล้างแรมแล้ว{_p()}\n" + res[:300]
    if re.fullmatch(r"(ล็อก|ล็อค|lock)\s*(จอ|หน้าจอ|เครื่อง)|ปิดจอ|ปิดหน้าจอ|ดับจอ", t):
        return _polish(_run("lock_screen", {}, ctx))

    # ความสว่าง
    m = re.fullmatch(r"(ปรับ|ตั้ง)?\s*(ความสว่าง|แสงจอ|แสงหน้าจอ|ไฟจอ|ไฟหน้าจอ)\s*(เป็น|ที่)?\s*(\d{1,3})\s*(%|เปอร์เซ็นต์)?", t)
    if m:
        return _polish(_run("brightness", {"level": f"{min(100, int(m.group(4)))}%"}, ctx))
    if re.fullmatch(r"(ลด|หรี่)\s*(แสง|ความสว่าง|ไฟ)?\s*(จอ|หน้าจอ)?\s*(ลง)?|จอมืดลง|หรี่จอ", t):
        return _polish(_run("brightness", {"level": "-20%"}, ctx))
    if re.fullmatch(r"(เพิ่ม)\s*(แสง|ความสว่าง|ไฟ)\s*(จอ|หน้าจอ)?|จอสว่างขึ้น|สว่างขึ้น", t):
        return _polish(_run("brightness", {"level": "+20%"}, ctx))
    if re.fullmatch(r"(ความสว่าง|แสงจอ)\s*(อัตโนมัติ|ออโต้|auto)", t):
        return _polish(_run("brightness", {"level": "auto"}, ctx))

    # เปิด / ปิด ...
    m = re.fullmatch(r"(เปิด|ปิด)\s*(.+)", t)
    if not m:
        return None
    on, target = m.group(1) == "เปิด", m.group(2).strip()
    # "เปิด instagram แล้วเปิดแชท" / "เปิดไลน์ เข้าหน้าแชท"
    pm = re.fullmatch(r"(.+?)\s*(?:แล้ว)?\s*(?:เข้า|เปิด|ไป|ดู)?\s*(?:หน้า|ที่|ไปที่)?\s*"
                      r"(กล่องข้อความ|แชท|แชต|ข้อความ|dm|inbox|ไดเร็กต์|ไดเร็ก|ไดเร็ค|direct|ค้นหา|โปรไฟล์|แจ้งเตือน)",
                      target) if on else None
    if pm:
        app_part = re.sub(r"\s*แล้ว\s*(เข้า|เปิด|ไป|ดู)?\s*(กล่อง)?$", "", pm.group(1)).strip()
    if pm and app_part and "แล้ว" not in app_part and len(app_part.split()) <= 3:
        import phone_tools
        app = re.sub(r"^(แอป|แอพ|app)\s*", "", app_part).strip()
        page = phone_tools.PAGE_ALIASES.get(pm.group(2), pm.group(2))
        res = _run("open_app", {"app": app, "page": page}, ctx)
        if res and not res.startswith("ERROR") and "ไม่ได้" not in res:
            return f"เปิด {app} เข้าหน้า{pm.group(2)}แล้ว{_p()}"
        if res and res.startswith("ERROR") and "ลองแล้ว" in res:
            return _polish(res)
        return None
    if re.search(r"\d|นาที|ชั่วโมง|โมง", raw):
        return None                             # "ปิด wifi 10 นาที" → ให้ AI ใส่ระยะเวลา
    for tool, words in _SYS.items():
        if target in words or target.replace(" ", "") in words:
            return _polish(_run(tool, {"on": on}, ctx))
    if any(k in f"{target} " or k in raw for k in _COMPLEX) or len(target.split()) > 3 or re.search(r"\d", target):
        return None                             # มีเงื่อนไข/เวลา/ตัวเลข → ให้ AI ตีความ

    app = re.sub(r"^(แอป|แอพ|แอปพลิเคชัน|app)\s*", "", target).strip()
    if not app or app in ("เสียง", "เพลง", "ทีวี", "ไฟ", "เน็ต", "เน็ตมือถือ", "ข้อมูล", "จอ"):
        return None
    if on:
        res = _run("open_app", {"app": app}, ctx)
        if res and res.startswith("ERROR") and "ลองแล้ว" in res:
            return _polish(res)             # ลองครบทุกวิธีแล้ว ไม่ต้องให้ AI วนลองซ้ำ
        if res is None or res.startswith("ERROR") or res.startswith("เจอหลายแอป"):
            return None                     # ให้ AI หาแอปต่อ (list_apps)
        return f"เปิด {app} แล้ว{_p()}"
    res = _run("close_app", {"app": app}, ctx)
    if res is None or res.startswith("ERROR"):
        return None
    return res if "ปิด" in res else f"ปิด {app} แล้ว{_p()}"


_handle_raw = handle


def handle(text, ctx=None):
    """คำตอบด่วนทุกแบบ → ลงท้าย "ครับ" ตามที่ตั้งไว้"""
    r = _handle_raw(text, ctx)
    if isinstance(r, str):
        import polite
        return polite.fix(r)
    return r
