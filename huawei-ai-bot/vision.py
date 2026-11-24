"""กล้องของผู้ช่วย: มองเห็น · หาใบหน้า · จำหน้าเจ้าของ (ทำในเครื่อง) · อธิบายสิ่งที่เห็น (ใช้ AI ที่ดูรูปได้)

- "จำหน้าฉัน"           → ถ่ายกล้องหน้า 3 รูป เก็บ "ลายหน้า" (LBP) ไว้ในเครื่อง
- "ใครอยู่หน้ากล้อง"     → เทียบลายหน้า (+ ให้ AI ช่วยยืนยันถ้ามี Gemini/Claude)
- "มองดูหน่อย" / "เห็นอะไรบ้าง" → ถ่ายแล้วให้ AI อธิบายเป็นภาษาไทย
รูปเก็บที่ data/camera (ลบเก่าเอง) · ลายหน้าเจ้าของ data/faces/owner.json
"""
import base64
import glob
import json
import os
import re
import time

import config

_DIR = lambda *p: os.path.join(config.DATA_DIR, *p)  # noqa: E731


def _b():
    import android_shim
    return android_shim.bridge()


def _cleanup():
    files = sorted(glob.glob(_DIR("camera", "*.jpg")), key=os.path.getmtime)
    for f in files[:-12]:
        try:
            os.remove(f)
        except OSError:
            pass


def capture(front=True):
    """ถ่ายรูป → (path, faces[], error)"""
    if not config.ANDROID_APP:
        return None, [], "กล้องใช้ได้ในแอป APK เท่านั้น"
    os.makedirs(_DIR("camera"), exist_ok=True)
    _cleanup()
    path = _DIR("camera", f"shot_{int(time.time() * 1000)}.jpg")
    err = str(_b().camCapture(bool(front), path))
    if err:
        return None, [], err
    face_path = path[:-4] + "_face.jpg"
    try:
        faces = json.loads(str(_b().camFaces(path, face_path)))
    except ValueError:
        faces = []
    return path, faces, ""


def _vec(face_path):
    try:
        return json.loads(str(_b().faceVector(face_path)))
    except ValueError:
        return []


def chi2(a, b):
    return sum((x - y) ** 2 / (x + y) for x, y in zip(a, b) if x + y > 0)


