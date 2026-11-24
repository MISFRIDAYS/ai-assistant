package com.aibot.assistant

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.ln
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** ลายเสียงแบบ MFCC (เหมือนฝั่ง Python speaker_id.features) — คำนวณในเครื่อง ไม่ส่งเสียงไปไหน */
object VoicePrint {
    private const val RATE = 16000
    private const val FLEN = 400
    private const val HOP = 160
    private const val NFFT = 512
    private const val NMELS = 40
    private const val NMFCC = 20

    private val mel: Array<FloatArray> by lazy {
        fun hz2mel(h: Double) = 2595 * log10(1 + h / 700.0)
        fun mel2hz(m: Double) = 700 * (10.0.pow(m / 2595.0) - 1)
        val lo = hz2mel(60.0); val hi = hz2mel(7600.0)
        val bins = IntArray(NMELS + 2) { i -> floor((NFFT + 1) * mel2hz(lo + (hi - lo) * i / (NMELS + 1)) / RATE).toInt() }
        Array(NMELS) { m ->
            val f = FloatArray(NFFT / 2 + 1)
            val a = bins[m]; val b = bins[m + 1]; val c = bins[m + 2]
            for (k in a until b) f[k] = (k - a).toFloat() / maxOf(1, b - a)
            for (k in b until c) if (k < f.size) f[k] = (c - k).toFloat() / maxOf(1, c - b)
            f
        }
    }
    private val hamming = FloatArray(FLEN) { (0.54 - 0.46 * cos(2 * PI * it / (FLEN - 1))).toFloat() }

    private fun fft(re: DoubleArray, im: DoubleArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) { val t = re[i]; re[i] = re[j]; re[j] = t; val u = im[i]; im[i] = im[j]; im[j] = u }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            val wr = cos(ang); val wi = sin(ang)
            var i = 0
            while (i < n) {
                var cr = 1.0; var ci = 0.0
                for (k in 0 until len / 2) {
                    val ar = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci
                    val ai = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr
                    re[i + k + len / 2] = re[i + k] - ar; im[i + k + len / 2] = im[i + k] - ai
                    re[i + k] += ar; im[i + k] += ai
                    val nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr
                }
                i += len
            }
            len = len shl 1
        }
    }

    fun features(pcm: ByteArray): FloatArray? {
        val n0 = pcm.size / 2
        if (n0 < RATE * 0.6) return null
        val x = FloatArray(n0)
        for (i in 0 until n0) x[i] = ((pcm[2 * i].toInt() and 0xFF) or (pcm[2 * i + 1].toInt() shl 8)).toShort().toFloat()
        for (i in n0 - 1 downTo 1) x[i] = x[i] - 0.97f * x[i - 1]
        val nf = 1 + (n0 - FLEN) / HOP
        if (nf < 40) return null
        val energy = DoubleArray(nf)
        for (f in 0 until nf) { var e = 0.0; for (k in 0 until FLEN) { val v = x[f * HOP + k] * hamming[k]; e += v * v }; energy[f] = e }
        val th = energy.sorted()[(nf * 0.4).toInt()]
        val keep = (0 until nf).filter { energy[it] > th }
        if (keep.size < 40) return null
        val mf = Array(keep.size) { FloatArray(NMFCC) }
        val re = DoubleArray(NFFT); val im = DoubleArray(NFFT)
        val logmel = DoubleArray(NMELS)
        for ((r, f) in keep.withIndex()) {
            java.util.Arrays.fill(re, 0.0); java.util.Arrays.fill(im, 0.0)
            for (k in 0 until FLEN) re[k] = (x[f * HOP + k] * hamming[k]).toDouble()
            fft(re, im)
            for (m in 0 until NMELS) {
                var s = 0.0
                val fb = mel[m]
                for (k in 0..NFFT / 2) if (fb[k] != 0f) s += fb[k] * (re[k] * re[k] + im[k] * im[k]) / NFFT
                logmel[m] = ln(s + 1e-6)
            }
            for (c in 1..NMFCC) {
                var s = 0.0
                for (m in 0 until NMELS) s += logmel[m] * cos(PI / NMELS * (m + 0.5) * c)
                mf[r][c - 1] = s.toFloat()
            }
        }
        val out = FloatArray(NMFCC * 3)
        val nr = mf.size
        for (c in 0 until NMFCC) {
            var mean = 0.0; for (r in 0 until nr) mean += mf[r][c]; mean /= nr
            var v = 0.0; for (r in 0 until nr) v += (mf[r][c] - mean).pow(2); v /= nr
            var dm = 0.0; for (r in 1 until nr) dm += mf[r][c] - mf[r - 1][c]; dm /= (nr - 1)
            var dv = 0.0; for (r in 1 until nr) dv += (mf[r][c] - mf[r - 1][c] - dm).pow(2); dv /= (nr - 1)
            out[c] = mean.toFloat(); out[NMFCC + c] = sqrt(v).toFloat(); out[2 * NMFCC + c] = sqrt(dv).toFloat()
        }
        return out
    }
}
