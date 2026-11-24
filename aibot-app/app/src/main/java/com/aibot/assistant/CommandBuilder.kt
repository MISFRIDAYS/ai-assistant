package com.aibot.assistant

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.ViewGroup
import android.view.Window
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import org.json.JSONArray
import org.json.JSONObject

/** สั่งงานแบบกดเลือก: 1) เลือกแอป  2) เลือกสิ่งที่จะทำ  3) กรอกชื่อ/ข้อความ → ได้ประโยคคำสั่งแล้วส่งให้ผู้ช่วย */
object CommandBuilder {
    fun open(a: Activity, onCommand: (String) -> Unit) {
        Popups.snack(a, "กำลังโหลดรายชื่อแอป…")
        Thread {
            val json = try {
                App.py(a).getModule("android_main").callAttr("command_catalog").toString()
            } catch (e: Throwable) { "[]" }
            a.runOnUiThread {
                val arr = try { JSONArray(json) } catch (_: Exception) { JSONArray() }
                if (arr.length() == 0) Popups.snack(a, "ยังไม่มีรายชื่อแอป — ลองใหม่อีกครั้งในไม่กี่วินาที")
                else pickApp(a, arr, onCommand)
            }
        }.start()
    }

    /** หน้าต่างล่างจอแบบเลื่อนได้ */
    private fun dialog(a: Activity, title: String, build: (LinearLayout, LinearLayout, Dialog) -> Unit): Dialog {
        val d = Dialog(a)
        d.requestWindowFeature(Window.FEATURE_NO_TITLE)
        val outer = FrameLayout(a)
        val card = Ui.card(a, 18, 24)
        card.addView(Ui.text(a, title, 18f, true, Ui.P700), Ui.lpm(a, b = 10))
        val top = Ui.col(a, 0)
        card.addView(top)
        val sv = ScrollView(a).apply { isVerticalScrollBarEnabled = false }
        val list = Ui.col(a, 0)
        sv.addView(list)
        card.addView(sv, Ui.lpm(a, h = (a.resources.displayMetrics.heightPixels * 0.55).toInt(), t = 6))
        card.addView(Ui.button(a, "ยกเลิก") { d.dismiss() }, Ui.lpm(a, t = 10))
        build(top, list, d)
        val maxW = minOf(a.resources.displayMetrics.widthPixels - Ui.dp(a, 24), Ui.dp(a, 600))
        outer.addView(card, FrameLayout.LayoutParams(maxW, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
        d.setContentView(outer)
        d.window?.let { w ->
            w.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            w.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            w.setGravity(Gravity.BOTTOM)
            w.setDimAmount(0.45f)
        }
        d.show()
        return d
    }

    private fun pickApp(a: Activity, apps: JSONArray, onCommand: (String) -> Unit) {
        dialog(a, "① เลือกแอป") { top, list, d ->
            top.addView(Ui.button(a, "👥 คนที่จำได้ — เลือกคนแล้วสั่งได้เลย ไม่ต้องเลือกแอป", true) {
                d.dismiss(); openContacts(a, onCommand)
            }, Ui.lpm(a, b = 8))
            val search = Ui.input(a, "🔎 ค้นหาแอป…")
            top.addView(search)
            fun fill(q: String) {
                list.removeAllViews()
                var row: LinearLayout? = null
                var n = 0
                for (i in 0 until apps.length()) {
                    val app = apps.getJSONObject(i)
                    val label = app.optString("label")
                    if (q.isNotBlank() && !label.contains(q, true) && !app.optString("pkg").contains(q, true)) continue
                    if (n % 3 == 0) { row = Ui.row(a); list.addView(row, Ui.lpm(a, b = 6)) }
                    val chip = Ui.button(a, label) { d.dismiss(); pickAction(a, app, onCommand) }
                    row!!.addView(chip, Ui.lp(0, weight = 1f).apply { marginEnd = Ui.dp(a, 6) })
                    n++
                }
                while (row != null && n % 3 != 0) { row?.addView(android.view.View(a), Ui.lp(0, weight = 1f)); n++ }
            }
            search.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, af: Int) {}
                override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
                override fun afterTextChanged(s: Editable?) { fill(s?.toString() ?: "") }
            })
            fill("")
        }
    }

    /** รายชื่อทุกคนที่ผู้ช่วยจำได้ (จากแจ้งเตือน/การส่งข้อความ) พร้อมแอปที่คุยกัน */
    fun openContacts(a: Activity, onCommand: (String) -> Unit) {
        Thread {
            val json = try {
                App.py(a).getModule("android_main").callAttr("contact_catalog").toString()
            } catch (e: Throwable) { "[]" }
            a.runOnUiThread {
                val arr = try { JSONArray(json) } catch (_: Exception) { JSONArray() }
                dialog(a, "👥 เลือกคน (${arr.length()} คน)") { top, list, d ->
                    top.addView(Ui.button(a, "🔄 อ่านรายชื่อจากแชททุกแอป (1-2 นาที)") {
                        d.dismiss()
                        Popups.snack(a, "⏳ กำลังเปิดแต่ละแอปอ่านรายชื่อ — แค่อ่าน ไม่กดเข้าแชท ไม่ส่งอะไร")
                        Thread {
                            val res = try {
                                App.py(a).getModule("android_main").callAttr("chat", "จำรายชื่อจากแชททุกแอป").toString()
                            } catch (e: Throwable) { "❗ $e" }
                            ChatLog.add("bot", res)
                            a.runOnUiThread { Popups.info(a, "👥", "อ่านรายชื่อ", res.take(800)) }
                        }.start()
                    }, Ui.lpm(a, b = 8))
                    if (arr.length() == 0) list.addView(Ui.text(a, "ยังไม่ได้จำใคร — กดปุ่มด้านบนให้อ่านจากแชททุกแอป หรือรอให้มีคนทักมา", 13f, false, Ui.SUB))
                    val search = Ui.input(a, "🔎 ค้นหาชื่อ…")
                    top.addView(search)
                    fun fill(q: String) {
                        list.removeAllViews()
                        for (i in 0 until arr.length()) {
                            val c = arr.getJSONObject(i)
                            val name = c.optString("name")
                            if (q.isNotBlank() && !name.contains(q, true)) continue
                            val apps = c.optJSONArray("apps") ?: JSONArray()
                            val tags = (0 until minOf(3, apps.length())).joinToString(" · ") { apps.getJSONObject(it).optString("label") }
                            list.addView(Ui.button(a, "$name   ($tags)") { d.dismiss(); pickPersonAction(a, c, onCommand) },
                                Ui.lpm(a, b = 6))
                        }
                    }
                    search.addTextChangedListener(object : TextWatcher {
                        override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, af: Int) {}
                        override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
                        override fun afterTextChanged(s: Editable?) { fill(s?.toString() ?: "") }
                    })
                    fill("")
                }
            }
        }.start()
    }

    private fun pickPersonAction(a: Activity, c: JSONObject, onCommand: (String) -> Unit) {
        val name = c.optString("name")
        val apps = c.optJSONArray("apps") ?: JSONArray()
        dialog(a, "② $name — ทำอะไร?") { _, list, d ->
            for (i in 0 until apps.length()) {
                val app = apps.getJSONObject(i).optString("label")
                list.addView(Ui.text(a, "ใน $app", 13f, true, Ui.SUB), Ui.lpm(a, t = if (i == 0) 0 else 8, b = 4))
                val row = Ui.row(a)
                fun add(t: String, primary: Boolean, f: () -> Unit) =
                    row.addView(Ui.button(a, t, primary, f), Ui.lp(0, weight = 1f).apply { marginEnd = Ui.dp(a, 6) })
                add("✉️ ส่งข้อความ", i == 0) {
                    d.dismiss()
                    Popups.form(a, "✉️", "ส่งหา $name ใน $app", "พิมพ์ข้อความแล้วกดบันทึก",
                        listOf(Popups.Field("text", "ข้อความ"))) { v ->
                        val t = v["text"].orEmpty().trim()
                        if (t.isEmpty()) Popups.snack(a, "พิมพ์ข้อความก่อนนะ") else onCommand("ส่งข้อความหา $name ใน $app ว่า $t")
                    }
                }
                add("💬 เปิดแชท", false) { d.dismiss(); onCommand("ไปที่แชท $name ใน $app") }
                add("📞 โทร", false) { d.dismiss(); onCommand("โทรหา $name ใน $app") }
                list.addView(row, Ui.lpm(a, b = 4))
            }
        }
    }

    private fun pickAction(a: Activity, app: JSONObject, onCommand: (String) -> Unit) {
        val label = app.optString("label")
        val acts = app.optJSONArray("actions") ?: JSONArray()
        dialog(a, "② $label — ทำอะไร?") { _, list, d ->
            for (i in 0 until acts.length()) {
                val act = acts.getJSONObject(i)
                list.addView(Ui.button(a, act.optString("title"), i == 1) { d.dismiss(); fillFields(a, label, act, onCommand) },
                    Ui.lpm(a, b = 8))
            }
        }
    }

    private fun fillFields(a: Activity, appLabel: String, act: JSONObject, onCommand: (String) -> Unit) {
        val fields = act.optJSONArray("fields") ?: JSONArray()
        val template = act.optString("template")
        fun finish(vals: Map<String, String>) {
            var cmd = template.replace("{app}", appLabel)
            for ((k, v) in vals) cmd = cmd.replace("{$k}", v)
            cmd = cmd.replace(Regex("\\{\\w+\\}"), "").replace(Regex("\\s+"), " ").trim()
            onCommand(cmd)
        }
        if (fields.length() == 0) { finish(emptyMap()); return }
        val fs = (0 until fields.length()).map {
            val f = fields.getJSONObject(it)
            Popups.Field(f.optString("key"), f.optString("label"))
        }
        Popups.form(a, "③", "${act.optString("title")} · $appLabel", "กรอกแล้วกดบันทึกเพื่อสั่งงาน", fs) { vals ->
            if (vals.values.any { it.isBlank() }) { Popups.snack(a, "กรอกให้ครบก่อนนะ"); return@form }
            finish(vals)
        }
    }
}
