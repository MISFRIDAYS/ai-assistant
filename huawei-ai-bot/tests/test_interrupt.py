"""คำถามค้างไม่แย่งคำสั่งใหม่ (send_confirm · appoint)"""
import os
import sys
import time
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import interrupt  # noqa: E402


class TestIsNewCommand(unittest.TestCase):
    def test_commands(self):
        for t in ("เข้าไปที่ instagram เข้าไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ",
                  "ส่งไลน์หาแม่ว่ากินข้าวยังครับ", "เปิดยูทูปแล้วเปิดเพลงให้หน่อย",
                  "โอเค ส่งข้อความหาแม่ในไลน์ว่าถึงแล้ว", "[10:00] ช่วยเปิดไลน์แล้วเข้าแชทเกตุหน่อย"):
            self.assertTrue(interrupt.is_new_command(t), t)

    def test_answers(self):
        for t in ("ภรรยาคนเจ็กในไอจีครับ", "อันแรก", "ใช่", "พรุ่งนี้บ่ายสามโมงถึงสี่โมงครับ",
                  "ประชุมลูกค้าที่บริษัทเรื่องงบประมาณ", "คุยเรื่องส่งข้อความหาลูกค้าทุกวัน",
                  "ส่งเคลมแล้วรอศูนย์ตอบกลับ", "เปลี่ยนจอและแบตเตอรี่ใหม่ เช็คลำโพงแล้ว"):
            self.assertFalse(interrupt.is_new_command(t), t)


class TestAppointYields(unittest.TestCase):
    def setUp(self):
        import appoint
        appoint._S.clear()

    def tearDown(self):
        import appoint
        appoint._S.clear()

    def test_new_command_drops_pending_appointment(self):
        import appoint
        appoint._S.update(kind="appt", data={}, ask="title", t=time.time())
        self.assertIsNone(appoint.handle_text("ส่งไลน์หาแม่ว่าเดี๋ยวโทรกลับนะครับ"))
        self.assertFalse(appoint.active())

    def test_answer_still_filled(self):
        import appoint
        appoint._S.update(kind="appt", data={}, ask="title", t=time.time())
        import agent
        with mock.patch.object(agent, "call_llm", side_effect=RuntimeError("offline")):
            r = appoint.handle_text("ประชุมลูกค้าที่บริษัทเรื่องงบประมาณ")
        self.assertIsNotNone(r)
        self.assertTrue(appoint.active())


if __name__ == "__main__":
    unittest.main()
