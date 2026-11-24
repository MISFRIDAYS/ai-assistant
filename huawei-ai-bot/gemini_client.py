"""ใช้ Google Gemini เป็นสมองแทน (หรือสำรอง) Claude

แปลงประวัติแชท/เครื่องมือรูปแบบ Claude ↔ Gemini ให้ agent.py ใช้ได้เหมือนเดิมทุกอย่าง
ค้นเว็บ: เรียก Gemini อีกครั้งพร้อม Google Search (grounding) แล้วส่งผลกลับเป็นข้อความ
"""
import json
import re
import threading
import time

import requests

import config

BASE = "https://generativelanguage.googleapis.com/v1beta"
API = BASE + "/models/{model}:generateContent"
SKIP_SIG = "skip_thought_signature_validator"   # ใช้กับ function call ที่ไม่ได้มาจาก Gemini เอง
_local = threading.local()
_resolved = {}          # ชื่อรุ่นที่ขอ -> ชื่อรุ่นจริงที่ใช้ได้ (บาง key ต้องใช้รุ่นเจาะจง)
# เรียงตามความชอบ: เร็ว/ฟรีก่อน แล้วค่อยรุ่นใหญ่
_PREFER = ("flash-lite", "flash", "pro")


class GeminiError(Exception):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


STREAM_API = BASE + "/models/{model}:streamGenerateContent?alt=sse"


def list_models():
    """รายชื่อรุ่นที่ key นี้ใช้ได้จริง (รองรับ generateContent)"""
    r = _session().get(BASE + "/models", timeout=20,
                       headers={"x-goog-api-key": config.GEMINI_API_KEY})
    if r.status_code != 200:
        raise GeminiError(f"ดูรายชื่อรุ่นไม่ได้ (Gemini {r.status_code}): {r.text[:200]}")
    out = []
    for m in r.json().get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(m["name"].split("/")[-1])
    return out


def _ver(m):
    nums = re.findall(r"(\d+(?:\.\d+)?)", m)
    return float(nums[0]) if nums else 0.0


def _pick(models, want):
    """เลือกรุ่นที่ใช้ได้จริงที่ใกล้เคียงกับ want ที่สุด — เลือกเวอร์ชันสูงสุด เลี่ยง preview/เลิกใช้"""
    want = want.lower()
    kind = "pro" if "pro" in want else ("flash-lite" if "lite" in want else "flash")
    cands = [m for m in models if kind in m.lower()]
    if kind == "flash":
        cands = [m for m in cands if "lite" not in m.lower()] or cands
    if not cands:
        for k in _PREFER:
            cands = [m for m in models if k in m.lower()]
            if cands:
                break
    cands = cands or models
    cands = [m for m in cands if "latest" not in m.lower()] or cands   # เลี่ยง alias ที่อาจเพี้ยนกับ key AQ.
    # เวอร์ชันสูงสุดก่อน, stable ก่อน preview/exp
    cands.sort(key=lambda m: (_ver(m), "preview" not in m.lower() and "exp" not in m.lower()), reverse=True)
    return cands[0] if cands else want


def resolve_model(want):
    """คืนชื่อรุ่นจริงที่ใช้ได้ (แคชไว้) — กันปัญหา key แบบ AQ. ที่รุ่น -latest ใช้ไม่ได้"""
    if want in _resolved:
        return _resolved[want]
    try:
        models = list_models()
        chosen = _pick(models, want)
    except Exception:  # noqa: BLE001
        chosen = want
    _resolved[want] = chosen
    if chosen != want:
        print(time.strftime("[%H:%M:%S]"), f"Gemini ใช้รุ่น {chosen} (แทน {want})", flush=True)
    return chosen


_quota_until = [0.0]           # โควตา Gemini หมด → ไม่ต้องลองซ้ำ (เดิมรอ backoff ~30 วิ ทุกครั้ง ทำให้ช้ามาก)


def quota_out():
    return time.time() < _quota_until[0]


