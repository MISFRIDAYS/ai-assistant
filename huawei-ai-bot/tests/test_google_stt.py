"""ถอดเสียงคำสั่งด้วยระบบรู้จำเสียงของเครื่อง (Google) + ใช้ตัวเดิมเมื่อใช้ไม่ได้"""
import json
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
import google_stt  # noqa: E402


class FakeBridge:
    def __init__(self, avail=True, result=None, visible=True):
        self.avail, self.result, self.visible, self.calls = avail, result, visible, 0

    def googleSttAvailable(self):
        return self.avail

    def googleListen(self, ms, lang):
        self.calls += 1
        return json.dumps(self.result)

    def appVisible(self):
        return self.visible


class TestGoogleStt(unittest.TestCase):
    def setUp(self):
        google_stt._S.update(avail=None, checked=0.0, off_until=0.0, empty_bg=0)
        self.p = [mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "GOOGLE_STT", True)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def _with(self, fb):
        return mock.patch.object(google_stt, "_bridge", return_value=fb)

    def test_text(self):
        fb = FakeBridge(result={"ok": True, "text": "ปลุก 6 โมงครึ่ง", "err": ""})
        with self._with(fb):
            self.assertEqual(google_stt.listen(), "ปลุก 6 โมงครึ่ง")

    def test_nobody_spoke_is_empty_not_fallback(self):
        fb = FakeBridge(result={"ok": True, "text": "", "err": "speech_timeout"})
        with self._with(fb):
            self.assertEqual(google_stt.listen(), "")

    def test_not_available_falls_back(self):
        with self._with(FakeBridge(avail=False)):
            self.assertIsNone(google_stt.listen())

    def test_error_falls_back_and_pauses(self):
        fb = FakeBridge(result={"ok": False, "text": "", "err": "language_unavailable"})
        with self._with(fb):
            self.assertIsNone(google_stt.listen())
            self.assertIsNone(google_stt.listen())
        self.assertEqual(fb.calls, 1)                    # ไม่ลองซ้ำทันที

    def test_silence_in_background_twice_turns_off(self):
        fb = FakeBridge(result={"ok": True, "text": "", "err": "no_match"}, visible=False)
        with self._with(fb):
            google_stt.listen()
            google_stt.listen()
            self.assertIsNone(google_stt.listen())

    def test_off_outside_app(self):
        with mock.patch.object(config, "ANDROID_APP", False):
            self.assertIsNone(google_stt.listen())

    def test_listen_text_prefers_google(self):
        import voice_chat
        with mock.patch.object(google_stt, "listen", return_value="เปิดเพลงสบายๆ"), \
                mock.patch.object(voice_chat.voice, "beep"):
            self.assertEqual(voice_chat.listen_text(timeout=5, check_owner=False), "เปิดเพลงสบายๆ")

    def test_followup_skips_google_so_voice_is_checked(self):
        """ช่วงฟังต่อหลังตอบ: Google ตรวจเสียงเจ้าของไม่ได้ → ต้องใช้ไมค์ของแอป (คนอื่นพูดจะได้ไม่ตอบ)"""
        import voice_chat
        mic = mock.Mock()
        mic.utterance.return_value = b""
        g = mock.Mock(return_value="คนอื่นคุยกันอยู่")
        with mock.patch.object(google_stt, "listen", g), \
                mock.patch.object(config, "SPEAKER_VERIFY", True), \
                mock.patch.object(voice_chat, "get_mic", return_value=mic), \
                mock.patch.object(voice_chat.voice, "beep"):
            self.assertEqual(voice_chat.listen_text(timeout=1, check_owner=True), "")
        g.assert_not_called()

    def test_listen_text_falls_back_when_none(self):
        import voice_chat
        mic = mock.Mock()
        mic.utterance.return_value = b""
        with mock.patch.object(google_stt, "listen", return_value=None), \
                mock.patch.object(voice_chat, "get_mic", return_value=mic), \
                mock.patch.object(voice_chat.voice, "beep"):
            self.assertEqual(voice_chat.listen_text(timeout=1), "")
        mic.utterance.assert_called()


if __name__ == "__main__":
    unittest.main()
