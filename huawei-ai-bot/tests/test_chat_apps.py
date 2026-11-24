"""ตารางแอปแชทกลาง (chat_apps.py)"""
import os
import sys
import unittest

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chat_apps  # noqa: E402


class TestChatApps(unittest.TestCase):
    def test_words(self):
        cases = {
            "instagram": ["ไอจี", "ไอจี้", "ig", "IG", "Instagram", "instragram", "instgram", "intagram", "insta",
                          "อินสตา", "อินสตาแกรม", "อินสตราแกรม", "อินสต้าแกรม", "อินสตาร์แกรม", "อินสตาแกม", "อินสตาร์"],
            "line": ["ไลน์", "line", "LINE"],
            "messenger": ["เมสเซนเจอร์", "เมสเซ็นเจอร์", "messenger", "แชทเฟส"],
            "facebook": ["เฟส", "เฟสบุ๊ค", "เฟซบุ๊ก", "facebook", "fb"],
            "whatsapp": ["วอทส์แอป", "วอทแอป", "whatsapp"],
            "telegram": ["เทเลแกรม", "telegram"],
        }
        for k, words in cases.items():
            for w in words:
                self.assertEqual(chat_apps.key(w), k, w)

    def test_dm_facebook_is_messenger(self):
        self.assertEqual(chat_apps.key("เฟส", dm=True), "messenger")
        self.assertEqual(chat_apps.key("facebook", dm=True), "messenger")
        self.assertEqual(chat_apps.key("เฟส"), "facebook")

    def test_no_false_hits_inside_words(self):
        for t in ("ออนไลน์อยู่ไหม online", "big boss", "program", "telegraph", "diagram", "ข้อความ"):
            k, _ = chat_apps.find(t)
            self.assertIsNone(k, t)

    def test_find_in_sentence(self):
        k, m = chat_apps.find("เข้าไปที่ instagram เข้าไปที่แชท ภรรยา ส่งข้อความ สวัสดี", dm=True)
        self.assertEqual(k, "instagram")
        self.assertEqual(m.group(1), "instagram")
        self.assertEqual(chat_apps.find("ส่งไลน์หาแม่ว่ากินข้าวยัง")[0], "line")

    def test_packages(self):
        self.assertEqual(chat_apps.PKG_APP["com.instagram.android"], "instagram")
        self.assertEqual(chat_apps.PKG_APP["com.huawei.message"], "sms")
        self.assertEqual(chat_apps.APP_PKG["line"], "jp.naver.line.android")
        self.assertEqual(chat_apps.PKG_LABEL["com.facebook.orca"], "Messenger")

    def test_other_modules_share_the_table(self):
        import contacts, quick, fastpath, share_tools
        self.assertIs(contacts.APP_KEYS, chat_apps.PKG_APP)
        self.assertEqual(quick._DM_APP, chat_apps.ANY)
        self.assertEqual(fastpath._PKG_APP["com.facebook.katana"], "messenger")
        self.assertEqual(set(share_tools.APP_PKG), set(chat_apps.DM_APPS))


if __name__ == "__main__":
    unittest.main()
