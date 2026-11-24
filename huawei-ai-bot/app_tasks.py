"""รู้จักปุ่มทุกปุ่ม + งานสำเร็จรูปในแอปที่ใช้บ่อย

1) เรียนรู้ไอคอนไม่มีชื่อ (เช่นปุ่ม + สีแดงของ WPS / ปุ่มเขียนโน้ต) — ถ่ายจอ วาดกรอบเลข ให้ AI ที่ดูรูปได้บอกว่าแต่ละปุ่มคืออะไร
   เก็บไว้ต่อแอป → read_screen/tap_text เห็นชื่อปุ่มที่เรียนรู้ไว้ (เช่น ≈"สร้างไฟล์ใหม่")
2) งานสำเร็จรูป (กดตามขั้น + ถ้าหาไม่เจอใช้ตำแหน่งปุ่มลอย/มองภาพ):
   "สร้างเอกสารใหม่ใน wps" · "สร้างเอกสาร wps เรื่อง ประชุมทีม" · "จดโน้ตว่า ซื้อนม" · "สร้างโน้ตใหม่"
"""
import json
import os
import re
import time

import config

_DANGER = re.compile(r"ลบ|delete|remove|จ่าย|ชำระ|pay|ซื้อ|buy|ส่ง|send|โทร|call|ออกจากระบบ|log ?out|sign ?out|"
                     r"รีเซ็ต|reset|ถอน|uninstall|โอน|transfer|สั่งซื้อ|order", re.I)
_CREATE = re.compile(r"^(\+|＋|สร้าง|ใหม่|เพิ่ม|New|Create|Add|เขียน|Compose)$|fab|floating|new_?(file|note|doc)|add_?(note|file|btn)|"
                     r"create|compose|btn_?add|plus", re.I)


def _b():
    import android_shim
    return android_shim.bridge()


def _items():
    import share_tools
    return share_tools._items()


def _lab(e):
    return (e.get("text") or e.get("desc") or "").strip()


def _size(items):
    w = max((e["box"][2] for e in items), default=1080)
    h = max((e["box"][3] for e in items), default=2000)
    return w, h


# ================================================================ เรียนรู้ไอคอนไม่มีชื่อ

def _store():
    import skills
    return skills


def icons_for(pkg):
    return (_store().get_pref(f"icons:{pkg}") or {}).get("icons", [])


def unlabeled(items):
    w, h = _size(items)
    out = []
    for e in items:
        bw, bh = e["box"][2] - e["box"][0], e["box"][3] - e["box"][1]
        if e.get("click") and not e.get("edit") and not _lab(e) and 20 < bw < w * 0.35 and 20 < bh < h * 0.2:
            out.append(e)
    return out[:20]


def learn_icons(pkg, items=None):
    """ถ่ายจอ → ให้ AI บอกชื่อไอคอนที่ไม่มีชื่อ → จำไว้ (คืนจำนวนที่เรียนรู้ได้)"""
    if not config.ANDROID_APP:
        return 0
    items = items if items is not None else _items()
    targets = unlabeled(items)
    if not targets:
        return 0
    w, h = _size(items)
    shot = os.path.join(config.DATA_DIR, "icons_raw.png")
    ann = os.path.join(config.DATA_DIR, "icons_ann.jpg")
    b = _b()
    if not b.screenshot(shot) or not b.annotate(shot, json.dumps([list(e["box"]) for e in targets]), ann):
        return 0
    import vision
    try:
        ans = vision.ask_images(
            "ภาพหน้าจอแอปที่มีกรอบแดงพร้อมเลข แต่ละกรอบคือปุ่มที่ไม่มีชื่อ บอกว่าปุ่มแต่ละเลขน่าจะทำอะไร "
            "เป็นภาษาไทยสั้นๆ 2-5 คำ (เช่น \"สร้างไฟล์ใหม่\", \"ค้นหา\", \"เมนู\", \"ย้อนกลับ\", \"แชร์\") "
            'ตอบ JSON เท่านั้น: {"1": "...", "2": "..."} ถ้าไม่แน่ใจใส่ "?"', [ann], quality=True)
    except Exception as e:  # noqa: BLE001
        print(f"[icons] {e}", flush=True)
        return 0
    if not ans:
        return 0
    m = re.search(r"\{.*\}", ans, re.S)
    try:
        labels = json.loads(m.group(0)) if m else {}
    except ValueError:
        return 0
    known = {(round(i["x"], 2), round(i["y"], 2)): i for i in icons_for(pkg)}
    n = 0
    for i, e in enumerate(targets):
        lab = str(labels.get(str(i + 1), "")).strip()
        if not lab or lab == "?" or len(lab) > 30:
            continue
        rx, ry = round(e["x"] / w, 3), round(e["y"] / h, 3)
        known[(round(rx, 2), round(ry, 2))] = {"x": rx, "y": ry, "label": lab, "id": e.get("id", "")}
        n += 1
    _store().set_pref(f"icons:{pkg}", {"icons": list(known.values())[-60:], "at": time.strftime("%Y-%m-%d")})
    return n


