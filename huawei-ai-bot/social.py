"""งานในแอปโซเชียลที่สั่งเป็นประโยคเดียว

- "เข้าเฟสบุ๊คแล้วหาโพสที่น่าสนใจวันนี้" → เปิดฟีด เลื่อนอ่าน 3-4 หน้าจอ แล้วให้ AI สรุปโพสต์เด่น
- "เข้าไอจีแล้วโทรหา ภรรยา" / "วิดีโอคอลหา แม่ ทางไลน์" → เข้าห้องแชทของคนนั้นแล้วกดปุ่มโทร (ถามยืนยันก่อน)
"""
import re
import time

import config

import chat_apps  # noqa: E402

# แอปแชทใช้คำเรียกจากตารางกลาง (รู้จักสะกดเพี้ยน เช่น 'Instragram') · แอปอื่นกำหนดที่นี่
_APP = {
    "facebook": chat_apps.WORDS["facebook"],
    "instagram": chat_apps.WORDS["instagram"],
    "line": chat_apps.WORDS["line"],
    "messenger": chat_apps.WORDS["messenger"],
    "whatsapp": chat_apps.WORDS["whatsapp"],
    "tiktok": r"ติ๊กต็อก|ติ๊กตอก|ติกต็อก|(?<![a-z])tiktok(?![a-z])",
    "x": r"ทวิตเตอร์|(?<![a-z])(?:twitter|x)(?![a-z])",
    "youtube": r"ยูทูป|ยูทูบ|(?<![a-z])youtube(?![a-z])",
    "threads": r"เธรดส์|(?<![a-z])threads(?![a-z])",
}
_APPS_RX = "|".join(f"(?P<{k}>{v})" for k, v in _APP.items())
_POL = r"(?:\s*(?:ให้หน่อย|หน่อย|ให้ที|ที|ครับ|ค่ะ|คะ|นะ|ด้วย|เลย))*"

_FEED = re.compile(r"^(?:ช่วย)?\s*(?:เข้า|เปิด|ไป|ดู|ไล่)?\s*(?:ไป)?\s*(?:ที่|ใน)?\s*(?:แอป|แอพ)?\s*(?:" + _APPS_RX + r")\s*(?:แล้ว|และ|จากนั้น)?\s*(?:ก็)?\s*"
                   r"(?:หา|ดู|สรุป|อ่าน|ไล่ดู|เช็ค|เช็ก|ว่า)\s*(?P<what>.*?(?:โพส|โพสต์|ฟีด|feed|คลิป|ข่าว|อัปเดต|อัพเดท|"
                   r"น่าสนใจ|มีอะไร|เทรนด์|ทวีต|เรื่อง).*?)" + _POL + r"$", re.I)
_CALL = re.compile(r"^(?:ช่วย)?\s*(?:(?:เข้า|เปิด|ไป)\s*(?:แอป)?\s*(?:" + _APPS_RX.replace("?P<", "?P<a_") + r")\s*(?:แล้ว|และ)?\s*)?"
                   r"(?:กด)?\s*(?P<kind>โทร(?:หา|ไปหา|ไป)?|วิดีโอคอล(?:หา)?|วีดีโอคอล(?:หา)?|คอล(?:หา)?|video\s*call|call)\s*"
                   r"(?P<to>.+?)\s*(?:(?:ใน|ทาง|ผ่าน|ด้วย)\s*(?:แอป)?\s*(?:" + _APPS_RX.replace("?P<", "?P<b_") + r"))?" + _POL + r"$",
                   re.I)


def _which(m, prefix=""):
    for k in _APP:
        if m.groupdict().get(prefix + k):
            return k
    return None


# ================================================================ อ่านฟีดแล้วสรุป

