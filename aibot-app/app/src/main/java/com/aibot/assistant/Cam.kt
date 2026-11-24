package com.aibot.assistant

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.FaceDetector
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Size
import android.view.Surface
import android.view.WindowManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** กล้อง: ถ่ายภาพนิ่ง (หน้า/หลัง) + หาใบหน้า + ทำ "ลายหน้า" (LBP) ไว้จำเจ้าของ — ทำในเครื่องทั้งหมด */
object Cam {
    @Volatile var busy = false

    private fun pickCamera(cm: CameraManager, front: Boolean): String? {
        val want = if (front) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        return cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == want }
            ?: cm.cameraIdList.firstOrNull()
    }

    private fun displayDegrees(c: Context): Int = try {
        @Suppress("DEPRECATION")
        when ((c.getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.rotation) {
            Surface.ROTATION_90 -> 90; Surface.ROTATION_180 -> 180; Surface.ROTATION_270 -> 270; else -> 0
        }
    } catch (_: Exception) { 0 }

    /** ถ่ายภาพ 1 รูป → บันทึก JPEG (หมุนให้ตั้งตรงแล้ว) คืน "" ถ้าสำเร็จ หรือข้อความ error */
    @SuppressLint("MissingPermission")
    @Synchronized
    fun capture(c: Context, front: Boolean, path: String): String {
        if (!Bridge.camAllowed()) return "ยังไม่ได้ให้สิทธิ์กล้อง (🔐 สิทธิ์)"
        busy = true
        val cm = c.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val id = pickCamera(cm, front) ?: return "ไม่พบกล้อง".also { busy = false }
        val ch = cm.getCameraCharacteristics(id)
        val map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return "อ่านขนาดกล้องไม่ได้".also { busy = false }
        val sizes = map.getOutputSizes(ImageFormat.JPEG) ?: arrayOf(Size(1280, 960))
        val size = sizes.minByOrNull { abs(it.width * it.height - 1280 * 960) } ?: sizes[0]
        val sensor = ch.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
        val thread = HandlerThread("cam").also { it.start() }
        val h = Handler(thread.looper)
        val reader = ImageReader.newInstance(size.width, size.height, ImageFormat.JPEG, 2)
        val st = SurfaceTexture(0).also { it.setDefaultBufferSize(640, 480) }
        val preview = Surface(st)
        var device: CameraDevice? = null
        var session: CameraCaptureSession? = null
        var err = ""
        try {
            val opened = CountDownLatch(1)
            cm.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(d: CameraDevice) { device = d; opened.countDown() }
                override fun onDisconnected(d: CameraDevice) { d.close(); opened.countDown() }
                override fun onError(d: CameraDevice, e: Int) { err = "เปิดกล้องไม่ได้ (code $e — แอปอื่นอาจใช้กล้องอยู่)"; d.close(); opened.countDown() }
            }, h)
            opened.await(5, TimeUnit.SECONDS)
            val dev = device ?: return err.ifEmpty { "เปิดกล้องไม่ได้ (ระบบไม่ให้ใช้กล้องตอนแอปอยู่เบื้องหลัง — เปิดแอปก่อน)" }
            val ready = CountDownLatch(1)
            @Suppress("DEPRECATION")
            dev.createCaptureSession(listOf(preview, reader.surface), object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(s: CameraCaptureSession) { session = s; ready.countDown() }
                override fun onConfigureFailed(s: CameraCaptureSession) { err = "ตั้งค่ากล้องไม่ได้"; ready.countDown() }
            }, h)
            ready.await(5, TimeUnit.SECONDS)
            val ses = session ?: return err.ifEmpty { "ตั้งค่ากล้องไม่ได้" }
            // พรีวิวสั้นๆ ให้กล้องปรับแสง/โฟกัสก่อน
            val pr = dev.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(preview)
                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            }
            ses.setRepeatingRequest(pr.build(), null, h)
            Thread.sleep(1200)
            val got = CountDownLatch(1)
            var bytes: ByteArray? = null
            reader.setOnImageAvailableListener({ r ->
                r.acquireLatestImage()?.use { img ->
                    val buf = img.planes[0].buffer
                    bytes = ByteArray(buf.remaining()).also { buf.get(it) }
                }
                got.countDown()
            }, h)
            val cap = dev.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(reader.surface)
                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            }
            ses.stopRepeating()
            ses.capture(cap.build(), null, h)
            got.await(5, TimeUnit.SECONDS)
            val b = bytes ?: return "ถ่ายภาพไม่สำเร็จ"
            var bmp = BitmapFactory.decodeByteArray(b, 0, b.size) ?: return "อ่านภาพไม่ได้"
            val dd = displayDegrees(c)
            val rot = if (front) (sensor + dd) % 360 else (sensor - dd + 360) % 360
            if (rot != 0) bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(rot.toFloat()) }, true)
            File(path).parentFile?.mkdirs()
            FileOutputStream(path).use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
            return ""
        } catch (e: Exception) {
            Bridge.log("camera: $e")
            return "ใช้กล้องไม่ได้: ${e.message}"
        } finally {
            try { session?.close() } catch (_: Exception) {}
            try { device?.close() } catch (_: Exception) {}
            try { reader.close() } catch (_: Exception) {}
            try { preview.release(); st.release() } catch (_: Exception) {}
            thread.quitSafely()
            busy = false
        }
    }

    /** หาใบหน้าในรูป → JSON ({"x","y","w","h","conf"}) เรียงจากใหญ่ไปเล็ก + ครอปหน้าใหญ่สุดไว้ที่ facePath */
    fun faces(path: String, facePath: String): String {
        val src = BitmapFactory.decodeFile(path) ?: return "[]"
        val scale = min(1f, 800f / max(src.width, src.height))
        var w = (src.width * scale).toInt(); if (w % 2 == 1) w -= 1
        val hgt = (src.height * scale).toInt()
        val small = Bitmap.createScaledBitmap(src, w, hgt, true).copy(Bitmap.Config.RGB_565, false)
        val found = arrayOfNulls<FaceDetector.Face>(5)
        val n = FaceDetector(w, hgt, 5).findFaces(small, found)
        val out = ArrayList<JSONObject>()
        val mid = android.graphics.PointF()
        for (i in 0 until n) {
            val f = found[i] ?: continue
            f.getMidPoint(mid)
            val e = f.eyesDistance()
            val fx = ((mid.x - e * 1.5f) / scale).toInt().coerceAtLeast(0)
            val fy = ((mid.y - e * 1.4f) / scale).toInt().coerceAtLeast(0)
            val fw = (e * 3f / scale).toInt().coerceAtMost(src.width - fx)
            val fh = (e * 3.6f / scale).toInt().coerceAtMost(src.height - fy)
            out.add(JSONObject().put("x", fx).put("y", fy).put("w", fw).put("h", fh).put("conf", f.confidence().toDouble()))
        }
        out.sortByDescending { it.getInt("w") }
        out.firstOrNull()?.let { f ->
            if (f.getInt("w") > 10 && f.getInt("h") > 10) {
                val crop = Bitmap.createBitmap(src, f.getInt("x"), f.getInt("y"), f.getInt("w"), f.getInt("h"))
                FileOutputStream(facePath).use { crop.compress(Bitmap.CompressFormat.JPEG, 90, it) }
            }
        }
        return JSONArray(out).toString()
    }

    /** ลายหน้าแบบ LBP (ใช้กันทั่วไปในการจำหน้าแบบไม่ใช้ AI): ภาพขาวดำ 64x64 แบ่ง 4x4 ช่อง ช่องละ 59 ค่า */
    fun lbph(facePath: String): String {
        val src = BitmapFactory.decodeFile(facePath) ?: return "[]"
        val n = 64
        val bm = Bitmap.createScaledBitmap(src, n, n, true)
        val g = Array(n) { y -> IntArray(n) { x -> val p = bm.getPixel(x, y); ((p shr 16 and 255) * 30 + (p shr 8 and 255) * 59 + (p and 255) * 11) / 100 } }
        // ปรับแสงให้เท่ากัน (histogram equalization)
        val hist = IntArray(256); for (r in g) for (v in r) hist[v]++
        val cdf = IntArray(256); var acc = 0; for (i in 0 until 256) { acc += hist[i]; cdf[i] = acc }
        val cmin = cdf.firstOrNull { it > 0 } ?: 0
        for (r in g) for (x in r.indices) r[x] = ((cdf[r[x]] - cmin) * 255.0 / max(1, n * n - cmin)).toInt()
        // แผนที่ค่า LBP แบบ uniform (58 แบบ + อื่นๆ)
        val uni = IntArray(256) { 58 }
        var k = 0
        for (i in 0 until 256) {
            var t = 0; for (b in 0 until 8) if (((i shr b) and 1) != ((i shr ((b + 1) % 8)) and 1)) t++
            if (t <= 2) uni[i] = k++
        }
        val cells = 4
        val feat = FloatArray(cells * cells * 59)
        val dx = intArrayOf(-1, 0, 1, 1, 1, 0, -1, -1)
        val dy = intArrayOf(-1, -1, -1, 0, 1, 1, 1, 0)
        for (y in 1 until n - 1) for (x in 1 until n - 1) {
            var code = 0
            for (b in 0 until 8) if (g[y + dy[b]][x + dx[b]] >= g[y][x]) code = code or (1 shl b)
            val cell = (y * cells / n) * cells + (x * cells / n)
            feat[cell * 59 + uni[code]] += 1f
        }
        for (c in 0 until cells * cells) {
            var s = 0f; for (i in 0 until 59) s += feat[c * 59 + i]
            if (s > 0) for (i in 0 until 59) feat[c * 59 + i] /= s
        }
        return JSONArray(feat.map { (it * 10000).toInt() / 10000.0 }).toString()
    }
}
