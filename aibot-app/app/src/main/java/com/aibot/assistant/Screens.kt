package com.aibot.assistant

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import org.json.JSONObject
import java.io.File

/** โครงหน้าจอย่อย: หัวม่วง + เนื้อหาเลื่อนได้ */
abstract class PageActivity : Activity() {
    protected lateinit var box: LinearLayout

    protected fun page(title: String, subtitle: String) {
        Ui.statusBar(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Ui.P50) }
        root.addView(Ui.header(this, title, subtitle))
        val sv = ScrollView(this).apply { isVerticalScrollBarEnabled = false }
        box = Ui.col(this, 16)
        sv.addView(box)
        root.addView(sv, Ui.lp(h = 0, weight = 1f))
        setContentView(root)
    }

    protected fun section(t: String) {
        box.addView(Ui.text(this, Ui.plain(t), 15f, true, Ui.TEXT), Ui.lpm(this, t = 18, b = 8, s = 4))
    }
}

/** ตั้งค่าสิทธิ์ทีละข้อ (การ์ด + แถบความคืบหน้า) */
class SetupActivity : PageActivity() {
    private var n = 0

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        if (Env.tester(this)) page("สิทธิ์ของผู้ช่วย", "เปิด 3 ข้อนี้ แล้วเริ่มใช้งานได้เลย")
        else page("สิทธิ์ของผู้ช่วย", "เปิดให้ครบ ผู้ช่วยจะทำงานแทนได้ทุกอย่าง")
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun item(ok: Boolean, emoji: String, title: String, desc: String, action: () -> Unit) {
        val card = Ui.card(this, 14, 20)
        if (!ok) card.background = Ui.round(Ui.WHITE, Ui.dpf(this, 22f), Ui.P500, Ui.dp(this, 2))   // ข้อที่ยังไม่เปิด = เด่น
        val r = Ui.row(this)
        val ic = Ui.iconTile(this, emoji, 48, if (ok) Ui.OK else Ui.P700, if (ok) 0xFFE9F7EF.toInt() else Ui.P100)
        r.addView(ic, LinearLayout.LayoutParams(Ui.dp(this, 48), Ui.dp(this, 48)).apply { marginEnd = Ui.dp(this@SetupActivity, 14) })
        val tc = Ui.col(this, 0)
        tc.addView(Ui.text(this, title, 15.5f, true))
        tc.addView(Ui.text(this, desc, 12.5f, false, Ui.SUB))
        r.addView(tc, Ui.lp(0, weight = 1f))
        if (ok) r.addView(Ui.text(this, "เปิดแล้ว", 13.5f, false, Ui.OK).apply {
            getDrawable(R.drawable.ic_ui_check)?.let { d ->
                d.setTint(Ui.OK); val s = Ui.dp(this@SetupActivity, 18); d.setBounds(0, 0, s, s)
                setCompoundDrawablesRelative(d, null, null, null); compoundDrawablePadding = Ui.dp(this@SetupActivity, 4)
            }
            gravity = Gravity.CENTER_VERTICAL; setPadding(Ui.dp(this@SetupActivity, 8), 0, 0, 0)
        })
        card.addView(r)
        if (!ok) card.addView(Ui.button(this, "เปิดสิทธิ์นี้", true) { action() }, Ui.lpm(this, t = 12))
        card.layoutParams = Ui.lpm(this, b = 10)
        box.addView(card)
        Fx.enter(card, delay = (n++ * 40L))
    }

    private fun open(i: Intent) {
        try { startActivity(i) } catch (_: Exception) {
            try { startActivity(Intent(Settings.ACTION_SETTINGS)) } catch (e: Exception) { Bridge.log("open: $e") }
        }
    }

    private fun pkgUri() = Uri.parse("package:$packageName")

    /** วิธีกันระบบปิดแอปเบื้องหลัง แยกตามยี่ห้อ (ชื่อเมนูอาจต่างกันเล็กน้อยตามเวอร์ชัน) */
    private fun batteryHint(): String {
        val m = (Build.MANUFACTURER ?: "").lowercase()
        return when {
            "huawei" in m || "honor" in m ->
                "Huawei: ตั้งค่า > แบตเตอรี่ > การเปิดแอป > ผู้ช่วย AI → ปิดจัดการอัตโนมัติ เปิดทั้ง 3 ข้อ"
            "samsung" in m ->
                "Samsung: ข้อมูลแอป ผู้ช่วย AI > แบตเตอรี่ > ไม่จำกัด · และ ตั้งค่า > การดูแลอุปกรณ์ > แบตเตอรี่ > " +
                    "การจำกัดการใช้งานเบื้องหลัง > แอปที่ไม่หลับ > เพิ่ม ผู้ช่วย AI"
            "xiaomi" in m || "redmi" in m || "poco" in m ->
                "Xiaomi/Redmi: ข้อมูลแอป ผู้ช่วย AI > ประหยัดแบตเตอรี่ > ไม่จำกัด · เปิด 'เริ่มอัตโนมัติ' · " +
                    "แล้วเปิดหน้าแอปล่าสุด กดค้างที่แอป → กดรูปกุญแจ (ล็อกไว้)"
            "vivo" in m || "iqoo" in m ->
                "Vivo: ตั้งค่า > แบตเตอรี่ > การใช้พลังงานเบื้องหลังสูง > เปิด ผู้ช่วย AI · " +
                    "และ ตั้งค่า > แอป > เริ่มอัตโนมัติ > เปิด ผู้ช่วย AI"
            "oppo" in m || "realme" in m || "oneplus" in m ->
                "Oppo/realme: ข้อมูลแอป ผู้ช่วย AI > การใช้แบตเตอรี่ > อนุญาตกิจกรรมเบื้องหลัง + อนุญาตเริ่มอัตโนมัติ · " +
                    "แล้วล็อกแอปในหน้าแอปล่าสุด"
            else -> "ตั้งค่า > แบตเตอรี่ (หรือข้อมูลแอป ผู้ช่วย AI > แบตเตอรี่) → ตั้งเป็น 'ไม่จำกัด' / ไม่ปรับให้เหมาะสม"
        }
    }
    private fun runtimeOk(vararg p: String) = p.all { checkSelfPermission(it) == android.content.pm.PackageManager.PERMISSION_GRANTED }