_JUNK = re.compile(r"^(ถูกใจ|like|แสดงความคิดเห็น|comment|แชร์|share|ส่ง|send|ติดตาม|follow|ดูเพิ่มเติม|see more|"
                   r"หน้าหลัก|home|ค้นหา|search|วิดีโอ|video|reels|marketplace|แจ้งเตือน|notifications|เมนู|menu|"
                   r"โปรไฟล์|profile|สตอรี่|stories|สร้างสตอรี่|คุณกำลังคิดอะไรอยู่.*|what's on your mind.*|\d+\s*(ชม\.|น\.|h|m|d)?)$",
                   re.I)


def _read_lines():
    import share_tools
    return _read_lines_from(share_tools._items())


def _read_lines_from(items):
    out = []
    for e in items:
        for t in (e.get("text") or "", e.get("desc") or ""):
            t = " ".join(t.split())
            if len(t) >= 6 and not _JUNK.match(t):
                out.append(t[:400])
    return out


_SUMMARY_SYS = ("คุณคือผู้ช่วยที่สรุปฟีดโซเชียลเป็นภาษาไทย สั้น กระชับ อ่านออกเสียงได้ลื่น "
                "ใช้ข้อมูลที่ให้มาเท่านั้น ห้ามแต่งเพิ่ม")


def _summarize(prompt):
    """สรุปฟีด: Groq ก่อน (~1-2 วิ) → ตัวหลัก (system prompt สั้น ไม่ต้องส่งคำสั่งระบบทั้งชุด)"""
    import agent
    msgs = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    if config.GROQ_API_KEY and config.LLM_PROVIDER != "groq" and time.time() >= agent._fast_chat_off[0]:
        try:
            import groq_client
            resp = groq_client.create_message(_SUMMARY_SYS, msgs, [], 700)
            out = agent._collect_text(resp.get("content", [])).strip()
            if out:
                return out, "Groq"
        except Exception as e:  # noqa: BLE001
            print(time.strftime("[%H:%M:%S]"), "สรุปฟีดด้วย Groq ไม่ได้ → ใช้ตัวหลัก:", str(e)[:80], flush=True)
    resp, who = agent.call_llm(msgs, [], system=_SUMMARY_SYS)
    return agent._collect_text(resp.get("content", [])).strip(), who


def _fresh_lines(seen, lines):
    new = 0
    for t in _read_lines():
        k = t[:60]
        if k not in seen:
            seen.add(k)
            lines.append(t)
            new += 1
    return new


def _ack(ctx, text):
    """สั่งด้วยเสียง + งานใช้เวลาหลายวิ → พูดตอบรับก่อนทันที (ไม่ให้เงียบจนผู้ใช้คิดว่าไม่ได้ยิน)"""
    if ctx is None or config.MOCK_PHONE:
        return
    if not (type(ctx).__name__ == "VoiceCtx" or getattr(ctx, "voice", False) or getattr(ctx, "via_voice", False)):
        return
    try:
        import voice
        import voice_profile
        voice.say(f"{voice_profile.ack_word()} {text}", wait=False)
    except Exception:  # noqa: BLE001
        pass