def _owner():
    try:
        with open(_DIR("faces", "owner.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ================================================================ AI ที่ดูรูปได้

_gv = {"model": None, "checked": 0.0}


def _groq_vision_model():
    """รุ่นของ Groq ที่ดูรูปได้ (ตรวจจากรายชื่อจริง จำไว้ 6 ชม.)"""
    if os.environ.get("GROQ_VISION_MODEL"):
        return os.environ["GROQ_VISION_MODEL"]
    if time.time() - _gv["checked"] < 6 * 3600:
        return _gv["model"]
    _gv["checked"] = time.time()
    try:
        import groq_client
        ms = groq_client.list_models()
        pick = [m for m in ms if re.search(r"llama-4-scout|llama-4-maverick|vision|scout|maverick", m, re.I)]
        pick.sort(key=lambda m: (0 if "scout" in m else 1, m))
        _gv["model"] = pick[0] if pick else None
    except Exception:  # noqa: BLE001
        _gv["model"] = None
    return _gv["model"]


def _groq_vision(prompt, imgs):
    import groq_client
    content = [{"type": "text", "text": prompt + "\n(ตอบเป็นภาษาไทย)"}] + \
              [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{d}"}} for d in imgs[:5]]
    r = groq_client._session().post(groq_client.URL, timeout=25,
                                    headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                                    json={"model": _groq_vision_model(), "max_tokens": 800, "temperature": 0.3,
                                          "messages": [{"role": "user", "content": content}]})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:100]}")
    data = json.loads(r.content.decode("utf-8", "replace"))
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _small(path, max_dim=896):
    """ย่อรูปใหญ่ให้เหลือด้านยาว ~1024px (ทำในเครื่องด้วย Android) — ย่อไม่ได้ใช้รูปเดิม"""
    try:
        if os.path.getsize(path) < 180_000 or not config.ANDROID_APP:
            return path
        out = os.path.join(config.DATA_DIR, "vis_" + os.path.basename(path).rsplit(".", 1)[0] + ".jpg")
        return out if _b().shrinkImage(path, out, max_dim) else path
    except Exception:  # noqa: BLE001
        return path


def _cloud_vision(prompt, imgs, t0, errs):
    if not (config.CLOUD_API_KEY and config.CLOUD_VISION):
        return None
    try:
        import cloud_client
        out = cloud_client.vision(prompt, imgs)
        if out:
            print(f"[vision] Cloud {time.time() - t0:.1f}s", flush=True)
            return out
    except Exception as e:  # noqa: BLE001
        errs.append(f"Cloud: {str(e)[:80]}")
    return None


def ask_images(prompt, paths, quality=False):
    """ส่งรูปให้ AI ดู คืนข้อความ หรือ None ถ้าไม่มี AI ที่ดูรูปได้
    quality=False (ดูเร็ว): Groq → Cloud → Gemini → Claude → Ollama
    quality=True (ดูละเอียด เช่น ไฟล์ที่ผู้ใช้ส่ง/เรียนรู้ไอคอน): Cloud (Qwen3.5/Kimi K3) ก่อน"""
    imgs = []
    for p in paths:
        p = _small(p)                                  # ย่อรูปก่อนส่ง (รูปจากกล้อง 5-10MB → ~150KB) เร็วขึ้นมาก
        with open(p, "rb") as f:
            imgs.append(base64.b64encode(f.read()).decode())
    errs = []
    t0 = time.time()
    if quality:
        out = _cloud_vision(prompt, imgs, t0, errs)
        if out:
            return out
    if config.GROQ_API_KEY and _groq_vision_model():
        try:                                           # เร็วที่สุด (~1-2 วิ)
            out = _groq_vision(prompt, imgs)
            if out:
                print(f"[vision] Groq {time.time() - t0:.1f}s", flush=True)
                return out
        except Exception as e:  # noqa: BLE001
            errs.append(f"Groq: {str(e)[:80]}")
    if not quality:
        out = _cloud_vision(prompt, imgs, t0, errs)
        if out:
            return out
    if config.GEMINI_API_KEY:
        try:
            import requests
            parts = [{"inline_data": {"mime_type": "image/jpeg", "data": d}} for d in imgs] + [{"text": prompt}]
            model = os.environ.get("GEMINI_VISION_MODEL", "gemini-flash-lite-latest")
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": config.GEMINI_API_KEY}, timeout=30,
                              json={"contents": [{"role": "user", "parts": parts}],
                                    "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}, "maxOutputTokens": 800}})
            if r.status_code != 200:                    # ไม่ลองซ้ำหลายรอบ (ช้า) → ข้ามไปตัวถัดไปเลย
                raise RuntimeError(f"{r.status_code} {r.text[:120]}")
            data = json.loads(r.content.decode("utf-8", "replace"))
            cand = (data.get("candidates") or [{}])[0]
            out = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
            if out:
                print(f"[vision] Gemini {time.time() - t0:.1f}s", flush=True)
                return out
        except Exception as e:  # noqa: BLE001
            errs.append(f"Gemini: {str(e)[:100]}")
    try:
        import extras
        _claude_ok = not (extras.over_budget() and config.OLLAMA_URL)   # เกินงบ + มีตัวฟรี → ข้าม Claude
    except Exception:  # noqa: BLE001
        _claude_ok = True
    if config.ANTHROPIC_API_KEY and _claude_ok:
        try:
            import claude_client
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": d}} for d in imgs]
            content.append({"type": "text", "text": prompt})
            r = claude_client.create_message(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL, "ตอบเป็นภาษาไทย กระชับ",
                                             [{"role": "user", "content": content}], None, 700)
            try:
                import extras
                extras.record_usage("Claude", r.get("usage", {}))
            except Exception:  # noqa: BLE001
                pass
            return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        except Exception as e:  # noqa: BLE001
            errs.append(f"Claude: {e}")
    model = os.environ.get("OLLAMA_VISION_MODEL", "").strip()
    if not model and re.match(r"(qwen3\.5|qwen3-vl|qwen2\.5vl|gemma3|gemma4|llava|mistral-small3|llama3\.2-vision)",
                              config.OLLAMA_MODEL or ""):
        model = config.OLLAMA_MODEL                      # โมเดลหลักดูรูปได้อยู่แล้ว
    if config.OLLAMA_URL and model:
        try:
            import requests
            import ollama_client
            r = requests.post(config.OLLAMA_URL.split(",")[0].strip().rstrip("/") + "/api/chat", timeout=120,
                              headers=ollama_client.auth_headers(), json={
                "model": model, "stream": False,
                "messages": [{"role": "user", "content": prompt, "images": imgs}]})
            return r.json().get("message", {}).get("content", "")
        except Exception as e:  # noqa: BLE001
            errs.append(f"Ollama: {e}")
    if errs:
        raise RuntimeError("; ".join(errs)[:300])
    return None


# ================================================================ คำสั่ง

def enroll_owner(ctx=None, arg=""):
    import user_profile
    name = (arg or user_profile.load().get("nickname") or user_profile.load().get("first_name") or "เจ้าของ").strip()
    vecs, kept = [], []
    for i in range(4):
        path, faces, err = capture(front=True)
        if err:
            return f"📷 {err}"
        if faces:
            v = _vec(path[:-4] + "_face.jpg")
            if v:
                vecs.append(v)
                kept.append(path[:-4] + "_face.jpg")
        if len(vecs) >= 3:
            break
        time.sleep(0.8)
    if len(vecs) < 2:
        return "📷 ไม่เห็นหน้าชัดพอ — หันหน้าตรงกล้องหน้า ในที่สว่าง แล้วลองใหม่"
    d = [chi2(a, b) for i, a in enumerate(vecs) for b in vecs[i + 1:]]
    thr = max(d) * 1.6 + 0.15                         # เผื่อแสง/มุมต่างจากตอนสอน
    os.makedirs(_DIR("faces"), exist_ok=True)
    for i, p in enumerate(kept[:3]):
        os.replace(p, _DIR("faces", f"owner_{i}.jpg"))
    with open(_DIR("faces", "owner.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "vecs": vecs, "threshold": round(thr, 3), "t": time.strftime("%Y-%m-%d")}, f)
    return f"😊 จำหน้า{name}แล้ว ({len(vecs)} รูป เก็บในเครื่อง) — ลองถาม \"ใครอยู่หน้ากล้อง\""


def who_is_there(ctx=None, arg=""):
    path, faces, err = capture(front=True)
    if err:
        return f"📷 {err}"
    if not faces:
        return "👀 ไม่เห็นใครอยู่หน้ากล้องเลย"
    owner = _owner()
    n = len(faces)
    if not owner:
        return f"👀 เห็นคน {n} คน — ยังไม่รู้จักใครเลย สั่ง \"จำหน้าฉัน\" ก่อนนะ"
    v = _vec(path[:-4] + "_face.jpg")
    dist = min((chi2(v, o) for o in owner["vecs"]), default=99) if v else 99
    local = dist <= owner["threshold"]
    verdict = None
    refs = sorted(glob.glob(_DIR("faces", "owner_*.jpg")))[:1]
    if refs and os.path.exists(path[:-4] + "_face.jpg"):
        try:
            ans = ask_images("รูปแรกคือเจ้าของเครื่อง รูปที่สองคือคนที่อยู่หน้ากล้องตอนนี้ เป็นคนเดียวกันไหม "
                             "ตอบขึ้นต้นด้วย ใช่ หรือ ไม่ใช่ แล้วตามด้วยเหตุผลสั้นๆ 1 ประโยค",
                             [refs[0], path[:-4] + "_face.jpg"])
            if ans:
                verdict = ans.strip().startswith("ใช่")
        except Exception:  # noqa: BLE001
            pass
    me = verdict if verdict is not None else local
    print(f"[face] dist={dist:.3f} thr={owner['threshold']} local={local} ai={verdict}", flush=True)
    others = f" และคนอื่นอีก {n - 1} คน" if n > 1 else ""
    if me:
        hour = int(time.strftime("%H"))
        hi = "สวัสดีตอนเช้า" if hour < 12 else ("สวัสดีตอนบ่าย" if hour < 18 else "สวัสดีตอนค่ำ")
        return f"😊 {hi}ครับคุณ{owner['name']}{others}"
    return f"🤔 เห็นคนที่ไม่รู้จัก{others} (ไม่ใช่คุณ{owner['name']})"


def look(ctx=None, arg="back"):
    front = str(arg).strip().lower() in ("front", "หน้า", "selfie")
    path, faces, err = capture(front=front)
    if err:
        return f"📷 {err}"
    try:
        ans = ask_images("อธิบายสิ่งที่เห็นในภาพนี้เป็นภาษาไทย กระชับ 2-4 ประโยค บอกสิ่งสำคัญ/ข้อความที่อ่านได้ "
                         "ถ้ามีคนให้บอกจำนวนและท่าทางโดยไม่ระบุตัวตน", [path])
    except Exception as e:  # noqa: BLE001
        return f"📷 ถ่ายแล้ว แต่ให้ AI ดูไม่ได้ ({str(e)[:120]})"
    if ans is None:
        return (f"📷 ถ่ายแล้ว เห็นใบหน้า {len(faces)} หน้า — ถ้าอยากให้อธิบายภาพได้ ต้องเปิดใช้ Gemini หรือ Claude "
                "(หรือใส่ OLLAMA_VISION_MODEL เช่น llava)")
    return "👀 " + ans.strip()


def look_ask(question, front=True, ctx=None):
    """ตอบคำถามจากสิ่งที่กล้องเห็น เช่น "ถืออะไรอยู่" "ฉันกำลังทำอะไร" """
    path, faces, err = capture(front=front)
    if err:
        return f"📷 {err}"
    try:
        ans = ask_images(f"ผู้ใช้ถาม: \"{question}\" (ภาพจากกล้อง{'หน้า ผู้ใช้อยู่หน้ากล้อง' if front else 'หลัง'})\n"
                         "ตอบคำถามจากสิ่งที่เห็นในภาพเป็นภาษาไทย สั้นๆ 1-3 ประโยค เป็นกันเอง ลงท้าย ครับ "
                         "ถ้ามองไม่ชัด/ไม่เห็นสิ่งที่ถาม บอกตรงๆ และแนะนำให้ยกขึ้นใกล้กล้อง", [path])
    except Exception as e:  # noqa: BLE001
        return f"📷 ถ่ายแล้ว แต่ให้ AI ดูไม่ได้ ({str(e)[:120]})"
    if ans is None:
        return "📷 ต้องเปิด Gemini หรือ Claude (หรือ Ollama รุ่นดูรูปได้) ก่อน ถึงจะดูได้ว่าถืออะไร"
    import polite
    return "👀 " + polite.fix(ans.strip())


_HOLD = re.compile(r"(ถือ|จับ|ชู|หยิบ)\s*(อะไร|อันไหน)|ในมือ.*(อะไร)|"
                   r"(ฉัน|ผม|เรา)\s*(กำลัง)?\s*ทำอะไรอยู่|ใส่เสื้อ(สี)?อะไร|หน้าตา.*เป็นยังไง|"
                   r"(ช่วย)?(ดู|มอง|สแกน).*(กล้อง)")


_ENROLL = re.compile(r"^(?:ช่วย)?\s*(?:จำ|สอนจำ|บันทึก)\s*หน้า\s*(?:ฉัน|ผม|เรา|ของฉัน|ของผม)?\s*(?:ด้วย|หน่อย|ที)?\s*(?:ชื่อ\s*(?P<n>\S+))?\s*$")
_WHO = re.compile(r"(ใคร(?:อยู่)?(?:หน้า)?กล้อง|ใครอยู่ตรงนี้|จำ(?:ฉัน|ผม)ได้ไหม|รู้ไหม(?:ว่า)?(?:ฉัน|ผม)?(?:คือ|เป็น)?ใคร|เห็นหน้า(?:ฉัน|ผม)ไหม)")
_LOOK = re.compile(r"^(?:ช่วย)?\s*(?:มอง(?:ดู)?|ดู(?:ซิ|สิ)?|ส่อง)\s*(?:ด้วยกล้อง|กล้อง)?\s*(?:หน่อย|ที|ให้หน่อย)?\s*(?:ว่า)?\s*(?:เห็นอะไร(?:บ้าง)?)?\s*$|"
                   r"^(?:เห็นอะไร(?:บ้าง)?|ตรงหน้ามีอะไร|ถ่ายรูปแล้วบอกว่าเห็นอะไร)")


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    if not t or len(t) > 60:
        return None
    if os.environ.get("FACE_ENABLED", "1").strip().lower() in ("0", "false", "off", "no"):
        if _ENROLL.match(t) or _WHO.search(t) or _LOOK.match(t):
            return "📷 ระบบกล้องปิดอยู่ — เปิดได้ที่ ⚙️ ตั้งค่า → กล้อง/จำหน้า"
        return None
    m = _ENROLL.match(t)
    if m:
        return enroll_owner(ctx, m.group("n") or "")
    if _WHO.search(t):
        return who_is_there(ctx)
    if _LOOK.match(t):
        return look(ctx, "front" if "หน้า" in t else "back")
    if _HOLD.search(t):
        return look_ask(t, front="กล้องหลัง" not in t, ctx=ctx)
    return None