    private fun render() {
        if (isFinishing || isDestroyed) return
        try { renderItems() } catch (e: Exception) {
            Bridge.log("setup render: $e")
            box.removeAllViews()
            box.addView(Ui.text(this, "โหลดรายการสิทธิ์ไม่สำเร็จ กดกลับแล้วเข้าใหม่อีกครั้ง", 15f, false, Ui.SUB))
        }
    }

    private fun renderItems() {
        box.removeAllViews(); n = 0
        val s = try { JSONObject(Bridge.status()) } catch (_: Exception) { JSONObject() }
        val basic = mutableListOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA, Manifest.permission.READ_CALENDAR)
        if (Build.VERSION.SDK_INT >= 33) basic.add(Manifest.permission.POST_NOTIFICATIONS)
        if (Build.VERSION.SDK_INT >= 31) basic.add(Manifest.permission.BLUETOOTH_CONNECT)
        val phone = arrayOf(Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.CALL_PHONE, Manifest.permission.READ_CONTACTS, Manifest.permission.READ_CALL_LOG,
            Manifest.permission.SEND_SMS, Manifest.permission.READ_SMS)
        val loc = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        val tester = Env.tester(this)       // รุ่นผู้ทดลอง: เหลือเฉพาะสิทธิ์ที่จำเป็นจริง
        val checks = if (tester) listOf(s.optBoolean("a11y"), runtimeOk(*basic.toTypedArray()), s.optBoolean("battery_opt"))
        else listOf(s.optBoolean("a11y"), s.optBoolean("notif"), runtimeOk(*basic.toTypedArray()),
            s.optBoolean("files"), s.optBoolean("write_settings"), s.optBoolean("dnd"), s.optBoolean("battery_opt"),
            Settings.canDrawOverlays(this))
        val done = checks.count { it }

        // ความคืบหน้า
        val prog = Ui.card(this, 16, 20)
        prog.addView(Ui.text(this, "ตั้งค่าแล้ว $done / ${checks.size}", 16f, true, Ui.P700))
        val bar = LinearLayout(this).apply { background = Ui.round(Ui.P100, Ui.dpf(this@SetupActivity, 6f)) }
        val fill = View(this).apply {
            background = Ui.grad(Ui.dpf(this@SetupActivity, 6f), Ui.P500, Ui.PINK, orient = android.graphics.drawable.GradientDrawable.Orientation.LEFT_RIGHT)
        }
        bar.addView(fill, LinearLayout.LayoutParams(0, Ui.dp(this, 10), done.toFloat()))
        bar.addView(View(this), LinearLayout.LayoutParams(0, Ui.dp(this, 10), (checks.size - done).toFloat()))
        prog.addView(bar, Ui.lpm(this, t = 10))
        if (done == checks.size) prog.addView(Ui.text(this, "🎉 ครบแล้ว! ผู้ช่วยพร้อมทำงานเต็มที่", 14f, false, Ui.OK), Ui.lpm(this, t = 8))
        box.addView(prog)

