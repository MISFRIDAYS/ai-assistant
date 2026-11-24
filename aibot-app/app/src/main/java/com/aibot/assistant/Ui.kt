package com.aibot.assistant

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.animation.ValueAnimator
import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.animation.DecelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** ธีมใหม่ (โลโก้แบบ B): พื้นอ่อน + สีหลักสีเดียว + การ์ดขาวมีขอบ + หัวข้อฟอนต์ Prompt */
object Ui {
    // ---------------------------------------------------------------- สี
    const val INK = 0xFF17142B.toInt()            // สีโลโก้ / ตัวอักษรหลัก
    const val P900 = INK
    const val P700 = 0xFF3A27AE.toInt()
    const val P600 = 0xFF4B34D6.toInt()
    const val P500 = 0xFF5B3FF0.toInt()           // สีหลัก
    const val P400 = 0xFF7B66F5.toInt()
    const val P300 = 0xFFC9C0FB.toInt()
    const val P200 = 0xFFE4E1F0.toInt()           // เส้นขอบการ์ด
    const val P100 = 0xFFF1EEFF.toInt()
    const val P50 = 0xFFF6F5FB.toInt()            // พื้นหลังทุกหน้า
    const val PINK = P500                         // เลิกใช้ไล่สีม่วง-ชมพู → สีเดียว
    const val LINE = 0xFFDAD6EA.toInt()
    const val WHITE = Color.WHITE
    const val TEXT = INK
    const val SUB = 0xFF6B6584.toInt()
    const val OK = 0xFF1E7A4F.toInt()
    const val WARN = 0xFFF59E0B.toInt()
    const val BAD = 0xFFE11D48.toInt()
    const val ACCENT = P500

    // ใช้กับโค้ดเดิม
    fun bg(c: Context) = P50
    fun fg(c: Context) = TEXT

    fun dp(c: Context, v: Int): Int = (v * c.resources.displayMetrics.density).toInt()
    fun dpf(c: Context, v: Float): Float = v * c.resources.displayMetrics.density

    // ---------------------------------------------------------------- พื้นหลัง
    fun round(color: Int, r: Float, stroke: Int = 0, strokeW: Int = 2): GradientDrawable =
        GradientDrawable().apply { setColor(color); cornerRadius = r; if (stroke != 0) setStroke(strokeW, stroke) }

    fun grad(r: Float, vararg colors: Int, orient: GradientDrawable.Orientation = GradientDrawable.Orientation.TL_BR) =
        GradientDrawable(orient, colors).apply { cornerRadius = r }

    fun corners(color: Int, tl: Float, tr: Float, br: Float, bl: Float) = GradientDrawable().apply {
        setColor(color); cornerRadii = floatArrayOf(tl, tl, tr, tr, br, br, bl, bl)
    }

    fun ripple(content: Drawable, rippleColor: Int = 0x337C3AED): RippleDrawable =
        RippleDrawable(ColorStateList.valueOf(rippleColor), content, null)

    fun oval(vararg colors: Int) = GradientDrawable(GradientDrawable.Orientation.TL_BR, colors).apply {
        shape = GradientDrawable.OVAL
    }

    fun statusBar(a: Activity, @Suppress("UNUSED_PARAMETER") color: Int = P50) {
        a.window.statusBarColor = P50                 // แถบบนสีเดียวกับพื้น ไอคอนสีเข้ม
        a.window.navigationBarColor = P50
        @Suppress("DEPRECATION")
        a.window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR or View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
    }

