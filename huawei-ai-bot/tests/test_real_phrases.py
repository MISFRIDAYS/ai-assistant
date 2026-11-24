"""ประโยคจริงที่ผู้ใช้เคยสั่ง (จาก log/ผลทดสอบบนเครื่อง) → ต้องตีความถูกทุกครั้ง

เจอประโยคที่สั่งแล้วพลาด → เพิ่ม 1 บรรทัดในตารางด้านล่าง แล้วแก้โค้ดจนเทสต์ผ่าน (CI กันไม่ให้พังซ้ำ)
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
os.environ.setdefault("SHARED_STORAGE", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

# (ประโยค, แอป, ผู้รับ, ข้อความ) — ส่งข้อความหาคน
DM = [
    # 2026-11-24 ผลทดสอบบนเครื่อง: สะกด instagram เพี้ยน → เคยส่งไป LINE
    ("เข้าไปที่ instragram เข้าไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ",
     "instagram", "ภรรยาคนเจ็ก", "สวัสดีฉัน Jamal เองครับ"),
    ("เข้า instragram ไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ",
     "instagram", "ภรรยาคนเจ็ก", "สวัสดีฉัน Jamal เองครับ"),
    ("เข้าไปที่ instagram เข้าไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ",
     "instagram", "ภรรยาคนเจ็ก", "สวัสดีฉัน Jamal เองครับ"),
    ("ส่งข้อความหาแม่ในไลน์ว่ากินข้าวยัง", "line", "แม่", "กินข้าวยัง"),
    ("ส่งไลน์หาเกตุว่าเดี๋ยวโทรกลับ", "line", "เกตุ", "เดี๋ยวโทรกลับ"),
    ("เข้าไอจีแล้วส่งข้อความหาต้นว่าพรุ่งนี้เจอกัน", "instagram", "ต้น", "พรุ่งนี้เจอกัน"),
    ("ส่งข้อความหาต้นในอินสตาว่าถึงแล้ว", "instagram", "ต้น", "ถึงแล้ว"),
    ("ทักเฟสหาพี่บอยว่าว่างไหม", "messenger", "พี่บอย", "ว่างไหม"),
    ("ไปที่แชทของ heart ในไอจีแล้วเขียนข้อความว่า ฝันดีนะ", "instagram", "heart", "ฝันดีนะ"),
]

# (ประโยค, แอป) — ดูฟีดแล้วสรุป
FEED = [
    ("เข้า Instragram แล้วดูโพสที่น่าสนใจในวันนี้", "instagram"),     # 2026-11-24: เคยหลุดไปให้ AI กดเอง 33 วิ
    ("เข้าไปที่ไอจีแล้วดูโพสต์น่าสนใจหน่อย", "instagram"),
    ("เปิดเฟสแล้วสรุปฟีดให้หน่อย", "facebook"),
]

# ประโยคที่ห้ามถูกอ่านเป็นการส่งข้อความ
NOT_DM = [
    "ออนไลน์อยู่ไหม",
    "เปิดยูทูป",
    "แบตเหลือเท่าไหร่",
    "ลดความสว่าง",
]


def _contacts():
    import contacts
    book = {"ภรรยาคนเจ็ก": {"name": "ภรรยาคนเจ็ก", "apps": {"line": 5}, "last": "line", "t": 1}}
    return {contacts.norm(k): v for k, v in book.items()}


class TestRealPhrases(unittest.TestCase):
    def setUp(self):
        import send_confirm
        send_confirm._P.clear()

    def test_dm(self):
        import quick, share_tools, contacts
        for text, app, to, msg in DM:
            with self.subTest(text=text), \
                    mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), \
                    mock.patch.object(contacts, "_load", side_effect=_contacts), \
                    mock.patch.object(contacts, "app_for", return_value="line"), \
                    mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว ✅") as sd:
                quick.dm(text, None)
                self.assertTrue(sd.called, "ไม่ได้ส่ง")
                a = sd.call_args[0][0]
                self.assertEqual((a["app"], a["to"], a["text"]), (app, to, msg))

    def test_feed(self):
        import quick, social
        for text, app in FEED:
            with self.subTest(text=text), mock.patch.object(social, "feed_summary", return_value="FEED") as f:
                self.assertEqual(quick.handle(text, None), "FEED")
                self.assertEqual(f.call_args[0][0], app)

    def test_not_dm(self):
        import quick, share_tools
        for text in NOT_DM:
            with self.subTest(text=text), mock.patch.object(share_tools, "send_dm") as sd:
                quick.dm(text, None)
                sd.assert_not_called()

    def test_open_app_alias(self):
        import phone_tools
        for word, app in (("instragram", "instagram"), ("ไอจี", "instagram"), ("ไลน์", "line"), ("เฟส", "facebook")):
            self.assertEqual(phone_tools.ALIASES.get(word, word), app, word)


if __name__ == "__main__":
    unittest.main()
