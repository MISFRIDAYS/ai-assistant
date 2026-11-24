"""แอปแชท: ชื่อ · package · คำเรียก (ไทย/อังกฤษ/สะกดเพี้ยน) — ที่เดียวทั้งโปรแกรม

เพิ่มแอป/คำเรียกใหม่ที่นี่ที่เดียว แล้วทุกส่วน (สั่งส่งข้อความ · รายชื่อติดต่อ · ตอบแชท · แจ้งเตือน) รู้จักพร้อมกัน
"""
import re

_L = r"(?<![a-z])"                    # คำอังกฤษต้องไม่อยู่กลางคำอื่น ('ig' ใน 'big', 'line' ใน 'online')
_R = r"(?![a-z])"

# key: (package หลัก, package อื่น, ชื่อที่แสดง, คำเรียก regex)
APPS = {
    "line": ("jp.naver.line.android", (), "LINE", rf"(?<!ออน)ไลน์|{_L}line{_R}"),
    "instagram": ("com.instagram.android", (), "Instagram",
                  # สะกด/ถอดเสียงเพี้ยน: instragram, instagam, instgram, intagram, insta, อินสตาร์แกรม …
                  rf"ไอจี้?|อินส(?:ต|ตร|ต้)า(?:ร์)?(?:แกรม|แกม)?|{_L}(?:i?ns?t?[ar]{{0,3}}gr?a?m+|insta|ig){_R}"),
    "messenger": ("com.facebook.orca", (), "Messenger", rf"เมสเซ็?นเจอร์|แชทเฟส|{_L}messenger{_R}"),
    "facebook": ("com.facebook.katana", (), "Facebook", rf"เฟ[สซ](?:บุ๊[คก]|บุค)?|{_L}(?:facebook|fb){_R}"),
    "whatsapp": ("com.whatsapp", (), "WhatsApp", rf"วอทส?์?แอป|{_L}whatsapp{_R}"),
    "telegram": ("org.telegram.messenger", (), "Telegram", rf"เทเลแกรม|{_L}telegram{_R}"),
    "sms": ("com.google.android.apps.messaging", ("com.android.mms", "com.huawei.message"), "SMS",
            rf"ข้อความมือถือ|{_L}sms{_R}"),
    "discord": ("com.discord", (), "Discord", rf"ดิสคอร์ด|{_L}discord{_R}"),
    "viber": ("com.viber.voip", (), "Viber", rf"ไวเบอร์|{_L}viber{_R}"),
    "wechat": ("com.tencent.mm", (), "WeChat", rf"วีแชท|{_L}wechat{_R}"),
}

# แอปที่ส่งข้อความหาคนได้ด้วยระบบส่งอัตโนมัติ (send_dm)
DM_APPS = ("instagram", "line", "messenger", "telegram", "whatsapp", "facebook")

PKG_APP = {}
for _k, (_p, _alt, _lab, _w) in APPS.items():
    for _pp in (_p,) + _alt:
        PKG_APP[_pp] = _k
APP_PKG = {k: v[0] for k, v in APPS.items()}
LABEL = {k: v[2] for k, v in APPS.items()}
PKG_LABEL = {p: LABEL[k] for p, k in PKG_APP.items()}
WORDS = {k: v[3] for k, v in APPS.items()}

# messenger ต้องมาก่อน facebook ("แชทเฟส"), แอปอื่นตามลำดับใน APPS
ANY = "(" + "|".join(WORDS[k] for k in APPS) + ")"
_ANY_RX = re.compile(ANY, re.I)
_ONE = {k: re.compile(rf"^(?:{w})$", re.I) for k, w in WORDS.items()}


def rx(keys=None):
    """regex (ไม่จับกลุ่ม) ของคำเรียกแอปที่ระบุ — ใช้ฝังในประโยคคำสั่งของโมดูลอื่น"""
    return "(?:" + "|".join(WORDS[k] for k in (keys or APPS)) + ")"


def key(word, dm=False):
    """คำที่พูด/พิมพ์ → ชื่อแอปมาตรฐาน หรือ None
    dm=True: ส่งข้อความหาคน → 'เฟส/facebook' หมายถึง messenger (ส่งข้อความในแอป Facebook ไม่ได้)"""
    w = (word or "").strip().lower()
    if not w:
        return None
    if w in APPS:
        k = w
    else:
        k = next((k for k, rx in _ONE.items() if rx.match(w)), None)
    if dm and k == "facebook":
        return "messenger"
    return k


def find(text, dm=False):
    """หาชื่อแอปแชทในประโยค → (key, match) หรือ (None, None)"""
    m = _ANY_RX.search(text or "")
    if not m:
        return None, None
    return key(m.group(1), dm=dm), m
