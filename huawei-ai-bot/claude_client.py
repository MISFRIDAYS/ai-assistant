"""เรียก Claude API ด้วย HTTP ตรง (ใช้แค่ requests เพื่อให้ติดตั้งบน Termux ง่าย)"""
import json
import threading
import time

import requests

API_URL = "https://api.anthropic.com/v1/messages"
_local = threading.local()


class ClaudeError(Exception):
    pass


def _session():
    """ใช้การเชื่อมต่อ HTTPS เดิมซ้ำ ประหยัดเวลาเชื่อมต่อใหม่ทุกครั้ง"""
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


def _clean(messages):
    """ลบข้อมูลภายในที่ Claude ไม่รู้จัก (เช่น _sig จาก Gemini)"""
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            c = [{k: v for k, v in b.items() if not k.startswith("_")} for b in c]
        out.append({"role": m["role"], "content": c})
    return out


def _cc(long=False):
    """cache_control: system+เครื่องมือ (ไม่เปลี่ยน) ใช้แคชยาว 1 ชม. / ประวัติล่าสุดใช้ 5 นาทีพอ"""
    import config
    cc = {"type": "ephemeral"}
    if long and getattr(config, "CACHE_TTL", "1h") == "1h":
        cc["ttl"] = "1h"
    return cc


def _with_cache(tools, messages):
    """ใส่ prompt caching: tools และประวัติแชทที่ส่งซ้ำจะถูกแคช ทำให้ตอบเร็วขึ้นและถูกลง
    เครื่องมือ 65 ตัว (ไม่เปลี่ยน) แคชยาว 1 ชม. จึงไม่ต้องเขียนแคชใหม่ทุกครั้งที่ถามห่างกัน"""
    messages = _clean(messages)
    if tools:
        tools = list(tools)
        tools[-1] = {**tools[-1], "cache_control": _cc(long=True)}
    if messages:
        messages = list(messages)
        last = messages[-1]
        content = last["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if content:
            content = list(content)
            content[-1] = {**content[-1], "cache_control": _cc(long=False)}
            messages[-1] = {"role": last["role"], "content": content}
    return tools, messages


def _request(api_key, model, system, messages, tools, max_tokens, stream=False):
    import config
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if getattr(config, "CACHE_TTL", "1h") == "1h":
        headers["anthropic-beta"] = "extended-cache-ttl-2025-04-11"
    tools, messages = _with_cache(tools, messages)
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": _cc(long=True)}],
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    if stream:
        body["stream"] = True

    last_err = None
    for attempt in range(4):
        try:
            r = _session().post(API_URL, headers=headers, json=body, timeout=180, stream=stream)
        except requests.RequestException as e:
            last_err = f"เชื่อมต่อ Claude ไม่ได้: {e}"
            _local.s = None
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r
        # 429 = rate limit, 529 = overloaded, 5xx = server error -> ลองใหม่
        if r.status_code in (429, 500, 502, 503, 529):
            last_err = f"Claude API {r.status_code}: {r.text[:300]}"
            time.sleep(2 ** attempt * 2)
            continue
        raise ClaudeError(f"Claude API {r.status_code}: {r.text[:500]}")
    raise ClaudeError(last_err or "Claude API error")


def create_message(api_key, model, system, messages, tools, max_tokens=2048):
    return _request(api_key, model, system, messages, tools, max_tokens).json()


def stream_message(api_key, model, system, messages, tools, max_tokens=2048, on_text=None):
    """เหมือน create_message แต่ส่งข้อความออกมาทีละนิดผ่าน on_text(ข้อความ) ทันทีที่ AI พิมพ์
    (ใช้ในโหมดเสียง: เริ่มพูดได้ตั้งแต่ประโยคแรก ไม่ต้องรอคำตอบทั้งหมด)"""
    r = _request(api_key, model, system, messages, tools, max_tokens, stream=True)
    blocks, stop, usage = {}, None, {}
    for raw in r.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        d = json.loads(raw[5:])
        t = d.get("type")
        if t == "message_start":
            usage = dict(d["message"].get("usage") or {})
        elif t == "content_block_start":
            b = dict(d["content_block"])
            if b["type"] in ("tool_use", "server_tool_use"):
                b["_json"] = ""
            blocks[d["index"]] = b
        elif t == "content_block_delta":
            b, delta = blocks[d["index"]], d["delta"]
            if delta["type"] == "text_delta":
                b["text"] = b.get("text", "") + delta["text"]
                if on_text:
                    on_text(delta["text"])
            elif delta["type"] == "input_json_delta":
                b["_json"] += delta.get("partial_json", "")
            elif delta["type"] == "citations_delta":
                b.setdefault("citations", []).append(delta["citation"])
        elif t == "content_block_stop":
            b = blocks.get(d["index"], {})
            for k in [k for k, v in b.items() if v is None]:
                b.pop(k)
            if "_json" in b:
                raw_json = b.pop("_json")
                b["input"] = json.loads(raw_json) if raw_json else (b.get("input") or {})
        elif t == "message_delta":
            stop = d.get("delta", {}).get("stop_reason") or stop
            usage.update(d.get("usage") or {})
        elif t == "error":
            raise ClaudeError(f"Claude stream error: {d.get('error')}")
    return {"content": [blocks[i] for i in sorted(blocks)], "stop_reason": stop, "usage": usage}
