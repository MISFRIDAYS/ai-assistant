"""ตัวแยกเจตนา: AI แค่ "เข้าใจว่าผู้ใช้ต้องการอะไร" → ระบบลงมือเองด้วยโค้ดที่ทดสอบแล้ว

ทำไมแบบนี้แม่นกว่า: ให้ AI กดหน้าจอเองทีละขั้นมักหลง/ตอบว่าทำแล้วทั้งที่ยังไม่ได้ทำ
แต่ให้ AI แยกประโยค (แม้พูดวกวน/ถอดเสียงเพี้ยน) เป็น JSON สั้นๆ นั้นแม่นมาก แล้วโค้ดทำงานจริงให้

เจตนาที่รองรับ:
  open_app · close_app · send_message · send_file · reply · notifications · device_check · setting
  search · analyze_file · remember · forget · chat · phone_task (งานบนจออื่นๆ → AI ใช้เครื่องมือ)
"""
import json
import os
import re
import time
import config


INTENTS = ("open_app", "close_app", "send_message", "send_file", "reply", "notifications", "device_check",
           "setting", "search", "analyze_file", "remember", "forget", "chat", "phone_task", "ignore", "compose",
           "fill_form")

CLASSIFY = """คุณคือตัวแยกคำสั่งของผู้ช่วยบนแท็บเล็ต ข้อความอาจมาจากเสียง (สะกดเพี้ยนได้: แชร์=แชท, ไอจี/IG/อินสตาร์แกรม=instagram,
เฟส=messenger, ยูทูป=youtube) ตอบ JSON บรรทัดเดียวเท่านั้น ห้ามมีข้อความอื่น

intent ที่ใช้ได้ (เลือกอันเดียว):
- open_app      เปิดแอป {"app": "...", "page": "chat|search|profile|"}
- close_app     ปิดแอป {"app": "..."}
- send_message  ส่งข้อความหาคน {"app": "instagram|line|messenger|telegram|whatsapp|", "to": "ชื่อผู้รับ หรือ '' ถ้าไม่ได้บอก (= ห้องแชทที่เปิดอยู่)", "text": "ข้อความ"}
- send_file     ส่งรูป/คลิป/ไฟล์ {"app": "...", "to": "ชื่อผู้รับ หรือ ''", "file": "รูปล่าสุด|คลิปล่าสุด|ไฟล์ล่าสุด|ชื่อไฟล์", "text": "ข้อความประกอบ หรือ ''"}
- reply         ตอบคนที่ทักมา (ไม่บอกแอป) {"to": "ชื่อ หรือ 'ล่าสุด'", "text": "..."}
- notifications อ่าน/สรุปแจ้งเตือน, ใครทักมา
- device_check  เช็คเครื่อง แบต แรม ความร้อน พื้นที่
- setting       ตั้งค่าเครื่อง {"setting": "wifi|bluetooth|brightness|volume|airplane|dnd|torch|data|location|hotspot|nfc|rotate|timeout|clean_ram|lock|home|answer_call|end_call", "value": "on|off|ตัวเลข|+|-|auto"}
- compose       หาข้อมูล/เขียนเนื้อหา แล้ว "พิมพ์ลงแอป/ส่งให้คน/โพสต์" {"query": "เรื่องที่ต้องหา หรือ ''", "write": "จะให้เขียนอะไร", "app": "แอปปลายทาง หรือ '' = ช่องที่เปิดอยู่", "to": "ชื่อผู้รับ หรือ ''", "send": true/false}
- fill_form     กรอกแบบฟอร์มที่เปิดอยู่บนจอ {"ask_all": true ถ้าผู้ใช้ให้ถามทุกช่อง}
- search        หาข้อมูลจากเน็ต ข่าว ราคา อากาศ ผลบอล ข้อเท็จจริงล่าสุด {"query": "..."}
- analyze_file  อ่าน/สรุป/วิเคราะห์ไฟล์ในเครื่อง {"file": "ชื่อไฟล์ หรือ ล่าสุด", "question": "ต้องการรู้อะไร"}
- remember      ผู้ใช้บอกให้จำข้อมูล {"text": "สิ่งที่ต้องจำ"}
- forget        ให้ลืมเรื่องที่จำไว้ {"text": "..."}
- phone_task    งานบนเครื่อง/ในแอปอื่นๆ ที่ต้องกดหลายขั้น (เช่น เปิดยูทูปหาเพลงแล้วเล่น, กดไลก์) {"goal": "..."}
- chat          คุยเล่น ถามความรู้ทั่วไป ขอคำแนะนำ แปลภาษา วิเคราะห์รูปที่ส่งมา
- ignore        (เฉพาะโหมดฟังตลอด) ประโยคที่ไม่ได้พูดกับผู้ช่วย: คุยกับคนอื่น บ่นลอยๆ ร้องเพลง เสียงทีวี ประโยคไม่จบความ

รูปแบบ: {"intent": "...", ...ฟิลด์ของ intent นั้น}
ชื่อผู้รับให้คัดลอกตามที่ผู้ใช้พูด ไม่ต้องใส่คำว่า แชท/ชื่อ/คุณ นำหน้า"""


