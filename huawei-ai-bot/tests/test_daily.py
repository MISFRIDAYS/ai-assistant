"""งานประจำวันแบบไม่ใช้ AI: ปลุก · จับเวลา · เตือน + สลับ Ollama/คลาวด์ + บันทึกเครื่องมือที่พลาด"""
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
import daily  # noqa: E402


class Ctx:
    def __init__(self):
        self.rem = []

    def add_reminder(self, minutes, text):
        self.rem.append((minutes, text))
        return "01/01 12:00"


class TestParse(unittest.TestCase):
    def test_clock(self):
        cases = {"6 โมงครึ่ง": (6, 30), "ตี 5": (5, 0), "ตีห้า": (5, 0), "บ่าย 2": (14, 0), "บ่ายโมง": (13, 0),
                 "2 ทุ่ม": (20, 0), "สองทุ่มครึ่ง": (20, 30), "เที่ยง": (12, 0), "เที่ยงคืน": (0, 0),
                 "06:30": (6, 30), "18.45": (18, 45), "6 โมงเช้า": (6, 0), "5 โมงเย็น": (17, 0),
                 "4 โมง": (16, 0), "11 โมง": (11, 0), "7 โมง 15 นาที": (7, 15)}
        for s, want in cases.items():
            self.assertEqual(daily.parse_clock(s), want, s)

    def test_duration(self):
        cases = {"5 นาที": 300, "1 ชั่วโมงครึ่ง": 5400, "30 วิ": 30, "2 ชม. 15 นาที": 8100,
                 "ชั่วโมงนึง": 3600, "ครึ่งนาที": 30, "สิบนาที": 600}
        for s, want in cases.items():
            self.assertEqual(daily.parse_duration(s), want, s)
        self.assertIsNone(daily.parse_duration("พรุ่งนี้"))


class TestCommands(unittest.TestCase):
    def _runs(self, text, ctx=None):
        calls = []
        with mock.patch.object(daily, "_run", side_effect=lambda n, a, c: calls.append((n, a)) or "ok"):
            out = daily.handle_text(text, ctx or Ctx())
        return out, calls

    def test_alarm(self):
        out, calls = self._runs("ตั้งปลุก 6 โมงครึ่งหน่อย")
        self.assertEqual(calls, [("set_alarm", {"hour": 6, "minute": 30, "label": "ปลุก"})])
        self.assertIn("06:30", out)
        out, calls = self._runs("ปลุกตี 5 ชื่อวิ่ง")
        self.assertEqual(calls[0][1]["label"], "วิ่ง")

    def test_repeat_alarm_goes_to_ai(self):
        self.assertEqual(self._runs("ปลุก 6 โมงทุกวัน"), (None, []))

    def test_timer(self):
        out, calls = self._runs("จับเวลา 5 นาที")
        self.assertEqual(calls, [("set_timer", {"seconds": 300})])
        self.assertIn("5 นาที", out)

    def test_timer_not_other_settings(self):
        self.assertEqual(self._runs("ตั้งเวลาปิดจอ 5 นาที"), (None, []))

    def test_remind_after(self):
        ctx = Ctx()
        out, calls = self._runs("อีก 10 นาทีเตือนให้ปิดเตา", ctx)
        self.assertEqual(calls, [("remind_me", {"minutes": 10.0, "text": "ปิดเตา"})])
        self.assertIn("ปิดเตา", out)
        out, calls = self._runs("เตือนให้โทรหาแม่ในอีก 1 ชั่วโมง", ctx)
        self.assertEqual(calls[0][1], {"minutes": 60.0, "text": "โทรหาแม่"})

    def test_remind_at_clock(self):
        out, calls = self._runs("เตือนกินยาตอน 2 ทุ่ม")
        self.assertEqual(calls[0][0], "remind_me")
        self.assertEqual(calls[0][1]["text"], "กินยา")
        self.assertTrue(0 < calls[0][1]["minutes"] <= 24 * 60)

    def test_not_daily(self):
        for t in ["ปิดปลุก", "วันนี้อากาศเป็นไง", "เปิดยูทูป"]:
            self.assertEqual(self._runs(t), (None, []), t)

    def test_quick_uses_daily_and_mock_clock_app(self):
        import quick
        out = quick.handle("จับเวลา 3 นาที", Ctx())
        self.assertIn("จับเวลา", out)

    def test_timer_tool_registered(self):
        import phone_tools
        self.assertIn("set_timer", phone_tools.TOOLS)
        self.assertIn("set_timer", phone_tools.CORE_TOOLS)


