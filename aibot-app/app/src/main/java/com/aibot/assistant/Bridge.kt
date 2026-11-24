package com.aibot.assistant

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.annotation.SuppressLint
import android.app.ActivityManager
import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.location.LocationManager
import android.media.AudioManager
import android.media.MediaScannerConnection
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.CallLog
import android.provider.ContactsContract
import android.provider.Settings
import android.provider.Telephony
import android.telecom.TelecomManager
import android.telephony.SmsManager
import android.util.Log
import android.view.KeyEvent
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** สะพานระหว่างโค้ดบอท (Python) กับระบบ Android — Python เรียกผ่าน jclass("com.aibot.assistant.Bridge") */
object Bridge {
    lateinit var app: Context
    private val main = Handler(Looper.getMainLooper())

    // ============================================================ ทั่วไป / log / UI

    @JvmStatic fun filesDir(): String = app.filesDir.absolutePath
    @Suppress("DEPRECATION")
    @JvmStatic fun versionCode(): Long {
        val pi = app.packageManager.getPackageInfo(app.packageName, 0)
        return if (Build.VERSION.SDK_INT >= 28) pi.longVersionCode else pi.versionCode.toLong()
    }
    @JvmStatic fun sdk(): Int = Build.VERSION.SDK_INT

    @JvmStatic fun log(msg: String) {
        Log.i("AiBot", msg)
        try {
            val f = File(app.filesDir, "data/app.log")
            f.parentFile?.mkdirs()
            if (f.length() > 3_000_000) f.writeText(f.readText().takeLast(500_000))
            f.appendText(SimpleDateFormat("HH:mm:ss", Locale.US).format(Date()) + " " + msg + "\n")
        } catch (_: Exception) {
        }
    }

    /** ข้อความเข้าหน้าแชทในแอป (role = user/bot/status/notify) */
    @JvmStatic fun post(role: String, text: String) = ChatLog.add(role, text)

    @JvmStatic fun appVisible(): Boolean = MainActivity.visible

    // ============================================================ เปิด/ปิดผู้ช่วยทั้งระบบ (ปุ่ม ⏻)

    private fun prefs() = app.getSharedPreferences("app", Context.MODE_PRIVATE)
    @JvmStatic fun isEnabled(): Boolean = prefs().getBoolean("enabled", true)

    @JvmStatic fun setEnabled(on: Boolean) {
        prefs().edit().putBoolean("enabled", on).apply()
        Thread {
            try { App.py(app).getModule("android_main").callAttr("set_enabled", on) } catch (e: Throwable) { log("set_enabled: $e") }
        }.start()
        if (on) {
            BotService.start(app)
        } else {
            try { Mic.stop() } catch (_: Exception) {}
            main.post { AssistantPanel.hideNow() }
            try { app.stopService(Intent(app, BotService::class.java)) } catch (_: Exception) {}
        }
        ChatLog.add("status", if (on) "▶️ เปิดผู้ช่วยแล้ว" else "⏸️ ปิดผู้ช่วยแล้ว — ไม่ฟังไมค์ ไม่ทำงานเบื้องหลัง")
    }

    @JvmStatic fun toast(text: String) = main.post { Toast.makeText(app, text, Toast.LENGTH_LONG).show() }

    @JvmStatic fun copyAssets(src: String, dest: String): Int {
        var n = 0
        fun walk(a: String, d: File) {
            val kids = app.assets.list(a) ?: arrayOf()
            if (kids.isEmpty()) {
                d.parentFile?.let { it.mkdirs(); it.setWritable(true, true) }
                if (d.exists()) { d.setWritable(true, true); d.delete() }   // ไฟล์เก่าแบบอ่านอย่างเดียว
                app.assets.open(a).use { i -> FileOutputStream(d).use { o -> i.copyTo(o) } }
                n++
            } else {
                d.mkdirs()
                for (k in kids) walk("$a/$k", File(d, k))
            }
        }
        walk(src, File(dest))
        return n
    }

    // ============================================================ ยืนยัน / ถาม (แจ้งเตือน + หน้าแอป)

    class Pending(val latch: CountDownLatch) {
        @Volatile var ok = false
        @Volatile var answer: String? = null
    }

    val pending = ConcurrentHashMap<Int, Pending>()

    @JvmStatic fun answer(id: Int, ok: Boolean, text: String?) {
        val p = pending[id] ?: return
        p.ok = ok
        p.answer = text
        p.latch.countDown()
        (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancel(id)
        ChatLog.clearPrompt(id)
        Overlay.answered(id)
    }

    /** ป๊อปอัปลอยของผู้ช่วยเสียง (เรียกจาก ui.py) */
    @JvmStatic fun popupShow(title: String, text: String, ongoing: Boolean) { Overlay.show(title, text, ongoing) }
    @JvmStatic fun popupHide() { Overlay.hide() }

    /** แผงผู้ช่วยด้านล่างจอแบบ Google Assistant: listen / heard / think / speak / done / idle / error */
    @JvmStatic fun assistant(state: String, text: String) { AssistantPanel.update(state, text) }

    private fun actionPI(id: Int, act: String, ok: Boolean): PendingIntent {
        val i = Intent(app, ActionReceiver::class.java).setAction(act).putExtra("id", id).putExtra("ok", ok)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (act == ActionReceiver.ASK) PendingIntent.FLAG_MUTABLE else PendingIntent.FLAG_IMMUTABLE)
        return PendingIntent.getBroadcast(app, id * 2 + (if (ok) 1 else 0), i, flags)
    }

