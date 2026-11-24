package com.aibot.assistant

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.provider.Settings
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

/**
 * อัปเดตแอปจาก GitHub Releases ในตัว — ติดตั้งทับของเดิม ไม่ต้องถอน (ข้อมูล/คีย์/ความจำอยู่ครบ)
 * ตั้งค่า UPDATE_REPO = "ชื่อบัญชี/ชื่อ repo" (+ UPDATE_TOKEN ถ้า repo เป็น Private)
 */
object Updater {
    data class Release(val tag: String, val published: Long, val apiUrl: String, val size: Long)

    private fun env(c: Context) = Env.load(c)

    private fun open(url: String, token: String?, accept: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000; readTimeout = 30000
            instanceFollowRedirects = false
            setRequestProperty("Accept", accept)
            setRequestProperty("User-Agent", "ai-assistant-updater")
            if (!token.isNullOrBlank()) setRequestProperty("Authorization", "Bearer $token")
        }

    /** รุ่นล่าสุดบน GitHub หรือ null / โยน error พร้อมเหตุผลภาษาไทย */
    fun latest(c: Context): Release? {
        val e = env(c)
        val repo = normRepo(e["UPDATE_REPO"] ?: return null) ?: throw Exception("ชื่อ repo ไม่ถูกต้อง — ใส่แบบ ชื่อบัญชี/ชื่อrepo เช่น MISFRIDAYS/ai-assistant")
        val conn = open("https://api.github.com/repos/$repo/releases/latest", e["UPDATE_TOKEN"], "application/vnd.github+json")
        val code = conn.responseCode
        if (code == 404) {
            val r = open("https://api.github.com/repos/$repo", e["UPDATE_TOKEN"], "application/vnd.github+json").responseCode
            throw Exception(if (r == 404) "ไม่เจอ repo \"$repo\" — เช็คชื่อบัญชี/ชื่อ repo (ถ้าเป็น Private ต้องใส่ token)"
                            else "เจอ repo \"$repo\" แล้ว แต่ยังไม่มี Release — รอ Actions build ให้ขึ้น ✅ ก่อน แล้วดูที่หน้า Releases")
        }
        if (code == 401 || code == 403) throw Exception("token ไม่ถูกต้อง/หมดอายุ (HTTP $code)")
        if (code != 200) throw Exception("GitHub ตอบ HTTP $code")
        val o = JSONObject(conn.inputStream.bufferedReader().readText())
        val assets = o.getJSONArray("assets")
        for (i in 0 until assets.length()) {
            val a = assets.getJSONObject(i)
            if (a.getString("name").endsWith(".apk")) {
                val t = Instant.parse(a.optString("updated_at", o.getString("published_at"))).toEpochMilli()
                return Release(o.getString("tag_name"), t, a.getString("url"), a.optLong("size"))
            }
        }
        throw Exception("Release ล่าสุดไม่มีไฟล์ .apk")
    }

    /** รับได้ทุกแบบ: "a/b", "github.com/a/b", "https://github.com/a/b/releases", "a/b.git" */
    fun normRepo(raw: String): String? {
        val t = raw.trim().replace(" ", "").removeSuffix(".git")
        val m = Regex("(?:github\\.com/)?([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)").find(t.substringAfter("github.com/", t)) ?: return null
        return "${m.groupValues[1]}/${m.groupValues[2]}"
    }

    fun installedAt(c: Context): Long = c.packageManager.getPackageInfo(c.packageName, 0).lastUpdateTime

    fun isNewer(c: Context, r: Release) = r.published > installedAt(c) + 5 * 60_000

    private fun download(c: Context, r: Release, progress: (Int) -> Unit): File {
        val token = env(c)["UPDATE_TOKEN"]
        var conn = open(r.apiUrl, token, "application/octet-stream")
        var hops = 0
        while (conn.responseCode in 301..308 && hops++ < 5) {        // ไปที่เก็บไฟล์จริง (ห้ามส่ง token ต่อ)
            val loc = conn.getHeaderField("Location")
            conn.disconnect()
            conn = open(loc, null, "application/octet-stream")
        }
        if (conn.responseCode != 200) throw Exception("ดาวน์โหลดไม่ได้ (HTTP ${conn.responseCode})")
        val f = File(c.cacheDir, "update.apk")
        val total = if (conn.contentLengthLong > 0) conn.contentLengthLong else r.size
        conn.inputStream.use { inp ->
            f.outputStream().use { out ->
                val buf = ByteArray(64 * 1024); var done = 0L; var last = -1
                while (true) {
                    val n = inp.read(buf); if (n < 0) break
                    out.write(buf, 0, n); done += n
                    val p = if (total > 0) (done * 100 / total).toInt() else 0
                    if (p != last) { last = p; progress(p) }
                }
            }
        }
        return f
    }

