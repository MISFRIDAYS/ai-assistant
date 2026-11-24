"""ค้นหาและอ่านไฟล์ในเครื่อง ให้ AI วิเคราะห์/สรุป

รองรับ: txt md csv json log html · pdf (pdftotext/pypdf) · docx xlsx pptx (อ่านเองไม่ต้องลงอะไรเพิ่ม) · รูปภาพ (ให้ AI ดู)
ค้นใน ~/storage/shared (Download, Documents, Pictures ...) และไฟล์ที่ส่งมาทาง Telegram
"""
import html
import os
import re
import shutil
import subprocess
import time
import zipfile

import config

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".html", ".htm", ".xml", ".py", ".js", ".ini",
            ".yaml", ".yml", ".srt", ".env.example"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".pptx"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
SUPPORTED = TEXT_EXT | DOC_EXT | IMG_EXT
_SKIP_DIRS = {"Android", ".thumbnails", ".trash", ".Trash", "cache", ".cache", "node_modules", ".git"}


def roots():
    home = os.path.expanduser("~")
    out = [os.path.join(config.DATA_DIR, "inbox")]
    for p in (f"{home}/storage/shared", "/sdcard", "/storage/emulated/0", home):
        if os.path.isdir(p) and all(not os.path.samefile(p, r) for r in out if os.path.isdir(r)):
            out.append(p)
    return [r for r in out if os.path.isdir(r)]


def _walk(root, max_depth=5):
    base = root.rstrip("/").count("/")
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP_DIRS and not d.startswith(".")]
        if dp.count("/") - base >= max_depth:
            dns[:] = []
        for f in fns:
            yield os.path.join(dp, f)


def find(query="", limit=15):
    q = (query or "").lower().strip()
    words = [w for w in re.split(r"\s+", q) if w]
    hits, seen = [], set()
    t0 = time.time()
    for r in roots():
        for p in _walk(r):
            if time.time() - t0 > 20:
                break
            ext = os.path.splitext(p)[1].lower()
            name = os.path.basename(p).lower()
            if ext not in SUPPORTED or (words and not all(w in name for w in words)):
                continue
            try:
                st = os.stat(p)
                key = (st.st_size, int(st.st_mtime), name)
            except OSError:
                continue
            if key in seen:                       # /sdcard กับ storage/shared เป็นที่เดียวกัน
                continue
            seen.add(key)
            hits.append((st.st_mtime, st.st_size, p))
    hits.sort(reverse=True)
    return hits[:limit]


def _size(n):
    return f"{n / 1e6:.1f}MB" if n > 1e6 else f"{n / 1e3:.0f}KB"


def tool_find(a, ctx):
    hits = find(a.get("query", ""))
    if not hits:
        return (f"ไม่พบไฟล์ที่ชื่อมี '{a.get('query', '')}' (ค้นใน Download, Documents ฯลฯ) — "
                "ลองคำค้นสั้นลง หรือส่งไฟล์มาในแชท Telegram ได้เลย")
    lines = [f"- {time.strftime('%d/%m %H:%M', time.localtime(m))} {_size(s)} {p}" for m, s, p in hits]
    return "ไฟล์ที่เจอ (ใหม่สุดก่อน):\n" + "\n".join(lines)


# ---------------------------------------------------------------- แปลงไฟล์เป็นข้อความ

def _xml_text(xml):
    xml = re.sub(r"</w:p>|</a:p>|<w:br/>|<w:tab/>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _docx(p):
    with zipfile.ZipFile(p) as z:
        return _xml_text(z.read("word/document.xml").decode("utf-8", "ignore"))


def _pptx(p):
    with zipfile.ZipFile(p) as z:
        names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n\n".join(f"--- สไลด์ {i + 1} ---\n" + _xml_text(z.read(n).decode("utf-8", "ignore")).strip()
                           for i, n in enumerate(names))


def _xlsx(p, max_rows=200):
    with zipfile.ZipFile(p) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            x = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", si)) for si in re.findall(r"<si>(.*?)</si>", x, re.S)]
        wb = z.read("xl/workbook.xml").decode("utf-8", "ignore")
        sheet_names = re.findall(r'<sheet [^>]*name="([^"]+)"', wb)
        files = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for i, n in enumerate(files):
            x = z.read(n).decode("utf-8", "ignore")
            rows = re.findall(r"<row[^>]*>(.*?)</row>", x, re.S)
            out.append(f"=== ชีต {sheet_names[i] if i < len(sheet_names) else i + 1} ({len(rows)} แถว) ===")
            for r in rows[:max_rows]:
                vals = []
                for attrs, inner in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
                    v = re.search(r"<v>(.*?)</v>", inner, re.S)
                    t = re.search(r"<t[^>]*>(.*?)</t>", inner, re.S)
                    if 't="s"' in attrs and v:
                        k = int(v.group(1))
                        vals.append(shared[k] if k < len(shared) else "")
                    elif v:
                        vals.append(html.unescape(v.group(1)))
                    elif t:
                        vals.append(html.unescape(t.group(1)))
                    else:
                        vals.append("")
                out.append(" | ".join(vals))
            if len(rows) > max_rows:
                out.append(f"... (อีก {len(rows) - max_rows} แถว)")
        return "\n".join(out)


