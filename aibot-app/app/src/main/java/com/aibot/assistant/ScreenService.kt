package com.aibot.assistant

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** ควบคุมหน้าจอแทน ADB: อ่านโครงหน้าจอ (XML แบบ uiautomator) แตะ ปัด พิมพ์ กดปุ่มระบบ จับภาพจอ */
class ScreenService : AccessibilityService() {

    companion object {
        @Volatile var inst: ScreenService? = null
        @Volatile var lastPkg: String = ""
        @Volatile var lastActivity: String = ""
        @Volatile var recording = false
        val events = ConcurrentLinkedQueue<String>()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        inst = this
        try { getSharedPreferences("app", MODE_PRIVATE).edit().putBoolean("a11y_seen", true).apply() } catch (_: Exception) {}
        Bridge.log("♿ Accessibility พร้อมควบคุมหน้าจอ")
    }

    override fun onDestroy() {
        inst = null
        super.onDestroy()
    }

    override fun onInterrupt() {}

    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        if (e == null) return
        val pkg = e.packageName?.toString() ?: ""
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED && pkg.isNotEmpty()
            && pkg != "com.android.systemui" && pkg != packageName) {
            val cls = e.className?.toString() ?: ""
            if (!cls.startsWith("android.widget.") || lastPkg != pkg) {
                lastPkg = pkg
                lastActivity = cls
            }
        }
        if (!recording || pkg == packageName) return
        try {
            when (e.eventType) {
                AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                    val src = e.source
                    val o = JSONObject()
                    o.put("type", "click"); o.put("pkg", pkg); o.put("t", System.currentTimeMillis())
                    if (src != null) {
                        val r = Rect(); src.getBoundsInScreen(r)
                        o.put("text", src.text?.toString() ?: e.text.joinToString(" "))
                        o.put("desc", src.contentDescription?.toString() ?: "")
                        o.put("id", (src.viewIdResourceName ?: "").substringAfterLast('/'))
                        o.put("edit", src.isEditable)
                        o.put("x", r.centerX()); o.put("y", r.centerY())
                    } else {
                        o.put("text", e.text.joinToString(" "))
                    }
                    events.add(o.toString())
                }
                AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                    if (e.isPassword) return
                    val src = e.source
                    val o = JSONObject()
                    o.put("type", "text"); o.put("pkg", pkg); o.put("t", System.currentTimeMillis())
                    o.put("text", e.text.joinToString(""))
                    o.put("id", (src?.viewIdResourceName ?: "").substringAfterLast('/'))
                    events.add(o.toString())
                }
            }
            while (events.size > 500) events.poll()
        } catch (_: Exception) {
        }
    }

    // ------------------------------------------------------------ อ่านหน้าจอ

    private fun esc(s: CharSequence?): String {
        if (s == null) return ""
        val b = StringBuilder(s.length + 8)
        for (c in s) {
            when (c) {
                '&' -> b.append("&amp;")
                '<' -> b.append("&lt;")
                '>' -> b.append("&gt;")
                '"' -> b.append("&quot;")
                '\n' -> b.append("&#10;")
                else -> if (c.code >= 0x20 || c == '\t') b.append(c)
            }
        }
        return b.toString()
    }

    private fun node(n: AccessibilityNodeInfo?, idx: Int, sb: StringBuilder, depth: Int) {
        if (n == null || depth > 60) return
        val r = Rect()
        n.getBoundsInScreen(r)
        var text: CharSequence? = n.text
        if (text.isNullOrEmpty() && n.isEditable && Build.VERSION.SDK_INT >= 26) text = n.hintText
        sb.append("<node index=\"").append(idx)
            .append("\" text=\"").append(esc(text))
            .append("\" resource-id=\"").append(esc(n.viewIdResourceName))
            .append("\" class=\"").append(esc(n.className))
            .append("\" package=\"").append(esc(n.packageName))
            .append("\" content-desc=\"").append(esc(n.contentDescription))
            .append("\" checkable=\"").append(n.isCheckable)
            .append("\" checked=\"").append(n.isChecked)
            .append("\" clickable=\"").append(n.isClickable)
            .append("\" enabled=\"").append(n.isEnabled)
            .append("\" focusable=\"").append(n.isFocusable)
            .append("\" focused=\"").append(n.isFocused)
            .append("\" scrollable=\"").append(n.isScrollable)
            .append("\" long-clickable=\"").append(n.isLongClickable)
            .append("\" password=\"").append(n.isPassword)
            .append("\" selected=\"").append(n.isSelected)
            .append("\" bounds=\"[").append(r.left).append(',').append(r.top).append("][")
            .append(r.right).append(',').append(r.bottom).append("]\"")
        val cnt = n.childCount
        if (cnt == 0) {
            sb.append(" />")
            return
        }
        sb.append(">")
        for (i in 0 until cnt) {
            try {
                node(n.getChild(i), i, sb, depth + 1)
            } catch (_: Exception) {
            }
        }
        sb.append("</node>")
    }

    /** โครงหน้าจอทุกหน้าต่าง (แอป + แถบระบบ + หน้าจอรับสาย) รูปแบบเดียวกับ uiautomator dump */
    fun dumpXml(): String {
        val sb = StringBuilder(64 * 1024)
        sb.append("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"")
            .append(rotation()).append("\">")
        val roots = ArrayList<AccessibilityNodeInfo>()
        try {
            val ws = windows
            // บนสุดก่อน (หน้าต่างที่ผู้ใช้เห็นข้างหน้า) — ข้ามคีย์บอร์ดและแอปนี้เอง
            for (w in ws.sortedByDescending { it.layer }) {
                if (w.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD) continue
                val r = w.root ?: continue
                if (r.packageName?.toString() == packageName) continue
                roots.add(r)
            }
        } catch (_: Exception) {
        }
        if (roots.isEmpty()) rootInActiveWindow?.let { roots.add(it) }
        // เต็มจอทั้งหมดเป็นโหนดแรก (โค้ดฝั่ง Python ใช้หาขนาดจอ)
        val size = realSize()
        sb.append("<node index=\"0\" text=\"\" resource-id=\"\" class=\"android.widget.FrameLayout\" package=\"")
            .append(esc(lastPkg)).append("\" content-desc=\"\" checkable=\"false\" checked=\"false\" clickable=\"false\" ")
            .append("enabled=\"true\" focusable=\"false\" focused=\"false\" scrollable=\"false\" long-clickable=\"false\" ")
            .append("password=\"false\" selected=\"false\" bounds=\"[0,0][").append(size.first).append(',')
            .append(size.second).append("]\">")
        roots.forEachIndexed { i, r -> node(r, i, sb, 0) }
        sb.append("</node></hierarchy>")
        return sb.toString()
    }

    fun rotation(): Int = try {
        @Suppress("DEPRECATION")
        (getSystemService(WINDOW_SERVICE) as android.view.WindowManager).defaultDisplay.rotation
    } catch (_: Exception) { 0 }

    fun realSize(): Pair<Int, Int> {
        val wm = getSystemService(WINDOW_SERVICE) as android.view.WindowManager
        return if (Build.VERSION.SDK_INT >= 30) {
            val b = wm.currentWindowMetrics.bounds
            Pair(b.width(), b.height())
        } else {
            val p = android.graphics.Point()
            @Suppress("DEPRECATION") wm.defaultDisplay.getRealSize(p)
            Pair(p.x, p.y)
        }
    }

    // ------------------------------------------------------------ แตะ / ปัด

    private fun gesture(path: Path, ms: Long): Boolean {
        val g = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, ms.coerceAtLeast(1)))
            .build()
        val latch = CountDownLatch(1)
        var ok = false
        val sent = dispatchGesture(g, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) { ok = true; latch.countDown() }
            override fun onCancelled(d: GestureDescription?) { latch.countDown() }
        }, null)
        if (!sent) return false
        latch.await(ms + 3000, TimeUnit.MILLISECONDS)
        return ok
    }

    fun tap(x: Float, y: Float, ms: Long = 60): Boolean {
        val p = Path(); p.moveTo(x.coerceAtLeast(0f), y.coerceAtLeast(0f))
        return gesture(p, ms)
    }

    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long): Boolean {
        val p = Path(); p.moveTo(x1, y1); p.lineTo(x2, y2)
        return gesture(p, ms.coerceIn(50, 5000))
    }

    fun global(action: Int): Boolean = performGlobalAction(action)

    // ------------------------------------------------------------ พิมพ์

    fun focusedInput(): AccessibilityNodeInfo? {
        val f = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (f != null && f.isEditable && f.packageName?.toString() != packageName) return f
        // ไม่มีช่องที่โฟกัส → ช่องพิมพ์ที่อยู่ล่างสุดของแอปที่ใช้อยู่ (ช่องแชท ไม่ใช่ช่องค้นหาด้านบน)
        val all = ArrayList<AccessibilityNodeInfo>()
        collectEditable(rootInActiveWindow, 0, all)
        if (all.isEmpty()) {                              // หน้าต่างที่ active เป็นแผงของผู้ช่วยเอง → ดูหน้าต่างแอปอื่นบนจอ
            val wins = try { windows } catch (_: Exception) { emptyList() }
            for (w in wins) collectEditable(try { w.root } catch (_: Exception) { null }, 0, all)
        }
        if (all.isEmpty()) return null
        val rect = android.graphics.Rect()
        return all.maxByOrNull { it.getBoundsInScreen(rect); rect.bottom }
    }

    private fun collectEditable(n: AccessibilityNodeInfo?, depth: Int, out: MutableList<AccessibilityNodeInfo>) {
        if (n == null || depth > 60) return
        if (n.isEditable && n.isVisibleToUser && n.packageName?.toString() != packageName) out.add(n)
        for (i in 0 until n.childCount) collectEditable(n.getChild(i), depth + 1, out)
    }


    fun setText(text: String, append: Boolean): Boolean {
        val n = focusedInput() ?: return false
        if (n.isPassword) return false                  // ห้ามพิมพ์ลงช่องรหัสผ่านเด็ดขาด
        var cur = ""
        if (append) {
            val t = n.text?.toString() ?: ""
            val hint = if (Build.VERSION.SDK_INT >= 26) n.hintText?.toString() else null
            val showingHint = Build.VERSION.SDK_INT >= 26 && n.isShowingHintText
            cur = if (showingHint || t == hint) "" else t
        }
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, cur + text)
        val ok = n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        if (ok) {
            val sel = Bundle()
            val end = (cur + text).length
            sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, end)
            sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end)
            n.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, sel)
        }
        return ok
    }

    /** ข้อความลงช่องจริงไหม (บางแอปตอบว่าสำเร็จแต่ไม่รับข้อความ) */
    fun textLanded(text: String): Boolean {
        val n = focusedInput() ?: return false
        try { n.refresh() } catch (_: Exception) {}
        val t = n.text?.toString() ?: return false
        val probe = text.trim().take(12)
        return probe.isEmpty() || t.contains(probe)
    }

    /** แตะข้อความบนจอ (ทุกหน้าต่าง รวมกล่องเลือกคีย์บอร์ดของระบบ) */
    fun clickText(label: String): Boolean {
        val wins = try { windows } catch (_: Exception) { emptyList() }
        val roots = (wins.mapNotNull { try { it.root } catch (_: Exception) { null } } + listOfNotNull(rootInActiveWindow))
        for (r in roots) {
            val hits = try { r.findAccessibilityNodeInfosByText(label) } catch (_: Exception) { null } ?: continue
            for (h in hits) {
                var n: AccessibilityNodeInfo? = h
                var d = 0
                while (n != null && !n.isClickable && d < 6) { n = n.parent; d++ }
                if (n != null && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
                val b = android.graphics.Rect(); h.getBoundsInScreen(b)
                if (!b.isEmpty && tap(b.exactCenterX(), b.exactCenterY())) return true
            }
        }
        return false
    }

    fun focusedIsPassword(): Boolean = focusedInput()?.isPassword ?: false

    fun deleteChars(count: Int): Boolean {
        val n = focusedInput() ?: return false
        val t = n.text?.toString() ?: ""
        val showingHint = Build.VERSION.SDK_INT >= 26 && n.isShowingHintText
        val base = if (showingHint) "" else t
        val nt = if (count >= base.length) "" else base.substring(0, base.length - count)
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, nt)
        return n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    fun imeEnter(): Boolean {
        val n = focusedInput() ?: return false
        if (Build.VERSION.SDK_INT >= 30) {
            if (n.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)) return true
        }
        return false
    }

    fun paste(): Boolean = focusedInput()?.performAction(AccessibilityNodeInfo.ACTION_PASTE) ?: false

    // ------------------------------------------------------------ จับภาพจอ

    fun screenshot(path: String): Boolean {
        if (Build.VERSION.SDK_INT < 30) return false
        for (attempt in 0 until 3) {                     // บางเครื่อง (HarmonyOS) ปฏิเสธครั้งแรก/ถ่ายถี่เกิน → รอแล้วลองใหม่
            if (shotOnce(path)) return true
            Thread.sleep(1100L)
        }
        return false
    }

    private fun shotOnce(path: String): Boolean {
        val latch = CountDownLatch(1)
        var ok = false
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : AccessibilityService.TakeScreenshotCallback {
            override fun onSuccess(res: AccessibilityService.ScreenshotResult) {
                try {
                    val hb = res.hardwareBuffer
                    val bmp = Bitmap.wrapHardwareBuffer(hb, res.colorSpace)
                    val soft = bmp?.copy(Bitmap.Config.ARGB_8888, false)
                    hb.close()
                    if (soft != null) {
                        File(path).parentFile?.mkdirs()
                        FileOutputStream(path).use { soft.compress(Bitmap.CompressFormat.PNG, 100, it) }
                        ok = true
                    }
                } catch (e: Exception) {
                    Bridge.log("screenshot error: $e")
                }
                latch.countDown()
            }

            override fun onFailure(code: Int) {
                Bridge.log("screenshot failed code=$code")
                latch.countDown()
            }
        })
        latch.await(6, TimeUnit.SECONDS)
        return ok
    }
}
