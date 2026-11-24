package com.aibot.assistant

import android.animation.Animator
import android.app.Activity
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/** หน้าหลัก: แชทกับผู้ช่วย (ธีมม่วง-ขาว) + ไมค์ + ทางลัด + ป๊อปอัป */
class MainActivity : Activity() {
    companion object {
        @Volatile var visible = false
        @Volatile var current: MainActivity? = null
    }

    private lateinit var list: LinearLayout
    private lateinit var scroll: ScrollView
    private lateinit var subtitle: TextView
    private lateinit var chips: LinearLayout
    private lateinit var input: EditText
    private lateinit var micBtn: TextView
    private lateinit var micHost: FrameLayout
    private lateinit var typing: LinearLayout
    private lateinit var typingText: TextView
    private lateinit var orb: View
    private lateinit var power: View
    private var micAnims: List<Animator> = emptyList()
    private val worker = Executors.newSingleThreadExecutor()
    private val busy = AtomicInteger(0)
    private val listener: () -> Unit = { render(); if (enrolling) onEnrollProgress() }
    private val rendered = ArrayList<ChatLog.Msg>()
    private val dialogs = HashMap<Int, Dialog>()
    private val timeFmt = SimpleDateFormat("HH:mm", Locale.US)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        Env.seedTester(this)                  // รุ่นผู้ทดลอง: ตั้งค่า + คีย์มาให้แล้ว (ก่อนบอทเริ่ม)
        Ui.statusBar(this, Ui.P700)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Ui.P50) }
        root.addView(buildHeader())
        root.addView(buildQuick())

        scroll = ScrollView(this).apply { isVerticalScrollBarEnabled = false; isFillViewport = true }
        list = Ui.col(this, 14)
        scroll.addView(list)
        root.addView(scroll, Ui.lp(h = 0, weight = 1f))

        // กำลังคิด… (จุดเด้ง)
        typing = Ui.row(this).apply { visibility = View.GONE; setPadding(Ui.dp(this@MainActivity, 22), 0, 0, Ui.dp(this@MainActivity, 6)) }
        val (dots, _) = Fx.typingDots(this)
        typing.addView(dots)
        typingText = Ui.text(this, "กำลังคิด…", 13f, false, Ui.SUB).apply { setPadding(Ui.dp(this@MainActivity, 6), 0, 0, 0) }
        typing.addView(typingText)
        root.addView(typing)

        root.addView(buildInput())
        setContentView(root)

        val prefs = getSharedPreferences("app", MODE_PRIVATE)
        if (!prefs.getBoolean("setup_seen", false)) {
            prefs.edit().putBoolean("setup_seen", true).apply()
            startActivity(Intent(this, SetupActivity::class.java))
        }
        BotService.start(this)
    }

    // ------------------------------------------------------------------ หัว
    private fun buildHeader(): View {
        val head = Ui.col(this, 0)
        head.setBackgroundColor(Ui.P50)                   // หัวแบบเรียบ (ดีไซน์ใหม่)
        head.setPadding(Ui.dp(this, 18), Ui.dp(this, 16), Ui.dp(this, 14), Ui.dp(this, 10))

        val r = Ui.row(this)
        orb = android.widget.ImageView(this).apply {
            setImageResource(R.drawable.ic_launcher)       // โลโก้แบบ B
            contentDescription = "ผู้ช่วย AI"
            clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: View, o: android.graphics.Outline) {
                    o.setRoundRect(0, 0, v.width, v.height, Ui.dpf(this@MainActivity, 12f))
                }
            }
        }
        r.addView(orb, LinearLayout.LayoutParams(Ui.dp(this, 46), Ui.dp(this, 46)).apply { marginEnd = Ui.dp(this@MainActivity, 12) })
        val tt = Ui.col(this, 0)
        tt.addView(Ui.text(this, "ผู้ช่วย AI", 21f, true, Ui.TEXT))
        subtitle = Ui.text(this, "พร้อมรับคำสั่ง", 13.5f, false, Ui.OK).apply { maxLines = 2 }
        tt.addView(subtitle)
        r.addView(tt, Ui.lp(0, weight = 1f))
        power = Ui.iconRes(this, R.drawable.ic_ui_power, "เปิด/ปิดผู้ช่วย") {
            val on = !Bridge.isEnabled()
            Bridge.setEnabled(on)
            Popups.snack(this, if (on) "▶️ เปิดผู้ช่วยแล้ว" else "⏸️ ปิดผู้ช่วยแล้ว (ไม่ฟังไมค์ ไม่ทำงานเบื้องหลัง)")
            refreshStatus()
        }
        r.addView(power)
        if (!Env.tester(this)) r.addView(Ui.iconRes(this, R.drawable.ic_ui_settings, "ตั้งค่า") {
            startActivity(Intent(this, SettingsActivity::class.java)) })
        r.addView(Ui.iconRes(this, R.drawable.ic_ui_more, "เมนูเพิ่มเติม") { menu() })
        head.addView(r)

        chips = Ui.row(this)
        val hs = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(chips) }
        head.addView(hs, Ui.lpm(this, t = 12))

        // คำสั่งด่วน (ดีไซน์ใหม่): แตะ = ใส่คำขึ้นต้นในช่องพิมพ์ให้พิมพ์ต่อ / บางอันสั่งเลย
        val quick = Ui.row(this)
        fun q(icon: Int, label: String, fill: String?, run: String? = null) {
            val c = Ui.chip(this, label) {
                if (run != null) { send(run); return@chip }
                input.setText(fill ?: ""); input.setSelection(input.text.length); input.requestFocus()
                (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager)
                    .showSoftInput(input, 0)
            }
            getDrawable(icon)?.let { d ->
                val s = Ui.dp(this, 18); d.setBounds(0, 0, s, s)
                c.setCompoundDrawablesRelative(d, null, null, null)
                c.compoundDrawablePadding = Ui.dp(this, 6)
            }
            c.minHeight = Ui.dp(this, 40); c.gravity = Gravity.CENTER_VERTICAL
            quick.addView(c, Ui.lpm(this, w = ViewGroup.LayoutParams.WRAP_CONTENT, e = 8))
        }
        q(R.drawable.ic_ui_sun, "สรุปวันนี้", null, run = "สรุปวันนี้")
        q(R.drawable.ic_ui_routine, "รูทีน", null, run = "มีรูทีนอะไรบ้าง")
        q(R.drawable.ic_ui_alarm, "ปลุก", "ปลุก ")
        q(R.drawable.ic_ui_timer, "จับเวลา", "จับเวลา ")
        q(R.drawable.ic_ui_bell, "เตือน", "เตือนให้ ")
        q(R.drawable.ic_ui_chat, "ส่ง LINE", "ส่งไลน์หา ")
        q(R.drawable.ic_ui_music, "เปิดเพลง", "เปิดเพลง ")
        q(R.drawable.ic_ui_calendar, "นัดวันนี้", null, run = "วันนี้มีนัดอะไรบ้าง")
        val qs = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(quick) }
        head.addView(qs, Ui.lpm(this, t = 8))
        return head
    }

    // ------------------------------------------------------------------ แผงควบคุมเครื่อง (อยู่ในหน้าแชท)
    private val tiles = LinkedHashMap<String, android.widget.ImageView>()
    @Volatile private var torchOn = false

    private fun tile(parent: LinearLayout, emoji: String, label: String, kind: String? = null, onTap: () -> Unit) {
        val a = this
        val col = Ui.col(a, 0).apply { gravity = Gravity.CENTER_HORIZONTAL }
        val ic = Ui.iconTile(a, emoji, 54, Ui.TEXT, Color.WHITE).apply {
            background = Ui.round(Color.WHITE, Ui.dpf(a, 18f), Ui.P200, Ui.dp(a, 1))
            contentDescription = label; importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
            isClickable = true
            setOnClickListener { Fx.press(this); onTap() }
        }
        col.addView(ic, LinearLayout.LayoutParams(Ui.dp(a, 54), Ui.dp(a, 54)))
        col.addView(Ui.text(a, label, 11.5f, false, Ui.SUB).apply { gravity = Gravity.CENTER; maxLines = 1 }, Ui.lpm(a, t = 5))
        parent.addView(col, LinearLayout.LayoutParams(Ui.dp(a, 72), ViewGroup.LayoutParams.WRAP_CONTENT))
        if (kind != null) tiles[kind] = ic
    }

    private fun paintTile(v: android.widget.ImageView, on: Boolean) {
        val r = Ui.dpf(this, 18f)
        v.background = if (on) Ui.round(Ui.P500, r) else Ui.round(Color.WHITE, r, Ui.P200, Ui.dp(this, 1))
        v.imageTintList = android.content.res.ColorStateList.valueOf(if (on) Color.WHITE else Ui.TEXT)
    }

    private fun refreshTiles() {
        Thread {
            val st = tiles.keys.associateWith { k -> if (k == "torch") (if (torchOn) "1" else "0") else try { Bridge.sysState(k) } catch (_: Throwable) { "" } }
            runOnUiThread { for ((k, v) in tiles) paintTile(v, st[k] == "1") }
        }.start()
    }

    private fun toggle(kind: String, name: String) {
        Thread {
            val on = try { Bridge.sysState(kind) == "1" } catch (_: Throwable) { false }
            runOnUiThread { send((if (on) "ปิด " else "เปิด ") + name) }
        }.start()
    }

    private fun buildQuick(): View {
        val q = Ui.row(this)
        q.setPadding(Ui.dp(this, 10), Ui.dp(this, 12), Ui.dp(this, 10), Ui.dp(this, 4))
        tile(q, "📶", "Wi-Fi", "wifi") { toggle("wifi", "wifi") }
        tile(q, "🔷", "บลูทูธ", "bluetooth") { toggle("bluetooth", "บลูทูธ") }
        tile(q, "🔄", "หมุนจอ", "rotate") { toggle("rotate", "หมุนจออัตโนมัติ") }
        tile(q, "🌙", "ห้ามรบกวน", "dnd") { toggle("dnd", "ห้ามรบกวน") }
        tile(q, "🔦", "ไฟฉาย", "torch") { torchOn = !torchOn; send(if (torchOn) "เปิดไฟฉาย" else "ปิดไฟฉาย") }
        tile(q, "📍", "ตำแหน่ง", "location") { toggle("location", "ตำแหน่ง") }
        tile(q, "🔆", "สว่างขึ้น") { send("เพิ่มความสว่าง") }
        tile(q, "🔅", "มืดลง") { send("ลดความสว่าง") }
        tile(q, "🔊", "เสียงดัง") { send("เพิ่มเสียง") }
        tile(q, "🔉", "เสียงเบา") { send("ลดเสียง") }
        tile(q, "🔋", "แบต") { send("แบตเหลือเท่าไหร่") }
        tile(q, "🌤️", "อากาศ") { send("อากาศวันนี้") }
        tile(q, "🔔", "แจ้งเตือน") { send("มีแจ้งเตือนอะไรบ้าง") }
        tile(q, "📱", "อยู่หน้าไหน") { send("อยู่หน้าไหน") }
        return HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(q) }
    }

    // ------------------------------------------------------------------ ปุ่ม ➕ : ทุกเครื่องมือในแผ่นเดียว
    private fun pyTool(name: String, arg: String = "") {
        busy.incrementAndGet(); render()
        worker.execute {
            try {
                val r = App.py(this).getModule("android_main").callAttr("tool", name, arg).toString()
                if (r.isNotBlank()) ChatLog.add("bot", r)
            } catch (e: Throwable) { ChatLog.add("bot", "❗ ${e.message?.take(200)}") }
            finally { busy.decrementAndGet(); runOnUiThread { render() } }
        }
    }

    private fun t(emoji: String, label: String, fn: () -> Unit): Triple<String, String, () -> Unit> = Triple(emoji, label, fn)

    private fun actions() {
        val a = this
        Popups.panel(a, "✨", "ทำอะไรดี") { card, dlg ->
            val sv = ScrollView(a)
            val body = Ui.col(a, 0)
            sv.addView(body)
            fun section(t: String, items: List<Triple<String, String, () -> Unit>>) {
                body.addView(Ui.text(a, t, 13f, true, Ui.P600), Ui.lpm(a, t = 10, b = 4))
                var row: LinearLayout? = null
                items.forEachIndexed { i, (emo, lab, fn) ->
                    if (i % 4 == 0) { row = Ui.row(a); body.addView(row) }
                    tile(row!!, emo, lab) { dlg.dismiss(); fn() }
                }
            }
            section("🧭 สั่งแบบกดเลือก", listOf(
                t("🧭", "เลือกแอป→คำสั่ง") { CommandBuilder.open(a) { cmd -> send(cmd) } }))
            section("✨ สร้าง", listOf(
                t("🎨", "วาดรูป") { prefill("วาดรูป ") }, t("📊", "สไลด์") { prefill("ทำสไลด์เรื่อง ") },
                t("📄", "ไฟล์ Word") { prefill("สร้างเอกสารเรื่อง ") }, t("📝", "จดโน้ต") { prefill("จดโน้ตว่า ") },
                t("🎬", "วิดีโอ") { prefill("สร้างวิดีโอ ") }, t("🧩", "ความสามารถใหม่") { prefill("เพิ่มความสามารถ: ") },
                t("🔎", "ค้นเว็บ") { prefill("ค้นหา ") }, t("📰", "ข่าววันนี้") { send("ข่าววันนี้") }))
            section("💬 แชท", listOf(
                t("🤖", "ตอบอัตโนมัติ") { startActivity(Intent(a, AutoReplyActivity::class.java)) },
                t("🌙", "ไม่อยู่") { send("ไม่อยู่นะ") }, t("👋", "กลับมาแล้ว") { send("กลับมาแล้ว") },
                t("📬", "ใครทักมา") { send("ใครทักมาตอนไม่อยู่") },
                t("✉️", "ส่งข้อความ") { prefill("ส่งข้อความหา ") }, t("📜", "ประวัติแชท") { startActivity(Intent(a, ChatHistoryActivity::class.java)) }))
            section("📱 เครื่อง", listOf(
                t("ℹ️", "ข้อมูลเครื่อง") { send("ข้อมูลเครื่อง") }, t("💾", "พื้นที่") { send("พื้นที่เหลือเท่าไหร่") },
                t("🌗", "โหมดมืด") { Popups.choose(a, "🌗", "โหมดมืด", "", listOf("เปิด" to { send("เปิดโหมดมืด") }, "ปิด" to { send("ปิดโหมดมืด") })) },
                t("👁️", "ถนอมสายตา") { Popups.choose(a, "👁️", "ถนอมสายตา", "", listOf("เปิด" to { send("เปิดถนอมสายตา") }, "ปิด" to { send("ปิดถนอมสายตา") })) },
                t("🍃", "ประหยัดแบต") { Popups.choose(a, "🍃", "ประหยัดพลังงาน", "", listOf("เปิด" to { send("เปิดประหยัดพลังงาน") }, "ปิด" to { send("ปิดประหยัดพลังงาน") })) },
                t("✈️", "เครื่องบิน") { toggle("airplane", "โหมดเครื่องบิน") },
                t("📸", "แคปจอ") { send("แคปหน้าจอ") }, t("⚙️", "หน้าตั้งค่า…") { prefill("เปิดหน้าตั้งค่า") }))
            section("📷 กล้อง", listOf(
                t("✋", "ถืออะไรอยู่") { send("ถืออะไรอยู่") }, t("🙂", "ใครอยู่หน้ากล้อง") { send("ใครอยู่หน้ากล้อง") },
                t("📷", "จำหน้าฉัน") { send("จำหน้าฉัน") }, t("🔭", "กล้องหลัง") { send("เห็นอะไรบ้าง") }))
            section("📚 เรียนรู้ / ระบบ", listOf(
                t("📚", "ศึกษาแอป") { prefill("ศึกษาแอป ") }, t("🎬", "จำขั้นตอน") { prefill("จำขั้นตอน ") },
                t("📱", "แอปทั้งหมด") { send("มีแอปอะไรบ้าง") }, t("🧪", "ทดสอบแอป") { send("ทดสอบแอปทั้งหมด") }, t("🗣️", "สอนเสียงฉัน") { enrollPanel(again = true) },
                t("👂", "ฟังตลอด") { Popups.choose(a, "👂", "โหมดฟัง", "", listOf("เปิดฟังตลอด" to { send("ฟังตลอด") }, "ต้องเรียกชื่อ" to { send("ปิดฟังตลอด") })) },
                t("🩺", "ตรวจซ่อม") { send("ตรวจซ่อม") }, t("🔒", "ข้อมูลของฉัน") { send("ข้อมูลของฉัน") },
                t("🧰", "เครื่องมือทั้งหมด") { startActivity(Intent(a, ToolsActivity::class.java)) }))
            card.addView(sv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (resources.displayMetrics.heightPixels * 0.55).toInt()))
            card.addView(Ui.button(a, "ปิด") { dlg.dismiss() }, Ui.lpm(a, t = 8))
        }
    }

    private fun menu() {
        Popups.choose(this, "⋯", "เมนู", "", listOf(
            (if (Floaty.enabled(this)) "🫧 ปิดปุ่มลอย (คุยเหนือแอปอื่น)" else "🫧 เปิดปุ่มลอย (คุยเหนือแอปอื่น)") to { toggleFloaty() },
            "🔐 สิทธิ์ของผู้ช่วย" to { startActivity(Intent(this, SetupActivity::class.java)) },
            "🎙️ ลงทะเบียนเสียงใหม่" to { enrollPanel(again = true) },
            "🧰 เครื่องมือทั้งหมด" to { startActivity(Intent(this, ToolsActivity::class.java)) },
            "💬 ตอบกลับอัตโนมัติ" to { startActivity(Intent(this, AutoReplyActivity::class.java)) },
            "📜 ประวัติแชท" to { startActivity(Intent(this, ChatHistoryActivity::class.java)) },
            "📄 บันทึกการทำงาน" to { startActivity(Intent(this, LogActivity::class.java)) },
            "🔄 ตรวจอัปเดตแอป" to { Updater.check(this, true) },
            "📋 ทำอะไรได้บ้าง" to { help() }))
    }

    private fun toggleFloaty() {
        if (Floaty.enabled(this)) {
            Floaty.setEnabled(this, false); Popups.snack(this, "ปิดปุ่มลอยแล้ว"); return
        }
        if (!Floaty.allowed(this)) {
            Popups.snack(this, "อนุญาต \"แสดงเหนือแอปอื่น\" ให้ผู้ช่วยก่อน แล้วกดเปิดอีกครั้ง")
            startActivity(Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                android.net.Uri.parse("package:$packageName")))
            return
        }
        Floaty.setEnabled(this, true); Floaty.pause()
        Popups.snack(this, "🫧 เปิดปุ่มลอยแล้ว — ออกไปแอปอื่นจะเห็นปุ่ม 🤖 แตะเพื่อพิมพ์คุย/ปิดเปิดไมค์")
    }

    private fun buildInput(): View {
        val bar = Ui.row(this)
        bar.setPadding(Ui.dp(this, 10), Ui.dp(this, 6), Ui.dp(this, 10), Ui.dp(this, 12))

        micHost = FrameLayout(this).apply { clipChildren = false; clipToPadding = false }
        micBtn = TextView(this).apply {
            text = ""; gravity = Gravity.CENTER; contentDescription = "กดเพื่อพูด"
            foreground = getDrawable(R.drawable.ic_ui_mic)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(this@MainActivity, 15)) }
            background = Ui.ripple(Ui.oval(Ui.P500, Ui.P500), 0x55FFFFFF)
            elevation = Ui.dpf(this@MainActivity, 6f)
            setOnClickListener { Fx.press(this); listenOnce() }
        }
        micHost.addView(micBtn, FrameLayout.LayoutParams(Ui.dp(this, 54), Ui.dp(this, 54), Gravity.CENTER))
        bar.addView(micHost, LinearLayout.LayoutParams(Ui.dp(this, 64), Ui.dp(this, 64)))

        val pill = Ui.row(this)
        pill.background = Ui.round(Color.WHITE, Ui.dpf(this, 28f), Ui.P200, Ui.dp(this, 1))
        pill.elevation = Ui.dpf(this, 3f)
        pill.setPadding(Ui.dp(this, 16), Ui.dp(this, 4), Ui.dp(this, 6), Ui.dp(this, 4))
        input = EditText(this).apply {
            hint = "พิมพ์คำสั่ง เช่น ส่งไลน์หาแม่ว่าถึงบ้านแล้ว…"
            setHintTextColor(0xFF9C94B8.toInt()); setTextColor(Ui.TEXT); textSize = 15.5f
            background = null; maxLines = 4
            imeOptions = EditorInfo.IME_ACTION_SEND
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
        }
        val plus = TextView(this).apply {
            text = ""; contentDescription = "คำสั่งเพิ่มเติม"
            foreground = getDrawable(R.drawable.ic_e_plus)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(this@MainActivity, 9)) }
            setOnClickListener { Fx.press(this); actions() }
        }
        pill.addView(plus, LinearLayout.LayoutParams(Ui.dp(this, 40), Ui.dp(this, 44)))
        val attach = TextView(this).apply {
            text = ""; contentDescription = "แนบไฟล์"
            foreground = getDrawable(R.drawable.ic_e_clip)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(this@MainActivity, 9)) }
            setOnClickListener { Fx.press(this); pickFile() }
        }
        pill.addView(attach, LinearLayout.LayoutParams(Ui.dp(this, 40), Ui.dp(this, 44)))
        val pick = TextView(this).apply {
            text = ""; contentDescription = "สร้างคำสั่งแบบเลือก"
            foreground = getDrawable(R.drawable.ic_e_compass)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(this@MainActivity, 9)) }
            setOnClickListener { Fx.press(this); CommandBuilder.open(this@MainActivity) { cmd -> send(cmd) } }
        }
        pill.addView(pick, LinearLayout.LayoutParams(Ui.dp(this, 40), Ui.dp(this, 44)))
        pill.addView(input, Ui.lp(0, weight = 1f))
        val sendBtn = TextView(this).apply {
            text = ""; gravity = Gravity.CENTER; contentDescription = "ส่ง"
            foreground = getDrawable(R.drawable.ic_ui_send)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(this@MainActivity, 12)) }
            background = Ui.ripple(Ui.oval(Ui.P500, Ui.P500), 0x55FFFFFF)
            setOnClickListener {
                Fx.press(this)
                val t = input.text.toString().trim()
                if (t.isNotEmpty()) { input.setText(""); send(t) }
            }
        }
        pill.addView(sendBtn, LinearLayout.LayoutParams(Ui.dp(this, 44), Ui.dp(this, 44)))
        bar.addView(pill, Ui.lp(0, weight = 1f).apply { marginStart = Ui.dp(this@MainActivity, 6) })
        return bar
    }

    // ------------------------------------------------------------------ วงจรชีวิต
    override fun onResume() {
        super.onResume()
        visible = true
        current = this
        ChatLog.listen(listener)
        rendered.clear()
        list.removeAllViews()
        render()
        BotService.start(this)                // ยืนยันบริการเบื้องหน้า (ให้ไมค์ทำงานตอนแอปเปิดอยู่)
        Floaty.pause()                        // อยู่ในแอปเอง → ซ่อนปุ่มลอย
        refreshTiles()
        Updater.check(this, false)            // มีเวอร์ชันใหม่บน GitHub → ถามอัปเดตทับ
        list.postDelayed({
            if (!visible || isFinishing || isDestroyed) return@postDelayed
            if (crashDlg?.isShowing == true) return@postDelayed
            crashDlg = try { CrashReport.showIfAny(this) { crashDlg = null; if (visible) checkVoiceGate() } } catch (_: Exception) { null }
            if (crashDlg == null) checkVoiceGate()        // ยังไม่ลงทะเบียนเสียง → บังคับลงทะเบียนก่อน
        }, 700)
    }

    // ------------------------------------------------------------------ ลงทะเบียนเสียงก่อนใช้งาน
    private var gate: Dialog? = null
    private var crashDlg: Dialog? = null
    @Volatile private var enrolling = false
    private var enrollStarted = 0L

    private fun voiceEnrolled() = java.io.File(filesDir, "data/voiceprint.json").exists()
    private fun gateOn() = (Env.load(this)["REQUIRE_VOICE_ENROLL"] ?: "1").trim().lowercase() !in setOf("0", "false", "off", "no")

    /** ยังไม่มีลายเสียง → แสดงหน้าบังคับลงทะเบียน (ปิดไม่ได้ จนกว่าจะลงทะเบียนสำเร็จ หรือออกจากแอป) */
    private fun checkVoiceGate() {
        if (isFinishing || isDestroyed || !gateOn()) return
        if (voiceEnrolled()) {
            if (enrolling) { enrolling = false; Popups.snack(this, "✅ ลงทะเบียนเสียงเรียบร้อย เริ่มใช้งานได้เลย") }
            gate?.dismiss(); gate = null
            return
        }
        if (enrolling && System.currentTimeMillis() - enrollStarted < 150_000) return   // กำลังพูดตามประโยคอยู่
        enrolling = false
        if (gate?.isShowing == true) return
        gate = enrollPanel(again = false)
    }

    /** หน้าลงทะเบียนเสียง · again = ลงทะเบียนใหม่จากเมนู (มีลายเสียงอยู่แล้ว ปิดได้) */
    private fun enrollPanel(again: Boolean): Dialog {
        val a = this
        return Popups.panel(a, "🎙️", if (again) "ลงทะเบียนเสียงใหม่" else "ลงทะเบียนเสียงก่อนใช้งาน") { card, d ->
            card.addView(Ui.text(a, "ผู้ช่วยจะรับคำสั่งเฉพาะเสียงของคุณเท่านั้น\n" +
                "กดเริ่ม แล้วพูดตามประโยคที่ขึ้นบนจอ 6 ประโยค ด้วยเสียงปกติ ในที่เงียบ (ประมาณ 1 นาที)" +
                (if (again) "\nลายเสียงเดิมจะถูกแทนที่เมื่อลงทะเบียนสำเร็จ" else ""),
                15f, false, Ui.TEXT).apply { gravity = Gravity.CENTER }, Ui.lpm(a, b = 14))
            card.addView(Ui.button(a, "🎙️ เริ่มลงทะเบียนเสียง", true) {
                d.dismiss()
                if (!again) startEnroll()
                else if (!Bridge.micAllowed()) requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 8)
                else { Popups.snack(a, "🎙️ พูดตามประโยคที่ขึ้นในแชททีละประโยค"); pyTool("voice_enroll") }
            }, Ui.lpm(a, b = 8))
            if (again) card.addView(Ui.button(a, "ยกเลิก") { d.dismiss() })
            else card.addView(Ui.button(a, "ออกจากแอป") { d.dismiss(); finish() })
        }.apply { if (!again) { setCancelable(false); setCanceledOnTouchOutside(false) } }
    }

    private fun startEnroll() {
        if (!Bridge.micAllowed()) {
            requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 7); return
        }
        enrolling = true
        enrollStarted = System.currentTimeMillis()
        Popups.snack(this, "🎙️ พูดตามประโยคที่ขึ้นในแชททีละประโยค")
        pyTool("voice_enroll")
        list.postDelayed({ if (visible && !isFinishing) checkVoiceGate() }, 151_000)
    }

    /** ระหว่างลงทะเบียน: สำเร็จ → ปิดหน้าบังคับ · ล้มเหลว (ข้อความ ❌) → ให้ลองใหม่ */
    private fun onEnrollProgress() {
        if (voiceEnrolled()) { checkVoiceGate(); return }
        val last = ChatLog.items.lastOrNull() ?: return
        if (last.role == "bot" && last.text.startsWith("❌") && last.time >= enrollStarted) {
            enrolling = false
            Popups.snack(this, "ลงทะเบียนไม่สำเร็จ ลองอีกครั้งในที่เงียบ")
            checkVoiceGate()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 8 && Bridge.micAllowed()) { Popups.snack(this, "🎙️ พูดตามประโยคที่ขึ้นในแชททีละประโยค"); pyTool("voice_enroll") }
        if (requestCode == 7) {
            if (Bridge.micAllowed()) startEnroll()
            else { Popups.snack(this, "ต้องอนุญาตไมโครโฟนก่อนลงทะเบียนเสียง"); checkVoiceGate() }
        }
    }

    override fun onPause() {
        ChatLog.unlisten(listener)
        visible = false
        current = null
        if (Floaty.enabled(this)) Floaty.resume(this)     // ออกไปแอปอื่น → แสดงปุ่มลอย
        super.onPause()
    }

    // ------------------------------------------------------------------ แสดงผล
    private fun refreshStatus() {
        val s = try { JSONObject(Bridge.status()) } catch (_: Exception) { return }
        chips.removeAllViews()
        fun chip(k: String, name: String) {
            val ok = s.optBoolean(k)
            val c = Ui.chip(this, (if (ok) "✓ " else "! ") + name, false) { startActivity(Intent(this, SetupActivity::class.java)) }
            if (!ok) c.background = Ui.round(0xFFFFF4DB.toInt(), Ui.dpf(this, 20f), 0xFFF2C46B.toInt(), Ui.dp(this, 1))
            chips.addView(c, Ui.lpm(this, w = ViewGroup.LayoutParams.WRAP_CONTENT, e = 8))
        }
        chip("bot", "บอท"); chip("a11y", "คุมจอ"); chip("notif", "แจ้งเตือน"); chip("mic", "ไมค์")
        val mood = listOf(ChatLog.moodTitle, ChatLog.moodText).filter { it.isNotBlank() }.joinToString(" · ")
        val on = Bridge.isEnabled()
        power.background = Ui.ripple(GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            if (on) setColor(0xFFE9F7EF.toInt()) else setColor(Color.WHITE)
            setStroke(Ui.dp(this@MainActivity, 1), if (on) 0xFF9BD3B5.toInt() else Ui.P200)
        })
        subtitle.setTextColor(if (on) Ui.OK else Ui.SUB)
        orb.alpha = if (on) 1f else 0.45f
        subtitle.text = Ui.clean(when {
            !on -> "ปิดอยู่ — แตะปุ่มเปิด/ปิดด้านบนเพื่อเปิด"
            mood.isNotEmpty() -> mood
            !s.optBoolean("a11y") -> "แตะชิป 'คุมจอ' เพื่อเปิดสิทธิ์ก่อนนะ"
            else -> "พร้อมรับคำสั่ง ✨"
        })
    }

    private fun welcome(): View {
        val c = Ui.card(this, 20, 24)
        c.gravity = Gravity.CENTER_HORIZONTAL
        val o = android.widget.ImageView(this).apply {
            setImageResource(R.drawable.ic_launcher); clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: View, o: android.graphics.Outline) { o.setRoundRect(0, 0, v.width, v.height, Ui.dpf(this@MainActivity, 22f)) }
            }
        }
        c.addView(o, LinearLayout.LayoutParams(Ui.dp(this, 78), Ui.dp(this, 78)).apply { bottomMargin = Ui.dp(this@MainActivity, 12) })
        Fx.breathe(o, 1.1f, 1300)
        c.addView(Ui.text(this, "สวัสดีครับ มีอะไรให้ช่วยไหม", 19f, true, Ui.TEXT).apply { gravity = Gravity.CENTER })
        c.addView(Ui.text(this, "พิมพ์ กดปุ่มไมค์ พูดว่า \"เฮ้ย ผู้ช่วย\" หรือสั่งผ่าน Telegram ก็ได้\nลองแตะปุ่มลัดด้านบนดูได้เลย", 14f, false, Ui.SUB)
            .apply { gravity = Gravity.CENTER }, Ui.lpm(this, t = 6))
        c.layoutParams = Ui.lpm(this, t = 20, s = 12, e = 12)
        return c
    }

    private fun imageBubble(m: ChatLog.Msg, path: String, user: Boolean): View {
        val a = this
        val wrap = Ui.col(a, 0)
        val iv = android.widget.ImageView(a).apply {
            adjustViewBounds = true
            scaleType = android.widget.ImageView.ScaleType.FIT_CENTER
            try {
                val o = android.graphics.BitmapFactory.Options().apply { inSampleSize = 2 }
                setImageBitmap(android.graphics.BitmapFactory.decodeFile(path, o))
            } catch (_: Throwable) {}
            clipToOutline = true
            background = Ui.round(Ui.P100, Ui.dpf(a, 18f))
            setOnClickListener {                                   // แตะเพื่อเปิดดูรูปเต็มในแกลเลอรี
                Thread { Bridge.openFile(path, "image/*") }.start()
            }
        }
        val w = (resources.displayMetrics.widthPixels * 0.55).toInt()
        wrap.addView(iv, LinearLayout.LayoutParams(w, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            gravity = if (user) Gravity.END else Gravity.START; if (!user) marginStart = Ui.dp(a, 38)
        })
        val rest = m.text.substringAfter("\n", "").trim()
        if (rest.isNotEmpty()) wrap.addView(Ui.text(a, rest, 14.5f, false, Ui.TEXT).apply {
            gravity = if (user) Gravity.END else Gravity.START
        }, Ui.lpm(a, t = 4))
        wrap.layoutParams = Ui.lpm(a, t = 10)
        return wrap
    }

    private fun bubble(m: ChatLog.Msg): View {
        val a = this
        if (m.role == "status") {
            val t = Ui.text(a, m.text, 12.5f, false, Ui.P600).apply {
                background = Ui.round(Ui.P100, Ui.dpf(a, 14f))
                setPadding(Ui.dp(a, 12), Ui.dp(a, 5), Ui.dp(a, 12), Ui.dp(a, 5))
            }
            t.layoutParams = Ui.lpm(a, w = ViewGroup.LayoutParams.WRAP_CONTENT, t = 8).apply { gravity = Gravity.CENTER_HORIZONTAL }
            return t
        }
        val user = m.role == "user"
        val img = Regex("^🖼️ (/\\S+\\.(?:jpg|jpeg|png|webp))", RegexOption.IGNORE_CASE).find(m.text)?.groupValues?.get(1)
        if (img != null && java.io.File(img).exists()) return imageBubble(m, img, user)
        val r = Ui.dpf(a, 20f); val s = Ui.dpf(a, 6f)
        val tv = Ui.text(a, m.text, 15.5f, false, if (user) Color.WHITE else Ui.TEXT, keepEmoji = true).apply {
            setPadding(Ui.dp(a, 14), Ui.dp(a, 10), Ui.dp(a, 14), Ui.dp(a, 10))
            setTextIsSelectable(false)
            background = if (user)
                GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(Ui.P500, Ui.PINK)).apply { cornerRadii = floatArrayOf(r, r, r, r, s, s, r, r) }
            else Ui.corners(Color.WHITE, s, r, r, r)
            elevation = Ui.dpf(a, if (user) 3f else 1.5f)
            setOnLongClickListener {
                (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("chat", m.text))
                Popups.snack(a, "📋 คัดลอกแล้ว"); true
            }
        }
        val wrap = Ui.col(a, 0)
        val line = Ui.row(a)
        line.gravity = if (user) Gravity.END else Gravity.START or Gravity.TOP
        if (!user) {
            val av = android.widget.ImageView(a).apply {
                setImageResource(R.drawable.ic_launcher); clipToOutline = true      // รูปผู้ช่วย = โลโก้
                outlineProvider = object : android.view.ViewOutlineProvider() {
                    override fun getOutline(v: View, o: android.graphics.Outline) { o.setOval(0, 0, v.width, v.height) }
                }
            }
            line.addView(av, LinearLayout.LayoutParams(Ui.dp(a, 30), Ui.dp(a, 30)).apply { marginEnd = Ui.dp(a, 8) })
        }
        val maxW = (resources.displayMetrics.widthPixels * 0.78).toInt()
        tv.maxWidth = maxW
        line.addView(tv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        wrap.addView(line, Ui.lp())
        wrap.addView(Ui.text(a, timeFmt.format(Date(m.time)), 10.5f, false, 0xFFA59CC4.toInt()).apply {
            gravity = if (user) Gravity.END else Gravity.START
            setPadding(if (user) 0 else Ui.dp(a, 40), Ui.dp(a, 2), Ui.dp(a, 4), 0)
        }, Ui.lp())
        wrap.layoutParams = Ui.lpm(a, t = 10)
        return wrap
    }

    private fun render() {
        val items = ChatLog.items.toList()
        if (items.isEmpty()) {
            if (rendered.isNotEmpty() || list.childCount == 0) { list.removeAllViews(); rendered.clear(); list.addView(welcome()) }
        } else {
            if (rendered.isEmpty()) list.removeAllViews()          // เอาการ์ดต้อนรับออก
            var common = 0
            while (common < rendered.size && common < items.size && rendered[common] === items[common]) common++
            while (rendered.size > common) {
                list.removeViewAt(list.childCount - 1); rendered.removeAt(rendered.size - 1)
            }
            for (i in common until items.size) {
                val v = bubble(items[i])
                list.addView(v)
                rendered.add(items[i])
                if (i >= items.size - 3) Fx.enter(v, items[i].role == "user")
            }
        }
        val last = items.lastOrNull()
        val thinking = busy.get() > 0 || ChatLog.moodTitle.isNotBlank()
        typing.visibility = if (thinking) View.VISIBLE else View.GONE
        typingText.text = when {
            ChatLog.moodTitle.isNotBlank() -> ChatLog.moodTitle
            last?.role == "status" -> last?.text?.take(60) ?: ""
            else -> "กำลังคิด…"
        }
        scroll.post { scroll.smoothScrollTo(0, list.height) }
        renderPrompts()
        refreshStatus()
    }

    /** คำถาม/ขออนุญาต → ป๊อปอัปแผ่นเด้ง */
    private fun renderPrompts() {
        val ids = ChatLog.prompts.map { it.id }.toSet()
        for (id in dialogs.keys.toList()) if (id !in ids) { dialogs.remove(id)?.let { if (it.isShowing) it.dismiss() } }
        for (p in ChatLog.prompts) {
            if (dialogs.containsKey(p.id) || isFinishing) continue
            dialogs[p.id] = if (p.kind == "confirm") Popups.confirm(this, p.id, p.text) else Popups.ask(this, p.id, p.text)
        }
    }

    // ------------------------------------------------------------------ การกระทำ
    // ---------------------------------------------------------------- แนบไฟล์ (รูป/เสียง/วิดีโอ/เอกสาร) ให้วิเคราะห์
    private fun pickFile() {
        if (!Bridge.isEnabled()) { Popups.snack(this, "⏸️ ผู้ช่วยปิดอยู่ — แตะ ⏻ ด้านบนเพื่อเปิด"); return }
        // รับทุกประเภท (รูป เสียง วิดีโอ PDF Word Excel PowerPoint ข้อความ) — บางแอปไฟล์ส่งชนิดเป็น octet-stream
        val i = Intent(Intent.ACTION_GET_CONTENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
        try { startActivityForResult(Intent.createChooser(i, "เลือกไฟล์ให้ผู้ช่วยดู"), 77) }
        catch (_: Exception) { Popups.snack(this, "เปิดตัวเลือกไฟล์ไม่ได้") }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req != 77 || res != RESULT_OK) return
        val uri = data?.data ?: return
        val mime = contentResolver.getType(uri) ?: "application/octet-stream"
        var name = "file"
        try {
            val c = contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)
            if (c != null) {
                if (c.moveToFirst()) name = c.getString(0) ?: name
                c.close()
            }
        } catch (_: Exception) {}
        val caption = input.text.toString().trim()
        input.setText("")
        val dir = java.io.File(filesDir, "data/inbox").apply { mkdirs() }
        val out = java.io.File(dir, System.currentTimeMillis().toString() + "_" + name.replace(Regex("[^\\w.\\-ก-๙]"), "_"))
        ChatLog.add("user", (if (mime.startsWith("image/")) "🖼️ ${out.absolutePath}" else "📎 $name") + (if (caption.isNotEmpty()) "\n$caption" else ""))
        busy.incrementAndGet(); render()
        worker.execute {
            try {
                contentResolver.openInputStream(uri)?.use { inp -> out.outputStream().use { inp.copyTo(it) } }
                val reply = App.py(this).getModule("android_main").callAttr("chat_file", out.absolutePath, mime, caption).toString()
                if (reply.isNotBlank()) ChatLog.add("bot", reply)
            } catch (e: Throwable) {
                ChatLog.add("bot", "❗ อ่านไฟล์ไม่ได้: ${e.message?.take(200)}")
            } finally {
                busy.decrementAndGet(); runOnUiThread { render() }
            }
        }
    }

    private fun prefill(t: String) {
        input.setText(t); input.setSelection(t.length); input.requestFocus()
        val imm = getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager
        imm.showSoftInput(input, 0)
    }

    private fun send(text: String, voice: Boolean = false) {
        if (!Bridge.isEnabled()) {
            Popups.snack(this, "⏸️ ผู้ช่วยปิดอยู่ — แตะ ⏻ ด้านบนเพื่อเปิด"); return
        }
        ChatLog.add("user", text)
        busy.incrementAndGet(); render()
        worker.execute {
            try {
                val reply = App.py(this).getModule("android_main").callAttr("chat", text, voice).toString()
                if (reply.isNotBlank()) ChatLog.add("bot", reply)
            } catch (e: Throwable) {
                ChatLog.add("bot", "❗ ผิดพลาด: ${e.message?.take(300)}")
            } finally {
                busy.decrementAndGet()
                runOnUiThread { render(); refreshTiles() }
            }
        }
    }

    private fun setListening(on: Boolean) {
        micAnims.forEach { it.cancel() }
        micAnims = if (on) Fx.ripples(micHost, this, 54) else emptyList()
        micBtn.background = Ui.ripple(Ui.oval(if (on) Ui.BAD else Ui.P500, if (on) Ui.BAD else Ui.P500), 0x55FFFFFF)   // แดง = กำลังฟัง
        if (on) ChatLog.setMood("🎙️ กำลังฟัง…", "พูดได้เลย", true) else if (ChatLog.moodTitle.startsWith("🎙️")) ChatLog.setMood("", "", false)
    }

    private fun listenOnce() {
        if (!Bridge.isEnabled()) { Popups.snack(this, "⏸️ ผู้ช่วยปิดอยู่ — แตะ ⏻ ด้านบนเพื่อเปิด"); return }
        if (!Bridge.micAllowed()) {
            requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 5); return
        }
        setListening(true)
        Thread {
            var err: String? = null
            val heard = try {
                App.py(this).getModule("android_main").callAttr("listen_once").toString()
            } catch (e: Throwable) {
                err = e.message?.substringAfterLast("Error: ")?.take(220); ""
            }
            runOnUiThread {
                setListening(false)
                when {
                    heard.isNotBlank() -> send(heard, voice = true)   // มาจากเสียง → ถามยืนยันก่อนส่งข้อความ
                    err != null -> Popups.info(this, "🎤", "ยังไม่ได้ยิน", err ?: "")
                    else -> Popups.snack(this, "🎤 ไม่ได้ยินเสียงพูด ลองอีกครั้ง")
                }
            }
        }.start()
    }

    private fun help() {
        Popups.info(this, "📋", "ผู้ช่วยทำอะไรได้บ้าง", """• เปิด youtube / ปิดแอป line / กลับหน้าหลัก
• ส่งไลน์หาแม่ว่า ถึงบ้านแล้ว / ส่งรูปล่าสุดให้ต้นในไอจี
• มีแจ้งเตือนอะไรบ้าง / ตอบกลับว่า โอเค
• ลดเสียง / เพิ่มแสง / เปิดห้ามรบกวน / ไฟฉาย
• หาข่าววันนี้ / สรุปไฟล์นี้ / ช่วยแปล…
• กรอกฟอร์ม / จำข้อมูลของฉัน ชื่อ …
• ศึกษาแอป instagram / จำขั้นตอน … → จบขั้นตอน → ทำขั้นตอน …
• ตรวจซ่อม / ซ่อมตัวเอง <อาการ> / ย้อนการซ่อม
• ทดสอบแอปทั้งหมด (ดูว่าแอปไหนผู้ช่วยใช้ได้/ไม่ได้)
• ฟังตลอด / ปิดฟังตลอด / สลับไปใช้ claude""")
    }
}
