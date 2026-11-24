"""รู้ว่าตอนนี้หน้าจออยู่ตรงไหน — สแกนทุกครั้งที่ได้ยิน "เฮ้ยผู้ช่วย" (ทำคู่กับการฟังคำสั่ง ไม่เพิ่มเวลารอ)

ผลสแกน: แอปอะไร · หน้าไหน (ชื่อหน้า/แท็บ/ห้องแชทของใคร) · ปุ่ม/ช่องกรอก/ข้อความเด่นบนจอ · ไอคอนที่เรียนรู้ไว้
แนบให้ AI ทุกคำสั่งที่ตามมา → "กดอันนี้" "ตอบเขาว่า…" "สรุปหน้านี้" เข้าใจเหมือนคนที่มองจออยู่
สั่งเองได้: "อยู่หน้าไหน" · "หน้าจอนี้คืออะไร" · "อธิบายหน้าจอ" (มองภาพละเอียด ถ้ามี AI ที่ดูรูปได้)
"""
import re
import threading
import time

import config

OWN = "com.aibot.assistant"
_last = {"t": 0.0, "snap": None, "busy": False}
_SYSTEM_UI = re.compile(r"^(\d{1,2}:\d{2}|\d+%|แบตเตอรี่.*|Wi-?Fi.*|สัญญาณ.*|บลูทูธ.*|Bluetooth.*|การแจ้งเตือน.*)$", re.I)
_HOME_PKG = re.compile(r"launcher|home", re.I)


def _items():
    import share_tools
    return share_tools._items()


def _lab(e):
    return (e.get("text") or e.get("desc") or "").strip()


def snapshot():
    """อ่านหน้าจอตอนนี้ (ไม่ถ่ายภาพ เร็ว ~0.3 วิ) → dict"""
    if not config.ANDROID_APP or config.MOCK_PHONE:
        return None
    import phone_tools
    pkg = phone_tools._fg() or ""
    if not pkg or pkg == OWN:
        return None
    try:
        items = _items()
    except Exception:  # noqa: BLE001
        return None
    w = max((e["box"][2] for e in items), default=1080)
    h = max((e["box"][3] for e in items), default=2000)
    try:
        import app_index
        app = app_index.label_of(pkg)
    except Exception:  # noqa: BLE001
        app = pkg
    act = ""
    try:
        import android_shim
        act = str(android_shim.bridge().currentActivity() or "").split(".")[-1]
    except Exception:  # noqa: BLE001
        pass
    texts = [e for e in items if _lab(e) and not _SYSTEM_UI.match(_lab(e)) and e["y"] > h * 0.03]
    top = [e for e in texts if e["y"] < h * 0.16 and not e.get("edit") and 1 < len(_lab(e)) <= 40]
    title = _lab(min(top, key=lambda e: (e["y"], -len(_lab(e))))) if top else ""
    buttons, seen = [], set()
    for e in texts:
        t = _lab(e)
        if e.get("click") and not e.get("edit") and len(t) <= 28 and t not in seen:
            seen.add(t)
            buttons.append(t)
    try:
        import app_tasks
        for e in app_tasks.unlabeled(items):
            lab = app_tasks.label_of(pkg, e, w, h)
            if lab and lab not in seen:
                seen.add(lab)
                buttons.append(f"≈{lab}")
    except Exception:  # noqa: BLE001
        pass
    fields = [(_lab(e) or e.get("id") or "ช่องกรอก")[:30] for e in items if e.get("edit")]
    content = [_lab(e)[:80] for e in texts if not e.get("click") and len(_lab(e)) > 3 and e["y"] > h * 0.16][:10]
    chat = None
    try:
        import share_tools
        c = share_tools._composer(items)
        if c and c["y"] > 0.5 * h:
            chat = title or "?"
    except Exception:  # noqa: BLE001
        pass
    kind = ("หน้าโฮม" if _HOME_PKG.search(pkg) else f"ห้องแชทกับ {chat}" if chat
            else "หน้ากรอกข้อมูล/ฟอร์ม" if len(fields) >= 2 else "หน้าค้นหา" if fields and re.search(r"ค้นหา|search", " ".join(fields), re.I)
            else "")
    snap = {"pkg": pkg, "app": app, "activity": act, "title": title, "kind": kind, "buttons": buttons[:14],
            "fields": fields[:5], "content": content, "chat": chat, "t": time.time()}
    _last.update(t=time.time(), snap=snap)
    return snap