    // ---------------------------------------------------------------- อีโมจิ → ไอคอนเส้น (ดีไซน์ใหม่ ไม่ใช้อีโมจิในหน้าแอป)
    val ICONS: Map<String, Int> = mapOf(
        "✨" to R.drawable.ic_e_sparkle,
        "💬" to R.drawable.ic_ui_chat,
        "🎤" to R.drawable.ic_ui_micline,
        "🎙️" to R.drawable.ic_ui_micline,
        "✅" to R.drawable.ic_e_check2,
        "❗" to R.drawable.ic_e_warn,
        "🤖" to R.drawable.ic_e_sparkle,
        "🔄" to R.drawable.ic_e_refresh,
        "🎬" to R.drawable.ic_e_film,
        "⏸️" to R.drawable.ic_e_pause,
        "📱" to R.drawable.ic_ui_phone,
        "🔎" to R.drawable.ic_e_search,
        "🔍" to R.drawable.ic_e_search,
        "🗑️" to R.drawable.ic_e_trash,
        "📋" to R.drawable.ic_e_clipboard,
        "🫧" to R.drawable.ic_e_sparkle,
        "🌙" to R.drawable.ic_e_moon,
        "🧠" to R.drawable.ic_e_cpu,
        "📷" to R.drawable.ic_e_camera,
        "📸" to R.drawable.ic_e_camera,
        "🛠️" to R.drawable.ic_e_wrench,
        "🔐" to R.drawable.ic_e_shield,
        "🛡️" to R.drawable.ic_e_shield,
        "⌨️" to R.drawable.ic_e_keyboard,
        "🔔" to R.drawable.ic_ui_bell,
        "⚡" to R.drawable.ic_e_bolt,
        "☁️" to R.drawable.ic_e_cloud,
        "📝" to R.drawable.ic_e_edit,
        "✏️" to R.drawable.ic_e_edit,
        "✍️" to R.drawable.ic_e_edit,
        "🧰" to R.drawable.ic_e_toolbox,
        "⚙️" to R.drawable.ic_ui_settings,
        "💾" to R.drawable.ic_e_save,
        "⏳" to R.drawable.ic_e_hourglass,
        "📚" to R.drawable.ic_e_doc,
        "🧭" to R.drawable.ic_e_compass,
        "📜" to R.drawable.ic_e_doc,
        "⏻" to R.drawable.ic_ui_power,
        "⚠️" to R.drawable.ic_e_warn,
        "👥" to R.drawable.ic_e_users,
        "♿" to R.drawable.ic_e_access,
        "🙏" to R.drawable.ic_e_heart,
        "🔋" to R.drawable.ic_ui_battery,
        "🔊" to R.drawable.ic_e_volup,
        "🔉" to R.drawable.ic_e_voldown,
        "🔇" to R.drawable.ic_e_mute,
        "🧩" to R.drawable.ic_e_puzzle,
        "👂" to R.drawable.ic_e_ear,
        "📬" to R.drawable.ic_e_inbox,
        "✉️" to R.drawable.ic_e_mail,
        "❌" to R.drawable.ic_e_circlex,
        "💥" to R.drawable.ic_e_warn,
        "🔑" to R.drawable.ic_e_key,
        "📞" to R.drawable.ic_ui_phone,
        "📍" to R.drawable.ic_e_pin,
        "📅" to R.drawable.ic_ui_calendar,
        "💭" to R.drawable.ic_ui_chat,
        "📊" to R.drawable.ic_e_chart,
        "♻️" to R.drawable.ic_e_refresh,
        "🔒" to R.drawable.ic_e_lock,
        "🎵" to R.drawable.ic_ui_music,
        "🗣️" to R.drawable.ic_e_wave,
        "👋" to R.drawable.ic_e_hand,
        "✋" to R.drawable.ic_e_hand,
        "🩺" to R.drawable.ic_e_pulse,
        "📄" to R.drawable.ic_e_doc,
        "🌗" to R.drawable.ic_e_contrast,
        "👁️" to R.drawable.ic_e_eye,
        "👀" to R.drawable.ic_e_eye,
        "🍃" to R.drawable.ic_e_leaf,
        "📎" to R.drawable.ic_e_clip,
        "🖼️" to R.drawable.ic_e_image,
        "⬇️" to R.drawable.ic_e_download,
        "⏹" to R.drawable.ic_e_stop,
        "➕" to R.drawable.ic_e_plus,
        "🎉" to R.drawable.ic_e_sparkle,
        "📁" to R.drawable.ic_e_folder,
        "☀️" to R.drawable.ic_e_sun,
        "🌤️" to R.drawable.ic_e_sun,
        "🖥️" to R.drawable.ic_e_monitor,
        "⭐" to R.drawable.ic_e_star,
        "🛟" to R.drawable.ic_e_lifebuoy,
        "💎" to R.drawable.ic_e_star,
        "👨" to R.drawable.ic_e_user,
        "👩" to R.drawable.ic_e_user,
        "🔗" to R.drawable.ic_e_link,
        "↩️" to R.drawable.ic_e_undo,
        "⏪" to R.drawable.ic_e_undo,
        "🌐" to R.drawable.ic_e_globe,
        "📶" to R.drawable.ic_e_wifi,
        "🔷" to R.drawable.ic_e_bluetooth,
        "🔦" to R.drawable.ic_e_flashlight,
        "🔆" to R.drawable.ic_e_sun,
        "🔅" to R.drawable.ic_e_sundim,
        "🎨" to R.drawable.ic_e_palette,
        "📰" to R.drawable.ic_e_news,
        "✈️" to R.drawable.ic_e_plane,
        "🙂" to R.drawable.ic_e_smile,
        "🔭" to R.drawable.ic_e_telescope,
        "🧪" to R.drawable.ic_e_flask,
        "🎁" to R.drawable.ic_e_gift,
        "📦" to R.drawable.ic_e_box,
        "➤" to R.drawable.ic_e_send2,
        "❓" to R.drawable.ic_e_help,
        "⏰" to R.drawable.ic_ui_alarm,
        "🙋" to R.drawable.ic_e_user,
        "⏱️" to R.drawable.ic_ui_timer,
        "📲" to R.drawable.ic_ui_phone,
    )

