"""ทดสอบระบบโดยจำลอง Telegram + Claude API + มือถือ (รัน: python -m unittest discover tests)"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("HUMAN_TYPING", "0")
os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "SHARED_STORAGE": tempfile.mkdtemp(),
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
config.DATA_DIR = tempfile.mkdtemp()
config.QUICK_COMMANDS = False      # เทสต์ทั่วไปทดสอบเส้นทาง AI — คำสั่งด่วนมีเทสต์แยกใน TestQuick
config.ROUTER = False              # ตัวแยกเจตนามีเทสต์แยกใน TestRouter
import agent  # noqa: E402
import bot  # noqa: E402
import telegram_api  # noqa: E402


class FakeResp:
    def __init__(self, data, code=200):
        self._d, self.status_code, self.text = data, code, str(data)

    def json(self):
        return self._d

    def iter_lines(self, decode_unicode=True):
        """จำลอง SSE สตรีมจากคำตอบปกติ"""
        import json as _j
        yield "data: " + _j.dumps({"type": "message_start", "message": {"usage": {}}})
        for i, b in enumerate(self._d["content"]):
            if b["type"] == "text":
                yield "data: " + _j.dumps({"type": "content_block_start", "index": i,
                                           "content_block": {"type": "text", "text": ""}})
                yield "data: " + _j.dumps({"type": "content_block_delta", "index": i,
                                           "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                yield "data: " + _j.dumps({"type": "content_block_start", "index": i,
                                           "content_block": dict(b, input={})})
                yield "data: " + _j.dumps({"type": "content_block_delta", "index": i, "delta": {
                    "type": "input_json_delta", "partial_json": _j.dumps(b.get("input", {}))}})
            yield "data: " + _j.dumps({"type": "content_block_stop", "index": i})
        yield "data: " + _j.dumps({"type": "message_delta", "delta": {"stop_reason": self._d["stop_reason"]}})


def claude_seq(*responses):
    calls = []
    it = iter(responses)

    def fake_post(*args, headers=None, json=None, timeout=None, stream=False):
        import copy
        calls.append(copy.deepcopy(json))
        return FakeResp(next(it))
    return fake_post, calls


class FakeTG:
    def __init__(self, auto_answer=None):
        self.sent, self.auto = [], auto_answer

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(text)
        if reply_markup and self.auto is not None:
            pid = reply_markup["inline_keyboard"][0][0]["callback_data"].split(":")[1]
            act = "ok" if self.auto else "no"
            threading.Timer(0.1, bot.handle_callback,
                            args=({"id": "c", "data": f"{act}:{pid}", "from": {"id": 111}},)).start()
        return {"message_id": len(self.sent)}

    def edit_message_text(self, *a, **k):
        self.sent.append("EDIT:" + a[2])

    def send_chat_action(self, *a): pass
    def answer_callback(self, *a): pass
    def send_photo(self, *a): pass

    def send_voice(self, chat_id, path):
        self.sent.append("VOICE:" + path)

    def download_file(self, fid):
        return b"OggS-mock", "voice/file_1.oga"


def msg(text, uid=111, chat=111):
    return {"chat": {"id": chat}, "from": {"id": uid}, "text": text}


class TestBot(unittest.TestCase):
    def setUp(self):
        agent.reset_history(111)

    def test_tool_call_battery(self):
        fake, calls = claude_seq(
            {"stop_reason": "tool_use", "content": [
                {"type": "text", "text": "ขอเช็คก่อนนะ"},
                {"type": "tool_use", "id": "t1", "name": "battery_status", "input": {}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "แบตเหลือ **78%** ครับ"}]},
        )
        bot.tg = FakeTG()
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("แบตเหลือเท่าไหร่"))
        self.assertIn("78%", bot.tg.sent[-1])
        tr = calls[1]["messages"][-1]["content"][0]
        self.assertEqual(tr["type"], "tool_result")
        self.assertIn("percentage", tr["content"])
        self.assertTrue(any(t.get("name") == "web_search" for t in calls[0]["tools"]))

    def test_dangerous_approved(self):
        fake, calls = claude_seq(
            {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "send_sms", "input": {"number": "0812345678", "text": "ถึงแล้ว"}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ส่งแล้วครับ"}]},
        )
        bot.tg = FakeTG(auto_answer=True)
        with mock.patch.object(config, "DISABLED_TOOLS", set()), \
                mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("ส่ง sms หาแม่ว่าถึงแล้ว"))
        res = calls[1]["messages"][-1]["content"][0]
        self.assertFalse(res.get("is_error"))
        # ส่งข้อความ = ทำได้เลย (AUTO_SEND) ไม่ต้องถาม
        self.assertFalse(any("ขออนุญาต" in s for s in bot.tg.sent))

    def test_hold_requires_confirm(self):
        fake, calls = claude_seq(
            {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "send_sms", "input": {"number": "0812345678", "text": "x"}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "รอคำสั่งครับ"}]},
        )
        bot.tg = FakeTG(auto_answer=False)
        with mock.patch.object(config, "DISABLED_TOOLS", set()), \
                mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("พิมพ์ sms หาแม่ว่า x แต่รอฟังคำสั่งก่อนส่งนะ"))
        self.assertTrue(any("ขออนุญาต" in s for s in bot.tg.sent))
        self.assertTrue(calls[1]["messages"][-1]["content"][0]["is_error"])

    def test_dangerous_denied(self):
        fake, calls = claude_seq(
            {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "run_shell", "input": {"command": "ls"}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ยกเลิกแล้วครับ"}]},
        )
        bot.tg = FakeTG(auto_answer=False)
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("ลอง ls"))
        self.assertTrue(calls[1]["messages"][-1]["content"][0]["is_error"])

    def test_unauthorized(self):
        bot.tg = FakeTG()
        with mock.patch("claude_client.requests.Session.post") as p:
            bot.handle_message(msg("hi", uid=999, chat=999))
            p.assert_not_called()
        self.assertIn("999", bot.tg.sent[-1])

    def test_history_and_citations(self):
        fake, calls = claude_seq(
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "สวัสดีครับ"}]},
            {"stop_reason": "end_turn", "content": [
                {"type": "text", "text": "ข่าว", "citations": [{"url": "https://example.com/a"}]}]},
        )
        bot.tg = FakeTG()
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("สวัสดี"))
            bot.handle_message(msg("ข่าววันนี้"))
        self.assertEqual(len(calls[1]["messages"]), 3)  # user, assistant, user
        self.assertIn("https://example.com/a", bot.tg.sent[-1])

    def test_reminder(self):
        bot.tg = FakeTG()
        bot.add_reminder(111, -1, "กินยา")
        t = threading.Thread(target=bot.reminder_loop, daemon=True)
        t.start()
        t.join(0.5)
        self.assertTrue(any("กินยา" in s for s in bot.tg.sent))

    def test_trim_keeps_valid_start(self):
        h = [{"role": "user", "content": "a"},
             {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "x", "input": {}}]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "r"}]},
             {"role": "assistant", "content": [{"type": "text", "text": "b"}]}]
        with mock.patch.object(config, "MAX_HISTORY", 3):
            out = agent.trim_history(list(h))
        self.assertTrue(agent._is_plain_user(out[0]) if out else True)

    def test_md_html(self):
        self.assertEqual(telegram_api.md_to_html("**a** <b> `c`"), "<b>a</b> &lt;b&gt; <code>c</code>")

    def test_all_tools_run_in_mock(self):
        ctx = bot.Ctx(111)
        bot.tg = FakeTG(auto_answer=True)
        samples = {"send_sms": {"number": "1", "text": "x"}, "make_call": {"number": "1"},
                   "find_contact": {"query": "แม่"}, "torch": {"on": True},
                   "set_volume": {"stream": "music", "volume": 5}, "set_brightness": {"level": "100"},
                   "speak": {"text": "hi"}, "show_notification": {"content": "x"},
                   "set_clipboard": {"text": "x"}, "open_url": {"url": "https://a.com"},
                   "open_app": {"app": "line"}, "set_alarm": {"hour": 7, "minute": 0},
                   "remind_me": {"minutes": 5, "text": "x"}, "run_shell": {"command": "echo"},
                   "adb_connect": {"port": "37000"}, "tap": {"x": 1, "y": 2}, "tap_text": {"text": "ส่ง"},
                   "type_text": {"text": "สวัสดีครับ"}, "press_key": {"key": "back"},
                   "swipe": {"direction": "up"},
                   "share_text": {"app": "line", "text": "ถึงบ้านแล้ว"}, "close_app": {"app": "line"},
                   "remember": {"text": "แม่ชื่อสมศรี"}, "forget": {"query": "ไม่มีเรื่องนี้"},
                   "schedule": {"time": "07:00", "text": "สรุปข่าว", "kind": "task", "repeat": "daily"},
                   "cancel_schedule": {"id_or_text": "สรุปข่าว"},
                   "wifi": {"on": True}, "bluetooth": {"on": False}, "airplane_mode": {"on": False},
                   "mobile_data": {"on": True}, "brightness": {"level": "50%"},
                   "rotate_screen": {"auto": True}, "screen_timeout": {"seconds": 60},
                   "open_panel": {"which": "notifications"}, "press_button": {"button": "home"},
                   "do_not_disturb": {"on": False}, "screen_record": {"seconds": 5},
                   "tap_visual": {"target": "ปุ่มส่ง"}}
        import phone_tools
        for name, (fn, _, _, _) in phone_tools.TOOLS.items():
            if name in ("video_info", "edit_video", "screen_task"):    # ทดสอบแยก
                continue
            r = fn(samples.get(name, {}), ctx)
            self.assertTrue(r, name)
        self.assertIn("แม่", phone_tools.find_contact({"query": "แม่"}, ctx))


class TestVoice(unittest.TestCase):
    def test_voice_message_roundtrip(self):
        fake, calls = claude_seq(
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "**สวัสดี**ครับ 😊 https://x.com"}]})
        bot.tg = FakeTG()
        m = {"chat": {"id": 111}, "from": {"id": 111}, "voice": {"file_id": "abc"}}
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(m)
        self.assertIn("ได้ยินว่า: ทดสอบ", bot.tg.sent[0])
        self.assertTrue(bot.tg.sent[-1].startswith("VOICE:"))
        self.assertIn("โหมด" if False else "เสียง", calls[0]["messages"][-1]["content"][1]["text"])

    def test_clean_for_speech(self):
        import voice
        self.assertEqual(voice.clean_for_speech("**แบต** 78% 🔋 ดูที่ https://a.com"), "แบต 78 เปอร์เซ็นต์ ดูที่")
        self.assertEqual(voice.clean_for_speech("คงเหลือ ≈ ฿158 อุณหภูมิ 31°C"),
                         "คงเหลือ ประมาณ 158 บาท อุณหภูมิ 31 องศา")

    def test_voice_chat_once(self):
        import voice_chat
        fake, calls = claude_seq(
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ได้ครับ"}]})
        with mock.patch("claude_client.requests.Session.post", fake), \
                mock.patch.object(sys, "argv", ["voice_chat.py", "--once"]):
            voice_chat.main()
        self.assertEqual(len(calls), 1)

    def test_wake_words(self):
        import voice_chat
        self.assertEqual(voice_chat.find_wake("สวัสดี ผู้ช่วย เปิดยูทูปหน่อย"), (True, "เปิดยูทูปหน่อย"))
        self.assertEqual(voice_chat.find_wake("สวัสดีผู้ช่วย พิมพ์ว่า เอา Claude ไปใช้"),
                         (True, "พิมพ์ว่า เอา Claude ไปใช้"))      # เว้นวรรคต้องอยู่ครบ
        self.assertEqual(voice_chat.find_wake("ผู้ช่วยครับ คะแนนบอล"), (True, "คะแนนบอล"))
        self.assertFalse(voice_chat.find_wake("วันนี้กินอะไรดี")[0])
        self.assertTrue(voice_chat.find_wake("ผู้ชวย เปิดไฟฉาย")[0])
        self.assertTrue(voice_chat.find_wake("สวัสดีผู้ช่าย")[0])
        for t in ("ไง", "เปิดยูทูปให้หน่อย", "ใช้คำปุกได้ไหม", "ผู้ชายคนนั้น"):
            self.assertFalse(voice_chat.find_wake(t)[0], t)

    def test_vad_segments(self):
        import audio_stream, struct, math
        silent = b"\x00\x00" * audio_stream.FRAME_SAMPLES
        loud = b"".join(struct.pack("<h", int(4000 * math.sin(i / 3))) for i in range(audio_stream.FRAME_SAMPLES))
        frames = [silent] * 20 + [loud] * 30 + [silent] * 40
        m = audio_stream.MicStream.__new__(audio_stream.MicStream)
        m.noise = 200.0
        it = iter(frames)
        m._frame = lambda: next(it)
        pcm = m.utterance(end_silence=0.7)
        secs = len(pcm) / 32000
        self.assertTrue(1.0 < secs < 2.3, secs)   # เสียงพูด 0.9s + เงียบท้าย 0.7s + ก่อนหน้า 0.5s

    def test_streaming_parse(self):
        import claude_client
        lines = [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}',
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":"","citations":null}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"สวัสดี"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ครับ"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"t1","name":"torch","input":{}}}',
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"on\\": tr"}}',
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"ue}"}}',
            'data: {"type":"content_block_stop","index":1}',
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":9}}',
        ]

        class R:
            status_code = 200
            def iter_lines(self, decode_unicode=True):
                return iter(lines)
        got = []
        with mock.patch.object(claude_client, "_request", return_value=R()):
            res = claude_client.stream_message("k", "m", "s", [], [], on_text=got.append)
        self.assertEqual("".join(got), "สวัสดีครับ")
        self.assertEqual(res["stop_reason"], "tool_use")
        self.assertEqual(res["content"][1]["input"], {"on": True})
        self.assertNotIn("citations", res["content"][0])

    def test_speaker_chunks(self):
        import voice
        sp = voice.Speaker()
        for ch in "สวัสดีครับ วันนี้แบตเหลือเจ็ดสิบสองเปอร์เซ็นต์ ยังใช้ได้อีกนานเลยครับ ":
            sp.feed(ch)
        sp.finish()
        self.assertEqual(sp.spoken[0], "สวัสดีครับ")
        self.assertGreaterEqual(len(sp.spoken), 2)

    def test_speaker_no_cut_mid_sentence(self):
        import voice
        sp = voice.Speaker()
        for ch in "วันนี้อากาศดีนะ ออกไปเดินเล่นกันไหม แล้วค่อยกลับมากินข้าวด้วยกันครับ ":
            sp.feed(ch)
        sp.finish()
        self.assertEqual(len(sp.spoken), 1)          # ไม่ตัดที่ "นะ " กลางประโยค

    def test_voice_json_does_not_override_newer_app_setting(self):
        import voice_profile, config, json, os, time, tempfile
        d = tempfile.mkdtemp()
        env = os.path.join(d, ".env")
        old_dir, old_env = config.DATA_DIR, os.environ.get("BOT_ENV_FILE")
        try:
            config.DATA_DIR = d
            os.environ["BOT_ENV_FILE"] = env
            json.dump({"TTS_VOICE": "th-TH-NiwatNeural"}, open(os.path.join(d, "voice.json"), "w"))
            os.utime(os.path.join(d, "voice.json"), (time.time() - 100, time.time() - 100))
            open(env, "w").write("TTS_VOICE=th-TH-PremwadeeNeural\n")
            config.TTS_VOICE = "th-TH-PremwadeeNeural"
            voice_profile._last["mtime"] = 0.0
            voice_profile.sync()
            self.assertEqual(config.TTS_VOICE, "th-TH-PremwadeeNeural")
            self.assertFalse(os.path.exists(os.path.join(d, "voice.json")))
        finally:
            config.DATA_DIR = old_dir
            if old_env is None:
                os.environ.pop("BOT_ENV_FILE", None)
            else:
                os.environ["BOT_ENV_FILE"] = old_env
            config.TTS_VOICE = "th-TH-NiwatNeural"
            voice_profile._last["mtime"] = 0.0

    def test_transcribe_retries_next_engine_on_garbage(self):
        import voice
        from unittest import mock
        calls = []

        def bad(p):
            calls.append("cf"); voice._last["why"] = "ข้อความแต่งเอง/ภาษาแปลก"; return ""

        def good(p):
            calls.append("groq"); return "เปิดไลน์"
        with mock.patch.object(voice, "stt_chain", return_value=["cloudflare", "groq"]), \
                mock.patch.object(voice, "_transcribe_cf", bad), mock.patch.object(voice, "_transcribe_groq", good), \
                mock.patch.object(voice.config, "MOCK_PHONE", False):
            voice._last["sec"] = 1.5
            self.assertEqual(voice.transcribe("x.wav"), "เปิดไลน์")
        self.assertEqual(calls, ["cf", "groq"])

    def test_vad_adapts_to_noisy_room(self):
        import audio_stream, struct, math
        def tone(a):
            return b"".join(struct.pack("<h", int(a * math.sin(i / 3))) for i in range(audio_stream.FRAME_SAMPLES))
        # ห้องมีเสียงพัดลมดังคงที่ 300 → ต้องยังจับได้ว่าพูดจบ (ไม่ค้างยาวจนครบ 15 วิ)
        frames = [tone(300)] * 200 + [tone(3000)] * 40 + [tone(300)] * 200
        m = audio_stream.MicStream.__new__(audio_stream.MicStream)
        m.noise = 20.0
        it = iter(frames)
        m._frame = lambda: next(it)
        pcm = m.utterance(end_silence=0.7, max_seconds=15)
        self.assertLess(len(pcm) / 32000, 4.0)

    def test_barge_in_detection(self):
        import audio_stream, struct, math, queue
        def tone(a):
            return b"".join(struct.pack("<h", int(a * math.sin(i / 3))) for i in range(audio_stream.FRAME_SAMPLES))
        m = audio_stream.MicStream.__new__(audio_stream.MicStream)
        m.noise = 50.0
        m.q = queue.Queue()
        for _ in range(40):
            m.q.put((tone(1000), True))     # เสียงลำโพงสะท้อนเข้าไมค์
        for _ in range(15):
            m.q.put((tone(6000), True))     # ผู้ใช้พูดแทรกดังกว่า
        frames = m.watch_interrupt(lambda: not m.q.empty())
        self.assertIsNotNone(frames)
        m.q = queue.Queue()
        for _ in range(60):
            m.q.put((tone(1200), True))     # มีแต่เสียงลำโพง → ต้องไม่นับว่าพูดแทรก
        self.assertIsNone(m.watch_interrupt(lambda: not m.q.empty()))
        # เสียงลำโพงเริ่มเบาแล้วดังขึ้น (ต้นประโยค TTS) → ต้องไม่นับว่าพูดแทรก
        import random
        random.seed(1)
        m.q = queue.Queue()
        for _ in range(5):
            m.q.put((tone(100), True))
        for _ in range(120):
            m.q.put((tone(random.choice([800, 1500, 2500, 3000, 600])), True))
        self.assertIsNone(m.watch_interrupt(lambda: not m.q.empty()))

    @mock.patch.object(config, "BARGE_IN", True)
    def test_answer_interrupted(self):
        import voice_chat, time as _t
        responses = iter([
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ประโยคยาวมาก " * 30}]}])

        def slow_post(*a, json=None, **k):
            _t.sleep(0.3)
            return FakeResp(next(responses))
        mic = voice_chat.get_mic()
        mic.interrupt_frames = [b"\x00\x10" * 480]
        ctx = voice_chat.VoiceCtx(111)
        with mock.patch("claude_client.requests.Session.post", slow_post):
            new = voice_chat.answer("เล่าเรื่องยาวๆ", ctx)
        self.assertEqual(new, "ทดสอบ")   # คำพูดใหม่ที่พูดแทรก (mock STT คืน "ทดสอบ")

    def test_quick_commands(self):
        import voice_chat, phone_tools
        ctx = voice_chat.VoiceCtx(111)
        with mock.patch.object(phone_tools, "_launcher_components",
                               return_value=["com.google.android.youtube/.Main", "com.garena.game.kgth/.M"]):
            import voice_profile
            acks = {a.format(p="ครับ") for a in voice_profile._ACKS}
            self.assertIn(voice_chat.quick_command("เปิด YouTube ให้หน่อย", ctx), acks)   # คำตอบรับไม่ซ้ำทุกครั้ง
            self.assertIn(voice_chat.quick_command("เปิดยูทูปหน่อยครับ", ctx), acks)
            self.assertEqual(voice_chat.quick_command("เปิดไฟฉาย", ctx), "เปิดไฟฉายแล้วครับ")
            self.assertIn("78", voice_chat.quick_command("แบตเหลือเท่าไหร่", ctx))
            self.assertIsNone(voice_chat.quick_command("เปิดแอปที่ใช้แต่งรูป", ctx))
            self.assertIsNone(voice_chat.quick_command("วันนี้อากาศเป็นยังไง", ctx))

    def test_normalize_quiet_audio(self):
        import voice, struct, math, array
        quiet = b"".join(struct.pack("<h", int(300 * math.sin(i / 5))) for i in range(16000))
        out, gain, peak = voice.normalize_pcm(quiet)
        self.assertGreater(gain, 20)
        self.assertGreater(max(abs(x) for x in array.array("h", out)), 14000)
        loud = b"".join(struct.pack("<h", int(25000 * math.sin(i / 5))) for i in range(16000))
        self.assertEqual(voice.normalize_pcm(loud)[1], 1.0)

    def test_speaker_truncates_long_answer(self):
        import voice
        sp = voice.Speaker(max_chars=60)
        for ch in ("ประโยคทดสอบยาวๆ ครับ " * 20):
            sp.feed(ch)
        sp.finish()
        self.assertIn("Telegram", sp.spoken[-1])
        self.assertLess(sum(len(x) for x in sp.spoken), 160)

    def test_yes_or_no(self):
        import voice_chat
        for t in ("ยืนยัน", "ตกลงครับ", "ใช่", "โอเค ส่งเลย", "Yes", "ได้เลย"):
            self.assertTrue(voice_chat.yes_or_no(t), t)
        for t in ("ไม่", "ยกเลิก", "ไม่ได้", "อย่าส่ง", "ไม่เอา"):
            self.assertFalse(voice_chat.yes_or_no(t), t)
        self.assertIsNone(voice_chat.yes_or_no("อะไรนะ"))

    def test_voice_confirm(self):
        import voice_chat
        ctx = voice_chat.VoiceCtx(111)
        ctx.tg = None
        with mock.patch.object(voice_chat, "listen_text", return_value="ยืนยันครับ"):
            self.assertTrue(ctx.confirm("พิมพ์ข้อความ: สวัสดี"))
        answers = iter(["", "ตกลง"])
        with mock.patch.object(voice_chat, "listen_text", side_effect=lambda **k: next(answers)):
            self.assertTrue(ctx.confirm("ส่งข้อความ"))         # ถามซ้ำแล้วตอบได้
        with mock.patch.object(voice_chat, "listen_text", return_value="ไม่เอา"):
            self.assertFalse(ctx.confirm("ส่งข้อความ"))

    def test_gemini_transcribe(self):
        import gemini_client
        sent = []

        def fake(*a, json=None, **k):
            sent.append(json)
            return FakeResp({"candidates": [{"content": {"parts": [{"text": "พิมพ์ว่า เอา Claude ไปใช้"}]}}]})
        with mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch("gemini_client.requests.Session.post", side_effect=fake):
            t = gemini_client.transcribe(b"RIFF....", vocab="Claude")
        self.assertEqual(t, "พิมพ์ว่า เอา Claude ไปใช้")
        self.assertIn("Claude", sent[0]["contents"][0]["parts"][1]["text"])
        self.assertEqual(sent[0]["contents"][0]["parts"][0]["inline_data"]["mime_type"], "audio/wav")

    def test_needs_accurate(self):
        import voice
        with mock.patch.object(config, "STT_ENGINE", "auto"):
            self.assertTrue(voice.needs_accurate("พิมพ์ข้อความว่า เอาคอร์สไปใช้"))
            self.assertTrue(voice.needs_accurate("ส่งไลน์หาแม่ว่าถึงแล้ว"))
            self.assertFalse(voice.needs_accurate("แบตเหลือเท่าไหร่"))
            self.assertFalse(voice.needs_accurate("เปิดไฟฉาย"))

    def test_highpass_keeps_length(self):
        import voice
        pcm = b"\x10\x00" * 1600
        self.assertEqual(len(voice.highpass(pcm)), len(pcm))

    def test_permissions(self):
        import permissions
        self.assertTrue(permissions.wants_hold("พิมพ์ไว้ แต่รอฟังคำสั่งก่อนส่ง"))
        self.assertTrue(permissions.wants_hold("อย่าเพิ่งส่งนะ"))
        self.assertFalse(permissions.wants_hold("ส่งไลน์หาแม่ว่าถึงแล้ว"))
        self.assertEqual(permissions.category("ชำระเงิน"), "always")
        self.assertEqual(permissions.category("Send"), "message")
        self.assertEqual(permissions.category("โทรด้วยเสียง"), "call")

    def test_ui_throttled(self):
        import ui
        calls = []
        with mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch.object(config, "UI_MIN_INTERVAL", 0.3), \
                mock.patch.object(ui, "_call", side_effect=lambda a: calls.append(a)):
            ui.listening()
            text = ""
            for ch in "สวัสดีครับ วันนี้มีอะไรให้ช่วยไหมครับ" * 3:
                text += ch
                ui.speaking(text)
                time.sleep(0.005)
            time.sleep(1.0)
        self.assertLess(len(calls), 8)                 # ไม่ยิงคำสั่งรัวๆ ทุกตัวอักษร
        self.assertIn(text[:300], " ".join(calls[-1]))  # แต่สุดท้ายแสดงข้อความล่าสุดครบ

    def test_menu_callback_runs_prompt(self):
        import prompts
        bot.tg = FakeTG()
        bot.handle_message(msg("/menu"))
        self.assertIn("เลือกหมวด", bot.tg.sent[-1])
        # กดหมวดแรก → แสดงคำสั่ง
        bot.tg.sent.clear()
        cq = {"id": "c", "from": {"id": 111}, "data": "cat:0",
              "message": {"chat": {"id": 111}, "message_id": 1}}
        bot.handle_callback(cq)
        self.assertTrue(any("EDIT:" in m for m in bot.tg.sent))

    def test_close_multiple_and_current(self):
        import phone_tools, app_index
        apps = [{"pkg": "com.ss.android.ugc.trill", "label": "TikTok"},
                {"pkg": "com.facebook.katana", "label": "Facebook"},
                {"pkg": "com.android.calculator2", "label": "เครื่องคิดเลข"}]
        with mock.patch.object(app_index, "load", return_value=apps), \
                mock.patch.object(app_index, "foreground_pkg", return_value="com.ss.android.ugc.trill"):
            out = phone_tools.close_app({"app": "เครื่องคิดเลข, Facebook"}, bot.Ctx(111))
            self.assertIn("เครื่องคิดเลข", out)
            self.assertIn("Facebook", out)
            out2 = phone_tools.close_app({"app": "แอปนี้"}, bot.Ctx(111))
            self.assertIn("TikTok", out2)

    def test_find_app_by_thai_label(self):
        import app_index
        apps = [{"pkg": "com.android.calculator2", "label": "เครื่องคิดเลข"},
                {"pkg": "com.lumii.capcut", "label": "CapCut"}]
        with mock.patch.object(app_index, "load", return_value=apps):
            self.assertEqual(app_index.find("เครื่องคิดเลข")[0], "com.android.calculator2")
            self.assertEqual(app_index.find("capcut")[0], "com.lumii.capcut")
            self.assertEqual(app_index.find("capcat")[0], "com.lumii.capcut")      # เพี้ยนจากเสียง

    def test_system_tools(self):
        import system_tools
        self.assertIn("เปิด Wi-Fi", system_tools.wifi({"on": True}, None))
        self.assertIn("ความสว่าง", system_tools.brightness({"level": "50%"}, None))
        self.assertIn("โฮม", system_tools.go_home({}, None))

    def test_adb_recovers_from_offline(self):
        import screen_tools
        screen_tools._state.update(serial=None, checked=0)
        calls = {"n": 0}
        def fake_run(cmd, timeout=30, input_text=None):
            if cmd[:2] == ["adb", "devices"]:
                calls["n"] += 1
                # รอบแรก offline, รอบต่อไป online
                return "List\n127.0.0.1:5555\toffline\n" if calls["n"] == 1 else "List\n127.0.0.1:5555\tdevice\n"
            if cmd[-1] == "ok" or "echo" in cmd:
                return "ok"
            return ""
        with mock.patch.object(screen_tools, "_run", side_effect=fake_run), \
                mock.patch.object(screen_tools.shutil, "which", return_value="/usr/bin/adb"), \
                mock.patch.object(config, "MOCK_PHONE", False):
            self.assertEqual(screen_tools.adb_serial(force=True), "127.0.0.1:5555")

    def test_device_tools(self):
        import phone_tools
        out = phone_tools.device_health({}, None)
        self.assertIn("แบต", out)
        self.assertIn("ล้างแรมแล้ว", phone_tools.clean_ram({}, None))

    def test_beep_file(self):
        import voice
        voice.beep()
        self.assertTrue(os.path.exists(os.path.join(config.DATA_DIR, "beep_880.wav")))


class TestExtras(unittest.TestCase):
    def test_memory_in_prompt(self):
        import extras, agent
        extras.forget({"query": "ทั้งหมด"}, None)
        extras.remember({"text": "ผู้ใช้ชื่อมิสิ ชอบให้เรียกว่าพี่"}, None)
        self.assertIn("ชอบให้เรียกว่าพี่", agent.system_prompt())
        self.assertIn("ลืมแล้ว 1", extras.forget({"query": "มิสิ"}, None))
        self.assertNotIn("มิสิ", agent.system_prompt())

    def test_schedule_task_runs_and_repeats(self):
        import extras
        ctx = bot.Ctx(111)
        extras.schedule({"time": "07:00", "text": "สรุปข่าว", "kind": "task", "repeat": "daily"}, ctx)
        items = bot._load_reminders()
        it = next(r for r in items if r["text"] == "สรุปข่าว")
        self.assertGreater(it["due"], time.time())
        self.assertLessEqual(it["due"] - time.time(), 86400 + 60)
        nxt = extras.reschedule(it)
        self.assertGreater(nxt["due"], time.time())          # รอบถัดไปอยู่ในอนาคตเสมอ
        self.assertIn("สรุปข่าว", extras.list_schedules({}, ctx))
        # ทำให้ถึงเวลา แล้วดูว่า AI ถูกเรียกและคำตอบส่งเข้า Telegram
        it["due"] = time.time() - 1
        bot._save_reminders([it])
        fake, calls = claude_seq({"stop_reason": "end_turn", "content": [{"type": "text", "text": "ข่าววันนี้..."}]})
        bot.tg = FakeTG()
        with mock.patch("claude_client.requests.Session.post", fake):
            th = threading.Thread(target=bot.reminder_loop, daemon=True)
            th.start()
            th.join(1.5)
        self.assertTrue(any("ข่าววันนี้" in m for m in bot.tg.sent))
        left = bot._load_reminders()
        self.assertTrue(left and left[0]["due"] > time.time())      # รอบพรุ่งนี้
        bot._save_reminders([])

    def test_status_and_usage(self):
        import extras
        extras.record_usage("Claude", {"input_tokens": 1000, "output_tokens": 500})
        rep, usd = extras.usage_report()
        self.assertGreater(usd, 0)
        bot.tg = FakeTG()
        bot.handle_message(msg("/status"))
        self.assertIn("สถานะผู้ช่วย", bot.tg.sent[-1])

    def test_battery_alert(self):
        import extras, phone_tools
        extras._alert.update(low=False, t=0)
        with mock.patch.object(phone_tools, "run", return_value='{"percentage": 9, "plugged": "UNPLUGGED", "temperature": 30}'):
            out = extras.check_device_alerts()
        self.assertTrue(any("9%" in m for m in out))


class TestGroq(unittest.TestCase):
    def test_convert_and_call(self):
        import groq_client as g
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "แบตเท่าไหร่"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "battery_status", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "78%"}]},
        ]
        conv = g.convert_messages("ระบบ", msgs)
        self.assertEqual(conv[0]["role"], "system")
        self.assertEqual(conv[2]["tool_calls"][0]["function"]["name"], "battery_status")
        self.assertEqual(conv[3]["role"], "tool")

        def fake_post(url, json=None, **k):
            return FakeResp({"choices": [{"message": {"content": "แบต 78% ครับ"}}],
                             "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
        with mock.patch.object(config, "GROQ_API_KEY", "gsk"), \
                mock.patch.object(config, "GROQ_MODEL", "llama-3.3-70b-versatile"), \
                mock.patch("groq_client.requests.Session.post", side_effect=lambda *a, **k: fake_post(a[0] if a else "", **k)):
            import phone_tools; res = g.create_message("sys", [{"role": "user", "content": "x"}], phone_tools.claude_tool_specs())
        self.assertEqual(res["content"][0]["text"], "แบต 78% ครับ")

    def test_groq_tool_call(self):
        import groq_client as g
        def fake_post(url, json=None, **k):
            return FakeResp({"choices": [{"message": {"tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "torch", "arguments": '{"on": true}'}}]}}], "usage": {}})
        with mock.patch.object(config, "GROQ_API_KEY", "gsk"), \
                mock.patch.object(config, "GROQ_MODEL", "llama-3.3-70b-versatile"), \
                mock.patch("groq_client.requests.Session.post", side_effect=lambda *a, **k: fake_post(a[0] if a else "", **k)):
            res = g.create_message("sys", [{"role": "user", "content": "เปิดไฟ"}], [])
        self.assertEqual(res["stop_reason"], "tool_use")
        self.assertEqual(res["content"][0]["name"], "torch")
        self.assertEqual(res["content"][0]["input"], {"on": True})


class TestNotify(unittest.TestCase):
    def test_new_notification_announced_and_replied(self):
        import notify_watch, voice_chat
        old = [{"packageName": "jp.naver.line.android", "title": "แม่", "content": "ข้อความเก่า"}]
        new = old + [{"packageName": "jp.naver.line.android", "title": "แม่", "content": "กินข้าวยัง"},
                     {"packageName": "com.android.systemui", "title": "USB", "content": "ชาร์จ"}]
        seq = iter([old, new])
        notify_watch._seen.clear()
        with mock.patch.object(notify_watch, "_list", side_effect=lambda: next(seq)), \
                mock.patch.object(notify_watch.time, "sleep", side_effect=[None, StopIteration]):
            try:
                notify_watch.watcher()
            except StopIteration:
                pass
        with mock.patch.object(config, "NOTIFY_QUIET", ""):
            items = notify_watch.pending()
            self.assertEqual(len(items), 1)                       # ของเก่า + systemui ไม่นับ
            self.assertIn("กินข้าวยัง", notify_watch.describe(items[0]))
            for it in items:
                notify_watch.new_items.put(it)
            ctx = voice_chat.VoiceCtx(111)
            ctx.tg = None
            said = []
            import share_tools
            with mock.patch.object(voice_chat.voice, "say", side_effect=lambda t, **k: said.append(t)), \
                    mock.patch.object(voice_chat, "listen_text", return_value="ตอบกลับว่า กินแล้วจ้า แล้วกดส่ง"), \
                    mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา แม่ ใน line แล้ว ✅") as sd, \
                    mock.patch.object(voice_chat, "conversation"):
                voice_chat.announce_notifications(ctx)
        self.assertIn("จะตอบกลับไหม", said[0])
        self.assertEqual(sd.call_args[0][0], {"app": "line", "to": "แม่", "text": "กินแล้วจ้า"})   # LINE ไม่ใช่ไอจี

    def test_reply_last_sender_uses_their_app(self):
        """แจ้งเตือน LINE เข้ามา → 'ตอบกลับว่า โอเค' ต้องไป LINE ของคนนั้น (ไม่ใช่แอปที่เคยส่งล่าสุด)"""
        import notify_watch, quick, share_tools, skills
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()):
            skills.set_pref("dm_app", "instagram")
            notify_watch.remember_last({"packageName": "jp.naver.line.android", "app": "LINE", "title": "พี่ต้น"})
            self.assertEqual(share_tools.reply_text("ตอบกลับว่า โอเค แล้วกดส่ง"), "โอเค")
            with mock.patch.object(share_tools, "send_here", return_value="ERROR: ตอนนี้ไม่ได้เปิดห้องแชทอยู่"), \
                    mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา พี่ต้น ใน line แล้ว ✅") as sd:
                res = quick.dm("ตอบกลับว่า โอเค")
        self.assertEqual(sd.call_args[0][0], {"app": "line", "to": "พี่ต้น", "text": "โอเค"})
        self.assertIn("✅", res)

    def test_format_list(self):
        import notify_watch
        out = notify_watch.format_list('[{"packageName":"com.facebook.orca","title":"ต้น","content":"ว่างไหม"}]')
        self.assertIn("[Messenger] ต้น: ว่างไหม", out)


class TestGemini(unittest.TestCase):
    def test_convert_and_roundtrip(self):
        import gemini_client, phone_tools
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "แบตเท่าไหร่"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "battery_status", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "78%"}]},
        ]
        c = gemini_client.convert_messages(msgs)
        self.assertEqual([x["role"] for x in c], ["user", "model", "user"])
        self.assertEqual(c[1]["parts"][0]["functionCall"]["name"], "battery_status")
        self.assertEqual(c[2]["parts"][0]["functionResponse"]["name"], "battery_status")
        tools = gemini_client.convert_tools(phone_tools.claude_tool_specs())
        names = [d["name"] for d in tools[0]["function_declarations"]]
        self.assertIn("web_search", names)
        sv = next(d for d in tools[0]["function_declarations"] if d["name"] == "set_volume")
        self.assertEqual(sv["parameters"]["type"], "OBJECT")
        self.assertEqual(sv["parameters"]["properties"]["volume"]["type"], "INTEGER")

    def test_agent_with_gemini(self):
        replies = iter([
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "battery_status", "args": {}}, "thoughtSignature": "SIG1"}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "แบต 78% ครับ"}]}}]},
        ])
        sent = []

        def fake(json=None, **k):
            sent.append(json)
            return FakeResp(next(replies))
        bot.tg = FakeTG()
        with mock.patch.object(config, "LLM_PROVIDER", "gemini"), \
                mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch("gemini_client.requests.Session.post", side_effect=lambda *a, **k: fake(**k)):
            bot.handle_message(msg("แบตเท่าไหร่"))
        self.assertIn("78%", bot.tg.sent[-1])
        parts = sent[1]["contents"][-2]["parts"]
        self.assertEqual(parts[0]["thoughtSignature"], "SIG1")          # ส่งลายเซ็นกลับให้ Gemini
        self.assertIn("functionResponse", sent[1]["contents"][-1]["parts"][0])

    def test_gemini_resolves_model_on_error(self):
        import gemini_client as gc
        gc._resolved.clear()
        calls = {"n": 0}

        class R:
            def __init__(self, code, data=None, text=""):
                self.status_code = code; self._d = data or {}; self.text = text
            def json(self): return self._d

        def fake_get(url, **k):
            return R(200, {"models": [
                {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]}]})

        def fake_post(url, json=None, **k):
            calls["n"] += 1
            if "gemini-flash-latest" in url:        # รุ่นเดิมใช้ไม่ได้ (error หลอกว่า auth)
                return R(401, text='{"error":{"status":"UNAUTHENTICATED","details":[{"reason":"ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}}')
            return R(200, {"candidates": [{"content": {"parts": [{"text": "โอเค"}]}}]})
        with mock.patch.object(config, "GEMINI_API_KEY", "AQ.test"), \
                mock.patch.object(config, "GEMINI_MODEL", "gemini-flash-latest"), \
                mock.patch("gemini_client.requests.Session.get", side_effect=lambda url, **k: fake_get(url, **k)), \
                mock.patch("gemini_client.requests.Session.post", side_effect=lambda url, **k: fake_post(url, **k)):
            res = gc.create_message("sys", [{"role": "user", "content": "x"}], [])
        self.assertEqual(res["content"][0]["text"], "โอเค")
        self.assertEqual(gc._resolved.get("gemini-flash-latest"), "gemini-3.6-flash")
        gc._resolved.clear()

    def test_gemini_stream(self):
        import gemini_client, json as _j
        chunks = [
            {"candidates": [{"content": {"parts": [{"text": "สวัส"}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "ดีครับ"}]}}]},
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "torch", "args": {"on": True}},
                                                     "thoughtSignature": "S"}]}}],
             "usageMetadata": {"promptTokenCount": 5}},
        ]

        class R:
            status_code = 200
            def iter_lines(self, decode_unicode=True):
                return iter("data: " + _j.dumps(c) for c in chunks)
        got = []
        with mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch("gemini_client.requests.Session.post", return_value=R()):
            res = gemini_client.create_message("sys", [{"role": "user", "content": "x"}], [], on_text=got.append)
        self.assertEqual("".join(got), "สวัสดีครับ")
        self.assertEqual(res["content"][0]["text"], "สวัสดีครับ")
        self.assertEqual(res["content"][1]["name"], "torch")
        self.assertEqual(res["content"][1]["_sig"], "S")
        self.assertEqual(res["stop_reason"], "tool_use")

    def test_credit_out_long_fallback(self):
        import claude_client, agent
        agent._fallback_until[0] = 0
        replies = iter([{"candidates": [{"content": {"parts": [{"text": "จาก Gemini"}]}}]}])
        bot.tg = FakeTG()
        with mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch.object(config, "LLM_FALLBACK", "gemini"), \
                mock.patch.object(claude_client, "_request",
                                  side_effect=claude_client.ClaudeError("Claude API 400: credit balance too low")), \
                mock.patch("gemini_client.requests.Session.post",
                           side_effect=lambda *a, **k: FakeResp(next(replies))):
            bot.handle_message(msg("สวัสดี"))
        self.assertGreater(agent._fallback_until[0] - time.time(), 3600)   # สลับยาวเกิน 1 ชม.
        agent._fallback_until[0] = 0; agent._fallback_to[0] = "groq"

    def test_fallback_to_gemini(self):
        import claude_client
        replies = iter([{"candidates": [{"content": {"parts": [{"text": "ตอบจาก Gemini"}]}}]}])
        bot.tg = FakeTG()
        with mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch.object(config, "LLM_FALLBACK", "gemini"), \
                mock.patch.object(claude_client, "_request", side_effect=claude_client.ClaudeError("credit")), \
                mock.patch("gemini_client.requests.Session.post",
                           side_effect=lambda *a, **k: FakeResp(next(replies))):
            bot.handle_message(msg("สวัสดี"))
        import agent
        agent._fallback_until[0] = 0; agent._fallback_to[0] = "groq"
        self.assertIn("Gemini", bot.tg.sent[-1])


class TestOpenApp(unittest.TestCase):
    """เปิดแอป: แอปใน GBox เปิดผ่านลิงก์ด้วย ADB และต้องไม่ตอบว่า 'เปิดแล้ว' ถ้าเปิดไม่สำเร็จ"""

    def _patch(self, installed, am_out="Starting: Intent { cmp=x }"):
        import phone_tools, screen_tools
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            return am_out
        ps = [mock.patch.object(phone_tools, "_launcher_components", return_value=installed),
              mock.patch("time.sleep"),
              mock.patch.object(screen_tools, "adb_serial", return_value="127.0.0.1:5555"),
              mock.patch.object(screen_tools, "adb_shell", side_effect=adb)]
        for p in ps:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in ps])
        return phone_tools, calls

    def test_youtube_in_gbox_opens_link(self):
        import phone_tools
        pt, calls = self._patch(["com.huawei.camera/.Main", "com.gbox.android/.Main"])
        with mock.patch.object(phone_tools, "run", return_value="") as r:
            res = pt.open_app({"app": "ยูทูป"}, None)
        self.assertIn("ผ่านลิงก์", res)
        self.assertEqual(r.call_args[0][0], ["termux-open-url", "https://www.youtube.com"])
        self.assertFalse(any(c[:2] == ["am", "start"] and "com.gbox.android/.Main" in c for c in calls))

    def test_app_list_unreadable_still_opens_link(self):
        pt, calls = self._patch([])                       # HarmonyOS บางทีอ่านรายชื่อแอปไม่ได้
        self.assertIn("ผ่านลิงก์", pt.open_app({"app": "youtube"}, None))

    def test_google_alias(self):
        pt, calls = self._patch(["com.huawei.camera/.Main"])
        import phone_tools
        with mock.patch.object(phone_tools, "run", return_value="") as r:
            self.assertIn("ผ่านลิงก์", pt.open_app({"app": "กูเกิ้ล"}, None))
        self.assertIn("https://www.google.com", r.call_args[0][0])

    def test_failed_launch_is_error_not_success(self):
        pt, calls = self._patch(["jp.naver.line.android/.Main"],
                                am_out="Error: Activity not started, unable to resolve Intent")
        res = pt.open_app({"app": "line"}, None)
        self.assertTrue(res.startswith("ERROR"), res)


    def test_home_icon_when_link_does_not_open(self):
        import phone_tools, screen_tools
        xml = screen_tools._MOCK_XML.replace('text="แม่"', 'text="YouTube"')
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            return xml if args[:2] == ["uiautomator", "dump"] else "Starting: Intent { cmp=x }"
        with mock.patch.object(phone_tools, "_launcher_components", return_value=["com.gbox.android/.Main"]), \
                mock.patch("time.sleep"), mock.patch.object(phone_tools, "run", return_value=""), \
                mock.patch.object(phone_tools, "_moved", return_value=None), \
                mock.patch.object(screen_tools, "adb_serial", return_value="s"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=adb):
            res = phone_tools.open_app({"app": "youtube"}, None)
        self.assertIn("หน้าโฮม", res)
        self.assertIn(["input", "tap", "250", "230"], calls)

    def test_adb_shell_quotes_args(self):
        import screen_tools
        with mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch.object(screen_tools, "adb_serial", return_value="s"), \
                mock.patch.object(screen_tools, "_run", return_value="ok") as r:
            screen_tools.adb_shell(["am", "start", "-d", "https://x.com/?a=1&b=2", "--es", "t", "สวัสดี ครับ"],
                                   quote=True)
        args = r.call_args[0][0]
        self.assertIn("'https://x.com/?a=1&b=2'", args)
        self.assertIn("'สวัสดี ครับ'", args)


class TestOpenPage(unittest.TestCase):
    """เปิดแอปแล้วเข้าหน้าแชท: แตะปุ่ม 'ข้อความ' ในแถบเมนู (Instagram บนแท็บเล็ต = แถบซ้าย)"""

    XML = ('<?xml version="1.0"?><hierarchy><node text="" class="x" bounds="[0,0][1838,1570]" clickable="false" '
           'content-desc="" resource-id="">'
           '<node text="หน้าหลัก" class="t" bounds="[640,480][714,530]" clickable="true" content-desc="" resource-id=""/>'
           '<node text="Reels" class="t" bounds="[640,686][714,736]" clickable="true" content-desc="" resource-id=""/>'
           '<node text="ข้อความ" class="t" bounds="[640,789][714,839]" clickable="true" content-desc="" resource-id=""/>'
           '<node text="ข้อความ" class="t" bounds="[1100,1000][1200,1040]" clickable="true" content-desc="" '
           'resource-id=""/>'
           '<node text="โปรไฟล์" class="t" bounds="[640,1099][714,1149]" clickable="true" content-desc="" resource-id=""/>'
           '</node></hierarchy>')

    def _run(self, fn):
        import phone_tools, screen_tools
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            return self.XML if args[:2] == ["uiautomator", "dump"] else "Starting: Intent { cmp=x }"
        with mock.patch.object(phone_tools, "_launcher_components",
                               return_value=["com.instagram.android/.Main"]), mock.patch("time.sleep"), \
                mock.patch.dict(phone_tools.COMMON_APPS, {"instagram": "com.instagram.android"}), \
                mock.patch.object(phone_tools, "run", return_value=""), \
                mock.patch.object(screen_tools, "adb_serial", return_value="s"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=adb):
            return fn(), calls

    def test_instagram_chat_taps_rail_button(self):
        import phone_tools
        res, calls = self._run(lambda: phone_tools.open_app({"app": "ไอจี", "page": "chat"}, None))
        self.assertIn("เข้าหน้า chat แล้ว", res)
        self.assertIn(["input", "tap", "677", "814"], calls)       # ปุ่มในแถบซ้าย
        self.assertNotIn(["input", "tap", "1150", "1020"], calls)  # ไม่แตะ 'ข้อความ' กลางจอ

    def test_quick_inbox_phrases(self):
        import quick
        for text in ("เปิด instagram แล้วเปิดแชทหน่อย", "เปิดไอจีแล้วเปิดกล่องข้อความ", "เปิด ig เข้าหน้าข้อความ"):
            res, calls = self._run(lambda: quick.handle(text))
            self.assertIn("เข้าหน้า", res or "", text)
            self.assertIn(["input", "tap", "677", "814"], calls, text)


class TestTimeLimits(unittest.TestCase):
    """เครื่องมือค้าง/หน้าจอมีวิดีโอ → ต้องไม่ทำให้บอทเงียบ"""

    def test_hanging_tool_is_cut(self):
        import agent
        with self.assertRaises(TimeoutError):
            agent._run_limited(lambda a, c: time.sleep(3), {}, None, 0.2)

    def test_dump_idle_fails_fast_with_hint(self):
        import screen_tools
        with mock.patch.object(screen_tools, "adb_shell", return_value="ERROR: could not get idle state."), \
                mock.patch("time.sleep"):
            with self.assertRaises(RuntimeError) as e:
                screen_tools._dump()
        self.assertIn("วิดีโอ", str(e.exception))


class TestSendDM(unittest.TestCase):
    """ส่งข้อความหาคน: แยกคำสั่งเอง ทำครบทุกขั้น และห้าม AI ตอบว่า 'ส่งแล้ว' ถ้ายังไม่ได้ส่ง"""

    def test_parse_phrases(self):
        import quick, share_tools
        cases = {
            "ส่งข้อความหาต้นในไอจีว่าพรุ่งนี้เจอกันนะ": ("instagram", "ต้น", "พรุ่งนี้เจอกันนะ"),
            "เข้าไอจีแล้วส่งข้อความหาต้นว่าสวัสดี": ("instagram", "ต้น", "สวัสดี"),
            "ทักแม่ทางไลน์ว่าถึงบ้านแล้ว": ("line", "แม่", "ถึงบ้านแล้ว"),
            "เปิด instagram แล้วส่งข้อความไปหา @tonny_99 ว่า hi bro": ("instagram", "@tonny_99", "hi bro"),
            "ส่งข้อความหาพี่บีในเฟสบอกว่าโทรกลับด้วย": ("messenger", "พี่บี", "โทรกลับด้วย"),
            "เข้า instagram แล้วไปที่แชทของ heart แล้วเขียนข้อความว่า ไอ่กาก แล้วกดส่งให้ที":
                ("instagram", "heart", "ไอ่กาก"),
            "เข้าไป instagram ไปที่แชท ภรรยา(คนเจก) แล้วพิมพ์ ฝันดีเพื่อน กดส่งข้อความที":
                ("instagram", "ภรรยา(คนเจก)", "ฝันดีเพื่อน"),
        }
        for text, want in cases.items():
            with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา x ใน y แล้ว ✅") as sd:
                res = quick.dm(text)
            self.assertIsNotNone(res, text)
            a = sd.call_args[0][0]
            self.assertEqual((a["app"], a["to"], a["text"]), want, text)
        self.assertIsNone(quick.dm("ส่งข้อความหาแม่ว่าเปิดไลน์ด้วย"))      # ไม่ได้บอกแอป
        self.assertIsNone(quick.dm("เปิดไอจี"))

    def test_no_app_uses_last_dm_app(self):
        import quick, share_tools, skills, contacts
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), \
                mock.patch.dict(contacts._db, {"d": {}}), \
                mock.patch.object(contacts, "_save"):                           # ยังไม่รู้จักคนนี้ในรายชื่อ
            self.assertIsNone(quick.dm("ส่งข้อความหาภรรยาว่าฝันดี"))          # ยังไม่เคยส่ง → ไม่เดา
            skills.set_pref("dm_app", "instagram")
            acks = []
            with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา ภรรยา ใน instagram แล้ว ✅") as sd:
                res = quick.dm("ส่งข้อความหาภรรยาว่าฝันดี", on_start=lambda: acks.append(1))
            self.assertEqual(sd.call_args[0][0]["app"], "instagram")
            self.assertEqual(acks, [1])
            self.assertIn("✅", res)

    def test_voice_log_phrase(self):
        """จาก voice.log จริง: ท่อนแรก + ท่อนที่พูดต่อ (ถอดเสียง แชท→แชร์, คนเจก→คนเจ็ด)"""
        import quick, share_tools
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา x ใน y แล้ว ✅") as sd:
            quick.dm("ไปที่ Instagram แล้วก็ไปที่แชร์ภรรยาคนเจ็ดส่งข้อความว่าฝันดี")
        a = sd.call_args[0][0]
        self.assertEqual((a["app"], a["to"], a["text"]), ("instagram", "ภรรยาคนเจ็ด", "ฝันดี"))
        items = [{"text": "ภรรยา(คนเจก)", "desc": "", "edit": False, "x": 1, "y": 2, "id": ""},
                 {"text": "หน้าหลัก", "desc": "", "edit": False, "x": 3, "y": 4, "id": ""}]
        self.assertEqual(share_tools._find_name(items, "ภรรยาคนเจ็ด")["x"], 1)

    def test_promise_without_action_is_nudged(self):
        import agent
        self.assertTrue(agent._is_promise('โอเคครับ ผมจะเปิด Instagram แล้วหาห้องแชทให้นะครับ', "ไปที่แชทภรรยา ส่งข้อความว่า hi"))
        self.assertTrue(agent._is_promise("ผมจะลองเช็คสถานะการเชื่อมต่อ ADB ให้นะครับ", "เช็คระบบ ADB"))
        self.assertFalse(agent._is_promise("พรุ่งนี้ฝนตก 60%", "พรุ่งนี้ฝนตกไหม"))
        seq = iter([
            ({"content": [{"type": "text", "text": "ผมจะเปิดไอจีให้นะครับ"}], "stop_reason": "end_turn", "usage": {}}, "Ollama"),
            ({"content": [{"type": "tool_use", "id": "t", "name": "battery_status", "input": {}}],
              "stop_reason": "tool_use", "usage": {}}, "Ollama"),
            ({"content": [{"type": "text", "text": "เปิดแล้วครับ"}], "stop_reason": "end_turn", "usage": {}}, "Ollama")])
        with mock.patch.object(agent, "call_llm", side_effect=lambda h, t, o=None: next(seq)), \
                mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()):
            res = agent.chat(4242, "เปิดไอจีให้หน่อย", type("C", (), {"status": lambda *a: None})())
        self.assertEqual(res, "เปิดแล้วครับ")

    def test_name_with_chue_wa(self):
        import quick, share_tools
        for text in ("ไปที่ instagram แล้วไปที่แชทชื่อว่า HAT แล้วพิมพ์ว่า สวัสดี",
                     "ส่งข้อความหาคนชื่อว่า HAT ในไอจีว่า สวัสดี"):
            with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา x ใน y แล้ว ✅") as sd:
                quick.dm(text)
            a = sd.call_args[0][0]
            self.assertEqual((a["app"], a["to"], a["text"]), ("instagram", "HAT", "สวัสดี"), text)
        self.assertEqual(share_tools.clean_name("แล้วไปที่แชทชื่อว่า HAT"), "HAT")

    def test_floating_window_and_top_dm_icon(self):
        import share_tools, screen_tools
        def el(t, x, y, click=True):
            return {"text": t, "desc": "", "id": "", "edit": False, "click": click, "x": x, "y": y,
                    "box": (x - 10, y - 10, x + 10, y + 10)}
        floating = [el("เต็มจอ", 1796, 142), el("ย่อ", 1899, 142), el("ปิด", 2449, 142), el("Reels", 2100, 900)]
        calls = []
        with mock.patch("time.sleep"), mock.patch.object(share_tools, "_items", return_value=[el("x", 1, 1)]), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: calls.append(a) or "ok"):
            share_tools._unfloat(floating)
        self.assertIn(["input", "tap", "1796", "142"], calls)
        phone = [el("ข้อความ", 2480, 500), el("ข้อความ", 2200, 1300), el("หน้าหลัก", 1710, 1550)]
        self.assertEqual(share_tools._dm_icon(phone)["y"], 500)

    def test_garbled_name_ai_pick_and_vocab(self):
        """จาก log: พูด Heart แต่ถอดเสียงได้ 'part' → ให้ AI เลือกจากชื่อบนจอ + จำชื่อไว้ช่วยถอดเสียงครั้งหน้า"""
        import share_tools, agent, skills, voice
        def el(t, x, y):
            return {"text": t, "desc": "", "id": "", "edit": False, "click": True, "x": x, "y": y, "box": (0, 0, 1, 1)}
        items = [el("ข้อความ", 677, 814), el("Heart", 1000, 300), el("ภรรยา(คนเจก)", 1000, 420),
                 el("3.1ล้าน", 900, 500), el("ส่งแล้ว 2 ชม.", 1000, 340)]
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()):
            with mock.patch.object(agent, "call_llm",
                                   return_value=({"content": [{"type": "text", "text": "Heart"}]}, "Claude")) as cl:
                self.assertEqual(share_tools._llm_pick("part", items)["y"], 300)
            prompt = cl.call_args[0][0][0]["content"][0]["text"]
            self.assertIn("ภรรยา(คนเจก)", prompt)
            self.assertNotIn("3.1ล้าน", prompt)
            share_tools._remember_chat_names(items)
            self.assertIn("Heart", voice._vocab())
            self.assertIn("ภรรยา(คนเจก)", voice._stt_prompt())
            self.assertIn("จำแล้ว", skills.handle_text("จำชื่อ แฮท = Heart"))
            self.assertEqual(skills.get_pref("alias:*:" + share_tools._loose("แฮท")), "Heart")

    def test_instagram_spellings(self):
        import quick, share_tools
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา x ใน y แล้ว ✅") as sd:
            quick.dm("เข้าอินสตาร์แกรมแล้วเปิดแชทแล้วไปที่แชทชื่อว่า HATแล้วส่งว่าสวัสดีแล้วกดส่ง")
        self.assertEqual(sd.call_args[0][0]["app"], "instagram")

    def test_error_is_reported_honestly(self):
        import quick, share_tools
        with mock.patch.object(share_tools, "send_dm", return_value="ERROR: หาคนชื่อ 'ต้น' ไม่เจอ — ยังไม่ได้ส่ง"):
            res = quick.dm("ส่งข้อความหาต้นในไอจีว่าสวัสดี")
        self.assertIn("ส่งไม่สำเร็จ", res)

    def test_send_dm_full_flow_in_line(self):
        import share_tools, screen_tools, phone_tools
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            return screen_tools._MOCK_XML if args[:2] == ["uiautomator", "dump"] else "Starting"
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb), \
                mock.patch.object(phone_tools, "run", return_value=""), \
                mock.patch.object(phone_tools, "_launcher_components", return_value=["jp.naver.line.android/.Main"]):
            res = share_tools.send_dm({"app": "ไลน์", "to": "แม่", "text": "hello"}, None)
        self.assertIn("✅", res)
        self.assertIn(["input", "tap", "250", "230"], calls)       # แตะชื่อแม่
        self.assertIn(["input", "tap", "1150", "1500"], calls)     # แตะช่องพิมพ์
        self.assertIn(["input", "tap", "2325", "1500"], calls)     # กดส่ง

    def test_find_name_fuzzy(self):
        import share_tools
        items = [{"text": "ภรรยา 💕", "desc": "", "edit": False, "x": 1, "y": 2, "id": ""},
                 {"text": "heart.official", "desc": "", "edit": False, "x": 3, "y": 4, "id": ""}]
        self.assertEqual(share_tools._find_name(items, "ภรรยา(คนเจก)")["x"], 1)
        self.assertEqual(share_tools._find_name(items, "heart")["x"], 3)
        self.assertIsNone(share_tools._find_name(items, "สมชาย"))

    def test_local_window_keeps_turn_and_shrinks(self):
        import agent
        h = []
        for i in range(10):
            h.append({"role": "user", "content": [{"type": "text", "text": f"q{i}"}]})
            h.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]})
            h.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "y" * 500}]})
            h.append({"role": "assistant", "content": [{"type": "text", "text": "ok"}]})
        w = agent._local_window(h)
        self.assertTrue(agent._is_plain_user(w[0]))
        self.assertLessEqual(len(w), 20)
        self.assertLess(len(w[2]["content"][0]["content"]), 300)

    def test_feed_to_inbox_via_dm_icon_then_open_chat(self):
        """ลิงก์ไปแล้วแต่ยังอยู่หน้าฟีด → ต้องแตะไอคอนกล่องข้อความมุมขวาบน (ไม่ใช่ปุ่ม 'ข้อความ' กลางจอ)"""
        import share_tools, screen_tools, phone_tools

        def node(text, x1, y1, x2, y2, click="true", cls="android.widget.TextView", desc=""):
            return (f'<node text="{text}" class="{cls}" bounds="[{x1},{y1}][{x2},{y2}]" clickable="{click}" '
                    f'content-desc="{desc}" resource-id=""/>')
        root = '<node text="" class="x" bounds="[0,0][1838,1570]" clickable="false" content-desc="" resource-id="">'
        feed = ('<?xml version="1.0"?><hierarchy>' + root + node("", 600, 800, 760, 840, desc="ข้อความ")
                + node("", 1700, 40, 1780, 120, desc="ข้อความ") + '</node></hierarchy>')
        inbox = ('<?xml version="1.0"?><hierarchy>' + root + node("heart.official", 200, 300, 600, 360)
                 + '</node></hierarchy>')
        state = {"xml": feed}
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            if args[:2] == ["uiautomator", "dump"]:
                return state["xml"]
            if args[:2] == ["input", "tap"] and args[2:] == ["1740", "80"]:
                state["xml"] = inbox
            return "Starting"
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb), \
                mock.patch.object(config, "MOCK_PHONE", False):
            hit = share_tools._pick_recipient("heart", "facebook")
        self.assertEqual(hit["text"], "heart.official")
        self.assertIn(["input", "tap", "1740", "80"], calls)
        self.assertNotIn(["input", "tap", "680", "820"], calls)

    def test_explore_screen_rail_tap_then_name(self):
        """หน้าจอจริงจาก log: ตกหน้าสำรวจ → แตะ 'ข้อความ' แถบซ้าย @677,814 → เจอชื่อ / ห้ามใช้ช่องค้นหาของหน้าสำรวจ"""
        import share_tools, screen_tools

        def n(text, x, y):
            return (f'<node text="{text}" class="t" bounds="[{x - 30},{y - 20}][{x + 30},{y + 20}]" clickable="true" '
                    f'content-desc="" resource-id=""/>')
        head = ('<?xml version="1.0"?><hierarchy><node text="" class="x" bounds="[0,0][1838,1570]" '
                'clickable="false" content-desc="" resource-id="">')
        rail = n("หน้าหลัก", 677, 505) + n("ค้นหาและสำรวจ", 677, 608) + n("Reels", 677, 711) + \
            n("ข้อความ", 677, 814) + n("โปรไฟล์", 677, 1124)
        explore = head + rail + n("ค้นหา", 1194, 93) + n("3.1ล้าน", 816, 570) + "</node></hierarchy>"
        inbox = head + rail + n("ภรรยา 💕", 1000, 400) + "</node></hierarchy>"
        st = {"x": explore}
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            if args[:2] == ["uiautomator", "dump"]:
                return st["x"]
            if args == ["input", "tap", "677", "814"]:
                st["x"] = inbox
            return "ok"
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb):
            hit = share_tools._pick_recipient("ภรรยา(คนเจก)", "instagram")
        self.assertEqual(hit["x"], 1000)
        self.assertNotIn(["input", "tap", "1194", "93"], calls)
        # ถ้าแตะแล้วยังไม่เข้ากล่องข้อความ (ไม่มีปุ่มในแถบ) → ไม่ค้นในหน้าสำรวจ
        st["x"] = head + n("ค้นหา", 1194, 93) + "</node></hierarchy>"
        calls.clear()
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb):
            self.assertIsNone(share_tools._pick_recipient("ภรรยา", "instagram"))
        self.assertNotIn(["input", "tap", "1194", "93"], calls)

    def test_search_uses_name_without_brackets(self):
        import share_tools
        items = [{"text": "", "desc": "", "id": "x", "edit": True, "click": True, "x": 5, "y": 5,
                  "box": (0, 0, 10, 10)}]
        self.assertEqual(share_tools._search_box(items)["x"], 5)
        self.assertEqual(share_tools._name_keys("ภรรยา(คนเจก)")[1], "ภรรยา")

    def test_loose_match_and_alias_and_vision_fallback(self):
        import share_tools, screen_tools, skills
        items = [{"text": "", "desc": "ภรรยา(คนเจก)💕, คุณ: ฝันดี · 2 ชม.", "edit": False, "click": True,
                  "x": 900, "y": 300, "id": "", "box": (0, 0, 1, 1)}]
        self.assertEqual(share_tools._find_name(items, "ภรรยาคนเจ็ด")["x"], 900)
        self.assertIsNone(share_tools._find_name(items, "สมชาย"))
        # หาด้วยข้อความไม่เจอ → มองภาพ
        xml = screen_tools._MOCK_XML.replace('text="แม่"', 'text="xyz"')
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), mock.patch("time.sleep"), \
                mock.patch.object(screen_tools, "adb_shell",
                                  side_effect=lambda a, timeout=30, quote=False:
                                  xml if a[:2] == ["uiautomator", "dump"] else "ok"), \
                mock.patch.object(screen_tools, "vision_find",
                                  return_value={"x": 77, "y": 88, "text": "ภรรยา", "desc": "", "id": "",
                                                "edit": False, "click": True, "box": (0, 0, 0, 0)}) as vf:
            hit = share_tools._pick_recipient("ภรรยาคนเจ็ด", "line")
            self.assertEqual((hit["x"], hit["y"]), (77, 88))
            vf.assert_called_once()
            skills.set_pref("alias:line:" + share_tools._loose("ภรรยาคนเจ็ด"), "แม่")
            xml2 = screen_tools._MOCK_XML
            with mock.patch.object(screen_tools, "adb_shell",
                                   side_effect=lambda a, timeout=30, quote=False:
                                   xml2 if a[:2] == ["uiautomator", "dump"] else "ok"):
                self.assertEqual(share_tools._pick_recipient("ภรรยาคนเจ็ด", "line")["text"], "แม่")

    def test_story_name_is_not_a_chat(self):
        import share_tools
        def el(t, d, x, y, i=""):
            return {"text": t, "desc": d, "id": i, "edit": False, "click": True, "x": x, "y": y, "box": (0, 0, 1, 1)}
        items = [el("", "สตอรี่ของ ภรรยา(คนเจก), ยังไม่ได้ดู", 300, 200),
                 el("ภรรยา(คนเจก)", "", 900, 700, "row_inbox_username")]
        self.assertEqual(share_tools._find_name(items, "ภรรยา(คนเจก)")["x"], 900)
        self.assertIsNone(share_tools._find_name(items[:1], "ภรรยา(คนเจก)"))

    def _chat_screen(self, title, typed=""):
        return ('<?xml version="1.0"?><hierarchy><node text="" class="x" bounds="[0,0][1838,1570]" clickable="false" '
                'content-desc="" resource-id="">'
                f'<node text="{title}" class="t" bounds="[700,40][900,100]" clickable="true" content-desc="" resource-id=""/>'
                f'<node text="{typed}" class="android.widget.EditText" bounds="[700,1450][1600,1530]" clickable="true" '
                'content-desc="" resource-id="row_thread_composer_edittext"/>'
                '<node text="ส่ง" class="t" bounds="[1620,1450][1720,1530]" clickable="true" content-desc="" resource-id=""/>'
                '</node></hierarchy>')

    def test_already_in_same_chat_types_directly(self):
        import share_tools, screen_tools, phone_tools
        st = {"x": self._chat_screen("ภรรยา(คนเจก)")}
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            if args[:2] == ["uiautomator", "dump"]:
                return st["x"]
            if args == ["input", "tap", "1670", "1490"]:
                st["x"] = self._chat_screen("ภรรยา(คนเจก)", "")
            return "ok"
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), mock.patch("time.sleep"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=adb), \
                mock.patch.object(phone_tools, "_fg", return_value="com.instagram.android"), \
                mock.patch.object(phone_tools, "open_app") as oa:
            res = share_tools.send_dm({"app": "instagram", "to": "ภรรยาคนเจ็ด", "text": "ฝันดี"}, None)
        self.assertIn("✅", res)
        oa.assert_not_called()                                   # ไม่เปิดแอปใหม่/ไม่แตะหัวห้อง
        self.assertNotIn(["input", "tap", "800", "70"], calls)

    def test_in_other_chat_leaves_first_and_clears_leftover(self):
        import share_tools, screen_tools, phone_tools
        calls = []
        with mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()), mock.patch("time.sleep"), \
                mock.patch.object(screen_tools, "adb_shell",
                                  side_effect=lambda a, timeout=30, quote=False: calls.append(list(a)) or
                                  (self._chat_screen("Heart") if a[:2] == ["uiautomator", "dump"] else "ok")), \
                mock.patch.object(phone_tools, "_fg", return_value="com.instagram.android"):
            self.assertEqual(share_tools._current_chat("instagram", "ภรรยา"), "other")
            self.assertEqual(share_tools._current_chat("line", "ภรรยา"), None)    # คนละแอป
            share_tools._clear_box({"text": "ข้อความค้างเก่า"})
            share_tools._clear_box({"text": "ส่งข้อความ..."})                  # ข้อความตัวอย่างจางๆ ไม่ลบ
        dels = [c for c in calls if c[:2] == ["input", "keyevent"] and "67" in c]
        self.assertEqual(len(dels), 1)

    def test_send_here_phrase(self):
        import quick, share_tools
        with mock.patch.object(share_tools, "send_here", return_value="ส่งในห้องแชทที่เปิดอยู่แล้ว ✅") as sh:
            self.assertIn("✅", quick.dm("พิมพ์ว่า เดี๋ยวโทรกลับนะ"))
        self.assertEqual(sh.call_args[0][0], "เดี๋ยวโทรกลับนะ")

    def test_type_here_without_wa(self):
        """พูดจริง: 'พิมพ์ทำไรอยู่แล้วกดส่ง' ตอนเปิดห้องแชทค้างไว้"""
        import quick, share_tools
        with mock.patch.object(share_tools, "chat_open", return_value=True), \
                mock.patch.object(share_tools, "send_here", return_value="ส่งในห้องแชทที่เปิดอยู่แล้ว ✅") as sh:
            self.assertIn("✅", quick.dm("พิมพ์ทำไรอยู่แล้วกดส่ง"))
            self.assertEqual(sh.call_args[0][0], "ทำไรอยู่")
            quick.dm("โอเค พิมพ์ว่า กินข้าวยัง กดส่งเลย")
            self.assertEqual(sh.call_args[0][0], "กินข้าวยัง")
            sh.reset_mock()
            quick.dm("พิมพ์รายงานส่งครูในไลน์")                 # มีแอป → ไม่ใช่พิมพ์ในห้องที่เปิดอยู่
            sh.assert_not_called()
        with mock.patch.object(share_tools, "chat_open", return_value=False), \
                mock.patch.object(share_tools, "send_here") as sh2:
            self.assertIsNone(quick.dm("พิมพ์ทำไรอยู่แล้วกดส่ง"))   # ไม่ได้เปิดห้องแชท → ให้ AI ตีความ
            sh2.assert_not_called()

    def test_screen_brief_in_chat(self):
        import share_tools, screen_tools, phone_tools
        xml = self._chat_screen("ภรรยา(คนเจก)")
        with mock.patch.object(screen_tools, "adb_shell",
                               side_effect=lambda a, timeout=30, quote=False: xml if a[:2] == ["uiautomator", "dump"] else "ok"), \
                mock.patch.object(phone_tools, "_fg", return_value="com.instagram.android"):
            b = share_tools.screen_brief()
            self.assertTrue(share_tools.chat_open())
        self.assertIn("ภรรยา(คนเจก)", b)
        self.assertIn("instagram", b)

    def test_honesty_guard(self):
        import agent
        fake = agent._honest("ส่งข้อความหาต้นเรียบร้อยแล้วครับ", {"open_app": "เปิด instagram แล้ว"})
        self.assertIn("ยังไม่ได้ส่ง", fake)
        real = agent._honest("ส่งข้อความหาต้นแล้วครับ", {"send_dm": "ส่งข้อความหา ต้น ใน instagram แล้ว ✅"})
        self.assertEqual(real, "ส่งข้อความหาต้นแล้วครับ")
        self.assertEqual(agent._honest("เปิดไอจีแล้วครับ", {}), "เปิดไอจีแล้วครับ")


class TestFastPath(unittest.TestCase):
    """งานที่สั่งบ่อย: ไม่ใช้ AI หรือใช้ AI รอบเดียว"""

    def test_notifications_direct(self):
        import fastpath
        res = fastpath.direct("อ่านแจ้งเตือนให้หน่อย")
        self.assertIn("[LINE] แม่", res)
        self.assertIn("ตอบได้เลย", res)
        self.assertIsNotNone(fastpath.direct("มีใครทักมาไหม"))
        self.assertIsNone(fastpath.direct("ปิดการแจ้งเตือน line"))

    def test_health_direct(self):
        import fastpath
        res = fastpath.direct("เช็คเครื่องหน่อย")
        self.assertIn("แบต", res)
        self.assertIn("💡", res)

    def test_reply_uses_app_from_notification(self):
        import fastpath, share_tools
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา แม่ ใน line แล้ว ✅") as sd:
            res = fastpath.direct("ตอบแม่ว่ากินแล้ว")
        a = sd.call_args[0][0]
        self.assertEqual((a["app"], a["to"], a["text"]), ("line", "แม่", "กินแล้ว"))
        self.assertIn("✅", res)

    def test_not_triggered_by_normal_commands(self):
        import fastpath
        for t in ("เปิดไฟฉาย", "สวัสดี", "เปิดยูทูป"):
            self.assertIsNone(fastpath.direct(t), t)
            self.assertIsNone(fastpath.prefetch(t), t)

    def test_search_prefetch(self):
        import fastpath, websearch
        with mock.patch.object(websearch, "search", return_value="แกลง ระยอง: ฝนตก 60%") as ws:
            label, data = fastpath.prefetch("เช็คสภาพอากาศวันนี้ที่แกลง ระยอง")
        self.assertIn("ฝนตก", data)
        ws.assert_called_once()
        self.assertIsNone(fastpath.prefetch("ค้นหาไฟล์รายงาน"))


class TestSkills(unittest.TestCase):
    """สกิล: จำปุ่มที่ใช้ได้ + จำขั้นตอนงานที่สำเร็จ แล้วใช้ซ้ำ"""

    def setUp(self):
        self.p = mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp())
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _chat_xml(self, typed=""):
        head = ('<?xml version="1.0"?><hierarchy><node text="" class="x" bounds="[0,0][1838,1570]" '
                'clickable="false" content-desc="" resource-id="">')
        return (head
                + '<node text="ภรรยา" class="t" bounds="[700,40][900,100]" clickable="true" content-desc="" '
                  'resource-id="com.instagram.android:id/thread_title_send_ctx"/>'
                + f'<node text="{typed}" class="android.widget.EditText" bounds="[700,1450][1600,1530]" '
                  'clickable="true" content-desc="" resource-id="com.instagram.android:id/row_thread_composer_edittext"/>'
                + '<node text="ส่ง" class="t" bounds="[1620,1450][1720,1530]" clickable="true" content-desc="" '
                  'resource-id=""/>'
                + "</node></hierarchy>")

    def test_send_button_must_be_in_composer_row(self):
        """ชื่อด้านบน (ไปหน้าโปรไฟล์) ต้องไม่ถูกกด แม้ id จะมีคำว่า send"""
        import share_tools, screen_tools
        st = {"x": self._chat_xml("ฝันดีเพื่อน")}
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            if args[:2] == ["uiautomator", "dump"]:
                return st["x"]
            if args == ["input", "tap", "1670", "1490"]:
                st["x"] = self._chat_xml("")              # ส่งแล้ว ช่องพิมพ์ว่าง
            return "ok"
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb):
            ok, info = share_tools._send_in_chat("instagram", "ฝันดีเพื่อน", None)
        self.assertTrue(ok, info)
        self.assertNotIn(["input", "tap", "800", "70"], calls)
        import skills
        self.assertEqual(skills.ui_recall("instagram", "send")["label"], "ส่ง")

    def test_not_sent_is_reported(self):
        import share_tools, screen_tools
        with mock.patch("time.sleep"), mock.patch.object(
                screen_tools, "adb_shell", side_effect=lambda a, timeout=30, quote=False:
                self._chat_xml("ฝันดีเพื่อน") if a[:2] == ["uiautomator", "dump"] else "ok"):
            ok, info = share_tools._send_in_chat("instagram", "ฝันดีเพื่อน", None)
        self.assertFalse(ok)

    def test_recipe_learn_and_hint(self):
        import skills
        trace = [{"tool": "open_app", "args": {"app": "line", "page": "chat"}, "result": "เปิด line แล้ว"},
                 {"tool": "tap_text", "args": {"text": "ครอบครัว"}, "result": "แตะ ครอบครัว แล้ว"},
                 {"tool": "type_text", "args": {"text": "ถึงบ้านแล้ว"}, "result": "พิมพ์แล้ว → กดส่งแล้ว ✅"}]
        r = skills.record("เข้าไลน์กลุ่มครอบครัวแล้วบอกว่าถึงบ้านแล้ว", trace)
        self.assertIsNotNone(r)
        h = skills.hint("เข้าไลน์กลุ่มครอบครัวแล้วบอกว่ากินข้าวแล้ว")
        self.assertIn("tap_text", h)
        self.assertIsNone(skills.hint("เช็คสภาพอากาศพรุ่งนี้"))
        bad = trace[:1] + [{"tool": "tap_text", "args": {}, "result": "ERROR: ไม่พบ"}]
        self.assertIsNone(skills.record("อะไรสักอย่างที่ล้มเหลว", bad))

    def test_incomplete_send_recipe_not_learned_and_pruned(self):
        import skills
        half = [{"tool": "open_app", "args": {"app": "instagram", "page": "chat"}, "result": "เปิดแล้ว"},
                {"tool": "tap_text", "args": {"text": "ข้อความ"}, "result": "แตะแล้ว"}]
        self.assertIsNone(skills.record("ส่งข้อความหาภรรยาในไอจีว่าฝันดี", half))
        full = half + [{"tool": "send_dm", "args": {"app": "instagram", "to": "ภรรยา", "text": "ฝันดี"},
                        "result": "ส่งข้อความหา ภรรยา ใน instagram แล้ว ✅"}]
        self.assertIsNotNone(skills.record("ส่งข้อความหาภรรยาในไอจีว่าฝันดี", full))
        d = skills._load()                                   # สกิลเสียที่จำไว้จากเวอร์ชันก่อน
        d["recipes"].append({"id": 99, "request": "ส่งข้อความหาต้นในไอจีว่าหวัดดี", "ok": 3, "pinned": False,
                             "steps": [{"tool": "open_app", "args": {}}, {"tool": "tap_text", "args": {}}]})
        skills._save(d)
        self.assertEqual(skills.prune(), 1)
        self.assertIn("send_dm", skills.hint("ส่งข้อความหาต้นในไอจีว่าหวัดดี"))

    def test_retry_uses_last_command(self):
        import agent
        c1 = agent._retry_last([{"type": "text", "text": "ส่งข้อความหาภรรยาในไอจีว่าฝันดี"}])
        self.assertEqual(c1[0]["text"], "ส่งข้อความหาภรรยาในไอจีว่าฝันดี")
        c2 = agent._retry_last([{"type": "text", "text": "[voice hint]"}, {"type": "text", "text": "ลองใหม่สิ"}])
        self.assertEqual(c2[-1]["text"], "ส่งข้อความหาภรรยาในไอจีว่าฝันดี")
        self.assertEqual(c2[0]["text"], "[voice hint]")

    def test_pin_teach_delete_commands(self):
        import skills
        self.assertIn("📌", skills.handle_text("สอนสกิล: ส่งการบ้าน => เปิด LINE ห้อง ม.6/2 แล้วส่งไฟล์ล่าสุด"))
        self.assertIn("ม.6/2", skills.hint("ส่งการบ้านให้หน่อย"))
        self.assertIn("ลบสกิล", skills.handle_text("วิธีนี้ผิด"))
        self.assertIsNone(skills.hint("ส่งการบ้านให้หน่อย"))
        self.assertIn("สกิล", skills.listing())


class TestRouter(unittest.TestCase):
    """AI แยกเจตนา → ระบบลงมือเอง (แม่นกว่าให้ AI กดเองทีละขั้น)"""

    def setUp(self):
        self.ps = [mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp()),
                   mock.patch.object(config, "ROUTER", True), mock.patch.object(config, "QUICK_COMMANDS", True)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def _llm(self, replies):
        import agent
        it = iter(replies)
        calls = []

        def f(history, tools, on_text=None, system=None):
            calls.append({"tools": tools, "system": system or "", "history": history})
            r = next(it)
            if isinstance(r, dict) and "content" in r:
                return r, "Ollama"
            return {"content": [{"type": "text", "text": r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)}],
                    "stop_reason": "end_turn", "usage": {}}, "Ollama"
        return mock.patch.object(agent, "call_llm", side_effect=f), calls

    def _ctx(self):
        return type("C", (), {"status": lambda *a: None})()

    def test_voice_style_message_is_sent_by_system(self):
        import agent, share_tools
        p, calls = self._llm([{"intent": "send_message", "app": "ไอจี", "to": "ภรรยาคนเจ็ด", "text": "ฝันดีนะ"}])
        with p, mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา ภรรยา ใน instagram แล้ว ✅") as sd:
            res = agent.chat(1, "เอ่อ ไปบอกภรรยาคนเจ็ดในไอจีหน่อยนะ ว่าฝันดีนะ", self._ctx())
        self.assertEqual(sd.call_args[0][0], {"app": "instagram", "to": "ภรรยาคนเจ็ด", "text": "ฝันดีนะ"})
        self.assertIn("✅", res)
        self.assertEqual(len(calls), 1)                         # AI แค่ครั้งเดียว (แยกเจตนา)
        self.assertEqual(calls[0]["tools"], [])

    def test_send_without_app_uses_last_app(self):
        import agent, share_tools, skills
        skills.set_pref("dm_app", "line")
        p, _ = self._llm([{"intent": "send_message", "app": "", "to": "แม่", "text": "ถึงแล้ว"}])
        with p, mock.patch.object(share_tools, "send_dm", return_value="ส่งข้อความหา แม่ ใน line แล้ว ✅") as sd:
            agent.chat(2, "บอกแม่ทีว่าถึงแล้ว", self._ctx())
        self.assertEqual(sd.call_args[0][0]["app"], "line")

    def test_send_photo(self):
        import agent, share_tools
        p, _ = self._llm([{"intent": "send_file", "app": "line", "to": "แม่", "file": "รูปล่าสุด", "text": ""}])
        with p, mock.patch.object(share_tools, "send_to_app", return_value="• photo.jpg: กดส่งแล้ว ✅") as st:
            res = agent.chat(3, "ส่งรูปเมื่อกี้ให้แม่ในไลน์", self._ctx())
        a = st.call_args[0][0]
        self.assertEqual((a["app"], a["files"], a["to"]), ("line", ["รูปล่าสุด"], "แม่"))
        self.assertIn("กดส่งแล้ว", res)

    def test_search_then_answer_once(self):
        import agent, websearch
        p, calls = self._llm([{"intent": "search", "query": "อากาศระยองพรุ่งนี้"}, "พรุ่งนี้ระยองฝนตก 60% พกร่มนะครับ"])
        with p, mock.patch.object(websearch, "search", return_value="ระยอง: ฝนตก 60%"):
            res = agent.chat(4, "พรุ่งนี้ระยองฝนตกไหม", self._ctx())
        self.assertIn("ฝนตก", res)
        self.assertEqual(calls[1]["tools"], [])
        self.assertIn("ระยอง: ฝนตก 60%", json.dumps(calls[1]["history"][-1], ensure_ascii=False))

    def test_analyze_file(self):
        import agent, files_tools
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "report_q3.txt"), "w") as f:
            f.write("ยอดขายไตรมาส 3 เพิ่มขึ้น 12%")
        p, calls = self._llm([{"intent": "analyze_file", "file": "report", "question": "สรุป"}, "ยอดขายเพิ่ม 12%"])
        with p, mock.patch.object(files_tools, "roots", return_value=[d]):
            res = agent.chat(5, "สรุปไฟล์ report ให้หน่อย", self._ctx())
        self.assertEqual(res, "ยอดขายเพิ่ม 12%")
        self.assertIn("ยอดขายไตรมาส 3", json.dumps(calls[1]["history"][-1], ensure_ascii=False))

    def test_setting_and_chat(self):
        import agent, phone_tools
        p, _ = self._llm([{"intent": "setting", "setting": "brightness", "value": "30"}])
        fake = mock.MagicMock(return_value="ตั้งความสว่าง 30% แล้ว")
        with p, mock.patch.dict(phone_tools.TOOLS, {"brightness": (fake, "", {}, False)}):
            res = agent.chat(6, "หรี่จอเหลือสามสิบ", self._ctx())
        self.assertEqual(fake.call_args[0][0], {"level": "30%"})
        self.assertIn("30%", res)
        p, calls = self._llm(["สวัสดีครับ วันนี้เป็นไงบ้าง"])
        with p:
            self.assertIn("สวัสดี", agent.chat(7, "หวัดดี", self._ctx()))   # ทักทาย → คุยเลย ไม่ต้องแยกเจตนา
        self.assertEqual(len(calls), 1)
        self.assertIn("ตอบคำถาม", calls[0]["system"])
        p, calls = self._llm([{"intent": "chat"}, "แนะนำให้นอนเร็วขึ้นครับ"])
        with p:
            agent.chat(7, "ช่วงนี้นอนไม่หลับทำไงดี", self._ctx())
        self.assertIn("ตอบคำถาม", calls[1]["system"])

    def test_phone_task_uses_lean_tools(self):
        import agent
        fake = {"content": [{"type": "text", "text": "เล่นให้แล้วครับ"}], "stop_reason": "end_turn", "usage": {}}
        p, calls = self._llm([{"intent": "phone_task", "goal": "เปิดยูทูปแล้วกดไลก์คลิปล่าสุด"}, fake, fake])
        with p:
            reply = agent.chat(8, "เปิดยูทูปแล้วกดไลก์คลิปล่าสุด", self._ctx())
        self.assertIn("ยังไม่ได้ทำจริง", reply)          # อ้างว่าทำแล้วทั้งที่ไม่ได้เรียกเครื่องมือ → ไม่ส่งคำตอบปลอม
        names = [t.get("name") for t in calls[1]["tools"]]
        self.assertIn("send_dm", names)
        self.assertIn("play_media", names)
        self.assertLessEqual(len(names), 25)

    def test_quick_commands_skip_ai(self):
        import agent
        p, calls = self._llm([])
        with p:
            agent.chat(9, "เปิดไฟฉาย", self._ctx())
        self.assertEqual(calls, [])


class TestVoiceOwner(unittest.TestCase):
    """ฟังเฉพาะเสียงเจ้าของ + โหมดฟังตลอด (ไม่ต้องเรียกคำปลุก)"""

    def setUp(self):
        self.p = mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp())
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _voice(self, rng, f0, scale):
        import numpy as np
        try:
            from scipy.signal import lfilter
        except ImportError:
            self.skipTest("ไม่มี scipy")
        vow = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480)]
        out = []
        for _ in range(8):
            n = 4000
            src = np.zeros(n)
            src[::int(16000 / (f0 * (1 + 0.05 * rng.standard_normal())))] = 1
            y = lfilter([1], [1, -0.95], src) + 0.02 * rng.standard_normal(n)
            for F, bw in zip(np.array(vow[rng.integers(4)]) * scale, (80, 100, 120)):
                r, th = np.exp(-np.pi * bw / 16000), 2 * np.pi * F / 16000
                y = lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], y)
            out.append(y)
        y = np.concatenate(out)
        return (y / np.abs(y).max() * 12000).astype(np.int16).tobytes()

    def test_owner_vs_other_voice(self):
        import numpy as np
        import speaker_id
        rng = np.random.default_rng(0)
        self.assertEqual(speaker_id.check(b"x" * 100), (True, None))          # ยังไม่สอนเสียง = ผ่าน
        speaker_id.enroll([self._voice(rng, 120, 1.0) for _ in range(6)])
        self.assertTrue(all(speaker_id.check(self._voice(rng, 120, 1.0))[0] for _ in range(4)))
        self.assertFalse(any(speaker_id.check(self._voice(rng, 210, 1.18))[0] for _ in range(4)))

    def test_listen_mode_toggle(self):
        import quick
        self.assertIn("ฟังตลอด", quick.listen_mode("เปิดโหมดฟังตลอด"))
        self.assertTrue(os.path.exists(os.path.join(config.DATA_DIR, "always_listen")))
        self.assertIn("คำปลุก", quick.listen_mode("ปิดโหมดฟังตลอด"))
        self.assertFalse(os.path.exists(os.path.join(config.DATA_DIR, "always_listen")))
        self.assertIsNone(quick.listen_mode("เปิดไอจี"))

    def test_ambient_talk_is_ignored(self):
        import agent
        calls = []

        def f(history, tools, on_text=None, system=None):
            calls.append(history[-1]["content"][-1]["text"])
            return {"content": [{"type": "text", "text": '{"intent": "ignore"}'}], "usage": {}}, "Ollama"
        ctx = type("C", (), {"status": lambda *a: None, "ambient": True})()
        with mock.patch.object(config, "ROUTER", True), mock.patch.object(agent, "call_llm", side_effect=f):
            self.assertEqual(agent.chat(31, "เดี๋ยวพรุ่งนี้ไปกินข้าวกันนะแม่", ctx), "")
        self.assertIn("โหมดฟังตลอด", calls[0])


class TestFastScreen(unittest.TestCase):
    """อ่านจอ/พิมพ์แบบเร็วด้วย uiautomator2 และกลับไปวิธีเดิมเองถ้าใช้ไม่ได้"""

    def test_fast_dump_and_typing(self):
        import screen_tools
        typed = []

        class El:
            exists = True

            def set_text(self, t):
                typed.append(t)

        class D:
            def dump_hierarchy(self, compressed=False):
                return screen_tools._MOCK_XML

            def __call__(self, **kw):
                return El()
        with mock.patch.object(screen_tools, "u2", return_value=D()), \
                mock.patch.object(screen_tools, "_dump_slow") as slow, \
                mock.patch.object(screen_tools, "adb_shell", return_value="ok"), mock.patch("time.sleep"):
            root = screen_tools._dump()
            self.assertTrue(any(e["text"] == "แม่" for e in screen_tools._elements(root)))
            slow.assert_not_called()
            screen_tools.type_text({"text": "สวัสดีครับ", "send": False}, None)
        self.assertEqual(typed, ["สวัสดีครับ"])

    def test_fallback_when_u2_breaks(self):
        import screen_tools

        class D:
            def dump_hierarchy(self, compressed=False):
                raise RuntimeError("server died")
        with mock.patch.object(screen_tools, "u2", return_value=D()), \
                mock.patch.object(screen_tools, "_dump_slow", return_value="SLOW") as slow:
            self.assertEqual(screen_tools._dump(), "SLOW")
        slow.assert_called_once()


class TestBugfixes(unittest.TestCase):
    """บั๊กที่เจอตอนตรวจระบบ"""

    def setUp(self):
        self.p = mock.patch.object(config, "DATA_DIR", tempfile.mkdtemp())
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_loose_type_here_is_safe(self):
        import quick, share_tools
        with mock.patch.object(share_tools, "chat_open", return_value=True), \
                mock.patch.object(share_tools, "send_here") as sh:
            for t in ("ตอบคำถามนี้หน่อย", "พิมพ์อะไรดี", "ตอบให้หน่อยว่าทำไมฟ้าสีฟ้า"):
                quick.dm(t)
            sh.assert_not_called()
            sh.return_value = "ส่งในห้องแชทที่เปิดอยู่แล้ว ✅"
            quick.dm("ตอบไปว่าโอเค")
            quick.dm("ตอบ ได้เลย แล้วกดส่ง")
        self.assertEqual([c[0][0] for c in sh.call_args_list], ["โอเค", "ได้เลย"])

    def test_today_does_not_trigger_screen_read(self):
        import agent
        self.assertIsNone(agent._ONSCREEN.search("อากาศวันนี้เป็นไง"))
        self.assertIsNotNone(agent._ONSCREEN.search("บอกเขาว่าเดี๋ยวไปรับ"))

    def test_last_sender_from_live_notifications(self):
        import share_tools, fastpath
        items = [{"packageName": "jp.naver.line.android", "title": "แม่ (2)", "content": "กินข้าวยัง"}]
        with mock.patch.object(fastpath, "_notif_items", return_value=(items, "")):
            self.assertEqual(share_tools.last_sender()["to"], "แม่")
            self.assertEqual(share_tools.last_sender()["app"], "line")

    def test_follow_up_answer_uses_context(self):
        """บอทถาม 'จะส่งทางแอปไหนดี?' → ผู้ใช้ตอบ 'ไลน์' → ตัวแยกเจตนาต้องเห็นคำสั่งเดิม"""
        import agent
        h = [{"role": "user", "content": [{"type": "text", "text": f"[เวลา: {agent.now_local().strftime('%a %d/%m/%Y %H:%M')}]"},
                                          {"type": "text", "text": "ส่งข้อความหาแม่ว่าถึงแล้ว"}]},
             {"role": "assistant", "content": [{"type": "text", "text": "จะส่งทางแอปไหนดีครับ?"}]}]
        ctx = agent._recent_context(h)
        self.assertIn("ส่งข้อความหาแม่", ctx)
        self.assertIn("แอปไหน", ctx)
        h[-1] = {"role": "assistant", "content": [{"type": "text", "text": "ส่งแล้วครับ"}]}
        self.assertIn("ส่งแล้ว", agent._recent_context(h))          # คุยต่อเนื่องภายใน 5 นาที
        old = (agent.now_local() - __import__("datetime").timedelta(minutes=8)).strftime('%a %d/%m/%Y %H:%M')
        h[0]["content"][0]["text"] = f"[เวลา: {old}]"
        self.assertEqual(agent._recent_context(h), "")                # เกิน 5 นาที และไม่ได้ถามค้าง → ไม่ใช้

    def test_open_app_page_failure_is_reported(self):
        import router, phone_tools
        with mock.patch.object(phone_tools, "open_app",
                               return_value="เปิด instagram แล้ว แต่เข้าหน้า chat ไม่ได้ (หาปุ่มไม่เจอ)"):
            r = router.execute({"intent": "open_app", "app": "instagram", "page": "chat"}, None)
        self.assertIn("ไม่ได้", r)


class TestDeviceControls(unittest.TestCase):
    """ปิดได้ทุกอย่าง: ห้ามรบกวน, ลดเสียง, ปิดแอปใน GBox, รับ/วางสายจากแอป"""

    def test_volume_quick(self):
        import quick, phone_tools, screen_tools
        calls = []
        with mock.patch.object(screen_tools, "adb_serial", return_value="s"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: calls.append(a) or "ok"):
            self.assertIn("ลดเสียง", quick.handle("ลดเสียงหน่อย"))
            self.assertIn("เพิ่มเสียง", quick.handle("เสียงดังขึ้น"))
        self.assertIn(["input", "keyevent", "25", "25", "25"], calls)
        self.assertIn(["input", "keyevent", "24", "24", "24"], calls)

    def test_dnd_off_has_settings_fallback(self):
        import system_tools
        cmds = []
        with mock.patch.object(system_tools, "_adb", return_value=True), \
                mock.patch.object(system_tools, "_state", side_effect=[True, True, True, False]), \
                mock.patch.object(system_tools, "_first_ok", side_effect=lambda c, **k: cmds.append(c) or (True, "ok")), \
                mock.patch("time.sleep"):
            res = system_tools.do_not_disturb({"on": False}, None)
        self.assertIn("ปิด", res)
        self.assertIn(["settings", "put", "global", "zen_mode", "0"], cmds[0])

    def test_close_instagram_uses_real_package(self):
        import phone_tools, screen_tools, app_index
        calls = []
        with mock.patch.object(screen_tools, "adb_serial", return_value="s"), \
                mock.patch.object(app_index, "find", side_effect=lambda n: ("com.gbox.android", "GBox") if n == "gbox" else (None, None)), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: calls.append(a) or "ok"):
            phone_tools.close_app({"app": "ไอจี"}, None)
        self.assertIn(["am", "force-stop", "com.instagram.android"], calls)

    def test_answer_app_call_and_decline_matching(self):
        import screen_tools
        xml = ('<?xml version="1.0"?><hierarchy><node text="" class="x" bounds="[0,0][1000,2000]" clickable="false" '
               'content-desc="" resource-id="">'
               '<node text="ส่ง" class="b" bounds="[0,0][100,100]" clickable="true" content-desc="" resource-id="send"/>'
               '<node text="" class="b" bounds="[100,1700][300,1900]" clickable="true" content-desc="ปฏิเสธ" resource-id=""/>'
               '<node text="" class="b" bounds="[700,1700][900,1900]" clickable="true" content-desc="รับสาย" resource-id=""/>'
               '</node></hierarchy>')
        calls = []
        with mock.patch.object(screen_tools, "adb_shell",
                               side_effect=lambda a, **k: calls.append(a) or (xml if a[:2] == ["uiautomator", "dump"] else "ok")), \
                mock.patch("time.sleep"):
            self.assertIn("รับสายแล้ว", screen_tools.answer_call({}, None))
            self.assertIn(["input", "tap", "800", "1800"], calls)
            self.assertIn("วางสายแล้ว", screen_tools.end_call({}, None))
            self.assertIn(["input", "tap", "200", "1800"], calls)
            self.assertNotIn(["input", "tap", "50", "50"], calls)      # ห้ามแตะปุ่ม "ส่ง"


class TestWakeFromLog(unittest.TestCase):
    """จาก voice.log จริง: 'เฮ้ย พุชไว' = เรียกผู้ช่วย / เสียงทีวี 'โอป้า' ไม่ต้องเรียก AI"""

    def test_garbled_wake_words(self):
        import voice_chat as v
        for t in ("เฮ้ย พุชไว", "เฮ้ บุชไว้", "เฮ้ย บูชัย", "เฮ้ บุชเว้"):
            self.assertTrue(v.find_wake(t)[0], t)
        self.assertEqual(v.find_wake("เฮ้ บุชไว้ เปิดไลน์"), (True, "เปิดไลน์"))
        for t in ("โอป้า", "ไปกินข้าวกัน", "ที่มีหลายแฟน"):
            self.assertFalse(v.find_wake(t)[0], t)

    def test_ambient_prefilter(self):
        import voice_chat as v
        for t in ("โอป้า", "ที่มีหลายแฟน", "ตกนะครับ เอาไว้ด้วย"):
            self.assertIsNone(v._COMMANDISH.search(t), t)
        for t in ("เปิดไฟฉายหน่อย", "พรุ่งนี้ฝนตกไหม", "ส่งข้อความหาแม่"):
            self.assertIsNotNone(v._COMMANDISH.search(t), t)


class TestShare(unittest.TestCase):
    """ส่งรูป/วิดีโอ/ไฟล์เข้าแอปไหนก็ได้ + เลือกผู้รับ + กดส่ง, กันไฟล์ลับ"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = mock.patch.object(config, "DATA_DIR", self.d)
        self.p.start()
        os.makedirs(os.path.join(self.d, "inbox"))
        self.img = os.path.join(self.d, "inbox", "photo_1.jpg")
        open(self.img, "wb").write(b"x")
        self.vid = os.path.join(self.d, "inbox", "video_1.mp4")
        open(self.vid, "wb").write(b"x")

    def tearDown(self):
        self.p.stop()

    def test_resolve_latest_by_kind(self):
        import share_tools
        os.utime(self.img, (1, 1))
        self.assertEqual(share_tools.resolve("รูปล่าสุด"), self.img)
        self.assertEqual(share_tools.resolve("คลิปล่าสุด"), self.vid)

    def test_blocks_secrets(self):
        import share_tools
        env = os.path.join(self.d, ".env")
        open(env, "w").write("KEY=1")
        self.assertTrue(share_tools._blocked(env))
        self.assertTrue(share_tools._blocked(os.path.join(self.d, "apps.json")))
        self.assertFalse(share_tools._blocked(self.img))
        res = share_tools.send_to_app({"app": "line", "files": [env]}, None)
        self.assertTrue(res.startswith("ERROR"))

    def test_send_photo_to_contact_in_line(self):
        import share_tools, screen_tools, phone_tools
        calls = []

        def adb(args, timeout=30, quote=False):
            calls.append(list(args))
            return screen_tools._MOCK_XML if args[:2] == ["uiautomator", "dump"] else "Starting: Intent"
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_shell", side_effect=adb), \
                mock.patch.object(phone_tools, "_launcher_components", return_value=["jp.naver.line.android/.Main"]):
            res = share_tools.send_to_app({"app": "ไลน์", "files": ["รูปล่าสุด"], "to": "แม่"}, None)
        self.assertIn("กดส่งแล้ว", res)
        send = next(c for c in calls if "android.intent.action.SEND" in c)
        self.assertIn("android.intent.extra.STREAM", send)
        self.assertIn("jp.naver.line.android", send)
        self.assertIn("--grant-read-uri-permission", send)
        self.assertIn(["input", "tap", "250", "230"], calls)      # แตะชื่อ "แม่"
        self.assertIn(["input", "tap", "2325", "1500"], calls)    # ปุ่มส่ง

    def test_hold_does_not_press_send(self):
        import share_tools, screen_tools, phone_tools

        class C:
            hold = True
        with mock.patch("time.sleep"), \
                mock.patch.object(screen_tools, "adb_shell",
                                  side_effect=lambda a, timeout=30, quote=False:
                                  screen_tools._MOCK_XML if a[:2] == ["uiautomator", "dump"] else "Starting"), \
                mock.patch.object(phone_tools, "_launcher_components", return_value=[]):
            res = share_tools.send_to_app({"app": "line", "files": ["รูปล่าสุด"]}, C())
        self.assertIn("ยังไม่กดส่ง", res)

    def test_tools_registered(self):
        import phone_tools
        for n in ("send_to_app", "ask_ai_app", "prepare_upload"):
            self.assertIn(n, phone_tools.TOOLS)
        names = [t["name"] for t in phone_tools.relevant_tool_specs("ส่งรูปนี้ให้แม่ในไลน์")]
        self.assertIn("send_to_app", names)
        self.assertEqual(phone_tools.ALIASES["คลอด"], "claude")


