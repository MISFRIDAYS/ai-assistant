"""เรียนรู้แอปอย่างละเอียด (ทำงานในเครื่อง ไม่มีการจำอัตโนมัติแบบเดาเอง)

1) สำรวจแอป:  "ศึกษาแอป instagram" / /learn instagram
   เปิดแอป → อ่านแท็บ/เมนูหลัก → แตะเข้าไปดูทีละแท็บ (ข้ามปุ่มอันตราย: ลบ/จ่าย/ส่ง/โทร/ออกจากระบบ ฯลฯ)
   → จดว่าแต่ละหน้ามีปุ่ม/ช่องกรอกอะไร → ให้ AI ใช้เป็นแผนที่ตอนสั่งงานในแอปนั้น
2) สอนด้วยการทำให้ดู:  "จำขั้นตอน สั่งกาแฟ" → ทำบนจอเองตามปกติ → "จบขั้นตอน"
   บอทจับว่าแตะปุ่มไหน/พิมพ์อะไร (getevent + อ่านจอ) → สรุปให้ดู → บันทึกเมื่อคุณยืนยันเท่านั้น
3) ทำซ้ำ:  "ทำขั้นตอน สั่งกาแฟ" → เล่นซ้ำโดยหาปุ่มจากชื่อ (ไม่ใช่พิกัดตายตัว) ปุ่มอันตรายจะถามก่อนเสมอ
   ลบ: "ลบขั้นตอน สั่งกาแฟ" · ดูทั้งหมด: "ขั้นตอนที่จำไว้"
"""
import json
import re
import subprocess
import threading
import time

import config

_DANGER = re.compile(r"(ลบ|ซื้อ|จ่าย|ชำระ|โอน|สั่งซื้อ|ออกจากระบบ|ล็อกเอาท์|โทร|วิดีโอคอล|ส่ง|โพสต์|แชร์|เผยแพร่|"
                     r"ติดตาม|ยกเลิกการติดตาม|บล็อก|รายงาน|ถูกใจ|ยืนยัน|delete|remove|buy|pay|purchase|order|"
                     r"transfer|log ?out|sign ?out|call|send|post|share|publish|follow|block|report|like|confirm)",
                     re.I)


def _prefs():
    import skills
    return skills


def _items():
    import share_tools
    return share_tools._items()


def _lab(e):
    return (e.get("text") or e.get("desc") or "").strip()


def _app_key(app):
    import phone_tools
    return phone_tools.ALIASES.get(app.strip().lower(), app.strip()).lower()


# ------------------------------------------------------------------ 1) สำรวจแอป

def _nav_items(items, w, h):
    """แท็บ/เมนูหลัก: ปุ่มกดได้ที่ชื่อสั้น อยู่แถบล่างหรือแถบบน"""
    out = []
    for e in items:
        t = _lab(e)
        if not e["click"] or e["edit"] or not t or len(t) > 24 or _DANGER.search(t):
            continue
        if e["y"] > h * 0.86 or e["y"] < h * 0.14:
            out.append(e)
    seen, uniq = set(), []
    for e in sorted(out, key=lambda e: (e["y"] < h * 0.5, e["x"])):
        if _lab(e) not in seen:
            seen.add(_lab(e))
            uniq.append(e)
    return uniq[:8]


# ปุ่มที่เปิดดูหน้าย่อยได้ปลอดภัย (เมนู/ตั้งค่า/โปรไฟล์/ดูเพิ่ม) — กดเพื่อเรียนรู้แล้วกดย้อนกลับ
_SAFE_MORE = re.compile(r"(เมนู|ตั้งค่า|การตั้งค่า|เพิ่มเติม|ดูทั้งหมด|โปรไฟล์|บัญชี|ตัวเลือก|อื่นๆ|ค้นหา|"
                        r"menu|settings|more|options|profile|account|see all|search|⋮|…)", re.I)


def _risky_map(items, w, h):
    """ปุ่มเสี่ยง (โทร/ส่ง/จ่าย/ลบ ฯลฯ) — จำชื่อ+ตำแหน่งไว้ใช้ตอนผู้ใช้สั่ง แต่ไม่กดตอนศึกษา"""
    out = {}
    for e in items:
        t = _lab(e)
        if e["click"] and t and len(t) <= 30 and _DANGER.search(t) and t not in out:
            out[t] = [round(e["x"] / w, 3), round(e["y"] / h, 3)]
    return dict(list(out.items())[:15])


