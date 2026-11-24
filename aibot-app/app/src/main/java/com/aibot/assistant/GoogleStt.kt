package com.aibot.assistant

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * ถอดเสียงด้วยระบบรู้จำเสียงของเครื่อง (ตัวเดียวกับปุ่มไมค์ในคีย์บอร์ด Gboard) — ฟรี แม่นกับภาษาไทย
 * ฟังทีละประโยค: ใช้ฟังคำสั่งหลังเรียก "ผู้ช่วย" และปุ่มไมค์ในแอป (คำปลุกยังใช้ไมค์ของแอปเหมือนเดิม)
 * เครื่องที่ไม่มีบริการของ Google (เช่น Huawei รุ่นใหม่) → available() = false → ใช้ตัวถอดเสียงเดิม
 */
object GoogleStt {
    private val main = Handler(Looper.getMainLooper())
    @Volatile var busy = false

    fun available(): Boolean = try { SpeechRecognizer.isRecognitionAvailable(Bridge.app) } catch (_: Throwable) { false }

    private fun errName(e: Int) = when (e) {
        SpeechRecognizer.ERROR_NO_MATCH -> "no_match"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "speech_timeout"
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "network"
        SpeechRecognizer.ERROR_AUDIO -> "audio"
        SpeechRecognizer.ERROR_CLIENT -> "client"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "busy"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "permission"
        SpeechRecognizer.ERROR_SERVER -> "server"
        12 -> "language_unsupported"
        13 -> "language_unavailable"
        else -> "error_$e"
    }

    /**
     * ฟังหนึ่งประโยค (เรียกจากเธรดเบื้องหลังเท่านั้น — รอจนได้ผล)
     * คืน JSON: {"ok": true, "text": "..."} ได้ข้อความ (text ว่าง = ไม่มีใครพูด)
     *           {"ok": false, "err": "..."} ใช้ไม่ได้ → ให้ใช้ตัวถอดเสียงเดิม
     */
    fun listen(timeoutMs: Int, lang: String): String {
        val out = JSONObject().put("ok", false).put("text", "").put("err", "")
        if (busy) return out.put("err", "busy").toString()
        if (!available()) return out.put("err", "unavailable").toString()
        busy = true
        val done = CountDownLatch(1)
        val ref = AtomicReference<SpeechRecognizer?>(null)
        val micWasOn = Mic.running
        if (micWasOn) Mic.stop()                    // ปล่อยไมค์ให้ระบบรู้จำเสียงใช้ (ไมค์ใช้พร้อมกันไม่ได้)
        try {
            main.post {
                try {
                    val r = SpeechRecognizer.createSpeechRecognizer(Bridge.app)
                    ref.set(r)
                    r.setRecognitionListener(object : RecognitionListener {
                        override fun onResults(b: Bundle?) {
                            val list = b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            out.put("ok", true).put("text", list?.firstOrNull().orEmpty())
                            done.countDown()
                        }
                        override fun onError(error: Int) {
                            val n = errName(error)
                            if (n == "no_match" || n == "speech_timeout") out.put("ok", true)   // ไม่มีคนพูด ไม่ใช่ระบบพัง
                            out.put("err", n)
                            done.countDown()
                        }
                        override fun onRmsChanged(rmsdB: Float) {
                            Mic.level = ((rmsdB + 2f).coerceIn(0f, 12f) * 250f)    // ขยับจุดสีบนแผงผู้ช่วย
                        }
                        override fun onReadyForSpeech(p: Bundle?) {}
                        override fun onBeginningOfSpeech() {}
                        override fun onBufferReceived(buffer: ByteArray?) {}
                        override fun onEndOfSpeech() {}
                        override fun onPartialResults(p: Bundle?) {}
                        override fun onEvent(type: Int, p: Bundle?) {}
                    })
                    val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang)
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, lang)
                        putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                        putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, Bridge.app.packageName)
                        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L)
                    }
                    r.startListening(i)
                } catch (e: Throwable) {
                    out.put("err", "start: ${e.javaClass.simpleName}")
                    done.countDown()
                }
            }
            if (!done.await(timeoutMs.toLong() + 5000, TimeUnit.MILLISECONDS)) out.put("err", "timeout")
        } catch (e: Throwable) {
            out.put("err", e.javaClass.simpleName)
        } finally {
            main.post { try { ref.get()?.cancel(); ref.get()?.destroy() } catch (_: Throwable) {} }
            if (micWasOn) {
                try { Thread.sleep(250) } catch (_: InterruptedException) {}
                Mic.start()                         // คืนไมค์ให้ระบบฟังคำปลุก
            }
            busy = false
        }
        return out.toString()
    }
}