        section("จำเป็น")
        item(s.optBoolean("a11y"), "📱", "คุมหน้าจอ (Accessibility)",
            "อ่านจอ แตะ พิมพ์ ปัดแทนคุณ — หน้าถัดไปเลื่อนลงล่างสุด → 'ผู้ช่วย AI — ควบคุมหน้าจอ' → เปิด\n(ห้ามเปิด ScreenReader)" +
                (if (Build.VERSION.SDK_INT >= 33) "\nถ้าปุ่มเป็นสีเทา: ข้อมูลแอป ผู้ช่วย AI → ⋮ มุมขวาบน → อนุญาตการตั้งค่าที่ถูกจำกัด แล้วกลับมาเปิดใหม่" else "")) {
            open(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        if (!tester) item(s.optBoolean("notif"), "🔔", "อ่านและตอบแจ้งเตือน", "อ่าน LINE/IG/Messenger และตอบกลับจากแจ้งเตือนได้ทันที") {
            open(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        item(runtimeOk(*basic.toTypedArray()), "🎤", "ไมค์ กล้อง ปฏิทิน บลูทูธ + แจ้งเตือนของแอป", "ฟังคำสั่งเสียง ใช้กล้องจำหน้า บอกนัดวันนี้ ตรวจสถานะบลูทูธ และแสดงป๊อปอัป") {
            try { requestPermissions(basic.toTypedArray(), 1) } catch (e: Exception) {
                Bridge.log("perm: $e"); open(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkgUri()))
            }
        }
        item(s.optBoolean("battery_opt"), "🔋", "ไม่ให้ระบบปิดแอป", batteryHint()) {
            open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, pkgUri()))
        }
        if (tester) {
            box.addView(Ui.button(this, "เสร็จแล้ว กลับหน้าแชท ✨", true) { finish() }, Ui.lpm(this, t = 16, b = 24))
            return
        }
        item(Settings.canDrawOverlays(this), "🫧", "ป๊อปอัปลอยเหนือแอปอื่น", "แสดงการ์ดผู้ช่วยตอนฟัง/ตอบ/ขออนุญาต ขณะใช้แอปอื่น") {
            open(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, pkgUri()))
        }
        section("พิมพ์ได้ทุกแอป")
        item(BotIme.enabled(this), "⌨️", "คีย์บอร์ดผู้ช่วย (เปิดใช้ในระบบ)",
            "ให้ผู้ช่วยพิมพ์ในแอปที่ปกติพิมพ์ให้ไม่ได้ (เช่น บันทึก Huawei) — หน้าถัดไปเปิด 'คีย์บอร์ดผู้ช่วย AI'\n(ไม่ต้องตั้งเป็นคีย์บอร์ดหลัก ใช้คีย์บอร์ดเดิมพิมพ์ตามปกติได้)") {
            open(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        }
        item(BotIme.canSwitch(this), "🔑", "สลับคีย์บอร์ดเองได้ (ตั้งครั้งเดียวจากคอม)",
            "ให้ผู้ช่วยสลับไปคีย์บอร์ดตัวเองตอนพิมพ์ แล้วสลับกลับให้อัตโนมัติ\n" +
            "ต่อสาย USB กับคอม เปิด USB debugging แล้วรันบนคอม:\n" +
            "adb shell pm grant $packageName android.permission.WRITE_SECURE_SETTINGS") {
            val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("adb",
                "adb shell pm grant $packageName android.permission.WRITE_SECURE_SETTINGS"))
            Popups.info(this, "🔑", "คัดลอกคำสั่งแล้ว",
                "1) แท็บเล็ต: ตั้งค่า → เกี่ยวกับแท็บเล็ต → แตะ 'หมายเลขบิลด์' 7 ครั้ง\n" +
                "2) ตั้งค่า → ระบบ → ตัวเลือกสำหรับนักพัฒนา → เปิด 'การแก้ไขข้อบกพร่อง USB'\n" +
                "3) ต่อสาย USB กับคอม (ติดตั้ง Android platform-tools ไว้) กดอนุญาตบนแท็บเล็ต\n" +
                "4) รันคำสั่งที่คัดลอกไว้บนคอม:\nadb shell pm grant $packageName android.permission.WRITE_SECURE_SETTINGS\n\n" +
                "ทำครั้งเดียวพอ อยู่ถาวรจนกว่าจะถอนแอป")
        }
        section("แนะนำ")
        item(s.optBoolean("files"), "📁", "เข้าถึงไฟล์ทั้งหมด", "ส่งรูป/ไฟล์/คลิปเข้าแอปอื่น และสรุปไฟล์") {
            if (Build.VERSION.SDK_INT >= 30) open(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, pkgUri()))
            else requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE), 4)
        }
        item(s.optBoolean("write_settings"), "☀️", "ปรับความสว่าง / ตั้งค่าเครื่อง", "เพิ่ม-ลดแสง หมุนจอ เวลาปิดจอ") {
            open(Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS, pkgUri()))
        }
        item(s.optBoolean("dnd"), "🌙", "โหมดห้ามรบกวน", "เปิด/ปิดห้ามรบกวนตามคำสั่ง") {
            open(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
        }
        section("ไม่บังคับ")
        item(runtimeOk(*phone), "📞", "โทร / รับสาย / รายชื่อ / SMS", "รับ-วางสาย โทรออก หารายชื่อ ส่ง SMS") { requestPermissions(phone, 2) }
        item(runtimeOk(*loc), "📍", "ตำแหน่ง", "ตอบคำถามที่ต้องรู้ว่าอยู่ที่ไหน") { requestPermissions(loc, 3) }
        box.addView(Ui.button(this, "เสร็จแล้ว กลับหน้าแชท ✨", true) { finish() }, Ui.lpm(this, t = 16, b = 24))
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        render()
        if (grantResults.isNotEmpty() && grantResults.all { it == android.content.pm.PackageManager.PERMISSION_GRANTED })
            Popups.snack(this, "✅ ได้รับสิทธิ์แล้ว")
    }
}

/** ไฟล์ .env ภายในแอป (คีย์ที่ปิดไว้เก็บเป็น _OFF_<KEY> → บอทไม่อ่าน แต่เปิดกลับได้ไม่ต้องพิมพ์ใหม่) */
object Env {
    fun file(c: android.content.Context) = File(c.filesDir, "data/.env")

    fun load(c: android.content.Context): LinkedHashMap<String, String> {
        val m = LinkedHashMap<String, String>()
        val f = file(c)
        if (f.exists()) f.readLines().forEach { l ->
            val t = l.trim()
            if (t.isNotEmpty() && !t.startsWith("#") && t.contains("="))
                m[t.substringBefore("=").trim()] = t.substringAfter("=").trim().trim('"', '\'')
        }
        return m
    }

    /** ติดตั้งครั้งแรก + แอปมีค่าตั้งต้นของรุ่นผู้ทดลอง (GitHub Actions ใส่ให้) → คัดลอกเป็น .env (มี .env แล้วไม่แตะ) */
    fun seedTester(c: android.content.Context) {
        val f = file(c)
        if (f.exists()) return
        try {
            c.assets.open("bot/tester_defaults.env").use { inp ->
                f.parentFile?.mkdirs()
                f.writeBytes(inp.readBytes())
            }
        } catch (_: Exception) { }
    }

    /** รุ่นผู้ทดลอง: ตั้งค่าและคีย์ใส่ไว้แล้ว → ซ่อนหน้าตั้งค่า เหลือเฉพาะสิทธิ์ที่จำเป็น */
    fun tester(c: android.content.Context) = (load(c)["TESTER_MODE"] ?: "").trim() == "1"

    fun save(c: android.content.Context, m: Map<String, String>) {
        val f = file(c)
        f.parentFile?.mkdirs()
        f.writeText(m.entries.filter { it.value.isNotEmpty() }.joinToString("\n") { "${it.key}=${it.value}" } + "\n")
    }
}

/** ตั้งค่าแบบปุ่มเลือก: เปิด AI ตัวไหนก็ติ๊ก → ป๊อปอัปใส่คีย์ · เลือกตัวหลัก/ตัวสำรอง · สวิตช์เสียง/Telegram/โหมดต่างๆ */
class SettingsActivity : PageActivity() {
    private data class Prov(val id: String, val emoji: String, val name: String, val desc: String,
                            val fields: List<Popups.Field>)

