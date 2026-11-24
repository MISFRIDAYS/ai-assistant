"""โหมดมองจอ: ทำงานหลายขั้นในแอปด้วยการ "ดูภาพหน้าจอจริง" ทีละขั้น (แบบคนมองจอแล้วกด)

ทุกขั้น: แคปจอ → ตีกรอบ+ใส่เลขทุกปุ่ม/ช่อง → ส่งภาพ+รายการให้ AI ที่ดูรูปได้ (Qwen3.5/Kimi/Gemini…)
→ AI ตอบ JSON ว่าจะทำอะไร → ทำ → วนจนเสร็จ (สูงสุด VISION_MAX_STEPS ขั้น)
ความปลอดภัย: ปุ่มโทร/ส่ง/จ่าย/ลบ ผ่านด่านยืนยันเดิม · ไม่พิมพ์ลงช่องรหัสผ่าน · ไม่แตะแอปธนาคาร
"""
import json
import os
import re
import time

import config

MAX_STEPS = int(os.environ.get("VISION_MAX_STEPS", "10"))
_BANK = re.compile(r"bank|kbank|kplus|scb|krungthai|ktb|bualuang|bbl|krungsri|ttb|gsb|baac|truemoney|wallet|"
                   r"paotang|promptpay|paypal", re.I)

_PROMPT = """คุณคือมือของผู้ช่วย AI ที่กำลังควบคุมอุปกรณ์ Android แทนผู้ใช้
เป้าหมาย: {goal}

ภาพ: หน้าจอตอนนี้ ทุกปุ่ม/ช่องที่กดได้มีกรอบแดงพร้อมเลขกำกับ
รายการ (เลข: ชนิด ข้อความ/คำอธิบาย):
{items}

สิ่งที่ทำไปแล้ว:
{history}

เลือกการกระทำถัดไป 1 อย่าง ตอบเป็น JSON บรรทัดเดียวเท่านั้น:
{{"do":"tap","n":เลข}}                    แตะปุ่ม/ช่องเลขนั้น
{{"do":"long","n":เลข}}                   กดค้าง
{{"do":"type","n":เลข,"text":"ข้อความ"}}    แตะช่องเลขนั้นแล้วพิมพ์ (n ใส่ 0 ถ้าช่องถูกเลือกอยู่แล้ว)
{{"do":"enter"}}                          กด Enter/ค้นหา
{{"do":"scroll","dir":"down|up|left|right"}}
{{"do":"back"}}  {{"do":"home"}}
{{"do":"open","app":"ชื่อแอป"}}
{{"do":"wait"}}                           รอหน้าโหลด
{{"do":"done","say":"สรุปสั้นๆ ว่าทำอะไรเสร็จ"}}
{{"do":"fail","why":"เหตุผลสั้นๆ"}}

กติกา:
- ดูภาพจริงเป็นหลัก ไอคอนไม่มีชื่อให้ดูจากรูปร่าง (+ = สร้างใหม่, ดินสอ = แก้ไข/เขียน, แว่นขยาย = ค้นหา, ⋮ = เมนู)
- ถ้ามีป๊อปอัปแนะนำ/โฆษณา ให้ปิดก่อน · ถ้าหน้าไม่เปลี่ยนหลังกด ให้ลองวิธีอื่น ไม่กดซ้ำเดิมเกิน 2 ครั้ง
- พิมพ์ข้อความตามที่ผู้ใช้สั่งเท่านั้น ห้ามแต่งข้อความส่งหาคนอื่นเอง
- ห้ามพิมพ์ในช่องรหัสผ่าน ห้ามจ่ายเงิน/โอน/ลบข้อมูล ถ้าเป้าหมายต้องทำแบบนั้นให้ตอบ fail
- เมื่อเป้าหมายสำเร็จแล้ว (เห็นผลบนจอ) ให้ตอบ done ทันที"""


def available():
    """ใช้โหมดมองจอได้ไหม (ต้องเป็นแอป + มี AI ที่ดูรูปได้)"""
    return bool(config.ANDROID_APP and (config.CLOUD_API_KEY or config.GEMINI_API_KEY or config.ANTHROPIC_API_KEY
                                        or config.GROQ_API_KEY or config.OLLAMA_URL))


def _b():
    import android_shim
    return android_shim.bridge()


