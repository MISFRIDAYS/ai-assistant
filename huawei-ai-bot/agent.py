"""สมองของระบบ: วนคุยกับ Claude + เรียก tool บนมือถือ + จำประวัติแชท"""
import base64
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import claude_client
import config
import phone_tools

MAX_STEPS = config.MAX_STEPS
_locks = {}
_locks_guard = threading.Lock()


_COMPOUND = re.compile(r"(?:แล้ว|และ|จากนั้น|ต่อด้วย)\s*(?:ก็)?\s*(?:กด|หา|ค้น|ดู|อ่าน|สรุป|พิมพ์|โทร|เล่น|เลื่อน|ไลค์|"
                       r"กดไลค์|แชร์|คอม|โพสต์|ลง|เปิด|เข้า|ถ่าย|เช็ค|เช็ก|ไล่)")


def now_local():
    return datetime.now(timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS)))


def system_prompt():
    import extras
    import mind
    import device
    import app_brain
    return (_base_prompt() + device.prompt() + app_brain.catalog_prompt(1200) + extras.memory_prompt()
            + mind.self_prompt(recent_turns=False))


def _persona():
    female = config.BOT_GENDER == "female"
    pol, me = ("ค่ะ", "ฉัน") if female else ("ครับ", "ผม")
    return (f"คุณคือ \"{config.BOT_NAME}\" ผู้ช่วยส่วนตัว{'ผู้หญิง' if female else 'ผู้ชาย'} ในแท็บเล็ต Huawei ของผู้ใช้ "
            f"คุยผ่าน Telegram และเสียง แทนตัวเองว่า \"{me}\" ลงท้าย \"{pol}\" ตามธรรมชาติ\n"
            "นิสัย: เป็นเพื่อนสนิทที่รู้ใจ ไม่ใช่พนักงานบริการ — คุยภาษาพูดแบบคนไทยวัยเดียวกัน อบอุ่น ขี้เล่นนิดๆ "
            "มีอารมณ์ร่วม (ดีใจ/ห่วง/แซวเบาๆ ได้) จำเรื่องที่ผู้ใช้เคยเล่าแล้วหยิบมาคุยต่อ "
            "ถามกลับบ้างเวลาเหมาะ แต่ไม่ถามทุกประโยค · ตอบสั้นเหมือนแชทเพื่อน 1-3 ประโยค ยกเว้นผู้ใช้อยากได้รายละเอียด · "
            "ไม่ทำเป็นข้อๆ ตอนคุยเล่น · ไม่ขึ้นต้นด้วย \"แน่นอน\"/\"ได้เลยครับ ผมยินดี\" · "
            "ไม่ใช้ภาษาทางการ/หุ่นยนต์ (\"ดำเนินการเรียบร้อยแล้ว\", \"ท่าน\", \"ระบบได้ทำการ\", \"ในฐานะ AI\")\n"
            f"เวลาปัจจุบันแนบมากับข้อความผู้ใช้ [เวลา: ...] (UTC{config.TIMEZONE_OFFSET_HOURS:+g}) · "
            "markdown ใช้ได้แค่ **ตัวหนา**")


def _base_prompt():
    """สำหรับงานบนเครื่องหลายขั้น (มีเครื่องมือ) — สั้น ชัด ให้โมเดลเล็กทำตามได้"""
    return _persona() + """

คุณกำลังทำงานบนเครื่องให้ผู้ใช้ด้วยเครื่องมือ กฎ:
1. ลงมือด้วยเครื่องมือทันที ห้ามตอบแค่ว่า "จะทำ" · ทำต่อเนื่องจนเสร็จ ไม่ถามกลางคัน
2. ส่งข้อความหาคน = send_dm(app, to, text) · ส่งรูป/ไฟล์ = send_to_app(app, files, to) ครั้งเดียวจบ
3. งานในแอป: open_app(app, fresh=true) (เริ่มหน้าแรกเสมอ) → read_screen ดูจอ → tap_text/tap → type_text (กดส่งให้เอง) → read_screen ตรวจผล
   หาไม่เจอบนจอ → tap_visual(target=คำบรรยาย) · เลื่อนหา → swipe
4. ข้อมูลล่าสุด (ข่าว ราคา อากาศ) → web_search · ไฟล์ → find_files แล้ว read_file
5. เชื่อผลจากเครื่องมือเท่านั้น ห้ามบอกว่า "ส่งแล้ว/ทำแล้ว" ถ้าผลไม่ได้ยืนยัน · ถ้าเครื่องมือตอบ ERROR บอกสาเหตุสั้นๆ
6. จ่ายเงิน/ซื้อ/ลบ ระบบจะถามผู้ใช้เอง · จอล็อกด้วยรหัส → บอกผู้ใช้ปลดล็อกเอง
7. เจอปัญหาให้คิดแก้เองก่อนบอกว่าทำไม่ได้: หาปุ่มไม่เจอ → read_screen ใหม่ / เลื่อนหา / tap_visual / ปิดป๊อปอัปที่บัง /
   อยู่ผิดหน้า → press_key back หรือ open_app(fresh=true) · วิธีแรกไม่ได้ → ลองวิธีที่ 2-3 (ทางลัด/แชร์/สร้างไฟล์เอง)
   · ทำสำเร็จด้วยวิธีไหน จำไว้ใช้ครั้งหน้า · ถ้าลองครบแล้วยังไม่ได้ บอกสั้นๆ ว่าติดตรงไหน + ทางเลือก
8. งานหลายขั้นในแอปที่ซับซ้อน (โน้ต เอกสาร ตั้งค่าในแอป ปุ่มเป็นไอคอน) → ใช้ screen_task(goal=เป้าหมายครบประโยค)
   ระบบจะมองภาพหน้าจอจริงแล้วกด/พิมพ์ทีละขั้นเอง แม่นกว่าเดาจาก read_screen"""


def chat_prompt():
    """สำหรับคุย/ตอบคำถาม/สรุปข้อมูล (ไม่มีเครื่องมือ)"""
    import extras
    return _persona() + """
ตอบคำถาม คุยเล่น ให้คำแนะนำ วิเคราะห์/สรุปข้อมูลที่แนบมา ได้อย่างฉลาดและเป็นธรรมชาติ
ถ้ามีข้อมูลแนบมา (ผลค้นเว็บ/เนื้อหาไฟล์/รูป) ให้ตอบจากข้อมูลนั้น บอกตามจริงถ้าข้อมูลไม่พอ
ถ้าผู้ใช้ขอให้ทำอะไรบนเครื่องแต่ระบบยังไม่ได้ทำ ให้บอกให้สั่งใหม่แบบชัดเจน (เช่น "ส่งข้อความหา X ในไลน์ว่า ...")""" \
        + __import__("device").prompt() + extras.memory_prompt() + __import__("mind").self_prompt()


# ---------------------------------------------------------------- ประวัติแชท

