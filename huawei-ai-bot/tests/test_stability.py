"""ทดสอบความเสถียร: จำกัดการถอดเสียงแบบเสียเงินตอนรอคำปลุก"""
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


class TestWakeSttCap(unittest.TestCase):
    def setUp(self):
        import voice
        self.v = voice
        voice._nano_wake.clear()
        self.p = [mock.patch.object(config, "MOCK_PHONE", False),
                  mock.patch.object(voice, "NANO_WAKE_PER_HOUR", 2),
                  mock.patch.object(voice, "stt_chain", return_value=["nano"]),
                  mock.patch.object(voice, "_transcribe_nano", return_value="สวัสดี")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_wake_capped_per_hour(self):
        out = [self.v.transcribe("x.wav", wake=True) for _ in range(4)]
        self.assertEqual(out, ["สวัสดี", "สวัสดี", "", ""])

    def test_commands_never_capped(self):
        for _ in range(3):
            self.v.transcribe("x.wav", wake=True)
        self.assertEqual(self.v.transcribe("x.wav"), "สวัสดี")      # คำสั่งจริงหลังเรียกผู้ช่วย → ถอดได้เสมอ

    def test_free_engine_not_counted(self):
        with mock.patch.object(self.v, "stt_chain", return_value=["groq", "nano"]), \
                mock.patch.object(self.v, "_transcribe_groq", return_value="ผู้ช่วย"):
            for _ in range(5):
                self.assertEqual(self.v.transcribe("x.wav", wake=True), "ผู้ช่วย")
        self.assertEqual(len(self.v._nano_wake), 0)



class TestWakeWord(unittest.TestCase):
    """คำพูดทั่วไป/เสียงทีวี ต้องไม่ปลุกผู้ช่วยเอง แต่การเรียกจริงต้องยังใช้ได้"""

    def test_not_a_call(self):
        import voice_chat
        for t in ("นี่ พี่จ๋า เปิดประตูหน่อย", "เขาเป็นผู้ช่วยผู้จัดการ ส่งงานให้เขาเลย", "ผู้ช่วยแพทย์โทรมา",
                  "เฮ้ย พี่ชาย เปิดไฟ", "วันนี้ผู้ชายคนนั้นมา", "ข่าววันนี้ ผู้ช่วยรัฐมนตรีแถลง"):
            self.assertFalse(voice_chat.find_wake(t)[0], t)

    def test_real_calls(self):
        import voice_chat
        for t, rest in (("ผู้ช่วย เปิดยูทูป", "เปิดยูทูป"), ("เฮ้ย ผู้ช่วย ปิดไฟ", "ปิดไฟ"),
                        ("เอ่อ ผู้ช่วย ส่งไลน์หาแม่", "ส่งไลน์หาแม่"), ("โอเคผู้ช่วย เปิดเพลง", "เปิดเพลง"),
                        ("เฮ้ย บุชไว เปิดยูทูป", "เปิดยูทูป"), ("เฮ้ย บูชัย ปิดไฟ", "ปิดไฟ"), ("ผู้ช้วย กี่โมงแล้ว", "กี่โมงแล้ว"),
                        ("สวัสดีผู้ช่วย", "")):
            self.assertEqual(voice_chat.find_wake(t), (True, rest), t)


class TestVoiceConfirmSend(unittest.TestCase):
    def test_voice_send_asks_first(self):
        import permissions
        import voice_chat

        class Ctx:
            hold = False
        with mock.patch.object(config, "AUTO_SEND", True), mock.patch.object(config, "VOICE_CONFIRM_SEND", True):
            self.assertTrue(permissions.need_confirm(voice_chat.VoiceCtx.__new__(voice_chat.VoiceCtx), "message"))
            self.assertFalse(permissions.need_confirm(Ctx(), "message"))          # พิมพ์สั่ง → ส่งได้เลยเหมือนเดิม
        with mock.patch.object(config, "VOICE_CONFIRM_SEND", False), mock.patch.object(config, "AUTO_SEND", True):
            self.assertFalse(permissions.need_confirm(voice_chat.VoiceCtx.__new__(voice_chat.VoiceCtx), "message"))

if __name__ == "__main__":
    unittest.main()
