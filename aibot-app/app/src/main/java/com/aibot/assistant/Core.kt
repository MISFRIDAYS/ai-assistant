package com.aibot.assistant

import android.app.AlarmManager
import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.app.Service
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import android.provider.Settings
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

class App : Application() {
    companion object {
        const val CH_RUN = "run"
        const val CH_ASK = "ask"
        const val CH_INFO = "info"
        @Volatile var top: android.app.Activity? = null

        /** เริ่ม Python (ครั้งเดียวต่อโปรเซส) */
        fun py(ctx: Context): Python {
            if (!Python.isStarted()) Python.start(AndroidPlatform(ctx.applicationContext))
            return Python.getInstance()
        }
    }

    override fun onCreate() {
        super.onCreate()
        CrashReport.install(this)       // แอปหลุด → จดสาเหตุไว้แสดงตอนเปิดครั้งถัดไป
        Bridge.app = this
        ChatLog.init(this)
        // จำว่าหน้าจอไหนของแอปเปิดอยู่ (ไว้ถอยแอปไปเบื้องหลังก่อนสั่งงานบนจอ)
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityResumed(a: android.app.Activity) { top = a }
            override fun onActivityPaused(a: android.app.Activity) { if (top === a) top = null }
            override fun onActivityCreated(a: android.app.Activity, b: android.os.Bundle?) {}
            override fun onActivityStarted(a: android.app.Activity) {}
            override fun onActivityStopped(a: android.app.Activity) {}
            override fun onActivitySaveInstanceState(a: android.app.Activity, b: android.os.Bundle) {}
            override fun onActivityDestroyed(a: android.app.Activity) {}
        })
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_RUN, "ผู้ช่วยทำงานอยู่", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(NotificationChannel(CH_ASK, "ขออนุญาต / คำถาม", NotificationManager.IMPORTANCE_HIGH))
        nm.createNotificationChannel(NotificationChannel(CH_INFO, "ข้อความจากผู้ช่วย", NotificationManager.IMPORTANCE_DEFAULT))
    }
}

/** ข้อความในหน้าแชทของแอป (เก็บล่าสุด 300 ข้อความ) + คำถาม/ขออนุญาตที่รอตอบ */
object ChatLog {
    data class Msg(val role: String, val text: String, val time: Long = System.currentTimeMillis())
    data class Prompt(val id: Int, val kind: String, val text: String)

    val items = CopyOnWriteArrayList<Msg>()
    val prompts = CopyOnWriteArrayList<Prompt>()
    private val listeners = CopyOnWriteArrayList<() -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    fun listen(l: () -> Unit) = listeners.add(l)
    fun unlisten(l: () -> Unit) = listeners.remove(l)
    private fun fire() = main.post { listeners.forEach { it() } }

    // ---------------- เก็บแชทลงไฟล์ (เปิดแอปใหม่ก็ยังเห็น + ดูย้อนหลังได้ในหน้า 📜 ประวัติแชท)
    @Volatile private var file: java.io.File? = null
    private val io = java.util.concurrent.Executors.newSingleThreadExecutor()

    fun init(c: Context) {
        if (file != null) return
        val f = java.io.File(c.filesDir, "data/chatlog.jsonl")
        file = f
        try {
            if (f.exists()) f.readLines().takeLast(120).forEach { l ->
                val o = org.json.JSONObject(l)
                items.add(Msg(o.optString("r"), o.optString("x"), o.optLong("t")))
            }
        } catch (_: Exception) {}
    }

    fun readAll(): List<Msg> = try {
        file?.takeIf { it.exists() }?.readLines()?.mapNotNull { l ->
            try { val o = org.json.JSONObject(l); Msg(o.optString("r"), o.optString("x"), o.optLong("t")) } catch (_: Exception) { null }
        } ?: emptyList()
    } catch (_: Exception) { emptyList() }

    fun clearAll() { items.clear(); io.execute { try { file?.delete() } catch (_: Exception) {} }; fire() }

    private fun persist(m: Msg) {
        val f = file ?: return
        if (m.role != "user" && m.role != "bot") return
        io.execute {
            try {
                f.parentFile?.mkdirs()
                f.appendText(org.json.JSONObject().put("r", m.role).put("x", m.text).put("t", m.time).toString() + "\n")
                if (f.length() > 3_000_000) {                       // เก็บล่าสุดไม่เกิน ~3MB
                    val keep = f.readLines().takeLast(8000)
                    f.writeText(keep.joinToString("\n") + "\n")
                }
            } catch (_: Exception) {}
        }
    }

