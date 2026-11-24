"""สร้างสื่อ + วิเคราะห์ไฟล์ที่ส่งมา

สร้าง:  "วาดรูป แมวใส่ชุดอวกาศ" · "สร้างภาพ …" · "สร้างวิดีโอ …" · "ทำสไลด์ เรื่อง …"
วิเคราะห์ (แนบไฟล์ 📎 ในแอป / ส่งใน Telegram):
   รูป → อธิบาย/ตอบคำถาม · เสียง → แกะเป็นข้อความ + สรุป · วิดีโอ ≤5 นาที → ภาพนิ่ง 8 ภาพ + เสียงพูด → สรุป
   PDF → อ่านทีละหน้า (ภาพ) → สรุป · Word/ข้อความ → สรุป
"""
import base64
import html
import json
import os
import re
import threading
import time
import urllib.parse
import zipfile

import config


def _b():
    import android_shim
    return android_shim.bridge()


def _out_dir(kind):
    """ที่เก็บไฟล์ที่สร้าง: Pictures/Movies/Documents/ผู้ช่วยAI (เห็นในแกลเลอรี/WPS) — เขียนไม่ได้ใช้ในแอป"""
    base = os.environ.get("SHARED_STORAGE", "/storage/emulated/0")
    sub = {"image": "Pictures", "video": "Movies", "doc": "Documents"}[kind]
    for d in (os.path.join(base, sub, "ผู้ช่วยAI"), os.path.join(config.DATA_DIR, "media")):
        try:
            os.makedirs(d, exist_ok=True)
            t = os.path.join(d, ".w")
            with open(t, "w") as f:
                f.write("1")
            os.remove(t)
            return d
        except OSError:
            continue
    return config.DATA_DIR


def _llm(prompt, system=None):
    import agent
    import polite
    resp, _ = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}], [],
                             system=system or agent.chat_prompt())
    return polite.fix(agent._collect_text(resp.get("content", [])).strip())


def _publish(path):
    if config.ANDROID_APP:
        try:
            _b().mediaUri(path)                  # ให้แกลเลอรี/แอปไฟล์เห็นทันที
        except Exception:  # noqa: BLE001
            pass


# ================================================================ สร้างภาพ

def _english(prompt):
    if re.fullmatch(r"[\x00-\x7F]+", prompt or ""):
        return prompt
    try:
        return _llm(f"แปลคำบรรยายภาพนี้เป็น prompt ภาษาอังกฤษสำหรับ AI วาดภาพ (บรรทัดเดียว ละเอียด ไม่มีคำอธิบาย): {prompt}",
                    "You translate image prompts to English. Output only the prompt.").strip().strip('"')[:600]
    except Exception:  # noqa: BLE001
        return prompt


def _gemini_image(prompt, path):
    import gemini_client
    model = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
    data = gemini_client._post(model, body, timeout=120)
    for p in ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
        inl = p.get("inlineData") or p.get("inline_data")
        if inl and inl.get("data"):
            with open(path, "wb") as f:
                f.write(base64.b64decode(inl["data"]))
            return path
    raise RuntimeError("Gemini ไม่ได้ส่งภาพกลับมา")


def _free_image(prompt, path):
    """Pollinations.ai — ฟรี ไม่ต้องมีคีย์"""
    import requests
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(_english(prompt)) +
           f"?width=1024&height=1024&nologo=true&seed={int(time.time()) % 100000}")
    r = requests.get(url, timeout=120)
    if r.status_code != 200 or len(r.content) < 2000 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"บริการวาดภาพฟรีตอบ {r.status_code}")
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def make_image(prompt, ctx=None):
    if config.MOCK_PHONE:
        return "🎨 (ทดสอบ) สร้างภาพแล้ว"
    path = os.path.join(_out_dir("image"), f"ai_{time.strftime('%Y%m%d_%H%M%S')}.png")
    errs = []
    if config.GEMINI_API_KEY:
        try:
            _gemini_image(prompt, path)
        except Exception as e:  # noqa: BLE001
            errs.append(f"Gemini: {str(e)[:100]}")
    if not os.path.exists(path):
        try:
            path = _free_image(prompt, path[:-4] + ".jpg")
        except Exception as e:  # noqa: BLE001
            errs.append(f"ฟรี: {str(e)[:100]}")
            return "❗ สร้างภาพไม่สำเร็จ (" + " | ".join(errs) + ")"
    _publish(path)
    if ctx is not None and hasattr(ctx, "send_photo"):
        try:
            ctx.send_photo(path)
        except Exception:  # noqa: BLE001
            pass
    return f"🎨 วาดเสร็จแล้ว — บันทึกในแกลเลอรี (อัลบั้ม ผู้ช่วยAI)\n{os.path.basename(path)}"