def _explore_more(pkg, items, w, h, amap, ctx, limit=3):
    """กดปุ่มเมนู/ตั้งค่า/ดูเพิ่ม (ปลอดภัย) ทีละปุ่ม เพื่อเรียนรู้หน้าย่อย แล้วกดย้อนกลับ"""
    import phone_tools
    import screen_tools
    done = 0
    for e in items:
        t = _lab(e)
        if done >= limit or not e["click"] or e["edit"] or not t or len(t) > 24 or _DANGER.search(t) \
                or not _SAFE_MORE.search(t) or t in amap.setdefault("pages", {}):
            continue
        screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
        time.sleep(1.2)
        try:
            sub = _items()
        except Exception:  # noqa: BLE001
            sub = []
        if pkg and phone_tools._fg() not in (pkg, None):
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(0.8)
            continue
        if sub:
            amap["pages"][t] = {"x": round(e["x"] / w, 3), "y": round(e["y"] / h, 3), **_page_summary(sub)}
            amap.setdefault("risky", {}).update(_risky_map(sub, w, h))
            _icons(pkg, sub, amap)
        done += 1
        screen_tools.adb_shell(["input", "keyevent", "4"])
        time.sleep(0.9)


def _page_summary(items):
    buttons, fields = [], []
    for e in items:
        t = _lab(e)
        if e["edit"]:
            fields.append(t or e["id"] or "ช่องกรอก")
        elif e["click"] and t and len(t) <= 30 and t not in buttons:
            buttons.append(t)
    return {"buttons": buttons[:25], "fields": fields[:10]}


def _icons(pkg, items, amap):
    """ไอคอนไม่มีชื่อในหน้านี้ → ให้ AI ที่ดูรูปได้ตั้งชื่อ (ถ้ามี Gemini/Claude/Ollama ที่ดูรูปได้)"""
    try:
        import app_tasks
        amap["icons"] = amap.get("icons", 0) + app_tasks.learn_icons(pkg, items)
    except Exception as e:  # noqa: BLE001
        print(f"[explore] icons: {e}", flush=True)


