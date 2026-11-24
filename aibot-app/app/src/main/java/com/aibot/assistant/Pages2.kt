package com.aibot.assistant

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.LinearLayout
import android.widget.Switch
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 📜 ประวัติแชท: ดูย้อนหลังทุกวัน + ค้นหา */
class ChatHistoryActivity : PageActivity() {
    private lateinit var list: LinearLayout
    private var all: List<ChatLog.Msg> = emptyList()
    private val day = SimpleDateFormat("EEEE d MMM yyyy", Locale("th", "TH"))
    private val hm = SimpleDateFormat("HH:mm", Locale.US)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        page("ประวัติแชท", "ทุกบทสนทนากับผู้ช่วย (เก็บในเครื่อง)")
        val q = Ui.input(this, "🔎 ค้นหาข้อความ…")
        box.addView(q, Ui.lpm(this, b = 8))
        val r = Ui.row(this)
        r.addView(Ui.button(this, "🗑️ ล้างประวัติ") {
            Popups.choose(this, "🗑️", "ล้างประวัติแชททั้งหมด?", "ลบถาวร (ความจำของผู้ช่วยไม่หาย)",
                listOf("ล้างเลย" to { ChatLog.clearAll(); load("") }))
        }, Ui.lpm(this, w = LinearLayout.LayoutParams.WRAP_CONTENT))
        box.addView(r, Ui.lpm(this, b = 8))
        list = Ui.col(this, 0)
        box.addView(list)
        q.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(e: Editable?) { load(e?.toString() ?: "") }
            override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, af: Int) {}
            override fun onTextChanged(s: CharSequence?, st: Int, bb: Int, c: Int) {}
        })
        Thread { all = ChatLog.readAll(); runOnUiThread { load("") } }.start()
    }

    private fun load(f: String) {
        list.removeAllViews()
        val shown = all.filter { f.isBlank() || it.text.contains(f, true) }.takeLast(400)
        if (shown.isEmpty()) {
            list.addView(Ui.text(this, if (f.isBlank()) "ยังไม่มีประวัติแชท" else "ไม่พบ \"$f\"", 14f, false, Ui.SUB))
            return
        }
        var lastDay = ""
        for (m in shown) {
            val d = day.format(Date(m.time))
            if (d != lastDay) {
                lastDay = d
                list.addView(Ui.text(this, d, 13.5f, true, Ui.SUB).apply { gravity = android.view.Gravity.CENTER },
                    Ui.lpm(this, t = 14, b = 8))
            }
            val me = m.role == "user"
            val c = Ui.card(this, 12, 16)
            c.background = if (me) Ui.round(Ui.P500, Ui.dpf(this, 20f)) else Ui.round(Ui.WHITE, Ui.dpf(this, 20f), Ui.P200, Ui.dp(this, 1))
            c.addView(Ui.text(this, (if (me) "คุณ" else "ผู้ช่วย") + " · " + hm.format(Date(m.time)), 11.5f, false,
                if (me) 0xE6FFFFFF.toInt() else Ui.SUB))
            c.addView(Ui.text(this, m.text, 14.5f, false, if (me) Ui.WHITE else Ui.TEXT, keepEmoji = true).apply { setTextIsSelectable(true) })
            list.addView(c, Ui.lpm(this, b = 6, s = if (me) 40 else 0, e = if (me) 0 else 40))
        }
    }
}