def scan_async():
    """เรียกตอนได้ยินคำปลุก — สแกนเบื้องหลังระหว่างรอผู้ใช้พูดคำสั่ง"""
    if _last["busy"]:
        return
    _last["busy"] = True

    def go():
        try:
            snapshot()
        except Exception as e:  # noqa: BLE001
            print(f"[screen] {e}", flush=True)
        finally:
            _last["busy"] = False
    threading.Thread(target=go, daemon=True).start()


def describe(s):
    if not s:
        return ""
    parts = [f"แอป {s['app']}" + (f" ({s['pkg']})" if s["app"] != s["pkg"] else "")]
    if s.get("kind"):
        parts.append(s["kind"])
    if s.get("title") and not s.get("chat"):
        parts.append(f"หัวข้อหน้า \"{s['title']}\"")
    if s.get("activity"):
        parts.append(f"activity {s['activity']}")
    out = "ตอนนี้หน้าจอ: " + " · ".join(parts)
    if s.get("buttons"):
        out += f"\nปุ่มที่เห็น: {', '.join(s['buttons'])}"
    if s.get("fields"):
        out += f"\nช่องกรอก: {', '.join(s['fields'])}"
    if s.get("content"):
        out += f"\nข้อความบนจอ: {' | '.join(s['content'][:6])}"
    return out[:900]


def recent(max_age=25):
    """ผลสแกนล่าสุด (ถ้ายังสดอยู่) เป็นข้อความสำหรับแนบให้ AI"""
    if _last["busy"]:
        for _ in range(3):                  # สแกนยังไม่เสร็จ รอได้ไม่เกิน 0.3 วิ (ไม่ให้ผู้ใช้รอ)
            time.sleep(0.1)
            if not _last["busy"]:
                break
    s = _last.get("snap")
    if not s or time.time() - _last["t"] > max_age:
        return ""
    return describe(s)


# ================================================================ คำสั่ง

_WHERE = re.compile(r"^(?:ตอนนี้)?\s*(?:อยู่|เปิด)\s*(?:หน้า|แอป|แอพ)\s*(?:ไหน|อะไร)|^หน้า(?:จอ)?(?:นี้)?\s*(?:คือ|เป็น)?\s*(?:หน้า)?อะไร|"
                    r"^(?:อธิบาย|อ่าน|สรุป|ดู)\s*(?:หน้าจอ|หน้านี้|จอ)(?:นี้|ให้หน่อย|หน่อย|ให้ฟัง)?|^บนจอมีอะไร(?:บ้าง)?")


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    t = re.sub(r"\s*(ให้หน่อย|หน่อย|ครับ|ค่ะ|นะ)+$", "", t)
    if not t or not _WHERE.search(t) or not config.ANDROID_APP:
        return None
    s = _last.get("snap") if time.time() - _last["t"] < 25 else None
    if s is None:
        try:
            import android_shim
            android_shim.bridge().away()             # สั่งจากหน้าผู้ช่วย → ดูแอปที่อยู่ข้างหลัง
            time.sleep(0.8)
        except Exception:  # noqa: BLE001
            pass
        s = snapshot()
    if not s:
        return "ตอนนี้อยู่หน้าแอปผู้ช่วยเองครับ (ไม่มีแอปอื่นเปิดอยู่ด้านหลัง)"
    deep = re.search(r"อธิบาย|สรุป|มีอะไร", t)
    if deep:
        try:                                          # มองภาพจริง (รู้ละเอียด แต่ตอบสั้น)
            import android_shim
            import vision
            path = config.DATA_DIR + "/screen_now.png"
            if android_shim.bridge().screenshot(path):
                ans = vision.ask_images("นี่คือภาพหน้าจอแท็บเล็ตของผู้ใช้ บอกสั้นที่สุดเป็นภาษาไทย 1-2 ประโยค "
                                        "ว่าอยู่หน้าอะไรและมีเรื่องสำคัญอะไร (ไม่ต้องไล่ปุ่ม ลงท้าย ครับ)\n"
                                        f"ข้อมูลจากระบบ: {describe(s)}", [path])
                if ans:
                    import polite
                    return "📱 " + polite.fix(ans.strip())
        except Exception as e:  # noqa: BLE001
            print(f"[screen] vision: {e}", flush=True)
    return "📱 " + short(s)


def short(s):
    """บอกผู้ใช้สั้นๆ (ผู้ช่วยรู้ละเอียดอยู่แล้วจาก describe)"""
    where = s.get("kind") or (f"หน้า \"{s['title']}\"" if s.get("title") else "")
    return f"อยู่ใน {s['app']}" + (f" · {where}" if where else "")