def _post(model, body, timeout=120, stream=False, _retried=False):
    if quota_out():
        raise GeminiError("Gemini 429: โควตาหมดชั่วคราว (ข้ามเพื่อไม่ให้ช้า)")
    model = _resolved.get(model, model)
    last = None
    for attempt in range(4):
        try:
            r = _session().post((STREAM_API if stream else API).format(model=model), json=body,
                                timeout=timeout, stream=stream,
                                headers={"x-goog-api-key": config.GEMINI_API_KEY,
                                         "content-type": "application/json"})
        except requests.RequestException as e:
            last = f"เชื่อมต่อ Gemini ไม่ได้: {e}"
            _local.s = None
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r if stream else r.json()
        if r.status_code == 429 and re.search(r"quota|exceeded|RESOURCE_EXHAUSTED", r.text, re.I):
            _quota_until[0] = time.time() + 15 * 60          # โควตาหมด (รายนาที/รายวัน) → พัก 15 นาที ไม่รอซ้ำ
            raise GeminiError(f"Gemini 429: {r.text[:200]}")
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"Gemini {r.status_code}: {r.text[:300]}"
            if attempt >= 1:
                break                                         # ไม่รอนาน (เดิมรอรวม ~30 วิ)
            time.sleep(2 ** attempt * 2)
            continue
        msg = r.text.lower()
        # error พวกนี้มักเกิดจาก "รุ่นไม่ถูกต้อง/ไม่มีแล้ว" (บางที error หลอกว่าเป็นเรื่อง auth)
        model_issue = (r.status_code == 404 or "not found" in msg or "not supported" in msg
                       or "access_token_type" in msg or "is not available" in msg
                       or "no longer available" in msg)
        if model_issue and not _retried:
            sug = re.search(r"use models/([\w.\-]+)", r.text)
            if sug and sug.group(1) != model:
                _resolved[_orig_name(model)] = sug.group(1)
                return _post(sug.group(1), body, timeout=timeout, stream=stream, _retried=True)
            _resolved.pop(model, None)
            real = resolve_model(_orig_name(model))
            if real and real != model:
                return _post(real, body, timeout=timeout, stream=stream, _retried=True)
            # ลองไล่รุ่นที่มีจริงทีละตัว
            try:
                for m in list_models():
                    if m == model:
                        continue
                    rr = _session().post((STREAM_API if stream else API).format(model=m), json=body,
                                         timeout=timeout, stream=stream,
                                         headers={"x-goog-api-key": config.GEMINI_API_KEY,
                                                  "content-type": "application/json"})
                    if rr.status_code == 200:
                        _resolved[_orig_name(model)] = m
                        print(time.strftime("[%H:%M:%S]"), f"Gemini ใช้รุ่น {m}", flush=True)
                        return rr if stream else rr.json()
            except Exception:  # noqa: BLE001
                pass
        if r.status_code in (400, 401, 403):
            if "api key not valid" in msg:
                raise GeminiError("Gemini API key ไม่ถูกต้อง — สร้างใหม่ที่ aistudio.google.com/apikey แล้วตั้งด้วย bash set_key.sh")
            if "quota" in msg or "resource_exhausted" in msg:
                raise GeminiError("โควตา Gemini หมดแล้ววันนี้ ลองใหม่พรุ่งนี้ หรือสลับไปใช้ Claude")
            raise GeminiError(f"Gemini {r.status_code}: {r.text[:300]}")
        raise GeminiError(f"Gemini {r.status_code}: {r.text[:500]}")
    raise GeminiError(last or "Gemini error")


def _orig_name(model):
    for k, v in _resolved.items():
        if v == model:
            return k
    return model


# ---------------------------------------------------------------- แปลงเครื่องมือ

def _schema(s):
    """JSON Schema → รูปแบบ Gemini (type ตัวใหญ่)"""
    if not isinstance(s, dict):
        return s
    out = {}
    for k, v in s.items():
        if k == "type":
            out["type"] = (v[0] if isinstance(v, list) else v).upper()
        elif k == "properties":
            out["properties"] = {pk: _schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out["items"] = _schema(v)
        elif k in ("description", "enum", "required", "nullable", "format"):
            if k == "required" and not v:
                continue
            out[k] = v
    return out


def convert_tools(tools):
    decls = []
    for t in tools or []:
        if t.get("type", "").startswith("web_search"):
            decls.append({"name": "web_search",
                          "description": "ค้นหาข้อมูลล่าสุดบนอินเทอร์เน็ต (ข่าว ราคา อากาศ ฯลฯ) ด้วย Google",
                          "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}},
                                         "required": ["query"]}})
            continue
        if "name" not in t or "input_schema" not in t:
            continue
        d = {"name": t["name"], "description": t.get("description", "")}
        sch = t["input_schema"]
        if sch.get("properties"):
            d["parameters"] = _schema(sch)
        decls.append(d)
    return [{"function_declarations": decls}] if decls else []


# ---------------------------------------------------------------- แปลงประวัติแชท