/** 💬 ตอบกลับอัตโนมัติ: กฎแต่ละแอป + โหมดไม่อยู่ */
class AutoReplyActivity : PageActivity() {
    private var cfg = JSONObject()

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        page("ตอบกลับอัตโนมัติ", "ตอบแชททุกแอปตอนไม่อยู่ — ข้อความที่ตั้งไว้ หรือให้ AI ตอบแทน")
        reload()
    }

    private fun tool(name: String, arg: String = "", then: ((String) -> Unit)? = null) {
        Thread {
            val r = try { App.py(this).getModule("android_main").callAttr("tool", name, arg).toString() }
                    catch (e: Throwable) { "❗ ${e.message}" }
            runOnUiThread { then?.invoke(r) }
        }.start()
    }

    private fun reload(): Unit = tool("ar_get") { r ->
        cfg = try { JSONObject(r) } catch (_: Exception) { JSONObject() }
        render()
    }

    private fun setKey(k: String, v: Any): Unit = tool("ar_set", JSONObject().put(k, v).toString())

    private fun sw(title: String, desc: String, on: Boolean, f: (Boolean) -> Unit): View {
        val r = Ui.row(this)
        val tc = Ui.col(this, 0)
        tc.addView(Ui.text(this, title, 15.5f, true))
        if (desc.isNotEmpty()) tc.addView(Ui.text(this, desc, 12.5f, false, Ui.SUB))
        r.addView(tc, Ui.lp(0, weight = 1f))
        r.addView(Switch(this).apply { isChecked = on; setOnCheckedChangeListener { _, x -> f(x) } })
        r.setPadding(0, Ui.dp(this, 6), 0, Ui.dp(this, 6))
        return r
    }

    private fun render() {
        box.removeAllViews()
        if (!Bridge.notifOn()) {
            val w = Ui.card(this, 14, 18)
            w.addView(Ui.text(this, "⚠️ ต้องเปิดสิทธิ์ \"อ่านการแจ้งเตือน\" ก่อน (🔐 สิทธิ์) — ระบบตอบผ่านปุ่มตอบกลับในแจ้งเตือน", 13.5f))
            box.addView(w, Ui.lpm(this, b = 10))
        }
        section("ภาพรวม")
        val c = Ui.card(this, 16, 20)
        c.addView(sw("เปิดระบบตอบกลับอัตโนมัติ", "", cfg.optBoolean("enabled", true)) { setKey("enabled", it) })
        c.addView(sw("🌙 โหมดไม่อยู่ ตอนนี้", "หรือพูดว่า \"ไม่อยู่นะ\" / \"กลับมาแล้ว\"", cfg.optBoolean("away")) { setKey("away", it) })
        c.addView(sw("🤖 ใส่ป้ายว่าผู้ช่วยตอบ", "ให้คนที่คุยด้วยรู้ว่าเป็น AI ตอบแทน (แนะนำ)", cfg.optBoolean("disclose", true)) { setKey("disclose", it) })
        c.addView(Ui.text(this, "ถือว่า \"ไม่อยู่\" อัตโนมัติเมื่อจอดับนานเกิน", 13f, true), Ui.lpm(this, t = 8))
        c.addView(Ui.segmented(this, listOf("0" to "ไม่ใช้", "10" to "10 นาที", "30" to "30 นาที", "60" to "1 ชม."),
            cfg.optInt("away_auto_min", 0).toString()) { setKey("away_auto_min", it.toInt()) }, Ui.lpm(this, t = 6))
        c.addView(Ui.button(this, "📬 ดูว่าตอบแทนอะไรไปบ้าง") {
            tool("ar_summary") { r -> Popups.info(this, "📬", "ที่ผู้ช่วยตอบแทน", r) }
        }, Ui.lpm(this, t = 10))
        box.addView(c, Ui.lpm(this, b = 10))

        section("กฎการตอบ")
        val rules = cfg.optJSONArray("rules") ?: JSONArray()
        if (rules.length() == 0) box.addView(Ui.text(this, "ยังไม่มีกฎ — กด ➕ เพิ่มกฎ", 14f, false, Ui.SUB), Ui.lpm(this, b = 8))
        for (i in 0 until rules.length()) {
            val r = rules.getJSONObject(i)
            val rc = Ui.card(this, 14, 18)
            val ai = r.optString("mode") == "ai"
            rc.addView(sw("${if (ai) "🤖" else "💬"} ${r.optString("app_label", "ทุกแอปแชท")}",
                describe(r), r.optBoolean("enabled", true)) { on -> r.put("enabled", on); tool("ar_save", r.toString()) })
            val row = Ui.row(this)
            row.addView(Ui.button(this, "✏️ แก้") { edit(r) }, Ui.lpm(this, w = LinearLayout.LayoutParams.WRAP_CONTENT, e = 8))
            row.addView(Ui.button(this, "🗑️ ลบ") {
                Popups.choose(this, "🗑️", "ลบกฎนี้?", describe(r), listOf("ลบ" to { tool("ar_delete", r.optString("id")) { reload() } }))
            }, Ui.lpm(this, w = LinearLayout.LayoutParams.WRAP_CONTENT))
            rc.addView(row, Ui.lpm(this, t = 6))
            box.addView(rc, Ui.lpm(this, b = 8))
        }
        box.addView(Ui.button(this, "➕ เพิ่มกฎ", true) { pickApp() }, Ui.lpm(this, t = 6, b = 24))
    }

    private fun describe(r: JSONObject): String {
        val parts = ArrayList<String>()
        parts.add(if (r.optString("mode") == "ai") "AI ตอบแทน" + (r.optString("style").takeIf { it.isNotBlank() }?.let { " ($it)" } ?: "")
                  else "\"${r.optString("text")}\"")
        val s = r.optString("start"); val e = r.optString("end")
        parts.add(if (s.isNotBlank() && e.isNotBlank()) "เวลา $s–$e" else "ทุกเวลา")
        if (r.optBoolean("only_away", true)) parts.add("เฉพาะตอนไม่อยู่")
        val who = r.optJSONArray("who"); if (who != null && who.length() > 0) parts.add("ตอบเฉพาะ: " + (0 until who.length()).joinToString { who.getString(it) })
        val skip = r.optJSONArray("skip"); if (skip != null && skip.length() > 0) parts.add("ไม่ตอบ: " + (0 until skip.length()).joinToString { skip.getString(it) })
        if (r.optBoolean("groups")) parts.add("ตอบในกลุ่มด้วย")
        return parts.joinToString(" · ")
    }

    private fun pickApp() {
        val chat = linkedMapOf("*" to "ทุกแอปแชท")
        val known = setOf("jp.naver.line.android", "com.facebook.orca", "com.instagram.android", "com.whatsapp",
            "org.telegram.messenger", "com.facebook.katana", "com.google.android.apps.messaging", "com.huawei.message",
            "com.discord", "com.twitter.android", "com.viber.voip", "com.tencent.mm")
        val others = ArrayList<Pair<String, String>>()
        for (l in Bridge.launcherApps().lines()) {
            val p = l.split("|"); if (p.size < 2) continue
            if (p[1] in known) chat[p[1]] = p[0] else others.add(p[0] to p[1])
        }
        val items = chat.map { (pkg, lab) -> "💬 $lab" to pkg } + others.sortedBy { it.first }.map { "📱 ${it.first}" to it.second }
        Popups.pick(this, "💬", "ตอบในแอปไหน", items) { label, pkg ->
            val r = JSONObject().put("app", pkg).put("app_label", label.substring(2).trim())
            Popups.choose(this, "💬", "ตอบแบบไหน", "ข้อความที่ตั้งไว้ = ตอบเหมือนกันทุกครั้ง · AI = อ่านข้อความแล้วตอบให้เหมาะ",
                listOf("ข้อความที่ตั้งไว้" to { edit(r.put("mode", "fixed")) }, "ให้ AI ตอบแทน" to { edit(r.put("mode", "ai")) }))
        }
    }

    private fun arr(s: String): JSONArray = JSONArray(s.split(",").map { it.trim() }.filter { it.isNotEmpty() })
    private fun joinArr(a: JSONArray?): String = if (a == null) "" else (0 until a.length()).joinToString(", ") { a.getString(it) }

    private fun edit(r: JSONObject) {
        val ai = r.optString("mode", "fixed") == "ai"
        val fields = ArrayList<Popups.Field>()
        if (ai) fields.add(Popups.Field("style", "สไตล์การตอบ (ว่างได้)", r.optString("style"), hint = "เช่น สุภาพ เป็นกันเอง ขี้เล่นนิดๆ"))
        else fields.add(Popups.Field("text", "ข้อความตอบกลับ ({name}=ชื่อคนส่ง {time}=เวลา)",
            r.optString("text", "ตอนนี้ไม่สะดวกตอบ เดี๋ยวติดต่อกลับนะ 🙏"), hint = "ตอนนี้ไม่สะดวก เดี๋ยวโทรกลับนะ"))
        fields.add(Popups.Field("start", "เริ่มเวลา (ว่าง = ทุกเวลา)", r.optString("start"), hint = "22:00"))
        fields.add(Popups.Field("end", "ถึงเวลา", r.optString("end"), hint = "07:00"))
        fields.add(Popups.Field("who", "ตอบเฉพาะคนเหล่านี้ (คั่นด้วย , ว่าง = ทุกคน)", joinArr(r.optJSONArray("who")), hint = "แม่, พี่"))
        fields.add(Popups.Field("skip", "ไม่ตอบคนเหล่านี้ (คั่นด้วย ,)", joinArr(r.optJSONArray("skip")), hint = "หัวหน้า"))
        fields.add(Popups.Field("cooldown_min", if (ai) "ตอบคนเดิมได้สูงสุดกี่ข้อความ/ชม." else "ตอบคนเดิมซ้ำห่างกันกี่นาที",
            if (ai) r.optInt("max_per_hour", 4).toString() else r.optInt("cooldown_min", 30).toString(), hint = if (ai) "4" else "30"))
        Popups.form(this, if (ai) "🤖" else "💬", r.optString("app_label", "ทุกแอปแชท"),
            if (ai) "AI ไม่รับปาก/ไม่นัด/ไม่คุยเรื่องเงิน/ไม่บอกข้อมูลส่วนตัว" else "", fields) { v ->
            if (ai) r.put("style", v["style"].orEmpty()) else r.put("text", v["text"].orEmpty().ifBlank { "ตอนนี้ไม่สะดวกตอบ เดี๋ยวติดต่อกลับนะ 🙏" })
            r.put("start", v["start"].orEmpty().trim()).put("end", v["end"].orEmpty().trim())
            r.put("who", arr(v["who"].orEmpty())).put("skip", arr(v["skip"].orEmpty()))
            val n = v["cooldown_min"]?.trim()?.toIntOrNull()
            if (ai) r.put("max_per_hour", n ?: 4) else r.put("cooldown_min", n ?: 30)
            Popups.choose(this, "⏰", "ตอบเมื่อไหร่", "", listOf(
                "เฉพาะตอนไม่อยู่" to { r.put("only_away", true); askGroups(r) },
                "ตลอด (ตามช่วงเวลาที่ตั้ง)" to { r.put("only_away", false); askGroups(r) }))
        }
    }

    private fun askGroups(r: JSONObject) {
        Popups.choose(this, "👥", "ตอบในแชทกลุ่มด้วยไหม", "แนะนำ: ไม่ตอบในกลุ่ม", listOf(
            "ไม่ตอบในกลุ่ม" to { r.put("groups", false); saveRule(r) },
            "ตอบในกลุ่มด้วย" to { r.put("groups", true); saveRule(r) }))
    }

    private fun saveRule(r: JSONObject): Unit = tool("ar_save", r.toString()) { msg -> Popups.snack(this, msg); reload() }
}
