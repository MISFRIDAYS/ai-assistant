"""ทักษะสำเร็จรูปของแอปยอดนิยม — ทำงานแบบตายตัว (ไม่ต้องให้ AI เดากดทีละปุ่ม → เร็วและแม่นกว่า)

- เปิดเพลง/คลิป: "เปิดเพลง ลาลาลอย" · "เล่น lofi ใน youtube" · "ฟังเพลง xxx ใน spotify"
- ค้นหาในแอป: "หา รองเท้าวิ่ง ใน shopee" · "ค้นหา แมว ใน tiktok"
- นำทาง: "นำทางไป เซ็นทรัลเวิลด์"
- คู่มือการใช้แต่ละแอป (ส่งให้ AI เป็นแผนที่ตอนต้องกดเองในแอป)
"""
import re
import time
import urllib.parse

# แอป → (ลิงก์ค้นหา, package)
SEARCH = {
    "youtube": ("https://www.youtube.com/results?search_query={q}", "com.google.android.youtube"),
    "youtube music": ("https://music.youtube.com/search?q={q}", "com.google.android.apps.youtube.music"),
    "spotify": ("spotify:search:{q}", "com.spotify.music"),
    "google": ("https://www.google.com/search?q={q}", None),
    "chrome": ("https://www.google.com/search?q={q}", "com.android.chrome"),
    "maps": ("geo:0,0?q={q}", "com.google.android.apps.maps"),
    "shopee": ("https://shopee.co.th/search?keyword={q}", "com.shopee.th"),
    "lazada": ("https://www.lazada.co.th/catalog/?q={q}", "com.lazada.android"),
    "tiktok": ("https://www.tiktok.com/search?q={q}", "com.ss.android.ugc.trill"),
    "facebook": ("https://www.facebook.com/search/top/?q={q}", "com.facebook.katana"),
    "x": ("https://x.com/search?q={q}", "com.twitter.android"),
    "wikipedia": ("https://th.wikipedia.org/w/index.php?search={q}", None),
    "play store": ("market://search?q={q}", "com.android.vending"),
}
NAMES = {
    "ยูทูป": "youtube", "ยูทูบ": "youtube", "ยูทู้ป": "youtube", "yt": "youtube", "youtube": "youtube",
    "ยูทูปมิวสิค": "youtube music", "youtube music": "youtube music", "yt music": "youtube music",
    "spotify": "spotify", "สปอติฟาย": "spotify", "สปอตติฟาย": "spotify",
    "google": "google", "กูเกิล": "google", "กูเกิ้ล": "google", "chrome": "chrome", "โครม": "chrome",
    "maps": "maps", "แผนที่": "maps", "google maps": "maps", "กูเกิลแมพ": "maps",
    "shopee": "shopee", "ช้อปปี้": "shopee", "ชอปปี้": "shopee", "lazada": "lazada", "ลาซาด้า": "lazada",
    "tiktok": "tiktok", "ติ๊กต็อก": "tiktok", "ติ๊กตอก": "tiktok", "facebook": "facebook", "เฟส": "facebook",
    "เฟสบุ๊ค": "facebook", "เฟซบุ๊ก": "facebook", "x": "x", "ทวิตเตอร์": "x", "twitter": "x",
    "wikipedia": "wikipedia", "วิกิ": "wikipedia", "play store": "play store", "เพลย์สโตร์": "play store",
}