    fun add(role: String, text: String) {
        // ข้อความสถานะซ้อนกันได้แค่อันเดียว (ไม่รกหน้าจอ)
        if (role == "status" && items.isNotEmpty() && items.last().role == "status") items.removeAt(items.size - 1)
        val m = Msg(role, text)
        items.add(m)
        while (items.size > 300) items.removeAt(0)
        persist(m)
        fire()
    }

    fun prompt(id: Int, kind: String, text: String) { prompts.add(Prompt(id, kind, text)); fire() }

    // สถานะผู้ช่วยเสียง (กำลังฟัง/คิด/ตอบ) → แสดงบนหัวหน้าแชท
    @Volatile var moodTitle = ""
    @Volatile var moodText = ""
    fun setMood(title: String, text: String, ongoing: Boolean) { moodTitle = title; moodText = text; fire() }
    fun clearPrompt(id: Int) { prompts.removeIf { it.id == id }; fire() }
}

/** ปุ่ม "อนุญาต/ยกเลิก" และช่องตอบในแจ้งเตือน */
class ActionReceiver : BroadcastReceiver() {
    companion object {
        const val CONFIRM = "com.aibot.assistant.CONFIRM"
        const val ASK = "com.aibot.assistant.ASK"
        const val KEY_TEXT = "text"
        const val PAUSE = "com.aibot.assistant.PAUSE"
        const val STOP_RECORD = "com.aibot.assistant.STOP_RECORD"
    }

    override fun onReceive(ctx: Context, i: Intent) {
        val id = i.getIntExtra("id", -1)
        when (i.action) {
            CONFIRM -> Bridge.answer(id, i.getBooleanExtra("ok", false), null)
            PAUSE -> Bridge.setEnabled(false)
            STOP_RECORD -> Thread {
                try {
                    val r = App.py(ctx).getModule("android_main").callAttr("tool", "record_stop", "").toString()
                    ChatLog.add("bot", r)
                    Bridge.postNotif(42, "ผู้ช่วย AI", r)
                } catch (e: Throwable) { Bridge.log("record_stop: $e") }
            }.start()
            ASK -> {
                val txt = RemoteInput.getResultsFromIntent(i)?.getCharSequence(KEY_TEXT)?.toString()
                Bridge.answer(id, txt != null, txt)
            }
        }
    }
}

/** บริการหลัก: รันสมองบอท (Python) ตลอด — Telegram, ผู้ช่วยเสียง, ตรวจซ่อมตัวเอง */
class BotService : Service() {
    companion object {
        @Volatile var running = false
        @Volatile var started = false
        @Volatile private var fails = 0
        const val WATCH = "watchdog"
        private const val WATCH_MS = 15 * 60_000L

        /** ตัวเฝ้า: ปลุกบริการทุก 15 นาที — ถ้าระบบ (เช่น Huawei) ปิดแอปทิ้ง จะเปิดกลับมาเอง */
        fun scheduleWatchdog(ctx: Context, delayMs: Long = WATCH_MS) {
            try {
                val i = Intent(ctx, BotService::class.java).putExtra(WATCH, true)
                val pi = PendingIntent.getForegroundService(ctx, 8, i,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
                val at = SystemClock.elapsedRealtime() + delayMs
                if (Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms())
                    am.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi)
                else am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi)
            } catch (e: Exception) { Bridge.log("watchdog schedule: $e") }
        }