class TestHybridAI(unittest.TestCase):
    def setUp(self):
        import agent
        self.agent = agent
        agent._reach.update(t=0.0, ok=True)

    def test_away_from_home_uses_cloud_directly(self):
        a = self.agent
        with mock.patch.object(config, "LLM_PROVIDER", "ollama"), \
                mock.patch.object(config, "LLM_FALLBACK", "cloud"), \
                mock.patch.object(config, "OLLAMA_URL", "http://192.168.1.50:11434"), \
                mock.patch.object(a, "ollama_reachable", return_value=False), \
                mock.patch.object(a, "_call_provider", return_value=("ok", "Cloud")) as cp:
            a._fallback_until[0] = 0.0
            a.call_llm([], [])
        self.assertEqual(cp.call_args[0][0], "cloud")

    def test_at_home_uses_ollama(self):
        a = self.agent
        with mock.patch.object(config, "LLM_PROVIDER", "ollama"), \
                mock.patch.object(config, "LLM_FALLBACK", "cloud"), \
                mock.patch.object(config, "OLLAMA_URL", "http://192.168.1.50:11434"), \
                mock.patch.object(a, "ollama_reachable", return_value=True), \
                mock.patch.object(a, "_call_provider", return_value=("ok", "Ollama")) as cp:
            a._fallback_until[0] = 0.0
            a.call_llm([], [])
        self.assertEqual(cp.call_args[0][0], "ollama")

    def test_reachable_unreachable_host_is_fast(self):
        import time
        with mock.patch.object(config, "OLLAMA_URL", "http://10.255.255.1:11434"), \
                mock.patch.object(config, "MOCK_PHONE", False):
            t0 = time.time()
            self.assertFalse(self.agent.ollama_reachable())
            self.assertLess(time.time() - t0, 2.0)


class TestToolLog(unittest.TestCase):
    def test_failed_tool_attached_to_command(self):
        import perf
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d):
            perf.tool("open_app", True)
            perf.tool("tap_text", False)
            perf.record("chat", "เปิดไลน์แล้วกดแชท", total=2.0, ok=False)
            rows = perf.rows()
            self.assertEqual(rows[-1]["tools"], ["open_app", "tap_text✗"])
            s = perf.summary(7)
        self.assertIn("tap_text: 1", s)
        self.assertIn("เปิดไลน์", s)


class TestSpeedAndStats(unittest.TestCase):
    def test_fast_chat_only_for_plain_chat(self):
        import agent
        agent._fast_chat_off[0] = 0.0
        txt = [{"type": "text", "text": "สวัสดี"}]
        with mock.patch.object(config, "GROQ_API_KEY", "k"), mock.patch.object(config, "LLM_PROVIDER", "cloud"):
            self.assertTrue(agent._fast_chat_ok("", txt))
            self.assertFalse(agent._fast_chat_ok("ผลค้นเว็บ...", txt))           # มีข้อมูลค้นมา → ตัวหลัก
            self.assertFalse(agent._fast_chat_ok("", txt + [{"type": "image"}]))  # มีรูป → ตัวหลัก
        with mock.patch.object(config, "GROQ_API_KEY", ""):
            self.assertFalse(agent._fast_chat_ok("", txt))

    def test_fast_chat_falls_back_to_main(self):
        import agent
        import groq_client
        agent._fast_chat_off[0] = 0.0
        with mock.patch.object(config, "GROQ_API_KEY", "k"), mock.patch.object(config, "LLM_PROVIDER", "cloud"), \
                mock.patch.object(groq_client, "create_message", side_effect=groq_client.GroqError("429 rate")), \
                mock.patch.object(agent, "call_llm", return_value=({"content": [{"type": "text", "text": "ตัวหลักตอบ"}],
                                                                      "usage": {}}, "Cloud")), \
                mock.patch.object(agent, "save_history"):
            out = agent._answer("t", [], {"type": "text", "text": "[เวลา]"}, [{"type": "text", "text": "ว่าไง"}], None)
        self.assertEqual(out, "ตัวหลักตอบ")
        self.assertGreater(agent._fast_chat_off[0], 0)

    def test_ignored_speech_not_counted_as_failure(self):
        import perf
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d):
            perf.mark_ignored()
            perf.record("voice", "เล่นเกมอยู่", total=1.0, ok=False)
            perf._IGNORED[0] = 0.0
            perf.record("voice", "เปิดไลน์", total=1.0, ok=True)
            s = perf.summary(7)
        self.assertIn("1/1", s)
        self.assertNotIn("เล่นเกมอยู่", s)


