"""จับเวลาแต่ละขั้น + เก็บสถิติการใช้งาน (ใช้หาว่าช้าตรงไหน และสรุปผลทำวิจัย)

บันทึกลง data/perf.jsonl ทีละบรรทัด:
{"t": เวลา, "kind": "voice|quick|chat", "text": คำสั่ง, "stt": วิ, "first_token": วิ, "first_sound": วิ,
 "total": วิ, "engine": ตัวถอดเสียง, "ok": สำเร็จไหม}
"""
import json
import os
import statistics
import threading
import time

import config

_lock = threading.Lock()
_FAIL = ("ERROR", "ทำไม่สำเร็จ", "ไม่สำเร็จ", "ใช้ไม่ได้", "ผิดพลาด", "ขอโทษครับ คำสั่งนี้มีปัญหา", "❗")
GOAL = {"quick": 2.0, "first_sound": 4.0}          # เป้าความเร็ว (วินาที)


def _path(name="perf.jsonl"):
    return os.path.join(config.DATA_DIR, name)


def looks_ok(reply):
    r = (reply or "")[:200]
    return bool(r) and not any(k in r for k in _FAIL)


LAST = [0.0]           # เวลาที่ผู้ใช้สั่งงานล่าสุด
_TOOLS = []            # (เวลา, ชื่อเครื่องมือ, สำเร็จไหม) ของคำสั่งที่กำลังทำ


_IGNORED = [0.0]


def mark_ignored():
    """คำสั่งนี้ไม่ได้พูดกับผู้ช่วย (คุยกับคนอื่น/ทีวี) → ไม่นับเป็นคำสั่งพลาด"""
    _IGNORED[0] = time.time()


def tool(name, ok):
    """เรียกทุกครั้งที่ใช้เครื่องมือ — แนบไปกับบันทึกของคำสั่งนั้น (ดูว่าพลาดที่ขั้นไหน)"""
    with _lock:
        _TOOLS.append((time.time(), name, bool(ok)))
        del _TOOLS[:-40]


def touch():
    LAST[0] = time.time()


def idle(sec=180):
    """ผู้ใช้ไม่ได้สั่งงานมาแล้วกี่วินาที (ให้งานเบื้องหลังรอจนว่าง จะได้ไม่แย่งความเร็ว)"""
    return time.time() - LAST[0] >= sec