# ================================================================ สร้างวิดีโอ (Gemini Veo)

def _veo(prompt, path, notify):
    import requests
    key = config.GEMINI_API_KEY
    model = os.environ.get("VIDEO_MODEL", "veo-3.0-fast-generate-001")
    base = "https://generativelanguage.googleapis.com/v1beta"
    h = {"x-goog-api-key": key, "Content-Type": "application/json"}
    r = requests.post(f"{base}/models/{model}:predictLongRunning", headers=h, timeout=60,
                      json={"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": "16:9"}})
    if r.status_code != 200:
        msg = r.text[:200]
        if r.status_code in (403, 429) or "billing" in msg.lower() or "not available" in msg.lower():
            raise RuntimeError("บัญชี Gemini นี้ยังใช้ Veo (สร้างวิดีโอ) ไม่ได้ — ต้องเปิดใช้แบบชำระเงินใน Google AI Studio")
        raise RuntimeError(f"Veo {r.status_code}: {msg}")
    op = r.json().get("name")
    for _ in range(60):                                # รอสูงสุด ~10 นาที
        time.sleep(10)
        st = requests.get(f"{base}/{op}", headers=h, timeout=30).json()
        if st.get("done"):
            if st.get("error"):
                raise RuntimeError(str(st["error"].get("message", st["error"]))[:200])
            samples = (((st.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [])
            uri = samples[0]["video"]["uri"] if samples else None
            if not uri:
                raise RuntimeError("ไม่ได้ไฟล์วิดีโอกลับมา (อาจโดนตัวกรองเนื้อหา)")
            v = requests.get(uri, headers={"x-goog-api-key": key}, timeout=180, allow_redirects=True)
            with open(path, "wb") as f:
                f.write(v.content)
            return path
    raise RuntimeError("รอนานเกิน 10 นาที")


def make_video(prompt, ctx=None):
    if config.MOCK_PHONE:
        return "🎬 (ทดสอบ) กำลังสร้างวิดีโอ"
    if not config.GEMINI_API_KEY:
        return ("🎬 สร้างวิดีโอต้องใช้ Gemini (Veo) — เปิด Gemini ใน ⚙️ ตั้งค่า ก่อน "
                "(Veo เป็นบริการแบบชำระเงินของ Google) · ระหว่างนี้สั่ง \"วาดรูป …\" หรือ \"ทำสไลด์ …\" ได้ฟรี")
    notify = (lambda t: ctx.notify(t)) if ctx is not None and hasattr(ctx, "notify") else print
    path = os.path.join(_out_dir("video"), f"ai_{time.strftime('%Y%m%d_%H%M%S')}.mp4")

    def work():
        try:
            _veo(_english(prompt), path, notify)
            _publish(path)
            notify(f"🎬 วิดีโอเสร็จแล้ว — อยู่ในแกลเลอรี (Movies/ผู้ช่วยAI)\n{os.path.basename(path)}")
            if config.ANDROID_APP:
                _b().openFile(path, "video/mp4")
        except Exception as e:  # noqa: BLE001
            notify(f"❗ สร้างวิดีโอไม่สำเร็จ: {e}")
    threading.Thread(target=work, daemon=True).start()
    return "🎬 กำลังสร้างวิดีโอ (ใช้เวลา 1-5 นาที) เสร็จแล้วจะแจ้งนะครับ"


# ================================================================ สร้างสไลด์

def make_slides(topic, ctx=None, n=7):
    import pptx_lite
    if config.MOCK_PHONE and not os.environ.get("MEDIA_TEST"):
        return "📊 (ทดสอบ) ทำสไลด์แล้ว"
    raw = _llm(f"ทำโครงสไลด์นำเสนอเรื่อง: {topic}\nจำนวน {n} สไลด์ (สไลด์แรกเป็นหน้าปก) ภาษาไทย กระชับ น่าสนใจ\n"
               'ตอบ JSON เท่านั้น: [{"title": "หัวข้อ", "bullets": ["ประเด็นสั้นๆ", ...]}] (แต่ละสไลด์ 3-5 ประเด็น หน้าปกใส่คำโปรย 1 ข้อ)',
               "คุณคือผู้เชี่ยวชาญทำสไลด์นำเสนอ ตอบเป็น JSON ที่ถูกต้องเท่านั้น")
    m = re.search(r"\[.*\]", raw, re.S)
    try:
        slides = json.loads(m.group(0)) if m else []
    except ValueError:
        slides = []
    slides = [s for s in slides if isinstance(s, dict) and s.get("title")]
    if not slides:
        return "❗ AI เขียนโครงสไลด์ไม่สำเร็จ ลองอีกครั้ง"
    safe = re.sub(r"[^\wก-๙]+", "_", topic)[:30].strip("_") or "slides"
    path = os.path.join(_out_dir("doc"), f"สไลด์_{safe}_{time.strftime('%H%M%S')}.pptx")
    theme = "dark" if re.search(r"มืด|ดำ|dark", topic) else "blue" if "ฟ้า" in topic else "green" if "เขียว" in topic else "purple"
    pptx_lite.write(path, slides, theme)
    _publish(path)
    outline = "\n".join(f"{i + 1}. {s['title']}" for i, s in enumerate(slides))
    opened = False
    if config.ANDROID_APP:
        try:
            opened = bool(_b().openFile(path, "application/vnd.openxmlformats-officedocument.presentationml.presentation"))
        except Exception:  # noqa: BLE001
            pass
    if ctx is not None and hasattr(ctx, "send_file") and not config.ANDROID_APP:
        ctx.send_file(path)
    return (f"📊 ทำสไลด์ {len(slides)} หน้าเสร็จแล้ว{' (เปิดให้แล้ว)' if opened else ''}\n{outline}\n\n"
            f"ไฟล์: Documents/ผู้ช่วยAI/{os.path.basename(path)} — แก้ต่อใน WPS ได้เลย")


# ================================================================ วิเคราะห์ไฟล์

def _ask_vision(prompt, images):
    import vision
    ans = vision.ask_images(prompt, images, quality=True)
    if ans is None:
        raise RuntimeError("ต้องมี AI ที่ดูรูปได้ (Cloud AI/Gemini/Claude หรือ Ollama รุ่นดูรูปได้ เช่น qwen3.5:9b)")
    import polite
    return polite.fix(ans.strip())


def _transcript(audio):
    import voice
    segs = voice.transcribe_segments(audio)
    return " ".join(s["text"].strip() for s in segs).strip()


def _xml_text(xml, para_tag):
    return html.unescape(re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", re.sub(para_tag, "\n", xml))))


def _xlsx_text(path, max_cells=3000):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", m)) for m in re.findall(r"<si>(.*?)</si>", xml, re.S)]
        out = []
        for n in sorted(x for x in names if x.startswith("xl/worksheets/sheet"))[:5]:
            xml = z.read(n).decode("utf-8", "ignore")
            out.append(f"## {n.rsplit('/', 1)[-1]}")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S)[:300]:
                cells = []
                for attrs, inner in re.findall(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
                    mv = re.search(r"<v>(.*?)</v>", inner or "", re.S)
                    v = mv.group(1) if mv else re.sub(r"<[^>]+>", "", inner or "")
                    if 't="s"' in attrs and v.isdigit() and int(v) < len(shared):
                        v = shared[int(v)]
                    cells.append(html.unescape(v))
                out.append(" | ".join(cells))
                if len(out) > max_cells:
                    break
        return "\n".join(out)


def _pptx_text(path):
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n".join(f"[สไลด์ {i + 1}] " + _xml_text(z.read(n).decode("utf-8", "ignore"), r"</a:p>")
                         for i, n in enumerate(slides))


def _sum(kind, content, caption):
    q = caption or f"สรุป{kind}นี้ให้หน่อย"
    return _llm(f"{q}\n\nเนื้อหา{kind}:\n{content[:15000]}\n\nตอบภาษาไทย: สรุปสั้นๆ 3-6 ข้อ + ประเด็นสำคัญ/สิ่งที่ต้องทำ (ถ้ามี)")


_WHO_IS = re.compile(r"(นี่|คนนี้|คนในรูป|หน้านี้|บุคคลนี้).*(ใคร|ชื่ออะไร|หา(ข้อมูล|เฟส|ไอจี|โปรไฟล์)|เฟส|ไอจี|facebook|instagram)|"
                     r"(หา|ค้น|ตามหา).*(คน|หน้า).*(จากรูป|ในรูป)|ใครอยู่ในรูป", re.I)


def analyze_file(path, mime="", caption="", ctx=None):
    mime = (mime or "").lower()
    if _WHO_IS.search(caption or ""):
        return ("🙏 ผมช่วยระบุตัวตนหรือตามหาโปรไฟล์ Facebook/IG ของคนจากใบหน้าในรูปไม่ได้ครับ "
                "เพราะเป็นข้อมูลส่วนตัวและอาจถูกใช้ติดตามคนอื่นโดยเขาไม่รู้ตัว\n"
                "ที่ช่วยได้: อธิบายรูป/อ่านข้อความในรูป · ถ้ารู้ชื่ออยู่แล้ว สั่ง \"หา ชื่อ ใน facebook\" ได้เลย · "
                "หรือถามเรื่องสถานที่/สิ่งของ/สินค้าในรูปก็ได้")
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    caption = (caption or "").strip()
    st = (lambda t: ctx.status(t)) if ctx is not None and hasattr(ctx, "status") else (lambda t: None)
    try:
        if mime.startswith("image/") or ext in ("jpg", "jpeg", "png", "webp", "heic"):
            st("👀 กำลังดูรูป")
            return "🖼️ " + _ask_vision((caption or "อธิบายภาพนี้ สรุปสิ่งสำคัญ อ่านข้อความในภาพ (ถ้ามี)") +
                                        "\nตอบภาษาไทย กระชับ เป็นธรรมชาติ", [path])
        if mime.startswith("audio/") or ext in ("mp3", "m4a", "wav", "ogg", "oga", "aac", "flac", "amr", "opus"):
            if os.path.getsize(path) > 24 * 1024 * 1024:
                return "❗ ไฟล์เสียงใหญ่เกิน 24MB (ประมาณ 25 นาที) — ตัดให้สั้นลงก่อนนะครับ"
            st("🎧 กำลังแกะเสียง")
            text = _transcript(path)
            if not text:
                return "🎧 ฟังแล้วไม่พบเสียงพูดในไฟล์นี้"
            summ = _sum("เสียง", text, caption)
            return f"🎧 **ถอดเสียงได้:**\n{text[:2500]}{'…' if len(text) > 2500 else ''}\n\n📝 **สรุป:**\n{summ}"
        if mime.startswith("video/") or ext in ("mp4", "mov", "mkv", "3gp", "webm"):
            if not config.ANDROID_APP:
                return "วิเคราะห์วิดีโอทำได้ในแอป APK"
            st("🎬 กำลังดูวิดีโอ")
            d = os.path.join(config.DATA_DIR, "video_tmp")
            info = json.loads(str(_b().videoFrames(path, d, 8)))
            dur = int(info.get("duration") or 0) / 1000
            if dur > 330:
                return f"❗ วิดีโอยาว {int(dur // 60)} นาที — ส่งได้ไม่เกิน 5 นาทีนะครับ"
            text = ""
            audio = os.path.join(d, "audio.m4a")
            if int(_b().extractAudio(path, audio)) > 0:
                st("🎧 กำลังแกะเสียงในวิดีโอ")
                try:
                    text = _transcript(audio)
                except Exception as e:  # noqa: BLE001
                    text = f"(แกะเสียงไม่ได้: {e})"
            frames = list(info.get("frames") or [])
            q = (caption or "สรุปวิดีโอนี้") + f"\n(วิดีโอยาว {int(dur)} วินาที — ภาพนิ่ง {len(frames)} ภาพเรียงตามเวลา)\n" + \
                (f"เสียงพูดในวิดีโอ: {text[:6000]}\n" if text else "ไม่มีเสียงพูด\n") + \
                "ตอบภาษาไทย: เกิดอะไรขึ้นในวิดีโอ ใครทำอะไร ประเด็นสำคัญ 3-6 ข้อ"
            try:
                out = _ask_vision(q, frames) if frames else _sum("วิดีโอ", text, caption)
            except RuntimeError:
                if not text:
                    raise
                out = _sum("วิดีโอ (จากเสียงพูด)", text, caption)
            return f"🎬 **สรุปวิดีโอ ({int(dur // 60)}:{int(dur % 60):02d} นาที):**\n{out}"
        if mime == "application/pdf" or ext == "pdf":
            if not config.ANDROID_APP:
                return "อ่าน PDF ทำได้ในแอป APK"
            st("📄 กำลังอ่าน PDF")
            pages = json.loads(str(_b().pdfPages(path, os.path.join(config.DATA_DIR, "pdf_tmp"), 6)))
            if not pages:
                return "❗ เปิด PDF นี้ไม่ได้ (อาจมีรหัสผ่าน)"
            return "📄 " + _ask_vision((caption or "สรุปเอกสารนี้") + f"\n(PDF {len(pages)} หน้าแรก) ตอบภาษาไทย สรุป 3-6 ข้อ + ประเด็นสำคัญ", pages)
        if ext in ("xlsx", "xlsm") or "spreadsheetml" in mime:
            st("📊 กำลังอ่านสเปรดชีต")
            return "📊 " + _sum("สเปรดชีต", _xlsx_text(path), caption)
        if ext == "pptx" or "presentationml" in mime:
            st("📊 กำลังอ่านสไลด์")
            return "📊 " + _sum("งานนำเสนอ", _pptx_text(path), caption)
        if ext in ("doc", "xls", "ppt", "rtf"):
            with open(path, "rb") as f:
                raw = f.read(3_000_000)
            txt = " ".join(re.findall(r"[\u0E00-\u0E7Fa-zA-Z0-9 ,.:;()/%-]{4,}", raw.decode("utf-16-le", "ignore")))
            txt = txt if len(txt) > 80 else " ".join(re.findall(r"[a-zA-Z0-9 ,.:;()/%-]{5,}", raw.decode("latin-1", "ignore")))
            return "📄 " + _sum("เอกสาร (ไฟล์แบบเก่า อ่านได้บางส่วน)", txt, caption)
        if ext == "docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            text = re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", xml))
            return "📄 " + _sum("เอกสาร", re.sub(r"[ \t]+", " ", text), caption)
        if mime.startswith("text/") or ext in ("txt", "csv", "md", "json", "log"):
            with open(path, encoding="utf-8", errors="ignore") as f:
                return "📄 " + _sum("ไฟล์", f.read(), caption)
        return f"ยังเปิดไฟล์ประเภทนี้ไม่ได้ ({mime or ext})"
    except Exception as e:  # noqa: BLE001
        return f"❗ วิเคราะห์ไฟล์ไม่สำเร็จ: {e}"


