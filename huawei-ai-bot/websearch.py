"""ค้นเว็บสำหรับสมองที่ไม่มีค้นเว็บในตัว (Ollama / Groq)

ลำดับ: Gemini + Google Search (ถ้ามีคีย์) → ถ้าโควตาหมด/ล้ม ใช้ DuckDuckGo ฟรีแทน
ถ้า Gemini ล้ม จะพักไม่เรียก 1 ชม. เพื่อไม่เสียเวลารอทุกครั้ง
"""
import html
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests

import config

_gemini_off_until = [0.0]
_UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"}


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _real_url(href):
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    return unquote(q["uddg"][0]) if "uddg" in q else href


def duckduckgo(query, n=5):
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "th-th"},
                      headers=_UA, timeout=15)
    r.raise_for_status()
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    out = []
    for i, (href, title) in enumerate(links[:n]):
        snip = _clean(snips[i]) if i < len(snips) else ""
        out.append(f"- {_clean(title)}: {snip}\n  {_real_url(href)}")
    if not out:
        return "ไม่พบผลการค้นหา"
    return "ผลค้นหา (DuckDuckGo) — สรุปให้ผู้ใช้เป็นภาษาไทย:\n" + "\n".join(out)


def search(query):
    """ค้นเว็บ: Gemini+Google → DuckDuckGo → DuckDuckGo lite → ข่าว Google News → Wikipedia (ตัวไหนได้ก่อนใช้ตัวนั้น)"""
    errs = []
    if config.GEMINI_API_KEY and time.time() >= _gemini_off_until[0]:
        try:
            import gemini_client
            return gemini_client.web_search(query)
        except Exception as e:  # noqa: BLE001
            _gemini_off_until[0] = time.time() + 3600
            print(time.strftime("[%H:%M:%S]"), f"ค้นผ่าน Gemini ไม่ได้ → ใช้แหล่งฟรี 1 ชม. ({str(e)[:80]})",
                  flush=True)
    import info
    try:
        r = duckduckgo(query)
        if r and "ไม่พบผลการค้นหา" not in r:
            return r
    except Exception as e:  # noqa: BLE001
        errs.append(f"ddg: {e}")
    try:
        r = info.ddg_lite(query)
        if r:
            return "ผลค้นหา (DuckDuckGo) — สรุปให้ผู้ใช้เป็นภาษาไทย:\n" + r
    except Exception as e:  # noqa: BLE001
        errs.append(f"ddg-lite: {e}")
    parts = []
    try:
        n = info.news(query, n=5)
        if not n.startswith("ไม่เจอข่าว"):
            parts.append(n)
    except Exception as e:  # noqa: BLE001
        errs.append(f"news: {e}")
    try:
        w = info.wikipedia(query)
        if w:
            parts.append(w)
    except Exception as e:  # noqa: BLE001
        errs.append(f"wiki: {e}")
    if parts:
        return "ข้อมูลที่ค้นได้ — สรุปให้ผู้ใช้เป็นภาษาไทย:\n" + "\n\n".join(parts)
    print(time.strftime("[%H:%M:%S]"), "ค้นเว็บไม่สำเร็จทุกแหล่ง:", "; ".join(errs)[:300], flush=True)
    return "ไม่พบผลการค้นหา (เช็คอินเทอร์เน็ตของเครื่อง)"