def record(kind, text="", **stages):
    touch()
    row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "text": (text or "")[:80]}
    since = time.time() - float(stages.get("total") or 0) - 1
    with _lock:
        used = [(n, ok) for (t, n, ok) in _TOOLS if t >= since]
    if used:
        row["tools"] = [n if ok else n + "✗" for n, ok in used][:15]
    if _IGNORED[0] >= since:
        row["ignored"] = True
        row.pop("ok", None)
    for k, v in stages.items():
        row[k] = round(v, 2) if isinstance(v, float) else v
    try:
        with _lock:
            with open(_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if os.path.getsize(_path()) > 600_000:            # เก็บแค่ ~3,000 รายการล่าสุด
                with open(_path(), encoding="utf-8") as f:
                    lines = f.read().splitlines()[-3000:]
                with open(_path(), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    parts = [f"{k} {v:.1f}s" for k, v in stages.items() if isinstance(v, (int, float)) and k != "ok"]
    print(time.strftime("[%H:%M:%S]"), f"⏱️ {kind}: " + " · ".join(parts), flush=True)


def rows(name="perf.jsonl", days=7):
    out = []
    cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    try:
        with open(_path(name), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("t", "") >= cut:
                    out.append(r)
    except OSError:
        pass
    return out


def _stat(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return {"n": len(vals), "median": statistics.median(vals), "avg": sum(vals) / len(vals),
            "p90": sorted(vals)[max(0, int(len(vals) * 0.9) - 1)]}


def _fmt(s):
    return "-" if not s else f"กลาง {s['median']:.1f} วิ · เฉลี่ย {s['avg']:.1f} · ช้าสุด 10% {s['p90']:.1f} (n={s['n']})"


def summary(days=7):
    """สรุปผลทดสอบ/ใช้งาน → ข้อความ + ไฟล์ CSV (สำหรับใส่รายงานวิจัย)"""
    rs = rows(days=days)
    lines = [f"📊 สรุปผล {days} วันล่าสุด"]
    # 1) ความเร็ว
    quick = [r for r in rs if r.get("kind") == "quick"]
    ai = [r for r in rs if r.get("kind") in ("voice", "chat")]
    sq, sf, st = _stat([r.get("total") for r in quick]), _stat([r.get("first_sound") for r in ai]), \
        _stat([r.get("total") for r in ai])
    lines.append("\n⏱️ ความเร็ว")
    lines.append(f"• คำสั่งด่วน: {_fmt(sq)} (เป้า ≤ {GOAL['quick']:.0f} วิ)")
    lines.append(f"• คำสั่งที่ใช้ AI — เริ่มพูด: {_fmt(sf)} (เป้า ≤ {GOAL['first_sound']:.0f} วิ)")
    lines.append(f"• คำสั่งที่ใช้ AI — จบทั้งหมด: {_fmt(st)}")
    stt = _stat([r.get("stt") for r in rs if r.get("stt")])
    if stt:
        lines.append(f"• ถอดเสียง: {_fmt(stt)}")
    # 2) ความสำเร็จ
    done = [r for r in rs if "ok" in r and not r.get("ignored")]
    if done:
        ok = sum(1 for r in done if r["ok"])
        lines.append(f"\n✅ คำสั่งสำเร็จ (ไม่มี error): {ok}/{len(done)} = {ok * 100 / len(done):.0f}%")
    # 2.1) จุดที่พลาดบ่อย (ไว้แก้ก่อน)
    bad = {}
    for r in rs:
        for n in r.get("tools") or []:
            if n.endswith("✗"):
                bad[n[:-1]] = bad.get(n[:-1], 0) + 1
    if bad:
        lines.append("\n🔧 เครื่องมือที่พลาดบ่อย")
        lines += [f"• {k}: {v} ครั้ง" for k, v in sorted(bad.items(), key=lambda x: -x[1])[:5]]
    failed = [r for r in done if not r["ok"]][-5:] if done else []
    if failed:
        lines.append("\n❌ คำสั่งที่พลาดล่าสุด")
        lines += [f"• {r['t'][5:16]} {r.get('text', '')[:90]}" for r in failed]
    # 3) ไมค์
    mic = rows("mic.jsonl", days)
    if mic:
        kept = sum(1 for r in mic if r.get("kept"))
        by = {}
        for r in mic:
            k = (r.get("why") or "ใช้ได้").split("(")[0].strip()       # รวมสาเหตุเดียวกันไว้บรรทัดเดียว
            by[k] = by.get(k, 0) + 1
        lines.append(f"\n🎤 การฟัง: ใช้ได้ {kept}/{len(mic)} ครั้ง ({kept * 100 / len(mic):.0f}%)")
        for k, v in sorted(by.items(), key=lambda x: -x[1])[:4]:
            lines.append(f"• {k}: {v}")
    # 4) ทดสอบแอป
    try:
        with open(_path("app_test.json"), encoding="utf-8") as f:
            at = json.load(f)
        ok = sum(1 for r in at["rows"] if r["ok"])
        lines.append(f"\n🧪 ทดสอบแอป ({at['at']}): ผ่าน {ok}/{len(at['rows'])}")
        lines += [f"{'✅' if r['ok'] else '❌'} {r['app']}" for r in at["rows"]]
    except (OSError, ValueError, KeyError):
        lines.append("\n🧪 ยังไม่เคยทดสอบแอป — สั่ง \"ทดสอบแอปทั้งหมด\"")
    if not rs and not mic:
        lines.append("\n(ยังไม่มีข้อมูล — ใช้งานสักพักแล้วสั่งใหม่)")
    path = export_csv(rs)
    if path:
        lines.append(f"\n📁 ข้อมูลดิบ: {path}")
    return "\n".join(lines)


def export_csv(rs):
    if not rs:
        return None
    import csv
    try:
        import media
        d = media._out_dir("doc")
    except Exception:  # noqa: BLE001
        d = config.DATA_DIR
    p = os.path.join(d, f"ผลทดสอบผู้ช่วย-{time.strftime('%Y%m%d')}.csv")
    cols = ["t", "kind", "text", "engine", "stt", "first_token", "first_sound", "total", "ok"]
    try:
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rs:
                w.writerow(r)
        return p.replace(os.environ.get("SHARED_STORAGE", "/storage/emulated/0") + "/", "")
    except OSError:
        return None


def handle_text(text, ctx=None):
    import re
    if re.match(r"^(สรุป|ดู)\s*(ผล)?\s*(ทดสอบ|การทดสอบ|การใช้งาน|สถิติ|ความเร็ว)", (text or "").strip()):
        return summary()
    return None
