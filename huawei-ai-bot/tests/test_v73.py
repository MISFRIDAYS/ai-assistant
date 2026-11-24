"""v73: แก้สั่งงานด้วยเสียง — ส่งข้อความเพี้ยน · เรียกไม่ตอบ · ฟังผิด · ช้า/ค้าง"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
os.environ.setdefault("SHARED_STORAGE", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

# คำใบ้แบบที่เครื่องจริงส่งให้ Whisper (คำปลุก + ชื่อคนที่คุยล่าสุด)
PROMPT = "สวัสดีผู้ช่วย, Heart, Wanchaporn Panprasit, ภรรยา(คนเจก), เกตุ, แม่"
INCIDENT = ("เข้าไปที่แอปไลน์ เข้าไปที่แชท เกตุ พิมพ์ สวัสดีผู้ช่วย Heart, Wanchaporn Panprasit, "
            "ภรรยา สันทร์ ภรรยา สันทร์ ภรรยา สันทร์")
GARBAGE = "สวัสดีผู้ช่วย Heart, Wanchaporn Panprasit, ภรรยา สันทร์ ภรรยา สันทร์ ภรรยา สันทร์"


class TestEchoDetection(unittest.TestCase):
    def test_incident_is_flagged(self):
        import voice
        self.assertTrue(voice.is_hallucination(INCIDENT, PROMPT))
        self.assertTrue(voice.prompt_echo(GARBAGE, PROMPT))

    def test_old_prompt_format_too(self):
        import voice
        old = "สวัสดีผู้ช่วย Heart, Wanchaporn Panprasit, ภรรยา(คนเจก), เกตุ, แม่"   # ไม่มีจุลภาคหลังคำปลุก
        self.assertTrue(voice.prompt_echo(GARBAGE, old))

    def test_bare_wake_word_is_kept(self):
        import voice
        for t in ("ผู้ช่วย", "สวัสดีผู้ช่วย", "เฮ้ผู้ช่วย", "เฮ้ย ผู้ช่วย"):
            self.assertFalse(voice.is_hallucination(t, PROMPT), t)

    def test_real_commands_are_kept(self):
        import voice
        for t in ("เฮ้ผู้ช่วย ส่งไลน์หาเกตุว่ากินข้าวยัง", "เข้าไปที่แชท ภรรยาคนเจก", "บอกแม่กับเกตุว่าถึงบ้านแล้ว",
                  "เปิด youtube", "ส่งข้อความหาแม่ว่ากินข้าวยัง"):
            self.assertFalse(voice.is_hallucination(t, PROMPT), t)

    def test_trailing_bad_segment_is_trimmed(self):
        import voice
        segs = [{"text": "ส่งไลน์หาเกตุว่ากินข้าวยัง", "no_speech_prob": 0.05, "avg_logprob": -0.2},
                {"text": GARBAGE, "no_speech_prob": 0.1, "avg_logprob": -0.4}]
        text = segs[0]["text"] + " " + GARBAGE
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()):
            out = voice._judge(text, segs, PROMPT, "Groq")
        self.assertEqual(out, "ส่งไลน์หาเกตุว่ากินข้าวยัง")

    def test_prompt_keeps_whole_names(self):
        import voice
        import skills
        names = ["ภรรยา(คนเจก)", "Wanchaporn Panprasit", "เกตุ", "แม่", "x" * 70]
        with mock.patch.object(skills, "known_names", return_value=names):
            p = voice._stt_prompt()
        self.assertTrue(p.startswith(config.STT_PROMPT + ", "))
        for part in p.split(", ")[1:]:
            self.assertIn(part, names)                     # ไม่ตัดกลางชื่อ
        self.assertLessEqual(len(p), len(config.STT_PROMPT) + 2 + 60)

    def test_message_echo(self):
        import voice
        with mock.patch.object(voice, "_stt_prompt", return_value=PROMPT):
            self.assertTrue(voice.message_echo(GARBAGE))
            self.assertFalse(voice.message_echo("กินข้าวยัง"))
            self.assertFalse(voice.message_echo("พรุ่งนี้จะเข้าไปที่เทศบาล ต้องการเอกสารอะไรเพิ่มมั้ยครับ"))


class TestNeverSendEcho(unittest.TestCase):
    def test_send_dm_refuses_echo(self):
        import share_tools
        import voice
        with mock.patch.object(voice, "_stt_prompt", return_value=PROMPT), \
                mock.patch.object(share_tools, "_send_dm") as sd, \
                mock.patch.object(share_tools, "_reply_via_notification") as rn:
            r = share_tools.send_dm({"app": "line", "to": "เกตุ", "text": GARBAGE}, None)
        self.assertTrue(r.startswith("ERROR"))
        sd.assert_not_called()
        rn.assert_not_called()

    def test_send_here_and_reply_last_refuse_echo(self):
        import share_tools
        import voice
        with mock.patch.object(voice, "_stt_prompt", return_value=PROMPT), \
                mock.patch.object(share_tools, "last_sender", return_value={"app": "line", "to": "เกตุ", "key": "k"}):
            self.assertTrue(share_tools.send_here(GARBAGE).startswith("ERROR"))
            self.assertIn("ยังไม่ได้ส่ง", share_tools.reply_last(GARBAGE))


class _AppVoiceCtx:
    """เหมือน AppCtx ของแอป ตอนสั่งผ่านปุ่มไมค์ (android_main.chat(text, voice=True))"""
    chat_id = "app"
    hold = False

    def __init__(self):
        self.voice = self.via_voice = True
        self.asked = []

    def confirm(self, d):
        self.asked.append(d)
        return True

    def status(self, t):
        pass


class TestVoiceAlwaysConfirms(unittest.TestCase):
    def setUp(self):
        import contacts
        import send_confirm
        send_confirm._P.clear()
        self.old = contacts._PATH, contacts._db["d"]
        contacts._PATH = os.path.join(tempfile.mkdtemp(), "c.json")
        contacts._db["d"] = {}

    def tearDown(self):
        import contacts
        import send_confirm
        contacts._PATH, contacts._db["d"] = self.old
        send_confirm._P.clear()

    def test_app_mic_button_reads_back(self):
        import quick
        import send_confirm
        import share_tools
        ctx = _AppVoiceCtx()
        self.assertTrue(send_confirm._is_voice(ctx))
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว ✅") as sd:
            q = quick._do_send("line", "เกตุ", "กินข้าวยัง", ctx)
            self.assertIn("ใช่ไหม", q)
            sd.assert_not_called()
            send_confirm.handle_text("ใช่", ctx)
        sd.assert_called_once()
        self.assertIsNone(getattr(ctx, "send_ok", None))          # ยืนยันใช้ได้ครั้งเดียว

    def test_confirmed_send_not_asked_twice(self):
        import permissions
        ctx = _AppVoiceCtx()
        self.assertTrue(permissions.need_confirm(ctx, "message"))
        ctx.send_ok = "กินข้าวยัง"
        self.assertFalse(permissions.need_confirm(ctx, "message"))

    def test_router_send_message_reads_back_for_voice(self):
        import router
        import share_tools
        ctx = _AppVoiceCtx()
        d = {"intent": "send_message", "app": "line", "to": "เกตุ", "text": "กินข้าวยัง",
             "_said": "ส่งไลน์หาเกตุว่ากินข้าวยัง"}
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว") as sd:
            r = router.execute(d, ctx)
        self.assertIn("ใช่ไหม", r)
        sd.assert_not_called()


class TestChatNavigation(unittest.TestCase):
    def test_goto_then_type_is_a_send(self):
        import social
        with mock.patch.object(social, "goto_chat") as g:
            self.assertIsNone(social.handle_text("เข้าไปที่แชท เกตุ พิมพ์ กินข้าวยัง"))
            self.assertIsNone(social.handle_text("เปิดไลน์แล้วเข้าแชท เกตุ แล้วพิมพ์ว่า กินข้าวยัง"))
        g.assert_not_called()

    def test_goto_then_type_nothing_opens_and_asks(self):
        import social
        with mock.patch.object(social, "goto_chat", return_value="💬 เข้าแชท เกตุ ใน line แล้ว") as g:
            r = social.handle_text("เข้าไปที่แอปไลน์ เข้าไปที่แชท เกตุ พิมพ์")
        self.assertEqual(g.call_args[0][:2], ("เกตุ", "line"))
        self.assertIn("พิมพ์ว่าอะไร", r)

    def test_plain_goto_still_works(self):
        import social
        with mock.patch.object(social, "goto_chat", return_value="ok") as g:
            social.handle_text("เข้าไปที่แชท ภรรยาคนเจก")
            social.handle_text("เข้าไปที่แอปไลน์ เข้าไปที่แชท เกตุ")
        self.assertEqual(g.call_args_list[0][0][0], "ภรรยาคนเจก")
        self.assertEqual(g.call_args_list[1][0][:2], ("เกตุ", "line"))


class TestNameMatch(unittest.TestCase):
    @staticmethod
    def _e(t):
        return {"text": t, "desc": "", "edit": False, "id": ""}

    def test_prefers_full_name(self):
        import share_tools as st
        r = st._find_name([self._e("ภรรยา"), self._e("ภรรยา(คนเจก)")], "ภรรยาคนเจก")
        self.assertEqual(r["text"], "ภรรยา(คนเจก)")

    def test_app_label_is_not_a_person(self):
        import share_tools as st
        self.assertIsNone(st._find_name([self._e("LINE"), self._e("ส่ง")], "เกตุ พิมพ์ กินข้าวยัง line"))

    def test_fuzzy_still_works(self):
        import share_tools as st
        self.assertEqual(st._find_name([self._e("Heart"), self._e("แม่")], "HART")["text"], "Heart")


class TestYesNo(unittest.TestCase):
    def test_own_prompt_is_not_an_answer(self):
        import voice_chat
        self.assertIsNone(voice_chat.yes_or_no("ขอยืนยันก่อนนะครับ จะส่งหาเกตุ"))
        self.assertIsNone(voice_chat.yes_or_no("จะส่งหา เกตุ ใน LINE ว่า กินข้าวยัง ใช่ไหมครับ"))

    def test_short_polite_word_is_yes(self):
        import voice_chat
        self.assertTrue(voice_chat.yes_or_no("ครับ"))
        self.assertTrue(voice_chat.yes_or_no("ค่ะ"))
        self.assertIsNone(voice_chat.yes_or_no("วันนี้อากาศดีนะครับ"))


class TestMicRecovery(unittest.TestCase):
    def test_noise_is_capped(self):
        import audio_stream
        m = audio_stream.AndroidMic.__new__(audio_stream.AndroidMic)
        m.noise = 40.0
        for _ in range(200):
            m._track_noise(300.0)                      # ทีวี/พัดลมดังต่อเนื่อง
        self.assertLessEqual(m.noise, 120.0)
        m.speech_peak = 200.0                           # เสียงพูดล่าสุดเบา (ไมค์ใหม่เสียงเบาลง)
        for _ in range(20):
            m._track_noise(300.0)
        self.assertLessEqual(m.noise, 70.0)
        self.assertLess(max(m.noise * 2.8, config.VAD_MIN_RMS), 200.0)   # เสียงพูดยังผ่านเกณฑ์

    def test_zero_frames_do_not_count(self):
        import audio_stream
        m = audio_stream.MicStream.__new__(audio_stream.MicStream)
        m.noise = 50.0
        for _ in range(100):
            m._track_noise(0.0)
        self.assertEqual(m.noise, 50.0)

    def test_restart_revives_dead_reader(self):
        import audio_stream

        class B:
            def __init__(self):
                self.started = 0

            def micStop(self):
                pass

            def micStart(self):
                self.started += 1
                return True

            def micError(self):
                return ""

            def micAllowed(self):
                return True

            def micRead(self, n):
                time.sleep(0.01)
                return b"\x01\x00" * 480

            def micFlush(self):
                pass

        m = audio_stream.AndroidMic.__new__(audio_stream.AndroidMic)
        m.b, m.proc, m.closed, m.owner, m.peak = B(), None, False, None, 0.0
        m.dead = "ไมค์ถูกปิดสิทธิ์"
        m._rt = threading.Thread(target=lambda: None)
        m._rt.start()
        m._rt.join()
        m.noise = 300.0
        self.assertTrue(m.reader_dead())
        with mock.patch.object(audio_stream.time, "sleep"):
            self.assertTrue(m.restart())
        self.assertFalse(m.reader_dead())
        self.assertEqual(m.noise, 40.0)
        m.close()


class TestSttEngineBackoff(unittest.TestCase):
    def test_off_map_is_saved(self):
        import voice
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d):
            o = voice._OffMap()
            o["cloudflare"] = time.time() + 3600
            again = voice._OffMap().load()
        self.assertIn("cloudflare", again)
        with open(os.path.join(d, "stt_off.json"), encoding="utf-8") as f:
            self.assertIn("cloudflare", json.load(f))

    def test_groq_does_not_wait_long(self):
        import groq_client
        r = mock.Mock(status_code=429, text="Rate limit. Please try again in 20.5s")
        sess = mock.Mock()
        sess.post.return_value = r
        with mock.patch.object(groq_client, "_session", return_value=sess), \
                mock.patch.object(groq_client.time, "sleep") as sl:
            with self.assertRaises(groq_client.GroqError):
                groq_client._post({"model": "x"})
        sl.assert_not_called()


class TestHighpass(unittest.TestCase):
    def test_numpy_matches_loop(self):
        import array
        import math
        import voice
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("ไม่มี numpy")
        pcm = array.array("h", [int(3000 * math.sin(i / 7)) for i in range(5000)]).tobytes()
        fast = voice.highpass(pcm)
        with mock.patch.object(voice, "_highpass_np", side_effect=ImportError):
            slow = voice.highpass(pcm)
        a, b = array.array("h", fast), array.array("h", slow)
        self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 1)


if __name__ == "__main__":
    unittest.main()
