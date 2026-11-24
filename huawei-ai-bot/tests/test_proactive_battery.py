"""ผู้ช่วยเชิงรุก: เตือนแบตใกล้หมด / เครื่องร้อน เอง ครั้งเดียวต่อรอบ"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402


def _bat(pct, status="DISCHARGING", temp=30.0):
    return json.dumps({"percentage": pct, "status": status, "temperature": temp})


class TestBatteryAlerts(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp())
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _run(self, raw):
        import proactive, phone_tools
        with mock.patch.object(phone_tools, "battery_status", return_value=raw):
            return proactive.battery_alerts()

    def test_once_per_level_and_reset_on_charge(self):
        self.assertEqual(self._run(_bat(50)), [])
        a = self._run(_bat(19))
        self.assertEqual(len(a), 1)
        self.assertIn("19%", a[0])
        self.assertEqual(self._run(_bat(18)), [])                  # ไม่เตือนซ้ำ
        b = self._run(_bat(9))
        self.assertEqual(len(b), 1)
        self.assertIn("ใกล้หมดมาก", b[0])
        self.assertEqual(self._run(_bat(8)), [])
        self.assertEqual(self._run(_bat(30, "CHARGING")), [])     # เสียบชาร์จ → เริ่มนับใหม่
        self.assertEqual(len(self._run(_bat(20))), 1)

    def test_no_alert_while_charging(self):
        self.assertEqual(self._run(_bat(5, "CHARGING")), [])

    def test_hot(self):
        a = self._run(_bat(80, temp=44.0))
        self.assertEqual(len(a), 1)
        self.assertIn("44 องศา", a[0])
        self.assertEqual(self._run(_bat(80, temp=45.0)), [])       # ชั่วโมงเดียวกันไม่เตือนซ้ำ

    def test_off_and_bad_data(self):
        with mock.patch.dict(os.environ, {"PROACTIVE_BATTERY": "0"}):
            self.assertEqual(self._run(_bat(5)), [])
        self.assertEqual(self._run("ERROR: no termux"), [])

    def test_tick_includes_battery(self):
        import proactive, phone_tools
        with mock.patch.object(phone_tools, "battery_status", return_value=_bat(15)), \
                mock.patch.object(proactive, "event_alerts", return_value=[]), \
                mock.patch.object(proactive, "_now", return_value=__import__("datetime").datetime(2026, 11, 24, 15)), \
                mock.patch.object(config, "paused", return_value=False, create=True):
            msgs = proactive.tick()
        self.assertTrue(any("แบตเหลือ 15%" in m for m in msgs))
        proactive.pending_speech()


if __name__ == "__main__":
    unittest.main()