def _targets(items, w, h):
    """ปุ่ม/ช่องที่ควรใส่เลข (กดได้ หรือ มีข้อความ) — ไม่เกิน 60 จุด เรียงบนลงล่าง"""
    out = []
    for e in items:
        x1, y1, x2, y2 = e["box"]
        bw, bh = x2 - x1, y2 - y1
        if bw <= 4 or bh <= 4 or (bw > w * 0.97 and bh > h * 0.6):
            continue
        if e["click"] or e["edit"] or e.get("checkable"):
            out.append(e)
    seen, uniq = set(), []
    for e in sorted(out, key=lambda e: (e["box"][1] // 20, e["box"][0])):
        k = (e["x"] // 8, e["y"] // 8)
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:60]


def _describe(e):
    kind = "ช่องพิมพ์" if e["edit"] else ("สวิตช์" if e.get("checkable") else "ปุ่ม")
    if e.get("password"):
        kind = "ช่องรหัสผ่าน(ห้ามพิมพ์)"
    lab = (e["text"] or e["desc"] or e.get("id") or "").replace("\n", " ")[:40]
    on = " [เปิดอยู่]" if e.get("checked") else ""
    return f"{kind} {lab or '(ไอคอนไม่มีชื่อ)'}{on}"


def _snapshot(step):
    """แคปจอ + ใส่เลข → (path ภาพ, รายการเป้าหมาย, w, h) หรือ None"""
    import screen_tools
    root = screen_tools._dump()
    w, h = screen_tools._screen_size(root)
    items = screen_tools._elements(root)
    tg = _targets(items, w, h)
    raw = os.path.join(config.DATA_DIR, "st_raw.png")
    ann = os.path.join(config.DATA_DIR, f"st_{step % 2}.jpg")
    b = _b()
    if not b.screenshot(raw):
        return None, tg, w, h
    if not b.annotate(raw, json.dumps([list(e["box"]) for e in tg]), ann):
        return None, tg, w, h
    return ann, tg, w, h


def _parse(ans):
    m = re.search(r"\{.*\}", ans or "", re.S)
    if not m:
        return None
    raw = m.group(0)
    for cand in (raw, raw[:raw.find("}") + 1]):
        try:
            d = json.loads(cand)
            if isinstance(d, dict) and d.get("do"):
                return d
        except ValueError:
            continue
    return None


def _act(d, tg, w, h, ctx):
    """ทำตามที่ AI เลือก → ข้อความผลลัพธ์ (ขึ้นต้น ERROR ถ้าทำไม่ได้)"""
    import phone_tools
    import screen_tools
    do = d.get("do")
    e = None
    n = d.get("n")
    if isinstance(n, (int, float, str)) and str(n).strip().isdigit() and int(n) > 0:
        i = int(n) - 1
        if i >= len(tg):
            return f"ERROR: ไม่มีเลข {n} บนจอ"
        e = tg[i]
    lab = (e["text"] or e["desc"] or "") if e else ""
    if do in ("tap", "long"):
        if not e:
            return "ERROR: ต้องระบุเลขปุ่ม"
        if lab and not screen_tools._check_sensitive(lab, ctx):
            return "ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้"
        if do == "long":
            screen_tools.adb_shell(["input", "swipe", str(e["x"]), str(e["y"]), str(e["x"]), str(e["y"]), "800"])
        else:
            screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
        time.sleep(1.0)
        screen_tools.allow_permission_popup()
        return f"แตะเลข {n} ({lab or 'ไอคอน'})"
    if do == "type":
        text = str(d.get("text") or "")
        if not text:
            return "ERROR: ไม่มีข้อความ"
        if e is not None:
            if e.get("password"):
                return "ERROR: ห้ามพิมพ์ลงช่องรหัสผ่าน"
            screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
            time.sleep(0.6)
        r = screen_tools.type_text({"text": text}, ctx)
        return f"พิมพ์ \"{text[:30]}\" → {r[:60]}"
    if do == "enter":
        screen_tools.adb_shell(["input", "keyevent", "66"])
        time.sleep(0.8)
        return "กด Enter"
    if do == "scroll":
        dmap = {"down": "up", "up": "down", "left": "right", "right": "left"}   # เลื่อนดูลง = ปัดนิ้วขึ้น
        screen_tools.swipe({"direction": dmap.get(d.get("dir", "down"), "up")}, ctx)
        time.sleep(0.7)
        return f"เลื่อน{d.get('dir', 'down')}"
    if do == "back":
        screen_tools.adb_shell(["input", "keyevent", "4"])
        time.sleep(0.8)
        return "ย้อนกลับ"
    if do == "home":
        screen_tools.adb_shell(["input", "keyevent", "3"])
        time.sleep(0.8)
        return "ไปหน้าโฮม"
    if do == "open":
        app = str(d.get("app") or "")
        if _BANK.search(app):
            return "ERROR: ไม่เปิดแอปการเงินในโหมดอัตโนมัติ"
        r = phone_tools.open_app({"app": app}, ctx)
        time.sleep(1.5)
        return f"เปิด {app} → {str(r)[:60]}"
    if do == "wait":
        time.sleep(1.5)
        return "รอ"
    return f"ERROR: ไม่รู้จัก {do}"


def run(goal, ctx=None, max_steps=None):
    """ทำเป้าหมายให้สำเร็จด้วยการมองจอ → ข้อความสรุป (ขึ้นต้น ERROR ถ้าไม่สำเร็จ)"""
    import phone_tools
    import vision
    if not config.ANDROID_APP:
        return "ERROR: โหมดมองจอใช้ได้เฉพาะในแอป"
    max_steps = max_steps or MAX_STEPS
    hist, last_sig, same = [], None, 0
    for step in range(max_steps):
        fg = phone_tools._fg() or ""
        if _BANK.search(fg):
            return "ERROR: หยุดก่อน — อยู่ในแอปการเงิน ผู้ช่วยไม่ควบคุมเองครับ"
        if ctx is not None and hasattr(ctx, "status"):
            try:
                ctx.status(f"👀 มองจอ ขั้นที่ {step + 1}")
            except Exception:  # noqa: BLE001
                pass
        img, tg, w, h = _snapshot(step)
        if not img:
            return "ERROR: แคปหน้าจอไม่ได้ (ต้องเปิดสิทธิ์คุมจอ และ Android 11 ขึ้นไป)"
        items = "\n".join(f"{i + 1}: {_describe(e)}" for i, e in enumerate(tg)) or "(ไม่มี — ดูจากภาพ)"
        prompt = _PROMPT.format(goal=goal, items=items,
                                history="\n".join(f"{i + 1}. {x}" for i, x in enumerate(hist[-8:])) or "(ยังไม่ได้ทำอะไร)")
        try:
            ans = vision.ask_images(prompt, [img], quality=True)
        except Exception as e:  # noqa: BLE001
            return f"ERROR: AI ที่ดูรูปได้ตอบไม่ได้ ({str(e)[:100]})"
        d = _parse(ans)
        if not d:
            hist.append("(AI ตอบไม่เป็น JSON — ลองใหม่)")
            continue
        do = d.get("do")
        print(time.strftime("[%H:%M:%S]"), f"👀 ขั้น {step + 1}: {json.dumps(d, ensure_ascii=False)[:150]}", flush=True)
        if do == "done":
            return "✅ " + str(d.get("say") or "ทำเสร็จแล้ว")
        if do == "fail":
            return "ERROR: " + str(d.get("why") or "ทำต่อไม่ได้")
        sig = json.dumps(d, sort_keys=True, ensure_ascii=False)
        same = same + 1 if sig == last_sig else 0
        last_sig = sig
        if same >= 2:
            hist.append(f"ทำ {sig} ซ้ำ 3 ครั้งแล้วไม่ได้ผล — ต้องเปลี่ยนวิธี")
            same = 0
            last_sig = None
            continue
        try:
            res = _act(d, tg, w, h, ctx)
        except Exception as e:  # noqa: BLE001
            res = f"ERROR: {str(e)[:80]}"
        hist.append(res)
        if res.startswith("ผู้ใช้ไม่อนุญาต"):
            return "⏹️ หยุดแล้ว — ผู้ใช้ไม่อนุญาตให้กดปุ่มนี้"
    return f"ERROR: ทำไม่เสร็จใน {max_steps} ขั้น (ทำไปแล้ว: {' → '.join(hist[-4:])})"


def tool_screen_task(a, ctx):
    return run(a.get("goal", ""), ctx)


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "screen_task": (tool_screen_task,
                    "ทำงานหลายขั้นในแอปด้วยการ 'มองภาพหน้าจอจริง' ทีละขั้น (แม่นที่สุดกับแอปซับซ้อน/ปุ่มไอคอนไม่มีชื่อ "
                    "เช่น สร้างโน้ต, ตั้งค่าในแอป, หาปุ่มที่ไม่เจอ) ใส่เป้าหมายให้ครบในประโยคเดียว เช่น "
                    "'เปิดแอปบันทึก สร้างโน้ตใหม่ พิมพ์ว่า ซื้อนม แล้วบันทึก'",
                    _obj({"goal": {"type": "string"}}, ["goal"]), False),
}