# วิธีใช้แอปแบบย่อ (ให้ AI รู้ว่าปุ่มอยู่ตรงไหน ทำอะไรได้)
KNOWLEDGE = {
    "youtube": "ค้นหา=แว่นขยายมุมขวาบน · ผลค้นหาเรียงลงมา แตะรูปปกเพื่อเล่น (ข้ามอันที่เขียนว่า โฆษณา/Sponsored) · "
               "แตะกลางวิดีโอ=แสดงปุ่มหยุด/เล่น · Shorts=แท็บล่าง · ทางลัด: เครื่องมือ play_media",
    "line": "แท็บล่าง: หน้าหลัก/แชท/... · แชท=ไอคอนกล่องข้อความ · ค้นหาเพื่อน=ช่องค้นหาบนสุดในแท็บแชท · "
            "พิมพ์=ช่องล่างสุดในห้องแชท · ส่ง=ปุ่มลูกศร/เครื่องบินกระดาษขวาของช่องพิมพ์ · ส่งรูป=ไอคอนรูปภาพข้างช่องพิมพ์",
    "instagram": "DM=ไอคอนเครื่องบินกระดาษ/Messenger มุมขวาบนของหน้าหลัก · ค้นหา=แว่นขยายแถบล่าง · "
                 "ห้องแชท: ช่อง 'ข้อความ...' ล่างสุด ปุ่ม 'ส่ง' ขวา · โพสต์=ปุ่ม + แถบล่าง",
    "facebook": "ค้นหา=แว่นขยายบนขวา · แชท=ไอคอน Messenger บนขวา (เปิดแอป Messenger) · แจ้งเตือน=รูปกระดิ่ง",
    "messenger": "แชท=หน้าแรก · ค้นหา=ช่องค้นหาบนสุด · พิมพ์=ช่อง Aa ล่าง · ส่ง=ลูกศร/ไลก์ขวาล่าง",
    "tiktok": "ฟีด=ปัดขึ้นดูคลิปถัดไป · ค้นหา=แว่นขยายบนขวา · ข้อความ=แท็บกล่องข้อความแถบล่าง",
    "chrome": "ช่องที่อยู่บนสุด พิมพ์แล้วกด Enter เพื่อค้นหา · แท็บ=ปุ่มตัวเลขบนขวา · เมนู=⋮",
    "gmail": "เขียน=ปุ่มดินสอขวาล่าง · ถึง/เรื่อง/เนื้อหา=ช่องบนลงล่าง · ส่ง=ปุ่มลูกศรบนขวา",
    "wps office": "สร้างไฟล์=ปุ่ม + สีแดง (เอกสาร/สเปรดชีต/งานนำเสนอ/PDF) · เปิดไฟล์=แท็บล่าสุด/เปิด · "
                  "บันทึก=ไอคอนแผ่นดิสก์ · แก้ไข=ปุ่ม แก้ไข/Edit · ส่งออก PDF=ไฟล์ > ส่งออกเป็น PDF",
    "settings": "ช่องค้นหาการตั้งค่าบนสุด พิมพ์ชื่อการตั้งค่าที่ต้องการแล้วแตะผลลัพธ์ (เร็วสุด)",
    "camera": "ถ่าย=ปุ่มวงกลมใหญ่ · สลับกล้องหน้า/หลัง=ไอคอนลูกศรวน · วิดีโอ=เลื่อนโหมดเป็น วิดีโอ",
    "gallery": "อัลบั้ม/รูปภาพ แท็บบน · แตะรูปเพื่อดู · แชร์=ไอคอนแชร์ล่าง",
    "shopee": "ค้นหา=ช่องบนสุด · ตะกร้า=ไอคอนรถเข็นบนขวา · ห้ามกดสั่งซื้อ/ชำระเงินเองโดยไม่ขออนุญาต",
    "lazada": "ค้นหา=ช่องบนสุด · ตะกร้า=แถบล่าง · ห้ามกดชำระเงินเองโดยไม่ขออนุญาต",
    "maps": "ค้นหา=ช่องบนสุด · เส้นทาง=ปุ่ม เส้นทาง · เริ่ม=ปุ่ม เริ่ม · ทางลัด: เครื่องมือ navigate",
    "telegram": "แชท=รายการหน้าแรก · ค้นหา=แว่นขยายบนขวา · พิมพ์=ช่อง ข้อความ ล่าง · ส่ง=ลูกศรขวา",
    "spotify": "ค้นหา=แท็บ ค้นหา แถบล่าง · เล่น=ปุ่มวงกลมเขียว",
    "clock": "ปลุก=แท็บ นาฬิกาปลุก · เพิ่ม=ปุ่ม + · ตัวจับเวลา=แท็บ ตัวจับเวลา",
    "calculator": "กดตัวเลขบนแป้น ผลลัพธ์อยู่บนสุด",
}
_KNOW_ALIASES = {"ไลน์": "line", "ไอจี": "instagram", "อินสตาแกรม": "instagram", "ig": "instagram", "เฟส": "facebook",
                 "เมสเซนเจอร์": "messenger", "wps": "wps office", "ตั้งค่า": "settings", "กล้อง": "camera",
                 "แกลเลอรี่": "gallery", "รูปภาพ": "gallery", "นาฬิกา": "clock", "เครื่องคิดเลข": "calculator",
                 "เทเลแกรม": "telegram", "ยูทูป": "youtube", "ยูทูบ": "youtube", "ติ๊กต็อก": "tiktok",
                 "จีเมล": "gmail", "โครม": "chrome", "แผนที่": "maps", "ช้อปปี้": "shopee", "ลาซาด้า": "lazada"}


