"""v74: สั่ง 'เข้า instagram … ส่งข้อความ' แล้วไปส่งใน LINE · เปิดแอปไม่ขึ้นแต่ทำต่อ · สถิติคำสั่งด่วน · ไมค์ปิด"""
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
os.environ.setdefault("SHARED_STORAGE", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

CMD = "เข้าไปที่ instagram เข้าไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ"
TYPO = "เข้า instragram ไปที่แชท ภรรยาคนเจ็ก ส่งข้อความ สวัสดีฉัน Jamal เองครับ"
BOOK = {"ภรรยาคนเจ็ก": {"name": "ภรรยาคนเจ็ก", "apps": {"line": 5}, "last": "line", "t": 2},
        "ภรรยา(คนเจก)": {"name": "ภรรยา(คนเจก)", "apps": {"line": 3}, "last": "line", "t": 1}}


def _book():
    import contacts
    return {contacts.norm(k): v for k, v in BOOK.items()}


class TestPendingQuestionDoesNotHijack(unittest.TestCase):
    def setUp(self):
        import send_confirm
        send_confirm._P.clear()

    def tearDown(self):
        import send_confirm
        send_confirm._P.clear()

    def _run(self, text):
        import quick, share_tools, contacts
        with mock.patch.object(contacts, "_load", side_effect=_book), \
                mock.patch.object(contacts, "app_for", return_value="line"), \
                mock.patch.object(share_tools, "send_dm", return_value="ERROR: stub") as sd:
            quick.handle(text, None)
        return sd

    def test_pick_pending_then_new_instagram_command(self):
        import send_confirm
        send_confirm._P.update(kind="pick", opts=[("ภรรยาคนเจ็ก", "line"), ("ภรรยา(คนเจก)", "line")],
                               msg="ข้อความเก่า", voice=False, t=time.time())
        sd = self._run(CMD)
        sd.assert_called_once()
        a = sd.call_args[0][0]
        self.assertEqual(a["app"], "instagram")
        self.assertEqual(a["text"], "สวัสดีฉัน Jamal เองครับ")

    def test_confirm_pending_then_new_command(self):
        import send_confirm
        send_confirm._P.update(kind="confirm", app="line", to="ภรรยาคนเจ็ก", msg="เก่า", t=time.time())
        self.assertIsNone(send_confirm.handle_text(CMD))
        self.assertFalse(send_confirm.active())

    def test_short_answers_still_work(self):
        import send_confirm
        opts = [("ภรรยาคนเจ็ก", "line"), ("ภรรยา(คนเจก)", "line")]
        self.assertEqual(send_confirm._pick("อันแรก", opts), ("ภรรยาคนเจ็ก", "line"))
        self.assertEqual(send_confirm._pick("ภรรยาคนเจ็กในไอจี", opts), ("ภรรยาคนเจ็ก", "instagram"))
        self.assertFalse(send_confirm._new_command("ภรรยาคนเจ็กครับ"))
        self.assertTrue(send_confirm._new_command(CMD))

    def test_misspelled_instagram(self):
        sd = self._run(TYPO)
        self.assertEqual(sd.call_args[0][0]["app"], "instagram")

    def test_app_key(self):
        import quick
        for w in ("instragram", "instagam", "instgram", "intagram", "Instagram", "ไอจี", "insta"):
            self.assertEqual(quick.app_key(w), "instagram", w)
        for w in ("line", "telegram", "messenger"):
            self.assertEqual(quick.app_key(w), w)


class TestAppMustReallyOpen(unittest.TestCase):
    def test_send_dm_stops_on_home_screen(self):
        import share_tools, screen_tools, phone_tools
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), mock.patch("time.sleep"), \
                mock.patch.object(share_tools, "_adb", return_value=True), \
                mock.patch.object(share_tools, "_current_chat", return_value=None), \
                mock.patch.object(share_tools, "_reply_via_notification", return_value=None), \
                mock.patch.object(screen_tools, "adb_shell", return_value="ok"), \
                mock.patch.object(phone_tools, "_fg", return_value="com.huawei.android.launcher"), \
                mock.patch.object(phone_tools, "open_app", return_value="เปิด line แล้ว") as oa, \
                mock.patch.object(share_tools, "_pick_recipient") as pr:
            res = share_tools.send_dm({"app": "line", "to": "ภรรยาคนเจ็ก", "text": "สวัสดี"}, None)
        self.assertTrue(res.startswith("ERROR: เปิด line ไม่ขึ้น"), res)
        self.assertNotIn("เข้าหน้าแชท", res)
        self.assertEqual(oa.call_count, 2)                     # ลองเปิดซ้ำ 1 ครั้ง
        pr.assert_not_called()

    def test_send_dm_continues_when_app_is_up(self):
        import share_tools, screen_tools, phone_tools
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), mock.patch("time.sleep"), \
                mock.patch.object(share_tools, "_adb", return_value=True), \
                mock.patch.object(share_tools, "_current_chat", return_value=None), \
                mock.patch.object(share_tools, "_reply_via_notification", return_value=None), \
                mock.patch.object(share_tools, "_visible_names", return_value=[]), \
                mock.patch.object(screen_tools, "adb_shell", return_value="ok"), \
                mock.patch.object(phone_tools, "_fg", return_value="jp.naver.line.android"), \
                mock.patch.object(phone_tools, "open_app", return_value="เปิด line แล้ว") as oa, \
                mock.patch.object(share_tools, "_pick_recipient", return_value=None) as pr:
            res = share_tools.send_dm({"app": "line", "to": "ภรรยาคนเจ็ก", "text": "สวัสดี"}, None)
        self.assertEqual(oa.call_count, 1)
        pr.assert_called_once()
        self.assertIn("หาคนชื่อ", res)

    def test_still_home(self):
        import phone_tools
        with mock.patch.object(phone_tools, "_fg", return_value="com.huawei.android.launcher"):
            self.assertTrue(phone_tools.still_home())
        for fg in (None, "com.instagram.android", "com.gbox.android"):
            with mock.patch.object(phone_tools, "_fg", return_value=fg):
                self.assertFalse(phone_tools.still_home(), fg)

    def test_launch_fresh_blocked_falls_back_to_am_start(self):
        import phone_tools, android_shim
        br = mock.Mock()
        br.launchFresh.return_value = True
        sh = mock.Mock(return_value="Starting: Intent")
        fg = lambda: "jp.naver.line.android" if sh.called else "com.huawei.android.launcher"   # noqa: E731
        with mock.patch.object(config, "ANDROID_APP", True), mock.patch("time.sleep"), \
                mock.patch.object(android_shim, "bridge", return_value=br), \
                mock.patch.object(phone_tools, "_launcher_components",
                                  return_value=["jp.naver.line.android/.Main"]), \
                mock.patch.object(phone_tools, "_fg", side_effect=fg), \
                mock.patch("screen_tools.adb_serial", return_value="x"), \
                mock.patch.object(phone_tools, "_sh", sh):
            res = phone_tools._open_app({"app": "line", "page": "chat"}, None)
        self.assertFalse(res.startswith("ERROR"), res)
        self.assertEqual(sh.call_args[0][0][:2], ["am", "start"])