    /** ไอคอนเส้นของอีโมจินี้ (ไม่มีในชุด → ประกายดาว) */
    fun iconOf(emoji: String?): Int = ICONS[emoji?.trim()] ?: ICONS[emoji?.trim()?.replace("\uFE0F", "")] ?: R.drawable.ic_e_sparkle

    /** ช่องไอคอนเส้น: ไอคอนสี tint บนพื้น bg มุมโค้ง */
    fun iconTile(c: Context, emoji: String?, sizeDp: Int = 48, tint: Int = P700, bg: Int = P100): android.widget.ImageView =
        android.widget.ImageView(c).apply {
            setImageResource(iconOf(emoji)); scaleType = android.widget.ImageView.ScaleType.CENTER
            imageTintList = ColorStateList.valueOf(tint)
            background = round(bg, dpf(c, sizeDp * 0.3f))
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }

    // คำแทนอีโมจิที่อยู่กลางประโยค (ลบทิ้งแล้วความหมายหาย)
    private val INLINE = listOf("✅" to "✓", "❌" to "✕", "✔️" to "✓", "☑️" to "✓", "🤖" to "ผู้ช่วย", "⏻" to "เปิด/ปิด", "🔐" to "สิทธิ์", "🧰" to "เครื่องมือ",
        "⚙️" to "ตั้งค่า", "🎤" to "ไมค์", "🫧" to "ปุ่มลอย")
    private val ANY_EMOJI = Regex("[\\x{1F000}-\\x{1FAFF}\\x{2300}-\\x{23FF}\\x{2600}-\\x{26FF}\\x{2B00}-\\x{2BFF}" +
        "\\x{2700}-\\x{2711}\\x{2714}\\x{2716}-\\x{27BF}\\x{FE0F}\\x{200D}\\x{20E3}]")

    /** ตัดอีโมจิทั้งข้อความ (ป้าย/ปุ่ม/คำอธิบาย) — เก็บ → ✓ ✕ ไว้ · อีโมจิกลางประโยคบางตัวแทนด้วยคำ */
    fun clean(s: CharSequence?): String {
        if (s.isNullOrEmpty()) return ""
        var t = s.toString()
        for ((e, w) in INLINE.take(4)) t = t.replace(e, w)            // เครื่องหมายผ่าน/ไม่ผ่าน ต้องอยู่รอด
        t = plain(t)
        for ((e, w) in INLINE) t = t.replace(e, w)
        t = t.replace(ANY_EMOJI, "")
        t = t.lines().joinToString("\n") { it.replace(Regex("[ \t]{2,}"), " ").trimEnd() }
        return if (t.isBlank()) s.toString() else t.trim()
    }

    // ---------------------------------------------------------------- ตัดอีโมจินำหน้า
    private val LEAD_EMOJI = Regex("^(?:[\\x{1F000}-\\x{1FAFF}\\x{2190}-\\x{21FF}\\x{2300}-\\x{23FF}\\x{2600}-\\x{26FF}" +
        "\\x{2B00}-\\x{2BFF}\\x{2700}-\\x{2711}\\x{2714}\\x{2716}-\\x{27BF}\\x{FE0F}\\x{200D}\\x{20E3}]+\\s*)+")

