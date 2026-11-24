"""สมองรู้จักแอป: รู้ว่าเครื่องมีแอปอะไร แต่ละแอปใช้ทำอะไร ใช้ยังไง เรียกชื่อว่าอะไรได้บ้าง
- ติดตั้งครั้งแรก → ทำรายชื่อแอปทั้งเครื่อง แล้วให้ AI อธิบายทุกแอป (ทำเบื้องหลังทีละชุด)
- เจอแอปใหม่ (ทุก 10 นาที) → ศึกษาเองอัตโนมัติ แล้วแจ้งว่าเรียนรู้แล้ว
- จำว่าเวลาผู้ใช้พูดชื่อกำกวม หมายถึงแอปไหน (app_index.resolve ถามครั้งเดียวแล้วจำ)
ข้อมูลอยู่ที่ data/app_brain.json (ในเครื่อง ไม่ส่งไปไหนนอกจากชื่อแอปตอนให้ AI อธิบาย)
"""
import json
import os
import re
import threading
import time

import config

_PATH = os.path.join(config.DATA_DIR, "app_brain.json")
_lock = threading.RLock()
_state = {"db": None, "running": False}

CAT_TH = {"game": "เกม", "audio": "เพลง/เสียง", "video": "วิดีโอ", "image": "รูปภาพ", "social": "โซเชียล",
          "news": "ข่าว", "maps": "แผนที่", "productivity": "งาน/เอกสาร"}


def load():
    with _lock:
        if _state["db"] is None:
            try:
                with open(_PATH, encoding="utf-8") as f:
                    _state["db"] = json.load(f)
            except (OSError, ValueError):
                _state["db"] = {"apps": {}, "choices": {}, "synced": 0}
        return _state["db"]


def save():
    with _lock:
        db = load()
        tmp = _PATH + ".tmp"
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False)
        os.replace(tmp, _PATH)


def apps():
    return load()["apps"]


def _n(s):
    return re.sub(r"[\s\-_.:()]+", "", (s or "").lower())


# ================================================================ รายชื่อแอป

def _meta(pkg):
    if not config.ANDROID_APP:
        return {}
    try:
        import android_shim
        return json.loads(str(android_shim.bridge().appMeta(pkg)))
    except Exception:  # noqa: BLE001
        return {}


def sync():
    """อัปเดตรายชื่อแอปจากเครื่อง → (แอปใหม่[], แอปที่ถูกลบ[])"""
    import app_index
    listed = app_index.build(force=True) or []
    if not listed:
        return [], []
    db = load()
    first = not db["apps"]
    now_pkgs = {a["pkg"] for a in listed}
    new = []
    with _lock:
        for a in listed:
            e = db["apps"].get(a["pkg"])
            if e is None:
                m = _meta(a["pkg"])
                db["apps"][a["pkg"]] = {"label": a["label"], "cat": m.get("category", ""), "sys": m.get("system", False),
                                        "ver": m.get("version", ""), "names": [], "what": "", "how": "", "studied": 0}
                if not first:
                    new.append(a["pkg"])
            elif e.get("label") != a["label"]:
                e["label"] = a["label"]
        gone = [p for p in db["apps"] if p not in now_pkgs]
        for p in gone:
            db["apps"].pop(p, None)
        db["synced"] = time.time()
    save()
    return new, gone


# ================================================================ ให้ AI อธิบายแอป

def _ask_ai(batch):
    import agent
    lines = "\n".join(f"- {p} | {apps()[p]['label']} | {CAT_TH.get(apps()[p].get('cat'), '')}" for p in batch)
    prompt = ("นี่คือแอปในอุปกรณ์ Android ของผู้ใช้คนไทย (package | ชื่อที่แสดง | หมวด)\n"
              f"{lines}\n\nตอบเป็น JSON array เท่านั้น แต่ละแอป: "
              '{"pkg": "...", "names": ["ชื่อที่คนไทยอาจเรียก 2-5 แบบ ทั้งไทย/อังกฤษ/คำย่อ"], '
              '"what": "ใช้ทำอะไร (ไทย ไม่เกิน 15 คำ)", '
              '"how": "วิธีใช้งานหลัก/ปุ่มสำคัญอยู่ตรงไหน (ไทย ไม่เกิน 45 คำ)", "sure": true/false}\n'
              "ถ้าไม่รู้จักแอปจริงๆ ให้เดาจากชื่อ/package และใส่ sure=false ห้ามแต่งรายละเอียดปุ่มที่ไม่แน่ใจ")
    resp, _who = agent.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}], [],
                                system="คุณคือผู้เชี่ยวชาญแอปมือถือ ตอบเป็น JSON ที่ถูกต้องเท่านั้น")
    text = agent._collect_text(resp.get("content", []))
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group(0)) if m else []