def feed_summary(app, what="", ctx=None, pages=3):
    """เปิดฟีด → อ่าน `pages` หน้าจอ → สรุป (รอตามจริงแทนการหน่วงตายตัว: ฟีดขึ้นเมื่อไหร่อ่านทันที)"""
    import phone_tools
    import screen_tools
    import share_tools
    t0 = time.time()
    _ack(ctx, f"กำลังดูฟีด {chat_apps.LABEL.get(app, app)} ให้")
    res = phone_tools.open_app({"app": app, "fresh": True}, ctx)
    if res.startswith("ERROR"):
        return res
    seen, lines = set(), []
    # รอจนฟีดมีข้อความพอ (สูงสุด 8 วิ) แทน sleep 3 วิทุกครั้ง
    ok = share_tools._wait_items(lambda it: sum(1 for t in _read_lines_from(it) if len(t) >= 20) >= 2,
                                 timeout=8.0, every=0.6)
    if ok is None:
        try:
            _read_lines()
        except RuntimeError as e:
            return f"ERROR: อ่านหน้าจอไม่ได้ ({e})"
    for i in range(pages):
        try:
            _fresh_lines(seen, lines)
        except RuntimeError as e:
            if i == 0:
                return f"ERROR: อ่านหน้าจอไม่ได้ ({e})"
        if i < pages - 1:
            screen_tools.swipe({"direction": "up"}, ctx)
            time.sleep(1.0)
    t_read = time.time() - t0
    text = "\n".join(lines)[:6000]
    if len(text) < 40:
        return f"เปิด {app} แล้ว แต่อ่านโพสต์บนจอไม่ออก (ฟีดอาจยังโหลดไม่เสร็จ) ลองสั่งอีกครั้งนะ"
    if config.MOCK_PHONE:
        return text[:500]
    prompt = (f"นี่คือข้อความที่อ่านได้จากหน้าฟีด {app} ของผู้ใช้ (เลื่อนดู {pages} หน้าจอ) "
              f"ผู้ใช้อยากรู้: \"{what or 'โพสต์ที่น่าสนใจวันนี้'}\"\n"
              "สรุปโพสต์ที่น่าสนใจ 3-5 อัน เป็นข้อๆ: ใครโพสต์ + เนื้อหาโดยย่อ · ข้ามโฆษณา/ได้รับการสนับสนุน/เมนูแอป · "
              "ถ้าข้อมูลน้อยให้บอกตามจริง ห้ามแต่งเพิ่ม\n\n---\n" + text)
    try:
        out, who = _summarize(prompt)
    except Exception as e:  # noqa: BLE001
        return f"อ่านฟีด {app} ได้แล้ว แต่ AI สรุปไม่ได้ ({str(e)[:100]})\n\n" + text[:800]
    print(time.strftime("[%H:%M:%S]"), f"📰 ฟีด {app}: อ่าน {t_read:.1f}s · สรุป {who} "
          f"{time.time() - t0 - t_read:.1f}s · รวม {time.time() - t0:.1f}s", flush=True)
    return f"📰 โพสต์น่าสนใจใน {app} ตอนนี้:\n" + out


# ================================================================ โทรผ่านแอปแชท

_VOICE = re.compile(r"(voice|audio)\s*call|โทรด้วยเสียง|โทรแบบเสียง|การโทรด้วยเสียง|call_button|voice_call|audio_call", re.I)
_VIDEO = re.compile(r"video\s*call|วิดีโอคอล|วิดีโอ|video_call|โทรแบบวิดีโอ", re.I)
_ANYCALL = re.compile(r"^(โทร|call|โทรออก)$|โทร|call", re.I)


def _call_btn(items, video):
    """ปุ่มโทรบนหัวห้องแชท — รับทั้งปุ่มที่กดได้ และไอคอนที่มีป้ายแต่ตัวมันเองกดไม่ได้ (IG: แตะพิกัดไอคอนก็ได้ผล)"""
    lab = lambda e: f"{e.get('desc') or ''} {e.get('text') or ''} {e.get('id') or ''}".strip()  # noqa: E731
    h = max((e["box"][3] for e in items), default=2000)
    area = lambda e: (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1])  # noqa: E731
    pool = [e for e in items if not e.get("edit") and len(lab(e)) <= 45      # ป้ายยาว = กล่องรวมทั้งแถบ ไม่ใช่ปุ่ม
            and h * 0.03 < e["y"] < h * 0.3                                      # หัวห้องแชท (ไม่เอาแถบสถานะ)
            and not (_VOICE.search(lab(e)) and _VIDEO.search(lab(e)))]
    rank = lambda e: (not e.get("click"), area(e))  # noqa: E731
    want = _VIDEO if video else _VOICE
    hit = [e for e in pool if want.search(lab(e)) and (video or not _VIDEO.search(lab(e)))]
    if hit:
        return min(hit, key=rank), True
    gen = [e for e in pool if _ANYCALL.search(lab(e)) and not _VIDEO.search(lab(e)) and e["y"] < h * 0.2]
    return (min(gen, key=rank), False) if gen else (None, False)


