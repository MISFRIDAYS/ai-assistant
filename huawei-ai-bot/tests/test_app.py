"""ทดสอบโหมดแอป APK (android_shim / Bridge จำลอง) — รัน: python -m unittest tests.test_app"""
import json
import os
import sys
import tempfile
import time
import types
import unittest
import zipfile
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
os.environ.setdefault("SHARED_STORAGE", tempfile.mkdtemp())
os.environ.setdefault("HUMAN_TYPING", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
config.DATA_DIR = tempfile.mkdtemp()
import android_shim  # noqa: E402

XML = ('<?xml version="1.0"?><hierarchy rotation="0"><node index="0" text="" resource-id="" class="F" package="x" '
       'content-desc="" clickable="false" bounds="[0,0][1000,2000]">'
       '<node index="0" text="บังคับหยุด" resource-id="force" class="android.widget.Button" package="x" '
       'content-desc="" clickable="true" bounds="[100,100][300,200]" />'
       '<node index="1" text="" resource-id="msg" class="android.widget.EditText" package="x" '
       'content-desc="" clickable="true" bounds="[0,1800][800,1900]" /></node></hierarchy>')


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.a11y = True
        self.mic = [b"\x01\x00" * 480] * 3

    def __getattr__(self, name):
        def f(*a):
            self.calls.append((name,) + a)
            return {"a11yOn": self.a11y, "dump": XML, "currentPackage": "jp.naver.line.android",
                    "currentActivity": ".Chat", "rotation": 0, "screenSize": "1000x2000",
                    "battery": '{"percentage": 80, "status": "DISCHARGING"}',
                    "notifications": '[{"key":"k1","packageName":"jp.naver.line.android","title":"แม่","content":"กินข้าวยัง"}]',
                    "volumes": '[{"stream":"music","volume":5,"max_volume":15}]',
                    "launcherApps": "LINE|jp.naver.line.android|.Main\nเครื่องคิดเลข|com.calc|.Calc\n",
                    "mediaUri": "content://media/external/images/media/42", "micAllowed": True,
                    "micStart": True, "canWriteSettings": True, "pollEvents": "[]", "resolve": "com.x/.Y",
                    "startIntent": "Starting: Intent {}", "memInfo": '{"total": 8000000000, "avail": 3000000000}',
                    "prop": "HUAWEI", "settingsGet": "1", "wifiEnabled": True, "notifReply": True, "lastViaIme": False,
                    }.get(name, True)
        return f

    def micRead(self, ms):
        self.calls.append(("micRead", ms))
        return self.mic.pop(0) if self.mic else b""


class TestShim(unittest.TestCase):
    def setUp(self):
        self.b = FakeBridge()
        android_shim.B = self.b
        self.p = mock.patch.object(config, "ANDROID_APP", True)
        self.p2 = mock.patch.object(config, "MOCK_PHONE", False)
        self.p.start()
        self.p2.start()

    def tearDown(self):
        self.p.stop()
        self.p2.stop()

    def names(self):
        return [c[0] for c in self.b.calls]

    def test_adb_shell_routes_to_bridge(self):
        import phone_tools
        import screen_tools
        self.assertEqual(screen_tools.adb_serial(), "app")
        screen_tools.adb_shell(["input", "tap", "10", "20"])
        self.assertIn(("tap", 10, 20), self.b.calls)
        screen_tools.adb_shell(["input", "keyevent", "4"])
        self.assertIn(("key", 4), self.b.calls)
        screen_tools.adb_shell(["input", "swipe", "1", "2", "3", "400", "300"])
        self.assertIn(("swipe", 1, 2, 3, 400, 300), self.b.calls)
        out = screen_tools.adb_shell(["uiautomator", "dump", "/dev/tty"])
        self.assertIn("<hierarchy", out)
        self.assertIn("jp.naver.line.android", phone_tools._fg())
        self.assertIn("80", phone_tools.run(["termux-battery-status"]))
        self.b.a11y = False
        self.assertIsNone(screen_tools.adb_serial())

    def test_quoted_am_start_and_extras(self):
        import screen_tools
        screen_tools.adb_shell(["am", "start", "-a", "android.intent.action.SEND", "-t", "image/*",
                                "--eu", "android.intent.extra.STREAM", "content://media/1", "-p",
                                "jp.naver.line.android"], quote=True)
        it = json.loads(next(c for c in self.b.calls if c[0] == "startIntent")[1])
        self.assertEqual(it["action"], "android.intent.action.SEND")
        self.assertEqual(it["streams"], ["content://media/1"])
        self.assertEqual(it["package"], "jp.naver.line.android")

    def test_elements_and_type_text_thai(self):
        import screen_tools
        items = screen_tools._elements(screen_tools._dump())
        self.assertTrue(any(e["edit"] for e in items))
        with mock.patch("time.sleep"):
            r = screen_tools.type_text({"text": "สวัสดีครับ", "send": False}, None)
        self.assertIn(("typeText", "สวัสดีครับ", False), self.b.calls)
        self.assertIn("ยังไม่ส่ง", r)

    def test_force_stop_taps_button(self):
        with mock.patch("time.sleep"):
            android_shim.run(["adb", "-s", "app", "shell", "am", "force-stop", "com.x"])
        self.assertIn(("appDetails", "com.x"), self.b.calls)
        self.assertIn(("tap", 200, 150), self.b.calls)

    def test_settings_volume_dnd_and_unsupported(self):
        android_shim.run(["settings", "put", "system", "screen_brightness", "50"])
        self.assertIn(("settingsPut", "system", "screen_brightness", "50"), self.b.calls)
        android_shim.run(["cmd", "notification", "set_dnd", "off"])
        self.assertIn(("dnd", False), self.b.calls)
        self.assertTrue(android_shim.run(["svc", "wifi", "enable"]).startswith("ERROR"))
        self.assertIn("music", android_shim.run(["termux-volume"]))
        android_shim.run(["termux-volume", "music", "3"])
        self.assertIn(("setVolume", "music", 3), self.b.calls)
        self.assertEqual(android_shim.run(["termux-clipboard-set"], input_text="ก"), "")
        self.assertIn(("clipboardSet", "ก"), self.b.calls)

    def test_screenshot_and_content_query(self):
        android_shim.run(["bash", "-c", "adb -s app exec-out screencap -p > '/tmp/x.png'"])
        self.assertIn(("screenshot", "/tmp/x.png"), self.b.calls)
        out = android_shim.run(["content", "query", "--uri", "content://media/external/file", "--projection",
                                "_id", "--where", "_data='/sdcard/a.jpg'"])
        self.assertIn("_id=42", out)

    def test_app_index_uses_labels(self):
        import app_index
        app_index._cache.update(apps=None, building=False)
        apps = app_index.build(force=True)
        self.assertIn({"pkg": "com.calc", "label": "เครื่องคิดเลข"}, apps)

    def test_notification_reply_direct(self):
        import share_tools
        import skills
        skills.set_pref("last_notif", {"app": "line", "to": "แม่", "t": __import__("time").time(), "key": "k1"})
        with mock.patch.object(share_tools, "send_dm") as sd:
            r = share_tools.reply_last("โอเค")
        self.assertIn(("notifReply", "k1", "โอเค"), self.b.calls)
        sd.assert_not_called()
        self.assertIn("แม่", r)

    def test_android_mic_frames(self):
        import audio_stream
        m = audio_stream.AndroidMic()
        f = m._frame(timeout=2)
        self.assertEqual(len(f), audio_stream.FRAME_BYTES)
        self.assertTrue(any(f))
        m.close()
        self.assertIn("micStop", self.names())

    def test_mic_owner_gets_frames_others_silence(self):
        import threading
        import audio_stream
        self.b.mic = [b"\x10\x00" * 480] * 50
        m = audio_stream.AndroidMic()
        m.owner = threading.get_ident()
        got = []
        t = threading.Thread(target=lambda: got.append(m._frame(timeout=1)))
        t.start()
        t.join(2)
        self.assertFalse(any(got[0]))                 # ผู้ช่วยเสียงเบื้องหลังได้ความเงียบ
        self.assertTrue(any(m._frame(timeout=2)))     # ปุ่มไมค์ได้เสียงจริง
        self.assertGreater(m.peak, 0)
        m.close()

    def test_ui_popup_in_app(self):
        import ui
        ui.listening()
        ui.heard("เปิดยูทูป")
        ui.speaking("เปิดให้แล้วครับ")
        ui.done("")
        ui.idle()
        st = [c[1] for c in self.b.calls if c[0] == "assistant"]
        self.assertEqual(st, ["listen", "heard", "speak", "done", "idle"])
        self.assertIn(("assistant", "done", "เปิดให้แล้วครับ"), self.b.calls)

    def test_play_youtube_via_app(self):
        import app_skills
        import xml.etree.ElementTree as ET
        import screen_tools
        root = ET.fromstring('<hierarchy><node bounds="[0,0][1000,2000]"/></hierarchy>')
        items = [{"text": "", "desc": "เพลงดี – 4 นาที – ยอดดู 1 ล้านครั้ง", "id": "", "edit": False, "click": True,
                  "x": 500, "y": 600, "box": (0, 500, 1000, 700)}]
        with mock.patch("time.sleep"), mock.patch.object(screen_tools, "_dump", return_value=root), \
                mock.patch.object(screen_tools, "_elements", return_value=items):
            r = app_skills.play("เพลงดี")
        it = json.loads(next(c for c in self.b.calls if c[0] == "startIntent")[1])
        self.assertIn("search_query=%E0", it["data"])
        self.assertIn(("tap", 500, 600), self.b.calls)
        self.assertIn("กำลังเล่น", r)

    def test_qs_toggle_wifi(self):
        import android_shim
        xml = ('<hierarchy><node bounds="[0,0][1000,2000]"><node text="" content-desc="Wi-Fi" clickable="true" '
               'bounds="[100,100][300,250]" /><node text="บลูทูธ" content-desc="" clickable="false" bounds="[350,200][450,240]" />'
               '<node text="" content-desc="" clickable="true" bounds="[320,100][480,260]" /></node></hierarchy>')
        states = iter(["0", "1"])
        self.b.dump = lambda: xml
        self.b.sysState = lambda k: next(states)
        with mock.patch("time.sleep"):
            r = android_shim.qs_toggle("wifi", "Wi-Fi", True)
        self.assertIn("เปิด Wi-Fi แล้ว", r)
        self.assertIn(("tap", 200, 175), self.b.calls)
        states2 = iter(["1", "0"])
        self.b.sysState = lambda k: next(states2)
        with mock.patch("time.sleep"):
            r = android_shim.qs_toggle("bluetooth", "บลูทูธ", False)
        self.assertIn(("tap", 400, 180), self.b.calls)            # ป้าย → ปุ่มที่ครอบป้าย

    def test_app_recorder_convert(self):
        import app_learn
        ev = [{"type": "click", "text": "ค้นหา", "id": "search", "edit": True, "x": 500, "y": 100},
              {"type": "text", "text": "ลา", "id": "search"}, {"type": "text", "text": "ลาเต้", "id": "search"},
              {"type": "click", "text": "", "desc": "สั่งเลย", "id": "", "x": 500, "y": 1900}]
        st = app_learn.AppRecorder.convert(ev, 1000, 2000, "com.coffee")
        self.assertEqual([s["type"] for s in st], ["open", "tap", "type", "tap"])
        self.assertEqual(st[2]["text"], "ลาเต้")
        self.assertEqual((st[3]["label"], st[3]["ry"]), ("สั่งเลย", 0.95))

    def test_self_heal_runs_tests_via_bridge(self):
        import self_heal
        self.b.runHeal = lambda root, t: json.dumps({"failed": ["a.b"], "detail": "x"})
        failed, detail = self_heal.run_tests("/tmp/stage")
        self.assertEqual(failed, {"a.b"})
        self.assertEqual(self_heal._compile_errors([__file__]), "")


class TestAndroidMain(unittest.TestCase):
    """android_main (อยู่ในโปรเจกต์แอป) — จำลองโมดูล java ของ Chaquopy"""

    def setUp(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(os.path.dirname(here), "aibot-app", "app", "src", "main", "python")
        if not os.path.exists(os.path.join(p, "android_main.py")):
            self.skipTest("ไม่มีโปรเจกต์แอป")
        self.files = tempfile.mkdtemp()
        self.b = FakeBridge()
        self.b.filesDir = lambda: self.files
        self.b.versionCode = lambda: 7

        def copy(src, dest):
            import shutil
            shutil.copytree(here, dest, ignore=shutil.ignore_patterns("__pycache__", "data", "*.pyc"))
            return 1
        self.b.copyAssets = copy
        java = types.ModuleType("java")
        java.jclass = lambda name: self.b
        self.mods = mock.patch.dict(sys.modules, {"java": java})
        self.mods.start()
        sys.path.insert(0, p)
        self.cwd = os.getcwd()
        self.env = dict(os.environ)

    def tearDown(self):
        self.mods.stop()
        os.chdir(self.cwd)
        os.environ.clear()
        os.environ.update(self.env)
        sys.modules.pop("android_main", None)

    def test_install_and_run_tests_result(self):
        import android_main
        android_main._ready[0] = False
        self.assertTrue(android_main._install_code())
        self.assertTrue(os.path.exists(os.path.join(self.files, "bot", "bot.py")))
        self.assertFalse(android_main._install_code())                    # เวอร์ชันเดิม → ไม่แตกซ้ำ
        stage = tempfile.mkdtemp()
        os.makedirs(os.path.join(stage, "tests"))
        with open(os.path.join(stage, "tests", "test_x.py"), "w") as f:
            f.write("import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
                    "    def test_bad(self):\n        self.fail('x')\n")
        res = os.path.join(stage, "r.json")
        android_main.run_tests(stage, res)
        d = json.load(open(res))
        self.assertEqual(d["ran"], 2)
        self.assertEqual(len(d["failed"]), 1)
        sys.path.remove(stage)


    def test_guard_restarts_crashed_task(self):
        import android_main
        runs, waits = [], []

        def task():
            runs.append(1)
            if len(runs) < 3:
                raise RuntimeError("ไมค์ค้าง")
            raise SystemExit("หยุดจริง")          # SystemExit = ตั้งใจหยุด → ไม่เริ่มใหม่
        with mock.patch("self_heal.record"), mock.patch("self_heal.after_crash_in_app", return_value=False):
            android_main._guard("voice_test", task, sleep=waits.append)
        self.assertEqual(len(runs), 3)
        self.assertEqual(waits, [5, 10])
        self.assertEqual(android_main._restarts.get("voice_test"), 2)

    def test_restart_wait_capped(self):
        import android_main
        self.assertEqual([android_main._restart_wait(n) for n in (1, 2, 3, 7, 50)], [5, 10, 20, 300, 300])

class TestAppSkills(unittest.TestCase):
    def test_parse_commands(self):
        import app_skills
        with mock.patch.object(app_skills, "play", return_value="p") as pl, \
                mock.patch.object(app_skills, "search", return_value="s") as se, \
                mock.patch.object(app_skills, "navigate", return_value="n") as nv:
            self.assertEqual(app_skills.handle_text("เปิดเพลง ลาลาลอย ใน youtube หน่อย"), "p")
            self.assertEqual(pl.call_args[0][:2], ("ลาลาลอย", "youtube"))
            app_skills.handle_text("อยากฟังเพลง lofi chill")
            self.assertEqual(pl.call_args[0][0], "lofi chill")
            app_skills.handle_text("เปิดยูทูปแล้วหาเพลง cocktail")
            self.assertEqual(pl.call_args[0][0], "cocktail")
            self.assertEqual(app_skills.handle_text("หา รองเท้าวิ่ง ใน ช้อปปี้"), "s")
            self.assertEqual(se.call_args[0][:2], ("ช้อปปี้", "รองเท้าวิ่ง"))
            self.assertEqual(app_skills.handle_text("นำทางไปเซ็นทรัลเวิลด์"), "n")
            self.assertIsNone(app_skills.handle_text("เปิด youtube"))
            self.assertIsNone(app_skills.handle_text("ส่งไลน์หาแม่ว่า ถึงแล้ว"))

    def test_first_video_skips_ads(self):
        import app_skills
        items = [_e("ค้นหา", 500, 80), _e("โฆษณา เพลงฮิต 3 นาที", 500, 300),
                 _e("ลาลาลอย - The TOYS – 4 นาที 10 วินาที – ยอดดู 200 ล้านครั้ง – เล่นวิดีโอ", 500, 700),
                 _e("อีกเพลง 3 นาที", 500, 1200)]
        v = app_skills._first_video(items, 2000)
        self.assertEqual(v["y"], 700)

    def test_knowledge_hint(self):
        import app_skills
        self.assertIn("ไลน์", app_skills.knowledge("ส่งไลน์หาแม่") .replace("line", "ไลน์"))


def _e(desc, x, y):
    return {"text": "", "desc": desc, "id": "", "edit": False, "click": True, "x": x, "y": y,
            "box": (x - 50, y - 50, x + 50, y + 50)}


class TestNoiseFilter(unittest.TestCase):
    def test_hallucination_and_prompt_echo(self):
        import voice
        self.assertTrue(voice.is_hallucination("ขอบคุณที่รับชมครับ"))
        self.assertTrue(voice.is_hallucination("อืม"))
        self.assertTrue(voice.is_hallucination("instagram line", "สวัสดีผู้ช่วย instagram, line, แม่"))
        self.assertFalse(voice.is_hallucination("เปิด youtube"))
        self.assertFalse(voice.is_hallucination("ครับ"))

    def test_speech_gate(self):
        import array
        import audio_stream
        quiet = array.array("h", [30] * 16000).tobytes()
        click = array.array("h", [9000] * 480 + [20] * 15520).tobytes()       # เสียงเคาะสั้นๆ
        talk = array.array("h", ([2500, -2500] * 4000) + [20] * 8000).tobytes()  # พูด 0.5 วิ
        self.assertFalse(audio_stream.is_speechy(quiet, 20))
        self.assertFalse(audio_stream.is_speechy(click, 20))
        self.assertTrue(audio_stream.is_speechy(talk, 20))

    def test_transcribe_rejects_no_speech(self):
        import voice
        r = mock.Mock(status_code=200)
        r.json.return_value = {"text": "เปิด instagram", "segments": [{"no_speech_prob": 0.9, "avg_logprob": -0.3}]}
        sess = mock.Mock(); sess.post.return_value = r
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.write(b"x"); f.close()
        with mock.patch.object(config, "MOCK_PHONE", False), mock.patch.object(config, "GROQ_API_KEY", "k"), \
                mock.patch.object(voice, "_session", return_value=sess):
            self.assertEqual(voice.transcribe(f.name), "")
            r.json.return_value = {"text": "เปิด youtube", "segments": [{"no_speech_prob": 0.05, "avg_logprob": -0.2}]}
            self.assertEqual(voice.transcribe(f.name), "เปิด youtube")


class TestNewBrains(unittest.TestCase):
    def test_weather_format(self):
        import info
        geo = mock.Mock(); geo.json.return_value = {"results": [{"latitude": 18.8, "longitude": 98.9, "name": "เชียงใหม่"}]}
        fc = mock.Mock(); fc.json.return_value = {
            "current": {"temperature_2m": 31.2, "apparent_temperature": 35, "relative_humidity_2m": 60,
                        "weather_code": 2, "wind_speed_10m": 8},
            "daily": {"time": ["a", "b", "c"], "weather_code": [61, 3, 0], "temperature_2m_min": [24, 23, 22],
                      "temperature_2m_max": [33, 32, 31], "precipitation_probability_max": [80, 20, 0],
                      "uv_index_max": [9, 8, 7]}}
        with mock.patch.object(info, "_get", side_effect=[geo, fc]):
            out = info.weather("เชียงใหม่", 0)
        self.assertIn("เชียงใหม่", out)
        self.assertIn("31°C", out)
        self.assertIn("โอกาสฝน 80%", out)
        self.assertIn("ร่ม", out)

    def test_news_rss(self):
        import info
        r = mock.Mock(); r.content = ("<rss><channel><item><title>ทองขึ้น - ข่าวสด</title><source>ข่าวสด</source></item>"
                                      "<item><title>ฝนตกหนัก</title></item></channel></rss>").encode()
        with mock.patch.object(info, "_get", return_value=r):
            out = info.news("ทอง")
        self.assertIn("ทองขึ้น", out)
        self.assertIn("ฝนตกหนัก", out)

    def test_mind_observe_and_diary(self):
        import mind
        import extras
        with mock.patch.dict(os.environ, {"MEMORY_AUTO": "1", "MIND_ENABLED": "1"}):
            new = mind.observe("ผมชื่อต้นนะ")
            mind.observe("ผมแพ้กุ้ง")
            mind.observe("แฟนผมชื่อมิ้น")
            self.assertEqual(mind.observe("ผมชอบอะไร"), [])          # คำถาม ไม่ใช่การบอกข้อมูล
            texts = [m["text"] for m in extras.memories()]
            self.assertTrue(any("ต้น" in t for t in texts), texts)
            self.assertTrue(any("แพ้ กุ้ง" in t or "แพ้กุ้ง" in t for t in texts), texts)
            self.assertTrue(any("มิ้น" in t for t in texts), texts)
            self.assertTrue(new)
            mind.log_turn("เปิด youtube", "เปิดแล้ว")
            self.assertIn("เปิด youtube", mind.handle_text("วันนี้ทำอะไรไปบ้าง"))
            self.assertIn("ตัวตนของคุณ", mind.self_prompt())

    def test_mind_battery_thought(self):
        import mind
        with mock.patch.dict(os.environ, {"MIND_ENABLED": "1"}), \
                mock.patch.object(mind, "_battery", return_value=(9, "DISCHARGING")), \
                mock.patch("time.localtime", return_value=time.struct_time((2026, 10, 30, 13, 0, 0, 3, 303, 0))):
            msg = mind.think()
            self.assertIn("แบตเหลือ 9%", msg)
            self.assertIsNone(mind.think())                           # เตือนครั้งเดียว

    def test_vision_routing_and_chi2(self):
        import vision
        self.assertEqual(vision.chi2([0.5, 0.5], [0.5, 0.5]), 0)
        with mock.patch.object(vision, "who_is_there", return_value="w"), \
                mock.patch.object(vision, "enroll_owner", return_value="e"), \
                mock.patch.object(vision, "look", return_value="l"):
            self.assertEqual(vision.handle_text("ใครอยู่หน้ากล้อง"), "w")
            self.assertEqual(vision.handle_text("จำหน้าฉันหน่อย"), "e")
            self.assertEqual(vision.handle_text("เห็นอะไรบ้าง"), "l")
            self.assertIsNone(vision.handle_text("เปิดกล้อง"))


class TestDevice(unittest.TestCase):
    def setUp(self):
        self.b = FakeBridge()
        android_shim.B = self.b
        self.ps = [mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "MOCK_PHONE", False)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def test_info_and_storage(self):
        import device
        out = device.handle_text("ข้อมูลเครื่อง")
        self.assertIn("TXZ-W09", out)
        self.assertIn("Kirin 8020", out)
        self.assertIn("แบต", out)
        self.assertIn("พื้นที่ว่าง", device.handle_text("พื้นที่เหลือเท่าไหร่"))
        self.assertIn("แรมว่าง", device.handle_text("แรมเหลือเท่าไหร่"))
        self.assertIn("AppGallery", device.prompt())

    def test_routing(self):
        import device
        with mock.patch.object(device, "toggle", return_value="T") as tg, \
                mock.patch.object(device, "open_setting", return_value="O") as op:
            self.assertEqual(device.handle_text("เปิดโหมดมืดหน่อย"), "T")
            tg.assert_called_with("โหมดมืด", True)
            self.assertEqual(device.handle_text("ปิดถนอมสายตา"), "T")
            tg.assert_called_with("ถนอมสายตา", False)
            self.assertEqual(device.handle_text("เปิดหน้าตั้งค่าเสียง"), "O")
            op.assert_called_with("เสียง")
            self.assertIsNone(device.handle_text("เปิด youtube"))
            self.assertIsNone(device.handle_text("เปิดไลน์"))

    def test_deny_and_switch(self):
        import device
        self.assertIn("🔒", device.toggle("รหัสผ่านหน้าจอ", False))
        items = [{"text": "โหมดมืด", "desc": "", "id": "title", "x": 100, "y": 500, "click": False, "edit": False,
                  "box": (0, 470, 600, 530), "checkable": False, "checked": False},
                 {"text": "", "desc": "", "id": "switch_widget", "x": 900, "y": 500, "click": True, "edit": False,
                  "box": (850, 470, 950, 530), "checkable": True, "checked": True}]
        sw, checked = device._switch_near(items, r"โหมดมืด")
        self.assertEqual(sw["x"], 900)
        self.assertTrue(checked)


class TestSocial(unittest.TestCase):
    def test_routing(self):
        import social
        with mock.patch.object(social, "call", return_value="C") as c, \
                mock.patch.object(social, "feed_summary", return_value="F") as f:
            self.assertEqual(social.handle_text("เข้า instagram แล้วกดโทรหา ภรรยา(คนเจก)"), "C")
            c.assert_called_with("instagram", "ภรรยา(คนเจก)", False, None)
            self.assertEqual(social.handle_text("วิดีโอคอลหาแม่ทางไลน์หน่อย"), "C")
            c.assert_called_with("line", "แม่", True, None)
            self.assertIsNone(social.handle_text("โทรหาแม่"))
            self.assertEqual(social.handle_text("เข้าเฟสบุ๊คแล้วหาโพสที่น่าสนใจในวันนี้ครับ"), "F")
            self.assertEqual(f.call_args[0][0], "facebook")
            self.assertIn("โพส", f.call_args[0][1])
            self.assertEqual(social.handle_text("ดูทวิตเตอร์ว่ามีอะไรน่าสนใจ"), "F")
            self.assertIsNone(social.handle_text("เปิดเฟสบุ๊ค"))

    def test_call_button(self):
        import social
        def e(desc, y, x=900):
            return {"text": "", "desc": desc, "id": "", "x": x, "y": y, "click": True, "edit": False,
                    "box": (x - 40, y - 40, x + 40, y + 40)}
        items = [e("Audio call", 100, 800), e("Video call", 100), e("Send", 1900)]
        b, exact = social._call_btn(items, False)
        self.assertEqual(b["desc"], "Audio call")
        self.assertTrue(exact)
        b, exact = social._call_btn(items, True)
        self.assertEqual(b["desc"], "Video call")
        ig = [dict(e("ภรรยา ไอคอนคัตเอาต์ Riff, วิดีโอคอล, การโทรด้วยเสียง, ย้อนกลับ", 150, 500), box=(0, 100, 1000, 200)),
              dict(e("การโทรด้วยเสียง", 150, 820), click=False), dict(e("วิดีโอคอล", 150, 920), click=False),
              e("สัญญาณ Wi-Fi เต็ม", 20), e("ข้อความ...", 1900)]
        b, exact = social._call_btn(ig, False)
        self.assertEqual((b["desc"], exact), ("การโทรด้วยเสียง", True))
        self.assertEqual(social._call_btn(ig, True)[0]["desc"], "วิดีโอคอล")
        b, exact = social._call_btn([e("โทร", 100), e("ส่ง", 1900)], False)
        self.assertFalse(exact)
        self.assertEqual(b["desc"], "โทร")

    def test_compound_guard(self):
        import agent
        self.assertTrue(agent._COMPOUND.search("เข้าเฟสบุ๊คแล้วหาโพส"))
        self.assertFalse(agent._COMPOUND.search("เปิดเฟสบุ๊ค"))


class TestInApp(unittest.TestCase):
    def setUp(self):
        self.ps = [mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "MOCK_PHONE", False)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def run_in(self, pkg, text, chat=True):
        import app_skills
        import inapp
        import share_tools
        with mock.patch.object(inapp, "current", return_value=pkg), \
                mock.patch.object(inapp, "_key") as k, \
                mock.patch.object(app_skills, "play", return_value="P") as pl, \
                mock.patch.object(app_skills, "search", return_value="S") as se, \
                mock.patch.object(share_tools, "chat_open", return_value=chat), \
                mock.patch.object(share_tools, "send_here", return_value="T") as sh:
            r = inapp.handle_text(text)
            return r, k, pl, se, sh

    def test_media(self):
        yt = "com.google.android.youtube"
        r, k, *_ = self.run_in(yt, "เปิดเพลงอื่นหน่อย")
        k.assert_called_with(87)
        r, k, pl, *_ = self.run_in(yt, "เปิดเพลงของ The Weeknd")
        pl.assert_called_with("The Weeknd", "youtube", None)
        r, k, pl, se, _ = self.run_in(yt, "เซิร์ชข่าวในวันนี้")
        se.assert_called_with("youtube", "ข่าวในวันนี้", None)
        r, k, pl, *_ = self.run_in(None, "เปิดข่าววันนี้ใน youtube")
        pl.assert_called_with("ข่าววันนี้", "youtube", None)
        r, k, *_ = self.run_in(yt, "หยุดเพลงก่อน")
        k.assert_called_with(127)
        self.assertIsNone(self.run_in(yt, "เปิดไลน์")[0])
        self.assertIsNone(self.run_in(None, "หาข่าววันนี้")[0])

    def test_chat_typing(self):
        line = "jp.naver.line.android"
        r, *_, sh = self.run_in(line, "พิมพ์ว่า กินข้าวยัง")
        sh.assert_called_with("กินข้าวยัง", None)
        r, *_, sh = self.run_in(line, "ตอบไปว่า โอเคเดี๋ยวไป")
        sh.assert_called_with("โอเคเดี๋ยวไป", None)
        self.assertIsNone(self.run_in(line, "ส่งข้อความหาแม่ว่า ถึงแล้ว")[0])
        self.assertIsNone(self.run_in(line, "พิมพ์ว่า hi", chat=False)[0])


class TestAppBrain(unittest.TestCase):
    APPS = [{"pkg": "com.huawei.maps.app", "label": "Petal Maps"},
            {"pkg": "com.google.android.apps.maps", "label": "Maps"},
            {"pkg": "com.huawei.calculator", "label": "เครื่องคิดเลข"},
            {"pkg": "com.kingsoft.moffice_pro", "label": "WPS Office"},
            {"pkg": "com.netflix.mediaclient", "label": "Netflix"}]

    def setUp(self):
        import tempfile
        import app_brain
        import app_index
        self.d = tempfile.mkdtemp()
        self.ps = [mock.patch.object(app_brain, "_PATH", os.path.join(self.d, "b.json")),
                   mock.patch.object(app_index, "load", return_value=self.APPS),
                   mock.patch.object(app_index, "build", return_value=self.APPS)]
        for p in self.ps:
            p.start()
        app_brain._state["db"] = None

    def tearDown(self):
        import app_brain
        for p in self.ps:
            p.stop()
        app_brain._state["db"] = None

    def test_scoring_and_ambiguity(self):
        import app_index
        c = app_index.candidates("เครื่องคิดเลข")
        self.assertEqual(c[0][1], "com.huawei.calculator")
        self.assertEqual(app_index.find("wps")[0], "com.kingsoft.moffice_pro")
        self.assertEqual(app_index.find("netflix")[0], "com.netflix.mediaclient")
        c = app_index.candidates("maps")
        self.assertEqual(c[0][1], "com.google.android.apps.maps")      # ตรงเป๊ะชนะ

    def test_ask_and_remember(self):
        import app_brain
        import app_index
        app_brain.sync()
        app_brain.apps()["com.huawei.maps.app"]["names"] = ["แผนที่"]
        app_brain.apps()["com.google.android.apps.maps"]["names"] = ["แผนที่", "กูเกิลแมพ"]
        ctx = mock.Mock()
        ctx.ask.return_value = "2"
        with mock.patch.dict("phone_tools.ALIASES", {}, clear=False), \
                mock.patch.dict("phone_tools.COMMON_APPS", {}, clear=False):
            import phone_tools
            phone_tools.ALIASES.pop("แผนที่", None)
            phone_tools.COMMON_APPS.pop("แผนที่", None)
            pkg, lab = app_index.resolve("แผนที่", ctx)
            self.assertTrue(ctx.ask.called)
            ctx.ask.reset_mock()
            pkg2, _ = app_index.resolve("แผนที่", ctx)               # จำแล้ว ไม่ถามซ้ำ
            self.assertEqual(pkg, pkg2)
            self.assertFalse(ctx.ask.called)

    def test_study_and_describe(self):
        import agent
        import app_brain
        new, gone = app_brain.sync()
        self.assertEqual(new, [])                                   # ครั้งแรกไม่นับเป็นแอปใหม่
        ans = json.dumps([{"pkg": "com.netflix.mediaclient", "names": ["เน็ตฟลิกซ์", "netflix"],
                           "what": "ดูหนังและซีรีส์", "how": "ค้นหาแว่นขยายบนขวา", "sure": True}], ensure_ascii=False)
        with mock.patch.object(agent, "call_llm", return_value=({"content": [{"type": "text", "text": ans}]}, "x")):
            self.assertEqual(app_brain.study(["com.netflix.mediaclient"]), 1)
        self.assertIn("ดูหนัง", app_brain.describe("com.netflix.mediaclient"))
        self.assertIn("Netflix", app_brain.hints("เปิดเน็ตฟลิกซ์ให้หน่อย"))
        self.assertIn("Netflix", app_brain.catalog_prompt())
        import app_index
        self.assertEqual(app_index.find("เน็ตฟลิกซ์")[0], "com.netflix.mediaclient")
        out = app_brain.handle_text("netflix ใช้ทำอะไร")
        self.assertIn("ดูหนัง", out)
        self.assertIsNone(app_brain.handle_text("ไมโครเวฟใช้ยังไง"))
        self.assertIn("5 แอป", app_brain.handle_text("ในเครื่องมีแอปอะไรบ้าง"))
        more = self.APPS + [{"pkg": "com.new.app", "label": "NewApp"}]
        import app_index as ai
        with mock.patch.object(ai, "build", return_value=more):
            new, _ = app_brain.sync()
        self.assertEqual(new, ["com.new.app"])

    def test_edge_gec(self):
        import edge_ws
        self.assertEqual(edge_ws.sec_ms_gec_v1(1700000000.0), edge_ws.sec_ms_gec_v1(1700000090.0))   # ปัดทีละ 5 นาที
        self.assertEqual(len(edge_ws.sec_ms_gec_v1()), 64)
        tok, ver = edge_ws.sec_ms_gec()
        self.assertTrue(ver.startswith(("1-", "2-")))

    def test_edge_drm_v2_loads_without_aiohttp(self):
        import edge_ws, sys, tempfile, os, importlib
        d = tempfile.mkdtemp()
        pkg = os.path.join(d, "edge_tts")
        os.makedirs(pkg)
        open(os.path.join(pkg, "__init__.py"), "w").write("import aiohttp\nfrom .communicate import Communicate\n")
        open(os.path.join(pkg, "constants.py"), "w").write('TRUSTED_CLIENT_TOKEN = "X"\n')
        open(os.path.join(pkg, "exceptions.py"), "w").write("class SkewAdjustmentError(Exception): pass\n")
        open(os.path.join(pkg, "drm.py"), "w").write(
            "import aiohttp\nfrom .constants import TRUSTED_CLIENT_TOKEN\nfrom .exceptions import SkewAdjustmentError\n"
            "def h(e: aiohttp.ClientResponseError): pass\n"
            "def generate_sec_ms_gec_v2(unix_timestamp=None):\n    return 'ABCDEF0123456789-' + 'F' * 64\n")
        sys.path.insert(0, d)
        old = dict(edge_ws._drm_mod)
        try:
            importlib.invalidate_caches()
            edge_ws._drm_mod.update(m=None, tried=False)
            tok, ver = edge_ws.sec_ms_gec(1700000000.0)
            self.assertEqual(ver, edge_ws.GEC_VERSION_V2)
            self.assertTrue(tok.startswith("ABCDEF0123456789-"))
            self.assertNotIn("aiohttp", sys.modules)          # ไม่ทิ้งของปลอมไว้ให้โค้ดอื่นสับสน
            self.assertNotIn("edge_tts", sys.modules)
        finally:
            sys.path.remove(d)
            edge_ws._drm_mod.clear(); edge_ws._drm_mod.update(old)
        self.assertIn("(th-TH, NiwatNeural)", edge_ws.full_voice("th-TH-NiwatNeural"))


class TestPlugins(unittest.TestCase):
    GOOD = {"slug": "sleep_mode", "name": "โหมดนอน", "desc": "ปิด wifi เปิดห้ามรบกวน",
            "triggers": ["โหมดนอน"],
            "examples": [{"say": "เปิดโหมดนอน", "expect_tools": ["wifi", "do_not_disturb"]}],
            "code": "import re\n\ndef run(text, api):\n    api.tool('wifi', on=False)\n"
                    "    api.tool('do_not_disturb', on=True)\n    api.data['n'] = api.data.get('n', 0) + 1\n"
                    "    api.save()\n    return 'ฝันดีนะ 😴'\n"}

    def setUp(self):
        import tempfile
        import plugins
        self.p = mock.patch.object(plugins, "DIR", tempfile.mkdtemp())
        self.p.start()
        plugins._loaded.clear()

    def tearDown(self):
        import plugins
        self.p.stop()
        plugins._loaded.clear()

    def test_sandbox_blocks_escape(self):
        import plugins
        bad = ["import os\ndef run(t, api): return os.listdir('/')",
               "def run(t, api): return open('/x').read()",
               "def run(t, api): return ().__class__",
               "def run(t, api): api._ctx.confirm = lambda d: True",
               "def run(t, api): return '{0._ctx}'.format(api)",
               "def run(t, api): return getattr(api, 'tool')",
               "def run(t, api): return eval('1')",
               "def nope(t, api): return 1"]
        for src in bad:
            self.assertFalse(plugins.check_code(src)[0], src)
        self.assertTrue(plugins.check_code(self.GOOD["code"])[0])

    def test_test_install_run(self):
        import agent
        import plugins
        ok, rep = plugins.test_plugin(self.GOOD)
        self.assertTrue(ok, rep)
        wide = dict(self.GOOD, triggers=[".*"])
        self.assertFalse(plugins.test_plugin(wide)[0])
        missing = dict(self.GOOD, examples=[{"say": "เปิดโหมดนอน", "expect_tools": ["bluetooth"]}])
        self.assertFalse(plugins.test_plugin(missing)[0])
        plugins.install(self.GOOD)
        calls = []
        with mock.patch.object(agent, "execute_tool",
                               side_effect=lambda b, c: calls.append(b["name"]) or {"content": "OK"}):
            self.assertEqual(plugins.handle_text("เปิดโหมดนอนหน่อย"), "ฝันดีนะ 😴")
        self.assertEqual(calls, ["wifi", "do_not_disturb"])
        self.assertIn("โหมดนอน", plugins.handle_text("ความสามารถที่เพิ่มเอง"))
        self.assertIn("ปิด", plugins.handle_text("ปิดความสามารถ โหมดนอน"))
        self.assertIsNone(plugins.handle_text("เปิดโหมดนอน"))

    def test_create_with_ai_and_autodisable(self):
        import plugins
        import self_heal
        ctx = mock.Mock()
        ctx.confirm.return_value = True
        with mock.patch.object(self_heal, "_llm", return_value=json.dumps(self.GOOD, ensure_ascii=False)):
            out = plugins.handle_text("เพิ่มความสามารถ: บอกว่าโหมดนอนแล้วปิดไวไฟเปิดห้ามรบกวน", ctx)
        self.assertIn("เปิดใช้แล้ว", out)
        boom = dict(self.GOOD, code="def run(text, api):\n    return 1 / 0\n")
        plugins.install(boom)
        for _ in range(3):
            plugins.handle_text("โหมดนอน", ctx)
        self.assertFalse(plugins.all_meta()["sleep_mode"]["enabled"])

    def test_repair_providers_without_claude(self):
        import self_heal
        with mock.patch.object(config, "ANTHROPIC_API_KEY", ""), mock.patch.object(config, "GEMINI_API_KEY", ""), \
                mock.patch.object(config, "OLLAMA_URL", "http://pc:11434"), mock.patch.object(config, "GROQ_API_KEY", "g"), \
                mock.patch.object(config, "LLM_PROVIDER", "ollama"):
            self.assertEqual(self_heal.repair_providers(), ["ollama", "groq"])
        src = "\n".join(f"x{i} = {i}" for i in range(1000))
        ex = self_heal._excerpt(src, [500])
        self.assertIn("x499 = 499", ex)
        self.assertNotIn("x5 = 5\n", ex)


class TestAutoReply(unittest.TestCase):
    def setUp(self):
        import tempfile
        import autoreply
        self.b = FakeBridge()
        android_shim.B = self.b
        self.ps = [mock.patch.object(autoreply, "_PATH", os.path.join(tempfile.mkdtemp(), "ar.json")),
                   mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "MOCK_PHONE", False)]
        for p in self.ps:
            p.start()
        autoreply._state["cfg"] = None

    def tearDown(self):
        import autoreply
        for p in self.ps:
            p.stop()
        autoreply._state["cfg"] = None

    def n(self, **kw):
        d = {"key": "k1", "packageName": "jp.naver.line.android", "title": "แม่", "content": "อยู่ไหน",
             "can_reply": True, "when": time.time() * 1000}
        d.update(kw)
        return d

    def test_rules_away_and_cooldown(self):
        import autoreply
        self.assertIn("โหมดไม่อยู่", autoreply.handle_text("ไม่อยู่นะ"))       # ไม่มีกฎ → สร้างกฎเริ่มต้นให้
        sent = autoreply.handle_notification(self.n())
        self.assertIn("ไม่สะดวก", sent)
        self.assertIn(("notifReply", "k1", sent), self.b.calls)
        self.assertIsNone(autoreply.handle_notification(self.n(content="ว่าไง")))      # ตอบคนเดิมซ้ำเร็วไป
        self.assertIsNone(autoreply.handle_notification(self.n(title="พี่", content="รหัส OTP 123456")))
        self.assertIsNone(autoreply.handle_notification(self.n(title="กลุ่มงาน", is_group=True)))
        self.assertIn("ตอบแทน 1", autoreply.handle_text("กลับมาแล้ว"))
        self.assertIsNone(autoreply.handle_notification(self.n(title="น้อง")))            # กลับมาแล้ว → ไม่ตอบ

    def test_ai_mode_window_and_filters(self):
        import agent
        import autoreply
        autoreply.handle_text("ให้ AI ตอบแทนในไลน์")
        autoreply.set_away(True)
        r = autoreply.cfg()["rules"][0]
        self.assertEqual((r["mode"], r["app"]), ("ai", "jp.naver.line.android"))
        with mock.patch.object(agent, "call_llm", return_value=({"content": [{"type": "text", "text": "เดี๋ยวแจ้งให้นะครับ"}]}, "x")):
            out = autoreply.handle_notification(self.n())
        self.assertTrue(out.startswith("🤖 "))
        self.assertIsNone(autoreply.match(self.n(packageName="com.whatsapp")))
        r.update(who=["แม่"])
        self.assertIsNone(autoreply.match(self.n(title="เพื่อน")))
        r.update(who=[], start="22:00", end="07:00")
        self.assertTrue(autoreply.in_window(r, time.struct_time((2026, 1, 1, 23, 0, 0, 0, 1, 0))))
        self.assertTrue(autoreply.in_window(r, time.struct_time((2026, 1, 1, 6, 59, 0, 0, 1, 0))))
        self.assertFalse(autoreply.in_window(r, time.struct_time((2026, 1, 1, 12, 0, 0, 0, 1, 0))))
        self.assertIn("ไลน์", "ไลน์")
        self.assertIn("✅", autoreply.handle_text("ตั้งตอบกลับอัตโนมัติในไลน์ว่า ติดประชุมอยู่"))

    def test_mojibake_fix(self):
        import voice
        bad = "เปิดเพลงให้หน่อย".encode().decode("latin-1")
        self.assertEqual(voice.fix_mojibake(bad), "เปิดเพลงให้หน่อย")
        self.assertEqual(voice.fix_mojibake("ปกติดี ok"), "ปกติดี ok")


class TestHumanAndContacts(unittest.TestCase):
    def setUp(self):
        import contacts
        self.p = mock.patch.object(contacts, "_PATH", os.path.join(tempfile.mkdtemp(), "c.json"))
        self.p.start()
        contacts._db["d"] = None

    def tearDown(self):
        import contacts
        self.p.stop()
        contacts._db["d"] = None

    def test_polite_male(self):
        import polite
        self.assertEqual(polite.fix("ได้เลยค่ะ ไปไหนคะ? รับครับ/ค่ะ"), "ได้เลยครับ ไปไหนครับ? รับครับ")
        self.assertEqual(polite.fix("คะแนนสอบดีนะคะ"), "คะแนนสอบดีนะครับ")

    def test_contacts_remember_app(self):
        import contacts
        import router
        contacts.learn("ภรรยา(คนเจก)", "com.instagram.android", "notif")
        self.assertEqual(contacts.app_for("ภรรยา(คนเจก)"), "instagram")
        contacts.learn("ภรรยา(คนเจก)", "line", "sent")
        self.assertEqual(contacts.app_for("ภรรยา (คนเจก)"), "line")          # ส่งจริงล่าสุดชนะ
        self.assertEqual(contacts.app_for("ภรรยา"), "line")                    # ชื่อสั้นก็หาเจอ
        self.assertEqual(router._dm_app("", "ภรรยา(คนเจก)"), "line")
        self.assertIn("instagram", contacts.handle_text("แม่อยู่ในไอจีนะ"))
        self.assertEqual(contacts.app_for("แม่"), "instagram")

    def test_human_typing_chunks(self):
        import screen_tools
        b = FakeBridge()
        with mock.patch.dict(os.environ, {"HUMAN_TYPING": "1"}), mock.patch.object(time, "sleep"):
            self.assertTrue(screen_tools._human_type(b, "สวัสดีครับ วันนี้กินข้าวยัง"))
        typed = [c[1] for c in b.calls if c[0] == "typeText"]
        self.assertGreater(len(typed), 3)
        self.assertEqual(typed[-1], "สวัสดีครับ วันนี้กินข้าวยัง")
        self.assertTrue(all(typed[-1].startswith(x) for x in typed))
        self.assertEqual(screen_tools._clusters("กิ่ง"), ["กิ่", "ง"])

    def test_app_task_routing_and_fab(self):
        import app_tasks
        with mock.patch.object(config, "ANDROID_APP", True), \
                mock.patch.object(app_tasks, "wps_new_doc", return_value="W") as w, \
                mock.patch.object(app_tasks, "note_new", return_value="N") as n:
            self.assertEqual(app_tasks.handle_text("สร้างเอกสารใหม่ใน wps"), "W")
            self.assertEqual(app_tasks.handle_text("สร้างไฟล์ Word ให้หน่อย"), "W")
            self.assertEqual(app_tasks.handle_text("สร้างไฟล์ Word ใน WPS ให้หน่อย"), "W")
            self.assertEqual(app_tasks.handle_text("เปิด wps แล้วสร้างเอกสาร ว่า สวัสดี"), "W")
            w.assert_called_with("สวัสดี", None, title="")
            self.assertEqual(app_tasks.handle_text("จดโน้ตว่า ซื้อนม"), "N")
            n.assert_called_with("ซื้อนม", None)
            self.assertIsNone(app_tasks.handle_text("เปิดไลน์"))
        def el(x, y, s=120, lab=""):
            return {"text": lab, "desc": "", "id": "", "x": x, "y": y, "click": True, "edit": False,
                    "box": (x - s // 2, y - s // 2, x + s // 2, y + s // 2)}
        items = [el(500, 100, 80, "หน้าหลัก"), el(1450, 2200), el(800, 1200, 300), el(1550, 2500, 40)]
        f = app_tasks._fab(items)
        self.assertEqual((f["x"], f["y"]), (1450, 2200))
        with mock.patch.object(app_tasks, "icons_for", return_value=[{"x": 1450 / 1570, "y": 2200 / 2520, "label": "สร้างไฟล์ใหม่"}]):
            self.assertEqual(app_tasks.find_learned("pkg", "สร้างไฟล์", items)["x"], 1450)


class TestMedia(unittest.TestCase):
    def test_routing(self):
        import media
        import vision
        with mock.patch.object(media, "make_image", return_value="I") as mi, \
                mock.patch.object(media, "make_slides", return_value="S") as ms, \
                mock.patch.object(media, "make_video", return_value="V"):
            self.assertEqual(media.handle_text("วาดรูป แมวใส่ชุดอวกาศ"), "I")
            mi.assert_called_with("แมวใส่ชุดอวกาศ", None)
            self.assertEqual(media.handle_text("ทำสไลด์เรื่อง ภาวะโลกร้อน หน่อย"), "S")
            ms.assert_called_with("ภาวะโลกร้อน", None)
            self.assertEqual(media.handle_text("สร้างวิดีโอ หมาวิ่งในทุ่ง"), "V")
            self.assertIsNone(media.handle_text("เปิดรูปในแกลเลอรี"))
        with mock.patch.object(vision, "look_ask", return_value="L") as la:
            self.assertEqual(vision.handle_text("ถืออะไรอยู่"), "L")
            self.assertEqual(vision.handle_text("ในมือผมคืออะไร"), "L")
            self.assertIsNone(vision.handle_text("ดูว่าพรุ่งนี้ฝนตกไหม"))

    def test_slides_file(self):
        import media
        import pptx_lite
        d = tempfile.mkdtemp()
        out = json.dumps([{"title": "ปก", "bullets": ["คำโปรย"]}, {"title": "หัวข้อ", "bullets": ["ก", "ข"]}], ensure_ascii=False)
        with mock.patch.object(media, "_llm", return_value=out), mock.patch.object(media, "_out_dir", return_value=d), \
                mock.patch.dict(os.environ, {"MEDIA_TEST": "1"}):
            r = media.make_slides("ทดสอบ")
        self.assertIn("2 หน้า", r)
        f = [x for x in os.listdir(d) if x.endswith(".pptx")][0]
        with zipfile.ZipFile(os.path.join(d, f)) as z:
            self.assertIn("ppt/slides/slide2.xml", z.namelist())
        self.assertTrue(pptx_lite.W > pptx_lite.H)

    def test_analyze_text_and_audio(self):
        import media
        import voice
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("ประชุมพรุ่งนี้ 9 โมง")
        with mock.patch.object(media, "_llm", return_value="สรุปแล้ว"):
            self.assertIn("สรุปแล้ว", media.analyze_file(p, "text/plain"))
            a = os.path.join(d, "v.m4a")
            open(a, "wb").write(b"0" * 100)
            with mock.patch.object(voice, "transcribe_segments", return_value=[{"start": 0, "end": 1, "text": "สวัสดีครับ"}]):
                r = media.analyze_file(a, "audio/mp4")
        self.assertIn("สวัสดีครับ", r)
        self.assertIn("สรุป", r)


class TestWpsAndFiles(unittest.TestCase):
    def el(self, lab, y=500, click=True, i=""):
        return {"text": lab, "desc": "", "id": i, "x": 500, "y": y, "click": click, "edit": False,
                "box": (400, y - 40, 600, y + 40)}

    def test_wps_states(self):
        import app_tasks
        self.assertEqual(app_tasks._wps_state([self.el("หน้าแรก"), self.el("ไฟล์"), self.el("เครื่องมือ")]), "home")
        self.assertEqual(app_tasks._wps_state([self.el("เอกสาร"), self.el("สเปรดชีต"), self.el("PDF")]), "types")
        self.assertEqual(app_tasks._wps_state([self.el("+"), self.el("แม่แบบแนะนำ")]), "template")
        self.assertEqual(app_tasks._wps_state([self.el("เลิกทำ"), self.el("แทรก")]), "editor")

    def test_docx_with_content(self):
        import app_tasks
        import media
        d = tempfile.mkdtemp()
        with mock.patch.object(media, "_out_dir", return_value=d), mock.patch.object(config, "ANDROID_APP", False):
            r = app_tasks.wps_new_doc("รายงาน\nบรรทัดหนึ่ง\n- ข้อ", None)
        self.assertIn("สร้างไฟล์ Word", r)
        f = [x for x in os.listdir(d) if x.endswith(".docx")][0]
        with zipfile.ZipFile(os.path.join(d, f)) as z:
            self.assertIn("บรรทัดหนึ่ง", z.read("word/document.xml").decode())

    def test_no_face_identification(self):
        import media
        r = media.analyze_file("/x.jpg", "image/jpeg", "คนในรูปนี้คือใคร หาเฟสให้หน่อย")
        self.assertIn("ไม่ได้", r)


class TestScreenContext(unittest.TestCase):
    def test_snapshot_and_describe(self):
        import phone_tools
        import screen_context
        import share_tools
        def el(lab, y, click=True, edit=False):
            return {"text": lab, "desc": "", "id": "", "x": 500, "y": y, "click": click, "edit": edit,
                    "box": (0, y - 30, 1600, y + 30)}
        items = [el("12:30", 20, False), el("ภรรยา(คนเจก)", 150, False), el("กินข้าวยัง", 900, False),
                 el("ข้อความ...", 2300, True, True), el("ส่ง", 2300)]
        with mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "MOCK_PHONE", False), \
                mock.patch.object(phone_tools, "_fg", return_value="com.instagram.android"), \
                mock.patch.object(share_tools, "_items", return_value=items):
            s = screen_context.snapshot()
            self.assertEqual(s["chat"], "ภรรยา(คนเจก)")
            d = screen_context.recent()
            self.assertIn("ห้องแชทกับ ภรรยา(คนเจก)", d)
            self.assertIn("กินข้าวยัง", d)
            self.assertNotIn("12:30", d)
            self.assertIn("ห้องแชท", screen_context.handle_text("ตอนนี้อยู่หน้าไหน"))
        self.assertIsNone(screen_context.handle_text("เปิดไลน์"))


class TestV26Guards(unittest.TestCase):
    def test_router_guards(self):
        import router
        d = {"intent": "reply", "to": "ล่าสุด", "text": "✅ ค่ะ", "_said": "อ่านข้อความ"}
        self.assertIsNone(router.execute(d, None))
        d = {"intent": "reply", "to": "ล่าสุด", "text": "ลบข้อความใน WPS", "_said": "ลบข้อความใน WPS"}
        self.assertIsNone(router.execute(d, None))
        self.assertTrue(router._from_said("ชอบอะไรเหรอ", "บอกว่าชอบอะไรเหรอ"))
        self.assertFalse(router._from_said("✅ ค่ะ", "ตอบกลับไปหน่อย"))
        self.assertFalse(router._app_said("ส่งหาภรรยาว่ากินข้าวยัง"))
        self.assertTrue(router._app_said("ส่งไลน์หาแม่"))

    def test_goto_chat_and_password(self):
        import share_tools
        import social
        with mock.patch.object(social, "goto_chat", return_value="G") as g:
            self.assertEqual(social.handle_text("ไปที่แชท ภรรยา คน เจก"), "G")
            self.assertEqual(social.handle_text("ไปที่แชร์ภรรยาคนเจก"), "G")
            self.assertIsNone(social.handle_text("ส่งข้อความหาแม่ว่าถึงแล้ว"))
        pw = {"text": "รหัสผ่าน", "desc": "", "id": "", "x": 1, "y": 900, "click": True, "edit": True,
              "box": (0, 880, 100, 920), "password": True}
        self.assertIsNone(share_tools._composer([pw]))

    def test_polite_quick(self):
        import polite
        self.assertEqual(polite.fix("รับทราบค่ะ"), "รับทราบครับ")


class TestToggles(unittest.TestCase):
    def setUp(self):
        self.b = FakeBridge()
        android_shim.B = self.b
        self.ps = [mock.patch.object(config, "ANDROID_APP", True), mock.patch.object(config, "MOCK_PHONE", False),
                   mock.patch.object(time, "sleep")]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def test_settings_switch_taps_row_switch(self):
        def el(lab, x, y, checkable=False, checked=False, i=""):
            return {"text": lab, "desc": "", "id": i, "x": x, "y": y, "click": True, "edit": False,
                    "box": (x - 50, y - 30, x + 50, y + 30), "checkable": checkable, "checked": checked}
        page = [el("Wi-Fi", 200, 300), el("", 1400, 300, True, False, "switch_widget"), el("เครือข่าย", 200, 600)]
        states = iter([False, True])
        with mock.patch.object(android_shim, "_screen_items", return_value=(page, 1600, 2500)), \
                mock.patch.object(android_shim, "sys_state", side_effect=lambda k: next(states, True)):
            r = android_shim.qs_toggle("wifi", "Wi-Fi", True)
        self.assertIn("เปิด Wi-Fi แล้ว", r)
        self.assertIn(("tap", 1400, 300), self.b.calls)
        self.assertIn(("key", 4), self.b.calls)

    def test_rotate_via_write_settings(self):
        with mock.patch.object(android_shim, "sys_state", return_value=True):
            r = android_shim.rotate_auto(True)
        self.assertIn("หมุนจออัตโนมัติ", r)
        self.assertIn(("settingsPut", "system", "accelerometer_rotation", "1"), self.b.calls)
        import device
        with mock.patch.object(android_shim, "rotate_auto", return_value="R") as ra:
            self.assertEqual(device.handle_text("ล็อกการหมุนจอ"), "R")
            ra.assert_called_with(False)
            self.assertEqual(device.handle_text("เปิดหมุนจออัตโนมัติหน่อย"), "R")
            ra.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()


class TestAutoreplyNoDouble(unittest.TestCase):
    def setUp(self):
        import autoreply
        autoreply._batch.clear()
        autoreply._outs.clear()

    def test_one_line(self):
        import autoreply
        self.assertEqual(autoreply.one_line("ได้ครับ ได้ครับ"), "ได้ครับ")
        self.assertEqual(autoreply.one_line('คำตอบ:\n"เดี๋ยวแจ้งเจ้าของให้นะครับ"\nขอบคุณครับ'), "เดี๋ยวแจ้งเจ้าของให้นะครับ")
        self.assertLessEqual(len(autoreply.one_line("ก " * 200)), 160)

    def test_echo_of_own_reply_is_ignored(self):
        import autoreply
        autoreply._remember_out("🤖 เดี๋ยวแจ้งเจ้าของให้นะครับ")
        n = {"packageName": "jp.naver.line.android", "title": "ต้น", "content": "เดี๋ยวแจ้งเจ้าของให้นะครับ"}
        self.assertTrue(autoreply._is_echo(n))
        self.assertTrue(autoreply._is_echo({"content": "x", "from_me": True, "last_text": "x"}))
        self.assertFalse(autoreply._is_echo({"packageName": "jp.naver.line.android", "title": "ต้น", "content": "อยู่ไหน"}))

    def test_burst_of_messages_gets_one_reply(self):
        import autoreply
        from unittest import mock
        base = {"packageName": "jp.naver.line.android", "title": "ต้น", "can_reply": True, "key": "k1"}
        t0 = 1000.0
        autoreply._queue(dict(base, content="อยู่ไหม"), t0)
        autoreply._queue(dict(base, content="ว่างคุยไหม"), t0 + 2)
        autoreply._queue(dict(base, content="ด่วนนิดนึง"), t0 + 4)
        with mock.patch.object(autoreply, "handle_notification", return_value="ok") as h:
            self.assertEqual(autoreply._flush(None, t0 + 6), [])          # ยังพิมพ์อยู่ → ยังไม่ตอบ
            autoreply._flush(None, t0 + 4 + autoreply.BATCH_SEC + 0.1)
        self.assertEqual(h.call_count, 1)
        self.assertEqual(h.call_args[0][0]["content"], "อยู่ไหม\nว่างคุยไหม\nด่วนนิดนึง")

    def test_contacts_catalog_and_learnable(self):
        import autoreply, contacts, tempfile, os
        old = contacts._PATH, contacts._db["d"]
        contacts._PATH = os.path.join(tempfile.mkdtemp(), "c.json")
        contacts._db["d"] = {}
        try:
            contacts.learn("ต้น", "jp.naver.line.android", "notif")
            contacts.learn("ต้น", "com.instagram.android", "sent")
            cat = contacts.catalog()
            self.assertEqual(cat[0]["name"], "ต้น")
            self.assertEqual(cat[0]["best"], "instagram")
            self.assertIn("จำได้ 1 คน", contacts.handle_text("รายชื่อที่จำได้"))
        finally:
            contacts._PATH, contacts._db["d"] = old
        self.assertFalse(autoreply._learnable({"title": "3 ข้อความใหม่"}))
        self.assertFalse(autoreply._learnable({"title": "LINE"}))
        self.assertTrue(autoreply._learnable({"title": "น้องฝน"}))


class TestSendConfirm(unittest.TestCase):
    def setUp(self):
        import contacts, send_confirm, tempfile, os
        send_confirm._P.clear()
        self.old = contacts._PATH, contacts._db["d"]
        contacts._PATH = os.path.join(tempfile.mkdtemp(), "c.json")
        contacts._db["d"] = {}

    def tearDown(self):
        import contacts, send_confirm
        contacts._PATH, contacts._db["d"] = self.old
        send_confirm._P.clear()

    class VoiceCtx:
        pass

    def test_voice_readback_then_send(self):
        import quick, send_confirm, share_tools
        from unittest import mock
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว") as sd:
            q = quick._do_send("line", "แม่", "กินข้าวยัง", self.VoiceCtx())
            self.assertIn("ใช่ไหม", q)
            sd.assert_not_called()
            self.assertIn("แก้แล้ว", send_confirm.handle_text("แก้เป็น กินข้าวหรือยัง", None))
            send_confirm.handle_text("ใช่", None)
        self.assertEqual(sd.call_args[0][0]["text"], "กินข้าวหรือยัง")

    def test_voice_cancel(self):
        import quick, send_confirm, share_tools
        from unittest import mock
        with mock.patch.object(share_tools, "send_dm") as sd:
            quick._do_send("line", "แม่", "ไปแล้ว", self.VoiceCtx())
            self.assertIn("ไม่ส่ง", send_confirm.handle_text("ยกเลิก", None))
        sd.assert_not_called()

    def test_typed_send_goes_straight(self):
        import quick, share_tools
        from unittest import mock
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว") as sd:
            quick._do_send("line", "แม่", "ไปแล้ว", None)
        sd.assert_called_once()

    def test_ambiguous_name_asks_who(self):
        import contacts, quick, send_confirm, share_tools
        from unittest import mock
        contacts.learn("ต้นข้าว", "jp.naver.line.android", "sent")
        contacts.learn("ต้นกล้า", "com.instagram.android", "sent")
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว") as sd:
            q = quick._do_send("line", "ต้น", "หวัดดี", None, explicit=False)
            self.assertIn("หมายถึงใคร", q)
            send_confirm.handle_text("ต้นกล้า", None)
        a = sd.call_args[0][0]
        self.assertEqual((a["to"], a["app"]), ("ต้นกล้า", "instagram"))

    def test_same_person_two_apps_asks_app(self):
        import contacts, quick, send_confirm, share_tools
        from unittest import mock
        contacts.learn("ฝน", "jp.naver.line.android", "notif")
        contacts.learn("ฝน", "com.facebook.orca", "notif")
        with mock.patch.object(share_tools, "send_dm", return_value="ส่งแล้ว") as sd:
            q = quick._do_send("line", "ฝน", "ถึงยัง", None, explicit=False)
            self.assertIn("ส่งทางไหน", q)
            send_confirm.handle_text("2", None)
        self.assertEqual(sd.call_args[0][0]["app"], "messenger")


class TestContactScan(unittest.TestCase):
    def test_names_from_chat_list_rows(self):
        import contact_scan
        def row(y, name, preview, t="10:32"):
            box = (0, y, 1000, y + 150)
            return [{"text": "", "click": True, "box": box, "x": 500, "y": y + 75},
                    {"text": name, "click": False, "box": (120, y + 20, 600, y + 60), "x": 300, "y": y + 40},
                    {"text": t, "click": False, "box": (850, y + 20, 980, y + 60), "x": 900, "y": y + 40},
                    {"text": preview, "click": False, "box": (120, y + 80, 900, y + 120), "x": 400, "y": y + 100}]
        items = [{"text": "แชท", "click": True, "box": (0, 0, 1000, 120), "x": 500, "y": 60}]
        items += row(200, "แม่", "กินข้าวยัง") + row(360, "กลุ่มงาน (25)", "พี่: ส่งงานยัง")
        items += row(520, "เมื่อวาน", "x") + row(680, "น้องฝน", "คุณ: โอเค")
        self.assertEqual(contact_scan.names_on_screen(items, 1000), ["แม่", "กลุ่มงาน", "น้องฝน"])

    def test_command(self):
        import contact_scan
        from unittest import mock
        with mock.patch.object(contact_scan, "scan", return_value="done") as s:
            self.assertEqual(contact_scan.handle_text("จำรายชื่อจากแชททุกแอป"), "done")
            self.assertIsNone(contact_scan.handle_text("จำไว้ว่าพรุ่งนี้ประชุม"))
        s.assert_called_once()