def _log(*a):
    print(time.strftime("[%H:%M:%S]"), "🧭", *a, flush=True)


def _p():
    import voice_profile
    return voice_profile.pol()


_fast_off = [0.0]


def _parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _complete(d, text):
    """ผลแยกคำสั่งครบพอจะลงมือไหม (ตัวเร็วมักดึงชื่อคน/ข้อความไทยไม่ครบ)"""
    it = d.get("intent")
    if it not in INTENTS:
        return False
    if it in ("send_message", "reply"):
        return bool((d.get("to") or it == "reply") and d.get("text"))
    if it == "send_file":
        return bool(d.get("to") or d.get("app"))
    if it in ("open_app", "close_app"):
        return bool(d.get("app"))
    return True


def classify(text, has_image=False, screen="", ambient=False, context=""):
    """ข้อความผู้ใช้ → dict เจตนา (ถ้า AI ใช้ไม่ได้ คืน {"intent": "phone_task"} ให้ทำแบบเดิม)"""
    import agent
    t0 = time.time()
    note = "\n(ผู้ใช้แนบรูป/ไฟล์มาด้วย)" if has_image else ""
    if context:
        note += (f"\n[บทสนทนาก่อนหน้า: {context}] — ถ้าข้อความนี้เป็นคำตอบของคำถามที่ผู้ช่วยเพิ่งถาม "
                 "(เช่น บอกชื่อแอป/ชื่อคน/ข้อความ) ให้รวมกับคำสั่งเดิมให้ครบ · ถ้าเป็นประโยคต่อเนื่องสั้นๆ "
                 "(\"แล้วพรุ่งนี้ล่ะ\" \"อันนั้นด้วย\" \"อีกเพลง\" \"ทำไมล่ะ\") ให้ตีความต่อจากเรื่องเดิม ห้ามตีความลอยๆ")
    if ambient:
        note += ("\n[โหมดฟังตลอด: ผู้ใช้ไม่ได้เรียกชื่อผู้ช่วย — ถ้าประโยคนี้ไม่ได้สั่ง/ถาม/คุยกับผู้ช่วยชัดเจน "
                 "ให้ตอบ {\"intent\": \"ignore\"}]")
    if screen:
        note += f"\n[สถานะหน้าจอ: {screen}] — ถ้าผู้ใช้สั่งพิมพ์/ส่ง/ตอบ โดยไม่บอกชื่อคน = ส่งในห้องแชทที่เปิดอยู่ (to เป็น '')"
    msgs = [{"role": "user", "content": [{"type": "text", "text": f"ข้อความ: {text}{note}"}]}]
    resp = None
    fast_ok = config.GROQ_API_KEY and config.LLM_PROVIDER != "groq" and os.environ.get("ROUTER_FAST", "1") != "0" \
        and time.time() > _fast_off[0]
    if not fast_ok and not ambient and config.LLM_PROVIDER in ("cloud", "ollama"):
        # ไม่มีตัวแยกเจตนาแบบเร็ว → ไม่ต้องให้ AI ตัวหลักแยกก่อน (เสีย 2-5 วิ) ส่งให้ทำงานเลยทีเดียว
        _log("ข้ามการแยกเจตนา (ไม่มี Groq) → ให้ AI ตัวหลักทำเลย")
        return {"intent": "phone_task", "goal": text}
    if config.GROQ_API_KEY and config.LLM_PROVIDER != "groq" and os.environ.get("ROUTER_FAST", "1") != "0" \
            and time.time() > _fast_off[0]:
        try:                                          # แยกเจตนาด้วย Groq (~0.3 วิ) เร็วกว่ารอ AI ตัวหลัก
            import groq_client
            resp = groq_client.create_message(CLASSIFY, msgs, None, 300,
                                              model=os.environ.get("ROUTER_MODEL") or None)   # None = รุ่นที่ Groq มีจริงตอนนี้
            who = "Groq⚡"
            if not _complete(_parse(agent._collect_text(resp.get("content", []))), text):
                if not ambient:                     # ไม่ต้องเสียเวลาแยกซ้ำ (~4 วิ) → ให้ AI ตัวหลักทำงานด้วยเครื่องมือเลย
                    _log("Groq แยกคำสั่งไม่ครบ → ให้ AI ตัวหลักทำต่อโดยตรง")
                    return {"intent": "phone_task", "goal": text}
                _log("Groq แยกคำสั่งไม่ครบ → ให้ตัวหลักแยกใหม่")
                resp = None
        except Exception as e:  # noqa: BLE001
            _log("fast router ใช้ไม่ได้ → ใช้ตัวหลัก:", str(e)[:80])
            _fast_off[0] = time.time() + (600 if "429" in str(e) else 120)
            resp = None
    if resp is None:
        try:
            resp, who = agent.call_llm(msgs, [], system=CLASSIFY)
        except Exception as e:  # noqa: BLE001
            _log("classify error:", e)
            return {"intent": "phone_task", "goal": text}
    out = agent._collect_text(resp.get("content", []))
    try:
        import extras
        extras.record_usage(who, resp.get("usage", {}))
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    if d.get("intent") not in INTENTS:
        d = {"intent": "chat"}
    _log(f"{who} {time.time() - t0:.1f}s → {json.dumps(d, ensure_ascii=False)[:160]}")
    return d