class TestVoiceProfile(unittest.TestCase):
    """เสียง/บุคลิกเหมือนคน: เลือกเสียงด้วย /voice, ครับ/ค่ะ ตามเพศ, เสียง Gemini สำรองอัตโนมัติ"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ps = [mock.patch.object(config, k, v) for k, v in (
            ("DATA_DIR", self.d), ("BASE_DIR", self.d), ("TTS_ENGINE", "edge"), ("TTS_VOICE", "th-TH-NiwatNeural"),
            ("TTS_RATE", "+5%"), ("TTS_PITCH", "-2Hz"), ("BOT_GENDER", "male"), ("GEMINI_TTS_VOICE", "Puck"),
            ("GEMINI_API_KEY", "AQ.k"))]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    @mock.patch.dict(os.environ, {"POLITE": "auto"})
    def test_female_voice_changes_particles_and_prompt(self):
        import voice_profile, agent
        self.assertIn("✅", voice_profile.apply("female"))
        self.assertEqual(config.TTS_VOICE, "th-TH-PremwadeeNeural")
        self.assertEqual(voice_profile.pol(), "ค่ะ")
        self.assertTrue(voice_profile.ack_word().endswith(("ค่ะ", "ได้เลย")))
        self.assertIn('แทนตัวเองว่า "ฉัน"', agent._base_prompt())
        self.assertIn("BOT_GENDER=female", open(os.path.join(self.d, ".env")).read())

    def test_other_process_picks_up_voice(self):
        import voice_profile, json as _j
        voice_profile._last["mtime"] = 0
        with open(os.path.join(self.d, "voice.json"), "w") as f:
            _j.dump({"TTS_ENGINE": "gemini", "GEMINI_TTS_VOICE": "Aoede", "BOT_GENDER": "female"}, f)
        voice_profile.sync()
        self.assertEqual((config.TTS_ENGINE, config.GEMINI_TTS_VOICE), ("gemini", "Aoede"))

    def test_human_persona_in_prompt(self):
        import agent
        p = agent._base_prompt()
        self.assertIn("ไม่ใช้ภาษาทางการ", p)
        self.assertIn("ดำเนินการเรียบร้อยแล้ว", p)          # อยู่ในรายการคำที่ห้ามใช้

    def test_gemini_tts_writes_audio_and_falls_back(self):
        import voice, base64, wave
        pcm = b"\x00\x01" * 24000
        reply = {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}
        out = os.path.join(self.d, "t.wav")
        with mock.patch("gemini_client._post", return_value=reply) as post:
            voice._gemini_tts("สวัสดีครับ", out)
        body = post.call_args[0][1]
        self.assertEqual(body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"],
                         "Puck")
        self.assertIn("warm", body["contents"][0]["parts"][0]["text"])
        with wave.open(out) as w:
            self.assertEqual((w.getframerate(), w.getnframes()), (24000, 24000))
        # โควตาหมด → ใช้ Microsoft แทน และพักเรียก Gemini 1 ชม.
        voice._gem_err["until"] = 0
        with mock.patch.object(config, "TTS_ENGINE", "gemini"), mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch("gemini_client._post", side_effect=RuntimeError("429 quota")), \
                mock.patch.object(voice, "_edge_tts", side_effect=lambda t, p: open(p, "wb").write(b"0" * 900)) as edge:
            path = voice.synthesize("ทดสอบ", os.path.join(self.d, "x.mp3"))
        self.assertTrue(edge.called)
        self.assertGreater(voice._gem_err["until"] - time.time(), 3000)
        voice._gem_err["until"] = 0

    def test_voice_buttons(self):
        bot.tg = FakeTG()
        bot.tg.answer_callback = lambda *a, **k: None
        with mock.patch.object(bot, "_voice_sample"):
            bot.handle_callback({"id": "q", "data": "voice:male_slow", "from": {"id": 111},
                                 "message": {"chat": {"id": 111}, "message_id": 1}})
        self.assertIn("ใจเย็น", bot.tg.sent[-1])
        self.assertEqual(config.TTS_RATE, "-5%")


class TestQuick(unittest.TestCase):
    """คำสั่งด่วน: ทำทันทีไม่ผ่าน AI ส่วนประโยคซับซ้อนส่งให้ AI"""

    def setUp(self):
        self.p = mock.patch.object(config, "QUICK_COMMANDS", True)
        self.p.start()
        self.calls = []
        import phone_tools
        self.orig = dict(phone_tools.TOOLS)

        def fake(name, out):
            def f(a, ctx):
                self.calls.append((name, a))
                return out
            return f
        for name, out in (("open_app", "เปิด com.google.android.youtube\nOK"), ("close_app", "ปิด YouTube แล้ว"),
                          ("wifi", "เปิด Wi-Fi แล้ว"), ("bluetooth", "ปิด บลูทูธ แล้ว"),
                          ("brightness", "ตั้งความสว่าง 50% แล้ว"),
                          ("battery_status", '{"percentage": 77, "status": "CHARGING", "temperature": 31.2}')):
            entry = phone_tools.TOOLS[name]
            phone_tools.TOOLS[name] = (fake(name, out),) + tuple(entry[1:])

    def tearDown(self):
        import phone_tools
        phone_tools.TOOLS.clear(); phone_tools.TOOLS.update(self.orig)
        self.p.stop()

    def test_simple_commands_skip_ai(self):
        import quick
        self.assertEqual(quick.handle("เปิดยูทูปให้หน่อยครับ"), "เปิด ยูทูป แล้วครับ")
        self.assertEqual(self.calls[-1], ("open_app", {"app": "ยูทูป"}))
        self.assertEqual(quick.handle("ช่วยเปิด wifi ที"), "เปิด Wi-Fi แล้ว")
        self.assertEqual(self.calls[-1], ("wifi", {"on": True}))
        quick.handle("ปิดบลูทูธ")
        self.assertEqual(self.calls[-1], ("bluetooth", {"on": False}))
        quick.handle("ความสว่าง 50%")
        self.assertEqual(self.calls[-1], ("brightness", {"level": "50%"}))
        quick.handle("ลดแสงหน้าจอหน่อย")
        self.assertEqual(self.calls[-1], ("brightness", {"level": "-20%"}))
        self.assertIn("แบตเหลือ 77% (กำลังชาร์จ)", quick.handle("แบตเหลือเท่าไหร่"))

    def test_complex_goes_to_ai(self):
        import quick
        for t in ("เปิดยูทูปแล้วกดไลก์คลิปล่าสุด", "เปิดเพลงในยูทูป", "สวัสดี", "ส่งข้อความหาแม่ว่าเปิดไลน์ด้วย",
                  "ปิด wifi 10 นาที", "อากาศวันนี้เป็นไง"):
            self.assertIsNone(quick.handle(t), t)

    def test_unknown_app_falls_back_to_ai(self):
        import quick, phone_tools
        phone_tools.TOOLS["open_app"] = (lambda a, c: "ERROR: ไม่พบแอป 'xyz'",) + tuple(self.orig["open_app"][1:])
        self.assertIsNone(quick.handle("เปิด xyz"))

    def test_bot_answers_without_calling_ai(self):
        bot.tg = FakeTG()
        with mock.patch("claude_client.requests.Session.post") as post:
            bot.handle_message(msg("เปิดยูทูป"))
        post.assert_not_called()
        self.assertTrue(bot.tg.sent[-1].startswith("เปิด ยูทูป แล้วครับ"))


class TestLoopGuard(unittest.TestCase):
    def test_repeated_tool_calls_are_not_rerun_and_summarized(self):
        same = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "x", "name": "torch",
                                                        "input": {"on": True}}]}
        fake, calls = claude_seq(dict(same), dict(same), dict(same),        # วนซ้ำ 3 รอบ → ตัดจบ
                                 {"stop_reason": "end_turn", "content": [{"type": "text", "text": "สรุป: เปิดไฟฉายแล้ว"}]})
        bot.tg = FakeTG()
        import phone_tools
        ran = []
        orig = phone_tools.TOOLS["torch"]
        phone_tools.TOOLS["torch"] = (lambda a, c: ran.append(a) or "เปิดไฟฉายแล้ว",) + tuple(orig[1:])
        try:
            with mock.patch("claude_client.requests.Session.post", fake):
                bot.handle_message(msg("ทำให้ห้องสว่างหน่อย"))
        finally:
            phone_tools.TOOLS["torch"] = orig
        self.assertEqual(len(ran), 1)                      # รันจริงครั้งเดียว
        self.assertIn("สรุป: เปิดไฟฉายแล้ว", bot.tg.sent[-1])
        self.assertNotIn("หยุดเพราะ", bot.tg.sent[-1])

    def test_local_model_gets_relevant_tools_only(self):
        import phone_tools
        base = phone_tools.relevant_tool_specs("สวัสดี")
        names = {t["name"] for t in base}
        self.assertIn("open_app", names)
        self.assertNotIn("rotate_screen", names)
        self.assertLess(len(base), len(phone_tools.claude_tool_specs()))
        more = {t["name"] for t in phone_tools.relevant_tool_specs("หมุนจอเป็นแนวนอน")}
        self.assertIn("rotate_screen", more)


class TestAutoSend(unittest.TestCase):
    """พิมพ์แล้วกดส่งให้เอง (ไม่ต้องสั่ง 'ส่ง' อีกรอบ)"""

    def _run(self, args, hold=False):
        import screen_tools
        sent = []
        orig = screen_tools.adb_shell

        def fake(a, timeout=30):
            sent.append(list(a))
            return orig(a, timeout=timeout)
        ctx = bot.Ctx(111)
        ctx.hold = hold
        with mock.patch.object(screen_tools, "adb_shell", side_effect=fake):
            res = screen_tools.type_text(args, ctx)
        return res, sent

    def test_types_then_taps_send_button(self):
        res, sent = self._run({"text": "ถึงบ้านแล้ว"})
        self.assertIn("กดส่งแล้ว", res)
        self.assertIn(["input", "tap", "2325", "1500"], sent)            # ปุ่มส่งของ LINE (id=send)

    def test_hold_does_not_send(self):
        res, sent = self._run({"text": "x"}, hold=True)
        self.assertIn("ยังไม่กดส่ง", res)
        self.assertFalse(any(c[:2] == ["input", "tap"] for c in sent))

    def test_send_false_and_search_enter(self):
        res, sent = self._run({"text": "x", "send": False})
        self.assertIn("ยังไม่ส่ง", res)
        res, sent = self._run({"text": "lofi", "press_enter": True})
        self.assertIn("กด Enter", res)
        self.assertFalse(any(c[:2] == ["input", "tap"] for c in sent))


class TestFiles(unittest.TestCase):
    def setUp(self):
        import zipfile
        self.d = tempfile.mkdtemp()
        self.p = mock.patch("files_tools.roots", return_value=[self.d])
        self.p.start()
        docx = os.path.join(self.d, "รายงานประชุม.docx")
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>วาระที่ 1 งบประมาณ</w:t></w:r></w:p>'
                                            '<w:p><w:r><w:t>สรุป: อนุมัติ 50,000 บาท</w:t></w:r></w:p></w:body></w:document>')
        xlsx = os.path.join(self.d, "ยอดขาย.xlsx")
        with zipfile.ZipFile(xlsx, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="มกราคม" sheetId="1"/></sheets></workbook>')
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>สินค้า</t></si><si><t>ยอด</t></si><si><t>กาแฟ</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1200</v></c></row></sheetData></worksheet>')
        pptx = os.path.join(self.d, "slide.pptx")
        with zipfile.ZipFile(pptx, "w") as z:
            z.writestr("ppt/slides/slide2.xml", "<p:sld><a:p><a:t>หัวข้อสอง</a:t></a:p></p:sld>")
            z.writestr("ppt/slides/slide1.xml", "<p:sld><a:p><a:t>หัวข้อหนึ่ง</a:t></a:p></p:sld>")
        with open(os.path.join(self.d, "note.txt"), "w", encoding="utf-8") as f:
            f.write("ก" * 30000)
        with open(os.path.join(self.d, ".env"), "w") as f:
            f.write("ANTHROPIC_API_KEY=secret")

    def tearDown(self):
        self.p.stop()

    def test_reads_office_files(self):
        import files_tools as ft
        self.assertIn("อนุมัติ 50,000 บาท", ft.tool_read({"path": "รายงานประชุม.docx"}, None))
        x = ft.tool_read({"path": os.path.join(self.d, "ยอดขาย.xlsx")}, None)
        self.assertIn("ชีต มกราคม", x)
        self.assertIn("กาแฟ | 1200", x)
        sl = ft.tool_read({"path": os.path.join(self.d, "slide.pptx")}, None)
        self.assertLess(sl.index("หัวข้อหนึ่ง"), sl.index("หัวข้อสอง"))       # เรียงสไลด์ถูก

    def test_long_file_paged(self):
        import files_tools as ft
        r = ft.tool_read({"path": os.path.join(self.d, "note.txt")}, None)
        self.assertIn("อ่านต่อด้วย start=12000", r)

    def test_find_and_secret_blocked(self):
        import files_tools as ft
        self.assertIn("รายงานประชุม.docx", ft.tool_find({"query": "รายงาน"}, None))
        self.assertNotIn(".env", ft.tool_find({"query": ""}, None))
        self.assertIn("อ่านไม่ได้", ft.tool_read({"path": os.path.join(self.d, ".env")}, None))

    def test_telegram_document_is_summarized(self):
        fake, calls = claude_seq({"stop_reason": "end_turn", "content": [{"type": "text", "text": "สรุปแล้ว"}]})
        bot.tg = FakeTG()
        with open(os.path.join(self.d, "รายงานประชุม.docx"), "rb") as f:
            data = f.read()
        bot.tg.download_file = lambda fid: (data, "documents/x.docx")
        bot.tg.send_chat_action = lambda *a, **k: None
        m = msg("")
        m["document"] = {"file_id": "F1", "file_name": "รายงานประชุม.docx", "file_size": len(data)}
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(m)
        user_text = json.dumps(calls[0]["messages"][-1], ensure_ascii=False)
        self.assertIn("อนุมัติ 50,000 บาท", user_text)                  # เนื้อหาไฟล์ส่งให้ AI แล้ว
        self.assertIn("สรุปแล้ว", bot.tg.sent[-1])


class TestProviders(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ps = [mock.patch.object(config, "DATA_DIR", self.d), mock.patch.object(config, "BASE_DIR", self.d),
                   mock.patch.object(config, "LLM_PROVIDER", "ollama"), mock.patch.object(config, "GROQ_API_KEY", "")]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def test_switch_by_words_and_persist(self):
        import providers
        self.assertIn("สลับไปใช้", providers.from_text("สลับไปใช้ claude ครับ"))
        self.assertEqual(config.LLM_PROVIDER, "claude")
        self.assertIn("LLM_PROVIDER=claude", open(os.path.join(self.d, ".env")).read())
        self.assertIn("ไม่ได้", providers.switch("groq"))                      # ไม่มีคีย์ → ไม่สลับ
        self.assertEqual(config.LLM_PROVIDER, "claude")
        self.assertIsNone(providers.from_text("ใช้ google ค้นหาร้านกาแฟแถวบ้าน"))

    def test_other_process_sees_switch(self):
        import providers
        providers._last["mtime"] = 0
        with open(os.path.join(self.d, "provider.txt"), "w") as f:
            f.write("claude")
        self.assertEqual(providers.sync(), "claude")

    def test_ai_button(self):
        bot.tg = FakeTG()
        bot.tg.answer_callback = lambda *a, **k: None
        bot.handle_callback({"id": "q", "data": "ai:claude", "from": {"id": 111},
                             "message": {"chat": {"id": 111}, "message_id": 1}})
        self.assertIn("Claude", bot.tg.sent[-1])
        self.assertEqual(config.LLM_PROVIDER, "claude")


class TestBalance(unittest.TestCase):
    """ยอด API คงเหลือ: ตั้งครั้งเดียว แล้วหักตามที่ใช้จริง แสดงท้ายข้อความทุกครั้ง"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ps = [mock.patch.object(config, "DATA_DIR", self.d),
                   mock.patch.object(config, "CLAUDE_MODEL", "claude-haiku-4-5"),
                   mock.patch.object(config, "USD_THB", 33.5),
                   mock.patch.object(config, "SHOW_BALANCE", True)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        import agent
        agent._fallback_until[0] = 0; agent._fallback_to[0] = "groq"

    def test_balance_command_and_footer_after_chat(self):
        bot.tg = FakeTG()
        bot.handle_message(msg("/balance $4.85"))
        self.assertIn("ตั้งยอดแล้ว", bot.tg.sent[-1])
        self.assertIn("$4.85", bot.tg.sent[-1])
        fake, _ = claude_seq({"stop_reason": "end_turn", "content": [{"type": "text", "text": "สวัสดีครับ"}],
                              "usage": {"input_tokens": 1000, "output_tokens": 1000,
                                        "cache_read_input_tokens": 0}})
        with mock.patch("claude_client.requests.Session.post", fake):
            bot.handle_message(msg("สวัสดี"))
        last = bot.tg.sent[-1]
        self.assertTrue(last.startswith("สวัสดีครับ"))
        cost = (1000 * 1.0 + 1000 * 5.0) / 1e6                        # Haiku = $0.006
        self.assertIn(f"ครั้งนี้ ฿{cost * 33.5:,.2f}", last)
        self.assertIn(f"คงเหลือ ≈ ฿{(4.85 - cost) * 33.5:,.0f}", last)
        import extras
        self.assertAlmostEqual(extras.balance()["usd"], 4.85 - cost, places=9)

    def test_free_provider_shows_free(self):
        import extras
        extras.set_balance(2.0)
        s0 = extras.spent_counter()
        extras.record_usage("Ollama", {"input_tokens": 50000, "output_tokens": 500})
        self.assertIn("ครั้งนี้ฟรี", extras.cost_footer(extras.spent_counter() - s0))
        self.assertEqual(extras.balance()["usd"], 2.0)

    def test_low_balance_warns_once(self):
        import extras
        extras.set_balance(0.5)
        self.assertIn("ใกล้หมด", extras.cost_footer(0.001))
        self.assertNotIn("ใกล้หมด", extras.cost_footer(0.001))

    def test_credit_error_marks_out(self):
        import claude_client, extras
        extras.set_balance(0.2)
        bot.tg = FakeTG()
        with mock.patch.object(config, "LLM_FALLBACK", "none"), \
                mock.patch.object(claude_client, "_request",
                                  side_effect=claude_client.ClaudeError("Your credit balance is too low")):
            bot.handle_message(msg("สวัสดี"))
        self.assertTrue(extras.balance()["out"])
        self.assertIn("เครดิตหมด", extras.balance_text())

    def test_unset_balance_hints_once(self):
        import extras
        self.assertIn("/balance", extras.cost_footer(0.01))
        self.assertEqual(extras.cost_footer(0.01), "")

    def test_bad_balance_input(self):
        bot.tg = FakeTG()
        bot.handle_message(msg("/balance ห้าดอล"))
        self.assertIn("เช่น /balance 4.85", bot.tg.sent[-1])


