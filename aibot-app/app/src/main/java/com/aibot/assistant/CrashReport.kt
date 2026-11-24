package com.aibot.assistant

import android.app.Activity
import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.widget.ScrollView
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.util.Date

/**
 * บันทึกสาเหตุที่แอปปิดเอง (แอปหลุด) แล้วแสดงตอนเปิดแอปครั้งถัดไป ให้ผู้ทดลองคัดลอกส่งผู้พัฒนาได้
 * - ข้อผิดพลาดฝั่ง Kotlin/Java → จับเองแล้วเขียน data/crash.txt
 * - หลุดจากโค้ด native (Python) / ค้าง (ANR) / หน่วยความจำไม่พอ → อ่านจากระบบ (Android 11+)
 */
object CrashReport {
    private fun file(c: Context) = File(c.filesDir, "data/crash.txt")

    private fun device(c: Context): String {
        val ver = try { c.packageManager.getPackageInfo(c.packageName, 0).versionName } catch (_: Exception) { "?" }
        return "เครื่อง: ${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT}) · แอป $ver"
    }

    /** เรียกครั้งเดียวตอนแอปเริ่ม */
    fun install(c: Context) {
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try {
                val sw = StringWriter(); e.printStackTrace(PrintWriter(sw))
                val f = file(c); f.parentFile?.mkdirs()
                f.writeText("เวลา: ${Date()}\n${device(c)}\nหน้า: ${App.top?.javaClass?.simpleName ?: "-"} · เธรด: ${t.name}\n\n" +
                    sw.toString().take(6000))
            } catch (_: Throwable) {}
            prev?.uncaughtException(t, e)
        }
    }

    /** สาเหตุที่ระบบบันทึกไว้ หลังครั้งล่าสุดที่เคยแสดงแล้ว (เฉพาะแบบที่เป็นปัญหา) */
    private fun systemExits(c: Context): String {
        if (Build.VERSION.SDK_INT < 30) return ""
        val p = c.getSharedPreferences("app", Context.MODE_PRIVATE)
        val since = p.getLong("exit_seen", 0)
        val first = since == 0L
        val am = c.getSystemService(ActivityManager::class.java) ?: return ""
        val list = try { am.getHistoricalProcessExitReasons(c.packageName, 0, 8) } catch (_: Exception) { return "" }
        val newest = list.maxOfOrNull { it.timestamp } ?: 0L
        if (newest > since) p.edit().putLong("exit_seen", newest).apply()
        if (first) return ""                       // ติดตั้งใหม่ครั้งแรก: เริ่มนับจากตอนนี้
        val bad = mapOf(
            ApplicationExitInfo.REASON_CRASH to "แอปเกิดข้อผิดพลาด",
            ApplicationExitInfo.REASON_CRASH_NATIVE to "ข้อผิดพลาดในส่วน native (Python/เสียง)",
            ApplicationExitInfo.REASON_ANR to "แอปค้าง (ANR)",
            ApplicationExitInfo.REASON_LOW_MEMORY to "หน่วยความจำเครื่องไม่พอ",
            ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE to "ใช้ทรัพยากรมากเกินไป",
            ApplicationExitInfo.REASON_INITIALIZATION_FAILURE to "เริ่มแอปไม่สำเร็จ",
        )
        val sb = StringBuilder()
        for (x in list.filter { it.timestamp > since && it.reason in bad }.sortedBy { it.timestamp }) {
            sb.append("• ${Date(x.timestamp)} — ${bad[x.reason]}")
            x.description?.let { sb.append(": ").append(it.take(300)) }
            sb.append('\n')
            if (x.reason == ApplicationExitInfo.REASON_ANR) try {
                x.traceInputStream?.bufferedReader()?.use { r -> sb.append(r.readText().take(2500)).append('\n') }
            } catch (_: Exception) {}
        }
        return sb.toString()
    }

    /** มีบันทึกการหลุดครั้งก่อน → แสดงให้ผู้ใช้คัดลอก · คืนค่า dialog (หรือ null ถ้าไม่มี) */
    fun showIfAny(a: Activity, onClose: () -> Unit): Dialog? {
        val f = file(a)
        val own = try { if (f.exists()) f.readText() else "" } catch (_: Exception) { "" }
        val sys = try { systemExits(a) } catch (_: Exception) { "" }
        if (own.isBlank() && sys.isBlank()) return null
        try { f.renameTo(File(f.parentFile, "crash_last.txt")) } catch (_: Exception) {}
        val text = buildString {
            if (own.isNotBlank()) append(own.trim()).append("\n\n")
            if (sys.isNotBlank()) append("บันทึกจากระบบ:\n").append(sys)
            if (own.isBlank()) append("\n").append(device(a))
        }.trim()
        Bridge.log("💥 แอปปิดเองครั้งก่อน: ${text.take(300)}")
        return Popups.panel(a, "💥", "ครั้งก่อนแอปปิดเอง") { card, d ->
            card.addView(Ui.text(a, "ขออภัยครับ 🙏 ช่วยกด 'คัดลอก' แล้ววางในช่องข้อเสนอแนะของแบบประเมิน " +
                "หรือส่งให้ผู้พัฒนา จะได้แก้ให้ตรงจุด", 14f, false, Ui.TEXT), Ui.lpm(a, b = 10))
            val sv = ScrollView(a)
            sv.addView(Ui.text(a, text, 11f, false, Ui.SUB).apply { setTextIsSelectable(true) })
            card.addView(sv, Ui.lpm(a, h = Ui.dp(a, 200), b = 12))
            card.addView(Ui.button(a, "📋 คัดลอก", true) {
                (a.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                    .setPrimaryClip(ClipData.newPlainText("crash", text))
                Popups.snack(a, "คัดลอกแล้ว")
            }, Ui.lpm(a, b = 8))
            card.addView(Ui.button(a, "ปิด") { d.dismiss() })
        }.apply { setOnDismissListener { onClose() } }
    }
}
