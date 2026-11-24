"""รู้จักเครื่อง Huawei MatePad 11.5 (TXZ-W09 · HarmonyOS 4.3) + ควบคุมการตั้งค่าเกือบทุกอย่าง

- "ข้อมูลเครื่อง" / "สเปคเครื่อง"          → สเปค + สถานะสด (แบต แรม พื้นที่ Wi-Fi ฯลฯ)
- "พื้นที่เหลือเท่าไหร่" / "แรมเหลือเท่าไหร่"
- "เปิด/ปิด โหมดมืด|ถนอมสายตา|ประหยัดพลังงาน|..." → เข้าแอปตั้งค่า ค้นหา แล้วแตะสวิตช์ให้ (ตรวจผลจริง)
- "เปิดหน้าตั้งค่า <อะไรก็ได้>"             → ค้นในแอปตั้งค่าแล้วเปิดหน้านั้นให้
- "แท็บเล็ตนี้ทำอะไรได้บ้าง" / "วิธีแบ่งจอ" → ความรู้เฉพาะรุ่น
ไม่แตะ: รหัสผ่าน/ล็อกหน้าจอ/ลายนิ้วมือ/บัญชี/รีเซ็ต/ล้างข้อมูล
"""
import json
import os
import re
import time

import config

SPEC = {
    "รุ่น": "HUAWEI MatePad 11.5 (2025) · TXZ-W09 (Wi-Fi)",
    "ระบบ": "HarmonyOS 4.3 (รัน APK Android ได้ · Android API ~31)",
    "ชิป": "Kirin 8020 (8 คอร์ สูงสุด 2.29GHz) · GPU Maleoon 920",
    "แรม/ความจุ": "RAM 8GB · 128/256GB (ไม่มีช่อง microSD)",
    "จอ": "11.5\" 2456×1600 120Hz (มีรุ่น PaperMatte จอด้านถนอมสายตา)",
    "แบต": "10,100mAh · ชาร์จเร็ว 40W (HUAWEI SuperCharge)",
    "กล้อง": "หลัง 13MP AF · หน้า 8MP มุมกว้าง",
    "เสียง": "ลำโพง 4 ตัว · ไม่มีช่องหูฟัง 3.5mm",
    "เชื่อมต่อ": "Wi-Fi 6 · Bluetooth 5.2 · USB-C 2.0 (OTG) · พอร์ตแม่เหล็กสำหรับคีย์บอร์ด",
    "ไม่มี": "ซิม/เน็ตมือถือ · GPS แยก (ใช้ตำแหน่งจาก Wi-Fi) · NFC · สแกนนิ้ว",
    "อุปกรณ์เสริม": "HUAWEI M-Pencil · Smart Keyboard",
}

KNOWLEDGE = """ความรู้เครื่อง Huawei MatePad 11.5 (TXZ-W09, HarmonyOS 4.3):
- ไม่มีซิม/NFC/GPS แยก → อย่าสั่งเน็ตมือถือ/NFC/โทรออกด้วยซิม · ตำแหน่งได้จาก Wi-Fi
- แอปสโตร์ = AppGallery · ค้นหา = Petal Search · แผนที่ = Petal Maps · ไม่มี Google Play/บริการ Google ในตัว
- ปัดลงจากมุมขวาบน = แผงควบคุม (Wi-Fi/บลูทูธ/ห้ามรบกวน/หมุนจอ/ถนอมสายตา) · มุมซ้ายบน = การแจ้งเตือน
- แบ่งจอ/หน้าต่างลอย: ปัดเข้าจากขอบซ้ายหรือขวาค้างไว้ → แถบหน้าต่างหลายบาน → ลากแอปออกมา
- ถ่ายภาพหน้าจอ: ปุ่มเปิดปิด + ลดเสียง หรือเคาะข้อนิ้วสองครั้ง · บันทึกจอ: แผงควบคุม
- Huawei Share: ส่งไฟล์ไร้สายกับมือถือ/คอม Huawei · การทำงานร่วมกับ PC (Multi-screen Collaboration)
- โหมดคอม (PC mode) เมื่อต่อ Smart Keyboard · M-Pencil เขียนใน Notes/WPS ได้
- ตั้งค่าหลัก: จอและความสว่าง (โหมดมืด, ถนอมสายตา, อัตรารีเฟรช) · แบตเตอรี่ (โหมดประหยัดพลังงาน,
  โหมดประสิทธิภาพ) · เสียงและการสั่น · การแจ้งเตือน · ตัวช่วยการเข้าถึง · ระบบและการอัปเดต"""

