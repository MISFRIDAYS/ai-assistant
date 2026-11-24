"""กรอกแบบฟอร์มบนจอ (เว็บ/แอปไหนก็ได้)

ขั้นตอน: อ่านฟอร์ม → บอกว่ามีช่องอะไรบ้าง → เติมจากข้อมูลของคุณ (ในเครื่อง) / ถามช่องที่ไม่รู้
        → พิมพ์ลงทีละช่อง (เลื่อนจอหาช่องถัดไปเอง) → สรุปให้ตรวจ → ถามก่อนกดส่งเสมอ
ความปลอดภัย: ข้อมูลส่วนตัวไม่ผ่าน AI · รหัสผ่าน/OTP/บัตรเครดิต ถามทุกครั้ง ไม่เก็บ ไม่บันทึกลง log
"""
import re
import time

import user_profile

_SUBMIT = re.compile(r"^(ส่ง|ยืนยัน|ตกลง|บันทึก|ถัดไป|ดำเนินการต่อ|สมัคร|ลงทะเบียน|submit|send|next|continue|"
                     r"confirm|save|sign ?up|register|ok)$", re.I)
_SKIP = re.compile(r"^(ข้าม|ไม่ต้อง|เว้น|skip|-|ไม่มี)$", re.I)
_CANCEL = re.compile(r"^(ยกเลิก|หยุด|พอ|cancel|stop)$", re.I)


def _items():
    import share_tools
    return share_tools._items()


def _label(e, items):
    """ป้ายของช่อง: คำใบ้ในช่อง (hint) / content-desc / id / ข้อความที่อยู่เหนือหรือซ้ายช่อง"""
    own = (e["text"] or e["desc"] or "").strip()
    rid = e["id"].replace("_", " ")
    above = None
    x1, y1, x2, y2 = e["box"]
    for o in items:
        if o is e or o["edit"]:
            continue
        t = (o["text"] or o["desc"] or "").strip()
        if not t or len(t) > 60:
            continue
        ox1, oy1, ox2, oy2 = o["box"]
        near_above = 0 <= y1 - oy2 <= 140 and ox1 < x2 and ox2 > x1
        near_left = abs((oy1 + oy2) / 2 - (y1 + y2) / 2) < 40 and 0 <= x1 - ox2 <= 300
        if near_above and any(f["edit"] and f is not e and oy2 <= f["y"] <= y1 for f in items):
            near_above = False                          # มีช่องกรอกอื่นคั่นอยู่ → ป้ายนี้เป็นของช่องนั้น
        if near_above or near_left:
            d = (y1 - oy2) if near_above else (x1 - ox2) / 3
            if above is None or d < above[0]:
                above = (d, t)
    parts = [p for p in (above[1] if above else "", own, rid) if p]
    return " / ".join(dict.fromkeys(parts))[:80] or "ช่องไม่มีชื่อ"


def read_fields(items=None):
    items = items if items is not None else _items()
    return [{"el": e, "label": _label(e, items), "filled": (e["text"] or "").strip()}
            for e in sorted((x for x in items if x["edit"]), key=lambda x: (x["y"], x["x"]))]


def _type_into(e, value, ctx):
    import screen_tools
    screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
    time.sleep(0.4)
    import share_tools
    share_tools._clear_box(e)
    screen_tools.type_text({"text": value, "send": False, "replace": True}, ctx)
    time.sleep(0.3)


def describe(fields):
    return "\n".join(f"{i + 1}. {f['label']}" + (f" (มีค่าอยู่แล้ว: {f['filled'][:20]})" if f["filled"] else "")
                     for i, f in enumerate(fields))