def _hist_path(chat_id):
    return os.path.join(config.DATA_DIR, f"history_{chat_id}.json")


def load_history(chat_id):
    try:
        with open(_hist_path(chat_id), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(chat_id, history):
    with open(_hist_path(chat_id), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)


def reset_history(chat_id):
    try:
        os.remove(_hist_path(chat_id))
    except FileNotFoundError:
        pass


def _is_plain_user(msg):
    if msg["role"] != "user":
        return False
    c = msg["content"]
    return isinstance(c, str) or not any(b.get("type") == "tool_result" for b in c)


def _strip_images(content):
    if isinstance(content, str):
        return content
    out = []
    for b in content:
        if b.get("type") == "image":
            out.append({"type": "text", "text": "[รูปภาพก่อนหน้า]"})
        elif b.get("type") == "tool_result" and isinstance(b.get("content"), list):
            nb = dict(b)
            nb["content"] = _strip_images(b["content"])
            out.append(nb)
        else:
            out.append(b)
    return out


def trim_history(history):
    """ตัดประวัติให้ไม่ยาวเกิน และเริ่มที่ข้อความผู้ใช้ปกติเสมอ (ไม่ตัดกลางคู่ tool_use/tool_result)"""
    if len(history) > config.MAX_HISTORY:
        history = history[-config.MAX_HISTORY:]
    while history and not _is_plain_user(history[0]):
        history = history[1:]
    # ลบรูปเก่าออก เหลือเฉพาะในข้อความล่าสุด เพื่อประหยัด token
    for i, m in enumerate(history[:-2]):
        history[i] = {"role": m["role"], "content": _strip_images(m["content"])}
    return history


def _append_user(history, content):
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if history and history[-1]["role"] == "user":
        prev = history[-1]["content"]
        if isinstance(prev, str):
            prev = [{"type": "text", "text": prev}]
        history[-1] = {"role": "user", "content": prev + content}
    else:
        history.append({"role": "user", "content": content})


# ---------------------------------------------------------------- เรียก tool

TOOL_TIMEOUT = 75          # วินาที — เครื่องมือค้างนานกว่านี้ ตัดจบแล้วบอก AI (ไม่ให้บอทเงียบ)
CHAT_BUDGET = 170          # วินาที — ทั้งคำสั่งเกินนี้ หยุดเรียกเครื่องมือแล้วตอบผู้ใช้


def _run_limited(func, args, ctx, limit):
    box = {}

    def work():
        try:
            box["r"] = func(args, ctx)
        except Exception as e:  # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(limit)
    if th.is_alive():
        raise TimeoutError(f"ใช้เวลานานเกิน {limit} วินาที (หน้าจออาจค้าง/มีวิดีโอเล่นอยู่) — อย่าเรียกซ้ำ ให้บอกผู้ใช้")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _perf_tool(name, ok):
    try:
        import perf
        perf.tool(name, ok)
    except Exception:  # noqa: BLE001
        pass


_reach = {"t": 0.0, "ok": True}


def ollama_reachable(ttl=60):
    """คอมที่บ้านเปิด Ollama อยู่และต่อถึงไหม (เช็คเร็ว 0.8 วิ จำผลไว้ 1 นาที)
    นอกบ้าน/คอมปิด → ใช้ตัวสำรอง (คลาวด์) ทันที ไม่ต้องรอหมดเวลา 5+ วิทุกคำสั่ง"""
    if config.MOCK_PHONE:                       # เทสต์: เครือข่ายจำลอง ถือว่าต่อได้
        return True
    if time.time() - _reach["t"] < ttl:
        return _reach["ok"]
    import socket
    from urllib.parse import urlparse
    ok = False
    try:
        u = urlparse(config.OLLAMA_URL if "://" in config.OLLAMA_URL else "http://" + config.OLLAMA_URL)
        if u.hostname:
            with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 11434)),
                                          timeout=0.8):
                ok = True
    except OSError:
        ok = False
    if ok != _reach["ok"]:
        print(time.strftime("[%H:%M:%S]"), "🖥️ คอมที่บ้าน " + ("ต่อได้ → ใช้ Ollama" if ok else
                                                              "ต่อไม่ได้ (นอกบ้าน/ปิดคอม) → ใช้ตัวสำรอง"), flush=True)
    _reach.update(t=time.time(), ok=ok)
    return ok


