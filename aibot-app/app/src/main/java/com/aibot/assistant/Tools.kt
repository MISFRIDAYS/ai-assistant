package com.aibot.assistant

import android.app.Activity
import android.os.Bundle
import android.widget.LinearLayout
import org.json.JSONArray

/** 🧰 เครื่องมือ: ทุกฟังก์ชันเป็นปุ่ม + ตัวเลือก (ไม่ต้องจำคำสั่ง) */
class ToolsActivity : PageActivity() {

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        page("เครื่องมือ", "แตะเลือกได้เลย ไม่ต้องพิมพ์คำสั่ง")
        render()
    }

    // ---------------------------------------------------------------- ตัวช่วย
    private fun tool(name: String, arg: String = "", show: Boolean = true, done: ((String) -> Unit)? = null) {
        Popups.snack(this, "⏳ กำลังทำ…")
        Thread {
            val r = try { App.py(this).getModule("android_main").callAttr("tool", name, arg).toString() }
                    catch (e: Throwable) { "❗ ${e.message}" }
            runOnUiThread {
                if (done != null) done(r)
                else if (show) { ChatLog.add("bot", r); if (!isFinishing) Popups.info(this, "✨", "ผลลัพธ์", r.take(1500)) }
            }
        }.start()
    }

    private fun chat(text: String) {
        ChatLog.add("user", text)
        Popups.snack(this, "⏳ $text")
        Thread {
            val r = try { App.py(this).getModule("android_main").callAttr("chat", text).toString() }
                    catch (e: Throwable) { "❗ ${e.message}" }
            ChatLog.add("bot", r)
            runOnUiThread { if (!isFinishing && MainActivity.visible.not()) Popups.info(this, "✨", "ผลลัพธ์", r.take(1500)) }
        }.start()
    }

    private fun ask(emoji: String, title: String, label: String, hint: String = "", then: (String) -> Unit) {
        Popups.form(this, emoji, title, "", listOf(Popups.Field("v", label, hint = hint))) { v ->
            val x = v["v"].orEmpty()
            if (x.isNotBlank()) then(x)
        }
    }

    private fun apps(): List<Pair<String, String>> = Bridge.launcherApps().lines()
        .mapNotNull { l -> l.split("|").takeIf { it.size == 3 }?.let { Pair(it[0].trim(), it[1]) } }
        .distinctBy { it.second }.sortedBy { it.first.lowercase() }

    private fun b(label: String, fn: () -> Unit): Pair<String, () -> Unit> = Pair(label, fn)

    private fun group(title: String, vararg buttons: Pair<String, () -> Unit>) {
        section(title)
        val c = Ui.card(this, 14, 20)
        var row: LinearLayout? = null
        buttons.forEachIndexed { i, (label, fn) ->
            if (i % 2 == 0) { row = Ui.row(this); c.addView(row, Ui.lpm(this, b = 8)) }
            row!!.addView(Ui.button(this, label, false) { fn() },
                Ui.lp(0, weight = 1f).apply { if (i % 2 == 1) marginStart = Ui.dp(this@ToolsActivity, 8) })
        }
        if (buttons.size % 2 == 1) row!!.addView(android.view.View(this), Ui.lp(0, weight = 1f).apply { marginStart = Ui.dp(this@ToolsActivity, 8) })
        box.addView(c, Ui.lpm(this, b = 6))
        Fx.enter(c)
    }

    private fun pickFlow(title: String, then: (String) -> Unit) {
        tool("flows", show = false) { r ->
            val names = try { JSONArray(r).let { a -> (0 until a.length()).map { a.getString(it) } } } catch (_: Exception) { emptyList() }
            if (names.isEmpty()) Popups.info(this, "🎬", "ยังไม่มีขั้นตอน", "กด \"จำขั้นตอนใหม่\" แล้วทำบนจอให้ดูก่อนนะ")
            else Popups.pick(this, "🎬", title, names.map { it to it }) { n, _ -> then(n) }
        }
    }

    private fun editProfile() {
        tool("profile_get", show = false) { r ->
            val a = try { JSONArray(r) } catch (_: Exception) { JSONArray() }
            val fields = (0 until a.length()).map { i ->
                val x = a.getJSONArray(i)
                Popups.Field(x.getString(0), x.getString(1), x.optString(2))
            }
            Popups.form(this, "🔒", "ข้อมูลของฉัน", "ใช้กรอกฟอร์มอัตโนมัติ · เก็บในเครื่องเท่านั้น · ไม่เก็บรหัสผ่าน/บัตร", fields) { v ->
                tool("profile_set", org.json.JSONObject(v as Map<*, *>).toString())
            }
        }
    }

    // ---------------------------------------------------------------- หน้า
    private fun render() {
        box.removeAllViews()
        group("📚 เรียนรู้แอป",
            b("ทุกแอปในเครื่อง") {
                Popups.choose(this, "📚", "ศึกษาทุกแอป", "เปิดทีละแอปแล้วแตะดูทุกแท็บ (ข้ามแอปธนาคาร/ระบบ) ใช้เวลาหลายนาที",
                    listOf("เริ่มเลย" to { tool("learn_all") }))
            },
            b("เลือกแอป…") {
                Popups.pick(this, "📱", "เลือกแอปที่จะศึกษา", apps()) { label, pkg -> tool("learn_app", "$label|$pkg") }
            },
            b("จำขั้นตอนใหม่") {
                ask("🎬", "จำขั้นตอนใหม่", "ตั้งชื่อขั้นตอน", "เช่น สั่งกาแฟ") { n ->
                    tool("record_start", n) { r ->
                        ChatLog.add("bot", r)
                        if (r.startsWith("🎬")) { Popups.snack(this, "🎬 เริ่มจำแล้ว — ไปทำบนจอได้เลย"); moveTaskToBack(true) }
                        else Popups.info(this, "🎬", "เริ่มไม่ได้", r)
                    }
                }
            },
            b("ทำขั้นตอนที่จำไว้…") { pickFlow("เลือกขั้นตอน") { n -> tool("play_flow", n) } },
            b("ลบขั้นตอน…") { pickFlow("ลบขั้นตอนไหน") { n -> tool("forget_flow", n) } },
        )
        group("📝 ฟอร์มและข้อมูลของฉัน",
            b("กรอกฟอร์มบนจอ") {
                Popups.choose(this, "📝", "กรอกฟอร์ม", "จะสลับไปหน้าที่เปิดไว้ก่อนหน้า (หน้าฟอร์ม) แล้วอ่านช่องให้ — ช่องที่ไม่รู้จะถามคุณ",
                    listOf("เริ่มกรอก" to { tool("fill_form") }))
            },
            b("ข้อมูลของฉัน") { editProfile() },
        )
        group("🎵 เพลง ค้นหา และข้อมูล",
            b("เปิดเพลง…") { ask("🎵", "เปิดเพลง/คลิป", "ชื่อเพลงหรือคลิป") { chat("เปิดเพลง $it") } },
            b("ค้นหาในแอป…") {
                val opts = listOf("YouTube" to "youtube", "Shopee" to "shopee", "Lazada" to "lazada", "TikTok" to "tiktok",
                    "Google" to "google", "Facebook" to "facebook", "แผนที่" to "maps", "Play Store" to "play store")
                Popups.pick(this, "🔎", "ค้นหาในแอปไหน", opts) { label, app ->
                    ask("🔎", "ค้นหาใน $label", "คำที่จะค้น") { q -> chat("หา $q ใน $app") }
                }
            },
            b("นำทาง…") { ask("🧭", "นำทาง", "ไปที่ไหน") { chat("นำทางไป $it") } },
            b("อากาศวันนี้") { chat("อากาศวันนี้เป็นยังไง") },
            b("ข่าววันนี้") { chat("ข่าววันนี้") },
            b("หาข้อมูล…") { ask("🌐", "หาข้อมูลจากเว็บ", "อยากรู้เรื่องอะไร") { chat("หาข้อมูล $it") } },
        )
        group("⚡ ควบคุมเครื่อง",
            b("เปิด Wi-Fi") { chat("เปิด wifi") }, b("ปิด Wi-Fi") { chat("ปิด wifi") },
            b("เปิดบลูทูธ") { chat("เปิดบลูทูธ") }, b("ปิดบลูทูธ") { chat("ปิดบลูทูธ") },
            b("เปิดห้ามรบกวน") { chat("เปิดห้ามรบกวน") }, b("ปิดห้ามรบกวน") { chat("ปิดห้ามรบกวน") },
            b("ไฟฉาย เปิด") { chat("เปิดไฟฉาย") }, b("ไฟฉาย ปิด") { chat("ปิดไฟฉาย") },
            b("เปิด GPS") { chat("เปิด gps") }, b("ปิด GPS") { chat("ปิด gps") },
            b("ฮอตสปอต เปิด") { chat("เปิดฮอตสปอต") }, b("ฮอตสปอต ปิด") { chat("ปิดฮอตสปอต") },
        )
        group("📱 เครื่องของฉัน (MatePad 11.5)",
            b("ข้อมูล/สถานะเครื่อง") { chat("ข้อมูลเครื่อง") },
            b("พื้นที่เหลือ") { chat("พื้นที่เหลือเท่าไหร่") },
            b("เปิดโหมดมืด") { chat("เปิดโหมดมืด") }, b("ปิดโหมดมืด") { chat("ปิดโหมดมืด") },
            b("เปิดถนอมสายตา") { chat("เปิดถนอมสายตา") }, b("ปิดถนอมสายตา") { chat("ปิดถนอมสายตา") },
            b("เปิดประหยัดพลังงาน") { chat("เปิดประหยัดพลังงาน") }, b("ปิดประหยัดพลังงาน") { chat("ปิดประหยัดพลังงาน") },
            b("หมุนจอ เปิด") { chat("เปิดหมุนจออัตโนมัติ") }, b("หมุนจอ ปิด") { chat("ปิดหมุนจออัตโนมัติ") },
            b("ตั้งค่าอื่นๆ…") {
                Popups.form(this, "⚙️", "เปิดหน้าตั้งค่า", "ผู้ช่วยจะค้นในแอปตั้งค่าแล้วเปิดหน้านั้นให้",
                    listOf(Popups.Field("q", "ชื่อการตั้งค่า", hint = "เช่น เสียง, แบตเตอรี่, Huawei Share"))) { v ->
                    val q = v["q"]?.trim().orEmpty()
                    if (q.isNotEmpty()) chat("เปิดหน้าตั้งค่า$q")
                }
            },
        )
        group("📷 กล้องและจำหน้า",
            b("สอนจำหน้าฉัน") {
                Popups.choose(this, "📷", "สอนจำหน้า", "มองกล้องหน้าตรงๆ ในที่สว่าง ระบบจะถ่าย 3 รูป (เก็บในเครื่อง)",
                    listOf("เริ่มถ่าย" to { tool("face_enroll") }))
            },
            b("ใครอยู่หน้ากล้อง") { tool("face_who") },
            b("ดูว่าเห็นอะไร") { tool("camera_look", "back") },
            b("มองหน้าฉัน") { tool("camera_look", "front") },
        )
        group("🧠 ความจำ",
            b("สิ่งที่จำไว้") {
                tool("memories", show = false) { r ->
                    val a = try { JSONArray(r) } catch (_: Exception) { JSONArray() }
                    val items = (0 until a.length()).map { a.getString(it) }
                    if (items.isEmpty()) Popups.info(this, "🧠", "ยังไม่ได้จำอะไร", "บอกว่า \"จำไว้ว่า…\" หรือคุยไปเรื่อยๆ ผู้ช่วยจะจำเอง")
                    else Popups.pick(this, "🧠", "แตะเรื่องที่อยากให้ลืม", items.reversed().map { it to it }) { t, _ ->
                        Popups.choose(this, "🗑️", "ลืมเรื่องนี้?", t, listOf("ลืม" to { tool("forget_memory", t) }))
                    }
                }
            },
            b("ลืมทั้งหมด") {
                Popups.choose(this, "🗑️", "ลืมทั้งหมด?", "ลบความจำระยะยาวทั้งหมด", listOf("ลืมทั้งหมด" to { tool("forget_memory", "ทั้งหมด") }))
            },
        )
        group("🗣️ เสียงเจ้าของ (ฟังเฉพาะเสียงคุณ)",
            b("สอนเสียงฉัน (1 นาที)") {
                Popups.choose(this, "🎙️", "สอนเสียง", "พูดตาม 6 ประโยคด้วยเสียงปกติ ห่างเครื่องเท่าที่ใช้จริง ในที่เงียบ\nหลังจากนี้ผู้ช่วยจะไม่ฟังเสียงคนอื่น/ทีวี",
                    listOf("เริ่มเลย" to { tool("voice_enroll") }))
            },
            b("ลืมเสียง (ฟังทุกคน)") { tool("voice_forget") },
        )
        group("💬 ตอบกลับอัตโนมัติ / แชท",
            b("ตั้งค่าตอบกลับอัตโนมัติ") { startActivity(android.content.Intent(this, AutoReplyActivity::class.java)) },
            b("🌙 ไม่อยู่ (เริ่มตอบแทน)") { chat("ไม่อยู่นะ") },
            b("👋 กลับมาแล้ว") { chat("กลับมาแล้ว") },
            b("📜 ประวัติแชท") { startActivity(android.content.Intent(this, ChatHistoryActivity::class.java)) },
        )
        group("🧩 เพิ่มความสามารถใหม่ (ผู้ช่วยเขียนโค้ดเอง)",
            b("สร้างความสามารถใหม่…") {
                ask("🧩", "เพิ่มความสามารถ", "อยากให้ผู้ช่วยทำอะไรได้เพิ่ม", "เช่น พูดว่า 'โหมดนอน' แล้วปิด wifi ลดเสียง เปิดห้ามรบกวน") {
                    chat("เพิ่มความสามารถ: $it")
                }
            },
            b("ความสามารถที่มี") { chat("ความสามารถที่เพิ่มเอง") },
            b("แก้/ปรับความสามารถ…") {
                ask("🛠️", "แก้ความสามารถ", "ชื่อความสามารถ : สิ่งที่อยากแก้", "เช่น โหมดนอน: ให้ปิดบลูทูธด้วย") {
                    chat("แก้ความสามารถ $it")
                }
            },
            b("ปิด/ลบความสามารถ…") {
                ask("⏸️", "ปิดหรือลบ", "พิมพ์ เช่น ปิด โหมดนอน / ลบ โหมดนอน", "ปิด โหมดนอน") { v ->
                    val w = v.trim().split(Regex("\\s+"), 2)
                    if (w.size == 2) chat("${w[0]}ความสามารถ ${w[1]}")
                }
            },
        )
        group("🩺 ซ่อมแซม",
            b("ตรวจซ่อม") { chat("ตรวจซ่อม") },
            b("ซ่อมบัคล่าสุด") { chat("ซ่อมบัค") },
            b("แจ้งอาการให้ซ่อม…") { ask("🛠️", "ซ่อมตัวเอง", "อาการที่เจอ", "เช่น ส่งไลน์แล้วไม่กดส่ง") { chat("ซ่อมตัวเอง $it") } },
            b("ย้อนการซ่อม") { chat("ย้อนการซ่อม") },
            b("ประวัติการซ่อม") { tool("history") },
            b("ฟังตลอด เปิด/ปิด") {
                Popups.choose(this, "👂", "ฟังตลอด", "ฟังตลอด = ไม่ต้องเรียกชื่อ (อาจได้ยินเสียงรอบข้างผิด)",
                    listOf("เปิดฟังตลอด" to { chat("ฟังตลอด") }, "ใช้คำปลุก" to { chat("ปิดฟังตลอด") }))
            },
        )
        box.addView(Ui.gap(this, 24))
    }
}
