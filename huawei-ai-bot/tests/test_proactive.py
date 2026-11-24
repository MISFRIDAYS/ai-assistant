"""ผู้ช่วยเชิงรุก (สรุปเช้า · เตือนก่อนนัด · แชทค้าง) + รูทีนด้วยเสียง"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
os.environ.setdefault("SHARED_STORAGE", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import proactive  # noqa: E402
import routines  # noqa: E402

NOTIFS = [
    {"packageName": "jp.naver.line.android", "title": "แม่", "content": "กินข้าวยัง"},
    {"packageName": "jp.naver.line.android", "title": "แม่", "content": "โทรกลับด้วย"},
    {"packageName": "com.instagram.android", "title": "มิ้น", "content": "เย็นนี้ว่างไหม"},
    {"packageName": "com.android.systemui", "title": "USB", "content": "กำลังชาร์จ"},
]
NOW = datetime(2026, 11, 10, 7, 30)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = [mock.patch.object(config, "DATA_DIR", self.d), mock.patch.object(proactive, "_now", return_value=NOW)]
        for x in self.p:
            x.start()
        while not proactive._say_q.empty():
            proactive._say_q.get_nowait()

    def tearDown(self):
        for x in self.p:
            x.stop()


def _run_notifs(cmd, **k):
    return json.dumps(NOTIFS, ensure_ascii=False) if cmd[0] == "termux-notification-list" else ""


class TestUnread(_Tmp):
    def test_groups_by_person_and_skips_system(self):
        with mock.patch("phone_tools.run", side_effect=_run_notifs):
            got = proactive.unread()
        self.assertEqual([(u["title"], u["app"]) for u in got], [("แม่", "LINE"), ("มิ้น", "Instagram")])
        self.assertIn("กินข้าวยัง / โทรกลับด้วย", got[0]["content"])

    def test_who_said_what(self):
        with mock.patch("phone_tools.run", side_effect=_run_notifs):
            r = proactive.handle_text("ไลน์จากแม่ว่าอะไร")
            self.assertIn("โทรกลับด้วย", r)
            self.assertNotIn("มิ้น", r)
            r = proactive.handle_text("มิ้นทักมาว่าอะไร")
            self.assertIn("เย็นนี้ว่างไหม", r)
            r = proactive.handle_text("มีใครทักมาบ้าง")
            self.assertIn("แม่", r)
            self.assertIn("มิ้น", r)

    def test_reply_goes_to_person_just_read(self):
        with mock.patch("phone_tools.run", side_effect=_run_notifs), \
                mock.patch("notify_watch.remember_last") as rl:
            proactive.handle_text("มิ้นทักมาว่าอะไร")
        self.assertEqual(rl.call_args[0][0]["title"], "มิ้น")

    def test_not_about_chats(self):
        self.assertIsNone(proactive.handle_text("ในข่าวเขาบอกว่าอะไร"))
        self.assertIsNone(proactive.handle_text("อาจารย์บอกว่าอะไร"))


class TestAgenda(_Tmp):
    EVS = [{"title": "ประชุมโครงงาน", "start": NOW.replace(hour=10, minute=0), "allDay": False, "location": "ห้อง 301"},
           {"title": "ส่งเล่ม", "start": NOW.replace(hour=15, minute=30), "allDay": False, "location": ""}]

    def test_agenda_line(self):
        with mock.patch.object(proactive, "events", return_value=self.EVS):
            line = proactive.agenda_line(0)
        self.assertIn("2 นัด", line)
        self.assertIn("10:00 ประชุมโครงงาน ที่ ห้อง 301", line)

    def test_alert_once_before_event(self):
        soon = [{"title": "ประชุม", "start": NOW + timedelta(minutes=28), "allDay": False, "location": ""}]
        with mock.patch.object(proactive, "events", return_value=soon):
            a = proactive.event_alerts()
            b = proactive.event_alerts()
        self.assertEqual(len(a), 1)
        self.assertIn("อีก 28 นาที", a[0])
        self.assertEqual(b, [])

    def test_morning_briefing_once_and_spoken(self):
        with mock.patch.object(proactive, "events", return_value=self.EVS), \
                mock.patch("info.weather", return_value="🌤️ กรุงเทพ 31°C โอกาสฝน 20%"), \
                mock.patch("phone_tools.run", side_effect=_run_notifs), \
                mock.patch.object(config, "paused", return_value=False):
            first = proactive.tick()
            second = proactive.tick()
        self.assertEqual(len(first), 1)
        self.assertIn("อรุณสวัสดิ์", first[0])
        self.assertIn("ประชุมโครงงาน", first[0])
        self.assertIn("แม่ (LINE)", first[0])
        self.assertEqual(second, [])
        with mock.patch("notify_watch._quiet_now", return_value=False):
            spoken = proactive.pending_speech()
        self.assertEqual(len(spoken), 1)
        self.assertNotIn("📅", proactive.spoken(spoken[0]))

    def test_quiet_hours_no_speech(self):
        proactive._say_q.put((__import__("time").time(), "⏰ อีก 30 นาทีมีนัด"))
        with mock.patch("notify_watch._quiet_now", return_value=True):
            self.assertEqual(proactive.pending_speech(), [])

    def test_appointments_question_uses_phone_calendar(self):
        import appoint
        with mock.patch.object(appoint, "connected", return_value=False), \
                mock.patch.object(proactive, "events", return_value=self.EVS):
            r = appoint.list_events("วันนี้มีนัดอะไรบ้าง")
        self.assertIn("ประชุมโครงงาน", r)


class TestRoutines(_Tmp):
    def test_create_and_list(self):
        r = routines.handle_text("สร้างรูทีน อ่านหนังสือ: เปิดโหมดห้ามรบกวน แล้ว จับเวลา 25 นาที")
        self.assertIn("2 ขั้น", r)
        self.assertEqual(routines.load()["อ่านหนังสือ"], ["เปิดโหมดห้ามรบกวน", "จับเวลา 25 นาที"])
        self.assertIn("อ่านหนังสือ", routines.handle_text("มีรูทีนอะไรบ้าง"))

    def test_teach_by_sentence(self):
        routines.handle_text("จำไว้นะ ถ้าบอกว่า ถึงบ้าน ให้ เปิดไวไฟ แล้วก็ เปิดเพลงสบายๆ")
        self.assertEqual(routines.load()["ถึงบ้าน"], ["เปิดไวไฟ", "เปิดเพลงสบายๆ"])

    def test_run_by_name(self):
        done = []
        with mock.patch.object(routines, "_do_step", side_effect=lambda s, c: done.append(s) or f"{s} แล้ว"):
            r = routines.handle_text("โหมดออกจากบ้าน")
        self.assertEqual(done, routines.DEFAULTS["ออกจากบ้าน"])
        self.assertIn("3/3", r)
        with mock.patch.object(routines, "_do_step", return_value="ok") as st:
            routines.handle_text("ถึงบ้านแล้ว")
        self.assertEqual(st.call_count, 2)

    def test_not_a_routine(self):
        with mock.patch.object(routines, "_do_step") as st:
            for t in ["เปิดโหมดห้ามรบกวน", "นอน", "ทำงานอยู่", "โหมดมืด", "วันนี้ไปทำงานไหม"]:
                self.assertIsNone(routines.handle_text(t), t)
        st.assert_not_called()

    def test_failed_step_is_marked(self):
        with mock.patch.object(routines, "_do_step", side_effect=["ok", "ERROR: ไม่มีสิทธิ์", "ok"]):
            r = routines.run("ออกจากบ้าน")
        self.assertIn("2/3", r)
        self.assertIn("✕ วันนี้มีนัดอะไรบ้าง", r)

    def test_delete(self):
        self.assertIn("ลบรูทีน", routines.handle_text("ลบรูทีน ทำงาน"))
        self.assertNotIn("ทำงาน", routines.load())

    def test_default_steps_run_without_ai(self):
        """ขั้นของรูทีนเริ่มต้นต้องทำได้ด้วยคำสั่งด่วน (เร็ว ไม่เสียค่า AI)"""
        import quick
        for step in ["เปิดโหมดห้ามรบกวน", "ปิดโหมดห้ามรบกวน", "ลดแสงจอ", "เปิดไวไฟ", "แบตเหลือเท่าไหร่"]:
            self.assertTrue(quick.handle(step, None), step)


if __name__ == "__main__":
    unittest.main()
