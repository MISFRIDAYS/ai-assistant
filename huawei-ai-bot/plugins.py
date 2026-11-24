"""เพิ่มความสามารถใหม่ให้ตัวเอง — สั่งเป็นภาษาพูด แล้วผู้ช่วยเขียนโค้ดความสามารถนั้นเอง ใช้ได้ทันทีไม่ต้องรีสตาร์ท

  "เพิ่มความสามารถ: ทุกครั้งที่บอกว่า 'โหมดนอน' ให้ปิด wifi ลดเสียง เปิดห้ามรบกวน"
  "สร้างระบบใหม่ ถามว่า 'วันนี้วันพระไหม' แล้วตอบจากปฏิทินจันทรคติ"
  "ความสามารถที่เพิ่มเอง" · "ปิดความสามารถ โหมดนอน" · "ลบความสามารถ โหมดนอน" · "แก้ความสามารถ โหมดนอน: ให้ปิดบลูทูธด้วย"

ความปลอดภัย (ความสามารถที่สร้างเองถูกขังไว้ในกรอบ):
- เขียนได้แค่ Python ล้วนกับไลบรารีพื้นฐาน (re json time datetime math random ...) — ห้าม import os/sys/subprocess/socket/requests
- ห้าม open/eval/exec/__import__/getattr และชื่อที่ขึ้นต้นด้วย __ (กันหลุดกรอบ)
- คุมเครื่องได้ผ่าน api.tool(...) เท่านั้น = เครื่องมือเดียวกับที่ผู้ช่วยใช้ → การยืนยันก่อนจ่ายเงิน/ลบ/ส่ง ยังทำงานครบ
- ทดสอบกับตัวอย่างก่อน → ให้เจ้าของดูสรุปแล้วกดอนุญาต → ถึงจะเปิดใช้
- error ซ้ำ 3 ครั้ง → ปิดตัวเองอัตโนมัติ แล้วพยายามซ่อมตัวเอง (ถามก่อนใช้)
เก็บที่ data/plugins/ (อยู่รอดแม้อัปเดตแอป)
"""
import ast
import json
import os
import re
import threading
import time

import config

DIR = os.path.join(config.DATA_DIR, "plugins")
ALLOWED_IMPORTS = {"re", "json", "time", "datetime", "math", "random", "statistics", "collections", "itertools",
                   "functools", "string", "textwrap", "difflib", "unicodedata", "calendar", "zoneinfo"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                "delattr", "input", "breakpoint", "help", "memoryview", "type", "object", "super", "classmethod",
                "staticmethod", "property", "exit", "quit"}
SAFE_BUILTINS = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k) for k in (
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "range", "enumerate", "zip", "min", "max",
    "sum", "sorted", "reversed", "any", "all", "abs", "round", "isinstance", "print", "map", "filter", "repr",
    "Exception", "ValueError", "KeyError", "IndexError", "TypeError", "RuntimeError", "divmod", "pow", "chr", "ord",
    "hasattr", "frozenset", "format", "iter", "next", "slice", "hash")}
_depth = threading.local()   # api.chat → ผู้ช่วย → ความสามารถเดิม วนซ้ำไม่ได้
_loaded = {}            # slug → {"mod": dict, "meta": {...}, "rx": [compiled]}
_lock = threading.RLock()


# ================================================================ ตรวจความปลอดภัยของโค้ด

