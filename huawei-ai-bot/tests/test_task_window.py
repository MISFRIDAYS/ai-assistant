"""ประวัติที่ส่งให้ AI ระหว่างงานสั่งเครื่อง: งานก่อนหน้าย่อ · ผลเครื่องมือเก่าย่อ · โครงสร้างยังถูกต้อง"""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.update({"MOCK_PHONE": "1", "ANTHROPIC_API_KEY": "test", "TELEGRAM_BOT_TOKEN": "test",
                   "ALLOWED_USER_IDS": "111"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402

SCREEN = "'ปุ่มหนึ่ง'@100,200 'ข้อความยาว ๆ บนจอ'@300,400 " * 60


def _task(h, k, text, steps=3, answer=True):
    h.append({"role": "user", "content": [{"type": "text", "text": f"[เวลา: x] {text}"}]})
    for j in range(steps):
        h.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"{k}{j}", "name": "read_screen",
                                                    "input": {}}]})
        h.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"{k}{j}", "content": SCREEN}]})
    if answer:
        h.append({"role": "assistant", "content": [{"type": "text", "text": "เรียบร้อยครับ"}]})


def _check_pairs(msgs):
    """ทุก tool_result ต้องมี tool_use คู่กันในข้อความก่อนหน้า"""
    ids = set()
    for m in msgs:
        if isinstance(m["content"], str):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_use":
                ids.add(b["id"])
            if b.get("type") == "tool_result":
                assert b["tool_use_id"] in ids, b["tool_use_id"]


class TestTaskWindow(unittest.TestCase):
    def _hist(self, answer_prev=True):
        h = []
        _task(h, "a", "เข้าไลน์แล้วส่งข้อความหาเกตุว่ากินข้าวยัง")
        _task(h, "b", "เปิดยูทูปแล้วเล่นเพลง", answer=answer_prev)
        start = len(h)
        if not answer_prev:
            agent._append_user(h, [{"type": "text", "text": "[เวลา: y] เข้าไอจีแล้วดูโพสต์"}])
            start = len(h) - 1
        else:
            h.append({"role": "user", "content": [{"type": "text", "text": "[เวลา: y] เข้าไอจีแล้วดูโพสต์"}]})
        for j in range(4):
            h.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"n{j}", "name": "read_screen",
                                                        "input": {}}]})
            h.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"n{j}", "content": SCREEN}]})
        return h, start

    def test_smaller_and_valid(self):
        h, start = self._hist()
        w = agent._task_window(h, start)
        self.assertLess(len(json.dumps(w, ensure_ascii=False)), len(json.dumps(h[start:], ensure_ascii=False)))
        self.assertEqual(w[0]["role"], "user")
        self.assertIn("เข้าไลน์แล้วส่งข้อความหาเกตุ", agent._text_of(w[0]["content"]))   # งานก่อนหน้ายังอยู่ (แค่ข้อความ)
        self.assertEqual([m["role"] for m in w[:4]], ["user", "assistant", "user", "assistant"])
        self.assertFalse(any(b.get("type") in ("tool_use", "tool_result") for m in w[:4] for b in m["content"]))
        _check_pairs(w)
        results = [b["content"] for m in w if isinstance(m["content"], list) for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertEqual(sum(1 for r in results if r == SCREEN), 2)          # 2 ผลล่าสุดเต็ม
        self.assertTrue(all(len(r) <= 310 for r in results[:-2]))

    def test_merged_with_orphan_results(self):
        h, start = self._hist(answer_prev=False)                        # งานก่อนจบด้วยผลเครื่องมือ → ถูกรวมข้อความ
        w = agent._task_window(h, start)
        _check_pairs(w)
        self.assertTrue(any("เข้าไอจีแล้วดูโพสต์" in agent._text_of(m["content"]) for m in w))
        roles = [m["role"] for m in w]
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])), roles)      # สลับ user/assistant ถูกต้อง

    def test_full_mode(self):
        h, start = self._hist()
        with mock.patch.dict(os.environ, {"TASK_CONTEXT": "full"}):
            self.assertIs(agent._task_window(h, start), h)

    def test_old_screenshots_dropped(self):
        h = [{"role": "user", "content": [{"type": "text", "text": "ถ่ายจอแล้วบอกว่ามีอะไร"}]}]
        for j in range(3):
            h.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"s{j}", "name": "screenshot",
                                                        "input": {}}]})
            h.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"s{j}",
                                                   "content": [{"type": "image", "source": {"data": "x" * 5000}}]}]})
        prev = [{"role": "user", "content": "ก่อนหน้า"}, {"role": "assistant", "content": "ครับ"}]
        w = agent._task_window(prev + h, len(prev))
        imgs = [b for m in w if isinstance(m["content"], list) for b in m["content"]
                if b.get("type") == "tool_result" and isinstance(b.get("content"), list)]
        self.assertEqual(len(imgs), 2)                                   # รูปเก่าถูกตัด เหลือ 2 รูปล่าสุด


if __name__ == "__main__":
    unittest.main()
