"""ใช้ Groq เป็นสมอง (ฟรี โควตาเยอะ เร็วมาก) — API แบบ OpenAI

แปลงข้อความ/เครื่องมือรูปแบบ Claude ↔ OpenAI ให้ agent.py ใช้ได้เหมือนเดิม
ค้นเว็บ: Groq ไม่มีค้นเว็บในตัว → ถ้าตั้ง GEMINI_API_KEY ไว้จะใช้ Gemini ค้นให้ (ไม่งั้นตอบจากความรู้)
"""
import json
import threading
import re
import time

import requests

import config

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"
_local = threading.local()
_resolved = [None]


class GroqError(Exception):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


def list_models():
    r = _session().get(MODELS_URL, timeout=20,
                       headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
    if r.status_code != 200:
        raise GroqError(f"Groq {r.status_code}: {r.text[:200]}")
    return [m["id"] for m in r.json().get("data", [])]


def _model():
    """เลือกรุ่นที่ใช้ได้: ตามที่ตั้งไว้ ถ้าไม่มีก็หารุ่น llama ตัวใหญ่ที่รองรับ tool"""
    if config.GROQ_MODEL and config.GROQ_MODEL != "auto":
        return config.GROQ_MODEL
    if _resolved[0]:
        return _resolved[0]
    try:
        models = list_models()
    except Exception:  # noqa: BLE001
        return "llama-3.3-70b-versatile"
    _resolved[0] = _best_chat(models) or "llama-3.3-70b-versatile"
    return _resolved[0]


_SKIP = ("whisper", "guard", "tts", "embed", "vision", "distil", "moderation", "allam-")
_PREFER_ORDER = ("llama-3.3-70b", "gpt-oss-120b", "120b", "qwen3", "qwen", "gpt-oss-20b", "gpt-oss",
                 "llama-3.1-70b", "70b", "versatile", "deepseek", "kimi", "gemma2-9b", "mixtral", "8b", "instant")


def _best_chat(models):
    cands = [m for m in models if not any(k in m.lower() for k in _SKIP)]
    if not cands:
        return models[0] if models else None
    def score(m):
        ml = m.lower()
        for i, k in enumerate(_PREFER_ORDER):
            if k in ml:
                return i
        return len(_PREFER_ORDER)
    cands.sort(key=score)
    return cands[0]


# ---------------------------------------------------------------- แปลงเครื่องมือ

def convert_tools(tools):
    out = []
    for t in tools or []:
        if t.get("type", "").startswith("web_search"):
            out.append({"type": "function", "function": {
                "name": "web_search",
                "description": "ค้นหาข้อมูลล่าสุดบนอินเทอร์เน็ต (ข่าว ราคา อากาศ ฯลฯ)",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                               "required": ["query"]}}})
            continue
        if "name" not in t:
            continue
        out.append({"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}})
    return out


def convert_messages(system, messages):
    out = [{"role": "system", "content": system}]
    for m in messages:
        blocks = m["content"]
        if isinstance(blocks, str):
            out.append({"role": m["role"], "content": blocks})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            calls = [b for b in blocks if b.get("type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = [{"id": b["id"], "type": "function",
                                      "function": {"name": b["name"],
                                                   "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                                     for b in calls]
            out.append(msg)
        else:  # user
            results = [b for b in blocks if b.get("type") == "tool_result"]
            if results:
                for b in results:
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if x.get("type") == "text")
                    out.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": str(c or "")})
                continue
            parts = []
            for b in blocks:
                if b.get("type") == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b.get("type") == "image":
                    src = b.get("source", {})
                    parts.append({"type": "image_url", "image_url":
                                  {"url": f"data:{src.get('media_type','image/jpeg')};base64,{src.get('data','')}"}})
            if len(parts) == 1 and parts[0]["type"] == "text":
                out.append({"role": "user", "content": parts[0]["text"]})
            else:
                out.append({"role": "user", "content": parts})
    return out


# ---------------------------------------------------------------- เรียกใช้

RETRY_BUDGET = 10.0     # วินาที: รอลองซ้ำรวมไม่เกินนี้ (ผู้ใช้รอคำตอบอยู่ — ล้มเร็วแล้วไปตัวสำรองดีกว่าค้าง)


def _post(body, stream=False):
    last = None
    t_start = time.time()

    def _can_wait(sec):
        return time.time() - t_start + sec <= RETRY_BUDGET

    for attempt in range(4):
        try:
            r = _session().post(URL, json=body, stream=stream, timeout=(8, 60),
                                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                                         "content-type": "application/json"})
        except requests.RequestException as e:
            last = f"เชื่อมต่อ Groq ไม่ได้: {e}"
            _local.s = None
            if attempt >= 1 or not _can_wait(1):
                break
            time.sleep(1)
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503):
            last = f"Groq {r.status_code}: {r.text[:200]}"
            if r.status_code == 429 and ("tokens per day" in r.text or "TPD" in r.text):
                raise GroqError("Groq ใช้โควตาฟรีของวันนี้หมดแล้ว — สลับไปใช้ AI ตัวอื่นก่อน")
            m = re.search(r"try again in ([\d.]+)(ms|s)", r.text)
            wait = (float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)) if m else 2 ** attempt * 1.5
            if wait > 8 or not _can_wait(wait + 0.5):
                raise GroqError(f"Groq เต็มโควตาชั่วคราว (ต้องรอ {wait:.0f} วิ) — ลองใหม่อีกสักครู่")
            time.sleep(wait + 0.5)
            continue
        if r.status_code == 400 and "tool" in r.text.lower() and body.get("tools"):
            body.pop("tools", None)      # รุ่นนี้ไม่รองรับ tool → ลองใหม่แบบไม่มี tool
            continue
        if r.status_code == 413 and body.get("tools") and len(body["tools"]) > 12:
            body["tools"] = body["tools"][:12]      # คำขอใหญ่ไป → ลดเครื่องมือลงแล้วลองใหม่
            continue
        if r.status_code == 413:
            raise GroqError("คำขอใหญ่เกินลิมิต Groq (8000 token/นาที ของรุ่นฟรี) — ลองพิมพ์สั้นลง "
                            "หรือเปลี่ยนรุ่นที่ GROQ_MODEL ใน .env")
        raise GroqError(f"Groq {r.status_code}: {r.text[:300]}")
    raise GroqError(last or "Groq error")


def create_message(system, messages, tools, max_tokens=2048, on_text=None, model=None):
    if not config.GROQ_API_KEY:
        raise GroqError("ยังไม่ได้ใส่ GROQ_API_KEY ในไฟล์ .env (ขอฟรีที่ console.groq.com)")
    body = {
        "model": model or _model(),
        "messages": convert_messages(system, messages),
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }
    gt = convert_tools(tools)
    if gt:
        body["tools"] = gt
    body["stream"] = bool(on_text)

    content, calls = [], []
    usage = {}
    if on_text:
        r = _post(body, stream=True)
        text_acc = ""
        tool_acc = {}
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            chunk = raw[5:].strip()
            if chunk == "[DONE]":
                break
            d = json.loads(chunk)
            if d.get("usage"):
                usage = d["usage"]
            delta = (d.get("choices") or [{}])[0].get("delta", {})
            if delta.get("content"):
                text_acc += delta["content"]
                on_text(delta["content"])
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                slot = tool_acc.setdefault(i, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
        if text_acc:
            content.append({"type": "text", "text": text_acc})
        for i in sorted(tool_acc):
            t = tool_acc[i]
            content.append({"type": "tool_use", "id": t["id"] or f"call_{i}", "name": t["name"],
                            "input": json.loads(t["args"]) if t["args"].strip() else {}})
    else:
        data = _post(body).json()
        usage = data.get("usage", {})
        msg = (data.get("choices") or [{}])[0].get("message", {})
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or "{}"
            content.append({"type": "tool_use", "id": tc.get("id", "call"), "name": fn.get("name"),
                            "input": json.loads(args) if args.strip() else {}})

    if not content:
        content = [{"type": "text", "text": "(ไม่มีคำตอบ)"}]
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
    return {"content": content, "stop_reason": stop,
            "usage": {"input_tokens": usage.get("prompt_tokens"),
                      "output_tokens": usage.get("completion_tokens")}}


def web_search(query):
    """Groq ไม่มีค้นเว็บในตัว — ใช้ Gemini ค้นถ้ามี key ไม่งั้นบอกว่าค้นไม่ได้"""
    if config.GEMINI_API_KEY:
        try:
            import gemini_client
            return gemini_client.web_search(query)
        except Exception:  # noqa: BLE001
            pass
    return "ขออภัย ตอนนี้ค้นเว็บไม่ได้ (ยังไม่ได้ตั้งค่าตัวค้นหา) ตอบจากความรู้ที่มีแทนนะครับ"
