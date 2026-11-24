package com.aibot.assistant

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors
import kotlin.math.abs

/** ปุ่มลอย 🤖 เหนือแอปอื่น: แตะ = เปิดช่องพิมพ์คุยกับผู้ช่วย · 🎤 เปิด/ปิดไมค์สั่งเสียง · ลากย้ายได้ */
object Floaty {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private var wm: WindowManager? = null
    private var bubble: View? = null
    private var bubbleLp: WindowManager.LayoutParams? = null
    private var panel: View? = null
    private var log: LinearLayout? = null
    private var logScroll: ScrollView? = null
    private var micBtn: TextView? = null
    @Volatile private var busy = false
    private val listener: () -> Unit = { refreshLog() }

    fun enabled(c: Context) = c.getSharedPreferences("app", Context.MODE_PRIVATE).getBoolean("float_on", false)

    fun setEnabled(c: Context, on: Boolean) {
        c.getSharedPreferences("app", Context.MODE_PRIVATE).edit().putBoolean("float_on", on).apply()
        if (on) show(c) else hide()
    }

    fun allowed(c: Context) = Settings.canDrawOverlays(c)

    private fun type() = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY

    /** ขนาดจอตอนนี้ (เปลี่ยนเมื่อหมุนจอ / แบ่งจอ) */
    private fun screen(c: Context): Pair<Int, Int> {
        val w = wm
        if (w != null && android.os.Build.VERSION.SDK_INT >= 30) {
            val r = w.currentWindowMetrics.bounds
            return r.width() to r.height()
        }
        val m = c.resources.displayMetrics
        return m.widthPixels to m.heightPixels
    }

    /** บังคับให้ปุ่มอยู่ในจอเสมอ (กันหลุดไปค้างมุมจอ/ใต้แถบสถานะ แล้วลากคืนไม่ได้) */
    private fun clamp(c: Context, lp: WindowManager.LayoutParams, size: Int, snap: Boolean) {
        val (w, h) = screen(c)
        val m = Ui.dp(c, 8)
        val top = Ui.dp(c, 40)                      // ไม่ทับแถบสถานะ
        val bottom = h - size - Ui.dp(c, 64)        // ไม่ทับแถบนำทาง
        lp.y = lp.y.coerceIn(top, maxOf(top, bottom))
        lp.x = if (snap) { if (lp.x + size / 2 < w / 2) m else w - size - m }
               else lp.x.coerceIn(m, maxOf(m, w - size - m))
    }