def explore(app, ctx=None, max_tabs=6, key=None, label=None):
    import phone_tools
    import screen_tools
    if not screen_tools.adb_serial():
        return screen_tools.NOT_CONNECTED
    key = key or _app_key(app)
    res = phone_tools.open_app({"app": app, "fresh": True}, ctx)
    if str(res).startswith("ERROR"):
        return f"เปิด {app} ไม่ได้: {res}"
    time.sleep(1.5)
    try:
        root = screen_tools._dump()
        w, h = screen_tools._screen_size(root)
        items = screen_tools._elements(root)
    except Exception as e:  # noqa: BLE001
        return f"อ่านหน้าจอไม่ได้ ({e})"
    pkg = phone_tools._fg() or ""
    amap = {"pkg": pkg, "home": _page_summary(items), "tabs": {}, "at": time.strftime("%Y-%m-%d %H:%M"),
            "risky": _risky_map(items, w, h)}
    tabs = _nav_items(items, w, h)[:max_tabs]
    for t in tabs:
        tlabel = _lab(t)
        if ctx is not None and hasattr(ctx, "status"):
            try:
                ctx.status(f"🔍 ดูแท็บ {tlabel}")
            except Exception:  # noqa: BLE001
                pass
        screen_tools.adb_shell(["input", "tap", str(t["x"]), str(t["y"])])
        time.sleep(1.3)
        try:
            now = _items()
        except Exception:  # noqa: BLE001
            continue
        if pkg and phone_tools._fg() not in (pkg, None):          # หลุดออกนอกแอป → กลับ
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(0.8)
            continue
        amap["tabs"][tlabel] = {"x": round(t["x"] / w, 3), "y": round(t["y"] / h, 3), **_page_summary(now)}
        amap["risky"].update(_risky_map(now, w, h))
        _icons(pkg, now, amap)
        try:
            _explore_more(pkg, now, w, h, amap, ctx)           # เปิดดูเมนู/ตั้งค่าในแท็บนี้ด้วย
        except Exception as ex:  # noqa: BLE001
            print(f"[explore] more: {ex}", flush=True)
    # หน้าแรก: เรียนรู้ไอคอนไม่มีชื่อ + เปิดดูเมนู "สร้างใหม่" (ปุ่ม + / ปุ่มลอย) ว่ามีอะไรให้เลือก
    try:
        import app_tasks
        if pkg:
            phone_tools.open_app({"app": pkg, "fresh": True}, ctx)
            time.sleep(1.5)
        home = _items()
        _icons(pkg, home, amap)
        e = app_tasks._find(home, app_tasks._CREATE.pattern) or app_tasks._fab(home)
        if e and not _DANGER.search(_lab(e)):
            screen_tools.adb_shell(["input", "tap", str(e["x"]), str(e["y"])])
            time.sleep(1.4)
            menu = _items()
            if not pkg or phone_tools._fg() in (pkg, None):
                amap["create_menu"] = {"x": round(e["x"] / w, 3), "y": round(e["y"] / h, 3), **_page_summary(menu)}
                _icons(pkg, menu, amap)
            screen_tools.adb_shell(["input", "keyevent", "4"])
            time.sleep(0.8)
    except Exception as ex:  # noqa: BLE001
        print(f"[explore] create menu: {ex}", flush=True)
    amap["label"] = label or app
    _prefs().set_pref(f"appmap:{key}", amap)
    lines = [f"📚 ศึกษา {app} แล้ว — เจอ {len(amap['tabs'])} แท็บ/เมนู"]
    for k, v in amap["tabs"].items():
        extra = f" · ช่องกรอก: {', '.join(v['fields'][:3])}" if v["fields"] else ""
        lines.append(f"• {k}: {', '.join(v['buttons'][:6])}{extra}")
    if amap.get("create_menu"):
        lines.append(f"• ปุ่มสร้างใหม่ → {', '.join(amap['create_menu']['buttons'][:6])}")
    if amap.get("pages"):
        lines.append(f"• หน้าย่อยที่เปิดดู: {', '.join(list(amap['pages'])[:8])}")
    if amap.get("icons"):
        lines.append(f"• เรียนรู้ไอคอนไม่มีชื่อ {amap['icons']} ปุ่ม (ด้วยการมองภาพ)")
    if amap.get("risky"):
        lines.append(f"• รู้ตำแหน่งปุ่มสำคัญ (จำไว้ แต่ไม่กดตอนศึกษา): {', '.join(list(amap['risky'])[:10])}")
    return "\n".join(lines)


def hints(text):
    """ความรู้ที่เรียนไว้ของแอปที่พูดถึงในคำสั่ง → ส่งให้ AI เป็นแผนที่"""
    import phone_tools
    t = (text or "").lower()
    out = []
    said = {v for a, v in phone_tools.ALIASES.items() if len(a) > 1 and a in t}
    import skills
    for k, amap in (skills._load().get("prefs") or {}).items():
        if not k.startswith("appmap:") or not isinstance(amap, dict) or not amap.get("tabs"):
            continue
        name = k.split(":", 1)[1]
        label = str(amap.get("label") or "").lower()
        if name in said or (len(name) > 2 and name in t) or (len(label) > 2 and label in t):
            tabs = "; ".join(f"{x}: {', '.join(v['buttons'][:8])}" for x, v in list(amap["tabs"].items())[:6])
            out.append(f"[แผนที่แอป {label or name} ที่เคยศึกษา] แท็บ — {tabs}")
            if amap.get("pages"):
                out.append("หน้าย่อย — " + "; ".join(f"{x}: {', '.join(v['buttons'][:6])}"
                                                    for x, v in list(amap["pages"].items())[:5]))
            if amap.get("risky"):
                out.append("ปุ่มโทร/ส่ง/จ่าย ฯลฯ ที่รู้ตำแหน่ง (สัดส่วนจอ x,y) — " +
                           ", ".join(f"{k}@{v[0]},{v[1]}" for k, v in list(amap["risky"].items())[:10]))
            if len(out) >= 2:
                break
    try:
        import app_skills
        k = app_skills.knowledge(text)
        if k:
            out.append(k)
    except Exception:  # noqa: BLE001
        pass
    try:
        import app_brain
        k = app_brain.hints(text)                   # ความรู้แอปที่ศึกษาไว้ตอนติดตั้ง/เจอแอปใหม่
        if k:
            out.append(k)
    except Exception:  # noqa: BLE001
        pass
    flows = _prefs().get_pref("flows") or {}
    for name, f in flows.items():
        if name.lower() in t:
            out.append(f"[ขั้นตอนที่ผู้ใช้สอนไว้ '{name}'] " + " → ".join(_step_text(s) for s in f["steps"]))
    return "\n".join(out)