    private val provs = listOf(
        Prov("claude", "🧠", "Claude", "ฉลาดสุด คุมจอแม่น (เสียเงินตามการใช้)",
            listOf(Popups.Field("ANTHROPIC_API_KEY", "คีย์ Claude (sk-ant-…)", secret = true),
                Popups.Field("CLAUDE_MODEL", "รุ่น (ว่าง = ค่าเริ่มต้น)", hint = "claude-sonnet-4-6"))),
        Prov("gemini", "✨", "Gemini", "ฟรีตามโควตา ค้นเว็บ/ดูรูป/กล้องได้ดี",
            listOf(Popups.Field("GEMINI_API_KEY", "คีย์ Gemini (aistudio.google.com)", secret = true))),
        Prov("groq", "⚡", "Groq", "ฟรี เร็ว ใช้แปลงเสียงเป็นข้อความด้วย (โควตาต่อนาทีน้อย)",
            listOf(Popups.Field("GROQ_API_KEY", "คีย์ Groq (console.groq.com)", secret = true))),
        Prov("ollama", "🖥️", "Ollama (คอมที่บ้าน)", "ฟรีไม่จำกัด ต้องเปิดคอมไว้ Wi-Fi วงเดียวกัน",
            listOf(Popups.Field("OLLAMA_URL", "ที่อยู่คอม", hint = "http://192.168.1.35:11434"),
                Popups.Field("OLLAMA_MODEL", "รุ่นโมเดล (เช่น qwen3.5:9b · qwen3.5:27b · gemma4:26b · gpt-oss:20b)", hint = "qwen3.5:9b"),
                Popups.Field("OLLAMA_VISION_MODEL", "รุ่นที่ดูรูปได้ (ว่างได้ · เช่น qwen3.5:9b, gemma4:12b)", hint = ""),
                Popups.Field("OLLAMA_API_KEY", "คีย์ Ollama Cloud (ว่างได้ · ใช้เมื่อที่อยู่เป็น https://ollama.com)", secret = true))),
        Prov("cloud", "☁️", "Cloud AI (รายเดือน)", "Chutes / NanoGPT / Synthetic · ฉลาด ดูรูปได้ สั่งงานได้ ไม่ต้องเปิดคอม",
            listOf(Popups.Field("CLOUD_API_KEY", "คีย์ (NanoGPT / Chutes / Synthetic)", secret = true),
                Popups.Field("CLOUD_MODEL", "รุ่นหลัก (ว่าง = Qwen3.5 397B แนะนำ)", hint = "Qwen/Qwen3.5-397B-A17B-TEE"),
                Popups.Field("CLOUD_MODEL_BACKUP", "รุ่นสำรอง (ว่าง = Kimi K3)", hint = "moonshotai/Kimi-K3-TEE"),
                Popups.Field("CLOUD_BASE_URL", "ที่อยู่ API (ว่าง = Chutes · NanoGPT ใส่ https://nano-gpt.com/api/v1)", hint = "https://nano-gpt.com/api/v1"))),
    )
    private lateinit var env: LinkedHashMap<String, String>
    private var dirty = false

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        page("ตั้งค่า", "แตะสวิตช์เพื่อเปิดใช้ · เก็บในเครื่องนี้เท่านั้น")
        env = Env.load(this)
        render()
    }

    override fun onPause() {
        super.onPause()
        // เดิมเริ่มผู้ช่วยใหม่เฉพาะตอนกดย้อนกลับ → กดโฮม/สลับแอป ค่าที่ตั้ง (เช่นเปลี่ยนเสียง) ไม่มีผล
        if (dirty) {
            dirty = false
            Bridge.toast("บันทึกแล้ว กำลังเริ่มผู้ช่วยใหม่…")
            Bridge.restartBot()
        }
    }

    private fun put(k: String, v: String?) {
        if (v.isNullOrBlank()) env.remove(k) else env[k] = v
        Env.save(this, env); dirty = true
    }

    private fun required(p: Prov) = p.fields.first().key
    private fun enabled(p: Prov) = !env[required(p)].isNullOrBlank()

    private fun setOn(p: Prov, on: Boolean) {
        for (f in p.fields) {
            if (on) { env["_OFF_${f.key}"]?.let { if (env[f.key].isNullOrBlank()) env[f.key] = it }; env.remove("_OFF_${f.key}") }
            else { env[f.key]?.let { env["_OFF_${f.key}"] = it }; env.remove(f.key) }
        }
        Env.save(this, env); dirty = true
        val primary = env["LLM_PROVIDER"] ?: "claude"
        if (!on && primary == p.id) provs.firstOrNull { enabled(it) }?.let { put("LLM_PROVIDER", it.id) }
        if (on && provs.none { it.id == primary && enabled(it) }) put("LLM_PROVIDER", p.id)
    }

    private fun askKeys(p: Prov, then: (Boolean) -> Unit) {
        val fs = p.fields.map { it.copy(value = env[it.key] ?: env["_OFF_${it.key}"] ?: "") }
        Popups.form(this, p.emoji, "เปิดใช้ ${p.name}", p.desc, fs, onCancel = { then(false) }) { vals ->
            if (vals[required(p)].isNullOrBlank()) { Popups.snack(this, "ต้องใส่ ${p.fields.first().label}"); then(false); return@form }
            vals.forEach { (k, v) -> put(k, v) }
            setOn(p, true); then(true)
            Popups.snack(this, "✅ เปิดใช้ ${p.name} แล้ว")
        }
    }

    private fun applyPreset() {
        fun has(k: String) = !env[k].isNullOrBlank()
        val done = ArrayList<String>()
        val brain = when {
            has("CLOUD_API_KEY") -> "cloud"; has("ANTHROPIC_API_KEY") -> "claude"
            has("GEMINI_API_KEY") -> "gemini"; has("GROQ_API_KEY") -> "groq"; else -> null
        }
        if (brain == null) { Popups.snack(this, "ยังไม่ได้ใส่คีย์ AI ตัวไหนเลย"); return }
        put("LLM_PROVIDER", brain); done.add("สมอง: $brain")
        val fb = listOf("groq", "gemini", "cloud").firstOrNull { it != brain && has(mapOf("groq" to "GROQ_API_KEY",
            "gemini" to "GEMINI_API_KEY", "cloud" to "CLOUD_API_KEY")[it]!!) } ?: "none"
        put("LLM_FALLBACK", fb); done.add("สำรอง: $fb")
        val stt = when {
            has("GROQ_API_KEY") -> "groq"; has("CF_API_TOKEN") -> "cloudflare"
            has("CLOUD_API_KEY") && (env["CLOUD_BASE_URL"] ?: "").contains("nano-gpt") -> "nano"; else -> "auto"
        }
        put("STT_PROVIDER", stt); done.add("ถอดเสียง: $stt")
        put("TTS_ENGINE", "edge"); done.add("เสียงพูด: Microsoft → Google")
        render()
        Popups.info(this, "✨", "ใช้ค่าแนะนำแล้ว", done.joinToString("\n") + "\n\nกดย้อนกลับเพื่อเริ่มผู้ช่วยใหม่")
    }

    private fun askCloudflare(then: (Boolean) -> Unit) {
        val fs = listOf(
            Popups.Field("CF_ACCOUNT_ID", "Account ID (หน้าแรก dash.cloudflare.com)", env["CF_ACCOUNT_ID"] ?: ""),
            Popups.Field("CF_API_TOKEN", "API Token (My Profile → API Tokens → เทมเพลต Workers AI)", env["CF_API_TOKEN"] ?: "", secret = true))
        Popups.form(this, "☁️", "ถอดเสียงด้วย Cloudflare", "ฟรีวันละประมาณ 200 นาทีเสียง (Whisper Large v3 Turbo)", fs,
            onCancel = { then(false) }) { vals ->
            if (vals["CF_ACCOUNT_ID"].isNullOrBlank() || vals["CF_API_TOKEN"].isNullOrBlank()) {
                Popups.snack(this, "ต้องใส่ทั้ง Account ID และ API Token"); then(false); return@form
            }
            vals.forEach { (k, v) -> put(k, v.trim()) }
            Popups.snack(this, "✅ ใช้ Cloudflare ถอดเสียงแล้ว"); then(true)
        }
    }

    private fun switchRow(title: String, desc: String, checked: Boolean, onChange: (Switch, Boolean) -> Unit): View {
        val r = Ui.row(this)
        val tc = Ui.col(this, 0)
        tc.addView(Ui.text(this, title, 15.5f, true))
        if (desc.isNotEmpty()) tc.addView(Ui.text(this, desc, 12.5f, false, Ui.SUB))
        r.addView(tc, Ui.lp(0, weight = 1f))
        val sw = Switch(this)
        sw.isChecked = checked
        sw.setOnCheckedChangeListener { v, on -> onChange(v as Switch, on) }
        r.addView(sw)
        r.setPadding(0, Ui.dp(this, 6), 0, Ui.dp(this, 6))
        return r
    }

    private fun card(): LinearLayout = Ui.card(this, 16, 20).also { box.addView(it, Ui.lpm(this, b = 10)) }

    private fun render() {
        box.removeAllViews()
        // ---------------------------------------------------------------- AI
        val pc = card()
        pc.addView(Ui.text(this, "✨ ค่าแนะนำ (เสถียร + เร็ว)", 15f, true))
        pc.addView(Ui.text(this, "ใช้อย่างละตัวเดียว: สมอง Cloud AI · สำรอง Groq · ถอดเสียง Groq · เสียงพูด Microsoft→Google", 12.5f, false, Ui.SUB), Ui.lpm(this, t = 4))
        pc.addView(Ui.button(this, "ใช้ค่าแนะนำ", true) { applyPreset() }, Ui.lpm(this, t = 8))
        section("🧠 สมอง AI — ติ๊กเปิดตัวที่จะใช้")
        val primary = env["LLM_PROVIDER"] ?: "claude"
        for (p in provs) {
            val c = card()
            val on = enabled(p)
            c.addView(switchRow("${p.emoji} ${p.name}", p.desc, on) { sw, want ->
                if (want && !on) askKeys(p) { ok -> sw.isChecked = ok; if (ok) render() }
                else if (!want && on) { setOn(p, false); render() }
            })
            if (on) {
                val r = Ui.row(this)
                r.addView(Ui.segmented(this, listOf("main" to (if (primary == p.id) "⭐ ตัวหลัก" else "ตั้งเป็นตัวหลัก")),
                    if (primary == p.id) "main" else "") { put("LLM_PROVIDER", p.id); render() })
                r.addView(View(this), Ui.lp(0, weight = 1f))
                r.addView(Ui.chip(this, "✏️ แก้คีย์") { askKeys(p) { render() } })
                c.addView(r, Ui.lpm(this, t = 6))
            }
        }
        val fbOpts = listOf("none" to "ไม่ใช้สำรอง") + provs.filter { enabled(it) && it.id != primary }.map { it.id to it.name }
        val fc = card()
        fc.addView(Ui.text(this, "🛟 AI สำรอง (เมื่อตัวหลักใช้ไม่ได้)", 15f, true))
        fc.addView(HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            addView(Ui.segmented(this@SettingsActivity, fbOpts, env["LLM_FALLBACK"] ?: "none") { put("LLM_FALLBACK", it) })
        }, Ui.lpm(this, t = 8))

        // ---------------------------------------------------------------- เสียง
        section("🎤 เสียง")
        val vc = card()
        val nanoStt = !env["CLOUD_API_KEY"].isNullOrBlank() && (env["CLOUD_BASE_URL"] ?: "").contains("nano-gpt")
        val cfStt = !env["CF_ACCOUNT_ID"].isNullOrBlank() && !env["CF_API_TOKEN"].isNullOrBlank()
        vc.addView(switchRow("ผู้ช่วยเสียง", "พูด \"เฮ้ย ผู้ช่วย\" สั่งงานได้ (แปลงเสียงด้วย Cloudflare / Groq / NanoGPT)",
            env["VOICE_AUTOSTART"] != "0") { sw, on ->
            if (on && env["GROQ_API_KEY"].isNullOrBlank() && !nanoStt && !cfStt) {
                askKeys(provs.first { it.id == "groq" }) { ok -> sw.isChecked = ok; if (ok) put("VOICE_AUTOSTART", "1") }
            } else put("VOICE_AUTOSTART", if (on) "1" else "0")
        })
        vc.addView(Ui.text(this, "แปลงเสียงเป็นข้อความด้วย", 13f, true), Ui.lpm(this, t = 8))
        vc.addView(HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            addView(Ui.segmented(this@SettingsActivity, listOf("auto" to "อัตโนมัติ", "cloudflare" to "☁️ Cloudflare (ฟรี)",
                "groq" to "⚡ Groq (ฟรี)", "nano" to "💎 NanoGPT (~฿0.02/นาที)"), env["STT_PROVIDER"] ?: "auto") { v ->
                when {
                    v == "nano" && !nanoStt -> Popups.snack(this@SettingsActivity, "ต้องเปิด ☁️ Cloud AI ด้วยคีย์ NanoGPT ก่อน")
                    v == "cloudflare" -> askCloudflare { ok -> if (ok) put("STT_PROVIDER", "cloudflare") }
                    else -> put("STT_PROVIDER", v)
                }
            })
        }, Ui.lpm(this, t = 6))
        if (!env["CF_API_TOKEN"].isNullOrBlank())
            vc.addView(Ui.chip(this, "✏️ แก้คีย์ Cloudflare") { askCloudflare { } }, Ui.lpm(this, t = 6))
        vc.addView(switchRow("🫧 ปุ่มลอยเหนือแอปอื่น", "แตะปุ่ม 🤖 เพื่อพิมพ์คุย และเปิด/ปิดไมค์สั่งเสียง ขณะอยู่ในแอปอื่น",
            Floaty.enabled(this)) { sw, on ->
            if (on && !Floaty.allowed(this)) {
                sw.isChecked = false
                Popups.snack(this, "อนุญาต \"แสดงเหนือแอปอื่น\" ก่อน แล้วเปิดอีกครั้ง")
                startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            } else {
                Floaty.setEnabled(this, on)
                if (on) Floaty.pause()
            }
            Unit
        })
        vc.addView(switchRow("ถอดคำสั่งด้วยระบบเสียงของเครื่อง (Google)",
            if (GoogleStt.available()) "ฟรี แม่นกับภาษาไทย เหมือนปุ่มไมค์ในคีย์บอร์ด"
            else "เครื่องนี้ไม่มีระบบเสียงของ Google — ใช้ตัวถอดเสียงเดิมอัตโนมัติ",
            env["GOOGLE_STT"] != "0") { _, on -> put("GOOGLE_STT", if (on) "1" else "0") })
        vc.addView(switchRow("ฟังตลอด (ไม่ต้องเรียกชื่อ)", "สะดวกแต่อาจได้ยินเสียงรอบข้างผิดได้", env["ALWAYS_LISTEN"] == "1") { _, on ->
            put("ALWAYS_LISTEN", if (on) "1" else "0")
        })
        vc.addView(switchRow("ต้องเรียก \"เฮ้ยผู้ช่วย\" ทุกคำสั่ง", "ปิด = ตอบแล้วฟังคำสั่งต่อเองอีก 15 วินาที", env["WAKE_EACH_TIME"] == "1") { _, on ->
            put("WAKE_EACH_TIME", if (on) "1" else "0")
        })
        vc.addView(Ui.text(this, "ความเข้มงวดในการฟัง (กันเสียงรบกวน)", 13f, true), Ui.lpm(this, t = 8))
        vc.addView(Ui.segmented(this, listOf("0.3" to "ไว", "0.4" to "ปกติ", "0.6" to "เข้ม", "0.9" to "เข้มมาก"),
            env["VOICE_MIN_SPEECH"] ?: "0.4") { put("VOICE_MIN_SPEECH", it) }, Ui.lpm(this, t = 6))
        vc.addView(Ui.text(this, "เสียงพูดของผู้ช่วย", 13f, true), Ui.lpm(this, t = 10))
        val curVoice = if (env["TTS_ENGINE"] == "gemini") "gemini" else (env["TTS_VOICE"] ?: "th-TH-NiwatNeural")
        vc.addView(Ui.segmented(this, listOf("th-TH-NiwatNeural" to "👨 ชาย", "th-TH-PremwadeeNeural" to "👩 หญิง",
            "gemini" to "✨ Gemini (เหมือนคนสุด)"), curVoice) { v ->
            if (v == "gemini") {
                if (env["GEMINI_API_KEY"].isNullOrBlank()) askKeys(provs.first { it.id == "gemini" }) { ok -> if (ok) put("TTS_ENGINE", "gemini") }
                else put("TTS_ENGINE", "gemini")
            } else { put("TTS_ENGINE", "edge"); put("TTS_VOICE", v); put("BOT_GENDER", if (v.contains("Premwadee")) "female" else "male") }
        }, Ui.lpm(this, t = 6))
        vc.addView(Ui.text(this, "ความเร็วพูด", 13f, true), Ui.lpm(this, t = 10))
        vc.addView(Ui.segmented(this, listOf("+0%" to "ช้า", "+10%" to "ปกติ", "+20%" to "เร็ว", "+30%" to "เร็วมาก"),
            env["TTS_RATE"] ?: "+10%") { put("TTS_RATE", it) }, Ui.lpm(this, t = 6))

        // ---------------------------------------------------------------- ทำงานไม่ต้องรอ
        section("⚡ ทำงานไม่ต้องรอถาม")
        val autoCard = card()
        autoCard.addView(switchRow("กดอนุญาตสิทธิ์ให้แอปอัตโนมัติ", "ระหว่างผู้ช่วยทำงาน ถ้าแอปขอสิทธิ์ (กล้อง/ไมค์/รูป/ตำแหน่ง) กดอนุญาตให้เลย",
            env["AUTO_ALLOW_PERMS"] != "0") { _, on -> put("AUTO_ALLOW_PERMS", if (on) "1" else "0") })
        autoCard.addView(switchRow("👀 โหมดมองจอ", "งานยากในแอป ผู้ช่วยดูภาพหน้าจอจริงทีละขั้น (แม่นกว่า แต่ช้ากว่าขั้นละ 2-4 วินาที)",
            env["VISION_MODE"] != "0") { _, on -> put("VISION_MODE", if (on) "1" else "0") })
        autoCard.addView(switchRow("ส่งข้อความได้เลย", "ส่ง/โพสต์/แชร์ตามที่สั่ง ไม่ต้องกดยืนยัน",
            env["AUTO_SEND"] != "0") { _, on -> put("AUTO_SEND", if (on) "1" else "0") })
        autoCard.addView(switchRow("โทรได้เลย", "สั่งโทรหาใคร โทรทันทีไม่ต้องกดยืนยัน",
            env["AUTO_CALL"] == "1") { _, on -> put("AUTO_CALL", if (on) "1" else "0") })
        autoCard.addView(Ui.text(this, "จ่ายเงิน/โอน/ซื้อ/ลบ ยังถามก่อนเสมอ เพื่อความปลอดภัย", 12.5f, false, Ui.SUB), Ui.lpm(this, t = 4))

        // ---------------------------------------------------------------- ปฏิทิน
        section("📅 Google Calendar")
        val gc = card()
        gc.addView(Ui.text(this, if (env["GCAL_URL"].isNullOrBlank())
            "ยังไม่ได้เชื่อม — นัดหมาย/บันทึกงานจะเปิดหน้าสร้างนัดของแอปปฏิทินให้กดบันทึกเอง"
            else "✅ เชื่อมแล้ว — พูด \"สร้างนัด\" หรือ \"บันทึกงาน\" ได้เลย นัดขึ้น Google Calendar ทันที", 13f))
        gc.addView(Ui.button(this, "🔗 เชื่อม Google Calendar") {
            Popups.form(this, "📅", "เชื่อม Google Calendar",
                "1) เปิด script.google.com → โปรเจกต์ใหม่ → วางโค้ดจากไฟล์ google_calendar_script.gs  " +
                "2) ตั้งรหัสลับในโค้ด  3) Deploy → New deployment → Web app → Execute as: Me, Who has access: Anyone  " +
                "4) คัดลอก URL ที่ลงท้าย /exec มาใส่",
                listOf(Popups.Field("GCAL_URL", "Web app URL (ลงท้าย /exec)", env["GCAL_URL"] ?: "", hint = "https://script.google.com/macros/s/…/exec"),
                    Popups.Field("GCAL_SECRET", "รหัสลับ (ตรงกับในโค้ด)", env["GCAL_SECRET"] ?: "", true))) { v ->
                v.forEach { (k, x) -> put(k, x.trim()) }
                Popups.snack(this, "บันทึกแล้ว — ลองพูด \"ทดสอบปฏิทิน\"")
            }
        }, Ui.lpm(this, t = 8))

        // ---------------------------------------------------------------- อัปเดต
        section("🔄 อัปเดตแอป (ไม่ต้องถอน)")
        val uc = card()
        uc.addView(Ui.text(this, "ดึงเวอร์ชันใหม่จาก GitHub Releases แล้วติดตั้งทับ — คีย์/ความจำ/การตั้งค่าอยู่ครบ", 13f))
        uc.addView(Ui.button(this, "📝 ตั้งค่า repo GitHub") {
            Popups.form(this, "🔄", "อัปเดตจาก GitHub", "repo Private ต้องใส่ token (สร้างที่ GitHub → Settings → Developer settings → Fine-grained token → สิทธิ์ Contents: Read)",
                listOf(Popups.Field("UPDATE_REPO", "ชื่อ repo", env["UPDATE_REPO"] ?: "", hint = "ชื่อบัญชี/ai-assistant"),
                    Popups.Field("UPDATE_TOKEN", "token (ว่างได้ถ้า repo Public)", env["UPDATE_TOKEN"] ?: "", true))) { v ->
                v.forEach { (k, x) -> put(k, x) }
            }
        }, Ui.lpm(this, t = 8))
        uc.addView(Ui.button(this, "🔍 ตรวจเวอร์ชันใหม่ตอนนี้") { Env.save(this, env); Updater.check(this, true) }, Ui.lpm(this, t = 6))

        // ---------------------------------------------------------------- Telegram
        section("💬 Telegram")
        val tc = card()
        val tgOn = !env["TELEGRAM_BOT_TOKEN"].isNullOrBlank()
        tc.addView(switchRow("สั่งผ่าน Telegram", "คุยกับผู้ช่วยจากที่ไหนก็ได้", tgOn) { sw, on ->
            if (on) {
                Popups.form(this, "💬", "เชื่อม Telegram", "ใส่ token จาก @BotFather และ Telegram ID ของคุณ",
                    listOf(Popups.Field("TELEGRAM_BOT_TOKEN", "Bot token", env["TELEGRAM_BOT_TOKEN"] ?: env["_OFF_TELEGRAM_BOT_TOKEN"] ?: "", true),
                        Popups.Field("ALLOWED_USER_IDS", "Telegram ID ของคุณ", env["ALLOWED_USER_IDS"] ?: "")),
                    onCancel = { sw.isChecked = false }) { v ->
                    v.forEach { (k, x) -> put(k, x) }; env.remove("_OFF_TELEGRAM_BOT_TOKEN"); Env.save(this, env)
                }
            } else {
                env["TELEGRAM_BOT_TOKEN"]?.let { env["_OFF_TELEGRAM_BOT_TOKEN"] = it }
                put("TELEGRAM_BOT_TOKEN", null)
            }
        })

        // ---------------------------------------------------------------- ความคิด / ความจำ / กล้อง
        section("💭 ความคิดและความจำ")
        val mc = card()
        mc.addView(switchRow("มีความคิดของตัวเอง", "ทักทายตอนเช้า เตือนแบตต่ำ/ฝนตก ชวนพักตอนดึก ฯลฯ", env["MIND_ENABLED"] != "0") { _, on ->
            put("MIND_ENABLED", if (on) "1" else "0")
        })
        mc.addView(switchRow("จำเรื่องของฉันเอง", "จำชื่อ ความชอบ นัดหมาย จากที่คุยกัน (เก็บในเครื่อง)", env["MEMORY_AUTO"] != "0") { _, on ->
            put("MEMORY_AUTO", if (on) "1" else "0")
        })
        mc.addView(switchRow("📷 จำหน้าเจ้าของ", "ใช้กล้องหน้าทักทาย/ยืนยันว่าเป็นคุณ (ต้องสอนหน้าก่อนในเมนู 🧰)", env["FACE_ENABLED"] == "1") { _, on ->
            put("FACE_ENABLED", if (on) "1" else "0")
        })

        // ---------------------------------------------------------------- ซ่อมตัวเอง
        section("🛠️ ซ่อมตัวเอง")
        val hc = card()
        hc.addView(Ui.text(this, "เมื่อเจอบัค", 13f, true))
        hc.addView(Ui.segmented(this, listOf("ask" to "ถามก่อนแก้", "auto" to "แก้เองอัตโนมัติ", "off" to "ปิด"),
            env["SELF_REPAIR"] ?: "ask") { put("SELF_REPAIR", it) }, Ui.lpm(this, t = 6))

        // ---------------------------------------------------------------- การแสดงผล
        section("✨ การแสดงผล")
        val prefs = getSharedPreferences("app", MODE_PRIVATE)
        val dc = card()
        dc.addView(switchRow("ป๊อปอัปลอย / แผงผู้ช่วย", "แสดงตอนฟัง/ตอบขณะใช้แอปอื่น", prefs.getBoolean("popup", true)) { _, on ->
            prefs.edit().putBoolean("popup", on).apply()
        })
        dc.addView(switchRow("เปิดเครื่องแล้วเริ่มเอง", "", prefs.getBoolean("autostart", true)) { _, on ->
            prefs.edit().putBoolean("autostart", on).apply()
        })

        // ---------------------------------------------------------------- ขั้นสูง
        section("⚙️ ขั้นสูง")
        val ac = card()
        ac.addView(Ui.text(this, "วางไฟล์ .env ทั้งไฟล์ (จาก Termux) หรือ KEY=VALUE", 13f, true))
        val paste = Ui.input(this, "KEY=VALUE ทีละบรรทัด", multi = true).apply { minLines = 3 }
        ac.addView(paste, Ui.lpm(this, t = 6, b = 8))
        ac.addView(Ui.button(this, "นำเข้า") {
            paste.text.toString().lines().forEach { l ->
                val t = l.trim()
                if (t.isNotEmpty() && !t.startsWith("#") && t.contains("="))
                    env[t.substringBefore("=").trim()] = t.substringAfter("=").trim().trim('"', '\'')
            }
            Env.save(this, env); dirty = true; paste.setText(""); render()
            Popups.snack(this, "📋 นำเข้าแล้ว")
        })
        box.addView(Ui.button(this, "💾 ใช้การตั้งค่า (เริ่มผู้ช่วยใหม่)", true) {
            dirty = false
            Popups.snack(this, "💾 กำลังเริ่มผู้ช่วยใหม่…")
            box.postDelayed({ Bridge.restartBot() }, 900)
        }, Ui.lpm(this, t = 14, b = 28))
    }
}