def convert_messages(messages):
    names = {}            # tool_use_id → ชื่อ tool
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        blocks = m["content"]
        if isinstance(blocks, str):
            blocks = [{"type": "text", "text": blocks}]
        parts = []
        for b in blocks:
            t = b.get("type")
            if t == "text" and b.get("text"):
                p = {"text": b["text"]}
                if b.get("_sig"):
                    p["thoughtSignature"] = b["_sig"]
                parts.append(p)
            elif t == "image":
                src = b.get("source", {})
                parts.append({"inline_data": {"mime_type": src.get("media_type", "image/jpeg"),
                                              "data": src.get("data", "")}})
            elif t == "tool_use":
                names[b["id"]] = b["name"]
                parts.append({"functionCall": {"name": b["name"], "args": b.get("input") or {}},
                              "thoughtSignature": b.get("_sig") or SKIP_SIG})
            elif t == "tool_result":
                content = b.get("content")
                extra = []
                if isinstance(content, list):
                    text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    for c in content:
                        if c.get("type") == "image":
                            src = c.get("source", {})
                            extra.append({"inline_data": {"mime_type": src.get("media_type", "image/jpeg"),
                                                          "data": src.get("data", "")}})
                else:
                    text = str(content or "")
                key = "error" if b.get("is_error") else "result"
                parts.append({"functionResponse": {"name": names.get(b.get("tool_use_id"), "tool"),
                                                   "response": {key: text}}})
                parts.extend(extra)
            elif t == "web_search_tool_result":
                continue            # ผลค้นเว็บของ Claude (ข้อความตอบกลับมีสรุปอยู่แล้ว)
        if parts:
            contents.append({"role": role, "parts": parts})
    return contents


# ---------------------------------------------------------------- เรียกใช้

def create_message(system, messages, tools, max_tokens=2048, on_text=None):
    """คืนค่ารูปแบบเดียวกับ Claude: {"content": [...], "stop_reason": ..., "usage": {...}}"""
    if not config.GEMINI_API_KEY:
        raise GeminiError("ยังไม่ได้ใส่ GEMINI_API_KEY ในไฟล์ .env (ขอฟรีที่ aistudio.google.com)")
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": convert_messages(messages),
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
    }
    if not config.GEMINI_THINKING:     # ไม่ต้อง "คิดนาน" → ตอบเร็วขึ้นมาก
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    gt = convert_tools(tools)
    if gt:
        body["tools"] = gt
    stream = on_text is not None          # โหมดเสียง: รับคำตอบทีละท่อน → เริ่มพูดได้ทันที
    try:
        data = _post(config.GEMINI_MODEL, body, stream=stream)
    except GeminiError as e:
        if "thinking" not in str(e).lower() or "thinkingConfig" not in body["generationConfig"]:
            raise
        body["generationConfig"].pop("thinkingConfig")
        data = _post(config.GEMINI_MODEL, body, stream=stream)
    if stream:
        parts, usage = [], {}
        for raw in data.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            chunk = json.loads(raw[5:])
            usage = chunk.get("usageMetadata", usage)
            for p in ((chunk.get("candidates") or [{}])[0].get("content") or {}).get("parts", []):
                if p.get("thought"):
                    continue
                if p.get("text") and parts and "text" in parts[-1] and "functionCall" not in parts[-1]:
                    parts[-1]["text"] += p["text"]          # ต่อข้อความท่อนเดียวกัน
                    if p.get("thoughtSignature"):
                        parts[-1]["thoughtSignature"] = p["thoughtSignature"]
                elif p.get("text") or "functionCall" in p:
                    parts.append(dict(p))
                elif p.get("thoughtSignature") and parts:
                    parts[-1]["thoughtSignature"] = p["thoughtSignature"]
                if p.get("text") and on_text:
                    on_text(p["text"])
        data = {"candidates": [{"content": {"parts": parts}}], "usageMetadata": usage}
        on_text_done = True
    else:
        on_text_done = False
    cands = data.get("candidates") or []
    if not cands:
        fb = data.get("promptFeedback", {})
        raise GeminiError(f"Gemini ไม่ตอบ: {fb.get('blockReason') or data}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    content, calls = [], 0
    for i, p in enumerate(parts):
        if p.get("thought"):
            continue
        if "functionCall" in p:
            fc = p["functionCall"]
            calls += 1
            blk = {"type": "tool_use", "id": f"g{int(time.time() * 1000)}_{i}", "name": fc["name"],
                   "input": fc.get("args") or {}}
            if p.get("thoughtSignature"):
                blk["_sig"] = p["thoughtSignature"]
            content.append(blk)
        elif p.get("text"):
            blk = {"type": "text", "text": p["text"]}
            if p.get("thoughtSignature"):
                blk["_sig"] = p["thoughtSignature"]
            content.append(blk)
            if on_text and not on_text_done:
                on_text(p["text"])
    if not content:
        content = [{"type": "text", "text": "(ไม่มีคำตอบ)"}]
    u = data.get("usageMetadata", {})
    return {"content": content, "stop_reason": "tool_use" if calls else "end_turn",
            "usage": {"input_tokens": u.get("promptTokenCount"), "output_tokens": u.get("candidatesTokenCount"),
                      "cache_read_input_tokens": u.get("cachedContentTokenCount")}}


def web_search(query):
    """ค้นเว็บด้วย Google Search ผ่าน Gemini แล้วสรุปเป็นข้อความพร้อมแหล่งที่มา"""
    body = {
        "contents": [{"role": "user", "parts": [{"text": f"ค้นหาข้อมูลล่าสุดแล้วสรุปให้กระชับเป็นภาษาไทย: {query}"}]}],
        "tools": [{"google_search": {}}],
    }
    data = _post(config.GEMINI_MODEL, body)
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    srcs = []
    for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks", []):
        w = ch.get("web") or {}
        if w.get("uri"):
            srcs.append(f"- {w.get('title', '')}: {w['uri']}")
    return text + ("\n\nแหล่งที่มา:\n" + "\n".join(srcs[:5]) if srcs else "")


def transcribe(wav_bytes, mime="audio/wav", vocab=""):
    """ถอดเสียงด้วย Gemini (แม่นกับภาษาไทยปนอังกฤษ ชื่อเฉพาะ คำแสลง) คืน "" ถ้าไม่มีเสียงพูด"""
    import base64
    vocab = re.sub(r"[^\w\s,.()ก-๙-]", "", vocab or "")[:400]          # ตัดอีโมจิ/ตัวอักษรแปลกจากชื่อแชท
    hint = f"คำเฉพาะที่อาจพูดถึง: {vocab}\n" if vocab else ""
    prompt = ("ถอดเสียงพูดภาษาไทยในไฟล์นี้ให้ตรงตามที่พูดจริงทุกคำ (รวมคำหยาบ/คำแสลง ห้ามเซ็นเซอร์)\n"
              "- คำภาษาอังกฤษ/ชื่อแอป/ชื่อแบรนด์ ให้เขียนเป็นตัวอักษรอังกฤษ เช่น Claude, Instagram, LINE\n"
              "- ห้ามแปล ห้ามสรุป ห้ามแต่งเติม ห้ามใส่เครื่องหมายคำพูด\n"
              "- ตอบเฉพาะข้อความที่ถอดได้ ถ้าไม่มีเสียงคนพูดให้ตอบว่า <ว่าง>\n" + hint)
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(wav_bytes).decode()}},
            {"text": prompt}]}],
        # ปิดโหมด "คิดก่อนตอบ" → ถอดเสียงเร็วขึ้นหลายวินาที
        "generationConfig": {"temperature": 0, "maxOutputTokens": 400,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    try:
        data = _post(config.GEMINI_STT_MODEL, body, timeout=20)
    except GeminiError as e:
        if "thinking" not in str(e).lower() and "invalid argument" not in str(e).lower():
            raise
        body["generationConfig"].pop("thinkingConfig", None)   # รุ่นที่ไม่รองรับการปิด thinking
        data = _post(config.GEMINI_STT_MODEL, body, timeout=20)
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                   if not p.get("thought")).strip()
    return "" if "<ว่าง>" in text or not text else text.strip('"“” ')