    /** "🔄 รีเฟรช" → "รีเฟรช" (ถ้าเหลือแต่อีโมจิ คืนของเดิม) */
    fun plain(s: String): String {
        val t = s.replace(LEAD_EMOJI, "")
        return if (t.isBlank()) s else t
    }

    // ---------------------------------------------------------------- ฟอนต์หัวข้อ (Prompt)
    @Volatile private var heading: Typeface? = null
    fun headingFont(c: Context): Typeface {
        heading?.let { return it }
        val t = try { c.applicationContext.resources.getFont(R.font.prompt_semibold) }
                catch (_: Exception) { Typeface.create("sans-serif-medium", Typeface.BOLD) }
        heading = t
        return t
    }

    // ---------------------------------------------------------------- วิว
    fun col(c: Context, pad: Int = 12): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        val p = dp(c, pad); setPadding(p, p, p, p)
    }

    fun row(c: Context): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun text(c: Context, s: String, size: Float = 15f, bold: Boolean = false, color: Int? = null,
             keepEmoji: Boolean = false): TextView =
        TextView(c).apply {
            text = if (keepEmoji) s else clean(s); textSize = size; setTextColor(color ?: TEXT)
            if (bold) typeface = headingFont(c)
            setLineSpacing(0f, 1.12f)
        }

    /** การ์ดขาวมุมโค้ง ขอบบาง (แบบเรียบ ไม่มีเงา) */
    fun card(c: Context, pad: Int = 14, radius: Int = 20): LinearLayout = col(c, pad).apply {
        background = round(WHITE, dpf(c, radius.toFloat() + 2f), P200, dp(c, 1))
    }

    /** ปุ่ม: primary = ไล่สีม่วง / ปกติ = ขาวขอบม่วง */
    fun button(c: Context, s: String, primary: Boolean = false, onClick: () -> Unit): TextView = TextView(c).apply {
        text = clean(s); textSize = 14.5f; gravity = Gravity.CENTER
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        val r = dpf(c, 26f)
        if (primary) {
            setTextColor(WHITE)
            background = ripple(round(P500, r), 0x55FFFFFF)
        } else {
            setTextColor(TEXT)
            background = ripple(round(WHITE, r, LINE, dp(c, 1)))
        }
        minHeight = dp(c, 48)                           // ปุ่มใหญ่พอกดง่าย
        setPadding(dp(c, 20), dp(c, 12), dp(c, 20), dp(c, 12))
        isClickable = true
        setOnClickListener { Fx.press(this); onClick() }
    }

    /** ชิปเล็ก (ทางลัด / สถานะ) */
    fun chip(c: Context, s: String, light: Boolean = true, onClick: (() -> Unit)? = null): TextView = TextView(c).apply {
        text = clean(s); textSize = 13.5f
        setTextColor(TEXT)
        background = ripple(round(WHITE, dpf(c, 20f), P200, dp(c, 1)))
        setPadding(dp(c, 14), dp(c, 8), dp(c, 14), dp(c, 8))
        if (onClick != null) { isClickable = true; setOnClickListener { Fx.press(this); onClick() } }
    }

    /** ปุ่มไอคอนกลม (ขาว ขอบบาง) */
    fun iconBtn(c: Context, emoji: String, size: Int = 44, bgColor: Int = WHITE, onClick: () -> Unit): TextView =
        TextView(c).apply {
            text = emoji; textSize = 18f; gravity = Gravity.CENTER; setTextColor(TEXT)
            background = ripple(GradientDrawable().apply {
                shape = GradientDrawable.OVAL; setColor(bgColor); if (bgColor == WHITE) setStroke(dp(c, 1), P200)
            })
            layoutParams = LinearLayout.LayoutParams(dp(c, size), dp(c, size)).apply { marginStart = dp(c, 6) }
            isClickable = true
            setOnClickListener { Fx.press(this); onClick() }
        }

    /** ปุ่มไอคอนเส้น (เวกเตอร์) กลม ขาวขอบบาง — แทนอีโมจิ */
    fun iconRes(c: Context, res: Int, label: String, size: Int = 44, onClick: () -> Unit): android.widget.ImageView =
        android.widget.ImageView(c).apply {
            setImageResource(res); contentDescription = label
            scaleType = android.widget.ImageView.ScaleType.CENTER
            background = ripple(GradientDrawable().apply {
                shape = GradientDrawable.OVAL; setColor(WHITE); setStroke(dp(c, 1), P200)
            })
            layoutParams = LinearLayout.LayoutParams(dp(c, size), dp(c, size)).apply { marginStart = dp(c, 8) }
            isClickable = true
            setOnClickListener { Fx.press(this); onClick() }
        }

    fun input(c: Context, hint: String, multi: Boolean = false, secret: Boolean = false): EditText = EditText(c).apply {
        this.hint = hint
        setTextColor(TEXT); setHintTextColor(0xFF9C94B8.toInt()); textSize = 15f
        inputType = when {
            secret -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
            multi -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            else -> InputType.TYPE_CLASS_TEXT
        }
        if (!multi) maxLines = 1
        background = round(WHITE, dpf(c, 16f), LINE, dp(c, 1))
        setPadding(dp(c, 14), dp(c, 10), dp(c, 14), dp(c, 10))
    }

    /** ปุ่มเลือกแบบแถว (เลือกได้อันเดียว) */
    fun segmented(c: Context, options: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit): LinearLayout {
        val r = row(c)
        fun paint() {
            for (i in 0 until r.childCount) {
                val v = r.getChildAt(i) as TextView
                val on = v.tag == r.tag
                v.setTextColor(if (on) WHITE else TEXT)
                v.background = if (on) round(P500, dpf(c, 20f))
                               else round(WHITE, dpf(c, 20f), P200, dp(c, 1))
            }
        }
        r.tag = selected
        for ((value, label) in options) {
            val t = TextView(c).apply {
                text = clean(label); textSize = 13.5f; tag = value; gravity = Gravity.CENTER
                setPadding(dp(c, 14), dp(c, 8), dp(c, 14), dp(c, 8))
                setOnClickListener { r.tag = value; paint(); Fx.press(this); onPick(value) }
            }
            r.addView(t, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 6); bottomMargin = dp(c, 6) })
        }
        paint()
        return r
    }

    fun lp(w: Int = ViewGroup.LayoutParams.MATCH_PARENT, h: Int = ViewGroup.LayoutParams.WRAP_CONTENT,
           weight: Float = 0f): LinearLayout.LayoutParams = LinearLayout.LayoutParams(w, h, weight)

    fun lpm(c: Context, w: Int = ViewGroup.LayoutParams.MATCH_PARENT, h: Int = ViewGroup.LayoutParams.WRAP_CONTENT,
            t: Int = 0, b: Int = 0, s: Int = 0, e: Int = 0): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(w, h).apply { topMargin = dp(c, t); bottomMargin = dp(c, b); marginStart = dp(c, s); marginEnd = dp(c, e) }

    fun gap(c: Context, h: Int = 8): View = View(c).apply { layoutParams = lp(h = dp(c, h)) }

    /** หัวหน้าจอแบบไล่สีม่วง มุมล่างโค้ง (ใช้กับทุกหน้า) */
    fun header(a: Activity, title: String, subtitle: String, back: Boolean = true): LinearLayout {
        val h = col(a, 0)
        h.setBackgroundColor(P50)                         // หัวแบบเรียบ พื้นเดียวกับหน้า
        h.setPadding(dp(a, 18), dp(a, 16), dp(a, 18), dp(a, 12))
        val r = row(a)
        if (back) r.addView(iconRes(a, R.drawable.ic_ui_back, "กลับ") { a.finish() }.apply {
            (layoutParams as LinearLayout.LayoutParams).marginStart = 0
            (layoutParams as LinearLayout.LayoutParams).marginEnd = dp(a, 12)
        })
        val tt = col(a, 0)
        tt.addView(text(a, title, 22f, true, TEXT))
        tt.addView(text(a, subtitle, 13f, false, SUB))
        r.addView(tt, lp(0, weight = 1f))
        h.addView(r)
        return h
    }
}

