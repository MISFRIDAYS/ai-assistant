"""ส่ง/แชร์/อัปโหลด รูป วิดีโอ ไฟล์ เข้าแอปไหนก็ได้ + สั่งแอป AI (Claude/ChatGPT/Gemini) ให้พิมพ์/ส่งรูป/ส่งข้อมูล

ขั้นตอน: คัดลอกไฟล์ไปที่เก็บข้อมูลส่วนกลาง (แอปอื่นมองเห็น) → สแกนเข้าแกลเลอรี → ส่ง Intent SEND เข้าแอป
→ (ถ้าระบุผู้รับ) ค้นหา/แตะชื่อผู้รับ → กดปุ่มส่ง
ต้องเชื่อม ADB จึงจะทำได้ครบอัตโนมัติ ไม่มี ADB จะเปิดหน้าต่างแชร์ให้ผู้ใช้เลือกเอง
"""
import mimetypes
import os
import json
import re
import shutil
import time

import config

SHARED = os.environ.get("SHARED_STORAGE", "/storage/emulated/0")
_LATEST = ("latest", "last", "ล่าสุด", "เมื่อกี้", "เมื่อกี๊", "เพิ่งส่ง", "เพิ่งถ่าย", "อันนี้", "ที่ส่งมา")
_SEND_EXACT = ("ส่ง", "send", "โพสต์", "post", "แชร์", "share", "อัปโหลด", "upload", "ถัดไป", "next", "เสร็จ", "done")


def _sh(args, timeout=30, quote=False):
    import phone_tools
    return phone_tools._sh(args, timeout=timeout, quote=quote)


def _adb():
    import screen_tools
    return bool(screen_tools.adb_serial())


def mime_of(p):
    ext = os.path.splitext(p)[1].lower()
    extra = {".heic": "image/heic", ".webp": "image/webp", ".mkv": "video/x-matroska", ".m4a": "audio/mp4",
             ".opus": "audio/ogg", ".ogg": "audio/ogg"}
    return extra.get(ext) or mimetypes.guess_type(p)[0] or "application/octet-stream"


def kind_of(p):
    m = mime_of(p)
    return m.split("/")[0] if m.split("/")[0] in ("image", "video", "audio") else "file"


# ---------------------------------------------------------------- หาไฟล์

def _candidates():
    d = config.DATA_DIR
    dirs = [os.path.join(d, "inbox"), d]
    for sub in ("DCIM/Camera", "Pictures/Screenshots", "Pictures", "Pictures/AIBot", "Movies", "Movies/AIBot",
                "Download", "Download/AIBot", "Documents", "DCIM/Screenshots"):
        dirs.append(os.path.join(SHARED, sub))
    out = []
    for folder in dirs:
        try:
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                if os.path.isfile(p) and not n.startswith(".") and not _blocked(p):
                    out.append(p)
        except OSError:
            continue
    return out


def latest(kind=None):
    files = [p for p in _candidates() if kind is None or kind_of(p) == kind]
    return max(files, key=os.path.getmtime) if files else None


def _blocked(p):
    """ห้ามส่งไฟล์ลับ: .env/คีย์ API, โฟลเดอร์ซ่อน, ข้อมูลภายในบอท (ยกเว้นรูป/ไฟล์ที่ผู้ใช้ส่งมาและรูปที่บอทถ่าย)"""
    real = os.path.realpath(p)
    name = os.path.basename(real).lower()
    if name.startswith(".env") or name.endswith((".env", ".key", ".pem")):
        return True
    data = os.path.realpath(config.DATA_DIR)
    if real.startswith(data + os.sep):
        rel = os.path.relpath(real, data)
        return not (rel.startswith("inbox" + os.sep) or name.startswith(("photo_", "screen", "edit_", "out_")))
    return any(x.startswith(".") for x in real.split(os.sep)[1:])


def resolve(spec, kind=None):
    """'รูปล่าสุด' / 'คลิปล่าสุด' / path / ชื่อไฟล์ → path จริง"""
    s = (spec or "").strip()
    low = s.lower()
    if not kind:
        if any(w in low for w in ("รูป", "ภาพ", "photo", "image", "pic")):
            kind = "image"
        elif any(w in low for w in ("คลิป", "วิดีโอ", "วีดีโอ", "video")):
            kind = "video"
    if not s or any(w in low for w in _LATEST) or low in ("รูป", "ภาพ", "คลิป", "วิดีโอ", "ไฟล์"):
        return latest(kind)
    p = os.path.expanduser(s)
    if os.path.isfile(p):
        return p
    for c in (os.path.join(config.DATA_DIR, "inbox", s), os.path.join(SHARED, s)):
        if os.path.isfile(c):
            return c
    import files_tools
    return files_tools._resolve(s)


# ---------------------------------------------------------------- ทำให้แอปอื่นมองเห็นไฟล์

def publish(path):
    """คัดลอกไปที่เก็บข้อมูลส่วนกลาง + สแกนเข้าแกลเลอรี → (path ใหม่, content:// uri หรือ None)"""
    real = os.path.realpath(path)
    shared = os.path.realpath(SHARED)
    k = kind_of(path)
    if real.startswith(shared + os.sep) or config.MOCK_PHONE:
        dst = real
    else:
        sub = {"image": "Pictures/AIBot", "video": "Movies/AIBot", "audio": "Music/AIBot"}.get(k, "Download/AIBot")
        folder = os.path.join(SHARED, sub)
        try:
            os.makedirs(folder, exist_ok=True)
            safe = re.sub(r"[^\w.\-ก-๙]", "_", os.path.basename(path))[:90]
            dst = os.path.join(folder, safe)
            if os.path.exists(dst):
                dst = os.path.join(folder, f"{int(time.time())}_{safe}")
            shutil.copyfile(path, dst)
        except OSError as e:
            raise RuntimeError(f"คัดลอกไฟล์ไปที่เก็บข้อมูลเครื่องไม่ได้ ({e}) — รัน termux-setup-storage แล้วกดอนุญาต") from e
    try:
        os.utime(dst, None)                    # ให้ขึ้นเป็นไฟล์ล่าสุดในหน้าเลือกไฟล์
    except OSError:
        pass
    return dst, _media_uri(dst, k)


def _media_uri(dst, k):
    import phone_tools
    if config.MOCK_PHONE:
        return f"content://media/external/{'images' if k == 'image' else 'file'}/media/1"
    phone_tools.run(["termux-media-scan", dst], timeout=30)
    if not _adb():
        return None
    _sh(["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file://" + dst], quote=True)
    coll = {"image": "images", "video": "video", "audio": "audio"}.get(k)
    for _ in range(8):
        out = _sh(["content", "query", "--uri", "content://media/external/file", "--projection", "_id",
                   "--where", f"_data='{dst}'"], quote=True)
        m = re.search(r"_id=(\d+)", out)
        if m:
            return (f"content://media/external/{coll}/media/{m.group(1)}" if coll
                    else f"content://media/external/file/{m.group(1)}")
        time.sleep(0.8)
    return None


# ---------------------------------------------------------------- หน้าจอ: หาผู้รับ / กดส่ง

def _items():
    import screen_tools
    return screen_tools._elements(screen_tools._dump())


def _n(t):
    return re.sub(r"\s+", "", (t or "").lower())


_MARKS = re.compile(r"[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]")          # สระบน/ล่าง วรรณยุกต์ ไม้ไต่คู้ การันต์


def _loose(t):
    """เทียบชื่อแบบหลวม: ตัดช่องว่าง/วงเล็บ/เครื่องหมาย/อีโมจิ/วรรณยุกต์ (เสียงถอด เจ็ด ≈ เจก)"""
    t = _MARKS.sub("", (t or "").lower())
    return re.sub(r"[^0-9a-z\u0e01-\u0e2e\u0e30\u0e32\u0e33\u0e40-\u0e46]", "", t)


def _name_keys(name):
    """ชื่อที่ผู้ใช้พูด → คำที่ใช้ค้น: เต็ม, ตัดวงเล็บ, คำในวงเล็บ, ตัด @"""
    full = _n(name).lstrip("@")
    keys = [full]
    outer = _n(re.sub(r"[\(\[（].*?[\)\]）]", "", name)).lstrip("@")
    inner = [_n(x) for x in re.findall(r"[\(\[（](.*?)[\)\]）]", name)]
    for k in [outer] + inner:
        if k and len(k) >= 2 and k not in keys:
            keys.append(k)
    return keys