def open_chat(app, to, ctx):
    """เข้าห้องแชทของคนนี้ (ไม่พิมพ์อะไร) → (ok, steps)"""
    import phone_tools
    import share_tools as st
    key = phone_tools.ALIASES.get(app.lower(), app).lower()
    steps = []
    if key in st.DM_LINKS and st._is_username(to):
        ok, _out = phone_tools._open_link(st.DM_LINKS[key].format(u=to.lstrip("@")))
        if ok and st._wait_items(lambda it: st._composer(it) is not None, timeout=9):
            return True, [f"เปิดห้องแชท @{to}"]
    if st._current_chat(key, to) == "same":
        return True, ["อยู่ในห้องแชทอยู่แล้ว"]
    res = phone_tools.open_app({"app": key, "page": "chat"}, ctx)
    steps.append(res[:60])
    if res.startswith("ERROR"):
        return False, steps
    time.sleep(1.0)
    try:
        hit = st._pick_recipient(to, key)
    except RuntimeError as e:
        return False, steps + [str(e)]
    if not hit:
        return False, steps + [f"หา '{to}' ไม่เจอ (บนจอมี: {st._visible_names()})"]
    steps.append(f"แตะ {hit.get('text') or hit.get('desc')}")
    ok = st._wait_items(lambda it: st._composer(it) is not None, timeout=6) is not None
    return ok, steps


def call(app, to, video=False, ctx=None):
    import share_tools as st
    to = st.clean_name(to)
    if not to:
        return "จะโทรหาใครดี?"
    kind = "วิดีโอคอล" if video else "โทร (เสียง)"
    if ctx is not None and hasattr(ctx, "confirm") and not ctx.confirm(f"📞 {kind} หา {to} ทาง {app} ใช่ไหม?"):
        return "ยกเลิกการโทรแล้ว"
    ok, steps = open_chat(app, to, ctx)
    if not ok:
        return f"ERROR: เข้าห้องแชทของ {to} ใน {app} ไม่ได้ — ยังไม่ได้โทร ({' → '.join(steps)})"
    items = st._items()
    btn, exact = _call_btn(items, video)
    if not btn:
        st._dump_log("หาปุ่มโทรไม่เจอ", items)
        return f"เข้าห้องแชทของ {to} แล้ว แต่หาปุ่ม{kind}ไม่เจอ — แตะไอคอนโทรมุมขวาบนได้เลย"
    import screen_tools
    screen_tools.adb_shell(["input", "tap", str(btn["x"]), str(btn["y"])])
    time.sleep(1.2)
    if not exact:                                   # ปุ่มรวม (เช่น LINE) → เมนูเลือกเสียง/วิดีโอ
        try:
            sub, ex2 = _call_btn(st._items(), video)
            if sub and ex2:
                screen_tools.adb_shell(["input", "tap", str(sub["x"]), str(sub["y"])])
        except RuntimeError:
            pass
    try:
        import contacts
        contacts.learn(to, app, "call")
    except Exception:  # noqa: BLE001
        pass
    return f"📞 กำลัง{kind}หา {to} ทาง {app} ✅"


# ================================================================ คำสั่ง

_GOTO = re.compile(r"^(?:ช่วย)?\s*(?:(?:เข้า|เปิด|ไป)\s*(?:ไป)?\s*(?:ที่)?\s*(?:แอป)?\s*(?:" + _APPS_RX.replace("?P<", "?P<p_") + r")\s*(?:แล้ว|และ)?\s*)?"
                   r"(?:เข้า|เปิด|กด)?\s*(?:ไป)?\s*(?:ที่|หา)?\s*(?:ห้อง)?\s*(?:แชท|แชต|แชร์|chat|ข้อความ|ไดเร็ค|dm)\s*(?:ของ|กับ|หา)?\s*"
                   r"(?P<to>.+?)(?:\s*(?:ใน|ทาง)\s*(?:แอป)?\s*(?:" + _APPS_RX.replace("?P<", "?P<g_") + r"))?"
                   r"(?:\s*(?:ให้หน่อย|หน่อย|ที|ครับ|ค่ะ|นะ))*$", re.I)