/** แอนิเมชัน */
object Fx {
    fun press(v: View) {
        v.animate().scaleX(0.93f).scaleY(0.93f).setDuration(70).withEndAction {
            v.animate().scaleX(1f).scaleY(1f).setDuration(160).setInterpolator(OvershootInterpolator(3f)).start()
        }.start()
    }

    /** เลื่อนขึ้น + จางเข้า (ข้อความใหม่) */
    fun enter(v: View, fromRight: Boolean = false, delay: Long = 0) {
        v.alpha = 0f
        v.translationY = 28f
        v.translationX = if (fromRight) 40f else -40f
        v.scaleX = 0.94f; v.scaleY = 0.94f
        v.animate().alpha(1f).translationY(0f).translationX(0f).scaleX(1f).scaleY(1f)
            .setStartDelay(delay).setDuration(320).setInterpolator(DecelerateInterpolator(1.6f)).start()
    }

    fun pop(v: View) {
        v.scaleX = 0.7f; v.scaleY = 0.7f; v.alpha = 0f
        v.animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(320).setInterpolator(OvershootInterpolator(1.6f)).start()
    }

    /** หายใจ (วงกลมสถานะ) */
    fun breathe(v: View, scale: Float = 1.08f, ms: Long = 1400): ObjectAnimator =
        ObjectAnimator.ofPropertyValuesHolder(v,
            PropertyValuesHolder.ofFloat(View.SCALE_X, 1f, scale),
            PropertyValuesHolder.ofFloat(View.SCALE_Y, 1f, scale)).apply {
            duration = ms; repeatCount = ValueAnimator.INFINITE; repeatMode = ValueAnimator.REVERSE; start()
        }

