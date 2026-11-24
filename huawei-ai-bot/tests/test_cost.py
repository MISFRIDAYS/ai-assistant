"""ทดสอบระบบคุมค่าใช้จ่าย: งบรายวัน, เพดานตอบแชทแทน, เพดานซ่อมโค้ด"""
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


class TestDailyBudget(unittest.TestCase):
    def setUp(self):
        self._p = [mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()),
                   mock.patch.object(config, "DAILY_BUDGET_USD", 0.5),
                   mock.patch.object(config, "LLM_PROVIDER", "claude"),
                   mock.patch.object(config, "LLM_FALLBACK", "gemini"),
                   mock.patch.object(config, "GEMINI_API_KEY", "g")]
        for p in self._p:
            p.start()
        import agent
        agent._fallback_until[0] = 0.0

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_under_budget_keeps_claude(self):
        import agent, extras
        extras.record_usage("Claude", {"input_tokens": 1000, "output_tokens": 100})
        self.assertFalse(extras.over_budget())
        self.assertEqual(agent._active_provider(), "claude")

    def test_over_budget_switches_to_free(self):
        import agent, extras
        extras.record_usage("Claude", {"input_tokens": 400_000, "output_tokens": 50_000})   # ≈ $0.65
        self.assertTrue(extras.over_budget())
        self.assertEqual(agent._active_provider(), "gemini")
        with mock.patch.object(agent, "_call_provider", return_value=({"content": []}, "Gemini")) as cp:
            agent.call_llm([], [])
        self.assertEqual(cp.call_args[0][0], "gemini")

    def test_over_budget_without_free_keeps_working(self):
        import agent, extras
        extras.record_usage("Claude", {"input_tokens": 400_000, "output_tokens": 50_000})
        with mock.patch.object(config, "GEMINI_API_KEY", ""), mock.patch.object(config, "GROQ_API_KEY", ""), \
                mock.patch.object(config, "OLLAMA_URL", ""), mock.patch.object(config, "CLOUD_API_KEY", ""):
            self.assertEqual(agent._active_provider(), "claude")     # ไม่มีตัวฟรี → ไม่หยุดบอท

    def test_budget_zero_means_unlimited(self):
        import extras
        extras.record_usage("Claude", {"input_tokens": 5_000_000, "output_tokens": 0})
        with mock.patch.object(config, "DAILY_BUDGET_USD", 0):
            self.assertFalse(extras.over_budget())

    def test_free_usage_not_counted(self):
        import extras
        extras.record_usage("Gemini", {"input_tokens": 9_000_000, "output_tokens": 9_000_000})
        self.assertFalse(extras.over_budget())

    def test_repair_skips_claude_over_budget(self):
        import extras, self_heal
        extras.record_usage("Claude", {"input_tokens": 400_000, "output_tokens": 50_000})
        self.assertNotIn("claude", self_heal.repair_providers())


class TestCaps(unittest.TestCase):
    def test_autoreply_daily_cap(self):
        import autoreply
        autoreply._quota.update(day="", n=0, warned=False)
        with mock.patch.object(config, "AUTOREPLY_DAILY_MAX", 3):
            self.assertEqual([autoreply._ai_quota_ok() for _ in range(5)], [True, True, True, False, False])

    def test_repair_daily_cap(self):
        import self_heal
        self_heal._attempts.update(day="", n=0)
        with mock.patch.object(config, "REPAIR_DAILY_MAX", 2):
            self.assertEqual([self_heal._attempt_ok() for _ in range(3)], [True, True, False])

    def test_defaults(self):
        import agent, screen_task
        self.assertEqual(agent.MAX_STEPS, 15)
        self.assertEqual(screen_task.MAX_STEPS, 10)


if __name__ == "__main__":
    unittest.main()