# ชื่อการตั้งค่า → (คำค้นในแอปตั้งค่า (ไทย, อังกฤษ), ป้ายของสวิตช์)
SETTINGS = {
    r"โหมด\s*มืด|ธีม\s*มืด|dark\s*mode": (("โหมดมืด", "Dark mode"), r"โหมดมืด|Dark mode"),
    r"ถนอมสายตา|กรองแสงสีฟ้า|eye\s*comfort": (("ถนอมสายตา", "Eye Comfort"), r"ถนอมสายตา|Eye Comfort"),
    r"ประหยัด(?:พลังงาน|แบต)|power\s*sav": (("ประหยัดพลังงาน", "Power saving"), r"ประหยัดพลังงาน|Power saving"),
    r"โหมดประสิทธิภาพ|performance\s*mode": (("โหมดประสิทธิภาพ", "Performance mode"), r"ประสิทธิภาพ|Performance"),
    r"ความสว่างอัตโนมัติ|auto\s*brightness": (("ความสว่าง", "Brightness"), r"อัตโนมัติ|Automatic|Auto"),
    r"huawei\s*share|หัวเว่ยแชร์": (("Huawei Share",), r"Huawei Share"),
    r"(?:แถบ|ท่าเรือ)?หน้าต่างหลายบาน|multi.?window|แบ่งจอ": (("หน้าต่างหลายบาน", "Multi-Window"), r"หน้าต่างหลายบาน|Multi-Window|แถบ"),
    r"แถบลอย|ปุ่มลอย|navigation\s*dock": (("แถบนำทางแบบลอย", "Navigation dock"), r"ลอย|dock"),
    r"สัมผัสด้วยข้อนิ้ว|เคาะข้อนิ้ว|knuckle": (("ข้อนิ้ว", "Knuckle"), r"ข้อนิ้ว|Knuckle"),
    r"เสียงสัมผัส|เสียงแตะ|touch\s*sound": (("เสียงสัมผัส", "Touch sounds"), r"เสียง.*สัมผัส|Touch"),
    r"การสั่น|สั่นเมื่อแตะ|haptic": (("การสั่น", "Vibration"), r"สั่น|Vibrat|Haptic"),
    r"แจ้งเตือนบนหน้าจอล็อก|lock\s*screen\s*notif": (("การแจ้งเตือนบนหน้าจอล็อก",), r"หน้าจอล็อก|Lock screen"),
    r"อัปเดตอัตโนมัติ|auto.?update": (("อัปเดตอัตโนมัติ", "Auto-update"), r"อัตโนมัติ|Auto"),
    r"ตัวอักษรตัวหนา|bold\s*text": (("ตัวหนา", "Bold"), r"ตัวหนา|Bold"),
    r"เปิดหน้าจอค้าง|screen\s*always\s*on|always\s*on\s*display|aod": (("แสดงผลตลอดเวลา", "Always On Display"), r"ตลอดเวลา|Always"),
}

_DENY = re.compile(r"รหัส|password|ล็อก(?:หน้า)?จอ(?!.*แจ้งเตือน)|screen\s*lock|ลายนิ้ว|ใบหน้า|face|บัญชี|account|"
                   r"รีเซ็ต|reset|ล้างข้อมูล|ลบ|erase|format|ฟอร์แมต|ดีบัก|debug|นักพัฒนา|developer", re.I)


def _b():
    import android_shim
    return android_shim.bridge()


def _js(s, default):
    try:
        return json.loads(str(s))
    except (ValueError, TypeError):
        return default


def _gb(n):
    return f"{n / 1024 ** 3:.1f}GB"


# ================================================================ ข้อมูลเครื่อง

def storage():
    try:
        st = os.statvfs(config.DATA_DIR if os.path.isdir(config.DATA_DIR) else "/")
        return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    except OSError:
        return 0, 0