class TestSmallerFasterRequests(unittest.TestCase):
    def test_cloud_gets_recent_window_only(self):
        import agent
        import cloud_client
        hist = []
        for i in range(30):
            hist.append({"role": "user", "content": [{"type": "text", "text": f"คำถาม {i}"}]})
            hist.append({"role": "assistant", "content": [{"type": "text", "text": f"คำตอบ {i}"}]})
        seen = {}
        with mock.patch.object(cloud_client, "create_message",
                               side_effect=lambda sp, h, t, m, on_text=None: seen.setdefault("h", h) or {"content": []}):
            agent._call_provider("cloud", hist, [], None, system="s")
        self.assertLess(len(seen["h"]), 20)
        self.assertEqual(seen["h"][-1]["content"][0]["text"], "คำตอบ 29")

    def test_compound_command_skips_router(self):
        import agent
        import router
        self.assertTrue(agent._COMPOUND.search("เข้าไอจีแล้วกดแชทภรรยา"))
        self.assertFalse(agent._COMPOUND.search("วันนี้อากาศเป็นไง"))


if __name__ == "__main__":
    unittest.main()


class TestV70Fixes(unittest.TestCase):
    def test_goto_chat_phrases(self):
        import social
        cases = {
            "เข้าไปที่แชท ภรรยาคนเจก": ("ภรรยาคนเจก", None),
            "เข้าไอจีแล้วเปิดแชท ภรรยา": ("ภรรยา", "instagram"),
            "เปิดไลน์ไปที่แชท พี่ต้น": ("พี่ต้น", "line"),
            "เข้าแชท แม่ ในไลน์": ("แม่", "line"),
        }
        for text, (to, app) in cases.items():
            with mock.patch.object(social, "goto_chat", return_value="ok") as g:
                self.assertEqual(social.handle_text(text), "ok", text)
            self.assertEqual(g.call_args[0][0], to, text)
            self.assertEqual(g.call_args[0][1], app, text)

    def test_not_a_chat_command(self):
        import social
        with mock.patch.object(social, "goto_chat", return_value="ok") as g:
            for text in ["แชทกับแม่สนุกดี", "เปิด instagram แล้วเปิดแชทหน่อย", "ส่งไลน์หาแม่ว่ากินข้าว"]:
                social.handle_text(text)
        g.assert_not_called()

    def test_followup_needs_command_words(self):
        import voice_chat
        with mock.patch.dict(voice_chat.voice._last, {"logprob": None}):
            self.assertFalse(voice_chat.followup_ok("วันนี้ฝนตกปอยๆ"))
            self.assertTrue(voice_chat.followup_ok("แล้วพรุ่งนี้ล่ะ อากาศเป็นยังไง"))

    def test_clock_save_button_is_pressed(self):
        import phone_tools
        import screen_tools
        items = [{"text": "ยกเลิก", "desc": "", "id": "cancel", "x": 50, "y": 100, "click": True},
                 {"text": "", "desc": "ตกลง", "id": "menu_ok", "x": 1000, "y": 100, "click": True},
                 {"text": "06:30", "desc": "", "id": "time", "x": 500, "y": 400, "click": False}]
        taps = []
        with mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch.object(phone_tools, "_fg", return_value="com.huawei.android.deskclock"), \
                mock.patch.object(screen_tools, "_dump", return_value=None), \
                mock.patch.object(screen_tools, "_elements", return_value=items), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda c, **k: taps.append(c) or ""), \
                mock.patch("time.sleep"):
            note = phone_tools._confirm_clock("ตั้งปลุก")
        self.assertIn("กดบันทึก", note)
        self.assertEqual(taps, [["input", "tap", "1000", "100"]])

    def test_clock_closed_means_nothing_to_press(self):
        import phone_tools
        with mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch.object(phone_tools, "_fg", return_value="com.aibot.assistant"), \
                mock.patch("time.sleep"):
            self.assertEqual(phone_tools._confirm_clock("ตั้งปลุก"), "")