# ชื่อคนที่อยู่ในสตอรี่/โพสต์/รูปโปรไฟล์ — แตะแล้วไม่ได้เข้าห้องแชท (ไปดูสตอรี่/โปรไฟล์แทน)
_NOT_CHAT = re.compile(r"สตอรี่|story|reel|โพสต์|post|รูปโปรไฟล์|profile ?pic|ฟีด|feed|ติดตาม|follow|"
                       r"avatar|row_feed|reel_|story_", re.I)


def _find_name(items, name):
    import difflib
    cand = [e for e in items if not e["edit"] and (e["text"] or e["desc"])
            and not _NOT_CHAT.search(e["text"] + " " + e["desc"] + " " + e["id"])]
    for q in _name_keys(name):
        exact = [e for e in cand if q in (_n(e["text"]), _n(e["desc"]))]
        part = [e for e in cand if q in _n(e["text"]) or q in _n(e["desc"])]
        if exact or part:
            return (exact or part)[0]
    q = _loose(name)                            # สะกดใกล้เคียง (เสียงถอดเพี้ยน/มีวงเล็บ/อีโมจิ)
    if len(q) < 2:
        return None
    ui = {_loose(x) for x in _NAV + _UI_LABELS}
    best, score, gap = None, 0.0, 999
    for e in cand:
        for raw in (e["text"], e["desc"]):
            for part in [raw] + re.split(r"[,·\n|•]", raw or ""):      # desc ยาวๆ เช่น "ชื่อ, ข้อความล่าสุด, 2 ชม."
                v = _loose(part)
                if len(v) < 2 or len(v) > 60 or v in ui:            # ปุ่ม/ชื่อแอป ("LINE" "ส่ง") ไม่ใช่ชื่อคน
                    continue
                # ชื่อบนจอสั้นกว่าที่พูดมาก ("ภรรยา" กับ "ภรรยาคนเจก") ไม่นับว่าตรง
                if q in v or (len(v) >= 3 and v in q and len(v) >= 0.6 * len(q)):
                    r = 0.95
                else:
                    r = difflib.SequenceMatcher(None, q, v[:len(q) + 3]).ratio()
                d = abs(len(v) - len(q))
                if r > score or (r == score and d < gap):                # คะแนนเท่ากัน → เลือกชื่อที่ยาวใกล้เคียงที่สุด
                    best, score, gap = e, r, d
    return best if score >= 0.75 else None


_UI_LABELS = ("line", "ไลน์", "instagram", "ไอจี", "facebook", "messenger", "whatsapp", "telegram", "ส่ง", "send",
              "ค้นหา", "search", "แชท", "chats", "chat", "ข้อความ", "messages", "เพื่อน", "friends", "โทร", "call")


def _visible_names(limit=12):
    try:
        names = []
        for e in _items():
            v = (e["text"] or e["desc"]).strip()
            if 1 < len(v) <= 30 and not e["edit"] and v not in names:
                names.append(v)
        return ", ".join(names[:limit])
    except Exception:  # noqa: BLE001
        return ""


_DM_ICON = ("ข้อความ", "messenger", "direct", "messages", "message", "inbox", "กล่องข้อความ", "แชท", "chats", "chat")


def _dump_log(tag, items, n=40):
    """บันทึกสิ่งที่เห็นบนจอลง log (ใช้ดูว่าบอทมองเห็นอะไรตอนติด)"""
    rows = [f"{(e['text'] or e['desc'])[:22]!r}@{e['x']},{e['y']}{'*' if e['click'] else ''}{'E' if e['edit'] else ''}"
            for e in items if (e["text"] or e["desc"] or e["edit"])][:n]
    print(f"[dm] {tag}: " + " ".join(rows), flush=True)


_NAV = ("หน้าหลัก", "home", "reels", "โปรไฟล์", "profile", "กิจกรรม", "activity", "สร้าง", "create",
        "ค้นหาและสำรวจ", "searchandexplore", "explore", "สำรวจ", "notifications", "การแจ้งเตือน", "ฟีด", "feed")


def _dm_icon(items):
    """ปุ่มกล่องข้อความ: อยู่ในแถบเมนู (เรียงแนวเดียวกับ หน้าหลัก/Reels/โปรไฟล์) หรือมุมขวาบน
    ไม่แตะปุ่ม 'ข้อความ' ลอยๆ กลางจอ (มักเป็นปุ่มแชร์โพสต์)"""
    if not items:
        return None
    w = max(e["box"][2] for e in items) or 1
    h = max(e["box"][3] for e in items) or 1
    nav = [e for e in items if _n(e["text"]) in _NAV or _n(e["desc"]) in _NAV]
    best, score = None, 0
    for e in items:
        v = [_n(e["text"]), _n(e["desc"])]
        if not e["click"] or not any(x in _DM_ICON for x in v):
            continue
        sc = 0
        if sum(1 for n in nav if abs(n["x"] - e["x"]) <= 25) >= 2:
            sc = 4                                   # แถบเมนูแนวตั้ง (แท็บเล็ต) — เช่น Instagram แถบซ้าย
        elif sum(1 for n in nav if abs(n["y"] - e["y"]) <= 25) >= 2:
            sc = 3                                   # แถบเมนูแนวนอน (ล่าง/บน)
        elif e["x"] > 0.72 * w and e["y"] < 0.2 * h:
            sc = 2                                   # มุมขวาบน
        if sc > score:
            best, score = e, sc
    if best is None:                              # หน้าต่างลอย/เลย์เอาต์มือถือ: ไอคอน DM มักอยู่บนสุด
        tops = sorted((e for e in items if e["click"] and not e["edit"]
                       and any(x in _DM_ICON for x in (_n(e["text"]), _n(e["desc"])))), key=lambda e: e["y"])
        best = tops[0] if tops else None
    return best


def _search_box(items):
    box = next((x for x in items if x["edit"]), None)
    if box:
        return box
    return next((x for x in items
                 if ("search" in x["id"].lower() or "ค้นหา" in (x["desc"] + x["text"])
                     or "search" in (x["desc"] + x["text"]).lower())
                 and not re.search(r"สำรวจ|explore", x["desc"] + x["text"], re.I)), None)


def _reach_inbox(key, to, items):
    """ยังไม่อยู่หน้ารวมแชท (เช่น ไปตกหน้าฟีด/สำรวจ) → แตะปุ่มกล่องข้อความในแถบเมนู
    คืน (items, เข้ากล่องข้อความได้ไหม)"""
    import screen_tools
    import skills
    icon = skills.ui_match(key, "inbox", items) or _dm_icon(items)
    if not icon and key in ("instagram", "facebook", "messenger", "tiktok"):   # ไอคอนไม่มีชื่อ → มองภาพหา
        icon = screen_tools.vision_find("ปุ่มเปิดกล่องข้อความ/แชท (Direct, Messenger, ไอคอนเครื่องบินกระดาษหรือฟองคำพูด)")
        if icon:
            print(f"[dm] หาปุ่มกล่องข้อความด้วยการมองภาพ @{icon['x']},{icon['y']}", flush=True)
    if not icon:
        _dump_log("หาปุ่มกล่องข้อความไม่เจอ", items)
        return items, False
    print(f"[dm] แตะปุ่มกล่องข้อความ {icon['text'] or icon['desc']!r} @{icon['x']},{icon['y']}", flush=True)
    screen_tools.adb_shell(["input", "tap", str(icon["x"]), str(icon["y"])])
    time.sleep(0.6)
    got = _wait_items(lambda it: _find_name(it, to) is not None, timeout=4)
    if not got:
        got = _wait_items(lambda it: any(x["edit"] for x in it), timeout=1.5)
    if got and key:
        skills.ui_learn(key, "inbox", icon)            # จำปุ่มนี้ไว้ ครั้งหน้าแตะเลย
    return (got or _items()), True


_FULL = ("เต็มจอ", "fullscreen", "full screen", "maximize", "ขยายเต็มจอ", "ขยาย")