class TestSystemControl(unittest.TestCase):
    """สั่งระบบต้องตรวจผลจริง ไม่ตอบว่า 'ทำแล้ว' ถ้ายังไม่ได้ทำ"""

    def _fake(self, adb=True, wifi_on=False, svc_ok=True, change=True, api_out="", am_ok=True):
        import system_tools
        st = {"wifi": wifi_on}
        log = []

        def sh(args, timeout=30):
            log.append(("sh", list(args)))
            if args[:3] == ["cmd", "wifi", "status"]:
                return f"Wifi is {'enabled' if st['wifi'] else 'disabled'}"
            if args[:2] == ["svc", "wifi"]:
                if not svc_ok:
                    return "ERROR (code 255): Permission Denial"
                if change:
                    st["wifi"] = args[2] == "enable"
                return ""
            if args[:3] == ["cmd", "wifi", "set-wifi-enabled"]:
                return "ERROR (code 255): Permission Denial" if not svc_ok else ""
            if args[:1] == ["am"]:
                return "Starting: Intent" if am_ok else "ERROR: blocked"
            if args[:2] == ["settings", "get"]:
                return "1" if st["wifi"] else "0"
            return ""

        def run(args, timeout=30):
            log.append(("run", list(args)))
            if args[0] == "termux-wifi-enable":
                return api_out or "OK"
            if args[0] == "termux-brightness":
                return api_out or "OK"
            if args[0] == "am":
                return "Starting: Intent" if am_ok else "ERROR: blocked"
            return "OK"
        ps = [mock.patch.object(system_tools, "_sh", side_effect=sh),
              mock.patch.object(system_tools, "_run", side_effect=run),
              mock.patch.object(system_tools, "_adb", return_value=adb),
              mock.patch.object(system_tools.time, "sleep")]
        for p in ps:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in ps])
        return system_tools, log, st

    def test_wifi_on_via_adb_uses_correct_command_and_verifies(self):
        st_mod, log, st = self._fake()
        res = st_mod.wifi({"on": True}, None)
        self.assertEqual(res, "เปิด Wi-Fi แล้ว")
        self.assertIn(("sh", ["svc", "wifi", "enable"]), log)          # ไม่ใช่ 'svc wifi on' ที่ผิด
        self.assertTrue(st["wifi"])

    def test_wifi_already_on(self):
        st_mod, log, _ = self._fake(wifi_on=True)
        self.assertIn("เปิดอยู่แล้ว", st_mod.wifi({"on": True}, None))
        self.assertFalse(any(c[1][:2] == ["svc", "wifi"] for c in log))

    def test_wifi_state_not_changing_is_not_reported_as_done(self):
        st_mod, log, _ = self._fake(change=False)
        res = st_mod.wifi({"on": True}, None)
        self.assertNotEqual(res, "เปิด Wi-Fi แล้ว")
        self.assertIn("ตรงๆ ไม่ได้", res)                               # เปิดหน้าตั้งค่าให้แตะเองแทน
        self.assertIn(("run", ["termux-wifi-enable", "true"]), log)     # ลองครบทุกวิธีก่อน

    def test_wifi_without_adb_uses_termux_api(self):
        st_mod, log, _ = self._fake(adb=False)
        self.assertEqual(st_mod.wifi({"on": True}, None), "เปิด Wi-Fi แล้ว")
        self.assertIn(("run", ["termux-wifi-enable", "true"]), log)

    def test_everything_refused_gives_error_not_success(self):
        st_mod, _, _ = self._fake(adb=True, svc_ok=False, change=False,
                                  api_out="ERROR: Permission denied", am_ok=False)
        self.assertTrue(st_mod.wifi({"on": True}, None).startswith("ERROR"))

    def test_wifi_off_with_minutes_schedules_restore(self):
        st_mod, _, st = self._fake(wifi_on=True)
        with mock.patch("threading.Timer") as T:
            res = st_mod.wifi({"on": False, "minutes": 5}, None)
        self.assertIn("เปิดกลับเองใน 5 นาที", res)
        self.assertEqual(T.call_args[0][0], 300)
        self.assertFalse(st["wifi"])

    def test_brightness_without_permission_opens_permission_page(self):
        st_mod, log, _ = self._fake(adb=False, api_out="ERROR: Please grant WRITE_SETTINGS permission")
        res = st_mod.brightness({"level": "40%"}, None)
        self.assertIn("แก้ไขการตั้งค่าระบบ", res)
        self.assertTrue(any("android.settings.action.MANAGE_WRITE_SETTINGS" in c[1] for c in log))

    def _huawei(self, bt_on=False, appops="WRITE_SETTINGS: default"):
        """จำลองผลจริงจาก MatePad 11.5 ของผู้ใช้"""
        import system_tools
        st = {"bt": bt_on, "settings": {"screen_brightness": "114", "screen_brightness_mode": "1",
                                        "hw_screen_brightness_mode_value": "1"}, "appops": appops}
        log = []

        def sh(args, timeout=30):
            log.append(list(args))
            if args[:2] == ["cmd", "bluetooth_manager"]:
                return "No shell command implementation."              # ไม่มีใน HarmonyOS
            if args[:2] == ["svc", "bluetooth"]:
                st["bt"] = args[2] == "enable"
                return ""
            if args[:3] == ["settings", "get", "global"] and args[3] == "bluetooth_on":
                return "1" if st["bt"] else "0"
            if args[:3] == ["settings", "get", "system"]:
                return st["settings"].get(args[3], "null")
            if args[:3] == ["settings", "put", "system"]:
                st["settings"][args[3]] = args[4]
                return ""
            if args[:2] == ["appops", "get"]:
                return st["appops"]
            if args[:2] == ["appops", "set"]:
                st["appops"] = "WRITE_SETTINGS: allow"
                return ""
            return ""

        def run(args, timeout=30):
            log.append(["RUN"] + list(args))
            if args[0] == "termux-brightness":
                return '{"error": "Please grant the following permission to use this command: ' \
                       'android.permission.WRITE_SETTINGS"}'
            return "Starting: Intent"
        system_tools._granted["ok"] = False
        ps = [mock.patch.object(system_tools, "_sh", side_effect=sh),
              mock.patch.object(system_tools, "_run", side_effect=run),
              mock.patch.object(system_tools, "_adb", return_value=True),
              mock.patch.object(system_tools.time, "sleep")]
        for p in ps:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in ps])
        return system_tools, log, st

    def test_huawei_bluetooth_uses_svc_not_bluetooth_manager(self):
        mod, log, st = self._huawei(bt_on=True)
        self.assertEqual(mod.bluetooth({"on": False}, None), "ปิด บลูทูธ แล้ว")
        self.assertFalse(st["bt"])
        self.assertEqual(mod.bluetooth({"on": True}, None), "เปิด บลูทูธ แล้ว")
        self.assertTrue(st["bt"])

    def test_bluetooth_manager_message_is_failure(self):
        import system_tools
        self.assertFalse(system_tools._ok("No shell command implementation."))

    def test_huawei_brightness_grants_permission_and_sets(self):
        mod, log, st = self._huawei()
        self.assertEqual(mod.brightness({"level": "30%"}, None), "ตั้งความสว่าง 30% แล้ว")
        self.assertEqual(st["settings"]["screen_brightness"], "76")
        self.assertEqual(st["settings"]["screen_brightness_mode"], "0")
        self.assertEqual(st["settings"]["hw_screen_brightness_mode_value"], "0")   # ปิด auto ของ Huawei ด้วย
        self.assertIn("allow", st["appops"])                                       # ให้สิทธิ์ Termux:API แล้ว
        self.assertFalse(any(c[:2] == ["RUN", "termux-brightness"] for c in log))  # ไม่เรียก → ไม่มีจอแดง

    def test_relative_brightness(self):
        mod, _, st = self._huawei()
        mod.brightness({"level": "-20%"}, None)
        self.assertEqual(st["settings"]["screen_brightness"], str(114 - 51))
        mod.brightness({"level": "up"}, None)
        self.assertEqual(st["settings"]["screen_brightness"], str(63 + 51))
        mod.brightness({"level": "+100%"}, None)
        self.assertEqual(st["settings"]["screen_brightness"], "255")

    def test_diagnose_runs(self):
        st_mod, _, _ = self._fake()
        out = st_mod.diagnose()
        self.assertIn("ADB: เชื่อมแล้ว", out)
        self.assertIn("Wi-Fi: ปิด", out)