def study(pkgs=None, limit=None, batch=15):
    """ให้ AI อธิบายแอปที่ยังไม่รู้จัก → จำนวนแอปที่เรียนรู้แล้ว"""
    db = load()
    todo = [p for p in (pkgs or list(db["apps"])) if p in db["apps"] and not db["apps"][p].get("studied")]
    if limit:
        todo = todo[:limit]
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        try:
            res = _ask_ai(chunk)
        except Exception as e:  # noqa: BLE001
            print(f"[app_brain] ศึกษาแอปไม่สำเร็จ: {str(e)[:120]}", flush=True)
            break
        with _lock:
            for r in res if isinstance(res, list) else []:
                p = r.get("pkg")
                if p not in db["apps"]:
                    continue
                e = db["apps"][p]
                e["names"] = [str(x).strip() for x in (r.get("names") or []) if str(x).strip()][:6]
                e["what"] = str(r.get("what") or "")[:120]
                e["how"] = str(r.get("how") or "")[:300]
                e["sure"] = bool(r.get("sure", True))
                e["studied"] = time.time()
                done += 1
        save()
        time.sleep(2)
    return done


# ================================================================ ใช้ความรู้

def names_of(pkg):
    e = apps().get(pkg) or {}
    return [e.get("label", "")] + list(e.get("names") or [])


def remember_choice(said, pkg):
    with _lock:
        load()["choices"][_n(said)] = pkg
    save()


def choice_for(said):
    p = load()["choices"].get(_n(said))
    return p if p and (p in apps() or not apps()) else None


def describe(pkg):
    e = apps().get(pkg)
    if not e:
        return None
    s = f"📱 **{e['label']}**"
    if e.get("what"):
        s += f" — {e['what']}"
    if e.get("how"):
        s += f"\nวิธีใช้: {e['how']}"
    if e.get("names"):
        s += f"\nเรียกได้ว่า: {', '.join(e['names'][:5])}"
    if e.get("explored"):
        s += "\n🔍 เคยเข้าไปสำรวจหน้าจอแล้ว"
    return s


def hints(text):
    """ความรู้ของแอปที่ถูกพูดถึงในคำสั่ง (ให้ AI ใช้ตอนต้องกดเองในแอป)"""
    t = _n(text)
    out = []
    for p, e in apps().items():
        if not (e.get("what") or e.get("how")):
            continue
        if any(len(_n(x)) >= 3 and _n(x) in t for x in names_of(p)):
            out.append(f"[รู้จักแอป {e['label']} ({p})] {e.get('what', '')} · วิธีใช้: {e.get('how', '')}")
            if len(out) >= 2:
                break
    return "\n".join(out)


def catalog_prompt(limit=1800):
    """รายชื่อแอปในเครื่องแบบย่อ (แนบในคำสั่งระบบของ AI)"""
    items = [f"{e['label']}" + (f"({e['what'][:25]})" if e.get("what") else "")
             for p, e in sorted(apps().items(), key=lambda x: x[1].get("label", "")) if not e.get("hidden")]
    if not items:
        return ""
    s = "แอปที่มีในเครื่องนี้: " + ", ".join(items)
    return "\n\n" + s[:limit] + "\n"


# ================================================================ ทำงานเบื้องหลัง