def goto_chat(to, app=None, ctx=None):
    """เข้าห้องแชทของคนนี้ (ไม่ส่งอะไร) — "คนแรก" = ห้องแชทบนสุดในหน้าที่เปิดอยู่"""
    import phone_tools
    import share_tools as st
    import contacts
    if re.fullmatch(r"(?:คน|อัน|ห้อง)?\s*(?:แรก|บนสุด|ล่าสุด)", to.strip()):
        try:
            items = st._items()
            h = max((e["box"][3] for e in items), default=2000)
            rows = [(n, e) for n, e in st._chat_rows(items) if e["y"] > h * 0.18 and e.get("click", True)]
        except Exception:  # noqa: BLE001
            rows = []
        if rows:
            import screen_tools
            name, r = rows[0]
            screen_tools.adb_shell(["input", "tap", str(r["x"]), str(r["y"])])
            return f"💬 เข้าแชท {name} แล้ว"
        return "ตอนนี้ไม่ได้อยู่หน้ารวมแชท — บอกชื่อคนได้เลย เช่น \"ไปที่แชท แม่\""
    to = contacts.known_name(to) or st.clean_name(to)
    fg = phone_tools._fg() or ""
    app = app or contacts.app_for(to) or contacts.APP_KEYS.get(fg)
    if not app:
        return f"แชท {to} อยู่แอปไหนครับ? (ไลน์ / ไอจี / เมสเซนเจอร์)"
    ok, steps = open_chat(app, to, ctx)
    if ok:
        contacts.learn(to, app, "sent")
        return f"💬 เข้าแชท {to} ใน {app} แล้ว"
    return f"เข้าแชท {to} ใน {app} ไม่ได้ ({' → '.join(steps)[-160:]})"


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    if not t or len(t) > 120:
        return None
    m = _GOTO.match(t)
    to = re.sub(r"^(?:ให้หน่อย|หน่อย|ให้ที|ที|ครับ|ค่ะ|คะ|นะ|ด้วย|เลย|ทั้งหมด|รวม)+$", "", (m.group("to") if m else "").strip())
    ask_msg = False
    if m and to:
        # "เข้าแชท X พิมพ์/บอก/เขียน Y" = ส่งข้อความ (ให้ quick.dm ทำ พร้อมอ่านทวน) ไม่ใช่แค่เปิดห้องแชท
        mv = re.search(r"\s*(?:แล้ว(?:ก็)?)?\s*(?:พิมพ์|เขียน|บอก|ส่ง|ตอบ)\s*(?:ข้อความ)?\s*(?:ว่า)?\s*(?P<rest>.*)$", to)
        if mv:
            if mv.group("rest").strip():
                return None
            to, ask_msg = to[:mv.start()].strip(), True
    if m and to and not re.search(r"\sว่า\s|ส่ง", t) and re.match(r"(?:ช่วย)?\s*(?:เข้า|เปิด|ไป|กด)", t):
        r = goto_chat(to, _which(m, "p_") or _which(m, "g_"), ctx)
        if ask_msg and r.startswith("💬"):
            r += " — จะพิมพ์ว่าอะไรดีครับ? (พูดว่า \"พิมพ์ว่า …\")"
        return r
    m = _CALL.match(t)
    if m:
        app = _which(m, "a_") or _which(m, "b_")
        to = re.sub(r"^(?:หา|ไปหา)\s*", "", m.group("to")).strip()
        if not app:
            import contacts
            app = contacts.app_for(to)              # จำได้ว่าคนนี้คุยในแอปไหน (แท็บเล็ตไม่มีซิม โทรปกติไม่ได้)
        video = bool(re.search(r"วิดีโอ|วีดีโอ|video", m.group("kind"), re.I))
        if app or video:
            return call(app or "line", to, video, ctx)
        return None                                 # ไม่รู้แอป → ให้ระบบอื่น/AI ถาม
    m = _FEED.match(t)
    if m:
        return feed_summary(_which(m), m.group("what"), ctx)
    return None