def label_of(pkg, e, w, h):
    """ชื่อที่เรียนรู้ไว้ของไอคอนนี้ (เทียบตำแหน่งบนจอ หรือ id)"""
    for i in icons_for(pkg):
        if (i.get("id") and i["id"] == e.get("id")) or \
                (abs(i["x"] - e["x"] / w) < 0.035 and abs(i["y"] - e["y"] / h) < 0.03):
            return i["label"]
    return ""


def find_learned(pkg, query, items):
    """tap_text หาไม่เจอ → ลองหาจากชื่อไอคอนที่เรียนรู้ไว้"""
    w, h = _size(items)
    q = query.strip().lower()
    for e in unlabeled(items):
        lab = label_of(pkg, e, w, h).lower()
        if lab and (q in lab or lab in q):
            return e
    return None


# ================================================================ งานสำเร็จรูป

def _fab(items):
    """ปุ่มลอยมุมขวาล่าง (มักเป็น "สร้างใหม่") ที่ไม่มีชื่อ"""
    w, h = _size(items)
    c = [e for e in unlabeled(items) if e["x"] > w * 0.6 and h * 0.6 < e["y"] < h * 0.95
         and abs((e["box"][2] - e["box"][0]) - (e["box"][3] - e["box"][1])) < 60]
    return max(c, key=lambda e: e["y"]) if c else None


def _find(items, rx):
    r = re.compile(rx, re.I)
    hits = [e for e in items if not e.get("edit") and (r.search(_lab(e)) or r.search(e.get("id") or ""))
            and not _DANGER.search(_lab(e))]
    hits.sort(key=lambda e: (not e.get("click"), len(_lab(e))))
    return hits[0] if hits else None


def _tap(e):
    import screen_tools
    screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])


_POPUP = r"^(ข้าม|Skip|ภายหลัง|Later|ไว้ทีหลัง|ไม่ใช่ตอนนี้|Not now|ปิด|Close|ยอมรับ|Agree|ตกลง|OK|Got it|เข้าใจแล้ว|×|✕)$"


def _dismiss(tries=2):
    for _ in range(tries):
        try:
            e = _find(_items(), _POPUP)
        except RuntimeError:
            return
        if not e:
            return
        _tap(e)
        time.sleep(0.8)


def step(rx=None, visual=None, fab=False, optional=False, wait=1.4, pkg=""):
    """แตะปุ่มหนึ่งขั้น: ชื่อ/ id ตรง rx → ไอคอนที่เรียนรู้ไว้ → ปุ่มลอย → มองภาพ"""
    items = _items()
    e = _find(items, rx) if rx else None
    if not e and visual and pkg:
        e = find_learned(pkg, visual, items)
    if not e and fab:
        e = _fab(items)
    if not e and visual:
        import screen_tools
        e = screen_tools.vision_find(visual)
    if not e:
        if optional:
            return True, ""
        return False, f"หา \"{visual or rx}\" ไม่เจอ"
    _tap(e)
    time.sleep(wait)
    return True, _lab(e) or visual or "ปุ่ม"