class TestOllama(unittest.TestCase):
    """สมองบนคอมที่บ้าน (Ollama) — ฟรี เครื่องมือครบ + สลับไป Claude ตอนคอมปิด"""

    def setUp(self):
        import agent
        agent._fallback_until[0] = 0; agent._fallback_to[0] = "groq"

    tearDown = setUp

    def _cfg(self, **extra):
        p = [mock.patch.object(config, "LLM_PROVIDER", "ollama"),
             mock.patch.object(config, "OLLAMA_URL", "http://10.0.0.5:11434"),
             mock.patch.object(config, "OLLAMA_MODEL", "qwen3.5:9b")]
        p += [mock.patch.object(config, k, v) for k, v in extra.items()]
        return p

    def test_full_toolset_and_tool_call(self):
        import phone_tools
        sent = []
        replies = iter([
            {"message": {"role": "assistant", "content": "<think>คิดก่อน</think>", "tool_calls": [
                {"function": {"name": "torch", "arguments": {"on": True}}}]},
             "done": True, "prompt_eval_count": 9000, "eval_count": 10},
            {"message": {"role": "assistant", "content": "เปิดไฟฉายแล้วครับ"}, "done": True},
        ])

        def fake_post(url, json=None, **k):
            import copy
            sent.append((url, copy.deepcopy(json)))
            return FakeResp(next(replies))
        bot.tg = FakeTG()
        ps = self._cfg()
        for p in ps: p.start()
        try:
            with mock.patch("ollama_client.requests.Session.post", side_effect=fake_post):
                bot.handle_message(msg("เปิดไฟฉาย"))
        finally:
            for p in ps: p.stop()
        url, body = sent[0]
        self.assertTrue(url.endswith("/api/chat"))                         # API ของ Ollama โดยตรง
        self.assertEqual(body["model"], "qwen3.5:9b")
        self.assertIs(body["think"], False)                                # ปิดโหมดคิดยาว
        self.assertEqual(body["options"]["num_ctx"], 32768)                # บริบทพอ ไม่ตัดเครื่องมือทิ้ง
        self.assertEqual(body["keep_alive"], "24h")
        names = [t["function"]["name"] for t in body["tools"]]
        self.assertLess(len(names), len(phone_tools.claude_tool_specs()))    # โมเดลเล็ก: เฉพาะที่เกี่ยวข้อง
        self.assertIn("send_dm", names)
        self.assertIn("open_app", names)
        self.assertIn("web_search", names)
        follow = sent[1][1]["messages"]
        self.assertEqual(follow[-2]["tool_calls"][0]["function"]["arguments"], {"on": True})   # dict ไม่ใช่ string
        self.assertEqual(follow[-1]["role"], "tool")
        self.assertEqual(follow[-1]["tool_name"], "torch")
        self.assertIn("เปิดไฟฉายแล้ว", bot.tg.sent[-1])
        self.assertNotIn("คิดก่อน", "".join(bot.tg.sent))

    def test_stream_filters_think_and_reads_tool_calls(self):
        import ollama_client, json as _j
        parts = ["<thi", "nk>ซ่อน", "ไว้</th", "ink>สวัส", "ดีครับ <b>"]

        class R:
            status_code = 200
            def iter_lines(self, decode_unicode=True):
                for p in parts:
                    yield _j.dumps({"message": {"role": "assistant", "content": p}, "done": False})
                yield _j.dumps({"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "speak", "arguments": {"text": "hi"}}}]}, "done": False})
                yield _j.dumps({"message": {"role": "assistant", "content": ""}, "done": True,
                                "prompt_eval_count": 12000, "eval_count": 20})
        got = []
        with mock.patch.object(config, "OLLAMA_URL", "http://x:11434"), \
                mock.patch("ollama_client.requests.Session.post", return_value=R()):
            res = ollama_client.create_message("sys", [{"role": "user", "content": "x"}], [], on_text=got.append)
        self.assertEqual("".join(got), "สวัสดีครับ <b>")
        self.assertEqual(res["content"][0]["text"], "สวัสดีครับ <b>")
        self.assertEqual(res["content"][1]["input"], {"text": "hi"})
        self.assertEqual(res["stop_reason"], "tool_use")
        self.assertEqual(res["usage"]["input_tokens"], 12000)

    def test_images_sent_as_native_images(self):
        import ollama_client
        msgs = ollama_client._native_messages("sys", [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
            {"type": "text", "text": "ดูรูปนี้"}]}])
        self.assertEqual(msgs[-1]["images"], ["QUJD"])
        self.assertEqual(msgs[-1]["content"], "ดูรูปนี้")

    def test_pc_off_falls_back_to_claude_briefly(self):
        import agent, requests as rq
        bot.tg = FakeTG()
        ps = self._cfg(LLM_FALLBACK="claude", ANTHROPIC_API_KEY="k")
        for p in ps: p.start()
        def fake_post(url, *a, **k):          # Session.post เป็นตัวเดียวกันทุกไคลเอนต์ → แยกตาม URL
            if ":11434" in url:
                raise rq.ConnectionError("down")
            return FakeResp({"content": [{"type": "text", "text": "ตอบจาก Claude"}],
                             "stop_reason": "end_turn", "usage": {}})
        try:
            with mock.patch("requests.Session.post", side_effect=fake_post):
                bot.handle_message(msg("สวัสดี"))
        finally:
            for p in ps: p.stop()
        self.assertIn("ตอบจาก Claude", bot.tg.sent[-1])
        left = agent._fallback_until[0] - time.time()
        self.assertTrue(60 < left <= 180, left)          # ลองคอมใหม่ใน 3 นาที

    def test_multi_address_failover_tailscale_then_lan(self):
        import ollama_client, requests as rq
        ollama_client._active[0] = 0
        tried = []

        def fake_post(url, *a, **k):
            tried.append(url)
            if "100.80.1.2" in url:                 # นอกบ้าน Tailscale ปิด → ติดต่อไม่ได้
                raise rq.ConnectionError("down")
            return FakeResp({"message": {"content": "ตอบจากคอมผ่าน Wi-Fi"}, "done": True})
        with mock.patch.object(config, "OLLAMA_URL", "http://100.80.1.2:11434,http://192.168.1.50:11434"), \
                mock.patch("ollama_client.requests.Session.post", side_effect=fake_post):
            res = ollama_client.create_message("sys", [{"role": "user", "content": "x"}], [])
            self.assertEqual(res["content"][0]["text"], "ตอบจากคอมผ่าน Wi-Fi")
            self.assertEqual(ollama_client._active[0], 1)       # จำไว้ ครั้งหน้าลอง Wi-Fi ก่อน
            tried.clear()
            ollama_client.create_message("sys", [{"role": "user", "content": "x"}], [])
            self.assertIn("192.168.1.50", tried[0])
        self.assertEqual(ollama_client._via("http://100.80.1.2:11434"), "Tailscale")
        ollama_client._active[0] = 0

    def test_slow_pc_falls_back_instead_of_silence(self):
        import requests as rq
        bot.tg = FakeTG()
        ps = self._cfg(LLM_FALLBACK="claude", ANTHROPIC_API_KEY="k")
        tried = []
        def fake_post(url, *a, **k):
            tried.append(url)
            if ":11434" in url:
                raise rq.ReadTimeout("slow")
            return FakeResp({"content": [{"type": "text", "text": "ตอบจาก Claude"}],
                             "stop_reason": "end_turn", "usage": {}})
        for p in ps: p.start()
        try:
            with mock.patch.object(config, "OLLAMA_URL", "http://100.1.1.1:11434,http://192.168.1.9:11434"), \
                    mock.patch("requests.Session.post", side_effect=fake_post):
                bot.handle_message(msg("สวัสดี"))
        finally:
            for p in ps: p.stop()
        self.assertIn("ตอบจาก Claude", bot.tg.sent[-1])
        self.assertEqual(sum(":11434" in u for u in tried), 1)     # ไม่ส่งซ้ำไปอีกที่อยู่ (กันรอนานสองเท่า)

    def test_think_flag_retry_for_models_without_thinking(self):
        import ollama_client
        bodies = []

        def fake_post(url, json=None, **k):
            bodies.append(dict(json))
            if "think" in json:
                return FakeResp({"error": "\"llama3\" does not support thinking"}, code=400)
            return FakeResp({"message": {"content": "ok"}, "done": True})
        with mock.patch.object(config, "OLLAMA_URL", "http://x:11434"), \
                mock.patch("ollama_client.requests.Session.post", side_effect=fake_post):
            res = ollama_client.create_message("sys", [{"role": "user", "content": "x"}], [])
        self.assertEqual(res["content"][0]["text"], "ok")
        self.assertEqual(len(bodies), 2)

    def test_usage_counts_cache_writes_and_search(self):
        import extras
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d), mock.patch.object(config, "CLAUDE_MODEL", "claude-haiku-4-5"):
            extras.record_usage("Claude", {
                "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 2_000_000,
                "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000},
                "server_tool_use": {"web_search_requests": 3}})
            text, usd = extras.usage_report(days=1)
        self.assertAlmostEqual(usd, 1.25 + 2.0 + 0.03, places=6)     # Haiku $1/M: 5m×1.25 + 1h×2 + ค้น 3 ครั้ง
        self.assertIn("ค้นเว็บ 3 ครั้ง", text)

    def test_usage_recorded_as_free(self):
        import extras
        d = tempfile.mkdtemp()
        with mock.patch.object(config, "DATA_DIR", d):
            extras.record_usage("Ollama", {"input_tokens": 1_000_000, "output_tokens": 1_000_000})
            _, usd = extras.usage_report(days=1)
        self.assertEqual(usd, 0.0)

    def test_websearch_falls_back_to_duckduckgo(self):
        import websearch
        page = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tmd.go.th%2F">'
                'พยากรณ์<b>อากาศ</b></a><a class="result__snippet" href="x">ฝนตก 60%</a>')

        class R:
            status_code, text = 200, page
            def raise_for_status(self): pass
        websearch._gemini_off_until[0] = 0
        with mock.patch.object(config, "GEMINI_API_KEY", "g"), \
                mock.patch("gemini_client.web_search", side_effect=RuntimeError("429 quota")), \
                mock.patch("websearch.requests.post", return_value=R()):
            out = websearch.search("อากาศวันนี้")
        self.assertIn("พยากรณ์อากาศ", out)
        self.assertIn("https://www.tmd.go.th/", out)
        self.assertIn("ฝนตก 60%", out)
        self.assertGreater(websearch._gemini_off_until[0], time.time())   # พัก Gemini 1 ชม.
        websearch._gemini_off_until[0] = 0


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ต้องมี ffmpeg")
class TestScreen(unittest.TestCase):
    def test_read_and_tap(self):
        import screen_tools
        bot.tg = FakeTG(auto_answer=True)
        ctx = bot.Ctx(111)
        out = screen_tools.read_screen({}, ctx)
        self.assertIn("แม่", out)
        self.assertIn("ช่องพิมพ์", out)
        self.assertIn("(2325,1500)", out)
        self.assertIn("2325,1500", screen_tools.tap_text({"text": "ส่ง"}, ctx))
        self.assertFalse(any("ขออนุญาต" in m for m in bot.tg.sent))      # ปุ่มส่ง → ส่งได้เลย
        bot.tg = FakeTG(auto_answer=False)
        ctx = bot.Ctx(111)
        ctx.hold = True                                                   # ผู้ใช้บอกให้รอ → ต้องถาม
        self.assertIn("ไม่อนุญาต", screen_tools.tap({"x": 2325, "y": 1500}, ctx))
        ctx.hold = False
        self.assertTrue(screen_tools.tap({"x": 250, "y": 230}, ctx).startswith("[MOCK]"))  # ปุ่มชื่อแม่ → ไม่ต้องถาม
        self.assertTrue(screen_tools.type_text({"text": "hello world"}, ctx).startswith("พิมพ์แล้ว"))

    def test_open_app_alias(self):
        import phone_tools
        self.assertIn("jp.naver.line.android", phone_tools.open_app({"app": "LINE"}, bot.Ctx(111)))