def _unfloat(items):
    """แอปเปิดเป็นหน้าต่างลอย (HarmonyOS) → กด 'เต็มจอ' ให้ใช้งานง่าย/อ่านจอแม่นขึ้น คืน items ใหม่"""
    import screen_tools
    labels = {_n(e["text"]) or _n(e["desc"]) for e in items}
    if not ({"ย่อ", "minimize", "ปิด", "close"} & labels):
        return items
    btn = next((e for e in items if e["click"] and (_n(e["text"]) in _FULL or _n(e["desc"]) in _FULL)), None)
    if not btn:
        return items
    print(f"[dm] แอปเป็นหน้าต่างลอย → กดเต็มจอ @{btn['x']},{btn['y']}", flush=True)
    screen_tools.adb_shell(["input", "tap", str(btn["x"]), str(btn["y"])])
    time.sleep(1.3)
    try:
        return _items()
    except RuntimeError:
        return items


_NOT_NAME = re.compile(r"^(\d[\d.,]*\s*(พัน|ล้าน|k|m)?|.*(สตอรี่|story|reels|คลิป|โพสต์|ค้นหา|search|หน้าหลัก|"
                       r"โปรไฟล์|ข้อความ|กิจกรรม|สร้าง|เต็มจอ|ย่อ|ปิด|แถบ|ชม\.|นาที|วัน|ส่งแล้ว|ดูแล้ว|คุณ:|you:).*)$",
                       re.I)


def _chat_rows(items):
    out = []
    for e in items:
        for v in (e["text"], (e["desc"] or "").split(",")[0]):
            v = (v or "").strip()
            if 1 < len(v) <= 30 and not e["edit"] and not _NOT_NAME.match(v) and v not in [o[0] for o in out]:
                out.append((v, e))
    return out


def _remember_chat_names(items):
    try:
        import skills
        skills.add_names([v for v, _ in _chat_rows(items)][:15], key="inbox_names")
    except Exception:  # noqa: BLE001
        pass


def _llm_pick(to, items):
    """ชื่อจากเสียงเพี้ยนมาก (Heart → 'part') → ให้ AI เลือกจากรายชื่อที่เห็นบนจอจริง (1 รอบ ไม่ใช้เครื่องมือ)"""
    rows = _chat_rows(items)[:25]
    if not rows:
        return None
    names = [v for v, _ in rows]
    prompt = ("[งานเลือกชื่อ ห้ามทำอย่างอื่น] ผู้ใช้พูดชื่อคนว่า \"" + to + "\" (ถอดจากเสียง อาจเพี้ยนมาก "
              "เช่น Heart→part, คนเจก→คนเจ็ด, ชื่ออังกฤษถูกเขียนเป็นไทย) ชื่อไหนในรายการนี้ตรงที่สุด?\n"
              + "\n".join(f"- {n}" for n in names)
              + "\nตอบเฉพาะชื่อที่เลือก คัดลอกให้ตรงตามรายการ หรือตอบ NONE ถ้าไม่มีชื่อไหนใกล้เคียงเลย")
    try:
        import agent
        resp, who = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}], [])
        ans = agent._collect_text(resp.get("content", [])).strip().strip("`\"'- ").splitlines()[0].strip()
    except Exception as e:  # noqa: BLE001
        print(f"[dm] เลือกชื่อด้วย AI ไม่ได้: {e}", flush=True)
        return None
    print(f"[dm] '{to}' → AI เลือกชื่อ {ans!r} จาก {names[:10]}", flush=True)
    for v, e in rows:
        if ans and (ans == v or _loose(ans) == _loose(v)):
            return e
    return None


def _pick_recipient(to, key=""):
    """หน้ารวมแชทของแอป: หาชื่อผู้รับในรายการ ไม่เจอ → ค้นหาด้วยช่องค้นหา แล้วแตะ"""
    import screen_tools
    import skills
    alias = (skills.get_pref(f"alias:{key}:{_loose(to)}") if key else None) \
        or skills.get_pref(f"alias:*:{_loose(to)}")                       # ชื่อจริงที่เคยเจอ/ผู้ใช้สอน
    names = [alias, to] if alias else [to]

    def look(it):
        for nm in names:
            hit = _find_name(it, nm)
            if hit:
                return hit
        return None
    # รอให้รายการแชทโหลดก่อน (ห้ามรีบไปช่องค้นหา ทั้งที่ชื่ออยู่ในรายการแรกๆ)
    items = _unfloat(_items())
    items = _wait_items(lambda it: look(it) is not None, timeout=4) or items
    e = look(items)
    reached = True
    if not e:
        items, reached = _reach_inbox(key, to, items)
        e = look(items)
    if reached or key != "instagram":
        _remember_chat_names(items)
    if not e and (reached or key != "instagram"):     # ชื่อเพี้ยนจากเสียง → ให้ AI เลือกจากชื่อที่เห็นบนจอ
        e = _llm_pick(to, items)
    if not e and (reached or key != "instagram"):   # ข้อความหาไม่เจอ → ให้ AI มองภาพหน้าจอหาแถวแชทของคนนี้
        e = screen_tools.vision_find(f"แถวในรายการแชท ของคนชื่อ '{to}'" + (f" หรือ '{alias}'" if alias else ""))
        if e:
            print(f"[dm] หาเจอด้วยการมองภาพ: {e['text']!r} @{e['x']},{e['y']}", flush=True)
    if not e and key == "instagram" and not reached:
        _dump_log("ยังไม่ได้อยู่หน้ากล่องข้อความ (ไม่ค้นในหน้าสำรวจ กันส่งผิดคน)", items)
        return None
    if not e:
        box = _search_box(items)
        if box and not box["edit"]:
            screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
            time.sleep(1.0)
            items = _items()
            box = next((x for x in items if x["edit"]), None)
        if box:
            screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
            time.sleep(0.4)
            q = _name_keys(to)
            word = q[1] if len(q) > 1 and len(q[1]) >= 2 and "(" in to else to      # ค้นด้วยชื่อที่ไม่มีวงเล็บ
            word = re.sub(r"[\(\)\[\]（）]", "", word)
            screen_tools.type_text({"text": word, "send": False}, None)
            got = _wait_items(lambda it: _find_name([x for x in it if not x["edit"]], to) is not None, timeout=5)
            items = got or _items()
            e = _find_name([x for x in items if not x["edit"]], to)
    if not e:
        _dump_log(f"หา '{to}' ไม่เจอ", items)
        return None
    screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(1.0)
    return e


def _tap_send(ctx, near_y=None):
    """กดปุ่มส่ง/โพสต์/อัปโหลด — ถ้ามีหลายปุ่ม (เช่น Messenger มีปุ่มส่งทุกแถว) เลือกปุ่มที่อยู่แถวเดียวกับผู้รับ"""
    import permissions
    import screen_tools
    if permissions.need_confirm(ctx, "message") and ctx is not None and \
            not ctx.confirm(f"กดส่งในแอป {screen_tools._current_app()}"):
        return "ผู้ใช้ไม่อนุญาตให้ส่ง — ค้างไว้ที่หน้าส่ง"
    items = _items()
    cands = [e for e in items if not e["edit"] and "send" in e["id"].lower()]
    for e in items:
        if e["edit"] or e in cands:
            continue
        for v in (e["text"].strip().lower(), e["desc"].strip().lower()):
            if v in _SEND_EXACT or (len(v) < 25 and v.startswith(("send", "ส่ง"))):
                cands.append(e)
                break
    if not cands:
        return "หาปุ่มส่งไม่เจอ — ใช้ read_screen หาปุ่ม (ลูกศร/เครื่องบินกระดาษ/ส่ง) แล้ว tap"
    e = min(cands, key=lambda c: abs(c["y"] - near_y)) if near_y is not None and len(cands) > 1 else cands[0]
    screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(1.0)
    return f"กดส่งแล้ว ✅ (ปุ่ม {e['text'] or e['desc'] or e['id']})"


def _screen_text(limit=1800):
    """ข้อความที่อ่านได้บนจอ (ใช้อ่านคำตอบของแอป AI)"""
    try:
        items = _items()
    except Exception as e:  # noqa: BLE001
        return f"(อ่านหน้าจอไม่ได้: {e})"
    lines, seen = [], set()
    for e in items:
        t = e["text"].strip()
        if len(t) > 1 and t not in seen and not e["edit"]:
            seen.add(t)
            lines.append(t)
    out = "\n".join(lines)
    return out[-limit:]


# ---------------------------------------------------------------- ส่งเข้าแอป

