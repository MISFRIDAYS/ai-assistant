"""สั่ง "ทดสอบแอปทั้งหมด" → ผู้ช่วยลองงานพื้นฐานในแอปหลักทีละแอป แล้วรายงานว่าแอปไหนผ่าน/ไม่ผ่าน
(ไม่ส่งข้อความ ไม่โทร ไม่ซื้อ — แค่เปิด อ่านจอ ค้นหา และจดโน้ตทดสอบ)
"""
import json
import os
import re
import time

import config

_CMD = re.compile(r"^(ทดสอบ|เทสต์|เทส|test)\s*(แอป|แอพ|app)\s*(ทั้งหมด|หลัก|ทุกตัว)?\s*(ให้หน่อย|หน่อย|ที)?\s*(ครับ|ค่ะ|คะ)?$",
                  re.I)


def _status(ctx, s):
    if ctx is not None and hasattr(ctx, "status"):
        try:
            ctx.status(s)
        except Exception:  # noqa: BLE001
            pass


def _pick_apps(limit=8):
    import app_brain
    import cmdmenu
    by_kind = {}
    for pkg, e in app_brain.apps().items():
        k = cmdmenu.kind_of(pkg, e.get("label", ""), e.get("cat", ""))
        if k in ("chat", "note", "video", "browser", "music", "office", "maps") and not e.get("sys", False) \
                or k == "note":
            by_kind.setdefault(k, []).append((pkg, e.get("label") or pkg))
    order = ["note", "browser", "video", "chat", "office", "music", "maps"]
    out = []
    for k in order:
        for p in by_kind.get(k, [])[:2 if k == "chat" else 1]:
            out.append((k, p[0], p[1]))
    return out[:limit]


def _test_one(kind, pkg, label, ctx):
    import phone_tools
    import screen_tools
    r = phone_tools.open_app({"app": pkg, "fresh": True}, ctx)
    if str(r).startswith("ERROR"):
        return False, f"เปิดไม่ได้: {str(r)[:60]}"
    time.sleep(1.5)
    if (phone_tools._fg() or "") != pkg:
        return False, "เปิดแล้วแต่ไม่ได้อยู่ในแอป (ถูกบล็อก/มีหน้าอื่นบัง)"
    try:
        items = screen_tools._elements(screen_tools._dump())
    except Exception as e:  # noqa: BLE001
        return False, f"อ่านหน้าจอไม่ได้ ({e})"
    if not items:
        return False, "อ่านหน้าจอได้ 0 ปุ่ม (แอปวาดจอเอง — ต้องใช้โหมดมองจอ)"
    if kind == "note":
        import app_tasks
        r = app_tasks.note_new("ทดสอบจากผู้ช่วย AI " + time.strftime("%H:%M"), ctx)
        return (not r.startswith("ERROR") and "ไม่ให้พิมพ์" not in r), r[:90]
    if kind in ("browser", "video", "music"):
        import screen_task
        r = screen_task.run(f"ในแอป {label} ที่เปิดอยู่ ค้นหาคำว่า ทดสอบ แล้วให้ผลการค้นหาขึ้นมา", ctx, max_steps=7)
        return not r.startswith("ERROR"), r[:90]
    return True, f"เปิดได้ อ่านจอได้ {len(items)} ปุ่ม"


def run_all(ctx=None):
    if not config.ANDROID_APP:
        return "ทดสอบแอปได้เฉพาะในแอปบนแท็บเล็ต"
    apps = _pick_apps()
    if not apps:
        return "ยังไม่มีรายชื่อแอป — รอสักครู่ให้ผู้ช่วยเรียนรู้แอปในเครื่องก่อน แล้วลองใหม่"
    rows, ok_n = [], 0
    for i, (kind, pkg, label) in enumerate(apps):
        _status(ctx, f"🧪 ทดสอบ {label} ({i + 1}/{len(apps)})")
        try:
            ok, why = _test_one(kind, pkg, label, ctx)
        except Exception as e:  # noqa: BLE001
            ok, why = False, f"ผิดพลาด: {str(e)[:60]}"
        ok_n += ok
        rows.append({"app": label, "pkg": pkg, "kind": kind, "ok": ok, "why": why})
        print(time.strftime("[%H:%M:%S]"), f"🧪 {label}: {'ผ่าน' if ok else 'ไม่ผ่าน'} — {why}", flush=True)
    try:
        with open(os.path.join(config.DATA_DIR, "app_test.json"), "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}, f, ensure_ascii=False)
    except OSError:
        pass
    try:
        import phone_tools
        phone_tools._sh(["input", "keyevent", "3"])
    except Exception:  # noqa: BLE001
        pass
    lines = [f"🧪 ทดสอบแอป {len(rows)} ตัว — ผ่าน {ok_n} ตัว"]
    lines += [f"{'✅' if r['ok'] else '❌'} {r['app']}: {r['why']}" for r in rows]
    if ok_n < len(rows):
        lines.append("ส่งผลนี้ให้คนดูแลแอปดูได้ จะได้แก้ตรงแอปที่ไม่ผ่าน")
    return "\n".join(lines)


_MIC = re.compile(r"^(รายงาน|ตรวจ|เช็ค|เช็ก)\s*(ไมค์|ไมโครโฟน|การฟัง)(\s*(ให้หน่อย|หน่อย))?\s*(ครับ|ค่ะ)?$")


def handle_text(text, ctx=None):
    t = (text or "").strip()
    if re.match(r"^(ทดสอบ|เช็ค|เช็ก|ตรวจ)\s*(คีย์\s*)?(cloudflare|คลาวด์แฟลร์|คลาวแฟร์|คลาวด์แฟร์)", t, re.I):
        import voice
        return voice.cf_check()
    if re.match(r"^(ทดสอบ|เช็ค|เช็ก|ตรวจ)\s*เสียง(พูด|บอท|ผู้ช่วย)?(\s*(ให้หน่อย|หน่อย))?\s*(ครับ|ค่ะ)?$", t):
        import voice
        return voice.voice_test()
    if _MIC.match(t):
        import voice
        return voice.mic_report()
    if _CMD.match(t):
        return run_all(ctx)
    return None