def step_home(rx, visual, pkg, fab=True):
    """หาปุ่มแรกของงาน — ไม่เจอ (ค้างหน้าอื่น/เปิดเอกสารค้างไว้) → ย้อนกลับทีละหน้าแล้วลองใหม่ (สูงสุด 3 ครั้ง)"""
    import phone_tools
    import screen_tools
    ok, what = step(rx, visual, fab=fab, pkg=pkg)
    tries = 0
    while not ok and tries < 3:
        tries += 1
        screen_tools.adb_shell(["input", "keyevent", "4"])
        time.sleep(1.0)
        if pkg and phone_tools._fg() not in (pkg, None):          # ย้อนจนหลุดแอป → เปิดใหม่ที่หน้าแรก
            phone_tools.open_app({"app": pkg, "fresh": True}, None)
            time.sleep(2.0)
        _dismiss(1)
        ok, what = step(rx, visual, fab=fab, pkg=pkg)
    return ok, what


def _open(names, ctx):
    import app_index
    import phone_tools
    for n in names:
        pkg, _lab2 = app_index.find(n)
        if pkg and "." in pkg:
            r = phone_tools.open_app({"app": pkg, "fresh": True}, ctx)
            if not r.startswith("ERROR"):
                time.sleep(2.5)
                return pkg
    return None


def _type(text, ctx):
    import screen_tools
    return screen_tools.type_text({"text": text}, ctx)


_DOC = re.compile(r"เอกสาร|document|\bdocs?\b|word|writer|เวิร์ด|\.docx", re.I)
_NOT_DOC = re.compile(r"pdf|สเปรดชีต|spreadsheet|sheet|ชีต|slide|สไลด์|นำเสนอ|presentation|ล่าสุด|recent|เปิด|open|"
                      r"สแกน|scan|แชร์|share|cloud|คลาวด์|template|เทมเพลต|ทั้งหมด|all|ค้นหา|search", re.I)


def _seen_labels(n=14):
    try:
        labs = []
        for e in _items():
            t = _lab(e)
            if t and t not in labs and len(t) < 30:
                labs.append(t)
        return ", ".join(labs[:n]) or "(อ่านจอไม่ได้)"
    except Exception:  # noqa: BLE001
        return "(อ่านจอไม่ได้)"


def _pick_doc(pkg):
    """เมนูหลังกด + ของ WPS: หา "เอกสาร/Document/Word" (ชื่อยาว/สั้นก็ได้ ไม่เอา PDF/ชีต/สไลด์)"""
    for attempt in range(2):
        items = _items()
        c = [e for e in items if not e.get("edit") and _DOC.search(_lab(e) or e.get("id") or "")
             and not _NOT_DOC.search(_lab(e)) and len(_lab(e)) <= 30]
        if c:
            e = min(c, key=lambda e: (len(_lab(e)), not e.get("click")))
            _tap(e)
            time.sleep(1.6)
            return True, _lab(e) or "เอกสาร"
        time.sleep(1.0)                                   # เมนูอาจกำลังเลื่อนขึ้นมา
    import screen_tools
    e = screen_tools.vision_find("ตัวเลือกสร้างเอกสาร Word (ไอคอนตัว W สีน้ำเงิน หรือคำว่า เอกสาร/Document)")
    if e:
        _tap(e)
        time.sleep(1.6)
        return True, "เอกสาร (มองภาพ)"
    return False, ""


WPS_PKGS = ("cn.wps.moffice_eng", "com.kingsoft.moffice_pro", "cn.wps.moffice_i18n", "cn.wps.moffice")
_EDITOR = re.compile(r"^(เลิกทำ|Undo|ทำซ้ำ|Redo|แทรก|Insert|ย่อหน้า|Paragraph|ตัวหนา|Bold|แบบอักษร|Font)$", re.I)
_BLANK = re.compile(r"^(\+|＋)$|ว่าง|Blank|เปล่า|New blank|เอกสารใหม่|สร้างใหม่", re.I)
_TEMPLATE_PAGE = re.compile(r"แม่แบบ|Template|เทมเพลต|ว่าง|Blank|เปล่า|แนะนำ|Recommended", re.I)
_TYPES_MENU = re.compile(r"สเปรดชีต|Spreadsheet|Sheet|งานนำเสนอ|Presentation|Slide|PDF", re.I)


def _wps_state(items):
    labs = [_lab(e) for e in items]
    ids = " ".join(e.get("id") or "" for e in items).lower()
    if any(_EDITOR.match(t) for t in labs) or re.search(r"writer_|doc_?view|editor|edit_layout|wps_doc", ids):
        return "editor"
    if any(_TEMPLATE_PAGE.search(t) for t in labs) and not any(_TYPES_MENU.search(t) for t in labs):
        return "template"
    if any(_DOC.search(t) for t in labs) and any(_TYPES_MENU.search(t) for t in labs):
        return "types"
    return "home"