def _target(app):
    """ชื่อแอป → (key, package ที่ติดตั้งจริงหรือ None, ชื่อที่แสดง)"""
    import phone_tools
    if not app:
        return None, None, None
    key = phone_tools.ALIASES.get(app.strip().lower(), app.strip()).lower()
    installed = {c.split("/")[0] for c in phone_tools._launcher_components()}
    pkg = phone_tools.COMMON_APPS.get(key)
    if "." in key and " " not in key:
        pkg = key
    if not pkg or (installed and pkg not in installed):
        try:
            import app_index
            found, _ = app_index.find(key)
            pkg = found if found and (not installed or found in installed) else None
        except Exception:  # noqa: BLE001
            pkg = None
    labels = phone_tools.APP_LABELS.get(key) or [app.strip()]
    return key, pkg, labels


def _send_intent(uri, mime, text, pkg):
    args = ["am", "start", "--user", "0", "-a", "android.intent.action.SEND", "-t", mime]
    if uri:
        args += ["--eu", "android.intent.extra.STREAM", uri, "--grant-read-uri-permission"]
    if text:
        args += ["--es", "android.intent.extra.TEXT", text]
    if pkg:
        args += ["-p", pkg]
    return _sh(args, quote=True)


def _choose_app(labels):
    """หน้าต่าง "แชร์ไปที่..." ของระบบ: แตะชื่อแอป (ถ้าไม่เจอลองแตะ GBox)"""
    import phone_tools
    time.sleep(1.8)
    hit = phone_tools._tap_label(labels)
    if not hit:
        import screen_tools
        try:
            screen_tools.swipe({"direction": "up"}, None)        # ขยายรายการแอป
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.8)
        hit = phone_tools._tap_label(labels) or phone_tools._tap_label(["GBox"])
    hit = hit or None
    if hit:
        time.sleep(1.5)
    return hit


def _share_one(path, app, text, ctx, trace):
    """ส่งไฟล์ 1 ไฟล์ (หรือข้อความอย่างเดียวถ้า path=None) เข้าแอป"""
    import phone_tools
    uri, mime = None, "text/plain"
    if path:
        mime = mime_of(path)
        dst, uri = publish(path)
        trace.append(f"ไฟล์อยู่ที่ {dst.replace(SHARED + '/', '')}")
        if not uri:
            if _adb():
                return False, "หา content uri ของไฟล์ไม่เจอ (ระบบยังสแกนไฟล์ไม่เสร็จ) ลองใหม่อีกครั้ง"
            out = phone_tools.run(["termux-share", "-a", "send", "-c", mime, dst], timeout=30)
            return (not out.startswith("ERROR")), ("ไม่ได้เชื่อม ADB → เปิดหน้าต่างแชร์ให้แล้ว ผู้ใช้ต้องเลือกแอป/ผู้รับเอง "
                                                   + (out if out.startswith("ERROR") else ""))
    elif not _adb():
        out = phone_tools.run(["termux-share", "-a", "send", "-c", "text/plain"], input_text=text, timeout=30)
        return (not out.startswith("ERROR")), "ไม่ได้เชื่อม ADB → เปิดหน้าต่างแชร์ให้เลือกแอปเอง"
    key, pkg, labels = _target(app)
    res = _send_intent(uri, mime, text, pkg)
    if not phone_tools._launch_ok(res) and pkg:
        trace.append(f"ส่งตรงเข้า {pkg} ไม่ได้ → ใช้หน้าต่างเลือกแอป")
        pkg = None
        res = _send_intent(uri, mime, text, None)
    if not phone_tools._launch_ok(res):
        return False, f"เปิดหน้าส่งไม่ได้: {res[:150]}"
    if not pkg and app:
        hit = _choose_app(labels)
        if not hit:
            return False, f"เปิดหน้าต่างแชร์แล้วแต่ไม่เจอแอป {labels[0]} — ใช้ read_screen แล้ว tap_text ชื่อแอปเอง"
        trace.append(f"เลือกแอป {hit}")
    return True, f"เปิดหน้าส่งของ {app or 'แอป'} แล้ว"


def send_to_app(a, ctx):
    """ส่งรูป/วิดีโอ/ไฟล์/ข้อความเข้าแอปไหนก็ได้ และ (ถ้าระบุ) เลือกผู้รับแล้วกดส่งให้"""
    import screen_tools
    app = (a.get("app") or "").strip()
    text = (a.get("text") or "").strip()
    to = (a.get("to") or "").strip()
    files = a.get("files") or ([a["file"]] if a.get("file") else [])
    if isinstance(files, str):
        files = [x.strip() for x in files.split(",") if x.strip()]
    paths = []
    for f in files[:10]:
        p = resolve(f)
        if not p:
            return f"ERROR: ไม่พบไฟล์ '{f}' — ใช้ find_files ค้นหาก่อน หรือให้ผู้ใช้ส่งไฟล์มาทาง Telegram"
        if _blocked(p):
            return f"ERROR: ไฟล์ {os.path.basename(p)} เป็นไฟล์ระบบ/ข้อมูลลับ ส่งออกไม่ได้"
        paths.append(p)
    if not paths and not text:
        return "ERROR: ต้องระบุ files (ไฟล์/รูป/คลิป) หรือ text อย่างน้อยหนึ่งอย่าง"
    if getattr(ctx, "hold", False):
        auto = False
    else:
        auto = a.get("send", True)
    trace, report = [], []
    jobs = paths or [None]
    for i, p in enumerate(jobs):
        msg = text if i == 0 else ""
        try:
            ok, info = _share_one(p, app, msg, ctx, trace)
        except Exception as e:  # noqa: BLE001
            ok, info = False, str(e)
        name = os.path.basename(p) if p else "ข้อความ"
        if not ok:
            report.append(f"✗ {name}: {info}")
            break
        if not _adb():
            report.append(f"• {name}: {info}")
            continue
        near = None
        if to:
            hit = _pick_recipient(to)
            if not hit:
                report.append(f"• {name}: เปิดหน้าส่งแล้ว แต่หาผู้รับ '{to}' ไม่เจอ — ใช้ read_screen เลือกเอง")
                auto = False
                break
            near = hit["y"]
            trace.append(f"เลือกผู้รับ {hit['text'] or hit['desc']}")
        if auto:
            report.append(f"• {name}: " + _tap_send(ctx, near))
        else:
            report.append(f"• {name}: เตรียมไว้แล้ว ยังไม่กดส่ง")
    out = "\n".join(report)
    if trace:
        out += "\n(" + " → ".join(trace) + ")"
    if a.get("read_reply") and _adb():
        time.sleep(min(60, max(5, int(a.get("wait", 15)))))
        out += "\n\nข้อความบนจอตอนนี้ (คำตอบของแอป):\n" + _screen_text()
    elif _adb() and auto and not to:
        out += "\nถ้ายังไม่ส่ง ให้ read_screen ตรวจหน้าจอแล้วทำต่อ"
    screen_tools._last["items"] = []
    return out


def ask_ai_app(a, ctx):
    """สั่งแอป AI ในเครื่อง (Claude, ChatGPT, Gemini): พิมพ์คำถาม + แนบรูป/ไฟล์ → ส่ง → อ่านคำตอบกลับมา"""
    import phone_tools
    import screen_tools
    app = a.get("app") or "claude"
    if not _adb():
        return screen_tools.NOT_CONNECTED
    files = a.get("files") or []
    prompt = a.get("text") or ""
    if files:
        res = send_to_app({"app": app, "files": files, "text": prompt, "send": False}, ctx)
        if res.startswith("ERROR") or "✗" in res:
            return res
        time.sleep(1.5)
        items = _items()
        box = next((x for x in items if x["edit"]), None)
        if prompt and box and _n(prompt[:15]) not in _n(box["text"]):
            screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
            screen_tools.type_text({"text": prompt, "send": False}, ctx)
        sent = _tap_send(ctx)
    else:
        opened = phone_tools.open_app({"app": app}, ctx)
        if opened.startswith("ERROR"):
            return opened
        time.sleep(2.5)
        items = _items()
        box = next((x for x in items if x["edit"]), None)
        if not box:
            return f"{opened}\nเปิดแอปแล้วแต่หาช่องพิมพ์ไม่เจอ — ใช้ read_screen แล้วแตะช่องพิมพ์ จากนั้น type_text"
        screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
        time.sleep(0.5)
        sent = screen_tools.type_text({"text": prompt, "send": True}, ctx)
    wait = min(90, max(5, int(a.get("wait", 20))))
    if not a.get("read_reply", True):
        return f"ส่งให้ {app} แล้ว: {sent}"
    time.sleep(wait)
    return f"ส่งให้ {app} แล้ว ({sent})\n\nข้อความบนจอหลังรอ {wait} วิ (คำตอบของ {app}):\n" + _screen_text()


