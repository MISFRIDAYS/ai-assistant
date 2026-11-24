"""ก่อนส่งข้อความหาคน: ถามกลับเมื่อไม่ชัด + อ่านทวนเมื่อสั่งด้วยเสียง

1) ชื่อกำกวม ("ต้น" → ต้นข้าว (LINE) / ต้นกล้า (IG)) หรือคนเดียวคุยหลายแอปพอๆ กัน → ถามว่าหมายถึงใคร/แอปไหน
2) สั่งด้วยเสียง → อ่านทวน "จะส่งหาต้นใน LINE ว่า … ใช่ไหม" (ถอดเสียงผิดจะได้แก้ก่อนส่ง) — ปิดได้: VOICE_CONFIRM_SEND=0
ตอบ "ใช่" = ส่ง · "แก้เป็น …" = เปลี่ยนข้อความ · "ยกเลิก" = ไม่ส่ง · ตอบเลข/ชื่อ/แอป = เลือก
"""
import os
import re
import time

import chat_apps

TTL = 120
_P = {}

_YES = re.compile(r"^(ใช่|ใช่ๆ|ช่าย|ช้าย|ไช่|ใช|ใช้|ชัย|ใช่แล้ว|เออ|อือ|อืม|ได้เลย|ถูกแล้ว|โอเค้|โอเคร|โอเคๆ|ถูก|ถูกต้อง|โอเค|ok|okay|ได้|ตกลง|ยืนยัน|ส่งเลย|ส่ง|เอาเลย|จัดไป|เยส|yes|ครับผม|ครับ|ค่ะ)"
                  r"(แล้ว|เลย|ครับ|ค่ะ|นะ|ได้|\s)*$", re.I)
_NO = re.compile(r"^(ไม่|ไม่ใช่|ยกเลิก|ไม่เอา|ไม่ต้อง|ไม่ส่ง|หยุด|cancel|no)(แล้ว|ส่ง|ครับ|ค่ะ|นะ|\s)*$", re.I)
_EDIT = re.compile(r"^(?:แก้|เปลี่ยน)\s*(?:ข้อความ)?\s*(?:เป็น|ว่า)\s*(?P<m>.+)$")
_ORD = {"1": 0, "หนึ่ง": 0, "แรก": 0, "อันแรก": 0, "คนแรก": 0, "2": 1, "สอง": 1, "ที่สอง": 1, "3": 2, "สาม": 2,
        "4": 3, "สี่": 3, "5": 4, "ห้า": 4}
_APP_LABEL = dict(chat_apps.LABEL)


def _p():
    try:
        import voice_profile
        return voice_profile.pol()
    except Exception:  # noqa: BLE001
        return "ครับ"


def active():
    return _P.get("kind") in ("pick", "confirm") and time.time() - _P.get("t", 0) < TTL


def _is_voice(ctx):
    return (type(ctx).__name__ == "VoiceCtx" or bool(getattr(ctx, "voice", False))
            or bool(getattr(ctx, "via_voice", False)))


def _label(app):
    return _APP_LABEL.get(app, app)


def _options(to, app, explicit):
    """ตัวเลือก [(ชื่อ, แอป)] ถ้ากำกวม / [] ถ้าชัดแล้ว"""
    try:
        import contacts
    except Exception:  # noqa: BLE001
        return [], to, app
    d = contacts._load()
    k = contacts.norm(to)
    if k in d:
        cands = [d[k]]
    else:
        cands = [v for kk, v in d.items() if len(k) >= 2 and (k in kk or kk in k)]
    if explicit:
        cands = [c for c in cands if app in (c.get("apps") or {})] or cands
    if len(cands) == 1:
        e = cands[0]
        apps = sorted((e.get("apps") or {}).items(), key=lambda x: x[1], reverse=True)
        if not explicit and len(apps) >= 2 and not e.get("last") and apps[1][1] >= apps[0][1] * 0.8:
            return [(e["name"], a) for a, _ in apps[:4]], to, app          # คุยหลายแอปพอๆ กัน → ถามแอป
        if not explicit and apps:
            app = contacts.app_for(e["name"]) or app
        return [], e["name"], app
    if len(cands) > 1:
        cands.sort(key=lambda v: v.get("t", 0), reverse=True)
        opts = []
        for e in cands[:5]:
            a = app if explicit else (contacts.app_for(e["name"]) or app)
            opts.append((e["name"], a))
        return opts, to, app
    return [], to, app


def maybe_hold(app, to, msg, ctx, explicit=True):
    """ต้องถามก่อนส่งไหม → คำถาม (และจำไว้รอคำตอบ) / None = ส่งได้เลย (คืน (app,to) ที่ปรับแล้วผ่าน _P['ready'])"""
    opts, to2, app2 = _options(to, app, explicit)
    voice = _is_voice(ctx) and os.environ.get("VOICE_CONFIRM_SEND", "1") != "0"
    if opts:
        _P.clear()
        _P.update(kind="pick", opts=opts, msg=msg, voice=voice, t=time.time())
        same = len({n for n, _ in opts}) == 1
        lst = " ".join(f"{i + 1}) {_label(a) if same else f'{n} ({_label(a)})'}" for i, (n, a) in enumerate(opts))
        q = f"{opts[0][0]} คุยหลายแอป จะส่งทางไหน{_p()}" if same else f"หมายถึงใคร{_p()}"
        return f"{q} {lst} — ตอบเป็นเลขหรือชื่อก็ได้"
    if voice:
        _P.clear()
        _P.update(kind="confirm", app=app2, to=to2, msg=msg, t=time.time())
        return f"จะส่งหา {to2} ใน {_label(app2)} ว่า \"{msg}\" ใช่ไหม{_p()}"
    _P.clear()
    _P.update(kind="ready", app=app2, to=to2, t=time.time())
    return None


