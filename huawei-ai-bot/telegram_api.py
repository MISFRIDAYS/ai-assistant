"""ตัวเชื่อม Telegram Bot API แบบ long polling (ไม่ต้องมีเซิร์ฟเวอร์/โดเมน)"""
import html
import os
import re
import threading

import requests

_local = threading.local()


def _session():
    """ใช้การเชื่อมต่อเดิมซ้ำ (แยกตาม thread) ไม่ต้องต่อ HTTPS ใหม่ทุกครั้ง = เร็วขึ้น"""
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
    return s


class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"

    def _call(self, method, http_timeout=40, files=None, **params):
        r = _session().post(f"{self.base}/{method}", data=params if files else None,
                          json=None if files else params, files=files, timeout=http_timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]

    def get_me(self):
        return self._call("getMe")

    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=timeout + 10, **params)

    def send_message(self, chat_id, text, reply_markup=None):
        last = None
        for chunk in _split(text):
            params = {"chat_id": chat_id, "text": md_to_html(chunk), "parse_mode": "HTML",
                      "disable_web_page_preview": True}
            if reply_markup:
                params["reply_markup"] = reply_markup
            try:
                last = self._call("sendMessage", **params)
            except RuntimeError:
                params.pop("parse_mode")
                params["text"] = chunk
                last = self._call("sendMessage", **params)
        return last

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        try:
            extra = {"reply_markup": reply_markup} if reply_markup else {}
            return self._call("editMessageText", chat_id=chat_id, message_id=message_id, text=text[:4000],
                              **extra)
        except RuntimeError:
            return None

    def delete_message(self, chat_id, message_id):
        try:
            self._call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except RuntimeError:
            pass

    def send_chat_action(self, chat_id, action="typing"):
        try:
            self._call("sendChatAction", chat_id=chat_id, action=action)
        except Exception:  # noqa: BLE001
            pass

    def send_photo(self, chat_id, path, caption=""):
        with open(path, "rb") as f:
            return self._call("sendPhoto", http_timeout=120, files={"photo": f},
                              chat_id=chat_id, caption=caption)

    def set_commands(self, commands):
        """ตั้งเมนูคำสั่ง (กด / ในแชทจะเห็นรายการ)"""
        try:
            self._call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
        except Exception:  # noqa: BLE001
            pass

    def send_file(self, chat_id, path, kind="document", caption=""):
        method, field = {"video": ("sendVideo", "video"), "photo": ("sendPhoto", "photo")}.get(
            kind, ("sendDocument", "document"))
        with open(path, "rb") as f:
            return self._call(method, http_timeout=600, files={field: (os.path.basename(path), f)},
                              chat_id=chat_id, caption=caption)

    def send_voice(self, chat_id, path):
        with open(path, "rb") as f:
            name = os.path.basename(path)
            return self._call("sendVoice", http_timeout=120, files={"voice": (name, f, "audio/mpeg")},
                              chat_id=chat_id)

    def answer_callback(self, callback_id, text=""):
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except RuntimeError:
            pass

    def download_file(self, file_id):
        info = self._call("getFile", file_id=file_id)
        r = requests.get(f"{self.file_base}/{info['file_path']}", timeout=60)
        r.raise_for_status()
        return r.content, info["file_path"]


def _split(text, n=4000):
    text = text or "(ว่าง)"
    parts = []
    while len(text) > n:
        cut = text.rfind("\n", 0, n)
        cut = cut if cut > n // 2 else n
        parts.append(text[:cut])
        text = text[cut:]
    parts.append(text)
    return parts


def md_to_html(text):
    """แปลง markdown พื้นฐานจาก Claude ให้เป็น HTML ที่ Telegram รองรับ"""
    t = html.escape(text, quote=False)
    t = re.sub(r"```(?:\w+)?\n?(.*?)```", lambda m: f"<pre>{m.group(1)}</pre>", t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", t, flags=re.M)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
    return t
