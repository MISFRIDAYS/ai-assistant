"""ใช้ Ollama บนคอมพิวเตอร์ที่บ้านเป็นสมอง (ฟรี ไม่จำกัด ส่งเครื่องมือได้ครบ)

Ollama มี API แบบเดียวกับ OpenAI จึงใช้ตัวแปลงข้อความ/เครื่องมือของ groq_client ได้เลย
ตั้งค่าใน .env:
    OLLAMA_URL=http://192.168.1.50:11434   (IP คอมในวง Wi-Fi บ้าน)
    OLLAMA_MODEL=qwen3.5:9b
"""
import json
import re
import threading
import time

import requests

import config
from groq_client import convert_messages, convert_tools

_local = threading.local()
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class OllamaError(Exception):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


def _urls():
    """OLLAMA_URL ใส่ได้หลายที่ คั่นด้วย , เช่น Tailscale (ใช้ได้ทุกที่) + Wi-Fi บ้าน (สำรอง)"""
    return [u.strip().rstrip("/") for u in config.OLLAMA_URL.split(",") if u.strip()]


_active = [0]          # ที่อยู่ที่ใช้ได้ล่าสุด → ลองก่อน


def _order():
    urls = _urls()
    i = _active[0] if _active[0] < len(urls) else 0
    return urls[i:] + urls[:i]


def auth_headers():
    """คีย์ Ollama Cloud (ถ้าตั้ง OLLAMA_API_KEY) — คอมที่บ้านไม่ต้องใช้คีย์"""
    key = config.OLLAMA_API_KEY or "ollama"
    return {"Authorization": f"Bearer {key}", "content-type": "application/json"}


def is_cloud(url=None):
    return "ollama.com" in (url or config.OLLAMA_URL or "")


def _via(url):
    host = url.split("//")[-1].split(":")[0]
    if is_cloud(url):
        return "Ollama Cloud"
    return "Tailscale" if host.startswith("100.") or host.endswith(".ts.net") else "Wi-Fi บ้าน"


def ping(timeout=4):
    """เช็กว่าคอมเปิดอยู่และมีโมเดลที่ตั้งไว้ไหม (ลองทุกที่อยู่) คืน (ok, ข้อความ)"""
    want, last = config.OLLAMA_MODEL, "ยังไม่ได้ตั้ง OLLAMA_URL"
    for base in _order():
        try:
            r = _session().get(base + "/api/tags", timeout=timeout, headers=auth_headers())
            if r.status_code in (401, 403):
                return False, "คีย์ Ollama Cloud ไม่ถูกต้อง (OLLAMA_API_KEY)"
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as e:  # noqa: BLE001
            last = f"เชื่อมต่อคอมไม่ได้ ({e.__class__.__name__}) — คอมปิด/หลับ หรือ Tailscale บนแท็บเล็ตปิดอยู่"
            continue
        _active[0] = _urls().index(base)
        if not is_cloud(base) and not any(n == want or n.split(":")[0] == want for n in names):
            return False, f"คอมเปิดอยู่ แต่ยังไม่มีโมเดล {want} (มี: {', '.join(names) or '-'})"
        return True, f"พร้อมใช้งาน ({want}) ผ่าน {_via(base)}"
    return False, last


def _post(body, stream):
    r, err = None, None
    for base in _order():                     # ลองทีละที่อยู่ จนกว่าจะติด
        try:
            r = _session().post(base + "/api/chat", json=body, stream=stream, timeout=(5, config.OLLAMA_TIMEOUT),
                                headers=auth_headers())
            _active[0] = _urls().index(base)
            break
        except requests.ReadTimeout:
            # เชื่อมติดแต่คอมตอบช้าเกิน (โหลดโมเดล/คิดนาน) → ไม่ลองที่อยู่อื่น สลับไปตัวสำรองเลย
            _active[0] = _urls().index(base)
            raise OllamaError(f"คอมตอบช้าเกิน {config.OLLAMA_TIMEOUT} วินาที — ใช้ตัวสำรองไปก่อน")
        except requests.RequestException as e:
            _local.s = None
            err = e
    if r is None:
        raise OllamaError("เชื่อมต่อคอม (Ollama) ไม่ได้ — คอมปิด/หลับ, IP เปลี่ยน หรือ Tailscale บนแท็บเล็ตปิดอยู่"
                          + (f": {err.__class__.__name__}" if err else ""))
    if r.status_code == 200:
        return r
    text = r.text[:300]
    if r.status_code == 400 and "think" in text.lower() and "think" in body:
        body.pop("think")                      # โมเดลนี้ไม่มีโหมดคิด → ส่งใหม่แบบไม่ระบุ
        return _post(body, stream)
    if r.status_code == 400 and "does not support tools" in text.lower():
        raise OllamaError(f"โมเดล {body.get('model')} ใช้เครื่องมือ (เปิดแอป/สั่งเครื่อง) ไม่ได้ — "
                          "เปลี่ยน OLLAMA_MODEL เป็นรุ่นที่รองรับ tools เช่น qwen3.5:9b")
    if r.status_code in (401, 403):
        raise OllamaError(f"401 คีย์ Ollama Cloud ไม่ถูกต้อง — ตั้ง OLLAMA_API_KEY ใหม่ (ollama.com/settings/keys)")
    if r.status_code == 429:
        raise OllamaError(f"Ollama Cloud ใช้โควตาเต็ม/คิวเต็มชั่วคราว: {text[:120]}")
    if r.status_code == 404:
        raise OllamaError(f"ไม่พบโมเดล {body.get('model')} บนคอม — สั่ง: ollama pull {body.get('model')}")
    raise OllamaError(f"Ollama {r.status_code}: {text}")