    private fun openAppPI(): PendingIntent = PendingIntent.getActivity(app, 0,
        Intent(app, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)

    /** ขออนุญาต: ปุ่มในแจ้งเตือน + กล่องในแอป รอคำตอบ (ไม่ตอบ = ไม่อนุญาต) */
    @JvmStatic fun confirm(text: String, timeoutSec: Int): Boolean {
        val id = (System.currentTimeMillis() % 100000).toInt() + 1000
        val p = Pending(CountDownLatch(1))
        pending[id] = p
        val n = Notification.Builder(app, App.CH_ASK)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("⚠️ ขออนุญาต")
            .setContentText(text.take(120))
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(openAppPI())
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "✅ อนุญาต", actionPI(id, ActionReceiver.CONFIRM, true)).build())
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "❌ ยกเลิก", actionPI(id, ActionReceiver.CONFIRM, false)).build())
            .setAutoCancel(true)
            .build()
        notifySafe(id, n)
        ChatLog.prompt(id, "confirm", text)
        Overlay.confirm(id, text)
        p.latch.await(timeoutSec.toLong(), TimeUnit.SECONDS)
        pending.remove(id)
        ChatLog.clearPrompt(id)
        Overlay.answered(id)
        cancelNotif(id)
        return p.ok
    }

    /** ถามคำถาม ให้พิมพ์ตอบ (ช่องตอบในแจ้งเตือน หรือในแอป) คืน null ถ้าไม่ตอบ */
    @JvmStatic fun ask(question: String, timeoutSec: Int): String? {
        val id = (System.currentTimeMillis() % 100000).toInt() + 200000
        val p = Pending(CountDownLatch(1))
        pending[id] = p
        val ri = RemoteInput.Builder(ActionReceiver.KEY_TEXT).setLabel("พิมพ์คำตอบ").build()
        val act = Notification.Action.Builder(null as android.graphics.drawable.Icon?, "✍️ ตอบ", actionPI(id, ActionReceiver.ASK, true))
            .addRemoteInput(ri).build()
        val n = Notification.Builder(app, App.CH_ASK)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("❓ ผู้ช่วยถาม")
            .setContentText(question.take(120))
            .setStyle(Notification.BigTextStyle().bigText(question))
            .setContentIntent(openAppPI())
            .addAction(act)
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "ยกเลิก", actionPI(id, ActionReceiver.CONFIRM, false)).build())
            .build()
        notifySafe(id, n)
        ChatLog.prompt(id, "ask", question)
        Overlay.ask(id, question)
        p.latch.await(timeoutSec.toLong(), TimeUnit.SECONDS)
        pending.remove(id)
        ChatLog.clearPrompt(id)
        Overlay.answered(id)
        cancelNotif(id)
        return if (p.ok) p.answer else null
    }

    private fun notifySafe(id: Int, n: Notification) {
        try {
            (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(id, n)
        } catch (e: Exception) {
            log("notify error: $e")
        }
    }

    @JvmStatic fun cancelNotif(id: Int) =
        (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancel(id)

    /** แจ้งเตือนค้างตอนกำลังจำขั้นตอน + ปุ่ม "จบขั้นตอน" (ผู้ใช้อยู่แอปอื่น) */
    @JvmStatic fun recordNotify(on: Boolean, name: String) {
        if (!on) { cancelNotif(43); return }
        val stop = PendingIntent.getBroadcast(app, 43, Intent(app, ActionReceiver::class.java).setAction(ActionReceiver.STOP_RECORD),
            PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(app, App.CH_ASK)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("🎬 กำลังจำขั้นตอน \"$name\"")
            .setContentText("ทำบนจอให้ดูได้เลย เสร็จแล้วกด ⏹ จบขั้นตอน")
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null as android.graphics.drawable.Icon?, "⏹ จบขั้นตอน", stop).build())
            .build()
        notifySafe(43, n)
    }

    @JvmStatic fun postNotif(id: Int, title: String, text: String) {
        val n = Notification.Builder(app, App.CH_INFO)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(openAppPI()).setAutoCancel(true).build()
        notifySafe(id, n)
    }

    // ============================================================ หน้าจอ (Accessibility)

    @JvmStatic fun screenOn(): Boolean = try {
        (app.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager).isInteractive
    } catch (_: Exception) { true }

    @JvmStatic fun a11yOn(): Boolean = ScreenService.inst != null

    /** สั่งงานบนจอขณะเปิดหน้าแชทของแอปอยู่ → ถอยแอปไปเบื้องหลังก่อน (ไม่งั้นจะพิมพ์/แตะโดนแอปตัวเอง) */
    /** บอทกำลังกดหน้าจอถึงเวลานี้ (ms) — ระหว่างนี้แผงผู้ช่วยไม่โผล่มาบังปุ่ม/ช่องพิมพ์ของแอปอื่น */
    @Volatile @JvmStatic var actingUntil = 0L

    @JvmStatic fun away() {
        actingUntil = System.currentTimeMillis() + 4000
        if (AssistantPanel.showing()) {                 // แผงผู้ช่วยลอยอยู่ล่างจอ → บังช่องพิมพ์แชท (แตะแล้วโดนแผงแทน)
            val h = CountDownLatch(1)
            main.post { try { AssistantPanel.hideForAction() } finally { h.countDown() } }
            h.await(1, TimeUnit.SECONDS)
            Thread.sleep(150)
        }
        val a = App.top ?: return
        if (a is ListenActivity) return
        val l = CountDownLatch(1)
        main.post {
            try { a.moveTaskToBack(true) } catch (_: Exception) {}
            l.countDown()
        }
        l.await(2, TimeUnit.SECONDS)
        Thread.sleep(800)
    }

    @JvmStatic fun dump(): String { away(); return ScreenService.inst?.dumpXml() ?: "" }
    @JvmStatic fun tap(x: Int, y: Int): Boolean { away(); return ScreenService.inst?.tap(x.toFloat(), y.toFloat()) ?: false }
    @JvmStatic fun longTap(x: Int, y: Int, ms: Int): Boolean {
        away(); return ScreenService.inst?.tap(x.toFloat(), y.toFloat(), ms.toLong()) ?: false
    }
    @JvmStatic fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, ms: Int): Boolean {
        away(); return ScreenService.inst?.swipe(x1.toFloat(), y1.toFloat(), x2.toFloat(), y2.toFloat(), ms.toLong()) ?: false
    }
    @Volatile private var viaImeFlag = false
    @JvmStatic fun lastViaIme(): Boolean = viaImeFlag

    @JvmStatic fun typeText(text: String, append: Boolean): Boolean {
        away()
        viaImeFlag = false
        val s = ScreenService.inst
        if (s?.focusedIsPassword() == true) return false              // ห้ามพิมพ์ลงช่องรหัสผ่าน
        val ok = s?.setText(text, append) ?: false
        // ไม่สลับไปใช้คีย์บอร์ดผู้ช่วยแล้ว (เด้งกล่องเลือกคีย์บอร์ด/เปลี่ยนคีย์บอร์ดของผู้ใช้) — ใส่ไม่ได้ = บอกตามจริง
        return ok && s?.textLanded(text) != false
    }

    /** สถานะคีย์บอร์ดผู้ช่วย (JSON): เปิดใช้ในระบบแล้วไหม / ใช้อยู่ไหม / สลับเองได้ไหม */
    @JvmStatic fun imeStatus(): String = org.json.JSONObject().apply {
        put("enabled", BotIme.enabled(app)); put("current", BotIme.isCurrent(app)); put("can_switch", BotIme.canSwitch(app))
        put("bound", BotIme.bound)
    }.toString()

    @JvmStatic fun imeType(text: String, enter: Boolean): Boolean = try { BotIme.type(app, text, enter) } catch (_: Exception) { false }

    @JvmStatic fun openImeSettings(): Boolean = try {
        app.startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true
    } catch (_: Exception) { false }
    @JvmStatic fun deleteChars(n: Int): Boolean { away(); return ScreenService.inst?.deleteChars(n) ?: false }
    @JvmStatic fun paste(): Boolean { away(); return ScreenService.inst?.paste() ?: false }
    @JvmStatic fun screenshot(path: String): Boolean { away(); return ScreenService.inst?.screenshot(path) ?: false }
    @JvmStatic fun rotation(): Int = ScreenService.inst?.rotation() ?: 0
    @JvmStatic fun screenSize(): String {
        val s = ScreenService.inst?.realSize()
        if (s != null) return "${s.first}x${s.second}"
        val dm = app.resources.displayMetrics
        return "${dm.widthPixels}x${dm.heightPixels}"
    }

    @JvmStatic fun currentPackage(): String {
        val s = ScreenService.inst ?: return ""
        val root = try { s.rootInActiveWindow } catch (_: Exception) { null }
        val p = root?.packageName?.toString()
        if (!p.isNullOrEmpty() && p != app.packageName && p != "com.android.systemui") return p
        return ScreenService.lastPkg
    }

    @JvmStatic fun currentActivity(): String = ScreenService.lastActivity

    private fun global(a: Int): Boolean = ScreenService.inst?.global(a) ?: false

    /** แปลงปุ่ม keyevent ของ Android เป็นการกระทำที่แอปทำได้ */
    @JvmStatic fun key(code: Int): Boolean {
        val am = app.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return when (code) {
            3 -> global(AccessibilityService.GLOBAL_ACTION_HOME)
            4, 111 -> { away(); global(AccessibilityService.GLOBAL_ACTION_BACK) }
            187 -> global(AccessibilityService.GLOBAL_ACTION_RECENTS)
            83 -> global(AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS)
            24 -> { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI); true }
            25 -> { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI); true }
            164 -> { am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_TOGGLE_MUTE, AudioManager.FLAG_SHOW_UI); true }
            26, 223 -> if (Build.VERSION.SDK_INT >= 28) global(AccessibilityService.GLOBAL_ACTION_LOCK_SCREEN) else false
            66, 160 -> { away(); ScreenService.inst?.imeEnter() ?: false }
            67 -> deleteChars(1)
            279 -> paste()
            5 -> answerCall()
            6 -> endCall()
            79, 85, 86, 87, 88, 126, 127 -> {
                am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
                am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code)); true
            }
            220, 221 -> {
                val cur = Settings.System.getInt(app.contentResolver, Settings.System.SCREEN_BRIGHTNESS, 128)
                brightness((cur + if (code == 221) 40 else -40).coerceIn(1, 255))
            }
            122, 123, 59, 60, 113, 114 -> true             // ย้ายเคอร์เซอร์/ปุ่ม modifier — ไม่จำเป็นเมื่อพิมพ์ด้วย setText
            else -> false
        }
    }

    @JvmStatic fun quickSettings(): Boolean = global(AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS)
    @JvmStatic fun collapseShade(): Boolean =
        if (Build.VERSION.SDK_INT >= 31) global(AccessibilityService.GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
        else global(AccessibilityService.GLOBAL_ACTION_BACK)

    // บันทึกขั้นตอนที่ผู้ใช้ทำบนจอ (สอนด้วยการทำให้ดู)
    @JvmStatic fun recordStart() { ScreenService.events.clear(); ScreenService.recording = true }
    @JvmStatic fun recordStop() { ScreenService.recording = false }
    @JvmStatic fun pollEvents(): String {
        val a = JSONArray()
        while (true) { val e = ScreenService.events.poll() ?: break; a.put(JSONObject(e)) }
        return a.toString()
    }

    // ============================================================ แจ้งเตือน

    @JvmStatic fun notifOn(): Boolean = NotifService.inst != null
    @JvmStatic fun notifications(): String = NotifService.inst?.listJson() ?: "[]"
    @JvmStatic fun notifReply(key: String, text: String): Boolean = NotifService.inst?.reply(key, text) ?: false
    @JvmStatic fun notifOpen(key: String): Boolean = NotifService.inst?.open(key) ?: false
    @JvmStatic fun notifDismiss(key: String): Boolean = NotifService.inst?.dismiss(key) ?: false

    // ============================================================ แอป / intent

    @JvmStatic fun launch(pkg: String): Boolean {
        val i = app.packageManager.getLaunchIntentForPackage(pkg) ?: return false
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        return try { app.startActivity(i); true } catch (e: Exception) { log("launch $pkg: $e"); false }
    }

    /** เปิดแอปจากหน้าแรก (ล้างหน้าที่ค้างอยู่) — ใช้ตอนจะทำงานในแอปต่อ */
    @JvmStatic fun launchFresh(pkg: String): Boolean {
        val i = app.packageManager.getLaunchIntentForPackage(pkg) ?: return false
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        return try { app.startActivity(i); true } catch (e: Exception) { log("launchFresh $pkg: $e"); launch(pkg) }
    }

    /** เปิดไฟล์ด้วยแอปที่เหมาะ (รูป → แกลเลอรี, pptx/docx → WPS) */
    @JvmStatic fun openFile(path: String, mime: String): Boolean {
        val u = mediaUri(path)
        if (u.isEmpty()) return false
        return try {
            app.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(u), mime)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)); true
        } catch (e: Exception) { log("openFile: $e"); false }
    }

    /** แยกเสียงจากวิดีโอ (ไม่แปลงใหม่ เร็ว) → .m4a คืนความยาว ms หรือ -1 */
    @JvmStatic fun extractAudio(video: String, out: String): Long {
        val ex = android.media.MediaExtractor()
        var mux: android.media.MediaMuxer? = null
        return try {
            ex.setDataSource(video)
            var track = -1
            var fmt: android.media.MediaFormat? = null
            for (t in 0 until ex.trackCount) {
                val f = ex.getTrackFormat(t)
                if ((f.getString(android.media.MediaFormat.KEY_MIME) ?: "").startsWith("audio/")) { track = t; fmt = f; break }
            }
            val af = fmt
            if (track < 0 || af == null) return -1L
            ex.selectTrack(track)
            val m = android.media.MediaMuxer(out, android.media.MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            mux = m
            val dst = m.addTrack(af)
            m.start()
            val buf = java.nio.ByteBuffer.allocate(1 shl 20)
            val info = android.media.MediaCodec.BufferInfo()
            var last = 0L
            while (true) {
                info.size = ex.readSampleData(buf, 0)
                if (info.size < 0) break
                info.offset = 0; info.presentationTimeUs = ex.sampleTime; info.flags = ex.sampleFlags
                m.writeSampleData(dst, buf, info)
                last = ex.sampleTime
                ex.advance()
            }
            m.stop()
            last / 1000
        } catch (e: Exception) { log("extractAudio: $e"); -1L } finally {
            try { mux?.release() } catch (_: Exception) {}
            ex.release()
        }
    }

    /** ภาพนิ่งจากวิดีโอ n ภาพกระจายตลอดคลิป → JSON {"duration": ms, "frames": (path...)} */
    @JvmStatic fun videoFrames(video: String, outDir: String, n: Int): String {
        val r = android.media.MediaMetadataRetriever()
        val o = JSONObject(); val arr = org.json.JSONArray()
        try {
            r.setDataSource(video)
            val dur = r.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            o.put("duration", dur)
            java.io.File(outDir).mkdirs()
            for (i in 0 until n) {
                val t = (dur * (i + 0.5) / n).toLong() * 1000
                val bmp = r.getFrameAtTime(t, android.media.MediaMetadataRetriever.OPTION_CLOSEST_SYNC) ?: continue
                val sc = 768f / maxOf(bmp.width, bmp.height)
                val small = if (sc < 1f) android.graphics.Bitmap.createScaledBitmap(bmp, (bmp.width * sc).toInt(), (bmp.height * sc).toInt(), true) else bmp
                val f = java.io.File(outDir, "frame_$i.jpg")
                java.io.FileOutputStream(f).use { small.compress(android.graphics.Bitmap.CompressFormat.JPEG, 80, it) }
                arr.put(f.absolutePath)
            }
        } catch (e: Exception) { log("videoFrames: $e") } finally { try { r.release() } catch (_: Exception) {} }
        return o.put("frames", arr).toString()
    }

    /** หน้า PDF → ภาพ (ให้ AI อ่าน) → JSON (path...) */
    @JvmStatic fun pdfPages(pdf: String, outDir: String, max: Int): String {
        val arr = org.json.JSONArray()
        try {
            val fd = android.os.ParcelFileDescriptor.open(java.io.File(pdf), android.os.ParcelFileDescriptor.MODE_READ_ONLY)
            val pr = android.graphics.pdf.PdfRenderer(fd)
            try {
                java.io.File(outDir).mkdirs()
                for (i in 0 until minOf(max, pr.pageCount)) {
                    val pg = pr.openPage(i)
                    try {
                        val w = 1100
                        val h = (w.toFloat() * pg.height / pg.width).toInt()
                        val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
                        bmp.eraseColor(android.graphics.Color.WHITE)
                        pg.render(bmp, null, null, android.graphics.pdf.PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                        val f = java.io.File(outDir, "page_$i.jpg")
                        java.io.FileOutputStream(f).use { bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 82, it) }
                        arr.put(f.absolutePath)
                    } finally { pg.close() }
                }
            } finally { pr.close() }
        } catch (e: Exception) { log("pdfPages: $e") }
        return arr.toString()
    }

    /** am start: {"action","data","type","package","component","extras":{k:v},"stream","flags","category"} */
    @JvmStatic fun startIntent(json: String): String {
        return try {
            val o = JSONObject(json)
            val i = Intent()
            if (o.optString("action").isNotEmpty()) i.action = o.getString("action")
            val data = o.optString("data")
            val type = o.optString("type")
            when {
                data.isNotEmpty() && type.isNotEmpty() -> i.setDataAndType(Uri.parse(data), type)
                data.isNotEmpty() -> i.data = Uri.parse(data)
                type.isNotEmpty() -> i.type = type
            }
            if (o.optString("package").isNotEmpty()) i.setPackage(o.getString("package"))
            val comp = o.optString("component")
            if (comp.isNotEmpty()) {
                val pk = comp.substringBefore('/')
                var cl = comp.substringAfter('/')
                if (cl.startsWith(".")) cl = pk + cl
                i.component = ComponentName(pk, cl)
            }
            if (o.optString("category").isNotEmpty()) i.addCategory(o.getString("category"))
            o.optJSONObject("extras")?.let { ex -> ex.keys().forEach { k -> i.putExtra(k, ex.getString(k)) } }
            o.optJSONObject("extras_long")?.let { ex -> ex.keys().forEach { k -> i.putExtra(k, ex.getLong(k)) } }
            o.optJSONObject("extras_int")?.let { ex -> ex.keys().forEach { k -> i.putExtra(k, ex.getInt(k)) } }
            o.optJSONObject("extras_bool")?.let { ex -> ex.keys().forEach { k -> i.putExtra(k, ex.getBoolean(k)) } }
            val streams = o.optJSONArray("streams")
            if (streams != null && streams.length() > 0) {
                val uris = ArrayList<Uri>()
                for (k in 0 until streams.length()) uris.add(Uri.parse(streams.getString(k)))
                if (uris.size == 1 && i.action != Intent.ACTION_SEND_MULTIPLE) i.putExtra(Intent.EXTRA_STREAM, uris[0])
                else i.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                i.clipData = ClipData.newRawUri("", uris[0])
            }
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (o.optBoolean("broadcast")) { app.sendBroadcast(i); return "Broadcast completed" }
            app.startActivity(i)
            "Starting: Intent { ${i.action ?: ""} }"
        } catch (e: Exception) {
            "Error: $e"
        }
    }

    @JvmStatic fun resolve(url: String): String {
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)
        val r = app.packageManager.resolveActivity(i, 0) ?: return "No activity found"
        return r.activityInfo.packageName + "/" + r.activityInfo.name
    }

    @JvmStatic fun openUrl(url: String): Boolean = try {
        app.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true
    } catch (e: Exception) { log("openUrl: $e"); false }

    @JvmStatic fun openSettings(action: String): Boolean = try {
        val i = Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (action == Settings.ACTION_APPLICATION_DETAILS_SETTINGS || action == "app_details") {
            i.action = Settings.ACTION_APPLICATION_DETAILS_SETTINGS
        }
        app.startActivity(i); true
    } catch (e: Exception) { log("openSettings: $e"); false }

    /** เปิดหน้า "ข้อมูลแอป" (ฝั่ง Python จะกด "บังคับหยุด" ต่อ) */
    @JvmStatic fun appDetails(pkg: String): Boolean = try {
        app.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$pkg"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true
    } catch (_: Exception) { false }

    @JvmStatic fun killBackground(pkg: String): Boolean = try {
        (app.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).killBackgroundProcesses(pkg); true
    } catch (_: Exception) { false }

    @JvmStatic fun killAll(): Int {
        val am = app.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        var n = 0
        for (p in app.packageManager.getInstalledApplications(0)) {
            if (p.packageName == app.packageName) continue
            try { am.killBackgroundProcesses(p.packageName); n++ } catch (_: Exception) {}
        }
        return n
    }

    @JvmStatic fun listPackages(thirdParty: Boolean): String {
        val sb = StringBuilder()
        for (p in app.packageManager.getInstalledApplications(0)) {
            if (thirdParty && (p.flags and android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0) continue
            sb.append("package:").append(p.packageName).append('\n')
        }
        return sb.toString()
    }

    /** แอปที่มีไอคอน: บรรทัดละ "ชื่อที่แสดง|package|activity" */
    @JvmStatic fun launcherApps(): String {
        val pm = app.packageManager
        val i = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val sb = StringBuilder()
        for (r in pm.queryIntentActivities(i, 0)) {
            val label = r.loadLabel(pm).toString().replace('|', ' ').replace('\n', ' ')
            sb.append(label).append('|').append(r.activityInfo.packageName).append('|')
                .append(r.activityInfo.name).append('\n')
        }
        return sb.toString()
    }

    /** ลายเสียง (MFCC 20 ค่า: เฉลี่ย + ส่วนเบี่ยงเบน + การเปลี่ยนแปลง = 60 ค่า) จาก PCM 16-bit 16kHz — ใช้แยกเสียงเจ้าของ */
    @JvmStatic fun voiceFeatures(pcm: ByteArray): String = VoicePrint.features(pcm)?.let { v ->
        org.json.JSONArray().also { a -> v.forEach { a.put(it.toDouble()) } }.toString()
    } ?: ""

    /** ย่อรูป (ด้านยาวไม่เกิน maxDim) → JPEG ส่งให้ AI ดูได้เร็ว */
    @JvmStatic fun shrinkImage(src: String, out: String, maxDim: Int): Boolean = try {
        val o = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeFile(src, o)
        var sample = 1
        while (maxOf(o.outWidth, o.outHeight) / (sample * 2) >= maxDim) sample *= 2
        val bmp = android.graphics.BitmapFactory.decodeFile(src, android.graphics.BitmapFactory.Options().apply { inSampleSize = sample })
        if (bmp == null) false else {
            val sc = maxDim.toFloat() / maxOf(bmp.width, bmp.height)
            val small = if (sc < 1f) android.graphics.Bitmap.createScaledBitmap(bmp, (bmp.width * sc).toInt(), (bmp.height * sc).toInt(), true) else bmp
            java.io.FileOutputStream(out).use { small.compress(android.graphics.Bitmap.CompressFormat.JPEG, 82, it) }
            true
        }
    } catch (e: Exception) { log("shrinkImage: $e"); false }

    /** วาดกรอบ+เลขบนภาพหน้าจอ (ให้ AI ที่ดูรูปได้บอกว่าแต่ละปุ่มคืออะไร) boxes = ((x1,y1,x2,y2),...) */
    @JvmStatic fun annotate(src: String, boxes: String, out: String): Boolean = try {
        val bmp = android.graphics.BitmapFactory.decodeFile(src)?.copy(android.graphics.Bitmap.Config.ARGB_8888, true)
        if (bmp == null) false else {
            val cv = android.graphics.Canvas(bmp)
            val box = android.graphics.Paint().apply { style = android.graphics.Paint.Style.STROKE; strokeWidth = 5f; color = 0xFFFF1744.toInt() }
            val bg = android.graphics.Paint().apply { color = 0xFFFF1744.toInt() }
            val tx = android.graphics.Paint().apply { color = android.graphics.Color.WHITE; textSize = 34f; isFakeBoldText = true }
            val arr = org.json.JSONArray(boxes)
            for (i in 0 until arr.length()) {
                val b = arr.getJSONArray(i)
                val r = android.graphics.RectF(b.getDouble(0).toFloat(), b.getDouble(1).toFloat(), b.getDouble(2).toFloat(), b.getDouble(3).toFloat())
                cv.drawRect(r, box)
                val label = "${i + 1}"
                cv.drawRect(r.left, r.top, r.left + 22f * label.length + 14f, r.top + 40f, bg)
                cv.drawText(label, r.left + 6f, r.top + 33f, tx)
            }
            val sc = 1280f / maxOf(bmp.width, bmp.height)
            val small = if (sc < 1f) android.graphics.Bitmap.createScaledBitmap(bmp, (bmp.width * sc).toInt(), (bmp.height * sc).toInt(), true) else bmp
            java.io.FileOutputStream(out).use { small.compress(android.graphics.Bitmap.CompressFormat.JPEG, 80, it) }
            true
        }
    } catch (e: Exception) { log("annotate: $e"); false }

    /** ข้อมูลแอป: หมวด เวอร์ชัน วันติดตั้ง แอประบบไหม (JSON) */
    @JvmStatic fun appMeta(pkg: String): String = try {
        val pm = app.packageManager
        val pi = pm.getPackageInfo(pkg, 0)
        val ai = pi.applicationInfo
        val cat = when (ai?.category ?: -1) {
            android.content.pm.ApplicationInfo.CATEGORY_GAME -> "game"
            android.content.pm.ApplicationInfo.CATEGORY_AUDIO -> "audio"
            android.content.pm.ApplicationInfo.CATEGORY_VIDEO -> "video"
            android.content.pm.ApplicationInfo.CATEGORY_IMAGE -> "image"
            android.content.pm.ApplicationInfo.CATEGORY_SOCIAL -> "social"
            android.content.pm.ApplicationInfo.CATEGORY_NEWS -> "news"
            android.content.pm.ApplicationInfo.CATEGORY_MAPS -> "maps"
            android.content.pm.ApplicationInfo.CATEGORY_PRODUCTIVITY -> "productivity"
            else -> ""
        }
        val sys = ((ai?.flags ?: 0) and android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0
        JSONObject().put("category", cat).put("version", pi.versionName ?: "")
            .put("installed", pi.firstInstallTime).put("updated", pi.lastUpdateTime).put("system", sys).toString()
    } catch (_: Exception) { "{}" }

    @JvmStatic fun appLabel(pkg: String): String = try {
        val pm = app.packageManager
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
    } catch (_: Exception) { "" }

    @JvmStatic fun prop(name: String): String = when (name) {
        "ro.product.manufacturer" -> Build.MANUFACTURER
        "ro.product.model" -> Build.MODEL
        "ro.product.brand" -> Build.BRAND
        "ro.build.version.release" -> Build.VERSION.RELEASE
        "ro.build.version.sdk" -> Build.VERSION.SDK_INT.toString()
        "ro.product.device" -> Build.DEVICE
        else -> ""
    }

    // ============================================================ เสียง / จอ / ระบบ

    private fun stream(name: String): Int = when (name) {
        "ring" -> AudioManager.STREAM_RING
        "alarm" -> AudioManager.STREAM_ALARM
        "notification" -> AudioManager.STREAM_NOTIFICATION
        "system" -> AudioManager.STREAM_SYSTEM
        "call" -> AudioManager.STREAM_VOICE_CALL
        else -> AudioManager.STREAM_MUSIC
    }

    @JvmStatic fun volumes(): String {
        val am = app.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val a = JSONArray()
        for (s in listOf("call", "system", "ring", "music", "alarm", "notification")) {
            val o = JSONObject()
            o.put("stream", s)
            o.put("volume", am.getStreamVolume(stream(s)))
            o.put("max_volume", am.getStreamMaxVolume(stream(s)))
            a.put(o)
        }
        return a.toString()
    }

    @JvmStatic fun setVolume(name: String, v: Int): Boolean = try {
        val am = app.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val s = stream(name)
        am.setStreamVolume(s, v.coerceIn(0, am.getStreamMaxVolume(s)), AudioManager.FLAG_SHOW_UI); true
    } catch (e: Exception) { log("setVolume: $e"); false }

    @JvmStatic fun canWriteSettings(): Boolean = Settings.System.canWrite(app)

    /** เปิดหน้าขอสิทธิ์ "แก้ไขการตั้งค่าระบบ" (ใช้หมุนจอ/ความสว่าง/เวลาปิดจอ) */
    @JvmStatic fun requestWriteSettings(): Boolean = try {
        app.startActivity(Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS, Uri.parse("package:${app.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true
    } catch (_: Exception) { false }

    @JvmStatic fun brightness(v: Int): Boolean {
        if (!Settings.System.canWrite(app)) return false
        return try {
            val cr = app.contentResolver
            if (v < 0) {
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS_MODE, Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC)
            } else {
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS_MODE, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL)
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS, v.coerceIn(1, 255))
            }
            true
        } catch (e: Exception) { log("brightness: $e"); false }
    }

    @JvmStatic fun settingsGet(ns: String, key: String): String = try {
        val cr = app.contentResolver
        when (ns) {
            "global" -> Settings.Global.getString(cr, key)
            "secure" -> Settings.Secure.getString(cr, key)
            else -> Settings.System.getString(cr, key)
        } ?: "null"
    } catch (_: Exception) { "null" }

    @JvmStatic fun settingsPut(ns: String, key: String, value: String): Boolean {
        if (ns == "global" && key == "zen_mode") return dnd(value != "0")
        if (ns != "system" || !Settings.System.canWrite(app)) return false
        return try { Settings.System.putString(app.contentResolver, key, value) } catch (e: Exception) { log("settings: $e"); false }
    }

    @JvmStatic fun dndAllowed(): Boolean =
        (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).isNotificationPolicyAccessGranted

    @JvmStatic fun dnd(on: Boolean): Boolean {
        val nm = app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (!nm.isNotificationPolicyAccessGranted) return false
        nm.setInterruptionFilter(if (on) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL)
        return true
    }

    @JvmStatic fun dndState(): Boolean =
        (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).currentInterruptionFilter !=
            NotificationManager.INTERRUPTION_FILTER_ALL

    @JvmStatic fun torch(on: Boolean): Boolean = try {
        val cm = app.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val id = cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it)
            .get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE) == true } ?: cm.cameraIdList[0]
        cm.setTorchMode(id, on); true
    } catch (e: Exception) { log("torch: $e"); false }

    @JvmStatic fun vibrate(ms: Int) {
        @Suppress("DEPRECATION")
        val v = app.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        v.vibrate(VibrationEffect.createOneShot(ms.toLong().coerceIn(10, 5000), VibrationEffect.DEFAULT_AMPLITUDE))
    }

    @JvmStatic fun clipboardSet(text: String) {
        val l = CountDownLatch(1)
        main.post {
            try {
                (app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                    .setPrimaryClip(ClipData.newPlainText("aibot", text))
            } catch (_: Exception) {}
            l.countDown()
        }
        l.await(3, TimeUnit.SECONDS)
    }

    @JvmStatic fun clipboardGet(): String {
        var out = ""
        val l = CountDownLatch(1)
        main.post {
            try {
                out = (app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                    .primaryClip?.getItemAt(0)?.coerceToText(app)?.toString() ?: ""
            } catch (_: Exception) {}
            l.countDown()
        }
        l.await(3, TimeUnit.SECONDS)
        return out
    }

    @JvmStatic fun battery(): String {
        val bm = app.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val st = app.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val o = JSONObject()
        o.put("percentage", bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
        val plugged = st?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        o.put("plugged", if (plugged == 0) "UNPLUGGED" else "PLUGGED_AC")
        val status = st?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        o.put("status", when (status) {
            BatteryManager.BATTERY_STATUS_CHARGING -> "CHARGING"
            BatteryManager.BATTERY_STATUS_FULL -> "FULL"
            BatteryManager.BATTERY_STATUS_DISCHARGING -> "DISCHARGING"
            else -> "NOT_CHARGING"
        })
        o.put("temperature", (st?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0) / 10.0)
        o.put("health", "GOOD")
        return o.toString()
    }

    @JvmStatic fun memInfo(): String {
        val am = app.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return JSONObject().put("total", mi.totalMem).put("avail", mi.availMem).put("low", mi.lowMemory).toString()
    }

    @SuppressLint("MissingPermission")
    @JvmStatic fun wifiInfo(): String {
        val o = JSONObject()
        try {
            @Suppress("DEPRECATION")
            val wm = app.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            o.put("enabled", wm.isWifiEnabled)
            @Suppress("DEPRECATION") val ci = wm.connectionInfo
            o.put("ssid", ci?.ssid ?: "")
            o.put("rssi", ci?.rssi ?: 0)
            o.put("link_speed_mbps", ci?.linkSpeed ?: 0)
            o.put("supplicant_state", ci?.supplicantState?.toString() ?: "")
        } catch (e: Exception) { o.put("error", e.toString()) }
        return o.toString()
    }

    /** สถานะระบบ "1"/"0"/"" (อ่านไม่ได้) — ใช้ตรวจว่าการแตะปุ่มในแผงควบคุมได้ผลจริง */
    @SuppressLint("MissingPermission")
    @JvmStatic fun sysState(kind: String): String = try {
        val cr = app.contentResolver
        when (kind) {
            "wifi" -> if (wifiEnabled()) "1" else "0"
            "bluetooth" -> {
                val bm = app.getSystemService(Context.BLUETOOTH_SERVICE) as android.bluetooth.BluetoothManager
                if (bm.adapter?.isEnabled == true) "1" else "0"
            }
            "airplane" -> Settings.Global.getInt(cr, Settings.Global.AIRPLANE_MODE_ON, 0).toString()
            "data" -> if (Settings.Global.getInt(cr, "mobile_data", 0) != 0) "1" else "0"
            "location" -> if ((app.getSystemService(Context.LOCATION_SERVICE) as LocationManager).isLocationEnabled) "1" else "0"
            "nfc" -> android.nfc.NfcAdapter.getDefaultAdapter(app)?.let { if (it.isEnabled) "1" else "0" } ?: ""
            "dnd" -> if (dndState()) "1" else "0"
            "rotate" -> Settings.System.getInt(cr, Settings.System.ACCELEROMETER_ROTATION, 0).toString()
            else -> ""
        }
    } catch (e: Exception) { log("sysState $kind: $e"); "" }

    @JvmStatic fun wifiEnabled(): Boolean = try {
        (app.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager).isWifiEnabled
    } catch (_: Exception) { false }

    @SuppressLint("MissingPermission")
    @JvmStatic fun location(): String {
        val lm = app.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (app.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            app.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED)
            return "{\"error\":\"ยังไม่ได้ให้สิทธิ์ตำแหน่งกับแอป\"}"
        val loc = lm.getProviders(true).mapNotNull { try { lm.getLastKnownLocation(it) } catch (_: Exception) { null } }
            .maxByOrNull { it.time } ?: return "{\"error\":\"ยังไม่มีตำแหน่งล่าสุด\"}"
        return JSONObject().put("latitude", loc.latitude).put("longitude", loc.longitude)
            .put("accuracy", loc.accuracy.toDouble()).put("provider", loc.provider).toString()
    }

    // ============================================================ โทร / SMS / รายชื่อ

    private fun has(p: String) = app.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    @JvmStatic fun answerCall(): Boolean {
        if (!has(Manifest.permission.ANSWER_PHONE_CALLS)) return false
        return try {
            val tm = app.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
            if (!tm.isInCall) return false
            @Suppress("DEPRECATION") tm.acceptRingingCall(); true
        } catch (e: Exception) { log("answer: $e"); false }
    }

    @SuppressLint("MissingPermission")
    @JvmStatic fun endCall(): Boolean {
        if (Build.VERSION.SDK_INT < 28 || !has(Manifest.permission.ANSWER_PHONE_CALLS)) return false
        return try {
            @Suppress("DEPRECATION")
            (app.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).endCall()
        } catch (e: Exception) { log("endCall: $e"); false }
    }

    @SuppressLint("MissingPermission")
    @JvmStatic fun inCall(): Boolean = try {
        has(Manifest.permission.READ_PHONE_STATE) && (app.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).isInCall
    } catch (_: Exception) { false }

    @JvmStatic fun call(number: String): Boolean = try {
        val act = if (has(Manifest.permission.CALL_PHONE)) Intent.ACTION_CALL else Intent.ACTION_DIAL
        app.startActivity(Intent(act, Uri.parse("tel:" + Uri.encode(number))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true
    } catch (e: Exception) { log("call: $e"); false }

    @JvmStatic fun smsSend(number: String, text: String): Boolean {
        if (!has(Manifest.permission.SEND_SMS)) return false
        return try {
            @Suppress("DEPRECATION") val sm = if (Build.VERSION.SDK_INT >= 31)
                app.getSystemService(SmsManager::class.java) else SmsManager.getDefault()
            sm.sendMultipartTextMessage(number, null, sm.divideMessage(text), null, null); true
        } catch (e: Exception) { log("sms: $e"); false }
    }

    @JvmStatic fun smsList(limit: Int): String {
        val a = JSONArray()
        if (!has(Manifest.permission.READ_SMS)) return a.toString()
        app.contentResolver.query(Telephony.Sms.CONTENT_URI, arrayOf("address", "body", "date", "type"),
            null, null, "date DESC")?.use { c ->
            while (c.moveToNext() && a.length() < limit) {
                a.put(JSONObject().put("number", c.getString(0) ?: "").put("body", c.getString(1) ?: "")
                    .put("received", c.getLong(2)).put("type", if (c.getInt(3) == 1) "inbox" else "sent"))
            }
        }
        return a.toString()
    }

    @JvmStatic fun contacts(): String {
        val a = JSONArray()
        if (!has(Manifest.permission.READ_CONTACTS)) return a.toString()
        app.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER),
            null, null, null)?.use { c ->
            while (c.moveToNext()) a.put(JSONObject().put("name", c.getString(0) ?: "").put("number", c.getString(1) ?: ""))
        }
        return a.toString()
    }

    /** นัดในปฏิทินของเครื่อง (ทุกบัญชีที่ซิงก์ไว้ รวม Google/Huawei) ช่วงเวลา [startMs, endMs) → JSON array
     *  ไม่มีสิทธิ์ → {"noperm":true} */
    @JvmStatic fun calendarEvents(startMs: Long, endMs: Long): String {
        if (!has(Manifest.permission.READ_CALENDAR)) return "{\"noperm\":true}"
        val a = JSONArray()
        try {
            android.provider.CalendarContract.Instances.query(app.contentResolver,
                arrayOf(android.provider.CalendarContract.Instances.TITLE, android.provider.CalendarContract.Instances.BEGIN,
                    android.provider.CalendarContract.Instances.END, android.provider.CalendarContract.Instances.ALL_DAY,
                    android.provider.CalendarContract.Instances.EVENT_LOCATION, android.provider.CalendarContract.Instances.EVENT_ID),
                startMs, endMs)?.use { c ->
                while (c.moveToNext() && a.length() < 50) {
                    a.put(JSONObject().put("title", c.getString(0) ?: "").put("begin", c.getLong(1)).put("end", c.getLong(2))
                        .put("allDay", c.getInt(3) == 1).put("location", c.getString(4) ?: "").put("id", c.getLong(5)))
                }
            }
        } catch (e: Exception) { log("calendar: $e") }
        return a.toString()
    }

    @JvmStatic fun callLog(limit: Int): String {
        val a = JSONArray()
        if (!has(Manifest.permission.READ_CALL_LOG)) return a.toString()
        app.contentResolver.query(CallLog.Calls.CONTENT_URI,
            arrayOf(CallLog.Calls.CACHED_NAME, CallLog.Calls.NUMBER, CallLog.Calls.TYPE, CallLog.Calls.DATE, CallLog.Calls.DURATION),
            null, null, CallLog.Calls.DATE + " DESC")?.use { c ->
            while (c.moveToNext() && a.length() < limit) {
                val t = when (c.getInt(2)) { 1 -> "INCOMING"; 2 -> "OUTGOING"; 3 -> "MISSED"; else -> "OTHER" }
                a.put(JSONObject().put("name", c.getString(0) ?: "").put("phone_number", c.getString(1) ?: "")
                    .put("type", t).put("date", c.getLong(3)).put("duration", c.getLong(4)))
            }
        }
        return a.toString()
    }

    // ============================================================ ไฟล์ / สื่อ

    /** สแกนไฟล์เข้าคลังสื่อ คืน content:// (ใช้แชร์ไฟล์เข้าแอปอื่น) */
    @JvmStatic fun mediaUri(path: String): String {
        var out = ""
        val l = CountDownLatch(1)
        MediaScannerConnection.scanFile(app, arrayOf(path), null) { _, uri -> out = uri?.toString() ?: ""; l.countDown() }
        l.await(10, TimeUnit.SECONDS)
        return out
    }

    @JvmStatic fun allFilesAccess(): Boolean =
        if (Build.VERSION.SDK_INT >= 30) android.os.Environment.isExternalStorageManager() else true

    @JvmStatic fun play(path: String, wait: Boolean): Boolean = Player.play(path, wait)
    @JvmStatic fun stopPlay() = Player.stop()
    @JvmStatic fun playing(): Boolean = Player.playing
    @JvmStatic fun speak(text: String, wait: Boolean): Boolean = Player.speak(text, wait)

    @JvmStatic fun micStart(): Boolean = Mic.start()
    @JvmStatic fun micRead(timeoutMs: Int): ByteArray = Mic.read(timeoutMs.toLong())
    @JvmStatic fun micStop() = Mic.stop()
    @JvmStatic fun micFlush() = Mic.flush()
    @JvmStatic fun micError(): String = Mic.lastError
    @JvmStatic fun micAllowed(): Boolean = has(Manifest.permission.RECORD_AUDIO)
    /** ระบบรู้จำเสียงของเครื่อง (Google) ใช้ได้ไหม / ฟังหนึ่งประโยค → JSON */
    @JvmStatic fun googleSttAvailable(): Boolean = GoogleStt.available()
    @JvmStatic fun googleListen(timeoutMs: Int, lang: String): String = GoogleStt.listen(timeoutMs, lang)
    @JvmStatic fun camAllowed(): Boolean = has(Manifest.permission.CAMERA)
    @JvmStatic fun camCapture(front: Boolean, path: String): String = Cam.capture(app, front, path)
    @JvmStatic fun camFaces(path: String, facePath: String): String = Cam.faces(path, facePath)
    @JvmStatic fun faceVector(facePath: String): String = Cam.lbph(facePath)

    // ============================================================ บอท / ซ่อมตัวเอง

    /** รันเทสต์ในโปรเซสแยก (:heal) แล้วรอผล JSON */
    @JvmStatic fun runHeal(stageDir: String, timeoutSec: Int): String {
        val res = File(stageDir, "heal_result.json")
        res.delete()
        val i = Intent(app, HealService::class.java).putExtra("stage", stageDir).putExtra("result", res.absolutePath)
        try { app.startService(i) } catch (e: Exception) { return "{\"error\":\"start heal: $e\"}" }
        val end = SystemClock.elapsedRealtime() + timeoutSec * 1000L
        while (SystemClock.elapsedRealtime() < end) {
            if (res.exists() && res.length() > 0) {
                Thread.sleep(300)
                return res.readText()
            }
            Thread.sleep(1000)
        }
        app.stopService(i)
        return "{\"error\":\"timeout\"}"
    }

    /** เริ่มบอทใหม่ (โหลดโค้ดที่ซ่อมแล้ว): ตั้งเวลาเปิดบริการใหม่ แล้วปิดโปรเซสนี้ */
    @JvmStatic fun restartBot() {
        log("♻️ รีสตาร์ทบอท")
        try {
            val i = Intent(app, BotService::class.java)
            val pi = PendingIntent.getForegroundService(app, 7, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val am = app.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + 1500, pi)
        } catch (e: Exception) {
            log("restart schedule: $e")
        }
        main.postDelayed({ Process.killProcess(Process.myPid()) }, 400)
    }

    @JvmStatic fun ignoringBattery(): Boolean =
        (app.getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(app.packageName)

    @JvmStatic fun status(): String = JSONObject()
        .put("a11y", a11yOn()).put("notif", notifOn()).put("mic", micAllowed())
        .put("write_settings", canWriteSettings()).put("dnd", dndAllowed()).put("battery_opt", ignoringBattery())
        .put("files", allFilesAccess()).put("bot", BotService.running).toString()
}
