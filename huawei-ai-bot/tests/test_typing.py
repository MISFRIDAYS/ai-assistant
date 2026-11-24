"""พิมพ์ข้อความในแอป: ไม่สลับคีย์บอร์ด · แอปแชทห้ามกดค้างกลางจอ · บอกผลตามจริง"""
import os
import sys
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402


class _Bridge:
    def __init__(self, type_ok=False, paste_ok=False):
        self.type_ok, self.paste_ok = type_ok, paste_ok
        self.long_taps = []
        self.clip = None

    def typeText(self, text, append):
        return self.type_ok

    def lastViaIme(self):
        return False

    def clipboardSet(self, t):
        self.clip = t

    def paste(self):
        return self.paste_ok

    def longTap(self, x, y, ms):
        self.long_taps.append((x, y))


class TestTyping(unittest.TestCase):
    def _type(self, b, pkg):
        import screen_tools, android_shim
        with mock.patch.object(config, "ANDROID_APP", True), mock.patch("time.sleep"), \
                mock.patch.object(android_shim, "bridge", return_value=b), \
                mock.patch.object(screen_tools, "_current_app", return_value=pkg), \
                mock.patch.object(screen_tools, "_dump", side_effect=RuntimeError("no dump in test")):
            return screen_tools.type_text({"text": "สวัสดีฉัน Jamal เองครับ", "send": False}, None)

    def test_chat_app_never_long_presses(self):
        b = _Bridge()
        res = self._type(b, "com.instagram.android")
        self.assertTrue(res.startswith("ERROR"), res)
        self.assertIn("คลิปบอร์ด", res)
        self.assertEqual(b.long_taps, [])
        self.assertEqual(b.clip, "สวัสดีฉัน Jamal เองครับ")

    def test_paste_fallback_works(self):
        b = _Bridge(paste_ok=True)
        res = self._type(b, "com.instagram.android")
        self.assertFalse(res.startswith("ERROR"), res)

    def test_direct_typing(self):
        b = _Bridge(type_ok=True)
        self.assertFalse(self._type(b, "jp.naver.line.android").startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
