"""/diag <แอป> — ตรวจทีละขั้นว่าทำไมเปิดแอป/กดในแอปไม่ได้ แล้วส่งผลให้ผู้ใช้ copy มาให้ดู"""
import time


def _short(s, n=300):
    s = (s or "").strip().replace("\r", "")
    return s if len(s) <= n else s[:n] + "…"


def run(app="youtube"):
    import phone_tools
    import screen_tools
    sh = phone_tools._sh
    key = phone_tools.ALIASES.get(app.strip().lower(), app.strip()).lower()
    out = [f"🔎 ตรวจการเปิด '{app}' (key={key})"]

    serial = screen_tools.adb_serial(force=True)
    out.append(f"1) ADB: {serial or '❌ ไม่ได้เชื่อม'}")
    if not serial:
        out.append("→ ต้องเชื่อม ADB ก่อน ทุกอย่างที่เป็นการกดหน้าจอจะใช้ไม่ได้")
        return "\n".join(out)

    out.append(f"2) แอปบนจอตอนนี้: {phone_tools._fg() or '❌ อ่านไม่ได้'}")
    comps = phone_tools._launcher_components()
    out.append(f"3) แอปที่มีไอคอน: {len(comps)} ตัว")
    for w in ("gbox", key.split()[0], "youtube", "instagram", "google"):
        hits = sorted({c for c in comps if w in c.lower()})[:4]
        if hits:
            out.append(f"   '{w}': {', '.join(hits)}")
    pk = sh(["pm", "list", "packages"])
    gb = [l.replace("package:", "") for l in pk.splitlines() if "gbox" in l.lower() or key.split()[0] in l.lower()]
    out.append(f"   package ที่เกี่ยวข้อง: {', '.join(gb[:6]) or 'ไม่มี'}")

    url = phone_tools.APP_LINKS.get(key)
    if url:
        r = sh(["cmd", "package", "resolve-activity", "--brief", "-a", "android.intent.action.VIEW",
                "-c", "android.intent.category.BROWSABLE", "-d", url], quote=True)
        out.append(f"4) ลิงก์ {url} เปิดด้วย: {_short(r.splitlines()[-1] if r.strip() else r, 150)}")

    sc = sh(["dumpsys", "shortcut"], timeout=30)
    lab = phone_tools.APP_LABELS.get(key, [app])[0].lower()
    lines = [l.strip() for l in sc.splitlines() if lab in l.lower() and ("label" in l.lower() or "title" in l.lower())]
    out.append(f"5) ทางลัดบนหน้าโฮม ({lab}): {_short(' | '.join(lines[:3]), 250) or 'ไม่พบ'}")

    raw = screen_tools.adb_shell(["uiautomator", "dump", "/dev/tty"], timeout=25)
    out.append(f"6) อ่านหน้าจอ (uiautomator): {'✅ ได้' if '<?xml' in raw else '❌ ' + _short(raw, 160)}")

    def labels_on_screen():
        try:
            items = screen_tools._elements(screen_tools._dump())
        except Exception as e:  # noqa: BLE001
            return f"❌ {e}"
        names = []
        for e in items:
            v = (e["text"] or e["desc"]).strip()
            if v and v not in names and len(v) < 30:
                names.append(v)
        return ", ".join(names[:35]) or "(ว่าง)"

    screen_tools.adb_shell(["input", "keyevent", "3"])
    time.sleep(0.6)
    screen_tools.adb_shell(["input", "keyevent", "3"])
    time.sleep(1.2)
    out.append(f"7) หน้าโฮมเห็น: {_short(labels_on_screen(), 500)}")

    gbox = next((c for c in comps if "gbox" in c.lower()), None)
    if gbox:
        sh(["am", "start", "--user", "0", "-n", gbox])
        time.sleep(2.5)
        out.append(f"8) ใน GBox เห็น: {_short(labels_on_screen(), 500)}")
        screen_tools.adb_shell(["input", "keyevent", "3"])
        time.sleep(1)

    t0 = time.time()
    res = phone_tools.open_app({"app": app}, None)
    out.append(f"9) ลองเปิดจริง ({time.time() - t0:.0f} วิ): {_short(res, 400)}")
    out.append(f"   แอปบนจอหลังเปิด: {phone_tools._fg() or '?'}")
    return "\n".join(out)