class _ThinkFilter:
    """กรองส่วน <think>...</think> ออกจากข้อความที่สตรีม (ไม่ให้พูด/ส่งความคิดภายในของโมเดล)"""

    def __init__(self, out):
        self.out, self.buf, self.inside = out, "", False

    def feed(self, s):
        self.buf += s
        while self.buf:
            if self.inside:
                i = self.buf.find("</think>")
                if i < 0:
                    self.buf = self.buf[-8:]
                    return
                self.buf, self.inside = self.buf[i + 8:].lstrip(), False
            else:
                i = self.buf.find("<think>")
                if i < 0:
                    j = self.buf.rfind("<")                       # เผื่อแท็ก <think> ถูกตัดครึ่งระหว่างชิ้น
                    cut = j if j >= 0 and "<think>".startswith(self.buf[j:]) else len(self.buf)
                    emit, self.buf = self.buf[:cut], self.buf[cut:]
                    if emit:
                        self.out(emit)
                    return
                if i:
                    self.out(self.buf[:i])
                self.buf, self.inside = self.buf[i + 7:], True

    def flush(self):
        if self.buf and not self.inside:
            self.out(self.buf)
        self.buf = ""


def _args(raw):
    if isinstance(raw, dict):
        return raw
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _native_messages(system, messages):
    """แปลงเป็นรูปแบบของ Ollama /api/chat (รูปเป็น images, arguments เป็น dict, ผลเครื่องมือระบุชื่อ)"""
    out, names = [], {}
    for m in convert_messages(system, messages):
        nm = {"role": m["role"], "content": ""}
        c = m.get("content")
        if isinstance(c, list):
            texts, imgs = [], []
            for part in c:
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    imgs.append(url.split(",", 1)[1] if "," in url else url)
            nm["content"] = "\n".join(texts)
            if imgs:
                nm["images"] = imgs
        else:
            nm["content"] = c or ""
        if m.get("tool_calls"):
            nm["tool_calls"] = []
            for tc in m["tool_calls"]:
                fn = tc["function"]
                names[tc.get("id")] = fn["name"]
                nm["tool_calls"].append({"function": {"name": fn["name"], "arguments": _args(fn.get("arguments"))}})
        if m["role"] == "tool" and m.get("tool_call_id") in names:
            nm["tool_name"] = names[m["tool_call_id"]]
        out.append(nm)
    return out


def _body(system, messages, tools, max_tokens, stream):
    body = {
        "model": config.OLLAMA_MODEL,
        "messages": _native_messages(system, messages),
        "stream": stream,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,          # ค้างโมเดลไว้ในการ์ดจอ ไม่ต้องโหลดใหม่ทุกครั้ง
        "options": {"num_ctx": config.OLLAMA_NUM_CTX,    # กำหนดเองทุกครั้ง → เครื่องมือ/คำสั่งระบบไม่ถูกตัด
                    "temperature": 0.6, "num_predict": max_tokens},
    }
    if config.OLLAMA_MODEL.startswith("gpt-oss"):
        body["think"] = "medium" if config.OLLAMA_THINK else "low"   # gpt-oss ปิดคิดไม่ได้ → คิดสั้นสุด
    elif not config.OLLAMA_THINK:
        body["think"] = False                            # ปิดโหมดคิดยาว → ตอบในไม่กี่วินาที
    ot = convert_tools(tools)
    if ot:
        body["tools"] = ot
    return body


def warmup():
    """โหลดโมเดลเข้าการ์ดจอล่วงหน้า (เรียกตอนบอทเริ่ม) — คำถามแรกจะได้ไม่ช้า"""
    if is_cloud():
        return True                                       # คลาวด์ไม่ต้องโหลดเข้าการ์ดจอ
    try:
        for base in _order():
            r = _session().post(base + "/api/generate", timeout=(5, 180),
                                json={"model": config.OLLAMA_MODEL, "keep_alive": config.OLLAMA_KEEP_ALIVE,
                                      "options": {"num_ctx": config.OLLAMA_NUM_CTX}})
            if r.status_code == 200:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def create_message(system, messages, tools, max_tokens=2048, on_text=None):
    if not config.OLLAMA_URL:
        raise OllamaError("ยังไม่ได้ตั้ง OLLAMA_URL ใน .env (รัน bash set_ollama.sh)")
    body = _body(system, messages, tools, max_tokens, bool(on_text))
    content, usage, calls = [], {}, []
    acc = []
    emit = (lambda s: (acc.append(s), on_text(s))) if on_text else acc.append
    filt = _ThinkFilter(emit)
    r = _post(body, bool(on_text))
    lines = r.iter_lines(decode_unicode=True) if on_text else [json.dumps(r.json())]
    for raw in lines:
        if not raw:
            continue
        d = json.loads(raw)
        if d.get("error"):
            raise OllamaError(f"Ollama: {d['error']}")
        msg = d.get("message") or {}
        if msg.get("content"):
            filt.feed(msg["content"])
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name"):
                calls.append({"name": fn["name"], "input": _args(fn.get("arguments"))})
        if d.get("done"):
            usage = {"input_tokens": d.get("prompt_eval_count"), "output_tokens": d.get("eval_count")}
    filt.flush()
    text = "".join(acc).strip()
    if text:
        content.append({"type": "text", "text": text})
    for i, c in enumerate(calls):
        content.append({"type": "tool_use", "id": f"call_{int(time.time() * 1000) % 10**8}_{i}",
                        "name": c["name"], "input": c["input"]})
    if not content:
        content = [{"type": "text", "text": "(ไม่มีคำตอบ)"}]
    stop = "tool_use" if calls else "end_turn"
    return {"content": content, "stop_reason": stop, "usage": usage}
