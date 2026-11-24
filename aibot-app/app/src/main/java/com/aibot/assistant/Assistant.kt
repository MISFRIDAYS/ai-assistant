package com.aibot.assistant

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.service.quicksettings.TileService
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.animation.OvershootInterpolator
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/** จุดสี่สีขยับตามสถานะ (แบบ Google Assistant): ฟัง = เต้นตามเสียงพูด · คิด = หมุนวน · พูด = คลื่น */
class AssistantDots(c: Context) : View(c) {
    var state = "idle"
    private val colors = intArrayOf(Ui.P700, Ui.P500, Ui.PINK, Ui.P300)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()
    private val start = SystemClock.uptimeMillis()
    private val levels = FloatArray(4)
    private val dot = Ui.dpf(c, 13f)
    private val gap = Ui.dpf(c, 9f)

    override fun onMeasure(w: Int, h: Int) {
        setMeasuredDimension(resolveSize(Ui.dp(context, 120), w), resolveSize(Ui.dp(context, 64), h))
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val t = (SystemClock.uptimeMillis() - start) / 1000f
        val cx = width / 2f
        val cy = height / 2f
        val total = 4 * dot + 3 * gap
        val mic = min(1f, Mic.level / 1800f)
        for (i in 0 until 4) {
            paint.color = colors[i]
            var x = cx - total / 2 + i * (dot + gap) + dot / 2
            var y = cy
            var hgt = dot
            when (state) {
                "listen" -> {                                       // เต้นตามความดังเสียงพูด
                    val target = dot + mic * Ui.dpf(context, 34f) * (0.6f + 0.4f * sin(t * 9f + i * 1.7f).toFloat())
                    levels[i] += (max(dot, target) - levels[i]) * 0.35f
                    hgt = max(dot, levels[i])
                }
                "think" -> {                                        // หมุนเป็นวง
                    val a = t * 5.0 + i * PI / 2
                    val r = Ui.dpf(context, 16f)
                    x = cx + (r * cos(a)).toFloat()
                    y = cy + (r * sin(a)).toFloat()
                }
                "speak" -> {                                        // คลื่นขึ้นลง
                    y = cy + Ui.dpf(context, 9f) * sin(t * 6.5f + i * 0.9f).toFloat()
                    hgt = dot + Ui.dpf(context, 6f) * (0.5f + 0.5f * sin(t * 8f + i).toFloat())
                }
                "error" -> paint.color = if (i % 2 == 0) Ui.BAD else 0xFFFB7185.toInt()
                else -> {                                           // หายใจเบาๆ
                    val s = 1f + 0.12f * sin(t * 2.5f + i * 0.6f).toFloat()
                    hgt = dot * s
                }
            }
            val w = if (state == "idle" || state == "heard" || state == "done") hgt else dot
            rect.set(x - w / 2, y - hgt / 2, x + w / 2, y + hgt / 2)
            canvas.drawRoundRect(rect, w / 2, w / 2, paint)
        }
        if (isAttachedToWindow) postInvalidateOnAnimation()
    }
}

/** แผงผู้ช่วยลอยด้านล่างจอ (เหนือแอปอื่น) เวลาพูดสั่งงาน */
object AssistantPanel {
    private val main = Handler(Looper.getMainLooper())
    private var root: FrameLayout? = null
    private var card: View? = null
    private var dots: AssistantDots? = null
    private var bigText: TextView? = null
    private var hint: TextView? = null
    private val hideTask = Runnable { hideNow() }

    private fun ctx(): Context = Bridge.app