def knowledge(text):
    """คู่มือย่อของแอปที่พูดถึงในคำสั่ง"""
    t = (text or "").lower()
    out = []
    for k, v in KNOWLEDGE.items():
        if k in t:
            out.append(f"[วิธีใช้ {k}] {v}")
    for a, k in _KNOW_ALIASES.items():
        if a in t and not any(f"[วิธีใช้ {k}]" in o for o in out):
            out.append(f"[วิธีใช้ {k}] {KNOWLEDGE[k]}")
    return "\n".join(out[:3])


# ================================================================ ลงมือ

def _installed(pkg):
    if not pkg:
        return False
    try:
        import phone_tools
        return any(c.split("/")[0] == pkg for c in phone_tools._launcher_components())
    except Exception:  # noqa: BLE001
        return True


def _view(url, pkg=None):
    import phone_tools
    args = ["am", "start", "-a", "android.intent.action.VIEW", "-d", url]
    if pkg and _installed(pkg):
        args += ["-p", pkg]
    out = phone_tools._sh(args, quote=True)
    if not phone_tools._launch_ok(out) and pkg:                     # แอปไม่รับลิงก์ → เปิดด้วยเบราว์เซอร์
        out = phone_tools._sh(args[:6], quote=True)
    return phone_tools._launch_ok(out), out


def search(app, query, ctx=None):
    key = NAMES.get(app.strip().lower(), app.strip().lower())
    if key not in SEARCH:
        return None
    url, pkg = SEARCH[key]
    ok, out = _view(url.format(q=urllib.parse.quote(query.strip())), pkg)
    return f"เปิดผลค้นหา \"{query}\" ใน {key} แล้ว 🔎" if ok else f"ERROR: เปิด {key} ไม่ได้ ({out[:80]})"


_VIDEO = re.compile(r"(นาที|วินาที|ชั่วโมง|minute|second|hour|ยอดดู|views?|ครั้ง|เล่นวิดีโอ|play video|\d+:\d\d)", re.I)
_AD = re.compile(r"(โฆษณา|ได้รับการสนับสนุน|sponsored|\bad\b|ads)", re.I)


def _first_video(items, h):
    cands = []
    for e in items:
        d = (e.get("desc") or e.get("text") or "")
        if not d or _AD.search(d) or e["y"] < h * 0.12:
            continue
        if _VIDEO.search(d) and (e.get("click") or len(d) > 25):
            cands.append(e)
    return min(cands, key=lambda e: e["y"]) if cands else None


def play(query, app="youtube", ctx=None):
    """ค้นหาแล้วเล่นอันแรกทันที (ไม่ใช่โฆษณา)"""
    import screen_tools
    key = NAMES.get((app or "youtube").strip().lower(), "youtube")
    if key in ("spotify", "youtube music"):
        return search(key, query, ctx) + " — แตะเพลงที่ต้องการได้เลย"
    if not screen_tools.adb_serial():
        return search("youtube", query, ctx) + " (คุมจอไม่ได้ เลยกดเล่นให้ไม่ได้)"
    url, pkg = SEARCH["youtube"]
    ok, out = _view(url.format(q=urllib.parse.quote(query.strip())), pkg)
    if not ok:
        return f"ERROR: เปิด YouTube ไม่ได้ ({out[:80]})"
    for i in range(8):                                    # รอผลค้นหาโหลด
        time.sleep(1.0 if i else 2.0)
        try:
            root = screen_tools._dump()
            w, h = screen_tools._screen_size(root)
            items = screen_tools._elements(root)
        except Exception:  # noqa: BLE001
            continue
        v = _first_video(items, h)
        if v:
            screen_tools.adb_shell(["input", "tap", str(v["x"]), str(v["y"])])
            title = re.split(r"\s[-–—]\s|,", (v.get("desc") or v.get("text") or ""))[0][:70]
            return f"▶️ กำลังเล่น: {title}"
    return (f"เปิดผลค้นหา \"{query}\" ใน YouTube แล้ว แต่หาคลิปที่จะกดเล่นไม่เจอ — "
            "แตะคลิปที่ต้องการได้เลย หรือสั่ง 'แตะคลิปแรก'")


