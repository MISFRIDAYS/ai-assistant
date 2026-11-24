"""สรุปฟีดโซเชียล: รู้จักชื่อแอปสะกดเพี้ยน · ไม่หน่วงตายตัว · สรุปด้วย Groq ก่อน"""
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

POSTS = [{"text": f"โพสต์ของเพื่อนคนที่ {i} เล่าเรื่องเที่ยวทะเลวันหยุดยาวสนุกมาก", "desc": ""} for i in range(4)]


class TestFeedRouting(unittest.TestCase):
    def test_incident_sentence_goes_to_feed(self):
        import social, quick
        with mock.patch.object(social, "feed_summary", return_value="FEED") as f:
            self.assertEqual(quick.handle("เข้า Instragram แล้วดูโพสที่น่าสนใจในวันนี้", None), "FEED")
        self.assertEqual(f.call_args[0][0], "instagram")

    def test_variants(self):
        import social
        for t, app in (("เข้าไปที่ไอจีแล้วดูโพสต์น่าสนใจหน่อย", "instagram"), ("เปิดเฟสแล้วสรุปฟีดให้หน่อย", "facebook"),
                       ("เปิดยูทูปแล้วดูคลิปน่าสนใจ", "youtube")):
            m = social._FEED.match(t)
            self.assertTrue(m, t)
            self.assertEqual(social._which(m), app, t)


class TestFeedSummary(unittest.TestCase):
    def _run(self, groq_ok=True):
        import social, phone_tools, screen_tools, share_tools, agent, groq_client
        sleeps = []
        g = mock.Mock(return_value={"content": [{"type": "text", "text": "• สรุปจาก Groq"}]}) if groq_ok \
            else mock.Mock(side_effect=RuntimeError("429"))
        with mock.patch.object(config, "MOCK_PHONE", False), mock.patch.object(config, "GROQ_API_KEY", "k"), \
                mock.patch.object(config, "LLM_PROVIDER", "cloud"), \
                mock.patch("time.sleep", side_effect=sleeps.append), \
                mock.patch.object(phone_tools, "open_app", return_value="เปิดแล้ว"), \
                mock.patch.object(share_tools, "_items", return_value=POSTS), \
                mock.patch.object(screen_tools, "swipe") as sw, \
                mock.patch.object(groq_client, "create_message", g), \
                mock.patch.object(agent, "call_llm",
                                  return_value=({"content": [{"type": "text", "text": "• สรุปจากตัวหลัก"}]}, "cloud")) as cl:
            out = social.feed_summary("instagram", "โพสต์น่าสนใจ")
        return out, sleeps, sw, g, cl

    def test_groq_first_no_long_sleeps(self):
        out, sleeps, sw, g, cl = self._run()
        self.assertIn("สรุปจาก Groq", out)
        cl.assert_not_called()
        self.assertEqual(sw.call_count, 2)                     # 3 หน้าจอ
        self.assertLessEqual(sum(sleeps), 2.5)                 # เดิม 3 + 2×3 = 9 วิ
        system = g.call_args[0][0]
        self.assertLess(len(system), 300)                      # ไม่ส่งคำสั่งระบบทั้งชุด

    def test_falls_back_to_main(self):
        out, _s, _sw, _g, cl = self._run(groq_ok=False)
        self.assertIn("สรุปจากตัวหลัก", out)
        self.assertLess(len(cl.call_args[1]["system"]), 300)


if __name__ == "__main__":
    unittest.main()