# ---------------------------------------------------------------- ส่งข้อความแชทหาคน (ทำครบทุกขั้น ตรวจผลจริง)

DM_LINKS = {   # เปิดห้องแชทของ username ได้ตรงๆ
    "instagram": "https://ig.me/m/{u}", "messenger": "https://m.me/{u}", "facebook": "https://m.me/{u}",
    "telegram": "https://t.me/{u}", "whatsapp": "https://wa.me/{u}",
}
_COMPOSER = ("message", "ข้อความ", "aa", "พิมพ์", "type", "chat_input", "composer", "edit")


def _wait_items(pred, timeout=8.0, every=0.7):
    """อ่านจอซ้ำจนกว่าเงื่อนไขจะจริง (แทนการรอตายตัว) → คืน items ล่าสุด หรือ None ถ้าหมดเวลา"""
    t0 = time.time()
    while True:
        try:
            items = _items()
            if pred(items):
                return items
        except RuntimeError:
            pass
        if time.time() - t0 > timeout:
            return None
        time.sleep(every)


def _composer(items):
    """ช่องพิมพ์ข้อความในห้องแชท (มักอยู่ล่างสุดของจอ)"""
    edits = [e for e in items if e["edit"] and not e.get("password")
             and not re.search(r"รหัสผ่าน|password|อีเมล|email|เบอร์โทร|phone|username|ชื่อผู้ใช้", e["text"] + e["desc"] + e["id"], re.I)]
    if not edits:                                 # ช่องรหัสผ่าน/ล็อกอิน ไม่ใช่ช่องแชท — ห้ามพิมพ์ลงไปเด็ดขาด
        return None
    named = [e for e in edits if any(k in (e["text"] + e["desc"] + e["id"]).lower() for k in _COMPOSER)]
    return max(named or edits, key=lambda e: e["y"])


def _is_username(to):
    return bool(re.fullmatch(r"@?[A-Za-z0-9._]{2,30}", to or ""))


APP_PKG = {"instagram": "com.instagram.android", "line": "jp.naver.line.android", "messenger": "com.facebook.orca",
           "facebook": "com.facebook.katana", "telegram": "org.telegram.messenger", "whatsapp": "com.whatsapp"}
_PLACEHOLDER = re.compile(r"^(ส่งข้อความ|ข้อความ|พิมพ์ข้อความ|aa|message|type a message|write a message|"
                          r"เขียนข้อความ|ถาม meta ai.*|message\.\.\.|พิมพ์ที่นี่)\s*[.…]*$", re.I)


def _screen_h(items):
    return max([e["box"][3] for e in items] or [1]) or 1


def _current_chat(key, to):
    """ตอนนี้อยู่ในห้องแชทของแอปนี้ไหม → "same" (ห้องของคนนี้) / "other" (ห้องคนอื่น) / None (ไม่ได้อยู่ในห้องแชท)"""
    import phone_tools
    pkg = APP_PKG.get(key)
    fg = phone_tools._fg()
    if not pkg or not fg or fg != pkg:
        return None
    try:
        items = _items()
    except RuntimeError:
        return None
    comp = _composer(items)
    if not comp:
        return None
    h = _screen_h(items)
    head = [e for e in items if e["y"] < 0.22 * h and not e["edit"]]     # ชื่อห้องแชทอยู่แถบบน
    hit = _find_name(head, to)
    print(f"[dm] เปิดห้องแชทค้างอยู่ หัวห้อง: {[(e['text'] or e['desc'])[:20] for e in head][:6]} → "
          f"{'ห้องเดียวกัน' if hit else 'ห้องอื่น'}", flush=True)
    return "same" if hit else "other"


def _leave_chat():
    """กดย้อนกลับจนออกจากห้องแชท (กลับไปหน้ารายการแชท) → True ถ้าออกได้"""
    import screen_tools
    for _ in range(3):
        screen_tools.adb_shell(["input", "keyevent", "4"])
        time.sleep(1.0)
        try:
            if _composer(_items()) is None:
                return True
        except RuntimeError:
            return False
    return False


def _clear_box(box):
    """ช่องพิมพ์มีข้อความค้างอยู่ (ไม่ใช่ข้อความจางๆ ตัวอย่าง) → ลบทิ้งก่อนพิมพ์ใหม่"""
    import screen_tools
    t = (box.get("text") or "").strip()
    if not t or _PLACEHOLDER.match(t):
        return
    print(f"[dm] ล้างข้อความค้างในช่องพิมพ์: {t[:30]!r}", flush=True)
    screen_tools.adb_shell(["input", "keyevent", "123"])                       # ไปท้ายข้อความ
    screen_tools.adb_shell(["input", "keyevent"] + ["67"] * min(300, len(t) + 5))   # ลบทีละตัว


_REPLY_HEAD = re.compile(r"^\s*(?:โอเค|ok|เอ่อ|ช่วย)?\s*(?:ตอบ(?:กลับ)?|พิมพ์|บอก(?:เขา|เค้า|เธอ|มัน)?|ส่ง|เขียน)?"
                         r"\s*(?:ข้อความ)?\s*(?:ไป|กลับไป)?\s*(?:ให้(?:เขา|เค้า)?)?\s*(?:ว่า|บอกว่า)?\s*")
_SEND_TAIL = re.compile(r"\s*(?:แล้ว\s*(?:ก็)?)?\s*(?:กด)?\s*ส่ง\s*(?:ข้อความ)?\s*(?:เลย|ให้|ที|ด้วย|หน่อย|นะ|ครับ|ค่ะ)*\s*$")


def reply_text(spoken):
    """'ตอบกลับว่า โอเค แล้วกดส่ง' → 'โอเค' (เอาแค่ตัวข้อความ ไม่เอาคำสั่ง)"""
    m = _REPLY_HEAD.sub("", (spoken or "").strip(), count=1).strip()
    prev = None
    while prev != m:
        prev = m
        m = _SEND_TAIL.sub("", m).strip()
    return m.strip(" \"'“”")


def last_sender(max_age=1800):
    """คนที่ทักมาล่าสุด (จากแจ้งเตือน) ภายใน 30 นาที → {"app","to"} หรือ None"""
    try:
        import skills
        n = skills.get_pref("last_notif")
    except Exception:  # noqa: BLE001
        return None
    if n and time.time() - n.get("t", 0) <= max_age:
        return n
    try:                                            # ยังไม่มีบันทึก (เช่น ไม่ได้เปิดโหมดเสียง) → ดูแจ้งเตือนที่ค้างอยู่
        import fastpath
        items, _ = fastpath._notif_items()
        for it in items or []:
            app = fastpath._PKG_APP.get(it.get("packageName"))
            title = (it.get("title") or "").strip()
            if app and title:
                return {"app": app, "to": re.sub(r"\s*\(\d+.*\)$", "", title), "t": time.time(),
                        "key": it.get("key") or ""}
    except Exception:  # noqa: BLE001
        pass
    return None


ECHO_REFUSE = ("ERROR: ข้อความที่จะส่งดูเหมือนระบบถอดเสียงผิด (มีรายชื่อหรือคำว่า \"ผู้ช่วย\" ปนมา) "
               "— ยังไม่ได้ส่ง ช่วยพูดข้อความอีกครั้งนะ")


def _echo_text(msg):
    """ข้อความที่จะส่งเป็นคำที่ระบบถอดเสียงแต่งเอง (ท่องรายชื่อ) ไหม → ห้ามส่ง"""
    try:
        import voice
        return voice.message_echo(msg)
    except Exception:  # noqa: BLE001
        return False