# ------------------------------------------------------------------ 2) จำขั้นตอนจากการทำให้ดู

def _step_text(s):
    if s["type"] == "type":
        return f"พิมพ์ \"{s['text'][:20]}\""
    if s["type"] == "open":
        return f"เปิด {s['app']}"
    return f"แตะ \"{s.get('label') or '?'}\""


def _rotate(nx, ny, rot):
    """พิกัดสัมผัส (แนวตั้งธรรมชาติของจอ) → พิกัดตามการหมุนจอปัจจุบัน (0-1)"""
    return {0: (nx, ny), 1: (ny, 1 - nx), 2: (1 - nx, 1 - ny), 3: (1 - ny, nx)}.get(rot, (nx, ny))


def _hit(items, x, y):
    """ปุ่มที่ถูกแตะ: กล่องเล็กที่สุดที่ครอบจุดนั้น (เลือกตัวที่มีชื่อ/กดได้ก่อน)"""
    best = None
    for e in items:
        x1, y1, x2, y2 = e["box"]
        if x1 <= x <= x2 and y1 <= y <= y2:
            area = (x2 - x1) * (y2 - y1)
            score = (0 if (_lab(e) or e["edit"]) else 1, area)
            if best is None or score < best[0]:
                best = (score, e)
    return best[1] if best else None


def parse_getevent(lines, maxx, maxy):
    """แปลงบรรทัด getevent -lt → รายการแตะ [(เวลา, nx, ny)] (นิ้วยกขึ้น = แตะเสร็จ)"""
    taps, x, y, down = [], None, None, None
    for ln in lines:
        m = re.search(r"\[\s*([\d.]+)\].*?(ABS_MT_POSITION_X|ABS_MT_POSITION_Y|BTN_TOUCH)\s+(\w+)", ln)
        if not m:
            continue
        ts, kind, val = float(m.group(1)), m.group(2), m.group(3)
        if kind == "ABS_MT_POSITION_X":
            x = int(val, 16)
            down = down or (ts, x, y)
        elif kind == "ABS_MT_POSITION_Y":
            y = int(val, 16)
        elif val == "DOWN":
            down = (ts, x, y)
        elif val == "UP" and x is not None and y is not None:
            sx, sy = (down[1], down[2]) if down and down[1] is not None and down[2] is not None else (x, y)
            if abs(sx - x) < maxx * 0.04 and abs(sy - y) < maxy * 0.04:      # แตะ (ไม่ใช่ปัด)
                taps.append((ts, x / maxx, y / maxy))
            down = None
    return taps


