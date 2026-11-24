package com.aibot.assistant

import android.animation.Animator
import android.app.Activity
import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** ป๊อปอัปในแอป: ขออนุญาต / คำถาม / ข้อมูล (แผ่นเด้งขึ้นจากล่าง มีแอนิเมชัน) */
object Popups {
    private fun sheet(a: Activity, emoji: String, title: String, msg: String, build: (LinearLayout, Dialog) -> Unit): Dialog {
        val d = Dialog(a)
        d.requestWindowFeature(Window.FEATURE_NO_TITLE)
        val outer = FrameLayout(a)
        val card = Ui.card(a, 20, 26)
        card.gravity = Gravity.CENTER_HORIZONTAL
        val orb = Ui.iconTile(a, emoji, 60)                              // ดีไซน์ใหม่: ไอคอนเส้นในช่องสีอ่อน
        card.addView(orb, LinearLayout.LayoutParams(Ui.dp(a, 60), Ui.dp(a, 60)).apply { bottomMargin = Ui.dp(a, 12) })
        card.addView(Ui.text(a, Ui.plain(title), 19f, true, Ui.TEXT).apply { gravity = Gravity.CENTER })
        val m = Ui.text(a, msg, 15f, false, Ui.TEXT).apply {
            gravity = if (msg.lines().size > 3) Gravity.START else Gravity.CENTER; setTextIsSelectable(true)
        }
        card.addView(m, Ui.lpm(a, t = 6, b = 14))
        build(card, d)
        val maxW = minOf(a.resources.displayMetrics.widthPixels - Ui.dp(a, 24), Ui.dp(a, 560))
        outer.addView(card, FrameLayout.LayoutParams(maxW, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
        d.setContentView(outer)
        d.window?.let { w ->
            w.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            w.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            w.setGravity(Gravity.BOTTOM)
            w.setDimAmount(0.45f)
            w.attributes = w.attributes.apply { y = Ui.dp(a, 24) }
        }
        // หน้าจอกำลังปิด/ถูกทำลายแล้ว → ไม่แสดง (กันแอปหลุดจาก BadTokenException)
        if (a.isFinishing || a.isDestroyed) return d
        try { d.show() } catch (e: Exception) { Bridge.log("popup: $e"); return d }
        Fx.enter(card)
        Fx.breathe(orb, 1.1f, 1100)
        return d
    }

    private fun buttons(a: Activity, card: LinearLayout, vararg b: View) {
        val r = Ui.row(a)
        r.gravity = Gravity.CENTER
        b.forEachIndexed { i, v -> r.addView(v, Ui.lp(0, weight = 1f).apply { if (i > 0) marginStart = Ui.dp(a, 10) }) }
        card.addView(r, Ui.lp())
    }

    fun confirm(a: Activity, id: Int, text: String): Dialog = sheet(a, "🛡️", "ขออนุญาตก่อนนะ", text) { card, d ->
        buttons(a, card,
            Ui.button(a, "ยกเลิก") { Bridge.answer(id, false, null); d.dismiss() },
            Ui.button(a, "✅ อนุญาต", true) { Bridge.answer(id, true, null); d.dismiss() })
    }.also { it.setOnCancelListener { _ -> Bridge.answer(id, false, null) } }

    fun ask(a: Activity, id: Int, text: String): Dialog = sheet(a, "💬", "ผู้ช่วยถาม", text) { card, d ->
        val inp = Ui.input(a, "พิมพ์คำตอบ… (ข้าม = เว้นว่าง)")
        card.addView(inp, Ui.lpm(a, b = 12))
        buttons(a, card,
            Ui.button(a, "ยกเลิก") { Bridge.answer(id, false, null); d.dismiss() },
            Ui.button(a, "ส่งคำตอบ", true) { Bridge.answer(id, true, inp.text.toString()); d.dismiss() })
        inp.requestFocus()
    }.also { it.setOnCancelListener { _ -> Bridge.answer(id, false, null) } }

    data class Field(val key: String, val label: String, val value: String = "", val secret: Boolean = false,
                     val hint: String = "")

    /** ฟอร์มป๊อปอัป (ใส่คีย์ / ตั้งชื่อ ฯลฯ) — กดบันทึกได้ค่าเป็น map, ยกเลิก = onCancel */
    fun form(a: Activity, emoji: String, title: String, msg: String, fields: List<Field>,
             onCancel: () -> Unit = {}, onSave: (Map<String, String>) -> Unit): Dialog {
        val inputs = LinkedHashMap<String, android.widget.EditText>()
        var saved = false
        val d = sheet(a, emoji, title, msg) { card, dlg ->
            for (f in fields) {
                card.addView(Ui.text(a, f.label, 13f, true, Ui.TEXT), Ui.lpm(a, t = 4))
                val e = Ui.input(a, f.hint.ifEmpty { f.label }, secret = f.secret)
                e.setText(f.value)
                inputs[f.key] = e
                card.addView(e, Ui.lpm(a, t = 4, b = 8))
            }
            buttons(a, card,
                Ui.button(a, "ยกเลิก") { dlg.dismiss() },
                Ui.button(a, "💾 บันทึก", true) {
                    saved = true
                    onSave(inputs.mapValues { it.value.text.toString().trim() })
                    dlg.dismiss()
                })
            inputs.values.firstOrNull()?.requestFocus()
        }
        d.setOnDismissListener { if (!saved) onCancel() }
        return d
    }

    /** เลือก 1 จากหลายตัวเลือก (ปุ่มใหญ่) */
    /** แผ่นล่างแบบกำหนดเนื้อหาเอง (เช่น ตารางปุ่มลัด) */
    fun panel(a: Activity, emoji: String, title: String, build: (LinearLayout, Dialog) -> Unit): Dialog = sheet(a, emoji, title, "", build)

    fun choose(a: Activity, emoji: String, title: String, msg: String, options: List<Pair<String, () -> Unit>>): Dialog =
        sheet(a, emoji, title, msg) { card, dlg ->
            for ((label, fn) in options) {
                card.addView(Ui.button(a, label, options.first().first == label) { dlg.dismiss(); fn() }, Ui.lpm(a, b = 8))
            }
            card.addView(Ui.button(a, "ยกเลิก") { dlg.dismiss() })
        }

    /** รายการให้เลือก (มีช่องค้นหา) เช่น เลือกแอป */
    fun pick(a: Activity, emoji: String, title: String, items: List<Pair<String, String>>, onPick: (String, String) -> Unit): Dialog =
        sheet(a, emoji, title, "แตะเพื่อเลือก") { card, dlg ->
            val q = Ui.input(a, "🔎 ค้นหา…")
            card.addView(q, Ui.lpm(a, b = 8))
            val listBox = Ui.col(a, 0)
            val sv = android.widget.ScrollView(a)
            sv.addView(listBox)
            card.addView(sv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 320)))
            fun fill(f: String) {
                listBox.removeAllViews()
                for ((label, value) in items.filter { f.isBlank() || it.first.contains(f, true) }.take(150)) {
                    listBox.addView(Ui.text(a, label, 15.5f).apply {
                        setPadding(Ui.dp(a, 12), Ui.dp(a, 11), Ui.dp(a, 12), Ui.dp(a, 11))
                        background = Ui.ripple(Ui.round(Color.WHITE, Ui.dpf(a, 10f)))
                        setOnClickListener { dlg.dismiss(); onPick(label, value) }
                    }, Ui.lpm(a, b = 2))
                }
            }
            fill("")
            q.addTextChangedListener(object : android.text.TextWatcher {
                override fun afterTextChanged(e: android.text.Editable?) { fill(e?.toString() ?: "") }
                override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, af: Int) {}
                override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
            })
            card.addView(Ui.button(a, "ยกเลิก") { dlg.dismiss() }, Ui.lpm(a, t = 8))
        }

    fun info(a: Activity, emoji: String, title: String, text: String): Dialog = sheet(a, emoji, title, text) { card, d ->
        buttons(a, card, Ui.button(a, "เข้าใจแล้ว", true) { d.dismiss() })
    }

    /** แถบแจ้งเตือนเล็กเลื่อนลงจากบน (ในแอป) หายเองใน 2.5 วิ */
    fun snack(a: Activity, text: String) {
        val root = a.window.decorView as? FrameLayout ?: return
        val t = Ui.text(a, text, 14.5f, false, Color.WHITE).apply {
            background = Ui.round(Ui.INK, Ui.dpf(a, 24f))                 // แจ้งเตือนสั้นสีเข้ม
            setPadding(Ui.dp(a, 18), Ui.dp(a, 10), Ui.dp(a, 18), Ui.dp(a, 10))
            elevation = Ui.dpf(a, 8f)
        }
        root.addView(t, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply { topMargin = Ui.dp(a, 56) })
        t.translationY = -Ui.dpf(a, 80f); t.alpha = 0f
        t.animate().translationY(0f).alpha(1f).setDuration(280).start()
        t.postDelayed({
            t.animate().translationY(-Ui.dpf(a, 80f)).alpha(0f).setDuration(260).withEndAction { root.removeView(t) }.start()
        }, 2500)
    }
}