# ---------------------------------------------------------------- ลงมือ

import chat_apps  # noqa: E402


def _app(a):
    a = (a or "").strip().lower()
    return chat_apps.key(a, dm=True) or a


def _dm_app(app, to):
    """แอปที่จะส่ง: ที่ผู้ใช้บอก → แจ้งเตือนล่าสุดของคนนั้น → แอปที่ส่งครั้งล่าสุด"""
    app = _app(app)
    if app:
        return app
    try:                                      # ตอนนี้เปิดแอปแชทค้างไว้ → ส่งในแอปนั้น
        import contacts
        import phone_tools
        fg = phone_tools._fg() or ""
        if fg in contacts.APP_KEYS and not contacts.app_for(to):
            return contacts.APP_KEYS[fg]
    except Exception:  # noqa: BLE001
        pass
    try:
        import contacts                       # จำไว้ว่าคนนี้คุยกันในแอปไหน (เคยส่ง/เคยทักมา/ผู้ใช้สอน)
        got = contacts.app_for(to)
        if got:
            return got
    except Exception:  # noqa: BLE001
        pass
    try:
        import fastpath
        items, _ = fastpath._notif_items()
        q = (to or "").replace(" ", "").lower()
        for n in items or []:
            if q and q in (n.get("title") or "").replace(" ", "").lower():
                got = fastpath._PKG_APP.get(n.get("packageName"))
                if got:
                    return got
    except Exception:  # noqa: BLE001
        pass
    try:
        import skills
        return skills.get_pref("dm_app") or ""
    except Exception:  # noqa: BLE001
        return ""


def _result(res, ok_prefix=""):
    res = str(res or "")
    if res.startswith("ERROR"):
        return "ทำไม่สำเร็จ: " + res[6:].strip()
    return ok_prefix + res.split(" (")[0]