    /** แสดงปุ่มลอย (ถ้าเปิดใช้และได้สิทธิ์แล้ว) */
    fun show(ctx: Context) = main.post {
        val c = ctx.applicationContext
        if (!enabled(c) || !allowed(c) || bubble != null) return@post
        wm = c.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val size = Ui.dp(c, 58)
        val b = android.widget.ImageView(c).apply {
            setImageResource(R.drawable.ic_launcher)                        // ปุ่มลอย = โลโก้แบบ B
            contentDescription = "ผู้ช่วย AI"
            clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: View, o: android.graphics.Outline) { o.setOval(0, 0, v.width, v.height) }
            }
            elevation = Ui.dpf(c, 8f)
            alpha = 0.95f
        }
        val lp = WindowManager.LayoutParams(size, size, type(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.START
            val p = c.getSharedPreferences("app", Context.MODE_PRIVATE)
            val (w, h) = screen(c)
            x = p.getInt("float_x", w - size - Ui.dp(c, 8))
            y = p.getInt("float_y", h / 3)
        }
        clamp(c, lp, size, snap = true)              // ตำแหน่งเก่าที่หลุดจอ → ดึงกลับเข้าจอ
        var dx = 0f; var dy = 0f; var sx = 0; var sy = 0; var moved = false
        b.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { dx = e.rawX; dy = e.rawY; sx = lp.x; sy = lp.y; moved = false; true }
                MotionEvent.ACTION_MOVE -> {
                    val mx = e.rawX - dx; val my = e.rawY - dy
                    if (!moved && (abs(mx) > 12 || abs(my) > 12)) { moved = true; showTrash(c) }
                    lp.x = sx + mx.toInt(); lp.y = sy + my.toInt()
                    clamp(c, lp, size, snap = false)
                    trash?.alpha = if (overTrash(c, e.rawX, e.rawY)) 1f else 0.6f
                    try { wm?.updateViewLayout(b, lp) } catch (_: Exception) {}
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    val drop = moved && overTrash(c, e.rawX, e.rawY)
                    hideTrash()
                    if (drop) {
                        // ลากลงถังขยะ → ปิดปุ่มลอย (เปิดใหม่ได้ที่ ⚙️ ตั้งค่า)
                        setEnabled(c, false)
                        android.widget.Toast.makeText(c, "ปิดปุ่มลอยแล้ว", android.widget.Toast.LENGTH_SHORT).show()
                    } else if (moved) {
                        clamp(c, lp, size, snap = true)
                        try { wm?.updateViewLayout(b, lp) } catch (_: Exception) {}
                        c.getSharedPreferences("app", Context.MODE_PRIVATE).edit()
                            .putInt("float_x", lp.x).putInt("float_y", lp.y).apply()
                    } else if (e.action == MotionEvent.ACTION_UP) togglePanel(c)
                    true
                }
                else -> false
            }
        }
        try { wm?.addView(b, lp); bubble = b; bubbleLp = lp } catch (e: Exception) { Bridge.log("floaty: $e") }
    }

    // ---------------------------------------------------------- ถังขยะตอนลาก (ลากมาวาง = ปิดปุ่มลอย)
    private var trash: View? = null

    private fun trashCenter(c: Context): Pair<Float, Float> {
        val (w, h) = screen(c)
        return (w / 2f) to (h - Ui.dp(c, 110).toFloat())
    }

    private fun overTrash(c: Context, x: Float, y: Float): Boolean {
        val (tx, ty) = trashCenter(c)
        val r = Ui.dp(c, 70)
        return (x - tx) * (x - tx) + (y - ty) * (y - ty) < r * r
    }

    private fun showTrash(c: Context) {
        if (trash != null) return
        val size = Ui.dp(c, 64)
        val t = TextView(c).apply {
            text = "✕"; textSize = 24f; gravity = Gravity.CENTER; setTextColor(Color.WHITE)
            background = Ui.oval(0xFFEF4444.toInt(), 0xFFDC2626.toInt())
            alpha = 0.6f
        }
        val (tx, ty) = trashCenter(c)
        val lp = WindowManager.LayoutParams(size, size, type(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (tx - size / 2).toInt(); y = (ty - size / 2).toInt()
        }
        try { wm?.addView(t, lp); trash = t } catch (_: Exception) {}
    }

    private fun hideTrash() {
        trash?.let { try { wm?.removeView(it) } catch (_: Exception) {} }
        trash = null
    }

    fun hide() = main.post {
        closePanel()
        hideTrash()
        bubble?.let { try { wm?.removeView(it) } catch (_: Exception) {} }
        bubble = null
    }

    /** ซ่อนชั่วคราว (ตอนเปิดหน้าแอปเอง) / กลับมาแสดง */
    fun pause() = main.post { bubble?.visibility = View.GONE; closePanel() }
    fun resume(c: Context) = main.post {
        val b = bubble
        if (b == null) show(c)
        b?.visibility = View.VISIBLE
        val lp = bubbleLp
        if (b != null && lp != null) {
            clamp(c, lp, lp.width, snap = true)
            try { wm?.updateViewLayout(b, lp) } catch (_: Exception) {}
        }
        Unit
    }

    private fun togglePanel(c: Context) { if (panel != null) closePanel() else openPanel(c) }

    private fun closePanel() {
        panel?.let { p ->
            try {
                (p.context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
                    .hideSoftInputFromWindow(p.windowToken, 0)
            } catch (_: Exception) {}
            try { wm?.removeView(p) } catch (_: Exception) {}
        }
        panel = null; log = null; logScroll = null; micBtn = null
        ChatLog.unlisten(listener)
    }

    // สถานะไมค์ล่าสุดที่รู้ (Python ยังไม่พร้อม/ยุ่งอยู่ → ใช้ค่าเดิม ไม่เดาว่า "เปิด" แล้วกดกลายเป็นปิดไมค์)
    private var lastMic = true

    private fun micOn(c: Context): Boolean = try {
        App.py(c).getModule("android_main").callAttr("mic_enabled").toBoolean().also { lastMic = it }
    } catch (_: Throwable) { lastMic }

    private fun openPanel(c: Context) {
        val w = (c.resources.displayMetrics.widthPixels * 0.42).toInt().coerceIn(Ui.dp(c, 300), Ui.dp(c, 460))
        val card = Ui.card(c, 12, 20).apply { elevation = Ui.dpf(c, 12f) }
        // หัว: ชื่อ · ไมค์ · เปิดแอป · ปิด
        val head = Ui.row(c)
        head.addView(Ui.text(c, "🤖 ผู้ช่วย AI", 15f, true), Ui.lp(0, weight = 1f))
        val mic = Ui.chip(c, "🎤 ไมค์") {}
        fun paintMic(on: Boolean) {
            lastMic = on
            mic.text = if (on) "ไมค์เปิด" else "ไมค์ปิด"
            mic.background = Ui.round(if (on) 0x2216A34A else 0x22EF4444, Ui.dpf(c, 16f))
        }
        paintMic(micOn(c))
        mic.setOnClickListener {
            val want = !lastMic                     // สลับจากสถานะที่แสดงอยู่บนปุ่ม
            worker.execute {
                try { App.py(c).getModule("android_main").callAttr("set_mic", want) } catch (_: Throwable) {}
                main.post { paintMic(want) }
            }
        }
        micBtn = mic
        head.addView(mic, Ui.lpm(c, w = ViewGroup.LayoutParams.WRAP_CONTENT, e = 6))
        head.addView(Ui.chip(c, "↗") {
            closePanel()
            c.startActivity(Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }, Ui.lpm(c, w = ViewGroup.LayoutParams.WRAP_CONTENT, e = 6))
        head.addView(Ui.chip(c, "✕") { closePanel() }, Ui.lpm(c, w = ViewGroup.LayoutParams.WRAP_CONTENT))
        card.addView(head)

        // ข้อความล่าสุด
        val sc = ScrollView(c).apply { isVerticalScrollBarEnabled = false }
        val l = Ui.col(c, 2)
        sc.addView(l)
        card.addView(sc, Ui.lpm(c, h = Ui.dp(c, 220), t = 8))
        log = l; logScroll = sc

        // ช่องพิมพ์ + ส่ง
        val bar = Ui.row(c)
        val input: EditText = Ui.input(c, "พิมพ์คำสั่ง…").apply {
            imeOptions = EditorInfo.IME_ACTION_SEND
            setSingleLine(true)
        }
        fun go() {
            val t = input.text.toString().trim()
            if (t.isEmpty() || busy) return
            input.setText("")
            send(c, t)
        }
        input.setOnEditorActionListener { _, id, _ -> if (id == EditorInfo.IME_ACTION_SEND) { go(); true } else false }
        bar.addView(input, Ui.lp(0, weight = 1f))
        bar.addView(Ui.iconBtn(c, "", 44, Ui.P500) { go() }.apply {
            contentDescription = "ส่ง"
            foreground = c.getDrawable(R.drawable.ic_ui_send)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(c, 12)) }
        },
            Ui.lpm(c, w = ViewGroup.LayoutParams.WRAP_CONTENT, s = 6))
        card.addView(bar, Ui.lpm(c, t = 8))

        val lp = WindowManager.LayoutParams(w, ViewGroup.LayoutParams.WRAP_CONTENT, type(),
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.START
            val bl = bubbleLp
            val sw = c.resources.displayMetrics.widthPixels
            x = if (bl != null && bl.x > sw / 2) (bl.x - w + Ui.dp(c, 58)).coerceAtLeast(0) else (bl?.x ?: 0)
            y = ((bl?.y ?: 200) + Ui.dp(c, 64)).coerceAtMost(c.resources.displayMetrics.heightPixels / 2)
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE or
                WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE
        }
        try {
            wm?.addView(card, lp); panel = card
            ChatLog.listen(listener)
            refreshLog()
            input.requestFocus()
        } catch (e: Exception) { Bridge.log("floaty panel: $e") }
    }

    private fun refreshLog() = main.post {
        val l = log ?: return@post
        val c = l.context
        l.removeAllViews()
        for (m in ChatLog.items.toList().takeLast(8)) {
            val user = m.role == "user"
            val t = Ui.text(c, m.text.take(400), 13.5f, false, if (user) Color.WHITE else Ui.TEXT, keepEmoji = true).apply {
                setPadding(Ui.dp(c, 10), Ui.dp(c, 6), Ui.dp(c, 10), Ui.dp(c, 6))
                background = Ui.round(if (user) Ui.P500 else Ui.P50, Ui.dpf(c, 14f))
            }
            val row = LinearLayout(c).apply { gravity = if (user) Gravity.END else Gravity.START }
            row.addView(t, Ui.lpm(c, w = ViewGroup.LayoutParams.WRAP_CONTENT))
            l.addView(row, Ui.lpm(c, b = 6))
        }
        if (busy) l.addView(Ui.text(c, "กำลังคิด…", 12.5f, false, Ui.SUB))
        logScroll?.post { logScroll?.fullScroll(View.FOCUS_DOWN) }
    }

    private fun send(c: Context, text: String) {
        if (!Bridge.isEnabled()) { ChatLog.add("bot", "⏸️ ผู้ช่วยปิดอยู่ — เปิดในแอปก่อนนะ"); return }
        ChatLog.add("user", text)
        busy = true; refreshLog()
        worker.execute {
            try {
                val reply = App.py(c).getModule("android_main").callAttr("chat", text).toString()
                if (reply.isNotBlank()) ChatLog.add("bot", reply)
            } catch (e: Throwable) {
                ChatLog.add("bot", "❗ ผิดพลาด: ${e.message?.take(200)}")
            } finally {
                busy = false; refreshLog()
            }
        }
    }
}
