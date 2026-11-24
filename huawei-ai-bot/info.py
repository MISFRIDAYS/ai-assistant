"""ข้อมูลทันใจจากแหล่งฟรี (ไม่ต้องมีคีย์ ไม่ต้องผ่าน AI) — ใช้ได้แม้สมองเป็น Ollama/Groq

- อากาศ: Open-Meteo (พยากรณ์ + ตอนนี้) · "อากาศวันนี้" "พรุ่งนี้ฝนตกไหม" "อากาศที่เชียงใหม่"
- ข่าว: Google News RSS (ไทย) · "ข่าววันนี้" "ข่าวล่าสุดเกี่ยวกับ ทองคำ"
- ค้นเว็บสำรอง: Wikipedia ไทย (เมื่อแหล่งอื่นใช้ไม่ได้)
"""
import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"}
_cache = {}

# รหัสสภาพอากาศ WMO → คำไทย
WMO = {0: "ท้องฟ้าแจ่มใส ☀️", 1: "แดดเป็นส่วนใหญ่ 🌤️", 2: "มีเมฆบางส่วน ⛅", 3: "เมฆมาก ☁️", 45: "มีหมอก 🌫️",
       48: "หมอกน้ำค้างแข็ง 🌫️", 51: "ฝนปรอยเล็กน้อย 🌦️", 53: "ฝนปรอย 🌦️", 55: "ฝนปรอยหนาแน่น 🌧️",
       61: "ฝนตกเล็กน้อย 🌧️", 63: "ฝนตกปานกลาง 🌧️", 65: "ฝนตกหนัก 🌧️", 66: "ฝนเยือกแข็ง", 67: "ฝนเยือกแข็งหนัก",
       71: "หิมะเล็กน้อย", 73: "หิมะ", 75: "หิมะหนัก", 80: "ฝนตกเป็นช่วงๆ 🌦️", 81: "ฝนตกเป็นช่วงๆ ค่อนข้างหนัก 🌧️",
       82: "ฝนตกหนักมาก ⛈️", 95: "พายุฝนฟ้าคะนอง ⛈️", 96: "พายุฝนฟ้าคะนอง มีลูกเห็บ ⛈️", 99: "พายุฝนฟ้าคะนองรุนแรง ⛈️"}


def _get(url, timeout=12):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r


# ================================================================ ตำแหน่ง

def _device_location():
    """พิกัดจากเครื่อง (ถ้าให้สิทธิ์ตำแหน่ง) → (lat, lon) / None"""
    try:
        import phone_tools
        raw = phone_tools.run(["termux-location", "-p", "network", "-r", "last"], timeout=20)
        d = json.loads(raw)
        if "latitude" in d:
            return float(d["latitude"]), float(d["longitude"])
    except Exception:  # noqa: BLE001
        pass
    return None


def geocode(name):
    """ชื่อเมือง/จังหวัด → (lat, lon, ชื่อที่แสดง) / None"""
    key = ("geo", name)
    if key in _cache:
        return _cache[key]
    url = ("https://geocoding-api.open-meteo.com/v1/search?count=1&language=th&format=json&name="
           + urllib.parse.quote(name))
    res = (_get(url).json().get("results") or [None])[0]
    out = (res["latitude"], res["longitude"], res.get("name") or name) if res else None
    _cache[key] = out
    return out


# ================================================================ อากาศ

def weather(place=None, day=0):
    """day: 0=วันนี้ 1=พรุ่งนี้ 2=มะรืน"""
    label = place
    if place:
        g = geocode(place)
        if not g:
            return f"หาตำแหน่ง \"{place}\" ไม่เจอ ลองพิมพ์ชื่อจังหวัด/เมืองอีกครั้ง"
        lat, lon, label = g
    else:
        loc = _device_location()
        if loc:
            lat, lon = loc
            label = "ตำแหน่งปัจจุบัน"
        else:
            lat, lon, label = 13.7563, 100.5018, "กรุงเทพฯ"
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone=auto&forecast_days=3"
           "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max")
    d = _get(url).json()
    dl = d.get("daily") or {}
    names = ["วันนี้", "พรุ่งนี้", "มะรืนนี้"]
    lines = []
    if day == 0 and d.get("current"):
        c = d["current"]
        lines.append(f"🌡️ ตอนนี้ที่{label}: {c['temperature_2m']:.0f}°C (รู้สึกเหมือน {c['apparent_temperature']:.0f}°C) "
                     f"{WMO.get(int(c['weather_code']), '')} · ความชื้น {c['relative_humidity_2m']}% · "
                     f"ลม {c['wind_speed_10m']:.0f} กม./ชม.")
    i = min(day, len(dl.get("time", [])) - 1)
    if i >= 0:
        rain = dl.get("precipitation_probability_max", [None] * 3)[i]
        uv = dl.get("uv_index_max", [None] * 3)[i]
        lines.append(f"📅 {names[i]}{'' if lines else 'ที่' + label}: {WMO.get(int(dl['weather_code'][i]), '')} "
                     f"{dl['temperature_2m_min'][i]:.0f}–{dl['temperature_2m_max'][i]:.0f}°C"
                     + (f" · โอกาสฝน {rain}%" if rain is not None else "")
                     + (f" · UV {uv:.0f}" if uv is not None else ""))
        if rain is not None and rain >= 60:
            lines.append("☔ พกร่มไปด้วยนะครับ")
        elif uv is not None and uv >= 8:
            lines.append("🧴 แดดแรง ทากันแดดด้วยนะครับ")
    return "\n".join(lines) or "ดึงข้อมูลอากาศไม่ได้"