def _setting(d, ctx):
    import phone_tools
    s = (d.get("setting") or "").lower()
    v = str(d.get("value") or "").lower().strip()
    on = v not in ("off", "ปิด", "false", "0", "no")
    T = phone_tools.TOOLS

    def run(name, args):
        if name not in T:
            return f"ERROR: ไม่มีคำสั่ง {name}"
        return str(T[name][0](args, ctx))
    simple = {"wifi": "wifi", "bluetooth": "bluetooth", "airplane": "airplane_mode", "dnd": "do_not_disturb",
              "torch": "torch", "data": "mobile_data", "location": "location", "hotspot": "hotspot", "nfc": "nfc"}
    if s in simple:
        return run(simple[s], {"on": on})
    if s == "brightness":
        lv = v if v else "50"
        if lv in ("+", "up", "เพิ่ม"):
            lv = "+20%"
        elif lv in ("-", "down", "ลด"):
            lv = "-20%"
        elif re.fullmatch(r"\d{1,3}", lv):
            lv += "%"
        return run("brightness", {"level": lv})
    if s == "volume" and not re.fullmatch(r"\d{1,3}", v):
        d = "up" if v in ("+", "up", "เพิ่ม", "on", "ดัง") else "mute" if v in ("off", "mute", "ปิด", "0") else "down"
        return run("volume_step", {"direction": d})
    if s == "volume":
        if re.fullmatch(r"\d{1,3}", v):
            return run("set_volume", {"stream": "music", "volume": min(15, int(v) * 15 // 100 if int(v) > 15 else int(v))})
        cur = 7
        try:
            vols = json.loads(run("get_volume", {}))
            cur = next((x["volume"] for x in vols if x.get("stream") == "music"), 7)
        except Exception:  # noqa: BLE001
            pass
        nv = cur + 3 if v in ("+", "up", "เพิ่ม", "on") else max(0, cur - 3) if v in ("-", "down", "ลด") else 0 \
            if v in ("off", "mute", "ปิด") else cur
        return run("set_volume", {"stream": "music", "volume": min(15, nv)})
    if s == "rotate":
        return run("rotate_screen", {"auto": v in ("auto", "on", "")})
    if s == "timeout":
        sec = int(re.sub(r"\D", "", v) or 60)
        return run("screen_timeout", {"seconds": sec * 60 if sec <= 30 else sec})
    if s in ("answer_call", "end_call"):
        return run(s, {})
    if s == "clean_ram":
        return run("clean_ram", {"aggressive": True})
    if s == "lock":
        return run("lock_screen", {})
    if s == "home":
        return run("go_home", {})
    return f"ERROR: ยังไม่รู้จักการตั้งค่า '{s}'"


_MSG_VERB = re.compile(r"ส่ง|ตอบ|บอก|พิมพ์|ทัก|แชท|แชต|แชร์|ว่า|message|reply|send|text", re.I)
_APP_WORD = re.compile(chat_apps.ANY, re.I)


def _n(t):
    return re.sub(r"[\s\"'“”.,!?]+", "", (t or "").lower())


def _from_said(text, said):
    a, b = _n(text), _n(said)
    if not a or a in b:
        return True
    import difflib
    m = difflib.SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size >= max(3, int(len(a) * 0.6))


def _voice(ctx):
    try:
        import send_confirm
        return send_confirm._is_voice(ctx)
    except Exception:  # noqa: BLE001
        return False


def _app_said(said):
    return bool(_APP_WORD.search(said or ""))


def execute(d, ctx, on_start=None):
    """ทำตามเจตนาที่ "ลงมือได้เลย" → คืนข้อความตอบ / None ถ้าไม่ใช่เจตนาแบบนี้"""
    import phone_tools
    import share_tools
    it = d.get("intent")
    if it == "open_app":
        if not d.get("app"):
            return None
        res = phone_tools.open_app({"app": d["app"], "page": d.get("page") or ""}, ctx)
        if res.startswith("ERROR") or "ไม่ได้" in res:
            return _result(res)
        return f"เปิด {d['app']}" + (f" เข้าหน้า{d['page']}" if d.get("page") else "") + f" ให้แล้ว{_p()}"
    if it == "close_app":
        return _result(phone_tools.close_app({"app": d.get("app") or "แอปนี้"}, ctx))
    if it in ("send_message", "reply"):
        said = d.get("_said") or ""
        if said and not _MSG_VERB.search(said):
            _log("ไม่มีคำว่า ส่ง/ตอบ/บอก/พิมพ์ → ไม่ใช่การส่งข้อความ ให้ AI ทำแทน")
            return None                       # "อ่านข้อความ" "ลบข้อความใน WPS" ไม่ใช่การส่ง
        if said and (d.get("text") or "").strip() and not _from_said(d["text"], said):
            _log(f"ข้อความ {d['text']!r} ไม่ได้มาจากที่ผู้ใช้พูด → ไม่ส่ง")
            return None                       # กัน AI แต่งข้อความเอง (เช่น "✅ ค่ะ") แล้วส่งให้คนอื่น
        if said and d.get("app") and not _app_said(said):
            d["app"] = ""                     # ผู้ใช้ไม่ได้บอกแอป → ใช้แอปที่เปิดอยู่/ที่จำไว้ แทนที่ AI เดา
        to = share_tools.clean_name(d.get("to") or "")
        text = (d.get("text") or "").strip()
        if text and not to:                  # ไม่บอกผู้รับ → ส่งในห้องแชทที่เปิดค้างอยู่
            res = share_tools.send_here(text, ctx)
            if not res.startswith("ERROR: ตอนนี้ไม่ได้เปิดห้องแชท"):
                return _result(res)
        if not to or not text:
            if to and not text:
                return f"จะส่งหา {to} ว่าอะไรดี{_p()}?"
            if text and not to:
                return f"ส่งหาใครดี{_p()}?"
            return f"ส่งหาใคร ว่าอะไรดี{_p()}?"
        if (it == "reply" or to in ("ล่าสุด", "คนล่าสุด", "")) and share_tools.last_sender():
            if _voice(ctx):                   # สั่งด้วยเสียง → อ่านทวนก่อนส่งเสมอ (ไม่ส่งผ่านแจ้งเตือนทันที)
                n = share_tools.last_sender()
                import quick
                return quick._do_send(n["app"], n["to"], share_tools.reply_text(text) or text, ctx, on_start=on_start)
            res = share_tools.reply_last(share_tools.reply_text(text) or text, ctx)
            if res:
                return _result(res)
        if it == "reply" or to in ("ล่าสุด", "คนล่าสุด"):
            import fastpath
            r = fastpath.reply_chat(f"ตอบ {to} ว่า {text}", ctx)
            if r:
                return r
        app = _dm_app(d.get("app"), to)
        if not app:
            return f"จะส่งทางแอปไหนดี{_p()}? (ไลน์ / ไอจี / เมสเซนเจอร์)"
        import quick                          # ผ่านด่านเดียวกับคำสั่งด่วน: ชื่อกำกวมถาม · สั่งด้วยเสียงอ่านทวนก่อนส่ง
        res = quick._do_send(app, to, text, ctx, on_start=on_start)
        _log(f"send_dm {app} → {to}: {res[:120]}")
        return res
    if it == "send_file":
        app = _dm_app(d.get("app"), d.get("to"))
        if not app:
            return f"จะส่งทางแอปไหนดี{_p()}?"
        f = d.get("file") or "ไฟล์ล่าสุด"
        if on_start:
            on_start()
        res = share_tools.send_to_app({"app": app, "files": [f], "to": share_tools.clean_name(d.get("to") or ""),
                                       "text": d.get("text") or ""}, ctx)
        _log(f"send_file {app} → {d.get('to')}: {res[:120]}")
        return _result(res)
    if it == "notifications":
        import fastpath
        return fastpath.notifications()
    if it == "device_check":
        import fastpath
        return fastpath.health() or _result(phone_tools.device_health({}, ctx))
    if it == "setting":
        return _result(_setting(d, ctx))
    if it == "remember":
        import extras
        txt = (d.get("text") or "").strip()
        return extras.remember({"text": txt}, ctx) if txt else None
    if it == "forget":
        import extras
        return extras.forget({"query": d.get("text") or ""}, ctx)
    return None


def compose(d, ctx, user_text):
    """หาข้อมูล (ถ้ามี) → AI เขียนข้อความพร้อมพิมพ์ → พิมพ์ลงแอป/ส่งให้คน/ช่องที่เปิดอยู่"""
    import agent
    import phone_tools
    import share_tools
    data = ""
    if d.get("query"):
        g = gather({"intent": "search", "query": d["query"]}, user_text)
        data = g[1] if g else ""
    prompt = (f"คำสั่งผู้ใช้: {user_text}\nเขียนเฉพาะ \"เนื้อหาที่จะพิมพ์ลงแอป\" ({d.get('write') or 'ตามคำสั่ง'}) "
              "ภาษาไทยแบบคนพิมพ์แชทจริงๆ (ภาษาพูด เป็นกันเอง ไม่เป็นทางการ ไม่สมบูรณ์แบบเกินไป ไม่ขึ้นต้นด้วยคำทักแบบหุ่นยนต์) "
              "ถ้าต้องมีคำลงท้ายสุภาพให้ใช้ \"ครับ\" เท่านั้น · ไม่มี markdown ไม่มีคำนำ/คำอธิบายเพิ่ม ไม่เกิน 600 ตัวอักษร"
              + (f"\n\nข้อมูลที่ค้นได้:\n{data}" if data else ""))
    try:
        resp, who = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}], [],
                                   system=agent.chat_prompt())
        body = agent._collect_text(resp.get("content", [])).strip().strip('"')
        import polite
        body = polite.fix(body)
    except Exception as e:  # noqa: BLE001
        return f"ทำไม่สำเร็จ: เขียนเนื้อหาไม่ได้ ({e})"
    if not body:
        return "ทำไม่สำเร็จ: เขียนเนื้อหาไม่ได้"
    _log(f"compose {len(body)} ตัวอักษร → app={d.get('app')} to={d.get('to')}")
    send = bool(d.get("send"))
    to = share_tools.clean_name(d.get("to") or "")
    app = _app(d.get("app"))
    if to:
        app = _dm_app(app, to)
        res = share_tools.send_dm({"app": app, "to": to, "text": body, "send": send}, ctx)
    else:
        if app:
            r = phone_tools.open_app({"app": app}, ctx)
            if r.startswith("ERROR"):
                return _result(r)
            time.sleep(2.0)
        res = share_tools.type_here(body, ctx, send=send)
    head = body if len(body) <= 160 else body[:160] + "…"
    return _result(res) + f"\n\n📝 ข้อความ: {head}"