        fun start(ctx: Context) {
            if (!ctx.getSharedPreferences("app", Context.MODE_PRIVATE).getBoolean("enabled", true)) return
            val i = Intent(ctx, BotService::class.java)
            try { ctx.startForegroundService(i) } catch (e: Exception) { Bridge.log("start service: $e") }
        }
    }

    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, App.CH_RUN)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("🤖 ผู้ช่วยทำงานอยู่")
            .setContentText("สั่งผ่านแอป / Telegram / เสียง ได้เลย")
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "⏸️ ปิดผู้ช่วย",
                PendingIntent.getBroadcast(this, 4, Intent(this, ActionReceiver::class.java).setAction(ActionReceiver.PAUSE),
                    PendingIntent.FLAG_IMMUTABLE)).build())
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "🎤 สั่งด้วยเสียง",
                PendingIntent.getActivity(this, 3, Intent(this, ListenActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)).build())
            .build()
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                if (Bridge.micAllowed()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
                if (Bridge.camAllowed()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                startForeground(1, n, type)
            } else if (Build.VERSION.SDK_INT >= 30) {
                var type = 0
                if (Bridge.micAllowed()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
                if (Bridge.camAllowed()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                startForeground(1, n, type)
            } else {
                startForeground(1, n)
            }
        } catch (e: Exception) {
            Bridge.log("startForeground: $e")
            try {
                if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
                else startForeground(1, n)
            } catch (e2: Exception) { Bridge.log("startForeground2: $e2") }
        }
        val prefs = getSharedPreferences("app", Context.MODE_PRIVATE)
        if (intent?.getBooleanExtra(WATCH, false) == true && !prefs.getBoolean("enabled", true)) {
            try { stopForeground(STOP_FOREGROUND_REMOVE) } catch (_: Exception) {}   // ผู้ใช้กดปิดผู้ช่วยไว้ → ไม่ปลุก
            stopSelf()
            return START_NOT_STICKY
        }
        scheduleWatchdog(this)
        Handler(Looper.getMainLooper()).postDelayed({ checkA11y() }, 20_000)
        if (wake == null) {
            wake = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "aibot:run").also { it.acquire() }
        }
        if (!started) {
            started = true
            Thread {
                try {
                    App.py(this).getModule("android_main").callAttr("start_bot")
                    running = true
                    fails = 0
                    Bridge.log("✅ สมองบอทเริ่มทำงาน")
                } catch (e: Throwable) {
                    // เริ่มไม่ติด (เช่น เพิ่งเปิดเครื่อง เน็ตยังไม่มา) → ลองใหม่เอง 1, 2, 4 … สูงสุด 15 นาที
                    fails++
                    val wait = minOf(WATCH_MS, 60_000L shl minOf(fails - 1, 4))
                    started = false
                    Bridge.log("❗ เริ่มบอทไม่สำเร็จ (ครั้งที่ $fails) ลองใหม่ใน ${wait / 1000} วิ: $e")
                    Bridge.post("status", "❗ เริ่มบอทไม่สำเร็จ — จะลองใหม่เอง: $e")
                    scheduleWatchdog(this, wait)
                }
            }.start()
        }
        return START_STICKY
    }

    /** Huawei ชอบปิดสิทธิ์ควบคุมจอเอง → ถ้ามีสิทธิ์ WRITE_SECURE_SETTINGS เปิดคืนให้ ไม่งั้นแจ้งเตือน (ไม่เกินทุก 6 ชม.) */
    private fun checkA11y() {
        try {
            if (ScreenService.inst != null) return
            val p = getSharedPreferences("app", Context.MODE_PRIVATE)
            if (!p.getBoolean("a11y_seen", false)) return            // ยังไม่เคยเปิดเอง → ไม่กวน
            val comp = ComponentName(this, ScreenService::class.java).flattenToString()
            if (checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS") == PackageManager.PERMISSION_GRANTED) {
                val cur = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: ""
                val list = cur.split(':').filter { it.isNotBlank() && it != comp } + comp
                Settings.Secure.putString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, list.joinToString(":"))
                Settings.Secure.putInt(contentResolver, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
                Bridge.log("♿ สิทธิ์ควบคุมจอถูกปิด → เปิดคืนให้อัตโนมัติ")
                return
            }
            val now = System.currentTimeMillis()
            if (now - p.getLong("a11y_warn", 0) > 6 * 3600_000L) {
                p.edit().putLong("a11y_warn", now).apply()
                Bridge.log("♿ สิทธิ์ควบคุมจอถูกปิด → แจ้งเจ้าของ")
                Bridge.postNotif(46, "♿ สิทธิ์ควบคุมจอถูกปิด",
                    "ระบบปิดสิทธิ์ Accessibility ของผู้ช่วย — เปิดแอปแล้วเปิดสิทธิ์อีกครั้ง เพื่อให้สั่งแอป แตะ พิมพ์ได้")
            }
        } catch (e: Exception) { Bridge.log("a11y check: $e") }
    }

    override fun onDestroy() {
        try { wake?.release() } catch (_: Exception) {}
        running = false
        super.onDestroy()
    }
}

/** โปรเซสแยกสำหรับรันเทสต์ตอนซ่อมตัวเอง (ไม่กวนบอทตัวจริง) */
class HealService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val stage = intent?.getStringExtra("stage") ?: return START_NOT_STICKY
        val result = intent?.getStringExtra("result") ?: return START_NOT_STICKY
        Thread {
            try {
                App.py(this).getModule("android_main").callAttr("run_tests", stage, result)
            } catch (e: Throwable) {
                try { File(result).writeText("{\"error\":\"${e.toString().replace("\"", "'").take(400)}\"}") } catch (_: Exception) {}
            }
            stopSelf()
            Process.killProcess(Process.myPid())      // ล้าง Python ของรอบเทสต์ทิ้งทั้งหมด
        }.start()
        return START_NOT_STICKY
    }
}

/** เปิดเครื่อง / อัปเดตแอป → เริ่มผู้ช่วยเอง */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, i: Intent) {
        val prefs = ctx.getSharedPreferences("app", Context.MODE_PRIVATE)
        if (prefs.getBoolean("autostart", true) && prefs.getBoolean("enabled", true)) BotService.start(ctx)
    }
}
