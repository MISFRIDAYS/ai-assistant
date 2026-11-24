package com.aibot.assistant

import android.app.Notification
import android.app.RemoteInput
import android.content.Intent
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject

/** อ่านแจ้งเตือนทุกแอป + ตอบกลับจากแจ้งเตือนโดยตรง (ไม่ต้องเปิดแอป) */
class NotifService : NotificationListenerService() {

    companion object {
        @Volatile var inst: NotifService? = null
    }

    override fun onListenerConnected() {
        inst = this
        Bridge.log("🔔 อ่านแจ้งเตือนได้แล้ว")
    }

    override fun onListenerDisconnected() {
        inst = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {}

    private fun text(b: Bundle, key: String): String = b.getCharSequence(key)?.toString() ?: ""

    /** รูปแบบเดียวกับ termux-notification-list */
    fun listJson(): String {
        val arr = JSONArray()
        val list = try { activeNotifications } catch (_: Exception) { null } ?: return "[]"
        for (s in list.sortedByDescending { it.postTime }) {
            if (s.packageName == packageName) continue
            val n = s.notification
            val ex = n.extras
            val o = JSONObject()
            o.put("id", s.id)
            o.put("tag", s.tag ?: "")
            o.put("key", s.key)
            o.put("group", n.group ?: "")
            o.put("packageName", s.packageName)
            var title = text(ex, Notification.EXTRA_TITLE)
            var content = text(ex, Notification.EXTRA_TEXT)
            val big = text(ex, Notification.EXTRA_BIG_TEXT)
            if (big.length > content.length) content = big
            val lines = ex.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            if (content.isEmpty() && lines != null && lines.isNotEmpty()) content = lines.last().toString()
            if (title.isEmpty()) title = text(ex, Notification.EXTRA_CONVERSATION_TITLE)
            o.put("title", title)
            o.put("content", content)
            o.put("when", s.postTime)
            o.put("ongoing", s.isOngoing)
            o.put("can_reply", replyAction(n) != null)
            // แชทกลุ่ม + ชื่อคนส่งข้อความล่าสุด (สำหรับตอบกลับอัตโนมัติ)
            o.put("is_group", ex.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false))
            try {
                @Suppress("DEPRECATION")
                val arr = ex.getParcelableArray(Notification.EXTRA_MESSAGES)
                if (arr != null) {
                    val last = Notification.MessagingStyle.Message.getMessagesFromBundleArray(arr).lastOrNull()
                    val who = last?.senderPerson?.name?.toString() ?: ""
                    if (who.isNotEmpty()) o.put("sender", who)
                    if (content.isEmpty()) o.put("content", last?.text?.toString() ?: "")
                    // ข้อความล่าสุดไม่มีผู้ส่ง = เจ้าของเครื่องส่งเอง (เช่นบอทเพิ่งตอบไป แอปอัปเดตแจ้งเตือน)
                    // → ฝั่ง Python จะไม่ถือเป็นข้อความเข้าใหม่ (กันบอทตอบข้อความตัวเองจนเบิ้ล)
                    if (last != null) {
                        o.put("from_me", last.senderPerson == null)
                        o.put("last_text", last.text?.toString() ?: "")
                    }
                }
            } catch (_: Exception) {}
            arr.put(o)
        }
        return arr.toString()
    }

    private fun replyAction(n: Notification): Notification.Action? {
        val acts = n.actions ?: return null
        return acts.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }
    }

    private fun find(key: String): StatusBarNotification? =
        try { activeNotifications.firstOrNull { it.key == key || it.id.toString() == key } } catch (_: Exception) { null }

    /** ตอบกลับผ่านปุ่ม "ตอบกลับ" ในแจ้งเตือน (LINE, Messenger, IG, WhatsApp, SMS ฯลฯ) */
    fun reply(key: String, msg: String): Boolean {
        val s = find(key) ?: return false
        val act = replyAction(s.notification) ?: return false
        val ri = act.remoteInputs ?: return false
        val intent = Intent()
        val res = Bundle()
        for (r in ri) res.putCharSequence(r.resultKey, msg)
        RemoteInput.addResultsToIntent(ri, intent, res)
        return try {
            act.actionIntent.send(this, 0, intent)
            true
        } catch (e: Exception) {
            Bridge.log("reply error: $e")
            false
        }
    }

    fun open(key: String): Boolean {
        val s = find(key) ?: return false
        return try {
            s.notification.contentIntent?.send()
            true
        } catch (_: Exception) {
            false
        }
    }

    fun dismiss(key: String): Boolean {
        val s = find(key) ?: return false
        cancelNotification(s.key)
        return true
    }
}
