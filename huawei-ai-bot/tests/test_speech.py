"""พูดออกเสียงแบบคนคุยกัน: คำตอบยาวพูดแค่ช่วงแรก · บอกที่อยู่ของคำตอบเต็มให้ถูก (แอป=บนจอ)"""
import os
import sys
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

FEED = ("📰 โพสต์น่าสนใจใน Instagram ตอนนี้:\n"
        "• เกตุโพสต์รูปไปเที่ยวทะเลที่หัวหินกับครอบครัวช่วงวันหยุดยาว\n"
        "• พี่บอยแชร์ข่าวราคาน้ำมันขึ้นอีกลิตรละ 50 สตางค์ตั้งแต่พรุ่งนี้\n"
        "• เพจร้านกาแฟแถวบ้านลดราคา 20% ทุกเมนูถึงสิ้นเดือน\n"
        "• แม่โพสต์สูตรแกงเขียวหวานไก่แบบง่าย ๆ\n"
        "• เพื่อนสมัยเรียนชวนไปงานเลี้ยงรุ่นเดือนหน้า")


class TestSpeakable(unittest.TestCase):
    def test_short_unchanged(self):
        import voice
        self.assertEqual(voice.speakable("แบตเหลือ 66% ครับ"), "แบตเหลือ 66 เปอร์เซ็นต์ ครับ")

    def test_long_list_cut_at_line(self):
        import voice
        with mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "VOICE_MAX_SPEAK", 220):
            s = voice.speakable(FEED)
            note = voice.more_note()
        self.assertLess(len(s), 300)
        self.assertIn("เกตุโพสต์รูป", s)
        self.assertNotIn("งานเลี้ยงรุ่น", s)
        self.assertTrue(s.endswith(note))
        self.assertIn("บนจอ", s)
        self.assertNotIn("•", s)
        self.assertNotIn("📰", s)

    def test_one_long_line(self):
        import voice
        s = voice.speakable("ข้อความยาว " * 80, limit=100)
        self.assertLess(len(s), 100 + len(voice.more_note()) + 5)

    def test_note_where_full_answer_is(self):
        import voice
        with mock.patch.object(config, "ANDROID_APP", True):
            self.assertIn("บนจอ", voice.more_note())
        with mock.patch.object(config, "ANDROID_APP", False):
            self.assertIn("Telegram", voice.more_note())


if __name__ == "__main__":
    unittest.main()