def check_code(src):
    """→ (ok, เหตุผล)"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, f"โค้ดผิดไวยากรณ์: {e}"
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for name in names:
                if name.split(".")[0] not in ALLOWED_IMPORTS:
                    return False, f"ห้าม import {name}"
        elif isinstance(n, ast.Name) and (n.id in BANNED_NAMES or n.id.startswith("__")):
            return False, f"ห้ามใช้ {n.id}"
        elif isinstance(n, ast.Attribute) and n.attr.startswith("_"):
            return False, f"ห้ามเข้าถึง .{n.attr}"
        elif isinstance(n, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)):
            return False, "ห้ามใช้ global/nonlocal/async"
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (
                "__" in n.value or re.search(r"\{[^{}]*[.\[]\s*_", n.value)):
            return False, "ห้ามใช้ชื่อพิเศษ/ชื่อที่ขึ้นต้นด้วย _ ในข้อความ"
    fns = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "run" not in fns:
        return False, "ต้องมีฟังก์ชัน run(text, api)"
    return True, ""


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"ห้าม import {name}")
    return __import__(name, globals, locals, fromlist, level)


def _exec(src):
    env = {"__builtins__": dict(SAFE_BUILTINS, __import__=_safe_import), "__name__": "plugin"}
    exec(compile(src, "<plugin>", "exec"), env)  # noqa: S102 — ตรวจด้วย check_code แล้ว + builtins จำกัด
    return env


# ================================================================ สิ่งที่ความสามารถใช้ได้ (api)

class Api:
    """ทางเดียวที่ความสามารถที่สร้างเองแตะเครื่องได้"""

    def __init__(self, slug, ctx=None, fake=False):
        # ชื่อขึ้นต้นด้วย _ → โค้ดความสามารถเข้าถึง/แก้ไม่ได้ (กันปิดการยืนยันของ ctx)
        self._slug, self._ctx, self._fake = slug, ctx, fake
        self._calls = []
        self.data = _load_data(slug)

    def tool(self, name, **args):
        """เรียกเครื่องมือของผู้ช่วย เช่น api.tool("wifi", on=False) · api.tool("open_app", app="LINE")
        เครื่องมือเสี่ยงจะถามเจ้าของก่อนเสมอ"""
        self._calls.append((name, args))
        if self._fake:
            return "OK (ทดสอบ)"
        import agent
        r = agent.execute_tool({"name": name, "input": args, "id": "plugin"}, self._ctx or _NullCtx())
        c = r.get("content")
        return c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))

    def say(self, text):
        """ส่งข้อความหาเจ้าของ (แชท/แจ้งเตือน)"""
        self._calls.append(("say", text))
        if not self._fake and self._ctx is not None and hasattr(self._ctx, "notify"):
            self._ctx.notify(str(text))

    def ask_ai(self, prompt):
        """ถาม AI แล้วได้คำตอบเป็นข้อความ"""
        self._calls.append(("ask_ai", prompt))
        if self._fake:
            return "คำตอบทดสอบ"
        import agent
        resp, _ = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": str(prompt)}]}], [],
                                 system=agent.chat_prompt())
        return agent._collect_text(resp.get("content", []))

    def search(self, query):
        """ค้นเว็บ → ข้อความสรุปผล"""
        self._calls.append(("search", query))
        if self._fake:
            return "ผลค้นหาทดสอบ"
        import websearch
        return websearch.search(str(query))

    def chat(self, text):
        """ส่งคำสั่งภาษาพูดให้ผู้ช่วยทำ เหมือนผู้ใช้พิมพ์เอง เช่น api.chat("เปิดเพลงผ่อนคลายใน youtube")"""
        self._calls.append(("chat", text))
        if self._fake:
            return "OK (ทดสอบ)"
        import quick
        _depth.n = getattr(_depth, "n", 0) + 1
        try:
            return quick.handle(str(text), self._ctx) or ""
        finally:
            _depth.n -= 1

    def now(self):
        import datetime
        return datetime.datetime.utcnow() + datetime.timedelta(hours=config.TIMEZONE_OFFSET_HOURS)

    def save(self):
        """บันทึก api.data (dict) ลงเครื่อง ใช้จำค่าระหว่างครั้ง"""
        if not self._fake:
            _save_data(self._slug, self.data)


class _NullCtx:
    def status(self, *_):
        pass

    def notify(self, *_):
        pass

    def confirm(self, *_):
        return False

    def send_photo(self, *_):
        pass


def _data_path(slug):
    return os.path.join(DIR, f"{slug}.data.json")


def _load_data(slug):
    try:
        with open(_data_path(slug), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_data(slug, data):
    os.makedirs(DIR, exist_ok=True)
    s = json.dumps(data, ensure_ascii=False)
    if len(s) < 200_000:
        with open(_data_path(slug), "w", encoding="utf-8") as f:
            f.write(s)


# ================================================================ เก็บ / โหลด

def _meta_path(slug):
    return os.path.join(DIR, f"{slug}.json")


def _code_path(slug):
    return os.path.join(DIR, f"{slug}.py")


def all_meta():
    out = {}
    if not os.path.isdir(DIR):
        return out
    for f in sorted(os.listdir(DIR)):
        if f.endswith(".json") and not f.endswith(".data.json"):
            try:
                with open(os.path.join(DIR, f), encoding="utf-8") as fh:
                    m = json.load(fh)
                out[m["slug"]] = m
            except (OSError, ValueError, KeyError):
                pass
    return out


def _save_meta(m):
    os.makedirs(DIR, exist_ok=True)
    with open(_meta_path(m["slug"]), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def load_all():
    with _lock:
        _loaded.clear()
        for slug, m in all_meta().items():
            if not m.get("enabled", True):
                continue
            try:
                with open(_code_path(slug), encoding="utf-8") as f:
                    src = f.read()
                ok, why = check_code(src)
                if not ok:
                    raise ValueError(why)
                _loaded[slug] = {"env": _exec(src), "meta": m,
                                 "rx": [re.compile(r, re.I) for r in m.get("triggers", [])]}
            except Exception as e:  # noqa: BLE001
                print(f"[plugins] โหลด {slug} ไม่ได้: {e}", flush=True)
    return len(_loaded)


def _ensure():
    if not _loaded and os.path.isdir(DIR):
        load_all()


# ================================================================ สร้างด้วย AI

GUIDE = """เขียนความสามารถใหม่ให้ผู้ช่วย AI ภาษาไทยบนแท็บเล็ต Huawei (Android) เป็น Python ล้วน

