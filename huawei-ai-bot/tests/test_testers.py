"""ทดสอบรุ่นสำหรับผู้ทดลอง: บังคับลงทะเบียนเสียง + รองรับมือถือหลายยี่ห้อ"""
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


class TestVoiceEnrollGate(unittest.TestCase):
    def setUp(self):
        import voice_chat
        self.vc = voice_chat
        voice_chat._ENROLLING[0] = False

    def test_blocks_until_enrolled(self):
        import speaker_id
        with mock.patch.object(config, "REQUIRE_VOICE_ENROLL", True, create=True), \
                mock.patch.object(speaker_id, "enrolled", return_value=False):
            self.assertFalse(self.vc.owner_voice(b"\0" * 32000))

    def test_passes_after_enrolled(self):
        import speaker_id
        with mock.patch.object(config, "REQUIRE_VOICE_ENROLL", True, create=True), \
                mock.patch.object(config, "SPEAKER_VERIFY", True), \
                mock.patch.object(speaker_id, "enrolled", return_value=True), \
                mock.patch.object(speaker_id, "check", return_value=(True, 0.9)):
            self.assertTrue(self.vc.owner_voice(b"\0" * 32000))

    def test_not_required_keeps_old_behaviour(self):
        import speaker_id
        with mock.patch.object(config, "REQUIRE_VOICE_ENROLL", False, create=True), \
                mock.patch.object(config, "SPEAKER_VERIFY", False), \
                mock.patch.object(speaker_id, "enrolled", return_value=False):
            self.assertTrue(self.vc.owner_voice(b"\0" * 32000))

    def test_off_outside_android_app(self):
        self.assertFalse(config.REQUIRE_VOICE_ENROLL)       # Termux/คอม/เทสต์ ไม่บังคับ


class TestOtherBrands(unittest.TestCase):
    def tearDown(self):
        import device
        device._DEV.clear()

    def test_brand_packages_listed(self):
        import phone_tools
        alt = phone_tools.ALT_PKGS
        self.assertIn("com.sec.android.app.camera", alt["camera"])          # Samsung
        self.assertIn("com.miui.gallery", alt["gallery"])                   # Xiaomi/Redmi
        self.assertIn("com.bbk.calendar", alt["calendar"])                  # Vivo
        self.assertIn("com.coloros.calculator", alt["calculator"])          # Oppo
        self.assertIn("com.samsung.android.app.notes", alt["notes"])
        self.assertIn("files", alt)

    def _as(self, man, model="Phone", ver="14"):
        import device
        device._DEV.clear()
        device._DEV["id"] = (man, model, ver)
        return device

    def test_other_brand_gets_generic_knowledge(self):
        d = self._as("samsung", "SM-A556E")
        self.assertFalse(d.is_matepad())
        self.assertNotIn("AppGallery", d.prompt())
        self.assertIn("SM-A556E", d.prompt())

    def test_huawei_keeps_matepad_knowledge(self):
        d = self._as("HUAWEI", "TXZ-W09")
        self.assertTrue(d.is_matepad())
        self.assertIn("AppGallery", d.prompt())

    def test_info_names_real_phone(self):
        d = self._as("Xiaomi", "Redmi Note 13", "14")
        with mock.patch.object(d, "live", return_value={}):
            out = d.info()
        self.assertIn("Redmi Note 13", out)
        self.assertNotIn("MatePad", out)


class TestVoiceMatchV61(unittest.TestCase):
    """เสียงเจ้าของโดนปฏิเสธบ่อย → ผ่อนเกณฑ์ + เรียนเสียงจริงจากการใช้งาน"""
    def setUp(self):
        import speaker_id
        self.sp = speaker_id
        self.d = tempfile.mkdtemp()
        self.p = mock.patch.object(config, "DATA_DIR", self.d)
        self.p.start()
        speaker_id._cache["prof"] = None

    def tearDown(self):
        self.p.stop()
        self.sp._cache["prof"] = None

    def _pcm(self, seed, f0=140.0):
        import numpy as np
        r = np.random.default_rng(seed)
        t = np.arange(16000 * 2) / 16000
        x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8)) * 3000
        x = x * (1 + 0.3 * np.sin(2 * np.pi * 3 * t)) + r.normal(0, 300, len(t))
        return x.astype(np.int16).tobytes()

    def test_enroll_keeps_vectors_and_adapt_learns(self):
        if not self.sp.available():
            self.skipTest("no numpy")
        prof = self.sp.enroll([self._pcm(i) for i in range(6)])
        self.assertEqual(len(prof["vecs"]), 6)
        self.assertTrue(self.sp.adapt(self._pcm(99)))
        p2 = self.sp._load()
        self.assertEqual(p2["n"], 6)
        self.assertEqual(len(p2["vecs"]), 7)
        self.assertEqual(p2["learned"], 1)

    def test_near_uses_last_score(self):
        self.sp.last.update(score=0.30, th=0.38)
        self.assertTrue(self.sp.near(0.12))
        self.sp.last.update(score=0.10, th=0.38)
        self.assertFalse(self.sp.near(0.12))

    def test_speed_report_command(self):
        import quick
        import perf
        with mock.patch.object(perf, "summary", return_value="📊 สรุปผล") as s:
            self.assertIn("สรุปผล", quick.handle("สรุปผลทดสอบ"))
            s.assert_called_once()
        with mock.patch.object(perf, "summary", return_value="📊") as s:
            quick.handle("ทดสอบ")
            s.assert_not_called()

    def test_background_study_waits_while_user_active(self):
        import perf
        perf.touch()
        self.assertFalse(perf.idle(180))
        perf.LAST[0] = 0.0
        self.assertTrue(perf.idle(180))


if __name__ == "__main__":
    unittest.main()