def reply_last(msg, ctx=None):
    """ตอบคนที่ทักมาล่าสุด ด้วยแอปที่เขาทักมา (ไม่ใช่แอปที่ส่งครั้งล่าสุด)"""
    n = last_sender()
    if not n:
        return None
    if _echo_text(msg):
        return ECHO_REFUSE[7:]
    print(f"[dm] ตอบกลับคนที่ทักล่าสุด: {n['app']} / {n['to']} ← {msg!r}", flush=True)
    if config.ANDROID_APP and n.get("key"):        # แอป: ตอบผ่านปุ่ม "ตอบกลับ" ในแจ้งเตือนเลย (เร็ว ไม่ต้องเปิดแอป)
        try:
            import android_shim
            if android_shim.bridge().notifReply(n["key"], msg):
                return f"ตอบกลับ {n['to']} ใน {n['app']} แล้ว ✅: {msg}"
        except Exception as e:  # noqa: BLE001
            print(f"[dm] ตอบผ่านแจ้งเตือนไม่ได้: {e}", flush=True)
    return send_dm({"app": n["app"], "to": n["to"], "text": msg}, ctx)


def chat_open():
    """ตอนนี้เปิดห้องแชทอยู่ไหม (มีช่องพิมพ์ข้อความอยู่ล่างจอ)"""
    try:
        items = _items()
    except Exception:  # noqa: BLE001
        return False
    c = _composer(items)
    return bool(c) and c["y"] > 0.5 * _screen_h(items)


def screen_brief():
    """สรุปสั้นๆ ว่าตอนนี้จออยู่ที่ไหน (แนบให้ AI ตีความคำสั่ง เหมือนคนที่มองจออยู่)"""
    import phone_tools
    try:
        items = _items()
    except Exception:  # noqa: BLE001
        return ""
    fg = phone_tools._fg() or "?"
    app = next((k for k, v in APP_PKG.items() if v == fg), fg)
    c = _composer(items)
    h = _screen_h(items)
    if c and c["y"] > 0.5 * h:
        head = [(e["text"] or e["desc"]).strip() for e in items if e["y"] < 0.22 * h and not e["edit"]
                and (e["text"] or e["desc"]).strip()]
        title = next((x for x in head if 1 < len(x) <= 40), "")
        return f"ตอนนี้ผู้ใช้เปิดห้องแชท{(' ของ ' + repr(title)) if title else ''} ในแอป {app} อยู่ (มีช่องพิมพ์ข้อความ)"
    labels = [(e["text"] or e["desc"]).strip() for e in items if (e["text"] or e["desc"]).strip()][:12]
    return f"ตอนนี้หน้าจออยู่ในแอป {app} เห็น: {', '.join(x[:20] for x in labels)}"


def type_here(text, ctx=None, send=False):
    """พิมพ์ลงช่องที่เปิดอยู่บนจอ (โน้ต/เอกสาร/ช่องโพสต์/ห้องแชท) — กดส่งเฉพาะเมื่อสั่ง send"""
    import screen_tools
    if not _adb():
        return screen_tools.NOT_CONNECTED
    try:
        items = _items()
    except RuntimeError as e:
        return f"ERROR: {e}"
    edits = [e for e in items if e["edit"]]
    if not edits:
        return "ERROR: ไม่เจอช่องพิมพ์บนจอ — เปิดหน้าที่จะพิมพ์ (โน้ต/แชท/ช่องโพสต์) ค้างไว้ก่อน"
    box = _composer(items) if send else max(edits, key=lambda e: (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1]))
    screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
    time.sleep(0.4)
    _clear_box(box)
    res = screen_tools.type_text({"text": text, "send": False}, ctx)
    if res.startswith("ERROR"):
        return res
    if not send:
        return "พิมพ์ลงช่องบนจอแล้ว (ยังไม่กดส่ง/บันทึก)"
    import phone_tools
    fg = phone_tools._fg() or ""
    key = next((k for k, v in APP_PKG.items() if v == fg), fg)
    ok, info = _send_in_chat(key, text, ctx)
    return "พิมพ์และกดส่งแล้ว ✅" if ok else f"ERROR: พิมพ์แล้วแต่กดส่งไม่สำเร็จ ({info})"


def send_here(text, ctx=None):
    """'พิมพ์ว่า ...' ตอนเปิดห้องแชทค้างไว้ → ส่งเข้าห้องที่เปิดอยู่เลย"""
    import phone_tools
    import screen_tools
    if _echo_text(text):
        return ECHO_REFUSE
    if not _adb():
        return screen_tools.NOT_CONNECTED
    try:
        items = _items()
    except RuntimeError as e:
        return f"ERROR: {e}"
    box = _composer(items)
    if not box:
        return "ERROR: ตอนนี้ไม่ได้เปิดห้องแชทอยู่ — บอกชื่อคนด้วย เช่น \"ส่งข้อความหาแม่ในไลน์ว่า ...\""
    fg = phone_tools._fg() or ""
    key = next((k for k, v in APP_PKG.items() if v == fg), fg)
    screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
    time.sleep(0.5)
    _clear_box(box)
    res = screen_tools.type_text({"text": text, "send": False}, ctx)
    if res.startswith("ERROR"):
        return res
    if getattr(ctx, "hold", False):
        return "พิมพ์ไว้ในห้องแชทที่เปิดอยู่แล้ว ยังไม่ได้กดส่ง"
    ok, info = _send_in_chat(key, text, ctx)
    return "ส่งในห้องแชทที่เปิดอยู่แล้ว ✅" if ok else f"ERROR: พิมพ์แล้วแต่กดส่งไม่สำเร็จ ({info})"


def clean_name(to):
    """'แล้วไปที่แชทชื่อว่า HAT' → 'HAT' (ตัดคำพูดนำหน้าที่ติดมากับชื่อ)"""
    t = " ".join((to or "").split())
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"^(?:แล้ว(?:ก็)?|ไปที่|ไป|เข้า(?:ไป)?|ห้อง|แชท|แชต|แชร์|ของ|กับ|หา|ให้|ถึง|คุณ|ชื่อว่า|ชื่อ|ที่ชื่อ|"
                   r"คนที่ชื่อ|คนชื่อ|ว่า)\s*", "", t).strip()
    return t.strip(" \"'“”")


def _reply_via_notification(app, to, text):
    """คนนี้มีแจ้งเตือนแชทค้างอยู่ (เพิ่งทักมา) → ตอบผ่านปุ่ม "ตอบกลับ" เลย: เร็ว ไม่ต้องเปิดแอป ไม่ส่งผิดห้อง"""
    if not config.ANDROID_APP:
        return None
    try:
        import android_shim
        import contacts
        b = android_shim.bridge()
        if not b.notifOn():
            return None
        want = contacts.norm(to)
        app_key = contacts.APP_WORDS.get(app.lower()) and app.lower()
        for n in json.loads(str(b.notifications()) or "[]"):
            if not n.get("can_reply") or n.get("is_group"):
                continue
            napp = contacts.APP_KEYS.get(n.get("packageName", ""))
            if not napp or (app_key and napp != app_key and app.lower() not in napp):
                continue
            who = contacts.norm(re.sub(r"\s*\(\d+.*\)$", "", n.get("sender") or n.get("title") or ""))
            if who and len(want) >= 2 and (who == want or (len(want) >= 3 and (want in who or who in want))):
                if b.notifReply(n.get("key", ""), text):
                    try:
                        import autoreply
                        autoreply._remember_out(text)      # กันระบบตอบกลับอัตโนมัติอ่านเป็นข้อความเข้าใหม่
                    except Exception:  # noqa: BLE001
                        pass
                    contacts.learn(to, n.get("packageName", ""), "sent")
                    return f"ส่งหา {to} ใน {napp} แล้ว ✅ (ตอบผ่านแจ้งเตือน): {text}"
    except Exception as e:  # noqa: BLE001
        print(f"[dm] ตอบผ่านแจ้งเตือนไม่ได้: {e}", flush=True)
    return None


def send_dm(a, ctx):
    t0 = time.time()
    if _echo_text(a.get("text") or ""):
        print(f"[dm] 🛑 ไม่ส่ง: ข้อความเหมือนถอดเสียงผิด {a.get('text', '')[:80]!r}", flush=True)
        return ECHO_REFUSE
    quick = _reply_via_notification((a.get("app") or "").strip(), clean_name(a.get("to") or ""),
                                    (a.get("text") or "").strip()) if a.get("text") and a.get("to") else None
    if quick:
        print(f"[dm] ⏱️ ใช้เวลา {time.time() - t0:.1f} วิ (ผ่านแจ้งเตือน)", flush=True)
        return quick
    res = _send_dm(a, ctx)
    print(f"[dm] ⏱️ ใช้เวลา {time.time() - t0:.1f} วิ", flush=True)
    return res