def _pdf(p):
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "ignore")
    try:
        from pypdf import PdfReader
        return "\n\n".join(f"--- หน้า {i + 1} ---\n{pg.extract_text() or ''}"
                           for i, pg in enumerate(PdfReader(p).pages))
    except ImportError:
        raise RuntimeError("อ่าน PDF ต้องติดตั้งก่อน: pkg install poppler (ใน Termux)")


def extract(path):
    """คืน (ข้อความ, None) หรือ (None, path รูป) สำหรับรูปภาพ"""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMG_EXT:
        return None, path
    if ext == ".pdf":
        return _pdf(path), None
    if ext == ".docx":
        return _docx(path), None
    if ext == ".xlsx":
        return _xlsx(path), None
    if ext == ".pptx":
        return _pptx(path), None
    with open(path, "rb") as f:
        raw = f.read(4_000_000)
    for enc in ("utf-8", "utf-16", "cp874"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "ignore")
    if ext in (".html", ".htm"):
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", text)))
    return text, None


def _resolve(path):
    path = os.path.expanduser((path or "").strip())
    if os.path.isfile(path):
        return path
    hits = find(os.path.basename(path), limit=1)
    return hits[0][2] if hits else None


def _private(p):
    """กันอ่านไฟล์ลับ: .env (มีคีย์ API) โฟลเดอร์ซ่อน (.ssh ฯลฯ) และข้อมูลภายในของบอท"""
    real = os.path.realpath(p)
    parts = real.split(os.sep)
    data = os.path.realpath(config.DATA_DIR)
    inbox = os.path.join(data, "inbox")
    if real.startswith(data) and not real.startswith(inbox):
        return True
    return any(x.startswith(".") for x in parts[1:]) or os.path.basename(real).lower().startswith(".env")


def tool_read(a, ctx):
    p = _resolve(a.get("path", ""))
    if not p:
        return f"ERROR: ไม่พบไฟล์ '{a.get('path')}' — ใช้ find_files ค้นหาก่อน"
    if _private(p):
        return "ERROR: ไฟล์นี้เป็นไฟล์ระบบ/ข้อมูลลับ (เช่น คีย์ API) อ่านไม่ได้"
    try:
        text, img = extract(p)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: อ่านไฟล์ไม่ได้ ({e})"
    if img:
        try:
            import screen_tools
            img = screen_tools._shrink(img)
        except Exception:  # noqa: BLE001
            pass
        return {"text": f"รูปภาพ: {p}", "image_path": img, "send_to_user": False}
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return f"ไฟล์ {os.path.basename(p)} ไม่มีข้อความที่อ่านได้ (อาจเป็น PDF แบบภาพสแกน)"
    start = max(0, int(a.get("start", 0)))
    n = config.FILE_READ_CHARS
    part = text[start:start + n]
    more = (f"\n\n...(ยังมีอีก {len(text) - start - n:,} ตัวอักษร — อ่านต่อด้วย start={start + n})"
            if start + n < len(text) else "")
    return f"ไฟล์ {p} (ทั้งหมด {len(text):,} ตัวอักษร)\n\n{part}{more}"


def from_telegram(data, filename):
    """เก็บไฟล์ที่ผู้ใช้ส่งมาทาง Telegram แล้วคืน content blocks ให้ AI"""
    inbox = os.path.join(config.DATA_DIR, "inbox")
    os.makedirs(inbox, exist_ok=True)
    safe = re.sub(r"[^\w.\-ก-๙ ]", "_", filename or "file")[:80]
    p = os.path.join(inbox, safe)
    with open(p, "wb") as f:
        f.write(data)
    res = tool_read({"path": p}, None)
    if isinstance(res, dict):
        import base64
        with open(res["image_path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": f"[ผู้ใช้ส่งรูป {safe} มา บันทึกไว้ที่ {p}]"}]
    return [{"type": "text", "text": f"[ผู้ใช้ส่งไฟล์ {safe} มา (บันทึกไว้ที่ {p} ส่งต่อเข้าแอปได้ด้วย send_to_app) เนื้อหาในไฟล์:]\n{res}"}]


def _obj(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "find_files": (tool_find, "ค้นหาไฟล์ในเครื่องจากชื่อ (Download, Documents, รูป ฯลฯ) — query ว่าง = ไฟล์ล่าสุด",
                   _obj({"query": {"type": "string"}}), False),
    "read_file": (tool_read, "อ่านไฟล์ในเครื่องเพื่อวิเคราะห์/สรุป (txt pdf docx xlsx pptx csv json รูปภาพ) "
                             "ใส่ path เต็มจาก find_files หรือชื่อไฟล์ — ไฟล์ยาวอ่านต่อด้วย start",
                  _obj({"path": {"type": "string"}, "start": {"type": "integer"}}, ["path"]), False),
}