รูปแบบ (บังคับ):
```python
import re  # ได้เฉพาะ re json time datetime math random statistics collections itertools functools string textwrap difflib calendar

def run(text, api):
    # text = ข้อความที่ผู้ใช้พูด/พิมพ์ (ตรงกับ triggers แล้ว)
    # คืนข้อความตอบผู้ใช้ภาษาไทยสั้นๆ (str) หรือ None ถ้าไม่ใช่เรื่องของความสามารถนี้
    ...
```
api ที่ใช้ได้ (ทางเดียวที่แตะเครื่องได้):
- api.tool(ชื่อ, **args) → str : เรียกเครื่องมือ เช่น
  wifi(on, minutes?) bluetooth(on) do_not_disturb(on) brightness(level="50%"/"auto"/"+20%") volume_step(direction="up"/"down"/"mute")
  set_volume(stream="music", volume=0-15) flashlight(on) rotate_screen(auto) open_app(app, page?) close_app(app)
  play_media(query, app?) search_in_app(app, query) navigate(place) send_dm(app, to, text) read_screen() tap_text(text)
  type_text(text, send?) swipe(direction) press_key(button) list_notifications() device_setting(name, on?) tablet_info()
  set_reminder(minutes, text) remember(text) web_search(query)
- api.chat(คำสั่งภาษาพูด) → str : ให้ผู้ช่วยทำคำสั่งเหมือนผู้ใช้พิมพ์เอง (ใช้เมื่อไม่แน่ใจชื่อเครื่องมือ)
- api.ask_ai(prompt) → str · api.search(query) → str · api.say(text) · api.now() → datetime (เวลาไทย)
- api.data (dict จำค่าข้ามครั้ง) + api.save()
ห้าม: import อื่น, open/eval/exec/getattr, ชื่อหรือ attribute ที่ขึ้นต้นด้วย _ , global, async, ลูปไม่รู้จบ, time.sleep เกิน 5 วินาที
ตอบเป็น JSON อย่างเดียว:
{"slug": "ชื่ออังกฤษตัวเล็ก_ขีดล่าง", "name": "ชื่อไทยสั้นๆ", "desc": "ทำอะไร 1 ประโยค",
 "triggers": ["regex ภาษาไทยที่จับคำสั่งนี้ (เฉพาะเจาะจง ไม่กว้างจนแย่งคำสั่งอื่น)"],
 "examples": [{"say": "ตัวอย่างคำพูดผู้ใช้", "expect_tools": ["ชื่อเครื่องมือที่ควรถูกเรียก"]}],
 "code": "โค้ด python ทั้งไฟล์"}"""


def _ai(prompt):
    import self_heal
    return self_heal._json(self_heal._llm("คุณคือวิศวกร Python ที่เขียนโค้ดสั้น ปลอดภัย ถูกต้อง ตอบเป็น JSON เท่านั้น",
                                          prompt, 6000))


def test_plugin(spec):
    """ทดลองรันกับตัวอย่าง (เครื่องมือจำลอง ไม่แตะเครื่องจริง) → (ok, รายงาน)"""
    src = spec.get("code") or ""
    ok, why = check_code(src)
    if not ok:
        return False, why
    try:
        rxs = [re.compile(r, re.I) for r in spec.get("triggers") or []]
    except re.error as e:
        return False, f"triggers ผิด: {e}"
    if not rxs:
        return False, "ไม่มี triggers"
    if any(r.search("") or r.search("สวัสดี") or r.search("เปิดไลน์") for r in rxs):
        return False, "triggers กว้างเกินไป (จับคำทั่วไปได้) จะแย่งคำสั่งอื่น"
    try:
        env = _exec(src)
    except Exception as e:  # noqa: BLE001
        return False, f"โหลดโค้ดไม่ได้: {e}"
    report = []
    for ex in (spec.get("examples") or [])[:5]:
        say = str(ex.get("say", ""))
        if not any(r.search(say) for r in rxs):
            return False, f"ตัวอย่าง '{say}' ไม่ตรงกับ triggers"
        api = Api(spec.get("slug", "x"), fake=True)
        box = {}

        def go():
            try:
                box["r"] = env["run"](say, api)
            except Exception as e:  # noqa: BLE001
                box["e"] = e
        th = threading.Thread(target=go, daemon=True)
        th.start()
        th.join(8)
        if th.is_alive():
            return False, f"'{say}' ทำงานนานเกิน 8 วินาที (อาจวนไม่รู้จบ)"
        if "e" in box:
            return False, f"'{say}' error: {type(box['e']).__name__}: {box['e']}"
        used = [c[0] for c in api._calls]
        miss = [t for t in ex.get("expect_tools") or [] if t not in used and not any(t in str(c) for c in api._calls)]
        if miss:
            return False, f"'{say}' ไม่ได้เรียก {miss} (เรียก: {used})"
        report.append(f"• \"{say}\" → {', '.join(used) or '-'} → {str(box.get('r'))[:60]}")
    if not report:
        return False, "ไม่มีตัวอย่างให้ทดสอบ"
    return True, "\n".join(report)


def create(request, ctx=None, base=None, status=None):
    """คำขอภาษาพูด → AI เขียน → ตรวจ → ทดสอบ → ถามเจ้าของ → ใช้ได้ทันที"""
    say = status or (lambda t: None)
    feedback = ""
    spec = None
    for attempt in range(3):
        say(f"🧩 กำลังเขียนความสามารถใหม่ (รอบ {attempt + 1})…")
        prompt = GUIDE + f"\n\nสิ่งที่ผู้ใช้ต้องการ: {request}"
        if base:
            prompt += f"\n\nปรับปรุงจากของเดิม (slug เดิม {base['slug']}):\n{base.get('code', '')}"
        if feedback:
            prompt += f"\n\nรอบก่อนไม่ผ่าน: {feedback}\nแก้ให้ผ่าน"
        try:
            spec = _ai(prompt)
        except Exception as e:  # noqa: BLE001
            feedback = f"ตอบไม่เป็น JSON ที่ถูกต้อง ({e})"
            continue
        if base:
            spec["slug"] = base["slug"]
        spec["slug"] = re.sub(r"[^a-z0-9_]", "_", str(spec.get("slug") or "skill").lower())[:40].strip("_") or "skill"
        ok, rep = test_plugin(spec)
        if ok:
            break
        feedback = rep
    else:
        return f"❌ สร้างความสามารถไม่สำเร็จ (ทดสอบไม่ผ่าน 3 รอบ): {feedback[:300]}\nลองอธิบายให้ชัดขึ้น หรือแบ่งเป็นขั้นๆ"
    summary = (f"🧩 ความสามารถใหม่: **{spec.get('name')}**\n{spec.get('desc', '')}\n"
               f"เรียกใช้เมื่อพูดว่า: {', '.join(spec.get('triggers', [])[:3])}\nผลทดสอบ:\n{rep}")
    conf = getattr(ctx, "confirm", None)
    if conf is None or not conf(summary + "\n\nเปิดใช้ความสามารถนี้เลยไหม?"):
        return summary + "\n\n(ยังไม่ได้เปิดใช้)"
    install(spec)
    return summary + "\n\n✅ เปิดใช้แล้ว ลองพูดได้เลย"


def install(spec):
    os.makedirs(DIR, exist_ok=True)
    with open(_code_path(spec["slug"]), "w", encoding="utf-8") as f:
        f.write(spec["code"])
    _save_meta({"slug": spec["slug"], "name": spec.get("name", spec["slug"]), "desc": spec.get("desc", ""),
                "triggers": spec.get("triggers", []), "examples": spec.get("examples", []),
                "enabled": True, "errors": 0, "created": time.strftime("%Y-%m-%d %H:%M")})
    load_all()


def _find(name):
    name = (name or "").strip().lower()
    for slug, m in all_meta().items():
        if name and (name == slug or name in m.get("name", "").lower() or m.get("name", "").lower() in name):
            return m
    return None


def set_enabled(m, on):
    m["enabled"] = on
    if on:
        m["errors"] = 0
    _save_meta(m)
    load_all()


def remove(m):
    for p in (_code_path(m["slug"]), _meta_path(m["slug"]), _data_path(m["slug"])):
        try:
            os.remove(p)
        except OSError:
            pass
    load_all()


def _failed(slug, err, ctx):
    m = all_meta().get(slug)
    if not m:
        return
    m["errors"] = m.get("errors", 0) + 1
    m["last_error"] = str(err)[:300]
    _save_meta(m)
    if m["errors"] >= 3:
        set_enabled(m, False)
        msg = (f"⚠️ ความสามารถ \"{m['name']}\" error ซ้ำ 3 ครั้ง ปิดไว้ก่อนแล้ว\n({m['last_error'][:120]})\n"
               f"สั่ง \"แก้ความสามารถ {m['name']}\" ให้ผู้ช่วยซ่อมเองได้")
        if ctx is not None and hasattr(ctx, "notify"):
            ctx.notify(msg)


# ================================================================ ใช้งาน

def handle_plugins(text, ctx=None):
    if getattr(_depth, "n", 0) > 0:
        return None
    _ensure()
    for slug, p in list(_loaded.items()):
        if not any(r.search(text) for r in p["rx"]):
            continue
        api = Api(slug, ctx)
        try:
            r = p["env"]["run"](text, api)
        except Exception as e:  # noqa: BLE001
            _failed(slug, e, ctx)
            return f"❗ ความสามารถ \"{p['meta'].get('name')}\" ทำงานผิดพลาด: {e}"
        if r:
            return str(r)
    return None


_NEW = re.compile(r"^(?:ช่วย)?\s*(?:เพิ่ม|สร้าง)\s*(?:ความสามารถ|ระบบ|ฟังก์ชัน|ฟีเจอร์|สกิล|คำสั่ง)\s*(?:ใหม่)?\s*[:：]?\s*(?P<s>.{6,})$")
_LIST = re.compile(r"^(?:ความสามารถ|สกิล|ระบบ)(?:ที่)?(?:เพิ่ม|สร้าง)(?:เอง|ไว้)(?:มีอะไรบ้าง)?$|^ดูความสามารถที่เพิ่มเอง$")
_OFF = re.compile(r"^(?P<v>ปิด|เปิด|ลบ)\s*(?:ความสามารถ|สกิล)\s*(?P<n>.+)$")
_EDIT = re.compile(r"^(?:แก้|ปรับ|ซ่อม|ปรับปรุง)\s*(?:ความสามารถ|สกิล)\s*(?P<n>[^:：]+?)\s*(?:[:：]\s*(?P<s>.+))?$")


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip()
    t = re.sub(r"\s*(ให้หน่อย|หน่อย|ครับ|ค่ะ|คะ|นะ)+\s*$", "", t)
    if not t:
        return None
    st = getattr(ctx, "notify", None)
    m = _NEW.match(t)
    if m:
        return create(m.group("s"), ctx, status=st)
    if _LIST.match(t):
        ms = all_meta()
        if not ms:
            return "ยังไม่มีความสามารถที่เพิ่มเอง — ลองสั่ง \"เพิ่มความสามารถ: …\""
        return "🧩 ความสามารถที่เพิ่มเอง:\n" + "\n".join(
            f"{'✅' if x.get('enabled', True) else '⏸️'} {x['name']} — {x.get('desc', '')}" for x in ms.values())
    m = _OFF.match(t)
    if m:
        p = _find(m.group("n"))
        if not p:
            return None
        v = m.group("v")
        if v == "ลบ":
            conf = getattr(ctx, "confirm", None)
            if conf and not conf(f"ลบความสามารถ \"{p['name']}\" ถาวรไหม?"):
                return "ไม่ได้ลบ"
            remove(p)
            return f"🗑️ ลบ \"{p['name']}\" แล้ว"
        set_enabled(p, v == "เปิด")
        return f"{'✅ เปิด' if v == 'เปิด' else '⏸️ ปิด'} \"{p['name']}\" แล้ว"
    m = _EDIT.match(t)
    if m:
        p = _find(m.group("n"))
        if not p:
            return None
        try:
            with open(_code_path(p["slug"]), encoding="utf-8") as f:
                p = dict(p, code=f.read())
        except OSError:
            pass
        req = m.group("s") or f"แก้ error นี้: {p.get('last_error', 'ทำงานไม่ถูกต้อง')}"
        return create(f"{p['name']}: {p.get('desc', '')} — {req}", ctx, base=p, status=st)
    return handle_plugins(t, ctx)