def live():
    """สถานะสด (เฉพาะในแอป)"""
    if not config.ANDROID_APP:
        return {}
    import android_shim
    b = _b()
    o = {"model": f"{b.prop('ro.product.manufacturer')} {b.prop('ro.product.model')}".strip(),
         "android": str(b.prop("ro.build.version.release"))}
    bat = _js(b.battery(), {})
    if bat:
        o["แบต"] = f"{bat.get('percentage')}% " + {"CHARGING": "กำลังชาร์จ", "FULL": "เต็ม"}.get(bat.get("status"), "") + \
            (f" · {bat.get('temperature')}°C" if bat.get("temperature") else "")
    mem = _js(b.memInfo(), {})
    if mem.get("total"):
        o["แรม"] = f"ว่าง {_gb(mem['avail'])} / {_gb(mem['total'])}"
    tot, free = storage()
    if tot:
        o["พื้นที่"] = f"ว่าง {_gb(free)} / {_gb(tot)}"
    wi = _js(b.wifiInfo(), {})
    ssid = str(wi.get("ssid") or "").strip('"')
    o["Wi-Fi"] = ("ต่อ " + ssid if ssid and "unknown" not in ssid else "เปิด (ยังไม่ต่อ)") if wi.get("enabled") else "ปิด"
    for k, lab in (("bluetooth", "บลูทูธ"), ("dnd", "ห้ามรบกวน"), ("rotate", "หมุนจอ"), ("airplane", "โหมดเครื่องบิน")):
        s = android_shim.sys_state(k)
        if s is not None:
            o[lab] = "เปิด" if s else "ปิด"
    try:
        o["ความสว่าง"] = f"{round(int(str(b.settingsGet('system', 'screen_brightness'))) * 100 / 255)}%"
    except (ValueError, TypeError):
        pass
    vols = _js(b.volumes(), [])
    for v in vols:
        if v.get("stream") == "music" and v.get("max_volume"):
            o["เสียงเพลง"] = f"{round(v['volume'] * 100 / v['max_volume'])}%"
    return o


_DEV = {}


def _ident():
    """ยี่ห้อ/รุ่นของเครื่องจริง (ในแอป) — ว่าง = ไม่รู้"""
    if "id" not in _DEV:
        man = model = ver = ""
        if config.ANDROID_APP:
            try:
                b = _b()
                man, model, ver = (str(b.prop(k) or "") for k in
                                   ("ro.product.manufacturer", "ro.product.model", "ro.build.version.release"))
            except Exception:  # noqa: BLE001
                pass
        _DEV["id"] = (man.strip(), model.strip(), ver.strip())
    return _DEV["id"]


def is_matepad():
    """เครื่อง Huawei (รุ่นที่โครงงานใช้ทดสอบ) หรือไม่รู้ยี่ห้อ → ใช้ความรู้ MatePad · ยี่ห้ออื่น → ความรู้ทั่วไป"""
    man = _ident()[0].lower()
    return not man or man in ("huawei", "honor")


def knowledge():
    if is_matepad():
        return KNOWLEDGE
    man, model, ver = _ident()
    return (f"เครื่องของผู้ใช้: {man} {model} (Android {ver or '?'})\n"
            "- เป็น Android ยี่ห้ออื่น ไม่ใช่ Huawei → มี Google Play และบริการ Google ตามปกติ (เช็กจากแอปที่ติดตั้ง)\n"
            "- ปัดลงจากขอบบน = การแจ้งเตือน · ปัดลงอีกครั้ง = แผงควบคุมด่วน (Wi-Fi/บลูทูธ/ไฟฉาย)\n"
            "- ชื่อเมนูตั้งค่าแต่ละยี่ห้อต่างกัน (Samsung One UI, Xiaomi/Redmi HyperOS/MIUI, Vivo OriginOS/Funtouch, "
            "Oppo ColorOS) → ใช้ช่องค้นหาในแอปตั้งค่าแทนการเดาเมนู")


def info(ctx=None, arg=""):
    if is_matepad():
        lines = ["📱 **HUAWEI MatePad 11.5 (TXZ-W09)**"] + [f"• {k}: {v}" for k, v in SPEC.items()]
    else:
        man, model, ver = _ident()
        lines = [f"📱 **{man} {model}**", f"• ระบบ: Android {ver}"]
    lv = live()
    if lv:
        m = lv.pop("model", "")
        a = lv.pop("android", "")
        lines.append(f"\n🔎 **ตอนนี้** ({m}{' · Android ' + a if a else ''})")
        lines += [f"• {k}: {v}" for k, v in lv.items()]
    return "\n".join(lines)


def prompt():
    """แนบในคำสั่งระบบของ AI ให้รู้จักเครื่อง"""
    return "\n\n" + knowledge() + "\n"


# ================================================================ ควบคุมผ่านแอปตั้งค่า

def _items():
    import android_shim
    return android_shim._screen_items()


def _label(e):
    return f"{e.get('text') or ''} {e.get('desc') or ''}".strip()