class Recorder:
    def __init__(self, name):
        self.name = name
        self.steps = []
        self.snap = []          # [(เวลาเครื่อง, items, w, h)] หน้าจอล่าสุดก่อนแตะ
        self.stop_ev = threading.Event()
        self.proc = None
        self.pending_edit = None
        self.start_pkg = None

    def _shot(self):
        import screen_tools
        root = screen_tools._dump()
        w, h = screen_tools._screen_size(root)
        return time.time(), screen_tools._elements(root), w, h

    def _poll(self):
        while not self.stop_ev.is_set():
            try:
                self.snap = (self.snap + [self._shot()])[-4:]
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
            time.sleep(0.3)

    def _touch_dev(self):
        import screen_tools
        out = screen_tools.adb_shell(["getevent", "-lp"], timeout=10)
        dev, maxx, maxy, best = None, None, None, None
        for ln in out.splitlines():
            m = re.match(r"add device \d+:\s*(\S+)", ln)
            if m:
                dev, maxx, maxy = m.group(1), None, None
            mx = re.search(r"ABS_MT_POSITION_X.*?max (\d+)", ln)
            my = re.search(r"ABS_MT_POSITION_Y.*?max (\d+)", ln)
            if mx:
                maxx = int(mx.group(1))
            if my:
                maxy = int(my.group(1))
            if dev and maxx and maxy and not best:
                best = (dev, maxx, maxy)
        return best

    def _rotation(self):
        import screen_tools
        out = screen_tools.adb_shell(["sh", "-c", "dumpsys input | grep -m1 SurfaceOrientation"],
                                     timeout=8, quote=True)
        m = re.search(r"SurfaceOrientation:\s*(\d)", out)
        return int(m.group(1)) if m else 0

    def _flush_edit(self, items):
        """ช่องที่แตะไว้ก่อนหน้า มีข้อความเปลี่ยน → บันทึกเป็นขั้น "พิมพ์" """
        pe = self.pending_edit
        if not pe:
            return
        self.pending_edit = None
        for e in items:
            if e["edit"] and (e["id"] == pe["id"] or abs(e["y"] - pe["y"]) < 30):
                txt = (e["text"] or "").strip()
                if txt and txt != pe["before"]:
                    self.steps.append({"type": "type", "text": txt, "field": pe["label"]})
                return

    def _on_tap(self, nx, ny):
        snap = self.snap[-1] if self.snap else None
        if not snap:
            return
        _, items, w, h = snap
        rx, ry = _rotate(nx, ny, self.rot)
        x, y = int(rx * w), int(ry * h)
        self._flush_edit(items)
        e = _hit(items, x, y)
        step = {"type": "tap", "rx": round(x / w, 3), "ry": round(y / h, 3)}
        if e:
            step.update(label=_lab(e)[:40], id=e["id"], edit=e["edit"])
            if e["edit"]:
                self.pending_edit = {"id": e["id"], "y": e["y"], "before": (e["text"] or "").strip(),
                                     "label": _lab(e)}
        self.steps.append(step)
        print(f"[learn] แตะ {step.get('label') or (step['rx'], step['ry'])}", flush=True)

    def start(self):
        import phone_tools
        import screen_tools
        dev = self._touch_dev()
        if not dev:
            raise RuntimeError("อ่านการแตะจอไม่ได้ (getevent) — ADB ต้องเชื่อมอยู่")
        self.dev, self.maxx, self.maxy = dev
        self.rot = self._rotation()
        self.start_pkg = phone_tools._fg()
        threading.Thread(target=self._poll, daemon=True).start()
        serial = screen_tools.adb_serial()
        self.proc = subprocess.Popen(["adb", "-s", serial, "shell", "getevent", "-lt", self.dev],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = []
        for ln in self.proc.stdout:
            if self.stop_ev.is_set():
                break
            buf.append(ln)
            if "BTN_TOUCH" in ln and "UP" in ln:
                for _, nx, ny in parse_getevent(buf, self.maxx, self.maxy):
                    try:
                        self._on_tap(nx, ny)
                    except Exception as e:  # noqa: BLE001
                        print(f"[learn] ❗ {e}", flush=True)
                buf = []

    def stop(self):
        try:
            self._flush_edit(self._shot()[1])
        except Exception:  # noqa: BLE001
            pass
        self.stop_ev.set()
        if self.proc:
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        steps = [s for s in self.steps if s.get("label") or s["type"] != "tap" or s.get("rx") is not None]
        if self.start_pkg:
            steps.insert(0, {"type": "open", "app": self.start_pkg})
        return steps


class AppRecorder:
    """โหมดแอป APK: จับการแตะ/พิมพ์จาก Accessibility events (แม่นกว่า getevent — รู้ชื่อปุ่มที่แตะจริง)"""

    def __init__(self, name):
        self.name = name
        self.start_pkg = None

    def start(self):
        import android_shim
        import phone_tools
        self.b = android_shim.bridge()
        self.start_pkg = phone_tools._fg()
        self.b.recordStart()

    @staticmethod
    def convert(events, w, h, start_pkg=None):
        steps = []
        for ev in events:
            if ev.get("type") == "click":
                label = (ev.get("text") or ev.get("desc") or "").strip()[:40]
                st = {"type": "tap", "label": label, "id": ev.get("id") or "", "edit": bool(ev.get("edit")),
                      "rx": round(ev.get("x", 0) / max(1, w), 3), "ry": round(ev.get("y", 0) / max(1, h), 3)}
                steps.append(st)
            elif ev.get("type") == "text":
                txt = ev.get("text") or ""
                if steps and steps[-1]["type"] == "type" and steps[-1].get("id") == ev.get("id"):
                    steps[-1]["text"] = txt                     # พิมพ์ต่อเนื่องช่องเดิม → เก็บข้อความสุดท้าย
                elif txt:
                    steps.append({"type": "type", "text": txt, "id": ev.get("id") or ""})
        steps = [x for x in steps if x["type"] != "type" or x["text"].strip()]
        if start_pkg:
            steps.insert(0, {"type": "open", "app": start_pkg})
        return steps

    def stop(self):
        self.b.recordStop()
        try:
            w, h = (int(v) for v in str(self.b.screenSize()).split("x"))
        except ValueError:
            w, h = 1600, 2560
        return self.convert(json.loads(str(self.b.pollEvents())), w, h, self.start_pkg)


_rec = {"r": None}


def record_start(name, ctx=None):
    if _rec["r"]:
        return f"กำลังจำขั้นตอน \"{_rec['r'].name}\" อยู่ — พูด \"จบขั้นตอน\" ก่อนนะ"
    import screen_tools
    if not screen_tools.adb_serial():
        return screen_tools.NOT_CONNECTED
    r = AppRecorder(name) if config.ANDROID_APP else Recorder(name)
    try:
        r.start()
    except Exception as e:  # noqa: BLE001
        return f"เริ่มจำไม่ได้: {e}"
    _rec["r"] = r
    return (f"🎬 เริ่มจำขั้นตอน \"{name}\" แล้ว — ทำบนจอให้ดูได้เลย (แตะ/พิมพ์ตามปกติ ช้าๆ ทีละขั้น)\n"
            "เสร็จแล้วพูด/พิมพ์ \"จบขั้นตอน\" · ยกเลิก: \"ยกเลิกจำขั้นตอน\"")


def record_stop(ctx=None, cancel=False):
    r = _rec["r"]
    if not r:
        return "ตอนนี้ไม่ได้จำขั้นตอนอะไรอยู่"
    _rec["r"] = None
    steps = r.stop()
    if cancel:
        return "ยกเลิกการจำขั้นตอนแล้ว ไม่ได้บันทึกอะไร"
    if len(steps) < 2:
        return "ยังไม่เห็นการแตะบนจอเลย — ไม่ได้บันทึก (ลองใหม่ แตะช้าๆ ทีละขั้น)"
    plan = "\n".join(f"{i + 1}. {_step_text(s)}" for i, s in enumerate(steps))
    ok = ctx.confirm(f"ขั้นตอน \"{r.name}\":\n{plan}\n\nบันทึกไว้ใช้ซ้ำไหม?") \
        if ctx is not None and hasattr(ctx, "confirm") else True
    if not ok:
        return "ไม่บันทึกขั้นตอนนี้"
    flows = _prefs().get_pref("flows") or {}
    flows[r.name] = {"steps": steps, "at": time.strftime("%Y-%m-%d %H:%M")}
    _prefs().set_pref("flows", flows)
    return f"✅ จำขั้นตอน \"{r.name}\" แล้ว ({len(steps)} ขั้น) — สั่ง \"ทำขั้นตอน {r.name}\" ได้เลย"


def _find(step, items):
    lab, rid = step.get("label"), step.get("id")
    for e in items:
        if lab and _lab(e) == lab:
            return e
    for e in items:
        if rid and e["id"] == rid and (not lab or lab in _lab(e) or not _lab(e)):
            return e
    for e in items:
        if lab and len(lab) > 2 and lab.lower() in _lab(e).lower():
            return e
    return None


def replay(name, ctx=None):
    import phone_tools
    import screen_tools
    flows = _prefs().get_pref("flows") or {}
    key = next((k for k in flows if k.lower() == name.lower()), None) or \
        next((k for k in flows if name.lower() in k.lower() or k.lower() in name.lower()), None)
    if not key:
        return f"ยังไม่มีขั้นตอนชื่อ \"{name}\" (มี: {', '.join(flows) or '-'})"
    if not screen_tools.adb_serial():
        return screen_tools.NOT_CONNECTED
    done = []
    for i, s in enumerate(flows[key]["steps"]):
        if s["type"] == "open":
            phone_tools._sh(["monkey", "-p", s["app"], "-c", "android.intent.category.LAUNCHER", "1"])
            time.sleep(2.0)
            done.append(_step_text(s))
            continue
        if s["type"] == "type":
            screen_tools.type_text({"text": s["text"], "send": False, "replace": True}, ctx)
            done.append(_step_text(s))
            time.sleep(0.5)
            continue
        e = None
        for _ in range(3):                                   # รอหน้าโหลด
            try:
                root = screen_tools._dump()
                w, h = screen_tools._screen_size(root)
                e = _find(s, screen_tools._elements(root))
            except Exception:  # noqa: BLE001
                w, h = 1600, 2560
            if e or not s.get("label"):
                break
            time.sleep(1.0)
        x, y = (e["x"], e["y"]) if e else (int(s["rx"] * w), int(s["ry"] * h))
        lab = s.get("label") or ""
        if _DANGER.search(lab) and ctx is not None and hasattr(ctx, "confirm"):
            if not ctx.confirm(f"ขั้นที่ {i + 1}: จะกด \"{lab}\" ใช่ไหม?"):
                return f"หยุดก่อนกด \"{lab}\" (ทำไปแล้ว: {' → '.join(done)})"
        screen_tools.adb_shell(["input", "tap", str(x), str(y)])
        done.append(_step_text(s) + ("" if e or not lab else " (ตามตำแหน่งเดิม)"))
        time.sleep(1.0)
    return f"✅ ทำขั้นตอน \"{key}\" แล้ว: " + " → ".join(done)


def list_flows():
    flows = _prefs().get_pref("flows") or {}
    import skills
    maps = [k.split(":", 1)[1] for k in (skills._load().get("prefs") or {}) if k.startswith("appmap:")]
    out = []
    if flows:
        out.append("🎬 ขั้นตอนที่สอนไว้:\n" + "\n".join(f"• {k} ({len(v['steps'])} ขั้น)" for k, v in flows.items()))
    if maps:
        out.append("📚 แอปที่ศึกษาแล้ว: " + ", ".join(maps))
    return "\n".join(out) or "ยังไม่มีขั้นตอน/แอปที่เรียนไว้ — ลอง \"ศึกษาแอป instagram\" หรือ \"จำขั้นตอน ...\""


def forget_flow(name):
    flows = _prefs().get_pref("flows") or {}
    key = next((k for k in flows if k.lower() == name.lower()), None)
    if not key:
        return f"ไม่มีขั้นตอนชื่อ \"{name}\""
    del flows[key]
    _prefs().set_pref("flows", flows)
    return f"ลบขั้นตอน \"{key}\" แล้ว"


# แอปที่ไม่สำรวจเอง (การเงิน/ความปลอดภัย/ระบบ) — กันกดอะไรผิดในแอปสำคัญ
_SKIP = re.compile(r"(bank|wallet|pay|krungthai|scb|kbank|kplus|bualuang|ttb|krungsri|gsb|baac|truemoney|paotang|"
                   r"เป๋าตัง|ธนาคาร|ทรูมันนี่|กรุงไทย|กสิกร|ไทยพาณิชย์|authenticator|password|vpn|settings|ตั้งค่า|"
                   r"phone|dialer|โทรศัพท์|contacts|รายชื่อ|camera|กล้อง|update|อัปเดต|termux|ผู้ช่วย ai|aibot|"
                   r"com\.android\.|com\.huawei\.(?!browser)|com\.hihonor|launcher)", re.I)
_all = {"running": False}


def explore_all(ctx=None, limit=40):
    """ศึกษาทุกแอปในเครื่องเบื้องหลัง (ข้ามแอปการเงิน/ระบบ) — แจ้งผลทีละแอป"""
    import threading
    import app_index
    import screen_tools
    if _all["running"]:
        return "กำลังศึกษาแอปอยู่แล้ว รอให้เสร็จก่อนนะ"
    if not screen_tools.adb_serial():
        return screen_tools.NOT_CONNECTED
    apps = app_index.load() or app_index.build()
    todo = [a for a in apps if a.get("pkg") and not _SKIP.search(f"{a.get('label', '')} {a['pkg']}")][:limit]
    if not todo:
        return "ไม่เจอแอปที่จะศึกษา"
    mins = max(1, len(todo) * 18 // 60)
    if ctx is not None and hasattr(ctx, "confirm") and not ctx.confirm(
            f"จะเปิดทีละแอป {len(todo)} แอป แล้วแตะดูแท็บ/เมนู (ไม่กดปุ่มเสี่ยง ข้ามแอปธนาคาร/ระบบ)\n"
            f"ใช้เวลาประมาณ {mins} นาที — ระหว่างนี้อย่าใช้เครื่อง เริ่มเลยไหม?"):
        return "ยกเลิกการศึกษาทุกแอปแล้ว"

    def run():
        _all["running"] = True
        done, failed = [], []
        try:
            for i, a in enumerate(todo):
                label = a.get("label") or a["pkg"].split(".")[-1]
                try:
                    r = explore(a["pkg"], ctx, max_tabs=5, key=label.lower(), label=label)
                    (done if r.startswith("📚") else failed).append(label)
                except Exception as e:  # noqa: BLE001
                    failed.append(label)
                    print(f"[learn] {label}: {e}", flush=True)
                screen_tools.adb_shell(["input", "keyevent", "3"])
                time.sleep(0.8)
                if ctx is not None and hasattr(ctx, "status"):
                    try:
                        ctx.status(f"📚 ศึกษาแอป {i + 1}/{len(todo)}: {label}")
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            _all["running"] = False
        msg = f"✅ ศึกษาเสร็จ {len(done)} แอป" + (f" · เปิดไม่ได้ {len(failed)}: {', '.join(failed[:8])}" if failed else "")
        if ctx is not None and hasattr(ctx, "notify"):
            ctx.notify(msg + "\nต่อไปสั่งงานในแอปเหล่านี้ ผู้ช่วยจะรู้ว่าปุ่มอยู่ตรงไหน")
    threading.Thread(target=run, daemon=True).start()
    return f"📚 เริ่มศึกษา {len(todo)} แอปเบื้องหลังแล้ว (~{mins} นาที) จะแจ้งเมื่อเสร็จ"


_ALL = re.compile(r"^(?:ช่วย)?\s*(?:ศึกษา|เรียนรู้|สำรวจ)\s*(?:ทุกแอป(?:พ)?|แอป(?:พ)?ทั้งหมด|ทุกแอป(?:พ)?ในเครื่อง)")
_EXPLORE = re.compile(r"^(?:ช่วย)?\s*(?:ศึกษา|เรียนรู้|สำรวจ)\s*แอป(?:พ)?\s*(?P<app>.+)$", re.I)
_REC = re.compile(r"^(?:เริ่ม)?\s*จำ\s*ขั้นตอน\s*(?:ชื่อ)?\s*(?P<name>.+)$")
_STOP = re.compile(r"^(จบ|หยุด|เสร็จ)\s*(การ)?\s*(จำ)?\s*ขั้นตอน|^(จบ|หยุดจำ)$")
_CANCEL = re.compile(r"^ยกเลิก\s*(การ)?\s*จำ\s*ขั้นตอน")
_PLAY = re.compile(r"^(?:ทำ|เล่น|รัน)\s*ขั้นตอน\s*(?P<name>.+)$")
_DEL = re.compile(r"^(?:ลบ|ลืม)\s*ขั้นตอน\s*(?P<name>.+)$")
_LIST = re.compile(r"^(?:ขั้นตอน(?:ที่)?(?:จำ|สอน)ไว้|ดูขั้นตอน(?:ทั้งหมด)?|แอปที่ศึกษาแล้ว)$")


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split())
    t = re.sub(r"\s*(ให้หน่อย|หน่อย|ที|ครับ|ค่ะ|คะ|นะ|จ้า)+\s*[.!?]*$", "", t).strip(" .!?")
    if not t:
        return None
    if _rec["r"] and _CANCEL.search(t):
        return record_stop(ctx, cancel=True)
    if _rec["r"] and _STOP.search(t):
        return record_stop(ctx)
    if _ALL.match(t):
        return explore_all(ctx)
    for rx, fn in ((_LIST, lambda m: list_flows()),
                   (_DEL, lambda m: forget_flow(m.group("name").strip())),
                   (_PLAY, lambda m: replay(m.group("name").strip(), ctx)),
                   (_REC, lambda m: record_start(m.group("name").strip(), ctx)),
                   (_EXPLORE, lambda m: explore(m.group("app").strip(), ctx))):
        m = rx.match(t)
        if m:
            return fn(m)
    return None