def _el(t, x, y, click=True, edit=False, desc="", rid="", w=200, h=60):
    return {"text": t, "desc": desc, "id": rid, "edit": edit, "click": click, "x": x, "y": y,
            "box": (x - w // 2, y - h // 2, x + w // 2, y + h // 2)}


class AskCtx:
    def __init__(self, answers=(), confirm=True):
        self.answers, self.ok, self.asked, self.notes, self.confirms = list(answers), confirm, [], [], []

    def ask(self, q):
        self.asked.append(q)
        return self.answers.pop(0) if self.answers else None

    def confirm(self, d):
        self.confirms.append(d)
        return self.ok

    def notify(self, t):
        self.notes.append(t)

    def status(self, t):
        pass


class TestProfileForms(unittest.TestCase):
    def setUp(self):
        import user_profile
        try:
            os.remove(user_profile._path())
        except OSError:
            pass

    def test_profile_set_show_and_secrets(self):
        import user_profile
        r = user_profile.handle_text("จำข้อมูลของฉัน ชื่อ สมชาย, นามสกุล ใจดี, เบอร์ 0812345678, อีเมล a@b.com")
        self.assertTrue(r)
        d = user_profile.load()
        self.assertEqual((d["first_name"], d["last_name"], d["phone"], d["email"]),
                         ("สมชาย", "ใจดี", "0812345678", "a@b.com"))
        self.assertNotIn("0812345678", user_profile.show())          # แสดงแบบปิดบัง
        self.assertIn("ไม่เก็บ", user_profile.handle_text("จำข้อมูลของฉัน รหัสผ่าน 1234"))
        self.assertEqual(user_profile.value_for("Password")[0], "sensitive")
        self.assertEqual(user_profile.value_for("ชื่อ-นามสกุล")[1], "สมชาย ใจดี")
        self.assertEqual(user_profile.value_for("ที่อยู่อีเมล")[1], "a@b.com")
        self.assertIn("ลบ", user_profile.handle_text("ลบข้อมูลของฉัน"))
        self.assertEqual(user_profile.load(), {})

    def _form(self):
        return [_el("ชื่อ", 300, 200, click=False), _el("", 300, 280, edit=True, rid="fname"),
                _el("เบอร์โทรศัพท์", 300, 400, click=False), _el("", 300, 480, edit=True, rid="tel"),
                _el("", 300, 600, edit=True, desc="รหัสผ่าน"),
                _el("หมายเหตุ", 300, 700, click=False), _el("", 300, 780, edit=True, rid="note"),
                _el("ส่ง", 300, 1000)]

    def test_fill_uses_profile_asks_rest_and_confirms_submit(self):
        import forms, user_profile, screen_tools
        user_profile.handle_text("จำข้อมูลของฉัน ชื่อ สมชาย, เบอร์ 0812345678")
        typed, taps = [], []
        ctx = AskCtx(["Secr3t!", "ข้าม"], confirm=True)
        with mock.patch("time.sleep"), mock.patch.object(forms, "_items", side_effect=lambda: self._form()), \
                mock.patch.object(screen_tools, "adb_serial", return_value="x"), \
                mock.patch.object(screen_tools, "swipe", return_value="OK"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: taps.append(a) or "ok"), \
                mock.patch("share_tools._clear_box"), \
                mock.patch.object(screen_tools, "type_text", side_effect=lambda a, c: typed.append(a["text"]) or "OK"):
            res = forms.fill(ctx)
        self.assertEqual(typed, ["สมชาย", "0812345678", "Secr3t!"])
        self.assertEqual(len(ctx.asked), 2)                       # รหัสผ่าน + หมายเหตุ
        self.assertIn("ข้อมูลลับ", ctx.asked[0])
        self.assertNotIn("Secr3t!", res)                          # ไม่โชว์รหัส
        self.assertTrue(ctx.confirms)
        self.assertIn(["input", "tap", "300", "1000"], taps)
        self.assertIn("ส่งฟอร์มแล้ว", res)
        self.assertIn("เจอฟอร์ม", ctx.notes[0])

    def test_fill_no_submit_without_confirm(self):
        import forms, screen_tools
        taps = []
        ctx = AskCtx(["a", "b", "c", "d"], confirm=False)
        form = self._form()
        with mock.patch("time.sleep"), mock.patch.object(forms, "_items", return_value=form), \
                mock.patch.object(screen_tools, "adb_serial", return_value="x"), \
                mock.patch.object(screen_tools, "swipe", return_value="OK"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: taps.append(a) or "ok"), \
                mock.patch("share_tools._clear_box"), \
                mock.patch.object(screen_tools, "type_text", return_value="OK"):
            res = forms.fill(ctx, use_profile=False)
        self.assertNotIn(["input", "tap", "300", "1000"], taps)
        self.assertIn("ยังไม่ได้กดส่ง", res)
        self.assertEqual(len(ctx.asked), 4)
        self.assertIn("ข้อมูลลับ", ctx.asked[2])

    def test_label_from_above_and_handle_text(self):
        import forms
        f = forms.read_fields(self._form())
        self.assertTrue(f[0]["label"].startswith("ชื่อ"))
        self.assertTrue(f[1]["label"].startswith("เบอร์โทรศัพท์"))
        self.assertEqual(f[2]["label"], "รหัสผ่าน")
        with mock.patch.object(forms, "fill", return_value="ok") as fl:
            self.assertEqual(forms.handle_text("กรอกฟอร์มให้หน่อย ถามทุกช่อง"), "ok")
        self.assertFalse(fl.call_args[1]["use_profile"])
        self.assertIsNone(forms.handle_text("ฟอร์มนี้คืออะไร"))

    def test_quick_routes_profile_and_hides_from_history(self):
        import quick
        r = quick.handle("จำข้อมูลของฉัน เบอร์ 0899999999")
        self.assertTrue(r)
        self.assertTrue(quick.PRIVATE["v"])
        quick.handle("แบต")
        self.assertFalse(quick.PRIVATE["v"])


class TestAppLearn(unittest.TestCase):
    def setUp(self):
        import skills
        skills.set_pref("flows", {})

    def test_parse_getevent_taps_not_swipes(self):
        import app_learn
        lines = ["[   10.000] EV_KEY BTN_TOUCH DOWN", "[   10.001] EV_ABS ABS_MT_POSITION_X 00000064",
                 "[   10.001] EV_ABS ABS_MT_POSITION_Y 000000c8", "[   10.100] EV_KEY BTN_TOUCH UP",
                 "[   11.000] EV_KEY BTN_TOUCH DOWN", "[   11.001] EV_ABS ABS_MT_POSITION_X 00000064",
                 "[   11.001] EV_ABS ABS_MT_POSITION_Y 000000c8", "[   11.050] EV_ABS ABS_MT_POSITION_Y 00000300",
                 "[   11.200] EV_KEY BTN_TOUCH UP"]
        taps = app_learn.parse_getevent(lines, 1000, 1000)
        self.assertEqual(len(taps), 1)
        self.assertAlmostEqual(taps[0][1], 0.1)
        self.assertAlmostEqual(taps[0][2], 0.2)
        self.assertEqual(app_learn._rotate(0.1, 0.2, 1), (0.2, 0.9))

    def test_recorder_tap_type_and_save_with_confirm(self):
        import app_learn
        r = app_learn.Recorder("สั่งกาแฟ")
        r.rot = 0
        scr1 = [_el("ค้นหา", 500, 100, edit=True, rid="search"), _el("เมนู", 500, 900)]
        scr2 = [_el("ลาเต้", 500, 100, edit=True, rid="search"), _el("เมนู", 500, 900)]
        r.snap = [(0, scr1, 1000, 1000)]
        r._on_tap(0.5, 0.1)
        r.snap = [(0, scr2, 1000, 1000)]
        r._on_tap(0.5, 0.9)
        self.assertEqual([s["type"] for s in r.steps], ["tap", "type", "tap"])
        self.assertEqual(r.steps[1]["text"], "ลาเต้")
        self.assertEqual(r.steps[2]["label"], "เมนู")
        app_learn._rec["r"] = r
        with mock.patch.object(r, "stop", return_value=r.steps):
            ctx = AskCtx(confirm=True)
            res = app_learn.handle_text("จบขั้นตอน", ctx)
        self.assertIn("จำขั้นตอน", res)
        self.assertIn("พิมพ์", ctx.confirms[0])
        import skills
        self.assertIn("สั่งกาแฟ", skills.get_pref("flows"))
        self.assertIn("สั่งกาแฟ", app_learn.handle_text("ขั้นตอนที่จำไว้"))
        self.assertIn("ลาเต้", app_learn.hints("ทำ สั่งกาแฟ ให้หน่อย"))

    def test_not_saved_when_declined(self):
        import app_learn, skills
        r = app_learn.Recorder("x")
        app_learn._rec["r"] = r
        with mock.patch.object(r, "stop", return_value=[{"type": "tap", "label": "a", "rx": .1, "ry": .1}] * 2):
            res = app_learn.record_stop(AskCtx(confirm=False))
        self.assertIn("ไม่บันทึก", res)
        self.assertNotIn("x", skills.get_pref("flows") or {})

    def test_replay_finds_by_label_and_asks_before_danger(self):
        import app_learn, skills, screen_tools
        import xml.etree.ElementTree as ET
        skills.set_pref("flows", {"ซื้อของ": {"steps": [
            {"type": "tap", "label": "ตะกร้า", "id": "", "rx": 0.1, "ry": 0.1},
            {"type": "type", "text": "สบู่"},
            {"type": "tap", "label": "ชำระเงิน", "id": "", "rx": 0.5, "ry": 0.5}]}})
        items = [_el("ตะกร้า", 700, 300), _el("ชำระเงิน", 400, 1500)]
        taps, typed = [], []
        root = ET.fromstring('<hierarchy><node bounds="[0,0][1000,2000]"/></hierarchy>')
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_serial", return_value="x"), \
                mock.patch.object(screen_tools, "_dump", return_value=root), \
                mock.patch.object(screen_tools, "_elements", return_value=items), \
                mock.patch.object(screen_tools, "type_text", side_effect=lambda a, c: typed.append(a["text"])), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: taps.append(a) or "ok"):
            res = app_learn.handle_text("ทำขั้นตอน ซื้อของ", AskCtx(confirm=False))
        self.assertEqual(taps, [["input", "tap", "700", "300"]])     # ตามชื่อ ไม่ใช่พิกัดเดิม
        self.assertEqual(typed, ["สบู่"])
        self.assertIn("หยุดก่อนกด", res)

    def test_explore_skips_danger_and_saves_map(self):
        import app_learn, phone_tools, screen_tools, skills
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<hierarchy><node bounds="[0,0][1000,2000]"/></hierarchy>')
        home = [_el("หน้าหลัก", 100, 1900), _el("ค้นหา", 300, 1900), _el("ลบบัญชี", 500, 1900),
                _el("โปรไฟล์", 700, 1900), _el("โพสต์นี้", 500, 800)]
        taps = []
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "adb_serial", return_value="x"), \
                mock.patch.object(phone_tools, "open_app", return_value="เปิดแล้ว"), \
                mock.patch.object(phone_tools, "_fg", return_value="com.app"), \
                mock.patch.object(screen_tools, "_dump", return_value=root), \
                mock.patch.object(screen_tools, "_elements", return_value=home), \
                mock.patch.object(app_learn, "_items", return_value=home + [_el("", 500, 300, edit=True, desc="ค้นหาผู้ใช้")]), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: taps.append(a) or "ok"):
            res = app_learn.handle_text("ศึกษาแอป testapp", AskCtx())
        self.assertNotIn(["input", "tap", "500", "1900"], taps)       # ลบบัญชี ไม่กด
        m = skills.get_pref("appmap:testapp")
        self.assertEqual(set(m["tabs"]), {"หน้าหลัก", "ค้นหา", "โปรไฟล์"})
        self.assertIn("ค้นหาผู้ใช้", m["tabs"]["ค้นหา"]["fields"])
        self.assertIn("3 แท็บ", res)