def gather(d, user_text):
    """เจตนาที่ต้องหาข้อมูลก่อนตอบ → (คำอธิบาย, ข้อมูล) ให้ AI สรุปรอบเดียว / None"""
    it = d.get("intent")
    if it == "search":
        import websearch
        q = d.get("query") or user_text
        try:
            res = websearch.search(q)
        except Exception as e:  # noqa: BLE001
            return "ค้นเว็บ", f"[ค้นเว็บไม่สำเร็จ: {e}]"
        return "ค้นเว็บ", f"[ผลค้นเว็บ '{q}' เวลา {time.strftime('%d/%m/%Y %H:%M')}]\n{str(res)[:6000]}"
    if it == "analyze_file":
        import files_tools
        q = (d.get("file") or "").strip()
        q = "" if q in ("ล่าสุด", "ไฟล์ล่าสุด", "อันล่าสุด") else q
        hits = files_tools.find(q, limit=3)
        if not hits:
            return "อ่านไฟล์", f"[หาไฟล์ที่ชื่อมี '{q}' ไม่เจอในเครื่อง — บอกผู้ใช้ให้บอกชื่อไฟล์ หรือส่งไฟล์มาในแชท]"
        path = hits[0][2]
        res = files_tools.tool_read({"path": path}, None)
        if isinstance(res, dict):
            return "อ่านไฟล์", f"[ไฟล์ {path} เป็นรูปภาพ]"
        others = "".join(f"\n- {h[2]}" for h in hits[1:])
        return "อ่านไฟล์", f"[ระบบอ่านไฟล์ให้แล้ว: {path}{' (ไฟล์อื่นที่ใกล้เคียง:' + others + ')' if others else ''}]\n{res}"
    return None