def _loop(notify):
    time.sleep(60)                                    # ให้บอทพร้อมก่อน
    while True:
        try:
            import perf
            if not config.paused() and perf.idle(180):      # ผู้ใช้กำลังสั่งงาน → รอก่อน ไม่แย่ง AI/เน็ต
                new, gone = sync()
                first_pending = [p for p, e in apps().items() if not e.get("studied")]
                if new:
                    study(new)
                    for p in new:
                        e = apps().get(p) or {}
                        msg = f"📲 เจอแอปใหม่: {e.get('label', p)}"
                        msg += f" — {e['what']}" if e.get("what") else ""
                        msg += "\nเรียนรู้เบื้องต้นแล้ว · อยากให้เข้าไปสำรวจทุกหน้า สั่ง \"ศึกษาแอป " + e.get("label", p) + "\""
                        notify(msg)
                elif first_pending:
                    n = study(first_pending, limit=30)         # ครั้งแรก: ค่อยๆ ศึกษาทั้งเครื่อง
                    if n and not [p for p, e in apps().items() if not e.get("studied")]:
                        notify(f"🧠 รู้จักแอปทั้งเครื่องแล้ว ({len(apps())} แอป) — ถามได้ว่า \"มีแอปอะไรบ้าง\" หรือ \"แอป X ใช้ทำอะไร\"")
                if gone:
                    print(f"[app_brain] แอปถูกลบ: {gone}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[app_brain] {e}", flush=True)
        time.sleep(600 if not [p for p, e in apps().items() if not e.get("studied")] else 120)


def start(notify):
    if _state["running"] or config.MOCK_PHONE or os.environ.get("APP_BRAIN", "1") == "0":
        return
    _state["running"] = True
    threading.Thread(target=_loop, args=(notify,), daemon=True).start()


# ================================================================ คำสั่ง

_LIST = re.compile(r"(มี|ในเครื่อง(?:มี)?|ลง(?:ไว้)?)\s*แอ[ปพ]\s*(อะไร|ไหน)บ้าง|แอ[ปพ]ทั้งหมด(ในเครื่อง)?|รายชื่อแอ[ปพ]")
_WHAT = re.compile(r"^(?:แอ[ปพ])?\s*(?P<n>.+?)\s*(?:คือ(?:แอ[ปพ])?อะไร|ใช้ทำอะไร|เอาไว้ทำอะไร|ใช้ยังไง|ใช้งานยังไง)$|"
                   r"^วิธีใช้(?:งาน)?\s*(?:แอ[ปพ])?\s*(?P<n2>.+)$")
_RESTUDY = re.compile(r"^(?:ช่วย)?\s*(ศึกษา|เรียนรู้|อัปเดต|รีเฟรช)\s*(รายชื่อ)?\s*แอ[ปพ]\s*(ใหม่|ในเครื่อง)\s*(อีกรอบ)?$|"
                      r"^(?:อัปเดต|รีเฟรช)\s*รายชื่อแอ[ปพ]$")


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip(" ?")
    if not t or len(t) > 80:
        return None
    if _LIST.search(t):
        if not apps():
            sync()
        groups = {}
        for p, e in apps().items():
            groups.setdefault(CAT_TH.get(e.get("cat"), "อื่นๆ"), []).append(e["label"])
        lines = [f"• {g}: {', '.join(sorted(v))}" for g, v in sorted(groups.items(), key=lambda x: x[0] == "อื่นๆ")]
        studied = sum(1 for e in apps().values() if e.get("studied"))
        return f"📱 มีแอป {len(apps())} แอป (รู้จักวิธีใช้แล้ว {studied})\n" + "\n".join(lines)
    m = _WHAT.match(t)
    if m:
        import app_index
        name = (m.group("n") or m.group("n2") or "").strip()
        cands = app_index.candidates(name)
        pkg = cands[0][1] if cands and cands[0][0] >= 70 else None
        if pkg and pkg in apps():
            if not apps()[pkg].get("studied"):
                study([pkg])
            return describe(pkg)
        return None
    if _RESTUDY.search(t) and "ทุกหน้า" not in t:
        new, _ = sync()
        if "อีกรอบ" in t:
            with _lock:
                for e in apps().values():
                    e["studied"] = 0
            save()
        n = study()
        return f"🧠 อัปเดตรายชื่อแอปแล้ว ({len(apps())} แอป, ศึกษาเพิ่ม {n} แอป)"
    return None