    fun canInstall(c: Context) = c.packageManager.canRequestPackageInstalls()

    fun askInstallPermission(a: Activity) {
        a.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${a.packageName}")))
    }

    private fun install(c: Context, apk: File) {
        val pi = c.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            .apply { setAppPackageName(c.packageName) }
        val id = pi.createSession(params)
        pi.openSession(id).use { s ->
            apk.inputStream().use { inp -> s.openWrite("app.apk", 0, apk.length()).use { out -> inp.copyTo(out); s.fsync(out) } }
            val cb = PendingIntent.getBroadcast(c, id, Intent(c, InstallReceiver::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            s.commit(cb.intentSender)
        }
    }

    /** ตรวจ + (ถ้ามีใหม่) ถามผู้ใช้ → ดาวน์โหลด → ติดตั้งทับ */
    fun check(a: Activity, manual: Boolean) {
        val prefs = a.getSharedPreferences("app", Context.MODE_PRIVATE)
        if (!manual && System.currentTimeMillis() - prefs.getLong("upd_check", 0) < 3 * 3600_000) return
        if (env(a)["UPDATE_REPO"].isNullOrBlank()) {
            if (manual) Popups.info(a, "🔄", "ยังไม่ได้ตั้งค่าอัปเดต", "ไปที่ ⚙️ ตั้งค่า → 🔄 อัปเดตแอป ใส่ชื่อ repo GitHub ก่อน")
            return
        }
        prefs.edit().putLong("upd_check", System.currentTimeMillis()).apply()
        if (manual) Popups.snack(a, "🔄 กำลังตรวจเวอร์ชันใหม่…")
        Thread {
            try {
                val r = latest(a)
                a.runOnUiThread {
                    if (r == null || !isNewer(a, r)) {
                        if (manual) Popups.info(a, "✅", "เป็นเวอร์ชันล่าสุดแล้ว", r?.tag ?: "")
                    } else if (!manual && prefs.getString("upd_skip", "") == r.tag) {
                        // ผู้ใช้กด "ไว้ทีหลัง" กับรุ่นนี้แล้ว
                    } else {
                        Popups.choose(a, "🎁", "มีเวอร์ชันใหม่ (${r.tag})",
                            "อัปเดตทับของเดิม — คีย์ ความจำ การตั้งค่า อยู่ครบ ไม่ต้องถอนแอป",
                            listOf("อัปเดตเลย" to { start(a, r) },
                                "ไว้ทีหลัง" to { prefs.edit().putString("upd_skip", r.tag).apply() }))
                    }
                }
            } catch (e: Exception) {
                Bridge.log("update check: $e")
                if (manual) a.runOnUiThread { Popups.info(a, "⚠️", "ตรวจอัปเดตไม่ได้", e.message ?: e.toString()) }
            }
        }.start()
    }

    fun start(a: Activity, r: Release) {
        if (!canInstall(a)) {
            Popups.info(a, "🔐", "ขอสิทธิ์ติดตั้งแอปก่อน", "เปิดสวิตช์ \"อนุญาตจากแหล่งนี้\" ให้ผู้ช่วย แล้วกลับมากดอัปเดตอีกครั้ง")
            askInstallPermission(a)
            return
        }
        Popups.snack(a, "⬇️ กำลังดาวน์โหลด ${r.tag}…")
        Thread {
            try {
                val f = download(a, r) { p -> if (p % 20 == 0) a.runOnUiThread { Popups.snack(a, "⬇️ ดาวน์โหลด $p%") } }
                a.runOnUiThread { Popups.snack(a, "📦 กำลังติดตั้ง…") }
                install(a, f)
            } catch (e: Exception) {
                Bridge.log("update: $e")
                a.runOnUiThread { Popups.info(a, "⚠️", "อัปเดตไม่สำเร็จ", e.message ?: e.toString()) }
            }
        }.start()
    }
}

/** ผลการติดตั้ง: ต้องให้ผู้ใช้กดยืนยัน → เปิดหน้ายืนยันของระบบ */
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        when (val st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, -999)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = i.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)?.let { c.startActivity(it) }
            }
            PackageInstaller.STATUS_SUCCESS -> Bridge.log("✅ อัปเดตแอปสำเร็จ")
            else -> {
                val msg = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: ""
                Bridge.log("update install status $st: $msg")
                Bridge.toast("อัปเดตไม่สำเร็จ: " +
                    if (st == PackageInstaller.STATUS_FAILURE_CONFLICT || msg.contains("signatures", true))
                        "ลายเซ็นแอปไม่ตรงกับตัวที่ติดตั้งอยู่ (ต้องถอนครั้งเดียว แล้วจากนี้อัปเดตทับได้ตลอด)" else msg)
            }
        }
    }
}