def _send_dm(a, ctx):
    """ส่งข้อความแชทหาคน: เปิดแอป → เข้าห้องแชทของคนนั้น → พิมพ์ → กดส่ง (บอกผลตามจริงทุกขั้น)"""
    import phone_tools
    import screen_tools
    app = (a.get("app") or "").strip()
    to = clean_name(a.get("to") or "")
    text = (a.get("text") or "").strip()
    if not (app and to and text):
        return "ERROR: ต้องมี app, to (ชื่อ/username ผู้รับ) และ text"
    if not _adb():
        return screen_tools.NOT_CONNECTED
    key = phone_tools.ALIASES.get(app.lower(), app).lower()
    steps = []
    in_chat = False
    hit = None
    # 1) username → ลิงก์ตรงเข้าห้องแชท
    if key in DM_LINKS and _is_username(to):
        ok, out = phone_tools._open_link(DM_LINKS[key].format(u=to.lstrip("@")))
        steps.append(f"เปิดห้องแชท @{to.lstrip('@')} ด้วยลิงก์" if ok else f"ลิงก์ห้องแชทใช้ไม่ได้ ({out[:60]})")
        if ok:
            time.sleep(1.2)
            in_chat = _wait_items(lambda it: _composer(it) is not None, timeout=9) is not None
    # 1.5) ผู้ใช้เปิดห้องแชทค้างไว้อยู่แล้ว → ถ้าเป็นห้องของคนนี้ พิมพ์เลย / ถ้าห้องคนอื่น ย้อนออกก่อน (กันส่งผิดคน)
    skip_open = False
    if not in_chat:
        state = _current_chat(key, to)
        if state == "same":
            in_chat = True
            steps.append(f"อยู่ในห้องแชทของ {to} อยู่แล้ว")
        elif state == "other":
            steps.append("ออกจากห้องแชทเดิม")
            skip_open = _leave_chat()
    # 2) เปิดหน้ารวมแชท แล้วค้นหาชื่อ
    if not in_chat:
        if not skip_open:
            res = phone_tools.open_app({"app": key, "page": "chat"}, ctx)
            steps.append(res[:80])
            if res.startswith("ERROR"):
                return f"ERROR: เปิด {app} ไม่ได้ — ยังไม่ได้ส่ง ({res[:150]})"
            time.sleep(1.0)
            if phone_tools.still_home():             # แอปไม่ขึ้นจริง (จอยังเป็นหน้าโฮม/หน้าแอปล่าสุด) → กดโฮมแล้วเปิดใหม่อีกครั้ง
                print(f"[dm] เปิด {app} แล้วจอยังเป็นหน้าโฮม → ลองอีกครั้ง", flush=True)
                screen_tools.adb_shell(["input", "keyevent", "3"])
                time.sleep(0.6)
                res = phone_tools.open_app({"app": key, "page": "chat"}, ctx)
                steps.append("เปิดซ้ำ: " + res[:60])
                time.sleep(1.0)
                if res.startswith("ERROR") or phone_tools.still_home(wait=1.5):
                    return (f"ERROR: เปิด {app} ไม่ขึ้น (จอยังเป็นหน้าโฮม) — ยังไม่ได้ส่ง "
                            f"ลองแตะไอคอน {app} เองครั้งหนึ่งแล้วสั่งใหม่")
        try:
            hit = _pick_recipient(to, key)
        except RuntimeError as e:
            return f"ERROR: {e} — ยังไม่ได้ส่ง (ขั้นที่ทำแล้ว: {' → '.join(steps)})"
        if not hit:
            seen = _visible_names()
            print(f"[dm] หา '{to}' ไม่เจอ บนจอมี: {seen}", flush=True)
            return (f"ERROR: เข้าหน้าแชทของ {app} แล้ว แต่หาคนชื่อ '{to}' ไม่เจอ — ยังไม่ได้ส่ง "
                    f"(ชื่อที่เห็นบนจอ: {seen or 'อ่านไม่ได้'} — บอกชื่อให้ตรงกับนี้ หรือใช้ username)")
        steps.append(f"แตะ {hit['text'] or hit['desc']}")
        if not _wait_items(lambda it: _composer(it) is not None, timeout=6):
            # แตะแล้วไม่ได้เข้าห้องแชท (เช่น ไปเปิดสตอรี่/โปรไฟล์) → ย้อนกลับ เข้ากล่องข้อความ แล้วลองอีกรอบ
            try:
                _dump_log("แตะชื่อแล้วไม่เจอช่องพิมพ์", _items())
            except RuntimeError:
                pass
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(1.0)
            try:
                items, reached = _reach_inbox(key, to, _items())
                hit2 = _pick_recipient(to, key) if reached else None
            except RuntimeError:
                hit2 = None
            if hit2:
                steps.append(f"ลองใหม่ในกล่องข้อความ → แตะ {hit2['text'] or hit2['desc']}")
                hit = hit2
                _wait_items(lambda it: _composer(it) is not None, timeout=6)
    # 3) พิมพ์ + ส่ง
    try:
        items = _items()
    except RuntimeError as e:
        return f"ERROR: {e} — ยังไม่ได้ส่ง (ขั้นที่ทำแล้ว: {' → '.join(steps)})"
    box = _composer(items)
    if not box:
        _dump_log("หาช่องพิมพ์ไม่เจอ", items)
        return f"ERROR: เข้าห้องแชทแล้วแต่หาช่องพิมพ์ไม่เจอ — ยังไม่ได้ส่ง (ขั้นที่ทำแล้ว: {' → '.join(steps)})"
    screen_tools.adb_shell(["input", "tap", str(box["x"]), str(box["y"])])
    time.sleep(0.6)
    _clear_box(box)                                 # ล้างข้อความค้างในช่องพิมพ์ (กันข้อความต่อกันมั่ว)
    res = screen_tools.type_text({"text": text, "send": False}, ctx)
    steps.append("พิมพ์แล้ว")
    if res.startswith("ERROR"):
        return f"ERROR: {res[6:].strip()} — ยังไม่ได้ส่ง ({' → '.join(steps)})"
    if not a.get("send", True) or getattr(ctx, "hold", False):
        return f"พิมพ์ข้อความไว้ในห้องแชทของ {to} แล้ว ยังไม่ได้กดส่ง ({' → '.join(steps)})"
    ok, info = _send_in_chat(key, text, ctx)
    steps.append(info)
    if ok:
        try:
            import skills
            skills.set_pref("dm_app", key)          # ครั้งหน้าไม่บอกแอป → ใช้แอปนี้
            shown = (hit.get("text") or hit.get("desc") or "").split(",")[0].strip() if hit else ""
            if shown:
                skills.add_names([shown])
            if shown and _loose(shown) != _loose(to):
                skills.set_pref(f"alias:{key}:{_loose(to)}", shown)   # จำว่า "ภรรยาคนเจ็ด" = "ภรรยา(คนเจก)"
            import contacts
            contacts.learn(shown or to, key, "sent")       # ครั้งหน้า "ส่งหา…" ไม่ต้องบอกแอป
            if shown and _loose(shown) != _loose(to):
                contacts.learn(to, key, "sent")
        except Exception:  # noqa: BLE001
            pass
        return f"ส่งข้อความหา {to} ใน {app} แล้ว ✅ ({' → '.join(steps)})"
    return f"ERROR: พิมพ์แล้วแต่กดส่งไม่สำเร็จ ({info}) — ข้อความค้างอยู่ในช่องพิมพ์ ({' → '.join(steps)})"


_MEDIA = re.compile(r"กล้อง|camera|ไมค์|mic|voice|เสียง|gallery|แกลเลอรี|รูป|photo|sticker|สติ๊กเกอร์|สติกเกอร์|"
                    r"gif|emoji|อีโมจิ|like|ถูกใจ|หัวใจ|heart|\+|เพิ่ม|add|ai|meta", re.I)


def _is_send_label(e):
    for v in (e["text"].strip().lower(), e["desc"].strip().lower()):
        if v in _SEND_EXACT or (len(v) < 25 and v.startswith(("send", "ส่ง"))):
            return True
    return "send" in e["id"].lower()