def resolved():
    """(app, to) ที่ปรับจากรายชื่อแล้ว หลัง maybe_hold คืน None"""
    if _P.get("kind") == "ready":
        r = (_P["app"], _P["to"])
        _P.clear()
        return r
    return None


def _new_command(t):
    """ประโยคนี้เป็นคำสั่งใหม่ทั้งประโยค ไม่ใช่คำตอบของคำถามค้าง
    ('เข้าไปที่ instagram เข้าไปที่แชท ภรรยา ส่งข้อความ …' ห้ามถูกอ่านเป็น 'เลือกภรรยา (LINE)')"""
    if len(t) <= 20:
        return False
    try:
        import quick
        if quick._DM_INTENT.search(t):
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(re.search(r"(เข้า|เปิด|ไปที่|ไปหน้า)\s*(ไป)?\s*(ที่|ใน)?\s*(แชท|แชต|แอป|แอพ|ห้อง)", t))


def _spoken_app(t):
    import contacts
    for a, rx in contacts.APP_WORDS.items():
        if re.search(rx, t, re.I):
            return a
    return None


def _pick(text, opts):
    t = text.strip().lower()
    for w, i in sorted(_ORD.items(), key=lambda x: -len(x[0])):
        if re.search(rf"(^|\s|ที่|อัน|คน|เบอร์){re.escape(w)}($|\s|ครับ|ค่ะ)", t) and i < len(opts):
            return opts[i]
    import contacts
    said = _spoken_app(t)
    for n, a in opts:
        if contacts.norm(n) and contacts.norm(n) in contacts.norm(t):
            if said and said != a and not any(nn == n and aa == said for nn, aa in opts):
                return n, said                     # "ภรรยาในไอจี" → คนนี้ แต่แอปที่เพิ่งพูด
            return n, a
    for n, a in opts:
        rx = contacts.APP_WORDS.get(a)
        if rx and re.search(rx, t, re.I):
            return n, a
    return None


def _send(app, to, msg, ctx):
    import quick
    if ctx is not None:
        try:
            ctx.send_ok = msg                  # ผู้ใช้ยืนยันข้อความนี้แล้ว → ตอนกดส่งไม่ต้องถามซ้ำ
        except Exception:  # noqa: BLE001
            pass
    return quick._do_send(app, to, msg, ctx, confirmed=True)


def handle_text(text, ctx=None):
    if not active():
        _P.clear()
        return None
    t = " ".join((text or "").split()).strip()
    if not t:
        return None
    if _NO.match(t):
        _P.clear()
        return f"ไม่ส่งแล้ว{_p()}"
    if not _EDIT.match(t) and _new_command(t):     # สั่งงานใหม่ทั้งประโยค → ทิ้งคำถามค้าง ทำคำสั่งใหม่แทน
        print(f"[dm] คำถามค้างถูกแทนด้วยคำสั่งใหม่: {t[:60]!r}", flush=True)
        _P.clear()
        return None
    if _P["kind"] == "pick":
        hit = _pick(t, _P["opts"])
        if not hit:
            if len(t) > 20:                       # พูดเรื่องอื่นไปแล้ว → ปล่อยให้ระบบปกติทำ
                _P.clear()
                return None
            return "ไม่แน่ใจว่าเลือกอันไหน ตอบเป็นเลข 1, 2 … หรือบอกว่า \"ยกเลิก\" ก็ได้"
        name, app = hit
        msg, voice = _P["msg"], _P.get("voice")
        if voice:
            _P.clear()
            _P.update(kind="confirm", app=app, to=name, msg=msg, t=time.time())
            return f"จะส่งหา {name} ใน {_label(app)} ว่า \"{msg}\" ใช่ไหม{_p()}"
        _P.clear()
        return _send(app, name, msg, ctx)
    if _P["kind"] == "confirm":
        m = _EDIT.match(t)
        if m:
            _P["msg"], _P["t"] = m.group("m").strip(), time.time()
            return f"แก้แล้ว — จะส่งหา {_P['to']} ใน {_label(_P['app'])} ว่า \"{_P['msg']}\" ใช่ไหม{_p()}"
        if _YES.match(t):
            app, to, msg = _P["app"], _P["to"], _P["msg"]
            _P.clear()
            return _send(app, to, msg, ctx)
        _P.clear()                                # พูดอย่างอื่น → ถือว่าไม่ส่ง แล้วทำคำสั่งใหม่แทน
        return None
    return None