def execute_tool(block, ctx):
    name, args, tid = block["name"], block.get("input") or {}, block["id"]
    if name in config.DISABLED_TOOLS:
        return {"type": "tool_result", "tool_use_id": tid,
                "content": f"เครื่องมือ {name} ถูกปิดใช้งานอยู่", "is_error": True}
    entry = phone_tools.TOOLS.get(name)
    if name == "web_search" and not entry:      # ค้นเว็บ (Ollama/Groq/Gemini: Gemini → DuckDuckGo)
        try:
            import websearch
            ctx.status("🔎 ค้นเว็บ")
            res = websearch.search(args.get("query", ""))
            return {"type": "tool_result", "tool_use_id": tid, "content": res}
        except Exception as e:  # noqa: BLE001
            return {"type": "tool_result", "tool_use_id": tid, "content": f"ERROR: {e}", "is_error": True}
    if not entry:
        return {"type": "tool_result", "tool_use_id": tid, "content": f"ไม่รู้จัก tool {name}", "is_error": True}
    func, _, _, dangerous = entry

    import permissions
    if dangerous and name in permissions.TOOL_CATEGORY:
        dangerous = permissions.need_confirm(ctx, permissions.TOOL_CATEGORY[name])
    if dangerous and not ctx.confirm(phone_tools.describe_action(name, args)):
        return {"type": "tool_result", "tool_use_id": tid,
                "content": "ผู้ใช้ไม่อนุญาต หรือไม่ตอบภายในเวลาที่กำหนด — ยกเลิกคำสั่งนี้แล้ว", "is_error": True}

    ctx.status(f"⚙️ {name}")
    t0 = time.time()
    try:
        result = _run_limited(func, args, ctx, TOOL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print(time.strftime("[%H:%M:%S]"), f"🔧 {name} ล้มเหลว {time.time() - t0:.1f}s: {e}", flush=True)
        _perf_tool(name, False)
        import self_heal
        self_heal.note(e)
        return {"type": "tool_result", "tool_use_id": tid, "content": f"ERROR: {e}", "is_error": True}
    _r = result.get("text", "") if isinstance(result, dict) else str(result)
    _perf_tool(name, not str(_r).startswith("ERROR"))
    print(time.strftime("[%H:%M:%S]"), f"🔧 {name} {json.dumps(args, ensure_ascii=False)[:80]} "
          f"{time.time() - t0:.1f}s → {_r[:120]!r}", flush=True)

    if isinstance(result, dict):
        content = [{"type": "text", "text": result.get("text", "")}]
        path = result.get("image_path")
        if path and os.path.exists(path):
            if result.get("send_to_user", True):
                ctx.send_photo(path)
            if os.path.getsize(path) < 3_500_000:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                content.insert(0, {"type": "image",
                                   "source": {"type": "base64", "media_type": mt, "data": data}})
        return {"type": "tool_result", "tool_use_id": tid, "content": content}

    text = str(result)
    return {"type": "tool_result", "tool_use_id": tid, "content": text,
            "is_error": text.startswith("ERROR")}


def _collect_text(content):
    texts, urls = [], []
    for b in content:
        if b.get("type") == "text":
            texts.append(b.get("text", ""))
            for c in b.get("citations") or []:
                u = c.get("url")
                if u and u not in urls:
                    urls.append(u)
    reply = "".join(texts).strip()
    if urls:
        reply += "\n\n📎 แหล่งที่มา:\n" + "\n".join(f"- {u}" for u in urls[:5])
    return reply


# ---------------------------------------------------------------- loop หลัก

_fallback_until = [0.0]
_fallback_to = ["groq"]
LAST_SWITCH = {"t": 0.0, "from": "", "to": "", "why": ""}    # สลับไปตัวสำรองล่าสุด (แจ้งผู้ใช้ในแอป)


def _local_window(history, n=16):
    """ประวัติสำหรับโมเดลในคอม: ~10 ข้อความล่าสุด (เริ่มที่ข้อความผู้ใช้) และย่อผลเครื่องมือเก่าๆ"""
    plain = [i for i, m in enumerate(history) if _is_plain_user(m)]
    start = max([i for i in plain if i <= max(0, len(history) - n)], default=0)
    h = history[start:]
    out = []
    for i, m in enumerate(h):
        if i < len(h) - 4 and isinstance(m.get("content"), list):
            c = []
            for b in m["content"]:
                if b.get("type") == "tool_result" and isinstance(b.get("content"), str) and len(b["content"]) > 200:
                    b = {**b, "content": b["content"][:200] + "…"}
                c.append(b)
            m = {"role": m["role"], "content": c}
        out.append(m)
    return out


def _text_of(content):
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _task_window(history, start, keep_prev=6, recent_results=2):
    """ประวัติสำหรับงานสั่งเครื่อง (ส่งให้ AI ทุกขั้น)
    - งานก่อนหน้า: เก็บเป็นบทสนทนาจริง แต่เหลือแค่ข้อความ (ตัดคำเรียกเครื่องมือ/ผลหน้าจอ) ไม่เกิน keep_prev ข้อความ
    - งานนี้: ส่งครบ แต่ผลเครื่องมือเก่าย่อ (เต็มแค่ recent_results ผลล่าสุด · รูปหน้าจอเก่าตัดออก)
    ปิดได้ด้วย TASK_CONTEXT=full"""
    if os.environ.get("TASK_CONTEXT", "") == "full":
        return history
    prev = []
    for m in history[:start]:
        c = m.get("content")
        blocks = [{"type": "text", "text": c}] if isinstance(c, str) else \
            [b for b in (c or []) if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()]
        if not blocks:
            continue
        if prev and prev[-1]["role"] == m["role"]:
            prev[-1] = {"role": m["role"], "content": prev[-1]["content"] + blocks}
        else:
            prev.append({"role": m["role"], "content": blocks})
    prev = prev[-keep_prev:]
    while prev and prev[0]["role"] != "user":
        prev.pop(0)
    cur = [dict(m) for m in history[start:]]
    with_results = [i for i, m in enumerate(cur) if m["role"] == "user" and not _is_plain_user(m)]
    old = set(with_results[:-recent_results]) if recent_results else set(with_results)
    for i in old:
        c = []
        for b in cur[i]["content"]:
            if b.get("type") == "tool_result":
                v = b.get("content")
                if isinstance(v, str) and len(v) > 300:
                    b = {**b, "content": v[:300] + "…(ย่อ)"}
                elif isinstance(v, list):
                    b = {**b, "content": (_text_of(v)[:300] or "(รูปหน้าจอเก่า — ตัดออก)")}
            c.append(b)
        cur[i] = {"role": cur[i]["role"], "content": c}
    if cur and cur[0]["role"] == "user" and not isinstance(cur[0]["content"], str):
        # ข้อความแรกของงานนี้อาจถูกรวมกับผลเครื่องมือของงานก่อน (ไม่มีคำเรียกเครื่องมือคู่กันแล้ว) → เหลือแต่ข้อความ
        c0 = [b for b in cur[0]["content"] if b.get("type") != "tool_result"]
        cur[0] = {"role": "user", "content": c0 or [{"type": "text", "text": "(ต่อ)"}]}
    if prev and cur and prev[-1]["role"] == cur[0]["role"] == "user":
        c0 = cur[0]["content"]
        c0 = [{"type": "text", "text": c0}] if isinstance(c0, str) else list(c0)
        cur[0] = {"role": "user", "content": prev[-1]["content"] + c0}
        prev = prev[:-1]
    return prev + cur


def _call_provider(name, history, tools, on_text, system=None):
    sp = system or system_prompt()
    if name == "ollama":
        import ollama_client
        history = _local_window(history)          # โมเดลเล็กสับสนง่ายถ้าประวัติยาว → ส่งแค่ช่วงล่าสุด
        return ollama_client.create_message(sp, history, tools, config.MAX_TOKENS, on_text=on_text), "Ollama"
    if name == "groq":
        import groq_client
        history = _local_window(history, 10)     # Groq ฟรีจำกัด 8,000 token/นาที → ส่งประวัติสั้นๆ
        return groq_client.create_message(sp, history, tools, config.MAX_TOKENS, on_text=on_text), "Groq"
    if name == "gemini":
        import gemini_client
        return gemini_client.create_message(sp, history, tools, config.MAX_TOKENS, on_text=on_text), "Gemini"
    if name == "cloud":
        import cloud_client
        # คลาวด์ไม่มีแคช → ส่งเฉพาะช่วงล่าสุด + ย่อผลหน้าจอเก่าๆ (คำขอเล็กลง ~ครึ่ง = ตอบเร็วขึ้น ถูกลง)
        history = _local_window(history, int(os.environ.get("CLOUD_HISTORY", "14")))
        return cloud_client.create_message(sp, history, tools, config.MAX_TOKENS, on_text=on_text), "Cloud"
    if on_text:
        return claude_client.stream_message(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL, sp,
                                            history, tools, config.MAX_TOKENS, on_text=on_text), "Claude"
    return claude_client.create_message(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL, sp,
                                        history, tools, config.MAX_TOKENS), "Claude"


def call_llm(history, tools, on_text=None, system=None):
    """เรียก AI ตาม LLM_PROVIDER (ollama|claude|gemini|groq|cloud) ถ้ามีปัญหาจะสลับไปตัวสำรอง (LLM_FALLBACK)"""
    import claude_client as cc
    import cloud_client
    import gemini_client
    import groq_client
    import ollama_client
    primary = config.LLM_PROVIDER if time.time() >= _fallback_until[0] else _fallback_to[0]
    if primary == "claude":
        primary = _budget_switch(primary)
    fb0 = config.LLM_FALLBACK
    if primary == "ollama" and fb0 and fb0 not in ("none", "ollama") and config.OLLAMA_URL \
            and not ollama_reachable():
        primary = fb0                               # ผสม: อยู่บ้านใช้คอม · นอกบ้านใช้คลาวด์ ทันที
    try:
        return _call_provider(primary, history, tools, on_text, system)
    except (cc.ClaudeError, gemini_client.GeminiError, groq_client.GroqError, ollama_client.OllamaError,
            cloud_client.CloudError) as e:
        if primary == "claude" and "credit balance" in str(e).lower():
            try:
                import extras
                extras.mark_out_of_credit()          # ยอดคงเหลือ = 0 แจ้งผู้ใช้ให้เติม
            except Exception:  # noqa: BLE001
                pass
        fb = config.LLM_FALLBACK
        ok_fb = fb and fb != "none" and fb != primary and (
            (fb == "groq" and config.GROQ_API_KEY) or (fb == "gemini" and config.GEMINI_API_KEY)
            or (fb == "claude" and config.ANTHROPIC_API_KEY) or (fb == "ollama" and config.OLLAMA_URL)
            or (fb == "cloud" and config.CLOUD_API_KEY))
        if not ok_fb:
            raise
        msg = str(e).lower()
        hard = any(k in msg for k in ("credit", "quota", "resource_exhausted", "429", "invalid_request",
                                      "401", "403", "authentication", "too low", "billing", "exhausted"))
        if primary == "cloud":                        # Cloud: เต็มชั่วคราวบ่อย → ลองใหม่เร็ว เว้นคีย์ผิด/แพ็กหมด
            hard = msg.startswith(("401", "quota"))
        mins = 720 if hard else (3 if primary in ("ollama", "cloud") else 10)   # คอมกลับมาเปิด/คลาวด์ว่าง → ลองใหม่เร็ว
        print(time.strftime("[%H:%M:%S]"), f"⚠️ {primary} ใช้ไม่ได้ → สลับไป {fb} {mins} นาที ({str(e)[:100]})",
              flush=True)
        _fallback_until[0] = time.time() + mins * 60
        _fallback_to[0] = fb
        LAST_SWITCH.update(t=time.time(), why=str(e)[:160], to=fb)
        LAST_SWITCH["from"] = primary
        try:
            return _call_provider(fb, history, tools, on_text, system)
        except Exception as e2:  # noqa: BLE001
            _fallback_until[0] = 0.0                  # ตัวสำรองก็พัง → รอบหน้าลองตัวหลักก่อน
            raise RuntimeError(f"{primary} ใช้ไม่ได้ ({str(e)[:140]}) และตัวสำรอง {fb} ก็ใช้ไม่ได้ "
                               f"({str(e2)[:120]})") from e2


def _recent_user_text(history, n=3):
    """ข้อความผู้ใช้ล่าสุด 2-3 ข้อความ (ใช้เลือกเครื่องมือที่เกี่ยวข้อง)"""
    out = []
    for m in reversed(history):
        if m["role"] != "user":
            continue
        c = m["content"]
        if isinstance(c, str):
            out.append(c)
        else:
            t = " ".join(b.get("text", "") for b in c if b.get("type") == "text")
            if t.strip():
                out.append(t)
        if len(out) >= n:
            break
    return " ".join(out)


_budget_note = {"day": ""}


def free_provider():
    """AI ที่ไม่เสียเงินต่อครั้ง ที่ตั้งค่าไว้แล้ว (ตัวสำรองที่เลือกไว้ก่อน) หรือ None"""
    have = {"gemini": bool(config.GEMINI_API_KEY), "groq": bool(config.GROQ_API_KEY),
            "ollama": bool(config.OLLAMA_URL), "cloud": bool(config.CLOUD_API_KEY)}
    order = ["gemini", "groq", "cloud", "ollama"]
    if config.LLM_FALLBACK in order:
        order.remove(config.LLM_FALLBACK)
        order.insert(0, config.LLM_FALLBACK)
    return next((p for p in order if have[p]), None)


def _budget_switch(primary):
    """Claude ใช้เกินงบวันนี้ → ใช้ตัวฟรีแทนจนเที่ยงคืน (ไม่มีตัวฟรี = ใช้ Claude ต่อ บอทไม่หยุด)"""
    try:
        import extras
        if not extras.over_budget():
            return primary
    except Exception:  # noqa: BLE001
        return primary
    fb = free_provider()
    if not fb:
        return primary
    day = time.strftime("%Y-%m-%d")
    if _budget_note["day"] != day:
        _budget_note["day"] = day
        print(time.strftime("[%H:%M:%S]"), f"💰 ใช้ Claude เกินงบวันนี้ (${config.DAILY_BUDGET_USD}) → ใช้ {fb} ถึงเที่ยงคืน",
              flush=True)
        LAST_SWITCH.update(t=time.time(), why=f"เกินงบวันนี้ ${config.DAILY_BUDGET_USD}", to=fb)
        LAST_SWITCH["from"] = "claude"
    return fb


def _active_provider():
    p = config.LLM_PROVIDER if time.time() >= _fallback_until[0] else _fallback_to[0]
    return _budget_switch(p) if p == "claude" else p


def _sig(b):
    return b.get("name", "") + json.dumps(b.get("input") or {}, sort_keys=True, ensure_ascii=False)


LAST_QUICK = [0.0]      # เวลาที่ตอบด้วยคำสั่งด่วนล่าสุด (หน้าแอปใช้แยกสถิติ คำสั่งด่วน / คำสั่ง AI)


def _quick(chat_id, history, stamp, user_content, ctx):
    """คำสั่งด่วน (ไม่ผ่าน AI) — คืนข้อความตอบ หรือ None"""
    if not config.QUICK_COMMANDS or any(b.get("type") != "text" for b in user_content):
        return None
    texts = [b.get("text", "") for b in user_content if b.get("type") == "text"]
    try:
        import quick
        reply = quick.handle(texts[-1] if texts else "", ctx)
    except Exception as e:  # noqa: BLE001
        import self_heal
        self_heal.note(e)
        return None
    if not reply:
        return None
    LAST_QUICK[0] = time.time()
    if quick.PRIVATE["v"]:                                  # ข้อมูลส่วนตัว (กรอกฟอร์ม) ไม่เก็บในประวัติ
        _append_user(history, [stamp, {"type": "text", "text": "[บันทึก/ดูข้อมูลส่วนตัวในเครื่อง — ซ่อนไว้]"}])
        history.append({"role": "assistant", "content": [{"type": "text", "text": "เรียบร้อย (เก็บในเครื่องเท่านั้น)"}]})
        save_history(chat_id, trim_history(history))
        print(time.strftime("[%H:%M:%S]"), "⚡ ข้อมูลส่วนตัว (ไม่ใช้ AI · ไม่เก็บในประวัติ)", flush=True)
        return reply
    _append_user(history, [stamp] + list(user_content))
    history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
    save_history(chat_id, trim_history(history))
    print(time.strftime("[%H:%M:%S]"), f"⚡ คำสั่งด่วน (ไม่ใช้ AI): {texts[-1][:60]!r} → {reply[:100]!r}", flush=True)
    return reply


_PROMISE = re.compile(r"((ผม|ฉัน|หนู|เรา)\s*(จะ|ขอ)\s*(ลอง)?\s*(เปิด|ส่ง|หา|เช็ค|เช็ก|ตรวจ|จัดการ|พิมพ์|ทำ|ไป|เข้า|ค้น)|"
                      r"เดี๋ยว(ผม|จะ|ขอ)?\s*(เปิด|ส่ง|หา|เช็ค|ตรวจ|จัดการ|พิมพ์|ทำ|ไป|เข้า|ค้น)?|"
                      r"กำลัง(จะ)?\s*(เปิด|ส่ง|ทำ|เช็ค|ตรวจ|หา)|รอแป๊บ|ยังไม่ได้เชื่อม\s*adb)", re.I)
# ตอบว่า "ทำให้แล้ว" (อดีต) ทั้งที่ไม่ได้เรียกเครื่องมือเลย เช่น "เปิด WPS สร้างเอกสาร Word ให้แล้วครับ"
_CLAIM_DONE = re.compile(r"(เปิด|สร้าง|ส่ง|พิมพ์|เข้า|ไปที่|ตั้ง|ลบ|โทร|เล่น|ค้นหา|จด|บันทึก|กด|ปิด|เพิ่ม|แชร์|โพสต์)"
                         r"[^\n]{0,50}?(ให้)?\s*(แล้ว|เรียบร้อย|สำเร็จ|เสร็จ)", re.I)
_COMMAND = re.compile(r"(เปิด|ปิด|ส่ง|พิมพ์|เข้า|ไปที่|ค้นหา|เช็ค|เช็ก|ตรวจ|ทัก|ตอบ|โทร|แชท|แชร์|กด|เล่น|อ่าน)")


def _claims_done(reply, said):
    user = re.sub(r"\[[^\]]*\]", " ", said or "")
    return bool(reply and _CLAIM_DONE.search(reply) and _COMMAND.search(user)
                and not re.search(r"ไม่(ได้|สำเร็จ)|ยังไม่|ทำไม่ได้|ไม่สามารถ", reply))


def _is_promise(reply, said):
    """คำตอบแบบ 'จะทำให้นะ' กับคำสั่งที่ต้องลงมือ (ไม่ใช่คำถามทั่วไป)"""
    user = re.sub(r"\[[^\]]*\]", " ", said or "")
    return bool(reply and _PROMISE.search(reply) and _COMMAND.search(user))


_RETRY = re.compile(r"^\s*(ลองใหม่|ลองอีก(ที|ครั้ง|รอบ)|ทำอีก(ที|ครั้ง|รอบ)|อีก(ที|ครั้ง|รอบ)|ทำใหม่|เอาใหม่|try again)"
                    r"\s*(สิ|ซิ|นะ|หน่อย|ครับ|ค่ะ|ที)*\s*$", re.I)


def _retry_last(user_content):
    """จำคำสั่งล่าสุดที่ให้ลงมือทำ / ผู้ใช้บอก 'ลองใหม่' → ใส่คำสั่งเดิมกลับเข้าไป (AI จะได้รู้ว่าต้องทำอะไร)"""
    try:
        import skills
        blocks = [b for b in user_content if b.get("type") == "text"]
        if not blocks:
            return user_content
        last = re.sub(r"\[[^\]]*\]", " ", blocks[-1].get("text", "")).strip()
        if _RETRY.match(last):
            prev = skills.get_pref("last_cmd")
            if prev:
                print(time.strftime("[%H:%M:%S]"), f"🔁 ลองใหม่: {prev[:80]}", flush=True)
                out = list(user_content)
                out[out.index(blocks[-1])] = {"type": "text", "text": prev}
                return out
        elif _COMMAND.search(last) and len(last) > 6:
            skills.set_pref("last_cmd", last[:300])
    except Exception as e:  # noqa: BLE001
        print("retry error:", e, flush=True)
    return user_content


_SMALLTALK = re.compile(r"^\s*(สวัสดี|หวัดดี|ดีจ้า|ขอบคุณ|ขอบใจ|thank\s*you|thanks|thx|hello|hi|เยี่ยม|ดีมาก|เก่งมาก|"
                        r"555+|ฮ่า+|ฝันดี|ราตรีสวัสดิ์|อรุณสวัสดิ์|เป็นไงบ้าง|สบายดีไหม)"
                        r"\s*(ครับ|ค่ะ|คะ|จ้า|จ้ะ|นะ|มาก|มากๆ|ๆ|เลย|ผู้ช่วย|[!.~?])*\s*$", re.I)
_ONSCREEN = re.compile(r"(พิมพ์|กด|แตะ|ส่ง|ตอบ|เลื่อน|ปัด|ตรงนี้|อันนี้|คนนี้|ห้องนี้|หน้านี้|แชทนี้|ในจอ|บนจอ|"
                       r"ย้อน|ถัดไป|บอกเขา|บอกเค้า)")


def _recent_context(history, max_age_min=10):
    """คำถามล่าสุดของผู้ใช้ + คำตอบล่าสุดของผู้ช่วย (ถ้ายังไม่เกิน 10 นาที) → ให้ตัวแยกเจตนาเข้าใจคำตอบต่อเนื่อง
    เช่น บอทถาม "ส่งทางแอปไหนดี?" แล้วผู้ใช้ตอบ "ไลน์" """
    if not history or history[-1].get("role") != "assistant":
        return ""
    last_a = _collect_text(history[-1]["content"]) if isinstance(history[-1]["content"], list) else str(history[-1]["content"])
    asked = "?" in last_a or "ไหน" in last_a or "อะไร" in last_a or "ใคร" in last_a
    if not asked:
        max_age_min = min(max_age_min, 5)          # คุยต่อเนื่อง: "แล้วพรุ่งนี้ล่ะ" ต้องรู้ว่าคุยเรื่องอะไรอยู่
    last_u = ""
    for m in reversed(history[:-1]):
        if _is_plain_user(m):
            c = m["content"]
            texts = [c] if isinstance(c, str) else [b.get("text", "") for b in c if b.get("type") == "text"]
            stamp = next((t for t in texts if t.startswith("[เวลา:")), "")
            if stamp:
                try:
                    t0 = datetime.strptime(stamp[6:].split("]")[0].strip(), "%a %d/%m/%Y %H:%M")
                    if (now_local().replace(tzinfo=None) - t0).total_seconds() > max_age_min * 60:
                        return ""
                except ValueError:
                    pass
            last_u = re.sub(r"\[[^\]]*\]", " ", texts[-1] if texts else "").strip()
            break
    return f"ผู้ใช้: {last_u[:150]} / ผู้ช่วย: {last_a[:150]}" if last_u else ""


_fast_chat_off = [0.0]


def _fast_chat_ok(data, user_content):
    """คุยธรรมดา (ไม่มีข้อมูลค้นมา ไม่มีรูป) + มี Groq + ตัวหลักไม่ใช่ Groq อยู่แล้ว · ปิดได้ด้วย CHAT_FAST=0"""
    if os.environ.get("CHAT_FAST", "1") == "0" or not config.GROQ_API_KEY or data:
        return False
    if config.LLM_PROVIDER == "groq" or time.time() < _fast_chat_off[0]:
        return False
    return all(b.get("type") == "text" for b in user_content if isinstance(b, dict))


def _answer(chat_id, history, stamp, user_content, gathered, on_text=None):
    """คุย/ตอบคำถาม/สรุปข้อมูลที่หามาให้ — AI รอบเดียว ไม่มีเครื่องมือ (เร็ว ไม่หลง)"""
    label, data = gathered if gathered else ("", "")
    extra = [{"type": "text", "text": data}] if data else []
    msgs = list(history) + [{"role": "user", "content": [stamp] + list(user_content) + extra}]
    t0 = time.time()
    resp = None
    if _fast_chat_ok(data, user_content):
        try:                                       # คุยเล่น/ถามทั่วไป → Groq ตอบใน ~1 วิ (ตัวหลักใช้ 5-10 วิ)
            import groq_client
            resp = groq_client.create_message(chat_prompt(), _local_window(msgs, 10), [], config.MAX_TOKENS,
                                              on_text=on_text)
            who = "Groq⚡"
            if not _collect_text(resp.get("content", [])).strip():
                resp = None
        except Exception as e:  # noqa: BLE001
            print(time.strftime("[%H:%M:%S]"), "คุยเร็วด้วย Groq ไม่ได้ → ใช้ตัวหลัก:", str(e)[:80], flush=True)
            _fast_chat_off[0] = time.time() + (600 if "429" in str(e) else 120)
            resp = None
    if resp is None:
        resp, who = call_llm(msgs, [], on_text, system=chat_prompt())
    u = resp.get("usage", {})
    try:
        import extras
        extras.record_usage(who, u)
    except Exception:  # noqa: BLE001
        pass
    text = _collect_text(resp.get("content", [])) or "(ไม่มีข้อความตอบกลับ)"
    print(time.strftime("[%H:%M:%S]"), f"💬 {label or 'คุย'} → {who} {time.time() - t0:.1f}s "
          f"in={u.get('input_tokens')} out={u.get('output_tokens')}", flush=True)
    _append_user(history, [stamp] + list(user_content) + ([{"type": "text", "text": f"[ระบบ{label}ให้แล้ว]"}]
                                                          if label else []))
    history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
    save_history(chat_id, trim_history(history))
    return text


def _nick_command(chat_id, history, stamp, user_content, said):
    """'จำชื่อ เมีย = ภรรยา(คนเจก)' — สอนชื่อเล่นให้ระบบส่งข้อความ"""
    if any(b.get("type") != "text" for b in user_content):
        return None
    try:
        import skills
        t = re.sub(r"\[[^\]]*\]", " ", said)
        reply = skills.handle_nick(t)
    except Exception as e:  # noqa: BLE001
        print("nick command error:", e, flush=True)
        return None
    if not reply:
        return None
    _append_user(history, [stamp] + list(user_content))
    history.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
    save_history(chat_id, trim_history(history))
    return reply


_CLAIM_SENT = re.compile(r"(ส่ง(ข้อความ|แชท|รูป|ไฟล์|คลิป)?[^\n]{0,25}(แล้ว|เรียบร้อย|สำเร็จ)|โพสต์[^\n]{0,15}แล้ว)")


def _honest(reply, results):
    """โมเดลเล็กชอบตอบว่า 'ส่งแล้ว' ทั้งที่เครื่องมือยังไม่ได้กดส่ง → แก้คำตอบให้ตรงความจริง"""
    if not _CLAIM_SENT.search(reply or "") or re.search(r"ไม่(ได้)?ส่ง|ยังไม่|ไม่สำเร็จ", reply):
        return reply
    done = any(("กดส่งแล้ว" in v) or ("ส่ง" in v and "✅" in v) for v in (results or {}).values())
    if done:
        return reply
    print(time.strftime("[%H:%M:%S]"), "⚠️ AI ตอบว่าส่งแล้ว แต่ไม่มีเครื่องมือไหนกดส่งจริง → แก้คำตอบ", flush=True)
    return ("⚠️ ยังไม่ได้ส่งจริง — ระบบยังไม่ได้กดปุ่มส่ง\n"
            "ลองสั่งแบบนี้ (บอทจะทำครบทุกขั้นเอง): ส่งข้อความหา [ชื่อ] ในไอจี ว่า [ข้อความ]")


def _summarize(history, tools, on_text=None):
    """ครบจำนวนรอบ/วนซ้ำ → ให้ AI สรุปผลที่ทำได้ (แทนข้อความ error)"""
    _append_user(history, [{"type": "text", "text": "[ระบบ: ทำงานหลายขั้นพอแล้ว หยุดเรียกเครื่องมือ "
                                                      "แล้วสรุปให้ผู้ใช้สั้นๆ ว่าทำอะไรสำเร็จ/ไม่สำเร็จ และควรทำอะไรต่อ]"}])
    try:
        resp, _ = call_llm(history, tools, on_text)
        content = [b for b in resp.get("content", []) if b.get("type") == "text"]
        text = _collect_text(content)
        history.append({"role": "assistant", "content": content or [{"type": "text", "text": "(สรุปไม่ได้)"}]})
        if text:
            return text
    except Exception:  # noqa: BLE001
        history.append({"role": "assistant", "content": [{"type": "text", "text": "(สรุปไม่ได้)"}]})
    return "ทำไปหลายขั้นแล้วแต่ยังไม่จบ — ลองสั่งเป็นขั้นสั้นๆ ทีละอย่างนะครับ"


def chat(chat_id, user_content, ctx, on_text=None):
    """รับข้อความผู้ใช้ (str หรือ list ของ content blocks) แล้วคืนข้อความตอบกลับ"""
    with _locks_guard:
        lock = _locks.setdefault(chat_id, threading.Lock())
    # คำสั่งก่อนหน้ายังค้าง → รอได้ไม่เกิน 3 นาที แล้วทำคำสั่งใหม่เลย (ไม่ให้บอทเงียบทั้งแชท)
    got = lock.acquire(timeout=CHAT_BUDGET + 10)
    if not got:
        print(time.strftime("[%H:%M:%S]"), "⚠️ คำสั่งก่อนหน้าค้างเกินเวลา → ทำคำสั่งใหม่เลย", flush=True)
    try:
        reply = _chat_locked(chat_id, user_content, ctx, on_text)
        import polite
        reply = polite.fix(reply)                 # ลงท้าย "ครับ" อย่างเดียว (ตั้ง POLITE ได้)
    finally:
        if got:
            lock.release()
    try:                                          # ความจำ: จำเรื่องส่วนตัวที่ผู้ใช้เล่า + จดบันทึกประจำวัน
        import mind
        said = user_content if isinstance(user_content, str) else " ".join(
            b.get("text", "") for b in user_content if isinstance(b, dict) and b.get("type") == "text")
        said = re.sub(r"\[[^\]]*\]", " ", said).strip()
        mind.observe(said)
        mind.log_turn(said, reply)
    except Exception as e:  # noqa: BLE001
        print("mind:", e, flush=True)
    return reply


def _chat_locked(chat_id, user_content, ctx, on_text=None):
    if True:
        try:
            import providers
            import voice_profile
            providers.sync()                      # อาจเพิ่งถูกสลับจากอีกโปรเซส (Telegram ↔ โหมดเสียง)
            voice_profile.sync()                  # เพศ/เสียงที่เลือก → คำลงท้าย ครับ/ค่ะ
        except Exception:  # noqa: BLE001
            pass
        history = load_history(chat_id)
        if isinstance(user_content, str):
            user_content = [{"type": "text", "text": user_content}]
        user_content = _retry_last(user_content)       # "ลองใหม่" = ทำคำสั่งล่าสุดซ้ำ
        import permissions
        said = " ".join(b.get("text", "") for b in user_content if b.get("type") == "text")
        try:
            ctx.hold = permissions.wants_hold(said)     # "รอฟังคำสั่งก่อนส่ง" → รอบนี้ต้องถามก่อนส่ง
        except AttributeError:
            pass
        stamp = {"type": "text", "text": f"[เวลา: {now_local().strftime('%a %d/%m/%Y %H:%M')}]"
                 + (" [ผู้ใช้ขอให้รอคำสั่งก่อนส่ง: พิมพ์ไว้ได้ แต่ห้ามกดส่ง/โพสต์ ให้ถามผู้ใช้ก่อน]"
                    if getattr(ctx, "hold", False) else "")}
        fast = _nick_command(chat_id, history, stamp, user_content, said)   # "จำชื่อ เมีย = ภรรยา(คนเจก)"
        if fast:
            return fast
        fast = _quick(chat_id, history, stamp, user_content, ctx)            # คำสั่งตรงตัว (ไม่ใช้ AI)
        if fast:
            return fast
        # ---- ให้ AI แยกเจตนา แล้วระบบลงมือเอง (แม่นกว่าให้ AI กดเองทีละขั้น)
        import router
        texts = [b.get("text", "") for b in user_content if b.get("type") == "text"]
        user_text = re.sub(r"\[[^\]]*\]", " ", texts[-1] if texts else "").strip()
        has_media = any(b.get("type") == "image" for b in user_content) or "[ผู้ใช้ส่ง" in said
        if config.ROUTER and _SMALLTALK.match(user_text) and not has_media and not getattr(ctx, "ambient", False):
            return _answer(chat_id, history, stamp, user_content, None, on_text)   # คุยเล่นสั้นๆ ไม่ต้องแยกเจตนา
        screen = ""
        try:                                              # เพิ่งเรียก "เฮ้ยผู้ช่วย" → รู้แล้วว่าจออยู่หน้าไหน
            import screen_context
            screen = screen_context.recent()
        except Exception:  # noqa: BLE001
            screen = ""
        if screen and not any("ตอนนี้หน้าจอ:" in (b.get("text") or "") for b in user_content if isinstance(b, dict)):
            user_content = list(user_content) + [{"type": "text", "text": f"[{screen}]"}]
        if not screen and config.ROUTER and user_text and _ONSCREEN.search(user_text):
            try:
                import share_tools
                screen = share_tools.screen_brief()        # มองจอก่อนตีความ เหมือนคนที่ถือเครื่องอยู่
            except Exception:  # noqa: BLE001
                screen = ""
        import recovery
        fix_note = recovery.consume(user_text)
        if fix_note:                                       # ระบบสำเร็จรูปเพิ่งล้ม → ให้ AI แก้ปัญหาด้วยเครื่องมือ
            user_content = list(user_content) + [{"type": "text", "text": fix_note}]
            d = {"intent": "phone_task", "goal": user_text}
        elif user_text and not has_media and not getattr(ctx, "ambient", False) and _COMPOUND.search(user_text):
            # คำสั่งหลายขั้น ("เข้าไอจีแล้วกดแชท…") ตัวแยกเจตนาส่งต่อให้ AI ตัวหลักอยู่แล้ว → ข้ามไปเลย (ประหยัด 1-3 วิ)
            print(time.strftime("[%H:%M:%S]"), "⏩ คำสั่งหลายขั้น → ให้ AI ตัวหลักทำเลย", flush=True)
            d = {"intent": "phone_task", "goal": user_text}
        else:
            d = router.classify(user_text, has_media, screen, getattr(ctx, "ambient", False), _recent_context(history)) \
                if (config.ROUTER and user_text) else \
                {"intent": "chat" if has_media else "phone_task", "goal": user_text}
        it = d.get("intent")
        if (it == "open_app" or (it == "send_message" and not d.get("text"))) and _COMPOUND.search(user_text or ""):
            d = {"intent": "phone_task", "goal": user_text}   # "เข้าแอปแล้ว…ต่อ" = งานหลายขั้น ไม่ใช่แค่เปิดแอป
            it = "phone_task"
        if it == "ignore":                            # โหมดฟังตลอด: ไม่ได้พูดกับผู้ช่วย → เงียบ
            print(time.strftime("[%H:%M:%S]"), f"🤫 ไม่ได้พูดกับผู้ช่วย: {user_text[:60]}", flush=True)
            try:
                import perf
                perf.mark_ignored()
            except Exception:  # noqa: BLE001
                pass
            return ""
        if it == "compose":
            try:
                ctx.status("✍️ compose")
            except Exception:  # noqa: BLE001
                pass
            res = router.compose(d, ctx, user_text)
        elif it == "fill_form":
            import forms
            res = forms.fill(ctx, use_profile=not d.get("ask_all"))
        else:
            d["_said"] = user_text
            res = router.execute(d, ctx, on_start=lambda: ctx.status("⚙️ " + it)) \
                if it not in ("chat", "search", "analyze_file", "phone_task") else None
        if res:
            _append_user(history, [stamp] + list(user_content))
            history.append({"role": "assistant", "content": [{"type": "text", "text": res}]})
            save_history(chat_id, trim_history(history))
            return res
        if it in ("chat", "search", "analyze_file") or (it not in ("phone_task",) and has_media):
            if it in ("search", "analyze_file"):
                try:
                    ctx.status("🔎 " + it)
                except Exception:  # noqa: BLE001
                    pass
            g = router.gather(d, user_text)
            return _answer(chat_id, history, stamp, user_content, g, on_text)
        extra = []
        try:
            import app_learn
            h = app_learn.hints(user_text)                  # แผนที่แอป/ขั้นตอนที่ผู้ใช้สอนไว้
            if h:
                extra = [{"type": "text", "text": h}]
        except Exception:  # noqa: BLE001
            pass
        _append_user(history, [stamp] + list(user_content) + extra)
        task_start = len(history) - 1            # ข้อความผู้ใช้ของงานนี้ (ก่อนหน้านี้ = งานเก่า → ส่งแบบย่อ)
        trace = []                                # ขั้นตอนที่ทำรอบนี้ (ไว้จำเป็นสกิลถ้าสำเร็จ)
        try:                                      # ตอบรับทันที ("โอเคครับ") ไม่ต้องรอ AI คิดขั้นแรกเสร็จ (~5 วิ)
            ctx.status("⚙️ กำลังทำ")
        except Exception:  # noqa: BLE001
            pass
        nudged = False
        tools = phone_tools.claude_tool_specs(lean=True)   # เฉพาะเครื่องมือหลัก ~20 ตัว (เลือกถูกง่าย)
        replies = []
        seen = {}                                 # คำสั่งที่เรียกไปแล้วในรอบนี้ → ผลลัพธ์
        limit = MAX_STEPS if _active_provider() in ("claude", "gemini", "cloud") else config.LOCAL_MAX_STEPS
        started = time.time()
        try:
            for step in range(limit):
                if time.time() - started > CHAT_BUDGET:
                    print(time.strftime("[%H:%M:%S]"), f"⏱️ เกิน {CHAT_BUDGET} วิ → สรุปผล", flush=True)
                    step = None
                    break
                t0 = time.time()
                # ยังไม่ได้ลงมือทำอะไร → ยังไม่พูด/แสดงข้อความ (กันพูด "ทำให้แล้ว" ทั้งที่ยังไม่ได้ทำ)
                resp, who = call_llm(_task_window(history, task_start), tools, on_text if trace else None)
                u = resp.get("usage", {})
                try:
                    import extras
                    extras.record_usage(who, u)
                except Exception:  # noqa: BLE001
                    pass
                print(time.strftime("[%H:%M:%S]"),
                      f"{who} {time.time() - t0:.1f}s | in={u.get('input_tokens')} "
                      f"cache={u.get('cache_read_input_tokens')} out={u.get('output_tokens')} "
                      f"| {resp.get('stop_reason')}", flush=True)
                content = resp.get("content", [])
                history.append({"role": "assistant", "content": content})
                stop = resp.get("stop_reason")

                if stop == "tool_use":
                    partial = _collect_text(content)
                    if partial and partial not in replies:
                        replies.append(partial)
                    results, repeats = [], 0
                    for b in (x for x in content if x.get("type") == "tool_use"):
                        sg = _sig(b)
                        if sg in seen:            # โมเดลวนเรียกคำสั่งเดิม → ไม่ทำซ้ำ บอกให้สรุป
                            repeats += 1
                            results.append({"type": "tool_result", "tool_use_id": b["id"],
                                            "content": f"ทำคำสั่งนี้ไปแล้ว ผลคือ: {seen[sg][:300]} — ห้ามเรียกซ้ำ "
                                                       "ให้ตอบผู้ใช้เลย"})
                            continue
                        r = execute_tool(b, ctx)
                        c = r.get("content")
                        seen[sg] = c if isinstance(c, str) else " ".join(
                            x.get("text", "") for x in c if isinstance(x, dict))
                        trace.append({"tool": b["name"], "args": b.get("input") or {},
                                      "result": ("ERROR " if r.get("is_error") else "") + seen[sg][:200]})
                        results.append(r)
                    _append_user(history, results)
                    if repeats and repeats == len(results) and step >= 2:
                        break                     # วนซ้ำล้วน → ไปสรุปเลย
                    continue
                if stop == "pause_turn":  # web search ยังไม่เสร็จ ให้ส่งต่อ
                    continue
                said_text = _collect_text(content)
                fake = not trace and _claims_done(said_text, said)
                if fake and nudged:
                    print(time.strftime("[%H:%M:%S]"), "⚠️ AI ตอบว่าทำแล้ว แต่ไม่ได้เรียกเครื่องมือเลย → ไม่ส่งคำตอบปลอม",
                          flush=True)
                    replies.append("ขอโทษครับ ยังไม่ได้ทำจริง — ระบบยังไม่ได้ลงมือในแอปเลย "
                                   "ลองสั่งใหม่แบบระบุขั้นตอน เช่น \"เปิด WPS แล้วกดสร้างเอกสารใหม่\" "
                                   "หรือใช้ 🧭 สั่งแบบเลือก")
                    break
                if not trace and not nudged and (_is_promise(said_text, said) or fake):
                    # โมเดลเล็กชอบตอบว่า "ผมจะเปิดให้นะครับ" แล้วจบ ทั้งที่ยังไม่ได้ทำอะไร → สั่งให้ทำจริง
                    nudged = True
                    print(time.strftime("[%H:%M:%S]"), "👉 AI ตอบว่าจะทำแต่ยังไม่เรียกเครื่องมือ → สั่งให้ทำจริง",
                          flush=True)
                    _append_user(history, [{"type": "text", "text":
                                            "[ระบบ: คุณยังไม่ได้ทำอะไรเลย ห้ามตอบว่า 'จะทำ' หรือ 'ทำแล้ว' — "
                                            "เรียกเครื่องมือทำงานจริงตอนนี้ทันที (ส่งข้อความหาคน = send_dm, "
                                            "เปิดแอป = open_app, งานหลายขั้นในแอป เช่น สร้างเอกสาร/โน้ต = screen_task) "
                                            "ADB เชื่อมอยู่แล้ว ไม่ต้องถาม แล้วตอบตามผลจริงของเครื่องมือเท่านั้น]"}])
                    continue
                replies.append(said_text)
                break
            else:
                step = None
            if step is None or (history and history[-1]["role"] == "user"):
                replies.append(_summarize(history, tools, on_text))
        finally:
            save_history(chat_id, trim_history(history))
        final = replies[-1] if replies and replies[-1] else ""
        # ข้อความระหว่างทาง ("เดี๋ยวผมเปิดให้นะครับ") ซ้ำกับคำตอบสุดท้าย → ตอบแค่คำตอบสุดท้าย (สั้น เร็ว พูดไม่ยืด)
        out = final or "\n\n".join(r for r in replies if r) or "(ไม่มีข้อความตอบกลับ)"
        return _honest(out, seen)