    /** คลื่นกระจายรอบปุ่มไมค์ตอนฟัง */
    fun ripples(host: FrameLayout, c: Context, sizeDp: Int): List<Animator> {
        val out = ArrayList<Animator>()
        for (i in 0 until 3) {
            val ring = View(c)
            ring.background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(0x557C3AED) }
            val s = Ui.dp(c, sizeDp)
            host.addView(ring, 0, FrameLayout.LayoutParams(s, s, Gravity.CENTER))
            val a = ObjectAnimator.ofPropertyValuesHolder(ring,
                PropertyValuesHolder.ofFloat(View.SCALE_X, 1f, 2.1f),
                PropertyValuesHolder.ofFloat(View.SCALE_Y, 1f, 2.1f),
                PropertyValuesHolder.ofFloat(View.ALPHA, 0.8f, 0f)).apply {
                duration = 1500; startDelay = i * 500L; repeatCount = ValueAnimator.INFINITE
                addListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationCancel(animation: Animator) { host.removeView(ring) }
                })
                start()
            }
            out.add(a)
        }
        return out
    }

    /** จุดสามจุดเด้ง (กำลังพิมพ์) */
    fun typingDots(c: Context): Pair<LinearLayout, List<Animator>> {
        val r = Ui.row(c)
        val anims = ArrayList<Animator>()
        for (i in 0 until 3) {
            val d = View(c)
            d.background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Ui.P400) }
            val s = Ui.dp(c, 8)
            r.addView(d, LinearLayout.LayoutParams(s, s).apply { marginEnd = Ui.dp(c, 5) })
            anims.add(ObjectAnimator.ofFloat(d, View.TRANSLATION_Y, 0f, -Ui.dpf(c, 6f), 0f).apply {
                duration = 600; startDelay = i * 150L; repeatCount = ValueAnimator.INFINITE; start()
            })
        }
        return Pair(r, anims)
    }

    /** ไล่สีพื้นหลังเปลี่ยนไปมาช้าๆ */
    fun shimmer(d: GradientDrawable, a: Int, b: Int, c2: Int): ValueAnimator =
        ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 5000; repeatCount = ValueAnimator.INFINITE; repeatMode = ValueAnimator.REVERSE
            val ev = android.animation.ArgbEvaluator()
            addUpdateListener {
                val f = it.animatedValue as Float
                d.colors = intArrayOf(ev.evaluate(f, a, b) as Int, ev.evaluate(f, b, c2) as Int, ev.evaluate(f, c2, a) as Int)
            }
            start()
        }
}