# ================================================================ คำสั่ง

_IMG = re.compile(r"^(?:ช่วย)?\s*(?:วาด|สร้าง|เจน|gen|generate|ทำ)\s*(?:รูป|ภาพ|รูปภาพ|image|picture)\s*(?:ให้หน่อย|หน่อย)?\s*(?:เป็น|ของ|ว่า|:)?\s*(?P<p>.{2,})$", re.I)
_VID = re.compile(r"^(?:ช่วย)?\s*(?:สร้าง|ทำ|เจน|gen)\s*(?:วิดีโอ|วีดีโอ|คลิป|video)\s*(?:ให้หน่อย|หน่อย)?\s*(?:เป็น|ของ|ว่า|เรื่อง|:)?\s*(?P<p>.{2,})$", re.I)
_SLIDE = re.compile(r"^(?:ช่วย)?\s*(?:สร้าง|ทำ|เจน)\s*(?:สไลด์|สไลด|พรีเซนต์|พรีเซน|presentation|powerpoint|พาวเวอร์พอยท์)\s*"
                    r"(?:ให้หน่อย|หน่อย)?\s*(?:เรื่อง|หัวข้อ|เกี่ยวกับ|:)?\s*(?P<p>.{2,})$", re.I)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip()
    t = re.sub(r"\s*(ให้หน่อย|หน่อย|ครับ|ค่ะ|นะ|ที)+\s*$", "", t)
    if not t:
        return None
    m = _SLIDE.match(t)
    if m:
        return make_slides(m.group("p"), ctx)
    m = _VID.match(t)
    if m:
        return make_video(m.group("p"), ctx)
    m = _IMG.match(t)
    if m:
        return make_image(m.group("p"), ctx)
    return None


def _obj(props, req):
    return {"type": "object", "properties": props, "required": req}


TOOLS = {
    "make_image": (lambda a, ctx: make_image(a.get("prompt", ""), ctx), "วาด/สร้างภาพจากคำบรรยาย",
                   _obj({"prompt": {"type": "string"}}, ["prompt"]), False),
    "make_slides": (lambda a, ctx: make_slides(a.get("topic", ""), ctx), "ทำสไลด์นำเสนอ .pptx (เปิดใน WPS ได้)",
                    _obj({"topic": {"type": "string"}}, ["topic"]), False),
    "make_video": (lambda a, ctx: make_video(a.get("prompt", ""), ctx), "สร้างวิดีโอสั้นจากคำบรรยาย (ต้องมี Gemini Veo)",
                   _obj({"prompt": {"type": "string"}}, ["prompt"]), False),
}