    private fun ensure(): Boolean {
        if (root != null) return true
        if (!Overlay.allowed()) return false
        val c = ctx()
        val wm = c.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val panel = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            val r = Ui.dpf(c, 30f)
            background = GradientDrawable().apply {
                setColor(Color.WHITE); cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
            }
            elevation = Ui.dpf(c, 16f)
            setPadding(Ui.dp(c, 22), Ui.dp(c, 10), Ui.dp(c, 22), Ui.dp(c, 18))
        }
        // ขีดจับด้านบน
        panel.addView(View(c).apply { background = Ui.round(Ui.P200, Ui.dpf(c, 3f)) },
            LinearLayout.LayoutParams(Ui.dp(c, 44), Ui.dp(c, 5)).apply { bottomMargin = Ui.dp(c, 10) })
        val head = Ui.row(c)
        head.addView(Ui.text(c, "✨ ผู้ช่วย AI", 13.5f, true, Ui.P600), Ui.lp(0, weight = 1f))
        head.addView(Ui.text(c, "✕", 18f, false, Ui.SUB).apply {
            setPadding(Ui.dp(c, 12), Ui.dp(c, 4), Ui.dp(c, 4), Ui.dp(c, 4))
            setOnClickListener { stopVoice(); hideNow() }
        })
        panel.addView(head, Ui.lp())
        bigText = Ui.text(c, "", 21f, false, Ui.TEXT).apply {
            maxLines = 7; gravity = Gravity.START
            setLineSpacing(0f, 1.15f)
        }
        panel.addView(bigText, Ui.lpm(c, t = 8))
        hint = Ui.text(c, "", 13.5f, false, Ui.SUB)
        panel.addView(hint, Ui.lpm(c, t = 4, b = 6))
        // แถวล่าง: คีย์บอร์ด · จุดสี/ไมค์ · ปิด
        val bottom = FrameLayout(c)
        val kb = Ui.text(c, "", 22f).apply {
            gravity = Gravity.CENTER; contentDescription = "เปิดแอปผู้ช่วย"
            foreground = c.getDrawable(R.drawable.ic_e_keyboard)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(c, 12)) }
            background = Ui.ripple(Ui.oval(Ui.P100, Ui.P100))
            setOnClickListener { openApp(); hideNow() }
        }
        bottom.addView(kb, FrameLayout.LayoutParams(Ui.dp(c, 48), Ui.dp(c, 48), Gravity.START or Gravity.CENTER_VERTICAL))
        dots = AssistantDots(c).apply {
            isClickable = true
            setOnClickListener { Fx.press(this); listenAgain() }
        }
        bottom.addView(dots, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, Ui.dp(c, 72), Gravity.CENTER))
        val micBtn = Ui.text(c, "", 22f).apply {
            gravity = Gravity.CENTER; contentDescription = "พูดอีกครั้ง"
            foreground = c.getDrawable(R.drawable.ic_ui_mic)?.let { android.graphics.drawable.InsetDrawable(it, Ui.dp(c, 12)) }
            background = Ui.ripple(Ui.oval(Ui.P500, Ui.PINK), 0x55FFFFFF)
            setOnClickListener { Fx.press(this); listenAgain() }
        }
        bottom.addView(micBtn, FrameLayout.LayoutParams(Ui.dp(c, 48), Ui.dp(c, 48), Gravity.END or Gravity.CENTER_VERTICAL))
        panel.addView(bottom, Ui.lp())

        val frame = FrameLayout(c)
        val w = min(c.resources.displayMetrics.widthPixels, Ui.dp(c, 680))
        frame.addView(panel, FrameLayout.LayoutParams(w, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL))
        frame.setOnTouchListener { _, e ->
            if (e.action == MotionEvent.ACTION_OUTSIDE) { if (dots?.state != "listen" && dots?.state != "think") hideNow(); true } else false
        }
        // ปัดลงเพื่อปิด
        var y0 = 0f
        panel.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { y0 = e.rawY; true }
                MotionEvent.ACTION_MOVE -> { val dy = e.rawY - y0; if (dy > 0) v.translationY = dy; true }
                MotionEvent.ACTION_UP -> {
                    if (e.rawY - y0 > Ui.dpf(c, 70f)) { stopVoice(); hideNow() }
                    else v.animate().translationY(0f).setDuration(160).start()
                    true
                }
                else -> false
            }
        }
        val lp = WindowManager.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH or WindowManager.LayoutParams.FLAG_DIM_BEHIND or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.BOTTOM
        lp.dimAmount = 0.28f
        return try {
            wm.addView(frame, lp)
            root = frame; card = panel
            panel.translationY = Ui.dpf(c, 320f)
            panel.animate().translationY(0f).setDuration(380).setInterpolator(OvershootInterpolator(0.9f)).start()
            true
        } catch (e: Exception) {
            Bridge.log("assistant panel: $e"); false
        }
    }

    /** สถานะจากผู้ช่วยเสียง: listen / heard / think / speak / done / idle / error */
    fun update(state: String, text: String) = main.post {
        if (MainActivity.visible) {                              // อยู่ในแอป → ใช้หัวแชทแทน
            when (state) {
                "listen" -> ChatLog.setMood("🎙️ กำลังฟัง…", "", true)
                "heard" -> ChatLog.setMood("💬", text, true)
                "think" -> ChatLog.setMood("💭 กำลังคิด…", text, true)
                "speak" -> ChatLog.setMood("🔊", text.take(80), true)
                else -> ChatLog.setMood("", "", false)
            }
            return@post
        }
        if (state == "idle") {
            val cur = dots?.state
            if (cur != "error" && cur != "done") {                  // ข้อความผิดพลาด/คำตอบ ให้ค้างไว้อ่านก่อน
                if (root != null) { main.removeCallbacks(hideTask); main.postDelayed(hideTask, 2500) }
                dots?.state = "idle"
            }
            return@post
        }
        if (!ensure()) return@post
        main.removeCallbacks(hideTask)
        dots?.state = state
        when (state) {
            "listen" -> { hint?.text = "กำลังฟัง… พูดได้เลย"; if (bigText?.text.isNullOrEmpty()) bigText?.text = "สวัสดีครับ มีอะไรให้ช่วยไหม?" }
            "heard" -> { bigText?.text = text; hint?.text = "" }
            "think" -> { hint?.text = if (text.isBlank()) "กำลังคิด…" else text }
            "speak" -> { bigText?.text = text; hint?.text = "" }
            "done" -> { if (text.isNotBlank()) bigText?.text = text; hint?.text = "แตะปุ่มไมค์เพื่อสั่งต่อ"; main.postDelayed(hideTask, 9000) }
            "error" -> { bigText?.text = text; hint?.text = "แตะปุ่มไมค์เพื่อลองอีกครั้ง"; main.postDelayed(hideTask, 8000) }
        }
        bigText?.let { if (state == "heard" || state == "speak") Fx.enter(it) }
    }

    private fun openApp() {
        val c = ctx()
        c.startActivity(Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun listenAgain() {
        bigText?.text = ""
        val c = ctx()
        c.startActivity(Intent(c, ListenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION))
    }

    private fun stopVoice() {
        try { Player.stop() } catch (_: Exception) {}
    }

    fun hideNow() {
        val r = root ?: return
        root = null
        main.removeCallbacks(hideTask)
        val wm = ctx().getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val p = card
        card = null; dots = null
        if (p == null) { try { wm.removeView(r) } catch (_: Exception) {}; return }
        p.animate().translationY(p.height.toFloat() + 40f).setDuration(240).withEndAction {
            try { wm.removeView(r) } catch (_: Exception) {}
        }.start()
    }
}

/** หน้าโปร่งใส: เรียกผู้ช่วยฟังคำสั่งทันที (จาก Quick Settings / แจ้งเตือน / ปุ่มไมค์บนแผง) แล้วปิดตัวเอง */
class ListenActivity : Activity() {
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        if (!Bridge.isEnabled()) Bridge.setEnabled(true)          // สั่งด้วยเสียงตอนปิดอยู่ = เปิดให้เลย
        BotService.start(this)
        Thread {
            try { App.py(this).getModule("android_main").callAttr("panel_listen") } catch (e: Throwable) {
                Bridge.log("panel_listen: $e")
                AssistantPanel.update("error", "เริ่มฟังไม่ได้: ${e.message?.take(160)}")
            }
        }.start()
        // อยู่บนจอสักครู่ให้ระบบนับว่าแอป "ใช้งานอยู่" (ได้สิทธิ์ไมค์) แล้วค่อยปิด
        Handler(Looper.getMainLooper()).postDelayed({ finish(); overridePendingTransition(0, 0) }, 700)
    }
}

/** ปุ่มใน Quick Settings (ปัดแถบด้านบนลง): แตะแล้วสั่งด้วยเสียงได้ทันที */
class AssistTile : TileService() {
    override fun onClick() {
        super.onClick()
        val i = Intent(this, ListenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            val pi = android.app.PendingIntent.getActivity(this, 9, i,
                android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
            startActivityAndCollapse(pi)
        } else {
            @Suppress("DEPRECATION") startActivityAndCollapse(i)
        }
    }
}