def fill(ctx, use_profile=True, max_pages=4):
    """กรอกฟอร์มที่เปิดอยู่บนจอ คืนข้อความสรุป"""
    import screen_tools
    if not screen_tools.adb_serial():
        return screen_tools.NOT_CONNECTED
    ask = getattr(ctx, "ask", None)
    done, seen, asked_any = [], set(), False
    for page in range(max_pages):
        try:
            items = _items()
        except RuntimeError as e:
            return f"ERROR: อ่านหน้าจอไม่ได้ ({e})"
        fields = [f for f in read_fields(items) if f["label"] not in seen]
        if page == 0 and not fields:
            return "ไม่เจอช่องกรอกข้อมูลบนจอ — เปิดหน้าฟอร์มค้างไว้ก่อนแล้วสั่งใหม่นะ"
        if page == 0 and ctx is not None and hasattr(ctx, "notify"):
            try:
                ctx.notify("📝 เจอฟอร์ม:\n" + describe(fields))
            except Exception:  # noqa: BLE001
                pass
        for f in fields:
            seen.add(f["label"])
            if f["filled"] and not re.search(r"กรอก|ระบุ|enter|type|e\.g|เช่น|^\W*$", f["filled"], re.I) \
                    and f["filled"] not in f["label"]:
                continue                                   # มีค่าอยู่แล้ว (ไม่ใช่คำใบ้) → ไม่ทับ
            secret = bool(user_profile.SENSITIVE.search(f["label"]))
            key, val = user_profile.value_for(f["label"]) if use_profile and not secret else (None, None)
            if not val:
                if not ask:
                    continue
                q = f"ช่อง \"{f['label']}\" กรอกว่าอะไรดี?" + (" (ข้อมูลลับ — ไม่บันทึก)" if secret else "")
                ans = ask(q)
                asked_any = True
                if ans is None or _CANCEL.match(ans.strip()):
                    return "หยุดกรอกฟอร์มแล้ว" + (f" (กรอกไปแล้ว: {', '.join(done)})" if done else "")
                if _SKIP.match(ans.strip()):
                    continue
                val = ans.strip()
            _type_into(f["el"], val, ctx)
            done.append(f["label"].split(" / ")[0] + ("=••••" if secret else f"={val[:25]}"))
            print(f"[form] กรอก {f['label'][:30]!r}" + (" (ข้อมูลลับ)" if secret else ""), flush=True)
        screen_tools.swipe({"direction": "up"}, None)       # เลื่อนหาช่องที่เหลือ
        time.sleep(0.6)
        try:
            more = [f for f in read_fields() if f["label"] not in seen]
        except RuntimeError:
            more = []
        if not more:
            break
    summary = "กรอกแล้ว: " + (", ".join(done) if done else "(ไม่มีช่องที่ต้องกรอก)")
    btn = _submit_button()
    if not btn:
        return summary + "\nตรวจข้อมูลบนจอได้เลย (หาปุ่มส่งไม่เจอ — กดส่งเองนะ)"
    ok = ctx.confirm(f"{summary}\n\nกดปุ่ม \"{btn['text'] or btn['desc']}\" ส่งฟอร์มเลยไหม?") \
        if ctx is not None and hasattr(ctx, "confirm") else False
    if not ok:
        return summary + "\nยังไม่ได้กดส่ง — ตรวจบนจอแล้วกดเองได้เลย"
    screen_tools.adb_shell(["input", "tap", str(btn["x"]), str(btn["y"])])
    return summary + f"\n✅ กด \"{btn['text'] or btn['desc']}\" ส่งฟอร์มแล้ว"


def _submit_button():
    try:
        items = _items()
    except RuntimeError:
        return None
    cands = [e for e in items if e["click"] and not e["edit"]
             and (_SUBMIT.match((e["text"] or "").strip()) or _SUBMIT.match((e["desc"] or "").strip()))]
    return max(cands, key=lambda e: e["y"]) if cands else None


_FILL = re.compile(r"^(?:ช่วย)?\s*กรอก\s*(?:แบบ)?\s*(?:ฟอร์ม|form|ข้อมูล)(?P<rest>.*)$", re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    m = _FILL.match(t)
    if not m:
        return None
    rest = m.group("rest")
    use_profile = not re.search(r"ถาม(ฉัน|ผม)?ทุกช่อง|ไม่ต้องใช้ข้อมูล", rest)
    return fill(ctx, use_profile=use_profile)