def navigate(place, ctx=None):
    q = urllib.parse.quote(place.strip())
    if _installed("com.google.android.apps.maps"):
        ok, out = _view(f"google.navigation:q={q}", "com.google.android.apps.maps")
        if ok:
            return f"🧭 เริ่มนำทางไป {place} แล้ว"
    ok, out = _view(f"geo:0,0?q={q}")
    return f"🗺️ เปิดแผนที่ค้นหา {place} แล้ว" if ok else f"ERROR: เปิดแผนที่ไม่ได้ ({out[:80]})"


# ================================================================ คำสั่งตรง (ไม่ต้องผ่าน AI)

_APPS_RX = "|".join(sorted((re.escape(k) for k in NAMES), key=len, reverse=True))
_TAIL = r"(?:\s*(?:ให้หน่อย|หน่อย|ให้ที|ที|ครับ|ค่ะ|คะ|นะ|ด้วย))*\s*$"
_PLAY = re.compile(r"^(?:ช่วย)?\s*(?:อยากฟัง|อยากดู|เปิด|เล่น|ฟัง|หา|ขอ)\s*(?:เพลง|คลิป|วิดีโอ|วีดีโอ|mv|เอ็มวี)\s*(?P<q>.+?)"
                   r"(?:\s*(?:ใน|บน|ที่|จาก|ด้วย)\s*(?P<app>" + _APPS_RX + r"))?" + _TAIL, re.I)
_YT = re.compile(r"^(?:เปิด|เข้า)?\s*(?P<app>ยูทูป|ยูทูบ|youtube|spotify|สปอติฟาย)\s*(?:แล้ว)?\s*"
                 r"(?:หา|ค้นหา|เปิด|เล่น)\s*(?:เพลง|คลิป)?\s*(?P<q>.+?)" + _TAIL, re.I)
_SEARCH = re.compile(r"^(?:ช่วย)?\s*(?:หา|ค้นหา|ค้น|เสิร์ช)\s*(?P<q>.+?)\s*(?:ใน|บน|ที่|จาก)\s*(?P<app>" + _APPS_RX + r")" + _TAIL, re.I)
_NAV = re.compile(r"^(?:ช่วย)?\s*(?:นำทาง|เส้นทาง|พา)\s*ไป\s*(?:ที่)?\s*(?P<q>.+?)" + _TAIL, re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    if not t or len(t) > 120:
        return None
    m = _PLAY.match(t) or _YT.match(t)
    if m:
        q = re.sub(r"\s*(?:แล้ว)?\s*(?:เล่น|เปิด|กด)\s*(?:คลิป|อัน|เพลง)?\s*(?:แรก|ที่\s*1)?\s*(?:เลย|ให้ฟัง|ให้ดู)?$", "", m.group("q")).strip()
        if len(q) >= 2 and not re.fullmatch(r"(ใน|บน)?\s*(ยูทูป|ยูทูบ|youtube)", q, re.I):
            return play(q, (m.group("app") or "youtube"), ctx)
    m = _SEARCH.match(t)
    if m:
        return search(m.group("app"), m.group("q"), ctx)
    m = _NAV.match(t)
    if m:
        return navigate(m.group("q"), ctx)
    return None


# ================================================================ เครื่องมือให้ AI ใช้

def _obj(props, req):
    return {"type": "object", "properties": props, "required": req}


TOOLS = {
    "play_media": (lambda a, ctx: play(a.get("query") or "เพลงฮิต", a.get("app", "youtube"), ctx),
                   "เปิดเพลง/คลิปทันที (ค้นหาแล้วกดเล่นอันแรกให้เอง) app: youtube (ค่าเริ่มต้น) / spotify / youtube music",
                   _obj({"query": {"type": "string"}, "app": {"type": "string"}}, ["query"]), False),
    "search_in_app": (lambda a, ctx: search(a.get("app", "google"), a.get("query", ""), ctx) or f"ไม่รู้จักแอป {a.get('app')}",
                      "เปิดหน้าผลค้นหาในแอปตรงๆ: " + ", ".join(SEARCH),
                      _obj({"app": {"type": "string"}, "query": {"type": "string"}}, ["app", "query"]), False),
    "navigate": (lambda a, ctx: navigate(a.get("place", ""), ctx), "นำทางไปสถานที่ด้วยแผนที่",
                 _obj({"place": {"type": "string"}}, ["place"]), False),
}
