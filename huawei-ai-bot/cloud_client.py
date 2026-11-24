"""AI บนคลาวด์แบบจ่ายรายเดือน (API แบบ OpenAI) — Chutes, NanoGPT, Synthetic ฯลฯ

ตั้งค่าใน ⚙️ ตั้งค่า → ☁️ Cloud AI:
    CLOUD_API_KEY=cpk_...                              (คีย์ของผู้ให้บริการ)
    CLOUD_BASE_URL=https://llm.chutes.ai/v1           (ว่าง = Chutes)
    CLOUD_MODEL=Qwen/Qwen3.5-397B-A17B-TEE            (ตัวหลัก: ดูรูป + สั่งเครื่องมือ + คุมมือถือ)
    CLOUD_MODEL_BACKUP=moonshotai/Kimi-K3-TEE         (ตัวสำรอง: เมื่อตัวหลักคนใช้เต็ม/ล่ม)

ตัวหลักเต็ม → ลองตัวสำรองทันที (จำไว้ 5 นาที) → ทั้งคู่ไม่ได้ → agent สลับไป AI ฟรี (LLM_FALLBACK)
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
_bad_until = {}                 # รุ่นที่เพิ่งเต็ม/ล่ม → ข้ามไปก่อนชั่วคราว
_no_vision = set()              # รุ่นที่ดูรูปไม่ได้ (เจอ 400 ตอนส่งรูป) → ข้ามไปใช้ AI ดูรูปตัวอื่น
_reasoning = {}                 # tool_call_id → ความคิดของโมเดล (Kimi ต้องส่งกลับตอนเรียกเครื่องมือหลายรอบ)
_CAPACITY = re.compile(r"capacity|overload|unavailable|no instances|busy|rate.?limit|too many|try again|timeout",
                       re.I)


class CloudError(Exception):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


def base_url():
    return (config.CLOUD_BASE_URL or "https://llm.chutes.ai/v1").rstrip("/")


def _headers():
    return {"Authorization": f"Bearer {config.CLOUD_API_KEY}", "content-type": "application/json"}


_lat = {}                       # เวลาตอบเฉลี่ยล่าสุดของแต่ละรุ่น (วินาที) — ใช้เลือกตัวที่เร็วกว่าอัตโนมัติ


def _note_latency(model, sec):
    old = _lat.get(model)
    _lat[model] = sec if old is None else old * 0.6 + sec * 0.4


def _slow(model, others):
    """รุ่นนี้ช้ากว่าอีกตัวมากไหม (ช้ากว่า 2.5 เท่า และเกิน 10 วิ)"""
    me = _lat.get(model)
    best = min((_lat[o] for o in others if o in _lat), default=None)
    return me is not None and best is not None and me > 10 and me > best * 2.5


def models_to_try(model=None):
    """ลำดับรุ่นที่จะลอง: ตัวหลัก → ตัวสำรอง (รุ่นที่เพิ่งเต็ม/ช้ามากช่วงนี้ ไปไว้ท้าย)"""
    if model:
        return [model]
    ms = [m for m in (config.CLOUD_MODEL, config.CLOUD_MODEL_BACKUP) if m]
    ms = list(dict.fromkeys(ms))
    now = time.time()
    return sorted(ms, key=lambda m: (_bad_until.get(m, 0) > now, _slow(m, [o for o in ms if o != m])))


def _mark_bad(model, mins=5):
    _bad_until[model] = time.time() + mins * 60


def _is_qwen(model):
    return "qwen" in (model or "").lower()


def _is_kimi(model):
    return "kimi" in (model or "").lower()


def _remember_reasoning(calls, text):
    if not text or not calls:
        return
    for c in calls:
        _reasoning[c] = text[-6000:]
    while len(_reasoning) > 200:
        _reasoning.pop(next(iter(_reasoning)))


def _messages(system, messages, model):
    out = convert_messages(system, messages)
    if _is_kimi(model):                         # Kimi: ส่งความคิดรอบก่อนกลับไปด้วย ไม่งั้นงานหลายขั้นเพี้ยน
        for m in out:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                r = _reasoning.get(m["tool_calls"][0].get("id"))
                if r:
                    m["reasoning_content"] = r
    return out


def _body(system, messages, tools, max_tokens, stream, model):
    body = {"model": model, "messages": _messages(system, messages, model), "max_tokens": max_tokens,
            "temperature": 0.6, "stream": stream}
    if _is_qwen(model):                         # ปิดโหมดคิดยาว → ตอบเร็ว (เปิดได้ด้วย CLOUD_THINK=1)
        body["chat_template_kwargs"] = {"enable_thinking": bool(config.CLOUD_THINK)}
    ct = convert_tools(tools)
    if ct:
        body["tools"] = ct
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _post(body):
    """ส่งคำขอ 1 ครั้ง (ปรับคำขอแล้วลองใหม่ได้เมื่อเซิร์ฟเวอร์ไม่รับบางช่อง) คืน response หรือ raise CloudError"""
    for _ in range(4):
        try:
            r = _session().post(base_url() + "/chat/completions", json=body, stream=True,
                                timeout=(8, config.CLOUD_TIMEOUT), headers=_headers())
        except requests.RequestException as e:
            _local.s = None
            raise CloudError(f"busy: เชื่อมต่อ Cloud AI ไม่ได้ ({e.__class__.__name__})") from e
        if r.status_code == 200:
            return r
        text = r.text[:300]
        low = text.lower()
        if r.status_code == 400 and ("chat_template_kwargs" in low or "enable_thinking" in low) \
                and "chat_template_kwargs" in body:
            body.pop("chat_template_kwargs")
            continue
        if r.status_code == 400 and "stream_options" in low and "stream_options" in body:
            body.pop("stream_options")
            continue
        if r.status_code == 400 and "reasoning_content" in low:
            for m in body["messages"]:
                m.pop("reasoning_content", None)
            continue
        if r.status_code in (401, 403):
            raise CloudError(f"401 คีย์ Cloud AI ไม่ถูกต้องหรือหมดอายุ — แก้ที่ ⚙️ ตั้งค่า → Cloud AI ({text[:120]})")
        if "subscription_only" in low or "billing_restriction" in low:
            # คีย์แบบ "ใช้แพ็กเท่านั้น" ไม่รับคำขอนี้: ลองตัดพารามิเตอร์เสริมออกก่อน (บางตัวทำให้ไม่นับเป็นแพ็ก)
            extra = [k for k in ("chat_template_kwargs", "stream_options", "temperature") if k in body]
            if extra:
                for k in extra:
                    body.pop(k)
                print(time.strftime("[%H:%M:%S]"), f"☁️ แพ็กไม่ครอบคลุม → ลองส่งแบบไม่มี {', '.join(extra)}", flush=True)
                continue
            raise CloudError(f"busy: รุ่น {body.get('model')} ไม่อยู่ในแพ็กรายเดือน (เช็กชื่อรุ่นในหน้า Models "
                             f"ต้องมีป้าย \"$ ขีดฆ่า\" สีเขียว) — {text[:120]}")
        if r.status_code == 402 or "quota" in low or "insufficient" in low or "subscription" in low:
            raise CloudError(f"quota: แพ็กเกจ/โควตา Cloud AI หมด ({r.status_code}: {text[:150]})")
        if r.status_code == 404 or ("model" in low and "not found" in low):
            raise CloudError(f"busy: ไม่พบรุ่น {body.get('model')} ({text[:120]})")
        if r.status_code in (429, 500, 502, 503, 504, 529) or _CAPACITY.search(low):
            raise CloudError(f"busy: {body.get('model')} เต็ม/ไม่ว่าง ({r.status_code}: {text[:150]})")
        raise CloudError(f"Cloud AI {r.status_code}: {text}")
    raise CloudError("Cloud AI ไม่รับคำขอ")


def _parse_stream(r, on_text):
    acc, reason, tool_acc, usage = [], [], {}, {}
    try:
        from ollama_client import _ThinkFilter
        filt = _ThinkFilter(lambda s: (acc.append(s), on_text(s)))
    except Exception:  # noqa: BLE001
        filt = None
    for raw in r.iter_lines(decode_unicode=False):
        if not raw:
            continue
        raw = raw.decode("utf-8", "replace")
        if not raw.startswith("data:"):
            continue
        chunk = raw[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            d = json.loads(chunk)
        except ValueError:
            continue
        if d.get("error"):
            raise CloudError(f"busy: {str(d['error'])[:200]}")
        if d.get("usage"):
            usage = d["usage"]
        delta = (d.get("choices") or [{}])[0].get("delta") or {}
        rc = delta.get("reasoning_content") or delta.get("reasoning")
        if rc:
            reason.append(rc)
        if delta.get("content"):
            if filt:
                filt.feed(delta["content"])
            else:
                acc.append(delta["content"])
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
    if filt:
        filt.flush()
    calls = [{"id": t["id"] or f"call_{i}", "name": t["name"], "args": t["args"]}
             for i, t in sorted(tool_acc.items()) if t["name"]]
    return "".join(acc), "".join(reason), calls, usage


class _Lines:
    """ห่อข้อมูลที่อ่านมาแล้ว ให้ใช้ตัวอ่านแบบสตรีมได้"""

    def __init__(self, raw):
        self.raw = raw

    def iter_lines(self, decode_unicode=False):
        return iter(self.raw.splitlines())


def _parse_any(r, emit):
    """อ่านคำตอบได้ทั้งแบบสตรีม (SSE) และแบบ JSON ก้อนเดียว (บางเซิร์ฟเวอร์ไม่สตรีมให้)"""
    ct = (getattr(r, "headers", None) or {}).get("content-type", "") or ""
    if "event-stream" in ct:
        return _parse_stream(r, emit)
    raw = r.content
    if raw.lstrip().startswith(b"data:"):
        return _parse_stream(_Lines(raw), emit)
    text, reason, calls, usage = _parse_json(r)
    if text:
        emit(text)
    return text, reason, calls, usage


def _parse_json(r):
    data = json.loads(r.content.decode("utf-8", "replace"))
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    text = _THINK.sub("", msg.get("content") or "")
    reason = msg.get("reasoning_content") or msg.get("reasoning") or ""
    calls = [{"id": tc.get("id") or f"call_{i}", "name": (tc.get("function") or {}).get("name"),
              "args": (tc.get("function") or {}).get("arguments") or ""}
             for i, tc in enumerate(msg.get("tool_calls") or []) if (tc.get("function") or {}).get("name")]
    return text, reason, calls, data.get("usage") or {}


def _args(s):
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s) if (s or "").strip() else {}
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def create_message(system, messages, tools, max_tokens=2048, on_text=None, model=None):
    if not config.CLOUD_API_KEY:
        raise CloudError("401 ยังไม่ได้ใส่คีย์ Cloud AI (⚙️ ตั้งค่า → ☁️ Cloud AI)")
    errs = []
    order = models_to_try(model)
    for m in order:
        body = _body(system, messages, tools, max_tokens, True, m)    # สตรีมเสมอ → รู้ทันทีถ้าค้าง แล้วสลับรุ่นได้
        t0 = time.time()
        said = []

        def emit(s, _said=said):
            _said.append(s)
            if on_text:
                on_text(s)
        try:
            r = _post(body)
            text, reason, calls, usage = _parse_any(r, emit)
        except CloudError as e:
            msg = str(e)
            if not msg.startswith("busy"):
                raise                                     # คีย์ผิด/โควตาหมด → ลองรุ่นอื่นก็ไม่ช่วย
            _mark_bad(m)
            errs.append(msg[:160])
            print(time.strftime("[%H:%M:%S]"), f"☁️ {m} ใช้ไม่ได้ → ลองตัวถัดไป ({msg[:100]})", flush=True)
            continue
        except (requests.RequestException, ValueError) as e:
            if said:                                      # พูด/พิมพ์ไปแล้วบางส่วน → สลับรุ่นไม่ได้ (จะซ้ำ)
                raise CloudError(f"busy: {m} หยุดกลางคัน ({e.__class__.__name__})") from e
            _mark_bad(m, 3)
            _note_latency(m, time.time() - t0 + 10)
            errs.append(f"{m}: ช้า/ค้างเกิน {config.CLOUD_TIMEOUT} วิ ({e.__class__.__name__})")
            print(time.strftime("[%H:%M:%S]"), f"☁️ {m.split('/')[-1]} ค้าง → สลับไปตัวถัดไป", flush=True)
            continue
        _bad_until.pop(m, None)
        _note_latency(m, time.time() - t0)
        print(time.strftime("[%H:%M:%S]"), f"☁️ {m.split('/')[-1]} {time.time() - t0:.1f}s", flush=True)
        _remember_reasoning([c["id"] for c in calls], reason)
        content = []
        text = text.strip()
        if text:
            content.append({"type": "text", "text": text})
        for c in calls:
            content.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": _args(c["args"])})
        if not content:
            content = [{"type": "text", "text": "(ไม่มีคำตอบ)"}]
        stop = "tool_use" if calls else "end_turn"
        return {"content": content, "stop_reason": stop, "model": m,
                "usage": {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}}
    raise CloudError("Cloud AI ทุกรุ่นไม่ว่างตอนนี้ (" + " | ".join(errs)[:300] + ")")


def vision(prompt, imgs_b64, timeout=30):
    """ให้ AI บนคลาวด์ดูรูป (รุ่นหลักก่อน แล้วรุ่นสำรอง) คืนข้อความ"""
    content = [{"type": "text", "text": prompt + "\n(ตอบเป็นภาษาไทย)"}] + \
              [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{d}"}} for d in imgs_b64[:5]]
    errs = []
    for m in models_to_try(config.CLOUD_VISION_MODEL or None):
        if m in _no_vision:
            continue
        body = {"model": m, "max_tokens": 800, "temperature": 0.3,
                "messages": [{"role": "user", "content": content}]}
        if _is_qwen(m):
            body["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            r = _session().post(base_url() + "/chat/completions", json=body, timeout=(8, timeout), headers=_headers())
            if r.status_code == 400 and "chat_template_kwargs" in body:
                body.pop("chat_template_kwargs")
                r = _session().post(base_url() + "/chat/completions", json=body, timeout=(8, timeout),
                                    headers=_headers())
            if r.status_code in (400, 415, 422):
                _no_vision.add(m)                          # รุ่นนี้ไม่รับรูป → จำไว้ ไม่ลองซ้ำ
                errs.append(f"{m.split('/')[-1]}: ดูรูปไม่ได้")
                continue
            if r.status_code != 200:
                raise CloudError(f"{r.status_code} {r.text[:100]}")
            text, _, _, _ = _parse_json(r)
            if text.strip():
                return text.strip()
        except Exception as e:  # noqa: BLE001
            if _CAPACITY.search(str(e)) or str(e).startswith(("429", "5")):
                _mark_bad(m, 3)                            # เต็มจริง → พักรุ่นนี้ชั่วคราว
            errs.append(f"{m.split('/')[-1]}: {str(e)[:80]}")
    raise CloudError("; ".join(errs) or "Cloud AI ดูรูปไม่ได้")


def ping(timeout=8):
    """เช็กคีย์ + รุ่นที่ตั้งไว้ คืน (ok, ข้อความ)"""
    if not config.CLOUD_API_KEY:
        return False, "ยังไม่ได้ใส่คีย์ Cloud AI"
    try:
        r = _session().get(base_url() + "/models", timeout=timeout, headers=_headers())
    except requests.RequestException as e:
        return False, f"เชื่อมต่อไม่ได้ ({e.__class__.__name__})"
    if r.status_code in (401, 403):
        return False, "คีย์ไม่ถูกต้อง"
    if r.status_code != 200:
        return True, f"เชื่อมต่อได้ (ตรวจรายชื่อรุ่นไม่ได้: {r.status_code})"
    try:
        ids = {m.get("id") for m in r.json().get("data", [])}
    except ValueError:
        ids = set()
    miss = [m for m in (config.CLOUD_MODEL, config.CLOUD_MODEL_BACKUP) if m and ids and m not in ids]
    if miss:
        return True, "เชื่อมต่อได้ แต่ไม่พบรุ่น: " + ", ".join(miss)
    return True, f"พร้อมใช้งาน ({config.CLOUD_MODEL.split('/')[-1]})"