class TestComposeTypeHere(unittest.TestCase):
    def test_type_here_largest_field_no_send(self):
        import share_tools, screen_tools
        items = [_el("", 500, 200, edit=True, w=200), _el("", 500, 900, edit=True, w=900, h=400)]
        got = []
        with mock.patch("time.sleep"), mock.patch.object(share_tools, "_items", return_value=items), \
                mock.patch.object(screen_tools, "adb_serial", return_value="x"), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: got.append(a) or "ok"), \
                mock.patch.object(share_tools, "_clear_box"), \
                mock.patch.object(share_tools, "_send_in_chat") as snd, \
                mock.patch.object(screen_tools, "type_text", side_effect=lambda a, c: got.append(a["text"]) or "OK"):
            res = share_tools.type_here("สวัสดีครับ")
        self.assertIn(["input", "tap", "500", "900"], got)
        self.assertIn("สวัสดีครับ", got)
        snd.assert_not_called()
        self.assertNotIn("ERROR", res)

    def test_router_compose_writes_and_types(self):
        import router, share_tools
        with mock.patch.object(router, "call_llm", create=True), \
                mock.patch("agent.call_llm", return_value=({"content": [{"type": "text", "text": "บทความสั้น"}]}, "x")), \
                mock.patch.object(share_tools, "type_here", return_value="พิมพ์แล้ว") as th, \
                mock.patch("phone_tools.open_app", return_value="เปิดแล้ว"):
            res = router.compose({"intent": "compose", "write": "แคปชั่นวันจันทร์", "app": "notes"},
                                 AskCtx(), "เขียนแคปชั่นวันจันทร์ลงโน้ต")
        self.assertEqual(th.call_args[0][0], "บทความสั้น")
        self.assertIn("บทความสั้น", res)