def _send_candidates(items, comp):
    """ปุ่มส่งต้องอยู่แถวเดียวกับช่องพิมพ์ (ไม่ใช่ชื่อคน/รูปโปรไฟล์ด้านบน ซึ่งกดแล้วไปหน้าโปรไฟล์)"""
    hh = max(70, comp["box"][3] - comp["box"][1])
    row = [e for e in items if not e["edit"] and e["click"] and abs(e["y"] - comp["y"]) <= hh
           and e["x"] > comp["box"][0]]
    named = [e for e in row if _is_send_label(e)]
    right = sorted([e for e in row if e not in named and e["x"] >= comp["box"][2] - 40
                    and not _MEDIA.search(e["text"] + " " + e["desc"] + " " + e["id"])],
                   key=lambda e: e["x"] - comp["box"][2])
    return named + right[:1]


def _verify_sent(msg):
    """ส่งจริงไหม: ช่องพิมพ์ต้องว่าง (ข้อความหายไปจากช่อง) และยังอยู่ในห้องแชท"""
    try:
        items = _items()
    except RuntimeError:
        return False, "อ่านจอไม่ได้"
    comp = _composer(items)
    if not comp:
        return False, "left"
    if msg.strip()[:10] and msg.strip()[:10] in comp["text"]:
        return False, "still"
    return True, "ok"


def _send_in_chat(app, msg, ctx):
    """กดส่งในห้องแชท + ตรวจว่าส่งจริง | จำปุ่มที่ใช้ได้ไว้ใช้ครั้งหน้า (สกิล)"""
    import permissions
    import screen_tools
    import skills
    if ctx is not None and permissions.need_confirm(ctx, "message") and \
            not ctx.confirm(f"กดส่งข้อความใน {app}: {msg[:80]}"):
        return False, "ผู้ใช้ไม่อนุญาตให้ส่ง"
    try:
        items = _items()
    except RuntimeError as e:
        return False, str(e)
    comp = _composer(items)
    if not comp:
        return False, "หาช่องพิมพ์ไม่เจอ"
    learned = skills.ui_match(app, "send", items)
    cands = ([learned] if learned else []) + _send_candidates(items, comp)
    tried = set()
    for e in cands:
        if (e["x"], e["y"]) in tried or len(tried) >= 3:
            continue
        tried.add((e["x"], e["y"]))
        print(f"[dm] กดส่ง: {(e['text'] or e['desc'] or e['id'])!r} @{e['x']},{e['y']}", flush=True)
        screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
        time.sleep(0.6)
        ok, why = _verify_sent(msg)
        if ok:
            skills.ui_learn(app, "send", e)
            return True, f"กดส่งแล้ว (ปุ่ม {e['text'] or e['desc'] or e['id'] or 'ขวาของช่องพิมพ์'})"
        if e is learned:
            skills.ui_forget(app, "send")
        if why == "left":                         # กดแล้วไปหน้าอื่น (เช่น โปรไฟล์) → ย้อนกลับมาห้องแชท
            print("[dm] กดแล้วออกจากห้องแชท → ย้อนกลับ", flush=True)
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(1.0)
    v = screen_tools.vision_find("ปุ่มส่งข้อความ (อยู่ข้างช่องพิมพ์ข้อความด้านล่าง)")   # มองภาพหาปุ่มส่ง
    if v and (v["x"], v["y"]) not in tried:
        print(f"[dm] กดส่ง (มองภาพ): {v['text']!r} @{v['x']},{v['y']}", flush=True)
        screen_tools.adb_shell(["input", "tap", str(v["x"]), str(v["y"])])
        time.sleep(1.0)
        ok, why = _verify_sent(msg)
        if ok:
            return True, "กดส่งแล้ว (หาปุ่มด้วยการมองภาพ)"
        if why == "left":
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(1.0)
    screen_tools.adb_shell(["input", "keyevent", "66"])        # สุดท้าย: ปุ่ม Enter
    time.sleep(1.0)
    ok, why = _verify_sent(msg)
    if ok:
        return True, "กดส่งแล้ว (Enter)"
    try:
        _dump_log("กดส่งไม่สำเร็จ", _items())
    except RuntimeError:
        pass
    return False, "หาปุ่มส่งไม่เจอ/กดแล้วข้อความยังค้าง"


def prepare_upload(a, ctx):
    """เตรียมไฟล์ให้อัปโหลดในแอปไหนก็ได้: คัดลอกไปที่ส่วนกลาง ขึ้นเป็นไฟล์ล่าสุดในหน้าเลือกไฟล์/แกลเลอรี"""
    p = resolve(a.get("file") or "")
    if not p:
        return f"ERROR: ไม่พบไฟล์ '{a.get('file')}' — ใช้ find_files ค้นหาก่อน"
    if _blocked(p):
        return "ERROR: ไฟล์นี้เป็นไฟล์ระบบ/ข้อมูลลับ อัปโหลดไม่ได้"
    try:
        dst, uri = publish(p)
    except RuntimeError as e:
        return f"ERROR: {e}"
    name = os.path.basename(dst)
    return (f"พร้อมอัปโหลดแล้ว: {name} อยู่ที่ {os.path.dirname(dst).replace(SHARED + '/', '')} "
            f"(เป็นไฟล์ล่าสุดในแกลเลอรี/หน้าเลือกไฟล์)\n"
            f"ขั้นต่อไป: ในแอปกดปุ่มอัปโหลด/แนบไฟล์/รูป (tap_text) → เลือก 'ล่าสุด'/'Recent' หรือโฟลเดอร์ AIBot "
            f"→ tap_text '{name[:30]}' (รูปในแกลเลอรีมักเป็นภาพแรกซ้ายบน) → กดเลือก/ส่ง/อัปโหลด")


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_FILES = {"type": "array", "items": {"type": "string"},
          "description": "path ไฟล์/รูป/คลิป หรือ 'รูปล่าสุด' 'คลิปล่าสุด' 'ไฟล์ล่าสุด' (รวมที่ผู้ใช้เพิ่งส่งมาทาง Telegram)"}

TOOLS = {
    "send_to_app": (send_to_app,
                    "ส่งรูป/วิดีโอ/ไฟล์/ข้อความ เข้าแอปไหนก็ได้ (LINE, Messenger, Facebook, IG, TikTok, YouTube, Drive, "
                    "Gmail, Telegram, Claude ฯลฯ) ใส่ to = ชื่อผู้รับ/ห้องแชท ระบบจะค้นหา แตะ และกดส่งให้เอง "
                    "(send=false = เปิดหน้าส่งค้างไว้ไม่กดส่ง, read_reply=true = รอแล้วอ่านคำตอบบนจอ)",
                    _obj({"app": {"type": "string"}, "files": _FILES, "text": {"type": "string"},
                          "to": {"type": "string"}, "send": {"type": "boolean"},
                          "read_reply": {"type": "boolean"}, "wait": {"type": "integer"}}, ["app"]), False),
    "ask_ai_app": (ask_ai_app,
                   "สั่งแอป AI ในเครื่อง (claude / chatgpt / gemini): พิมพ์ข้อความ แนบรูป/ไฟล์ ส่ง แล้วอ่านคำตอบกลับมา",
                   _obj({"app": {"type": "string", "enum": ["claude", "chatgpt", "gemini"]},
                         "text": {"type": "string"}, "files": _FILES,
                         "read_reply": {"type": "boolean"}, "wait": {"type": "integer",
                                                                    "description": "วินาทีที่รอคำตอบ (ค่าเริ่ม 20)"}},
                        ["text"]), False),
    "send_dm": (send_dm,
                "ส่งข้อความแชทหาคน ในแอป Instagram/Messenger/LINE/Facebook/Telegram ฯลฯ ทำครบทุกขั้นให้เอง "
                "(เปิดแอป → เข้าห้องแชทของคนนั้น → พิมพ์ → กดส่ง) to = ชื่อที่แสดงในแอป หรือ username",
                _obj({"app": {"type": "string"}, "to": {"type": "string"}, "text": {"type": "string"},
                      "send": {"type": "boolean"}}, ["app", "to", "text"]), False),
    "prepare_upload": (prepare_upload,
                       "เตรียมไฟล์ให้อัปโหลดผ่านปุ่มอัปโหลด/แนบไฟล์ของแอปไหนก็ได้ (เว็บ/ฟอร์ม/แอปที่ไม่รับการแชร์)",
                       _obj({"file": {"type": "string"}}, ["file"]), False),
}
