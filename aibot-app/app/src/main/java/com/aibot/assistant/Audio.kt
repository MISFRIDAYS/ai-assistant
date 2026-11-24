package com.aibot.assistant

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.speech.tts.TextToSpeech
import java.util.Locale
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** ไมค์ฟังต่อเนื่อง 16kHz (ส่งท่อนละ 30ms ให้ฝั่ง Python ตัดประโยค) */
object Mic {
    private const val RATE = 16000
    const val FRAME = 960                       // 30ms * 16kHz * 2 bytes
    private var rec: AudioRecord? = null
    private var th: Thread? = null
    private val q = ArrayBlockingQueue<ByteArray>(800)
    @Volatile var running = false
    @Volatile var lastError = ""
    @Volatile var level = 0f                       // ความดังล่าสุด (ใช้ขยับจุดสีบนแผงผู้ช่วย)

    @SuppressLint("MissingPermission")
    @Synchronized
    fun start(): Boolean {
        if (running) return true
        return try {
            val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val r = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(min, FRAME * 8))
            if (r.state != AudioRecord.STATE_INITIALIZED) {
                lastError = "AudioRecord init failed"; r.release(); return false
            }
            r.startRecording()
            rec = r
            running = true
            q.clear()
            th = Thread {
                val buf = ByteArray(FRAME)
                while (running) {
                    var got = 0
                    while (got < FRAME && running) {
                        val n = r.read(buf, got, FRAME - got)
                        if (n <= 0) { Thread.sleep(5); continue }
                        got += n
                    }
                    var sum = 0.0
                    var k = 0
                    while (k + 1 < FRAME) {
                        val v = ((buf[k].toInt() and 0xFF) or (buf[k + 1].toInt() shl 8)).toShort().toInt()
                        sum += (v * v).toDouble(); k += 2
                    }
                    level = Math.sqrt(sum / (FRAME / 2)).toFloat()
                    if (!q.offer(buf.copyOf())) { q.poll(); q.offer(buf.copyOf()) }
                }
            }.also { it.isDaemon = true; it.start() }
            true
        } catch (e: Exception) {
            lastError = e.toString(); running = false; false
        }
    }

    /** ท่อนเสียงถัดไป (รอได้ไม่เกิน timeoutMs) — ว่าง = ไม่มีเสียงเข้า */
    fun read(timeoutMs: Long): ByteArray = q.poll(timeoutMs, TimeUnit.MILLISECONDS) ?: ByteArray(0)

    fun flush() = q.clear()

    @Synchronized
    fun stop() {
        running = false
        try { rec?.stop() } catch (_: Exception) {}
        try { rec?.release() } catch (_: Exception) {}
        rec = null
    }
}

/** เล่นไฟล์เสียง (mp3/wav/ogg) + เสียงพูดของเครื่อง (TTS ของ Android) */
object Player {
    private var mp: MediaPlayer? = null
    @Volatile var playing = false
    private var tts: TextToSpeech? = null
    @Volatile private var ttsReady = false

    fun play(path: String, wait: Boolean): Boolean {
        stop()
        val done = CountDownLatch(1)
        return try {
            val p = MediaPlayer()
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(path)
            p.setOnCompletionListener { playing = false; done.countDown(); it.release(); if (mp === it) mp = null }
            p.setOnErrorListener { mpp, _, _ -> playing = false; done.countDown(); mpp.release(); if (mp === mpp) mp = null; true }
            p.prepare()
            mp = p
            playing = true
            p.start()
            if (wait) done.await(180, TimeUnit.SECONDS)
            true
        } catch (e: Exception) {
            Bridge.log("play error: $e")
            playing = false
            false
        }
    }

    fun stop() {
        val p = mp ?: return
        mp = null
        playing = false
        try { p.stop() } catch (_: Exception) {}
        try { p.release() } catch (_: Exception) {}
    }

    fun speak(text: String, wait: Boolean): Boolean {
        if (tts == null) {
            val ready = CountDownLatch(1)
            tts = TextToSpeech(Bridge.app) { st ->
                ttsReady = st == TextToSpeech.SUCCESS
                ready.countDown()
            }
            ready.await(8, TimeUnit.SECONDS)
            tts?.setLanguage(Locale("th", "TH"))
        }
        if (!ttsReady) return false
        val t = tts ?: return false
        val id = "u" + System.currentTimeMillis()
        val done = CountDownLatch(1)
        t.setOnUtteranceProgressListener(object : android.speech.tts.UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) { playing = true }
            override fun onDone(utteranceId: String?) { playing = false; done.countDown() }
            @Deprecated("deprecated") override fun onError(utteranceId: String?) { playing = false; done.countDown() }
        })
        t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
        if (wait) done.await(120, TimeUnit.SECONDS)
        return true
    }
}