def _tap_blank(pkg):
    items = _items()
    c = [e for e in items if not e.get("edit") and _BLANK.search(_lab(e) or "")]
    if c:
        e = min(c, key=lambda e: (not _lab(e).strip() in ("+", "＋"), len(_lab(e))))
        _tap(e)
        time.sleep(2.0)
        return True
    import screen_tools
    e = screen_tools.vision_find("แม่แบบเอกสารเปล่า (กรอบสีขาวที่มีเครื่องหมาย + ตรงกลาง หรือคำว่า ว่าง/Blank)")
    if e:
        _tap(e)
        time.sleep(2.0)
        return True
    return False


def wps_blank(ctx=None):
    """สร้างเอกสารเปล่าใน WPS โดยดูว่าตอนนี้อยู่หน้าไหนแล้วทำต่อจากตรงนั้น (ไม่ย้อนไปเริ่มใหม่ถ้าไม่จำเป็น)"""
    import phone_tools
    import screen_tools
    fg = phone_tools._fg() or ""
    pkg = fg if fg in WPS_PKGS or fg.startswith("cn.wps") else _open(["WPS Office", "wps", *WPS_PKGS], ctx)
    if not pkg:
        return "ERROR: ไม่พบแอป WPS Office ในเครื่อง"
    trail = []
    for _ in range(7):
        _dismiss(1)
        st = _wps_state(_items())
        if st == "editor":
            return "📄 สร้างเอกสาร Word ใหม่ใน WPS แล้ว พร้อมพิมพ์ (" + " → ".join(trail or ["อยู่ในเอกสารแล้ว"]) + ")"
        if st == "template":
            if _tap_blank(pkg):
                trail.append("เลือกเอกสารเปล่า")
                continue
        elif st == "types":
            ok, what = _pick_doc(pkg)
            if ok:
                trail.append(what)
                continue
        else:
            ok, what = step(_CREATE.pattern, "ปุ่มสร้างไฟล์ใหม่ (เครื่องหมาย + สีแดงมุมขวาล่าง)", fab=True, pkg=pkg)
            if ok:
                trail.append("กด +")
                continue
        screen_tools.adb_shell(["input", "keyevent", "4"])           # หน้าที่ไม่รู้จัก → ย้อนกลับแล้วดูใหม่
        trail.append("ย้อนกลับ")
        time.sleep(1.0)
        if phone_tools._fg() not in (pkg, None):
            phone_tools.open_app({"app": pkg, "fresh": True}, ctx)
            time.sleep(2.0)
    return (f"ทำไปถึง: {' → '.join(trail) or '-'} แต่ยังไม่ถึงหน้าเอกสาร\nบนจอตอนนี้มี: {_seen_labels()}\n"
            "สอนให้ดูครั้งเดียวได้: \"จำขั้นตอน สร้างเอกสาร wps\"")