class TestTelegramAsk(unittest.TestCase):
    def test_ask_waits_next_message(self):
        bot.tg = FakeTG()
        if True:
            c = bot.Ctx(111)
            out = {}
            th = threading.Thread(target=lambda: out.update(a=c.ask("ช่องชื่อ?", timeout=5)))
            th.start()
            for _ in range(50):
                if bot._ask_waiters.get(111):
                    break
                time.sleep(0.05)
            bot.handle_message({"chat": {"id": 111}, "from": {"id": 111}, "text": "สมชาย"})
            th.join(3)
        self.assertEqual(out.get("a"), "สมชาย")


class TestSelfHeal(unittest.TestCase):
    TB = ('Traceback (most recent call last):\n  File "bot.py", line 10, in handle_message\n    x()\n'
          '  File "demo_mod.py", line 3, in broken\n    return undefined_name\nNameError: name \'undefined_name\' is not defined')

    def setUp(self):
        import self_heal, shutil
        self.h = self_heal
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "demo_mod.py"), "w") as f:
            f.write('"""demo"""\n\ndef broken():\n    return undefined_name\n')
        with open(os.path.join(self.root, "bot.py"), "w") as f:
            f.write("x = 1\n")
        os.makedirs(os.path.join(self.root, "tests"))
        shutil.copy(os.path.join(self_heal.DIR, "self_heal.py"), self.root)
        self.p = mock.patch.object(self_heal, "DIR", self.root)
        self.p.start()
        self_heal._attempts.update(day="", n=0)          # เพดานลองซ่อมต่อวัน เริ่มใหม่ทุกเทสต์
        for n in ("errors.json", "heal_pending.json", "heal_history.json", "heal_baseline.json"):
            try:
                os.remove(self_heal._p(n))
            except OSError:
                pass

    def tearDown(self):
        self.p.stop()

    def test_record_only_code_bugs_and_due(self):
        h = self.h
        self.assertIsNone(h.record(self.TB.replace("NameError", "ConnectionError")))   # เน็ตหลุด ไม่ใช่บัคโค้ด
        sig = h.record(self.TB)
        self.assertEqual(sig, "demo_mod.py:broken NameError")
        self.assertEqual(h.due_repairs(), [])
        h.record(self.TB)
        self.assertEqual(h.due_repairs(), [sig])

    def test_validate_blocks_unsafe_edits(self):
        h = self.h
        with open(os.path.join(self.root, "demo_mod.py"), "a") as f:
            f.write("def guard(ctx):\n    if not ctx.confirm(\'x\'):\n        return 0\n")
        ok, _ = h.validate([{"file": "demo_mod.py", "old": "return undefined_name", "new": "return None"}])
        self.assertTrue(ok)
        self.assertFalse(h.validate([{"file": "config.py", "old": "a", "new": "b"}])[0])
        self.assertFalse(h.validate([{"file": "../x.py", "old": "a", "new": "b"}])[0])
        self.assertFalse(h.validate([{"file": "demo_mod.py", "old": "if not ctx.confirm(\'x\'):", "new": "if False:"}])[0])
        self.assertFalse(h.validate([{"file": "demo_mod.py", "old": "return undefined_name",
                                      "new": "import subprocess; return subprocess.run(\'x\')"}])[0])
        self.assertFalse(h.validate([{"file": "demo_mod.py", "old": "nothing-here", "new": "y"}])[0])

    def test_repair_tests_in_copy_then_confirm_apply_and_rollback(self):
        h = self.h
        sig = h.record(self.TB)
        plan = json.dumps({"explain": "ตัวแปรไม่มี", "edits": [
            {"file": "demo_mod.py", "old": "return undefined_name", "new": "return None"}]})
        asked = []
        with mock.patch.object(h, "_llm", return_value=plan), \
                mock.patch.object(h, "run_tests", side_effect=[({"t.old"}, ""), ({"t.old"}, "")]) as rt:
            res = h.repair(self.TB, sig=sig, confirm=lambda d: asked.append(d) or True)
        self.assertIn("ซ่อมได้แล้ว", res)
        self.assertEqual(rt.call_count, 2)                              # baseline + หลังแก้
        self.assertIn("ตัวแปรไม่มี", asked[0])
        with open(os.path.join(self.root, "demo_mod.py")) as f:
            self.assertIn("return None", f.read())
        self.assertTrue(h._jload("heal_pending.json", None))
        self.assertEqual(h._jload("errors.json", {})[sig]["status"], "fixed")
        # บอทล่มภายในช่วงทดลอง → ย้อนกลับเอง
        self.assertIn("ย้อน", h.after_exit(1))
        with open(os.path.join(self.root, "demo_mod.py")) as f:
            self.assertIn("undefined_name", f.read())
        self.assertIsNone(h._jload("heal_pending.json", None))

    def test_repair_rejects_when_new_tests_fail_and_never_touches_real_code(self):
        h = self.h
        plan = json.dumps({"explain": "x", "edits": [
            {"file": "demo_mod.py", "old": "return undefined_name", "new": "return 1"}]})
        with mock.patch.object(h, "_llm", return_value=plan), \
                mock.patch.object(h, "run_tests", side_effect=[(set(), ""), ({"t.new"}, "boom"), ({"t.new"}, "boom")]):
            res = h.repair(self.TB, confirm=lambda d: True)
        self.assertIn("ซ่อมไม่สำเร็จ", res)
        with open(os.path.join(self.root, "demo_mod.py")) as f:
            self.assertIn("undefined_name", f.read())

    def test_declined_keeps_code(self):
        h = self.h
        plan = json.dumps({"explain": "x", "edits": [
            {"file": "demo_mod.py", "old": "return undefined_name", "new": "return None"}]})
        with mock.patch.object(h, "_llm", return_value=plan), \
                mock.patch.object(h, "run_tests", return_value=(set(), "")):
            res = h.repair(self.TB, confirm=lambda d: False)
        self.assertIn("ไม่ได้ใช้", res)
        with open(os.path.join(self.root, "demo_mod.py")) as f:
            self.assertIn("undefined_name", f.read())

    def test_symptom_picks_files_and_daily_limit(self):
        h = self.h
        calls = []
        def llm(sys_, q, mt=8000):
            calls.append(q)
            return json.dumps({"files": ["demo_mod.py"]}) if len(calls) == 1 else \
                json.dumps({"explain": "ไม่ใช่บัคโค้ด", "edits": []})
        with mock.patch.object(h, "_llm", side_effect=llm), mock.patch.object(h, "run_tests", return_value=(set(), "")):
            res = h.handle_text("ซ่อมตัวเอง ส่งข้อความแล้วไม่กดส่ง", None)
        self.assertIn("ไม่ใช่บัคโค้ด", res)
        self.assertIn("demo_mod.py", calls[1])
        h._jsave("heal_history.json", [{"day": time.strftime("%Y-%m-%d"), "applied": True}] * 5)
        self.assertIn("วันนี้ซ่อม", h.repair(self.TB))

    def test_doctor_restores_broken_json(self):
        h = self.h
        p = h._p("broken_test.json")
        with open(p, "w") as f:
            f.write("{bad")
        with mock.patch.object(h, "_voice_expected", return_value=False):
            out = h.doctor()
        self.assertIn("broken_test.json", out)
        self.assertFalse(os.path.exists(p))
        self.assertIsNone(h.handle_text("เปิด youtube"))
        self.assertIn("ตรวจซ่อม", h.handle_text("ตรวจซ่อมให้หน่อย"))


if __name__ == "__main__":
    unittest.main()


class _CloudResp:
    def __init__(self, code=200, data=None, lines=None, text=""):
        self.status_code, self._d, self._lines = code, data, lines or []
        self.text = text or json.dumps(data or {})
        self.content = "\n".join(lines).encode() if lines else json.dumps(data or {}).encode()

    def json(self):
        return self._d

    def iter_lines(self, decode_unicode=False):
        for ln in self._lines:
            yield ln.encode()


class TestCloudAI(unittest.TestCase):
    def setUp(self):
        import cloud_client
        self.cc = cloud_client
        cloud_client._bad_until.clear()
        cloud_client._reasoning.clear()
        self.p = mock.patch.multiple(config, CLOUD_API_KEY="cpk_test", CLOUD_MODEL="Qwen/Qwen3.5-397B-A17B-TEE",
                                     CLOUD_MODEL_BACKUP="moonshotai/Kimi-K3-TEE", CLOUD_THINK=False)
        self.p.start()
        self.addCleanup(self.p.stop)

    def _sess(self, responses):
        calls = []

        class S:
            def post(_s, url, json=None, **kw):
                calls.append((url, json))
                return responses.pop(0)

            def get(_s, url, **kw):
                return responses.pop(0)
        return S(), calls

    def test_defaults(self):
        self.assertTrue(config.CLOUD_BASE_URL.startswith("https://llm.chutes.ai"))

    def test_tool_call_and_no_thinking_for_qwen(self):
        data = {"choices": [{"message": {"content": "<think>x</think>เปิดให้แล้วครับ",
                                         "tool_calls": [{"id": "c1", "function": {
                                             "name": "open_app", "arguments": "{\"name\": \"LINE\"}"}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        s, calls = self._sess([_CloudResp(200, data)])
        with mock.patch.object(self.cc, "_session", return_value=s):
            r = self.cc.create_message("sys", [{"role": "user", "content": "เปิดไลน์"}],
                                       [{"name": "open_app", "description": "d", "input_schema": {}}])
        self.assertEqual(calls[0][1]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertTrue(calls[0][1]["tools"])
        self.assertEqual(r["stop_reason"], "tool_use")
        self.assertEqual(r["content"][0]["text"], "เปิดให้แล้วครับ")
        self.assertEqual(r["content"][1]["input"], {"name": "LINE"})

    def test_busy_primary_falls_to_kimi(self):
        ok = {"choices": [{"message": {"content": "ได้ครับ", "reasoning_content": "คิด"}}]}
        s, calls = self._sess([_CloudResp(503, text="Infrastructure is at maximum capacity"), _CloudResp(200, ok)])
        with mock.patch.object(self.cc, "_session", return_value=s):
            r = self.cc.create_message("sys", [{"role": "user", "content": "สวัสดี"}], [])
        self.assertEqual([c[1]["model"] for c in calls], ["Qwen/Qwen3.5-397B-A17B-TEE", "moonshotai/Kimi-K3-TEE"])
        self.assertEqual(r["model"], "moonshotai/Kimi-K3-TEE")
        self.assertNotIn("chat_template_kwargs", calls[1][1])
        # ตัวหลักเพิ่งเต็ม → รอบหน้าลองตัวสำรองก่อน
        self.assertEqual(self.cc.models_to_try()[0], "moonshotai/Kimi-K3-TEE")

    def test_bad_key_does_not_try_backup(self):
        s, calls = self._sess([_CloudResp(401, text="unauthorized")])
        with mock.patch.object(self.cc, "_session", return_value=s):
            with self.assertRaises(self.cc.CloudError) as e:
                self.cc.create_message("sys", [{"role": "user", "content": "x"}], [])
        self.assertTrue(str(e.exception).startswith("401"))
        self.assertEqual(len(calls), 1)

    def test_stream_hides_thinking_and_collects_tools(self):
        lines = ['data: ' + json.dumps({"choices": [{"delta": {"reasoning_content": "ลับ"}}]}),
                 'data: ' + json.dumps({"choices": [{"delta": {"content": "สวัส"}}]}),
                 'data: ' + json.dumps({"choices": [{"delta": {"content": "ดีครับ"}}]}),
                 'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [
                     {"index": 0, "id": "t9", "function": {"name": "read_screen", "arguments": "{}"}}]}}]}),
                 'data: [DONE]']
        s, _ = self._sess([_CloudResp(200, lines=lines)])
        got = []
        with mock.patch.object(self.cc, "_session", return_value=s), \
                mock.patch.object(config, "CLOUD_MODEL", "moonshotai/Kimi-K3-TEE"):
            r = self.cc.create_message("sys", [{"role": "user", "content": "x"}], [], on_text=got.append)
        self.assertEqual("".join(got), "สวัสดีครับ")
        self.assertEqual(r["content"][1]["name"], "read_screen")
        self.assertEqual(self.cc._reasoning.get("t9"), "ลับ")
        # Kimi: ส่งความคิดกลับไปในรอบถัดไป
        msgs = self.cc._messages("sys", [{"role": "assistant", "content": r["content"]}], "moonshotai/Kimi-K3-TEE")
        self.assertEqual(msgs[1].get("reasoning_content"), "ลับ")

    def test_agent_uses_cloud_and_falls_back_quickly(self):
        import cloud_client
        with mock.patch.object(config, "LLM_PROVIDER", "cloud"), \
                mock.patch.object(config, "LLM_FALLBACK", "claude"), \
                mock.patch.object(cloud_client, "create_message",
                                  side_effect=cloud_client.CloudError("Cloud AI ทุกรุ่นไม่ว่างตอนนี้ (429)")), \
                mock.patch.object(agent, "_call_provider", wraps=agent._call_provider) as cp, \
                mock.patch("claude_client.create_message",
                           return_value={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}):
            agent._fallback_until[0] = 0.0
            r, who = agent.call_llm([{"role": "user", "content": "x"}], [])
            self.assertEqual(who, "Claude")
            self.assertLess(agent._fallback_until[0] - time.time(), 4 * 60)   # ไม่ล็อก 12 ชม.
            agent._fallback_until[0] = 0.0
        self.assertEqual(cp.call_args_list[0][0][0], "cloud")

    def test_provider_switch_and_vision_quality_order(self):
        import providers
        import vision
        self.assertEqual(providers.ALIASES["chutes"], "cloud")
        self.assertTrue(providers.ready("cloud")[0])
        order = []
        with mock.patch.object(config, "CLOUD_VISION", True), \
                mock.patch.object(config, "GROQ_API_KEY", "g"), \
                mock.patch.object(vision, "_groq_vision_model", return_value="scout"), \
                mock.patch.object(vision, "_groq_vision", side_effect=lambda p, i: order.append("groq") or "groq"), \
                mock.patch("cloud_client.vision", side_effect=lambda p, i: order.append("cloud") or "cloud"):
            f = os.path.join(config.DATA_DIR, "v.jpg")
            open(f, "wb").write(b"x" * 10)
            self.assertEqual(vision.ask_images("ดู", [f], quality=True), "cloud")
            self.assertEqual(vision.ask_images("ดู", [f]), "groq")
        self.assertEqual(order, ["cloud", "groq"])

    def test_ollama_cloud_key_header(self):
        import ollama_client
        with mock.patch.object(config, "OLLAMA_API_KEY", "ok_123"), \
                mock.patch.object(config, "OLLAMA_URL", "https://ollama.com"):
            self.assertEqual(ollama_client.auth_headers()["Authorization"], "Bearer ok_123")
            self.assertTrue(ollama_client.is_cloud())
            self.assertTrue(ollama_client.warmup())
        with mock.patch.object(config, "OLLAMA_API_KEY", ""):
            self.assertEqual(ollama_client.auth_headers()["Authorization"], "Bearer ollama")


class TestCloudCost(unittest.TestCase):
    def test_cloud_usage_is_free_per_call(self):
        import extras
        self.assertEqual(extras.record_usage("Cloud", {"input_tokens": 100000, "output_tokens": 5000}), 0)


class TestCloudVisionSkip(unittest.TestCase):
    def test_model_without_vision_is_remembered(self):
        import cloud_client as cc
        cc._no_vision.clear(); cc._bad_until.clear()
        calls = []

        class S:
            def post(_s, url, json=None, **kw):
                calls.append(json["model"])
                return _CloudResp(400, text="image input not supported")
        with mock.patch.multiple(config, CLOUD_API_KEY="k", CLOUD_MODEL="zai-org/glm-5.3",
                                 CLOUD_MODEL_BACKUP="", CLOUD_VISION_MODEL=""), \
                mock.patch.object(cc, "_session", return_value=S()):
            with self.assertRaises(cc.CloudError):
                cc.vision("ดู", ["aGk="])
            with self.assertRaises(cc.CloudError):
                cc.vision("ดู", ["aGk="])
        self.assertEqual(calls, ["zai-org/glm-5.3"])           # ไม่ลองซ้ำ
        self.assertNotIn("zai-org/glm-5.3", cc._bad_until)      # ไม่กระทบการคุยปกติ


class TestNanoSubscription(unittest.TestCase):
    def test_retry_without_extras_then_backup(self):
        import cloud_client as cc
        cc._bad_until.clear()
        sent = []
        err = '{"error":{"billing_restriction":"subscription_only"}}'
        ok = {"choices": [{"message": {"content": "สวัสดีครับ"}}]}
        resps = [_CloudResp(429, text=err), _CloudResp(429, text=err), _CloudResp(200, ok)]

        class S:
            def post(_s, url, json=None, **kw):
                sent.append(dict(json))
                return resps.pop(0)
        with mock.patch.multiple(config, CLOUD_API_KEY="k", CLOUD_MODEL="qwen/qwen3.5-397b-a17b",
                                 CLOUD_MODEL_BACKUP="moonshotai/kimi-k2.6"), \
                mock.patch.object(cc, "_session", return_value=S()):
            r = cc.create_message("sys", [{"role": "user", "content": "สวัสดี"}], [])
        self.assertIn("chat_template_kwargs", sent[0])
        self.assertNotIn("chat_template_kwargs", sent[1])          # ลองแบบตัดพารามิเตอร์เสริม
        self.assertEqual(sent[2]["model"], "moonshotai/kimi-k2.6")  # ยังไม่ได้ → ตัวสำรอง
        self.assertEqual(r["content"][0]["text"], "สวัสดีครับ")

    def test_nano_defaults(self):
        import importlib
        with mock.patch.dict(os.environ, {"CLOUD_BASE_URL": "https://nano-gpt.com/api/v1", "CLOUD_MODEL": "",
                                          "CLOUD_MODEL_BACKUP": ""}):
            importlib.reload(config)
            got = (config.CLOUD_MODEL, config.CLOUD_MODEL_BACKUP)
        importlib.reload(config)
        config.DATA_DIR = tempfile.mkdtemp()
        config.QUICK_COMMANDS = False
        config.ROUTER = False
        self.assertEqual(got, ("moonshotai/kimi-k2.5", "qwen/qwen3.5-397b-a17b"))   # ตัวไวเป็นหลัก ตัวฉลาดสำรอง


class TestNanoSTT(unittest.TestCase):
    def test_engine_choice_and_transcribe(self):
        import voice
        env = dict(CLOUD_API_KEY="nk", CLOUD_BASE_URL="https://nano-gpt.com/api/v1", MOCK_PHONE=False)
        with mock.patch.multiple(config, GROQ_API_KEY="", STT_PROVIDER="auto", **env):
            self.assertEqual(voice.stt_engine(), "nano")          # ไม่มี Groq → ใช้ NanoGPT เอง
        with mock.patch.multiple(config, GROQ_API_KEY="g", STT_PROVIDER="nano", **env):
            self.assertEqual(voice.stt_engine(), "nano")
        with mock.patch.multiple(config, GROQ_API_KEY="g", STT_PROVIDER="auto", **env):
            self.assertEqual(voice.stt_engine(), "groq")
        with mock.patch.multiple(config, GROQ_API_KEY="", CLOUD_API_KEY="k", CLOUD_BASE_URL="https://llm.chutes.ai/v1"):
            self.assertFalse(voice.stt_available())

        sent = {}

        class S:
            def post(_s, url, headers=None, files=None, data=None, **kw):
                sent.update(url=url, data=data, key=headers.get("x-api-key"))
                r = _CloudResp(200, {"text": "เปิดไลน์ให้หน่อย", "language": "th", "duration": 1.2})
                return r
        f = os.path.join(config.DATA_DIR, "u.wav")
        with open(f, "wb") as fh:
            fh.write(b"RIFF0000")
        with mock.patch.multiple(config, GROQ_API_KEY="", STT_PROVIDER="nano", **env), \
                mock.patch.object(voice, "_session", return_value=S()):
            self.assertEqual(voice.transcribe(f), "เปิดไลน์ให้หน่อย")
        self.assertEqual(sent["data"]["model"], "Whisper-Large-V3")
        self.assertEqual(sent["key"], "nk")
        self.assertIn("audio/transcriptions", sent["url"])

    def test_no_balance_message(self):
        import voice

        class S:
            def post(_s, *a, **k):
                return _CloudResp(402, text="Insufficient balance")
        f = os.path.join(config.DATA_DIR, "u2.wav")
        with open(f, "wb") as fh:
            fh.write(b"RIFF0000")
        with mock.patch.multiple(config, GROQ_API_KEY="", STT_PROVIDER="nano", CLOUD_API_KEY="nk",
                                 CLOUD_BASE_URL="https://nano-gpt.com/api/v1", MOCK_PHONE=False), \
                mock.patch.object(voice, "_session", return_value=S()):
            with self.assertRaises(voice.VoiceError) as e:
                voice.transcribe(f)
        self.assertIn("เติมเงิน", str(e.exception))


class TestCloudflareSTT(unittest.TestCase):
    def setUp(self):
        import voice
        voice._off.clear()
        self.f = os.path.join(config.DATA_DIR, "cf.wav")
        with open(self.f, "wb") as fh:
            fh.write(b"RIFF0000")

    def test_chain_order(self):
        import voice
        with mock.patch.multiple(config, GROQ_API_KEY="", CF_ACCOUNT_ID="a", CF_API_TOKEN="t", STT_PROVIDER="auto",
                                 CLOUD_API_KEY="nk", CLOUD_BASE_URL="https://nano-gpt.com/api/v1"):
            self.assertEqual(voice.stt_chain(), ["cloudflare", "nano"])
        with mock.patch.multiple(config, GROQ_API_KEY="g", CF_ACCOUNT_ID="a", CF_API_TOKEN="t",
                                 STT_PROVIDER="cloudflare", CLOUD_API_KEY=""):
            self.assertEqual(voice.stt_chain(), ["cloudflare", "groq"])

    def test_cf_transcribe_and_quota_fallback(self):
        import voice
        sent = []

        class S:
            def __init__(s, resps):
                s.resps = resps

            def post(s, url, headers=None, json=None, files=None, data=None, **kw):
                sent.append((url, json, data))
                return s.resps.pop(0)
        ok = _CloudResp(200, {"result": {"text": "เปิดยูทูบ"}, "success": True})
        with mock.patch.multiple(config, GROQ_API_KEY="", CF_ACCOUNT_ID="acc", CF_API_TOKEN="t",
                                 STT_PROVIDER="cloudflare", CLOUD_API_KEY="", MOCK_PHONE=False), \
                mock.patch.object(voice, "_session", return_value=S([ok])):
            self.assertEqual(voice.transcribe(self.f), "เปิดยูทูบ")
        self.assertIn("/accounts/acc/ai/run/@cf/openai/whisper-large-v3-turbo", sent[0][0])
        self.assertEqual(sent[0][1]["language"], "th")
        self.assertEqual(voice._last["engine"], "Cloudflare")

        quota = _CloudResp(429, text="daily free allocation of 10,000 neurons exceeded")
        nano = _CloudResp(200, {"text": "เปิดเพลง"})
        with mock.patch.multiple(config, GROQ_API_KEY="", CF_ACCOUNT_ID="acc", CF_API_TOKEN="t",
                                 STT_PROVIDER="cloudflare", CLOUD_API_KEY="nk",
                                 CLOUD_BASE_URL="https://nano-gpt.com/api/v1", MOCK_PHONE=False), \
                mock.patch.object(voice, "_session", return_value=S([quota, nano])):
            self.assertEqual(voice.transcribe(self.f), "เปิดเพลง")
            self.assertEqual(voice.stt_chain(), ["nano"])          # Cloudflare พักชั่วคราว


class TestAutoAllowPerm(unittest.TestCase):
    def _e(self, text, x=10, y=10):
        return {"text": text, "desc": "", "click": True, "edit": False, "x": x, "y": y, "id": "", "box": (0, 0, 0, 0)}

    def test_taps_allow_on_permission_dialog_only(self):
        import phone_tools
        import screen_tools
        taps = []
        items = [self._e("อนุญาตให้ LINE ถ่ายรูปไหม"), self._e("ขณะใช้แอป", 100, 200), self._e("ไม่อนุญาต", 100, 300)]
        with mock.patch.multiple(config, AUTO_ALLOW_PERMS=True, MOCK_PHONE=False), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: taps.append(a) or ""), \
                mock.patch.object(screen_tools.time, "sleep"):
            with mock.patch.object(phone_tools, "_fg", return_value="com.android.permissioncontroller"):
                self.assertEqual(screen_tools.allow_permission_popup(items), "ขณะใช้แอป")
            with mock.patch.object(phone_tools, "_fg", return_value="jp.naver.line.android"):
                self.assertIsNone(screen_tools.allow_permission_popup(items))       # ไม่ใช่ป๊อปอัปสิทธิ์
            risky = [self._e("ติดตั้งแอปจากแหล่งที่ไม่รู้จัก"), self._e("อนุญาต")]
            with mock.patch.object(phone_tools, "_fg", return_value="com.android.packageinstaller"):
                self.assertIsNone(screen_tools.allow_permission_popup(risky))       # เรื่องติดตั้งแอป ไม่กด
        with mock.patch.multiple(config, AUTO_ALLOW_PERMS=False, MOCK_PHONE=False):
            self.assertIsNone(screen_tools.allow_permission_popup(items))
        self.assertEqual(taps, [["input", "tap", "100", "200"]])

    def test_explore_records_risky_without_tapping(self):
        import app_learn
        items = [self._e("โทร", 500, 100), self._e("ส่ง", 900, 1500), self._e("ค้นหา")]
        r = app_learn._risky_map(items, 1000, 2000)
        self.assertEqual(r, {"โทร": [0.5, 0.05], "ส่ง": [0.9, 0.75]})

    def test_mic_off_flag(self):
        config.set_mic_off(True)
        self.assertTrue(config.mic_off())
        config.set_mic_off(False)
        self.assertFalse(config.mic_off())