/** ดู log + ประวัติการซ่อม + ปุ่มซ่อม/ย้อน/คืนค่าโค้ด */
class LogActivity : PageActivity() {
    private lateinit var tv: TextView

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        page("บันทึกการทำงาน", "ประวัติการซ่อม + log ล่าสุด")
        val r = Ui.row(this)
        fun add(t: String, primary: Boolean = false, f: () -> Unit) =
            r.addView(Ui.button(this, t, primary, f), Ui.lpm(this, w = LinearLayout.LayoutParams.WRAP_CONTENT, e = 8))
        add("🔄 รีเฟรช") { load() }
        add("🛠️ ซ่อมบัค", true) { py("ซ่อมบัค") }
        add("↩️ ย้อนการซ่อม") { py("ย้อนการซ่อม") }
        add("⏪ ย้อนเวอร์ชัน") {
            android.app.AlertDialog.Builder(this).setMessage("ย้อนโค้ดผู้ช่วยกลับเป็นชุดก่อนอัปเดตครั้งล่าสุด? (ใช้เมื่ออัปเดตแล้วมีปัญหา)")
                .setPositiveButton("ย้อน") { _, _ -> py("__rollback__") }
                .setNegativeButton("ไม่", null).show()
        }
        add("📊 สรุปผล") { py("สรุปผลทดสอบ") }
        add("🔊 ทดสอบเสียง") { py("ทดสอบเสียง") }
        add("🎤 รายงานไมค์") { py("รายงานไมค์") }
        add("♻️ คืนค่าโค้ด") {
            android.app.AlertDialog.Builder(this).setMessage("คืนโค้ดบอทเป็นเวอร์ชันที่มากับแอป (ยกเลิกการซ่อม/ปรับปรุงทั้งหมด)?")
                .setPositiveButton("คืนค่า") { _, _ -> py("__factory__") }
                .setNegativeButton("ไม่", null).show()
        }
        box.addView(android.widget.HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(r) })
        val card = Ui.card(this, 14, 18)
        card.background = Ui.round(0xFF1E1433.toInt(), Ui.dpf(this, 18f))
        tv = Ui.text(this, "กำลังโหลด…", 11f, false, 0xFFE9E3FF.toInt(), keepEmoji = true).apply {
            typeface = Typeface.MONOSPACE; setTextIsSelectable(true)
        }
        card.addView(tv)
        box.addView(card, Ui.lpm(this, t = 12, b = 20))
        load()
    }

    private fun tail(name: String, n: Int): String {
        val f = File(filesDir, "data/$name")
        if (!f.exists()) return ""
        return "===== $name =====\n" + f.readLines().takeLast(n).joinToString("\n") + "\n\n"
    }

    private fun load() {
        Thread {
            val hist = try {
                App.py(this).getModule("android_main").callAttr("heal_history").toString()
            } catch (e: Throwable) { "" }
            val t = hist + "\n\n" + tail("bot.log", 150) + tail("voice.log", 80) + tail("app.log", 80)
            runOnUiThread { tv.text = t }
        }.start()
    }

    private fun py(cmd: String) {
        Popups.snack(this, "⏳ กำลังทำ… ผลจะขึ้นในหน้าแชท")
        Thread {
            try {
                val res = App.py(this).getModule("android_main").callAttr("chat", cmd).toString()
                ChatLog.add("bot", res)
                runOnUiThread { Popups.info(this, "🛠️", "ผลการทำงาน", res.take(1200)) }
            } catch (e: Throwable) {
                ChatLog.add("bot", "❗ $e")
            }
            runOnUiThread { load() }
        }.start()
    }
}