def locate(image_bytes, target, mime="image/jpeg"):
    """หาตำแหน่งสิ่งของบนภาพหน้าจอ (Gemini มองภาพได้) → (x, y, ป้ายที่เห็น) แบบสัดส่วน 0-1 หรือ None"""
    import base64
    prompt = (f"นี่คือภาพหน้าจอแท็บเล็ต หา UI ที่ตรงกับ: {target}\n"
              "ถ้าเป็นชื่อคน ให้ยอมรับการสะกดต่างกันเล็กน้อย (เสียงถอดเพี้ยน เช่น เจ็ด/เจก, ไม่มีวงเล็บ)\n"
              'ตอบ JSON เท่านั้น: {"found": true/false, "box_2d": [ymin, xmin, ymax, xmax] (สเกล 0-1000), '
              '"label": "ข้อความที่เห็นตรงนั้น"}')
    body = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}}, {"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 300, "responseMimeType": "application/json",
                             "thinkingConfig": {"thinkingBudget": 0}}}
    try:
        data = _post(config.GEMINI_MODEL, body, timeout=40)
    except GeminiError as e:
        if "thinking" not in str(e).lower():
            raise
        body["generationConfig"].pop("thinkingConfig")
        data = _post(config.GEMINI_MODEL, body, timeout=40)
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except ValueError:
        return None
    box = j.get("box_2d")
    if not j.get("found") or not box or len(box) != 4:
        return None
    y1, x1, y2, x2 = [max(0, min(1000, float(v))) for v in box]
    return (x1 + x2) / 2000, (y1 + y2) / 2000, str(j.get("label", ""))