# ================================================================ ข่าว

def news(query="", n=6):
    q = query.strip()
    url = ("https://news.google.com/rss/search?hl=th&gl=TH&ceid=TH:th&q=" + urllib.parse.quote(q) if q
           else "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th")
    root = ET.fromstring(_get(url).content)
    items = []
    for it in root.iter("item"):
        title = html.unescape(it.findtext("title") or "").strip()
        src = (it.find("source").text if it.find("source") is not None else "") or ""
        if title:
            items.append(f"• {title}" + ("" if src and src in title else (f" ({src})" if src else "")))
        if len(items) >= n:
            break
    if not items:
        return "ไม่เจอข่าว" + (f"เกี่ยวกับ {q}" if q else "")
    return (f"📰 ข่าวล่าสุด{' เรื่อง ' + q if q else ''}:\n" + "\n".join(items))


# ================================================================ ค้นเว็บสำรอง

def wikipedia(query, lang="th"):
    s = _get(f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=3&srsearch="
             + urllib.parse.quote(query)).json()
    hits = (s.get("query") or {}).get("search") or []
    if not hits:
        return ""
    title = hits[0]["title"]
    e = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))).json()
    return f"Wikipedia: {title}\n{e.get('extract', '')[:1500]}\nhttps://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}"


def ddg_lite(query, n=5):
    r = requests.post("https://lite.duckduckgo.com/lite/", data={"q": query, "kl": "th-th"}, headers=_UA, timeout=15)
    r.raise_for_status()
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>', r.text, re.S)
    snips = re.findall(r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>', r.text, re.S)
    out = []
    for i, (href, title) in enumerate(links[:n]):
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()  # noqa: E731
        out.append(f"- {clean(title)}: {clean(snips[i]) if i < len(snips) else ''}\n  {href}")
    return "\n".join(out)


# ================================================================ คำสั่งตรง

_TAIL = r"(?:\s*(?:เป็น(?:ยัง|อย่าง)ไง(?:บ้าง)?|เป็นไง(?:บ้าง)?|ยังไง|ไหม|มั้ย|หรือเปล่า|บ้าง|ให้หน่อย|หน่อย|ที|ครับ|ค่ะ|คะ|นะ))*\s*[?？]*$"
_WEATHER = re.compile(r"^(?:ขอ|ดู|เช็ค|เช็ก|บอก)?\s*(?:สภาพ)?(?:อากาศ|พยากรณ์อากาศ|อุณหภูมิ|ฝน(?:จะ)?ตก|ร้อน|หนาว)"
                      r"(?P<rest>.*)$")
_PLACE = re.compile(r"(?:ที่|แถว|จังหวัด|จ\.|เมือง|ใน)\s*(?P<p>[ก-๙A-Za-z][ก-๙A-Za-z .-]{1,30})")
_NEWS = re.compile(r"^(?:ขอ|ดู|อ่าน|สรุป|มี)?\s*ข่าว(?:อะไร)?(?:วันนี้|ล่าสุด|ด่วน|เด่น)?\s*(?:บ้าง)?"
                   r"\s*(?:เกี่ยวกับ|เรื่อง)?\s*(?P<q>.*?)" + _TAIL)


def handle_text(text, ctx=None):
    t = " ".join(re.sub(r"\[[^\]]*\]", " ", text or "").split()).strip()
    if not t or len(t) > 80:
        return None
    import config
    if config.MOCK_PHONE:                                  # โหมดทดสอบ: ไม่ต่อเน็ต
        return None
    m = _WEATHER.match(t) or (re.search(r"(อากาศ|ฝน(?:จะ)?ตก)", t) and re.match(r"^(?:วันนี้|พรุ่งนี้|ตอนนี้|มะรืน)", t)
                              and _WEATHER.match(re.sub(r"^(วันนี้|พรุ่งนี้|ตอนนี้|มะรืน)\s*", "", t)))
    if m:
        day = 1 if "พรุ่งนี้" in t else (2 if "มะรืน" in t else 0)
        rest = re.sub(_TAIL, "", m.group("rest"))
        rest = re.sub(r"(วันนี้|พรุ่งนี้|มะรืนนี้|มะรืน|ตอนนี้|เป็นยังไง|เป็นไง|ร้อนไหม|ไหม|มั้ย)", " ", rest)
        pm = _PLACE.search(rest)
        place = pm.group("p").strip() if pm else None
        if not pm and rest.strip() and not re.search(r"(ไหม|มั้ย|ยังไง|เป็นไง|กี่องศา|เท่าไหร่|บ้าง|\?|เช็ค|ดู|ขอ|บอก)", t):
            return None                                   # "อากาศดีจัง" = คุยเล่น ไม่ใช่ถามอากาศ
        if not pm and 1 < len(rest.strip()) <= 20:
            place = rest.strip()                           # "อากาศเชียงใหม่เป็นไง"
        try:
            return weather(place, day)
        except Exception as e:  # noqa: BLE001
            print(f"[info] อากาศ: {e}", flush=True)
            return None                                    # ให้ AI ค้นเว็บตอบแทน
    m = _NEWS.match(t)
    if m and not re.search(r"(ส่ง|แชร์|โพสต์)", t):
        try:
            return news(m.group("q") or "")
        except Exception as e:  # noqa: BLE001
            print(f"[info] ข่าว: {e}", flush=True)
            return None
    return None