class TestCmdMenu(unittest.TestCase):
    def test_actions_and_build(self):
        import app_brain
        import cmdmenu
        fake = {"com.instagram.android": {"label": "Instagram", "cat": "social"},
                "com.example.android.notepad": {"label": "บันทึก", "cat": "", "sys": True},
                "com.google.android.youtube": {"label": "YouTube", "cat": "video"},
                "com.android.systemui": {"label": "System UI", "sys": True}}
        with mock.patch.object(app_brain, "apps", return_value=fake):
            cat = json.loads(cmdmenu.catalog())
            pkgs = [a["pkg"] for a in cat]
            self.assertNotIn("com.android.systemui", pkgs)
            ig = next(a for a in cat if a["pkg"] == "com.instagram.android")
            titles = [x["title"] for x in ig["actions"]]
            self.assertIn("✉️ ส่งข้อความ", titles)
            self.assertIn("📞 โทร", titles)
            self.assertEqual(cmdmenu.build("com.instagram.android", "✉️ ส่งข้อความ", {"name": "ภรรยา", "text": "ถึงแล้ว"}),
                             "ส่งข้อความหา ภรรยา ใน Instagram ว่า ถึงแล้ว")
            self.assertEqual(cmdmenu.build("com.instagram.android", "💬 ไปที่แชท", {"name": "ต้น"}),
                             "ไปที่แชท ต้น ใน Instagram")
            self.assertEqual(cmdmenu.build("com.example.android.notepad", "📝 จดโน้ตใหม่", {"text": "ซื้อนม"}),
                             "จดโน้ตว่า ซื้อนม")
            self.assertEqual(cmdmenu.kind_of("com.google.android.youtube", "YouTube"), "video")


class TestScreenTask(unittest.TestCase):
    def test_vision_loop_taps_types_done(self):
        import screen_task
        import screen_tools
        import phone_tools
        import vision
        items = [{"text": "", "desc": "", "id": "fab", "x": 900, "y": 1800, "click": True, "edit": False,
                  "box": (850, 1750, 950, 1850)},
                 {"text": "", "desc": "", "id": "body", "x": 500, "y": 600, "click": True, "edit": True,
                  "box": (50, 400, 950, 800)}]
        answers = ['{"do":"tap","n":1}', 'ok {"do":"type","n":2,"text":"ซื้อนม"}', '{"do":"done","say":"สร้างโน้ตแล้ว"}']
        acts = []

        class B:
            def screenshot(self, p):
                return True

            def annotate(self, s, boxes, out):
                return True
        with mock.patch.object(config, "ANDROID_APP", True), \
                mock.patch.object(screen_task, "_b", return_value=B()), \
                mock.patch.object(screen_tools, "_dump", return_value=None), \
                mock.patch.object(screen_tools, "_screen_size", return_value=(1000, 2000)), \
                mock.patch.object(screen_tools, "_elements", return_value=items), \
                mock.patch.object(screen_tools, "adb_shell", side_effect=lambda a, **k: acts.append(a) or ""), \
                mock.patch.object(screen_tools, "allow_permission_popup", return_value=None), \
                mock.patch.object(screen_tools, "type_text", side_effect=lambda a, c: acts.append(("type", a["text"])) or "OK"), \
                mock.patch.object(phone_tools, "_fg", return_value="com.example.android.notepad"), \
                mock.patch.object(vision, "ask_images", side_effect=lambda p, i, quality=False: answers.pop(0)), \
                mock.patch.object(screen_task.time, "sleep"):
            r = screen_task.run("สร้างโน้ต ซื้อนม", None)
        self.assertEqual(r, "✅ สร้างโน้ตแล้ว")
        self.assertIn(["input", "tap", "900", "1800"], acts)
        self.assertIn(("type", "ซื้อนม"), acts)

    def test_stops_in_bank_app(self):
        import screen_task
        import phone_tools
        with mock.patch.object(config, "ANDROID_APP", True), \
                mock.patch.object(phone_tools, "_fg", return_value="com.kasikorn.retail.mbanking.wap"):
            self.assertIn("การเงิน", screen_task.run("โอนเงิน", None))

    def test_app_test_command(self):
        import app_test
        self.assertIsNotNone(app_test._CMD.match("ทดสอบแอปทั้งหมด"))
        self.assertIsNone(app_test.handle_text("เปิดไลน์"))


class TestMicQuality(unittest.TestCase):
    def test_judge_and_report(self):
        import voice
        voice.HISTORY.clear()
        self.assertEqual(voice._judge("เปิดไลน์", [{"no_speech_prob": 0.1, "avg_logprob": -0.3}], "", "Cloudflare"),
                         "เปิดไลน์")
        self.assertEqual(voice._judge("เปิดไลน์", [{"no_speech_prob": 0.9, "avg_logprob": -0.3}], "", "Cloudflare"), "")
        self.assertEqual(voice._last["dropped"], "เปิดไลน์")
        self.assertEqual(voice._judge("你好世界", [], "", "NanoGPT"), "")
        self.assertIsNone(voice._last["logprob"])
        r = voice.mic_report()
        self.assertIn("ใช้ได้ 1", r)
        import app_test
        self.assertIn("รายงานไมค์", app_test.handle_text("รายงานไมค์"))

    def test_followup_filter(self):
        import voice
        import voice_chat
        voice._last["logprob"] = None
        self.assertFalse(voice_chat.followup_ok("ครับ"))
        self.assertTrue(voice_chat.followup_ok("เปิดยูทูบ"))
        self.assertFalse(voice_chat.followup_ok("ฮ่าๆ"))
        voice._last["logprob"] = -1.2
        self.assertFalse(voice_chat.followup_ok("เปิดยูทูบให้หน่อย"))
        voice._last["logprob"] = None


class TestCfCheck(unittest.TestCase):
    def test_reports_bad_account(self):
        import voice
        import app_test

        class S:
            def get(s, *a, **k):
                return _CloudResp(401, text="{}")

            def post(s, *a, **k):
                return _CloudResp(403, text='{"errors":[{"code":10000,"message":"Authentication error"}]}')
        with mock.patch.multiple(config, CF_ACCOUNT_ID="abc", CF_API_TOKEN="tok "), \
                mock.patch.object(voice, "_session", return_value=S()):
            r = app_test.handle_text("ทดสอบ cloudflare")
        self.assertIn("Account ID ไม่ถูกรูปแบบ", r)
        self.assertIn("ช่องว่าง", r)
        self.assertIn("ไม่มีสิทธิ์ Workers AI", r)


class TestPerf(unittest.TestCase):
    def test_record_and_summary(self):
        import perf
        for p in ("perf.jsonl", "mic.jsonl", "app_test.json"):
            try:
                os.remove(os.path.join(config.DATA_DIR, p))
            except OSError:
                pass
        perf.record("quick", "เปิดไวไฟ", stt=0.6, total=1.2, ok=True)
        perf.record("voice", "หาข่าว", stt=0.8, first_token=3.0, first_sound=4.5, total=9.0, ok=True)
        perf.record("chat", "ส่งไลน์", total=6.0, ok=False)
        self.assertFalse(perf.looks_ok("❗ ผิดพลาด"))
        self.assertTrue(perf.looks_ok("เปิดแล้วครับ"))
        with mock.patch.dict(os.environ, {"SHARED_STORAGE": config.DATA_DIR}):
            s = perf.handle_text("สรุปผลทดสอบ")
        self.assertIn("คำสั่งด่วน: กลาง 1.2", s)
        self.assertIn("เริ่มพูด: กลาง 4.5", s)
        self.assertIn("2/3", s)
        self.assertIn("ผลทดสอบผู้ช่วย", s)


class TestCloudSpeed(unittest.TestCase):
    def test_slow_model_moves_behind(self):
        import cloud_client as cc
        cc._lat.clear(); cc._bad_until.clear()
        with mock.patch.multiple(config, CLOUD_MODEL="a", CLOUD_MODEL_BACKUP="b"):
            cc._note_latency("a", 40.0)
            cc._note_latency("b", 3.0)
            self.assertEqual(cc.models_to_try(), ["b", "a"])
            cc._lat.clear()
            self.assertEqual(cc.models_to_try(), ["a", "b"])

    def test_router_skips_without_groq(self):
        import router
        with mock.patch.multiple(config, GROQ_API_KEY="", LLM_PROVIDER="cloud"):
            self.assertEqual(router.classify("สบายดีไหม")["intent"], "phone_task")


class TestAppoint(unittest.TestCase):
    def setUp(self):
        import appoint
        appoint._S.clear()
        from unittest import mock
        self.p = mock.patch.object(appoint, "_llm_extract", return_value={})   # ทดสอบกฎพื้นฐาน (ไม่เรียก AI)
        self.p.start()

    def tearDown(self):
        import appoint
        self.p.stop()
        appoint._S.clear()

    def test_appointment_dialog_asks_each_field_then_creates(self):
        import appoint
        from unittest import mock
        self.assertIn("วันไหน", appoint.handle_text("สร้างนัด"))
        self.assertIn("กี่โมง", appoint.handle_text("พรุ่งนี้"))
        self.assertIn("จบกี่โมง", appoint.handle_text("บ่ายสอง"))
        self.assertIn("เรื่องอะไร", appoint.handle_text("สี่โมงเย็น"))
        self.assertIn("สำคัญ", appoint.handle_text("ประชุมกับลูกค้า"))
        s = appoint.handle_text("ด่วนมาก")
        self.assertIn("14:00 ถึง 16:00", s)
        self.assertIn("ถูกต้องไหม", s)
        with mock.patch.object(appoint, "connected", return_value=True), \
                mock.patch.object(appoint, "_post", return_value={"ok": True}) as post:
            r = appoint.handle_text("ใช่")
        self.assertIn("ลง Google Calendar แล้ว", r)
        ev = post.call_args[0][0]
        self.assertEqual(ev["action"], "create")
        self.assertTrue(ev["start"].endswith("T14:00:00+07:00"))
        self.assertEqual(ev["color"], "11")
        self.assertFalse(appoint.active())

    def test_cancel_and_duration(self):
        import appoint
        appoint.handle_text("สร้างนัด วันนี้ 10 โมง")
        self.assertIn("จบกี่โมง", appoint.handle_text("10:00") or "จบกี่โมง")
        appoint._S["data"].update(start="10:00")
        appoint._S["data"].pop("end", None)
        appoint._S["ask"] = "time"
        appoint.handle_text("ชั่วโมงเดียว")
        self.assertEqual(appoint._S["data"]["end"], "11:00")
        self.assertIn("ยกเลิก", appoint.handle_text("ยกเลิก"))
        self.assertFalse(appoint.active())

    def test_job_record_to_calendar(self):
        import appoint
        from unittest import mock
        self.assertIn("ลูกค้า", appoint.handle_text("บันทึกงาน job 1234"))
        self.assertIn("สถานะ", appoint.handle_text("สมชาย ใจดี"))
        self.assertIn("รายละเอียด", appoint.handle_text("ซ่อมเสร็จแล้ว"))
        self.assertIn("กี่บาท", appoint.handle_text("เปลี่ยนจอและแบตเตอรี่"))
        s = appoint.handle_text("1,500 บาท")
        self.assertIn("Job 1234", s)
        self.assertIn("1,500 บาท", s)
        with mock.patch.object(appoint, "connected", return_value=True), \
                mock.patch.object(appoint, "_post", return_value={"ok": True}) as post:
            appoint.handle_text("ถูกต้อง")
        ev = post.call_args[0][0]
        self.assertEqual(ev["key"], "job-1234-ทำงานเสร็จแล้ว")
        self.assertIn("[ทำงานเสร็จแล้ว] Job 1234 · สมชาย ใจดี · 1,500 บาท", ev["title"])
        self.assertIn("ค่าใช้จ่ายทั้งหมด: 1,500 บาท", ev["description"])

    def test_not_connected_opens_calendar_app(self):
        import appoint, phone_tools
        from unittest import mock
        appoint.handle_text("สร้างนัด")
        appoint._S["data"].update(date="2026-11-05", start="09:00", end="10:00", title="หาหมอ", priority="ปกติ")
        appoint._S["ask"] = None
        appoint._S["confirm"] = True
        with mock.patch.object(appoint, "connected", return_value=False), \
                mock.patch.object(phone_tools, "_launcher_components",
                                  return_value=["com.huawei.calendar/.Main", "com.google.android.calendar/.All"]), \
                mock.patch.object(phone_tools, "_sh", return_value="Starting") as sh:
            r = appoint.handle_text("ใช่")
        args = sh.call_args[0][0]
        self.assertIn("android.intent.action.INSERT", args)
        self.assertEqual(args[args.index("-p") + 1], "com.google.android.calendar")
        self.assertIn("กดบันทึก", r)

    def test_unrelated_text_passes_through(self):
        import appoint
        self.assertIsNone(appoint.handle_text("เปิดไลน์"))

    def test_calendar_alias_picks_installed_package(self):
        import phone_tools
        self.assertEqual(phone_tools.ALIASES["ปฏิทิน"], "calendar")
        self.assertIn("com.huawei.calendar", phone_tools.ALT_PKGS["calendar"])


class TestHonestAndWake(unittest.TestCase):
    def test_claims_done_detected(self):
        import agent
        self.assertTrue(agent._claims_done("ได้เลย เปิด WPS สร้างเอกสาร Word ให้แล้วครับ หน้าว่างๆ", "เข้าแอป WPS แล้วสร้างไฟล์ Word"))
        self.assertFalse(agent._claims_done("ยังเปิดไม่ได้ครับ", "เปิด WPS"))
        self.assertFalse(agent._claims_done("วันนี้อากาศดีครับ", "อากาศเป็นไง"))

    def test_short_loud_wake_word_passes_gate(self):
        import audio_stream, struct, math
        def tone(a, n):
            return b"".join(struct.pack("<h", int(a * math.sin(i / 3))) for i in range(audio_stream.FRAME_SAMPLES)) * n
        # ห้องมีพัดลม (noise 220) + "โอเคผู้ช่วย" สั้นๆ ดังๆ 0.6 วิ
        pcm = tone(300, 10) + tone(2000, 20) + tone(300, 10)
        self.assertTrue(audio_stream.is_speechy(pcm, noise=220.0))
        self.assertFalse(audio_stream.is_speechy(tone(300, 40), noise=220.0))   # เสียงพัดลมอย่างเดียว


class TestVoiceV52(unittest.TestCase):
    def test_prompt_echo_is_hallucination(self):
        import voice
        prompt = "ชื่อแอป: ไลน์ ไอจี, Haryaya, Wanchaporn Pancrit, ภรรยา, แม่, Heart"
        self.assertTrue(voice.prompt_echo("ไปที่แชท Haryaya, Wanchaporn Pancrit, ภรรยา, Wanchaporn Pancrit", prompt))
        self.assertFalse(voice.prompt_echo("ส่งข้อความหาแม่ว่ากินข้าวยัง", prompt))

    def test_utterance_ends_in_fan_noise(self):
        import audio_stream, struct, math
        def tone(a):
            return b"".join(struct.pack("<h", int(a * math.sin(i / 3))) for i in range(audio_stream.FRAME_SAMPLES))
        frames = [tone(2500)] * 25 + [tone(400)] * 400        # พูด 0.75 วิ แล้วพัดลมดังกว่าเกณฑ์ตลอด
        m = audio_stream.MicStream.__new__(audio_stream.MicStream)
        m.noise = 60.0
        it = iter(frames)
        m._frame = lambda timeout=1.0: next(it)
        m._track_noise = lambda lv: None
        pcm = m.utterance(max_seconds=15.0, end_silence=0.9)
        self.assertLess(len(pcm) / 32000, 3.0)                  # จบเร็ว ไม่ฟังยาวเต็ม 15 วิ

    def test_fuzzy_yes(self):
        import appoint, send_confirm
        for w in ("ช่าย", "ช้าย", "ใช่", "ได้เลย"):
            self.assertTrue(appoint._YES.match(w), w)
            self.assertTrue(send_confirm._YES.match(w), w)