/** ป๊อปอัปลอยเหนือแอปอื่น (แบบผู้ช่วยมือถือ): กำลังฟัง / กำลังคิด / คำตอบ / ขออนุญาต */
object Overlay {
    private val main = Handler(Looper.getMainLooper())
    private var view: View? = null
    private var titleV: TextView? = null
    private var textV: TextView? = null
    private var btnRow: LinearLayout? = null
    private var orbAnim: Animator? = null
    private var promptId = -1
    private val hideTask = Runnable { hideNow() }

    private fun ctx(): Context = Bridge.app

    fun allowed(): Boolean = Settings.canDrawOverlays(ctx()) &&
        ctx().getSharedPreferences("app", Context.MODE_PRIVATE).getBoolean("popup", true)

    private fun ensure(): Boolean {
        if (view != null) return true
        if (!allowed()) return false
        val c = ctx()
        val wm = c.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val card = Ui.card(c, 14, 24)
        card.background = Ui.round(Color.WHITE, Ui.dpf(c, 24f), Ui.P200, Ui.dp(c, 1))
        card.elevation = Ui.dpf(c, 12f)
        val top = Ui.row(c)
        val orb = android.widget.ImageView(c).apply {
            setImageResource(R.drawable.ic_launcher)                       // โลโก้แบบ B
            clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(v: android.view.View, o: android.graphics.Outline) {
                    o.setRoundRect(0, 0, v.width, v.height, Ui.dpf(c, 12f))
                }
            }
        }
        top.addView(orb, LinearLayout.LayoutParams(Ui.dp(c, 46), Ui.dp(c, 46)).apply { marginEnd = Ui.dp(c, 12) })
        val tc = Ui.col(c, 0)
        titleV = Ui.text(c, "", 14f, true, Ui.TEXT)
        textV = Ui.text(c, "", 15.5f, false, Ui.TEXT).apply { maxLines = 6 }
        tc.addView(titleV); tc.addView(textV)
        top.addView(tc, Ui.lp(0, weight = 1f))
        top.addView(Ui.text(c, "✕", 18f, false, Ui.SUB).apply {
            setPadding(Ui.dp(c, 10), Ui.dp(c, 4), Ui.dp(c, 4), Ui.dp(c, 4))
            setOnClickListener { if (promptId >= 0) Bridge.answer(promptId, false, null); hideNow() }
        })
        card.addView(top)
        btnRow = Ui.row(c).apply { visibility = View.GONE; gravity = Gravity.END }
        card.addView(btnRow, Ui.lpm(c, t = 10))
        card.setOnClickListener {
            c.startActivity(Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            if (promptId < 0) hideNow()
        }
        // ปัดขึ้นเพื่อปิด
        var y0 = 0f
        card.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { y0 = e.rawY; false }
                MotionEvent.ACTION_MOVE -> { val dy = e.rawY - y0; if (dy < 0) v.translationY = dy; dy < -10 }
                MotionEvent.ACTION_UP -> {
                    if (e.rawY - y0 < -Ui.dpf(c, 50f)) { if (promptId >= 0) Bridge.answer(promptId, false, null); hideNow(); true }
                    else { v.animate().translationY(0f).setDuration(150).start(); false }
                }
                else -> false
            }
        }
        val frame = FrameLayout(c)
        val w = minOf(c.resources.displayMetrics.widthPixels - Ui.dp(c, 24), Ui.dp(c, 560))
        frame.addView(card, FrameLayout.LayoutParams(w, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_HORIZONTAL))
        frame.setPadding(0, Ui.dp(c, 6), 0, Ui.dp(c, 16))
        val lp = WindowManager.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        lp.y = Ui.dp(c, 28)
        return try {
            wm.addView(frame, lp)
            view = frame
            card.translationY = -Ui.dpf(c, 120f); card.alpha = 0f
            card.animate().translationY(0f).alpha(1f).setDuration(340)
                .setInterpolator(android.view.animation.OvershootInterpolator(1.1f)).start()
            orbAnim = Fx.breathe(orb, 1.12f, 900)
            true
        } catch (e: Exception) {
            Bridge.log("overlay: $e"); false
        }
    }

    private fun set(title: String, text: String) {
        titleV?.text = Ui.clean(title)
        textV?.text = text
    }

    /** สถานะจากผู้ช่วยเสียง (ui.py) */
    fun show(title: String, text: String, ongoing: Boolean) = main.post {
        if (MainActivity.visible) { ChatLog.setMood(title, text, ongoing); return@post }
        if (promptId >= 0) return@post                   // กำลังถามอยู่ ไม่ทับ
        if (!ensure()) return@post
        set(title, text)
        btnRow?.visibility = View.GONE
        main.removeCallbacks(hideTask)
        if (!ongoing) main.postDelayed(hideTask, 7000)
    }

    fun hide() = main.post {
        ChatLog.setMood("", "", false)
        if (promptId < 0) hideNow()
    }

    fun confirm(id: Int, text: String) = main.post {
        if (MainActivity.visible || !ensure()) return@post
        promptId = id
        main.removeCallbacks(hideTask)
        set("🛡️ ขออนุญาต", text)
        val c = ctx()
        btnRow?.let { r ->
            r.removeAllViews()
            r.addView(Ui.button(c, "ยกเลิก") { Bridge.answer(id, false, null) })
            r.addView(Ui.button(c, "✅ อนุญาต", true) { Bridge.answer(id, true, null) }, Ui.lpm(c, s = 10, w = ViewGroup.LayoutParams.WRAP_CONTENT))
            r.visibility = View.VISIBLE
        }
    }

    fun ask(id: Int, text: String) = main.post {
        if (MainActivity.visible || !ensure()) return@post
        promptId = id
        main.removeCallbacks(hideTask)
        set("💬 ผู้ช่วยถาม", text)
        val c = ctx()
        btnRow?.let { r ->
            r.removeAllViews()
            r.addView(Ui.button(c, "ตอบในแอป", true) {
                c.startActivity(Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                hideNow()
            })
            r.visibility = View.VISIBLE
        }
    }

    /** คำถาม/ขออนุญาตนี้ตอบแล้ว → ปิดป๊อปอัป */
    fun answered(id: Int) = main.post { if (promptId == id) { promptId = -1; hideNow() } }

    private fun hideNow() {
        val v = view ?: return
        view = null
        promptId = -1
        orbAnim?.cancel()
        main.removeCallbacks(hideTask)
        val wm = ctx().getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val card = (v as FrameLayout).getChildAt(0)
        card.animate().translationY(-Ui.dpf(ctx(), 120f)).alpha(0f).setDuration(220).withEndAction {
            try { wm.removeView(v) } catch (_: Exception) {}
        }.start()
    }
}
