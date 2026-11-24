package com.aibot.assistant

import android.content.ComponentName
import android.content.Context
import android.graphics.Color
import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.LinearLayout
import android.widget.TextView

/** คีย์บอร์ดของผู้ช่วย: ใช้พิมพ์แทนผู้ใช้ในแอปที่ไม่ยอมให้ใส่ข้อความผ่านระบบช่วยเหลือ (เช่น แอปบันทึก Huawei)
 *  ผู้ช่วยสลับมาใช้ชั่วคราว → พิมพ์ → สลับกลับไปคีย์บอร์ดเดิมให้เอง */
class BotIme : InputMethodService() {
    companion object {
        @Volatile var inst: BotIme? = null
        @Volatile var bound = false                     // มีช่องพิมพ์ที่เชื่อมอยู่
        @Volatile var lastBind = 0L
        private val main = Handler(Looper.getMainLooper())

        fun id(c: Context) = ComponentName(c, BotIme::class.java).flattenToShortString()

        fun enabled(c: Context): Boolean {
            val list = Settings.Secure.getString(c.contentResolver, Settings.Secure.ENABLED_INPUT_METHODS) ?: ""
            val me = id(c)
            val full = ComponentName(c, BotIme::class.java).flattenToString()
            return list.split(":").any { it == me || it == full }
        }

        fun current(c: Context): String =
            Settings.Secure.getString(c.contentResolver, Settings.Secure.DEFAULT_INPUT_METHOD) ?: ""

        fun isCurrent(c: Context): Boolean {
            val cur = current(c)
            return cur == id(c) || cur == ComponentName(c, BotIme::class.java).flattenToString()
        }

        /** สิทธิ์สลับคีย์บอร์ดเอง (ต้องอนุญาตครั้งเดียวผ่าน adb จากคอม) */
        fun canSwitch(c: Context): Boolean =
            c.checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS") == android.content.pm.PackageManager.PERMISSION_GRANTED

        private fun waitBound(ms: Long): Boolean {
            val end = SystemClock.uptimeMillis() + ms
            while (SystemClock.uptimeMillis() < end) {
                if (inst != null && bound) return true
                Thread.sleep(80)
            }
            return inst != null && bound
        }

        /** พิมพ์ข้อความลงช่องที่เลือกอยู่ผ่านคีย์บอร์ดผู้ช่วย (คืน true ถ้าพิมพ์ได้) — เรียกจากเธรดเบื้องหลัง */
        fun type(c: Context, text: String, enter: Boolean): Boolean {
            if (!enabled(c)) return false
            var prev: String? = null
            var viaPicker = false
            if (!isCurrent(c)) {
                if (canSwitch(c)) {
                    prev = current(c)
                    try {
                        Settings.Secure.putString(c.contentResolver, Settings.Secure.DEFAULT_INPUT_METHOD, id(c))
                    } catch (e: Exception) { Bridge.log("ime switch: $e"); return false }
                } else {
                    // ไม่มีสิทธิ์สลับเอง → เปิดกล่องเลือกคีย์บอร์ดของระบบ แล้วแตะ "คีย์บอร์ดผู้ช่วย AI" ให้
                    main.post {
                        try { (c.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker() }
                        catch (_: Exception) {}
                    }
                    Thread.sleep(900)
                    if (ScreenService.inst?.clickText("คีย์บอร์ดผู้ช่วย AI") != true) return false
                    viaPicker = true
                }
            }
            var ok = false
            try {
                if (waitBound(2500)) {
                    val latch = java.util.concurrent.CountDownLatch(1)
                    main.post {
                        ok = inst?.commit(text, enter) ?: false
                        latch.countDown()
                    }
                    latch.await(3, java.util.concurrent.TimeUnit.SECONDS)
                }
            } finally {
                if (viaPicker) main.post { try { inst?.switchToPreviousInputMethod() } catch (_: Exception) {} }
                if (prev != null && prev.isNotEmpty()) {
                    Thread.sleep(250)
                    try { Settings.Secure.putString(c.contentResolver, Settings.Secure.DEFAULT_INPUT_METHOD, prev) }
                    catch (e: Exception) { Bridge.log("ime restore: $e") }
                }
            }
            return ok
        }
    }

    override fun onCreate() { super.onCreate(); inst = this }
    override fun onDestroy() { if (inst === this) inst = null; bound = false; super.onDestroy() }

    override fun onStartInput(attr: EditorInfo?, restarting: Boolean) {
        super.onStartInput(attr, restarting)
        val t = attr?.inputType ?: 0
        val cls = t and 0xF
        val v = t and 0xFF0
        val pwd = (cls == 1 && (v == 0x80 || v == 0x90 || v == 0xE0)) || (cls == 2 && v == 0x10)
        bound = currentInputConnection != null && !pwd       // ช่องรหัสผ่าน → ไม่พิมพ์ให้
        lastBind = SystemClock.uptimeMillis()
    }

    override fun onFinishInput() { bound = false; super.onFinishInput() }

    fun commit(text: String, enter: Boolean): Boolean {
        val ic = currentInputConnection ?: return false
        if (!bound) return false
        val ok = ic.commitText(text, 1)
        if (enter) {
            val action = (currentInputEditorInfo?.imeOptions ?: 0) and EditorInfo.IME_MASK_ACTION
            if (action != EditorInfo.IME_ACTION_NONE && action != EditorInfo.IME_ACTION_UNSPECIFIED) ic.performEditorAction(action)
            else {
                ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENTER))
                ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_ENTER))
            }
        }
        return ok
    }

    /** หน้าตาคีย์บอร์ด: แถบเล็กๆ บอกว่าผู้ช่วยกำลังพิมพ์ + ปุ่มสลับกลับคีย์บอร์ดปกติ */
    override fun onCreateInputView(): View {
        val c = this
        val bar = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Ui.P50)
            setPadding(Ui.dp(c, 14), Ui.dp(c, 10), Ui.dp(c, 14), Ui.dp(c, 10))
        }
        bar.addView(TextView(c).apply {
            text = "คีย์บอร์ดผู้ช่วย — ผู้ช่วยใช้พิมพ์ให้อัตโนมัติ"; textSize = 14f; setTextColor(Ui.TEXT)
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        bar.addView(TextView(c).apply {
            text = "สลับคีย์บอร์ด"; textSize = 14f; setTextColor(Color.WHITE)
            setPadding(Ui.dp(c, 12), Ui.dp(c, 8), Ui.dp(c, 12), Ui.dp(c, 8))
            background = Ui.round(Ui.P500, Ui.dpf(c, 16f))
            setOnClickListener {
                if (!switchToPreviousInputMethod())
                    (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker()
            }
        })
        return bar
    }
}
