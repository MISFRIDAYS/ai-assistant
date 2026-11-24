"""รายชื่อแอปทั้งหมดในเครื่อง + ชื่อที่แสดงจริง (เช่น "เครื่องคิดเลข", "CapCut")
ให้สั่ง เปิด/ปิด แอปไหนก็ได้ด้วยชื่อที่เห็นบนหน้าจอ

ชื่อแอปอ่านด้วย aapt (pkg install aapt) ครั้งแรกใช้เวลาสักครู่ แล้วจำไว้ในไฟล์
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time

import config

_PATH = os.path.join(config.DATA_DIR, "apps.json")
_lock = threading.Lock()
_cache = {"apps": None, "t": 0.0, "building": False}


def _sh(args, timeout=30):
    import phone_tools
    return phone_tools._sh(args, timeout=timeout)


def _label(apk):
    if not shutil.which("aapt") or not apk:
        return ""
    try:
        out = subprocess.run(["aapt", "dump", "badging", apk], capture_output=True, text=True,
                             timeout=15).stdout
    except Exception:  # noqa: BLE001
        return ""
    m = re.search(r"application-label-th:'([^']+)'", out) or re.search(r"application-label:'([^']+)'", out)
    return m.group(1) if m else ""


def build(force=False):
    """สร้างรายชื่อแอป (package, ชื่อแสดง) — แอปที่มีไอคอนบนหน้าจอหลักเท่านั้น"""
    import phone_tools
    with _lock:
        if _cache["building"]:
            return _cache["apps"] or []
        _cache["building"] = True
    try:
        if config.ANDROID_APP:                      # แอป APK: ได้ชื่อที่แสดงจากระบบตรงๆ
            import android_shim
            seen, apps = set(), []
            for line in str(android_shim.bridge().launcherApps()).splitlines():
                parts = line.split("|")
                if len(parts) == 3 and parts[1] not in seen:
                    seen.add(parts[1])
                    apps.append({"pkg": parts[1], "label": parts[0].strip()})
            with open(_PATH, "w", encoding="utf-8") as f:
                json.dump(apps, f, ensure_ascii=False)
            _cache.update(apps=apps, t=time.time())
            return apps
        old = {a["pkg"]: a for a in (load() or [])} if not force else {}
        comps = phone_tools._launcher_components()
        pkgs = sorted({c.split("/")[0] for c in comps})
        paths = {}
        for line in _sh(["pm", "list", "packages", "-f"], timeout=40).splitlines():
            m = re.match(r"package:(.+\.apk)=(.+)$", line.strip())
            if m:
                paths[m.group(2)] = m.group(1)
        apps = []
        for p in pkgs:
            if p in old and old[p].get("label"):
                apps.append(old[p])
                continue
            apps.append({"pkg": p, "label": _label(paths.get(p, ""))})
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False)
        _cache.update(apps=apps, t=time.time())
        return apps
    finally:
        _cache["building"] = False


def load():
    if _cache["apps"] is not None:
        return _cache["apps"]
    try:
        with open(_PATH, encoding="utf-8") as f:
            _cache["apps"] = json.load(f)
            _cache["t"] = os.path.getmtime(_PATH)
    except (FileNotFoundError, json.JSONDecodeError):
        _cache["apps"] = None
    return _cache["apps"]


def ensure_background():
    """สร้าง/อัปเดตรายชื่อในเบื้องหลัง (ไม่ทำให้คำสั่งช้า)"""
    if config.MOCK_PHONE:
        return
    stale = load() is None or time.time() - _cache["t"] > 6 * 3600
    if stale and not _cache["building"]:
        threading.Thread(target=build, daemon=True).start()


def _n(s):
    return re.sub(r"[\s\-_.:]+", "", (s or "").lower())


def _apps_now():
    apps = load()
    if apps is None:
        import phone_tools
        ensure_background()
        apps = [{"pkg": c.split("/")[0], "label": ""} for c in phone_tools._launcher_components()]
    return apps


def candidates(name):
    """ให้คะแนนทุกแอปว่าตรงกับชื่อที่ผู้ใช้พูดแค่ไหน → [(คะแนน, pkg, ชื่อแสดง)] มากไปน้อย
    100 ชื่อตรงเป๊ะ · 95 ชื่อเรียกที่เรียนรู้ไว้ · 85 ขึ้นต้นด้วย · 75 มีคำนี้ · 70 ท้าย package · ≤65 คล้าย"""
    import phone_tools
    raw = (name or "").strip()
    key = phone_tools.ALIASES.get(raw.lower(), raw)
    q = _n(key)
    q0 = _n(raw)
    if not q:
        return []
    try:
        import app_brain
        brain = app_brain.apps()
    except Exception:  # noqa: BLE001
        brain = {}
    out = []
    for a in _apps_now():
        pkg, lab = a["pkg"], a.get("label") or ""
        nl = _n(lab)
        names = [_n(x) for x in (brain.get(pkg) or {}).get("names", []) if x]
        tail = _n(pkg.split(".")[-1])
        sc = 0.0
        if nl and nl in (q, q0):
            sc = 100
        elif q in names or q0 in names:
            sc = 95
        elif nl and (nl.startswith(q) or q.startswith(nl)) and min(len(nl), len(q)) >= 3:
            sc = 85 - min(10, abs(len(nl) - len(q)))
        elif nl and len(q) >= 3 and q in nl:
            sc = 75 - min(10, len(nl) - len(q))
        elif any(len(q) >= 3 and (q in x or x in q) and len(x) >= 3 for x in names):
            sc = 72
        elif q == tail or (len(q) >= 4 and q in _n(pkg)):
            sc = 70 if q == tail else 55
        else:
            best = max([difflib.SequenceMatcher(None, q, c).ratio() for c in [nl, tail] + names if c] or [0])
            sc = best * 65 if best >= 0.72 else 0
        if sc:
            out.append((round(sc, 1), pkg, lab or pkg))
    out.sort(key=lambda x: -x[0])
    return out


def ambiguous(cands):
    """ชื่อนี้ชี้ได้หลายแอปพอๆ กันไหม"""
    return len(cands) >= 2 and cands[0][0] < 100 and cands[1][0] >= 60 and cands[0][0] - cands[1][0] <= 6


def find(name):
    """หา package จากชื่อที่ผู้ใช้พูด/พิมพ์ คืน (pkg, ชื่อแสดง) หรือ (None, None)"""
    import phone_tools
    raw = name.strip()
    key = phone_tools.ALIASES.get(raw.lower(), raw)
    if "." in key and " " not in key:
        return key, key
    try:
        import app_brain
        ch = app_brain.choice_for(raw)
        if ch:
            return ch, label_of(ch)
    except Exception:  # noqa: BLE001
        pass
    if key.lower() in phone_tools.COMMON_APPS:
        pkg = phone_tools.COMMON_APPS[key.lower()]
        apps = load() or []
        if not apps or any(a["pkg"] == pkg for a in apps):
            return pkg, key
    c = candidates(raw)
    return (c[0][1], c[0][2]) if c else (None, None)


_TH_NUM = {"หนึ่ง": 1, "แรก": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5}


def resolve(name, ctx=None):
    """เหมือน find แต่ถ้ากำกวม (เช่น "แผนที่" มีทั้ง Petal Maps และ Google Maps) → ถามผู้ใช้ แล้วจำคำตอบไว้
    คืน (pkg, label) / (None, ข้อความบอกผู้ใช้)"""
    import phone_tools
    raw = name.strip()
    key = phone_tools.ALIASES.get(raw.lower(), raw)
    try:
        import app_brain
        ch = app_brain.choice_for(raw)
        if ch:
            return ch, label_of(ch)
    except Exception:  # noqa: BLE001
        app_brain = None
    if key.lower() in phone_tools.COMMON_APPS:
        pkg = phone_tools.COMMON_APPS[key.lower()]
        if not load() or any(a["pkg"] == pkg for a in load()):
            return pkg, key
    c = candidates(raw)
    if not c:
        return None, None
    if not ambiguous(c):
        return c[0][1], c[0][2]
    opts = [x for x in c if x[0] >= c[0][0] - 12][:5]
    if ctx is None or not hasattr(ctx, "ask"):
        return None, "มีหลายแอปที่ชื่อคล้าย '" + raw + "': " + ", ".join(o[2] for o in opts) + " — บอกชื่อให้ชัดขึ้นนะ"
    q = f"'{raw}' หมายถึงแอปไหน?\n" + "\n".join(f"{i + 1}. {o[2]}" for i, o in enumerate(opts)) + "\n(ตอบเป็นเลขหรือชื่อ)"
    ans = (ctx.ask(q) or "").strip()
    pick = None
    m = re.search(r"\d+", ans)
    if m and 1 <= int(m.group()) <= len(opts):
        pick = opts[int(m.group()) - 1]
    else:
        for w, i in _TH_NUM.items():
            if w in ans and i <= len(opts):
                pick = opts[i - 1]
        for o in opts:
            if ans and (_n(ans) in _n(o[2]) or _n(o[2]) in _n(ans)):
                pick = o
    if not pick:
        return None, "ยกเลิก — ไม่แน่ใจว่าแอปไหน"
    if app_brain:
        app_brain.remember_choice(raw, pick[1])        # ครั้งหน้าพูดชื่อนี้ = แอปนี้เลย ไม่ถามซ้ำ
    return pick[1], pick[2]


def foreground_pkg():
    out = _sh(["dumpsys", "window"], timeout=15)
    m = re.search(r"mCurrentFocus=.*?\s([\w.]+)/", out) or re.search(r"mFocusedApp=.*?\s([\w.]+)/", out)
    return m.group(1) if m else None


def label_of(pkg):
    for a in load() or []:
        if a["pkg"] == pkg and a.get("label"):
            return a["label"]
    return pkg