def wps_new_doc(body="", ctx=None, title=""):
    """มีเนื้อหา → สร้างไฟล์ .docx เองแล้วเปิดใน WPS (แม่นกว่าพิมพ์ทีละตัว) · ไม่มีเนื้อหา → เอกสารเปล่าผ่านหน้าจอ"""
    if not body:
        return wps_blank(ctx)
    import docx_lite
    import media
    lines = body.strip().splitlines()
    title = title or (lines[0][:60] if lines and len(lines[0]) <= 60 and len(lines) > 1 else "")
    text = "\n".join(lines[1:]) if title and lines and lines[0][:60] == title else body
    safe = re.sub(r"[^\wก-๙]+", "_", title or "เอกสาร")[:30].strip("_") or "เอกสาร"
    path = os.path.join(media._out_dir("doc"), f"{safe}_{time.strftime('%H%M%S')}.docx")
    docx_lite.write(path, title, text)
    media._publish(path)
    opened = False
    if config.ANDROID_APP:
        try:
            opened = bool(_b().openFile(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        except Exception:  # noqa: BLE001
            pass
    return (f"📄 สร้างไฟล์ Word แล้ว{' และเปิดใน WPS ให้แล้ว' if opened else ''}\n"
            f"ไฟล์: Documents/ผู้ช่วยAI/{os.path.basename(path)}")


NOTE_PKGS = ("com.example.android.notepad", "com.huawei.notepad", "com.google.android.keep",
             "com.samsung.android.app.notes", "com.miui.notes", "com.coloros.note", "com.oplus.note",
             "com.android.notes")


def _note_by_share(body, ctx):
    """ใส่เนื้อหาโน้ตด้วยการ "แชร์ข้อความ" ไปที่แอปโน้ต (แอปโน้ตของ Huawei พิมพ์ผ่านระบบไม่ได้ แต่รับการแชร์ได้)"""
    import json as _json
    import app_index
    import phone_tools
    installed = {a["pkg"] for a in (app_index.load() or [])}
    pkg = next((p for p in NOTE_PKGS if p in installed), None)
    if not pkg:
        found, _ = app_index.find("บันทึก")
        pkg = found if found and "note" in found.lower() else None
    if not pkg:
        return None
    res = str(_b().startIntent(_json.dumps({"action": "android.intent.action.SEND", "type": "text/plain",
                                            "package": pkg, "extras": {"android.intent.extra.TEXT": body}})))
    if "rror" in res or "No activity" in res:
        return None
    time.sleep(2.2)
    if phone_tools._fg() != pkg:
        return None
    trail = ["แชร์ข้อความเข้าแอปโน้ต"]
    ok2, w2 = step(r"^(✓|✔|เสร็จ|เสร็จสิ้น|Done|บันทึก|Save|ตกลง)$|done|save|confirm|ok_btn", None, optional=True, wait=1.0)
    if w2:
        trail.append(w2)
    else:
        import screen_tools
        screen_tools.adb_shell(["input", "keyevent", "4"])       # ย้อนกลับ = บันทึกอัตโนมัติ
        trail.append("ย้อนกลับเพื่อบันทึก")
    return "📝 จดโน้ตแล้ว (" + " → ".join(trail) + ")"


def _note_vision(body, ctx):
    """ทางสุดท้าย: มองภาพหน้าจอจริงแล้วสร้างโน้ตเอง (โหมดมองจอ)"""
    try:
        import screen_task
        if not screen_task.available():
            return None
        goal = ("เปิดแอปบันทึก/โน้ตของเครื่อง สร้างโน้ตใหม่" +
                (f" พิมพ์ข้อความว่า \"{body}\" ลงในเนื้อหาโน้ต" if body else "") + " แล้วบันทึก")
        r = screen_task.run(goal, ctx)
        return None if r.startswith("ERROR") else "📝 " + r.lstrip("✅ ")
    except Exception as e:  # noqa: BLE001
        print(f"[note] vision: {e}", flush=True)
        return None


def note_new(body="", ctx=None):
    r = _note_new(body, ctx)
    if config.ANDROID_APP and (r.startswith("ERROR") or "ไม่ให้พิมพ์" in r or "สอนให้ดูได้" in r):
        v = _note_vision(body, ctx)
        if v:
            return v
    return r


def _note_new(body="", ctx=None):
    if body and config.ANDROID_APP:
        r = _note_by_share(body, ctx)
        if r:
            return r
    pkg = _open(["บันทึก", "Notepad", "Notes", "โน้ต", "com.example.android.notepad", "com.huawei.notepad",
                 "Google Keep", "com.google.android.keep"], ctx)
    if not pkg:
        return "ERROR: ไม่พบแอปโน้ตในเครื่อง"
    _dismiss()
    ok, what = step_home(_CREATE.pattern + r"|^(บันทึกใหม่|โน้ตใหม่|New note|สร้างบันทึก|เขียนบันทึก)$",
                         "ปุ่มสร้างบันทึกใหม่ (+ หรือรูปดินสอ)", pkg)
    if not ok:
        return f"เปิดแอปโน้ตแล้วแต่ {what} — สอนให้ดูได้: สั่ง \"จำขั้นตอน สร้างโน้ต\" แล้วกดเอง"
    trail = [what]
    step(r"^(บันทึก|Note|Notes|โน้ต|ข้อความ|Text)$", None, optional=True, wait=1.2)
    if body:
        r = _type(body, ctx)
        if r.startswith("ERROR"):
            return ("📝 เปิดโน้ตใหม่ให้แล้ว แต่แอปนี้ไม่ให้พิมพ์ผ่านระบบ — ข้อความอยู่ในคลิปบอร์ดแล้ว "
                    "กดค้างในโน้ตแล้วเลือก \"วาง\" ได้เลยครับ")
        trail.append("พิมพ์แล้ว")
        ok2, w2 = step(r"^(✓|✔|เสร็จ|เสร็จสิ้น|Done|บันทึก|Save)$|done|save|confirm|ok_btn", None, optional=True, wait=1.0)
        if w2:
            trail.append(w2)
        else:
            import screen_tools
            screen_tools.adb_shell(["input", "keyevent", "4"])       # ย้อนกลับ = บันทึกอัตโนมัติ (แอปโน้ตส่วนใหญ่)
            trail.append("ย้อนกลับเพื่อบันทึก")
    return "📝 สร้างโน้ตใหม่แล้ว (" + " → ".join(trail) + ")"


def _write(topic, kind):
    """ให้ AI เขียนเนื้อหาตามเรื่อง"""
    import agent
    import polite
    resp, _ = agent.call_llm([{"role": "user", "content": [{"type": "text", "text":
                              f"เขียน{kind}เรื่อง: {topic}\nภาษาไทย กระชับ เป็นธรรมชาติ ไม่มี markdown ไม่มีคำนำ"}]}], [],
                             system=agent.chat_prompt())
    return polite.fix(agent._collect_text(resp.get("content", [])).strip())


_WPS = re.compile(r"^(?:ช่วย)?\s*(?:เปิด\s*(?:wps|ดับบลิวพีเอส)\s*(?:แล้ว)?\s*)?(?:สร้าง|ทำ)\s*(?:ไฟล์)?\s*(?:เอกสาร|word|เวิร์ด|docx?)\s*(?:ใหม่)?"
                  r"\s*(?:ใน|ด้วย|ที่)?\s*(?:แอป)?\s*(?:wps|ดับบลิวพีเอส)?(?:\s*office)?\s*"
                  r"(?:(?P<v>ว่า|เขียนว่า|พิมพ์ว่า)\s*(?P<t>.+)|(?:เรื่อง|หัวข้อ)\s*(?P<topic>.+))?$", re.I)
_NOTE = re.compile(r"^(?:ช่วย)?\s*(?:จด|สร้าง|เขียน|เพิ่ม)\s*(?:โน้ต|โน๊ต|บันทึก|memo|note)\s*(?:ใหม่)?\s*(?:ไว้)?"
                   r"\s*(?:(?:ว่า|:)\s*(?P<t>.+)|(?:เรื่อง)\s*(?P<topic>.+))?$", re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip()
    t = re.sub(r"\s*(ให้หน่อย|หน่อย|ครับ|ค่ะ|นะ|ที)+\s*$", "", t)
    if not t or not config.ANDROID_APP:
        return None
    m = _WPS.match(t)
    if m and re.search(r"wps|ดับบลิวพีเอส|เอกสาร|word|เวิร์ด", t, re.I):
        topic = m.group("topic")
        body = (m.group("t") or "").strip() or (_write(topic, "เอกสาร (บรรทัดแรกเป็นชื่อเรื่อง ใช้ # นำหน้าหัวข้อย่อย - นำหน้ารายการ)")
                                                if topic else "")
        return wps_new_doc(body, ctx, title=(topic or "").strip()[:60] if topic else "")
    m = _NOTE.match(t)
    if m:
        body = (m.group("t") or "").strip() or (_write(m.group("topic"), "บันทึกสั้นๆ") if m.group("topic") else "")
        return note_new(body, ctx)
    return None


def _obj(props, req):
    return {"type": "object", "properties": props, "required": req}


TOOLS = {
    "wps_new_document": (lambda a, ctx: wps_new_doc(a.get("text", ""), ctx),
                         "สร้างเอกสารใหม่ใน WPS Office (+ พิมพ์เนื้อหาให้ถ้าใส่ text)",
                         _obj({"text": {"type": "string"}}, []), False),
    "new_note": (lambda a, ctx: note_new(a.get("text", ""), ctx), "สร้างโน้ต/บันทึกใหม่ในแอปบันทึก (+ เนื้อหา)",
                 _obj({"text": {"type": "string"}}, []), False),
}