def _open_search(b, q):
    """เปิดแอปตั้งค่า → ช่องค้นหา → พิมพ์ q"""
    b.openSettings("android.settings.SETTINGS")
    time.sleep(1.5)
    for _ in range(2):
        items, w, h = _items()
        box = [e for e in items if e.get("edit") or re.search(r"search|ค้นหา", f"{e.get('id')} {_label(e)}", re.I)]
        if box:
            b.tap(box[0]["x"], box[0]["y"])
            time.sleep(1.0)
            b.typeText(q, False)
            time.sleep(1.5)
            return True
        b.swipe(w // 2, int(h * 0.3), w // 2, int(h * 0.7), 250)     # ช่องค้นหาอยู่บนสุด
        time.sleep(0.8)
    return False


def open_page(query):
    """ค้นแล้วเปิดหน้าตั้งค่าที่ตรงที่สุด คืน True/False"""
    b = _b()
    for q in ([query] if isinstance(query, str) else list(query)):
        if not _open_search(b, q):
            continue
        items, w, h = _items()
        words = [x for x in re.split(r"\s+", q.lower()) if x]
        hits = [e for e in items if e.get("text") and not e.get("edit")
                and all(x in e["text"].lower() for x in words) and e["y"] > h * 0.12]
        if hits:
            b.tap(hits[0]["x"], hits[0]["y"])
            time.sleep(1.6)
            return True
    return False


def _switch_near(items, rx):
    """หาสวิตช์ในแถวเดียวกับป้ายที่ตรง rx → (switch, checked)"""
    labels = [e for e in items if re.search(rx, _label(e), re.I) and not e.get("edit")]
    sws = [e for e in items if e.get("checkable") or re.search(r"switch|toggle|checkbox", e.get("id") or "", re.I)]
    for lab in labels:
        y1, y2 = lab["box"][1] - 60, lab["box"][3] + 60
        row = [s for s in sws if y1 <= s["y"] <= y2]
        if row:
            s = row[0]
            return s, s.get("checked")
    if len(sws) == 1:                                    # หน้าที่มีสวิตช์ตัวเดียว
        return sws[0], sws[0].get("checked")
    return None, None


def toggle(name, on):
    """เปิด/ปิดการตั้งค่าตามชื่อ (ไทย/อังกฤษ)"""
    if not config.ANDROID_APP:
        return "สั่งตั้งค่าเครื่องได้ในแอป APK เท่านั้น"
    if _DENY.search(name or ""):
        return "🔒 อันนี้เกี่ยวกับความปลอดภัย/ข้อมูลสำคัญ ให้ทำเองในแอปตั้งค่านะ"
    b = _b()
    if not b.a11yOn():
        import android_shim
        return android_shim.NOT_READY
    want = "เปิด" if on else "ปิด"
    queries, rx = (name,), re.escape(name)
    for pat, (qs, r) in SETTINGS.items():
        if re.search(pat, name, re.I):
            queries, rx = qs, r
            break
    if not open_page(queries):
        return f"หา \"{name}\" ในแอปตั้งค่าไม่เจอ ลองเรียกชื่อตามที่เห็นในหน้าตั้งค่านะ"
    for attempt in range(2):
        items, w, h = _items()
        sw, checked = _switch_near(items, rx)
        if sw:
            if checked is not None and bool(checked) == bool(on):
                b.key(3)
                return f"{name} {want}อยู่แล้ว"
            b.tap(sw["x"], sw["y"])
            time.sleep(1.2)
            items, w, h = _items()
            sw2, c2 = _switch_near(items, rx)
            # บางอันเด้งกล่องยืนยัน (เช่น ประหยัดพลังงาน) → กด "เปิด/ตกลง"
            ok = [e for e in items if e.get("click") and re.fullmatch(r"\s*(เปิด|ตกลง|OK|Turn on|Enable)\s*", _label(e), re.I)]
            if on and ok:
                b.tap(ok[0]["x"], ok[0]["y"])
                time.sleep(1.0)
            b.key(3)
            if c2 is not None and bool(c2) != bool(on) and not ok:
                return f"แตะสวิตช์{name}แล้ว แต่สถานะยังไม่เปลี่ยน — อาจต้องแตะเองในหน้าตั้งค่า"
            return f"✅ {want} {name} แล้ว"
        # สวิตช์อาจอยู่หน้าในอีกชั้น → แตะป้ายนั้นก่อน
        labels = [e for e in items if re.search(rx, _label(e), re.I) and e["y"] > h * 0.12]
        if attempt == 0 and labels:
            b.tap(labels[0]["x"], labels[0]["y"])
            time.sleep(1.4)
            continue
        break
    return f"เปิดหน้าตั้งค่า \"{name}\" ไว้ให้แล้ว แต่หาสวิตช์ไม่เจอ แตะเองได้เลย"


def open_setting(name):
    if not config.ANDROID_APP:
        return "ใช้ได้ในแอป APK เท่านั้น"
    if not _b().a11yOn():
        import android_shim
        return android_shim.NOT_READY
    return f"⚙️ เปิดหน้าตั้งค่า \"{name}\" ให้แล้ว" if open_page(name) else f"หา \"{name}\" ในแอปตั้งค่าไม่เจอ"


# ================================================================ คำสั่ง

_INFO = re.compile(r"(ข้อมูล|สเปค|สเป็ค|spec|รายละเอียด)\s*(ของ)?\s*(เครื่อง|แท็บเล็ต|แทปเลต|tablet|matepad)|"
                   r"เครื่อง(นี้)?(เป็น)?รุ่นอะไร|สถานะเครื่อง", re.I)
_STORE = re.compile(r"(พื้นที่|ความจุ|เมมโมรี่|storage).*(เหลือ|ว่าง|เต็ม|เท่าไ)", re.I)
_RAM = re.compile(r"(แรม|ram).*(เหลือ|ว่าง|เท่าไ)", re.I)
_CAN = re.compile(r"(แท็บเล็ต|เครื่อง)(นี้)?\s*(ทำอะไรได้บ้าง|มีอะไรบ้าง|มีความสามารถ)|วิธี(แบ่งจอ|เปิดหน้าต่างลอย|แคปจอ|ถ่ายภาพหน้าจอ)", re.I)
_OPEN = re.compile(r"^(?:ช่วย)?\s*(?:เปิด|ไปที่|เข้า)\s*(?:หน้า)?\s*(?:การ)?ตั้งค่า\s*(?P<n>.+?)\s*(?:ให้หน่อย|หน่อย|ที|ให้ที)?$")
_TOG = re.compile(r"^(?:ช่วย)?\s*(?P<v>เปิด|ปิด|เปิดใช้|ปิดใช้|turn\s*on|turn\s*off)\s*(?:งาน|ใช้)?\s*(?P<n>.+?)\s*"
                  r"(?:ให้หน่อย|หน่อย|ที|ให้ที|ด้วย|ครับ|ค่ะ)*$", re.I)


_ROT = re.compile(r"^(?:ช่วย)?\s*(?P<v>เปิด|ปิด|ล็อก|ล็อค|ปลดล็อก|ปลดล็อค)\s*(?:การ)?\s*หมุน\s*(?:หน้า)?\s*จอ\s*(?:อัตโนมัติ|ออโต้)?"
                  r"(?:\s*(?:ให้หน่อย|หน่อย|ที|ครับ|ค่ะ))*$|^(?:auto\s*rotate|หมุนจออัตโนมัติ)\s*(?P<v2>on|off|เปิด|ปิด)$", re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    if not t or len(t) > 80:
        return None
    m = _ROT.match(t)
    if m and config.ANDROID_APP:
        v = (m.group("v") or m.group("v2") or "").lower()
        auto = v in ("เปิด", "on", "ปลดล็อก", "ปลดล็อค")      # "ล็อกหมุนจอ" = ปิดหมุนอัตโนมัติ
        import android_shim
        return android_shim.rotate_auto(auto)
    if _INFO.search(t):
        return info(ctx)
    if _STORE.search(t):
        tot, free = storage()
        return f"💾 พื้นที่ว่าง {_gb(free)} จาก {_gb(tot)}" if tot else None
    if _RAM.search(t) and config.ANDROID_APP:
        mem = _js(_b().memInfo(), {})
        return f"🧠 แรมว่าง {_gb(mem['avail'])} จาก {_gb(mem['total'])}" if mem.get("total") else None
    if _CAN.search(t):
        return "📱 " + knowledge()
    m = _OPEN.match(t)
    if m:
        return open_setting(m.group("n"))
    m = _TOG.match(t)
    if m:
        name = m.group("n").strip()
        if any(re.search(p, name, re.I) for p in SETTINGS):
            return toggle(name, not m.group("v").lower().startswith(("ปิด", "turn off", "turnoff")))
    return None


def _obj(props, req):
    return {"type": "object", "properties": props, "required": req}


TOOLS = {
    "tablet_info": (lambda a, ctx: info(ctx), "ข้อมูล/สเปค/สถานะของแท็บเล็ต (แบต แรม พื้นที่ Wi-Fi ฯลฯ)", _obj({}, []), False),
    "device_setting": (lambda a, ctx: toggle(a.get("name", ""), bool(a.get("on", True))) if "on" in a
                       else open_setting(a.get("name", "")),
                       "เปิด/ปิดการตั้งค่าใดๆ ของเครื่องตามชื่อในแอปตั้งค่า (เช่น โหมดมืด ถนอมสายตา ประหยัดพลังงาน) "
                       "ไม่ใส่ on = แค่เปิดหน้านั้น",
                       _obj({"name": {"type": "string"}, "on": {"type": "boolean"}}, ["name"]), False),
}