class TestPerf(unittest.TestCase):
    def test_summary_no_resource_warning_and_quick_row(self):
        import perf
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d):
            perf.record("quick", "สรุปผลทดสอบ", total=0.1, ok=True)
            perf.record("chat", "ถามอะไรสักอย่าง", total=6.0, ok=True)
            with open(os.path.join(d, "app_test.json"), "w", encoding="utf-8") as f:
                json.dump({"at": "x", "rows": [{"app": "โน้ต", "ok": True}]}, f)
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                out = perf.summary(7)
        self.assertIn("คำสั่งด่วน: กลาง 0.1", out)
        self.assertIn("จบทั้งหมด: กลาง 6.0", out)

    def test_agent_marks_quick(self):
        import agent, quick
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), \
                mock.patch.object(config, "QUICK_COMMANDS", True), \
                mock.patch.object(quick, "handle", return_value="ok"):
            agent.LAST_QUICK[0] = 0.0
            r = agent._quick("app", [], {"type": "text", "text": "[t]"}, [{"type": "text", "text": "x"}], None)
        self.assertEqual(r, "ok")
        self.assertGreater(agent.LAST_QUICK[0], 0.0)


class TestMicClosed(unittest.TestCase):
    def test_conversation_ends_quietly(self):
        import voice_chat
        err = RuntimeError("ไมค์หยุดส่งเสียง: ปิดไมค์แล้ว")
        self.assertTrue(voice_chat.mic_closed(err))
        self.assertFalse(voice_chat.mic_closed(RuntimeError("อย่างอื่น")))
        with mock.patch.object(voice_chat, "listen_text", side_effect=err):
            self.assertIsNone(voice_chat.conversation(mock.Mock(), first_text=None))

    def test_other_errors_still_raise(self):
        import voice_chat
        with mock.patch.object(voice_chat, "listen_text", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                voice_chat.conversation(mock.Mock(), first_text=None)


if __name__ == "__main__":
    unittest.main()
