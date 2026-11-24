plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// รุ่น Python ในแอป (ต้องตรงกับ python ที่ติดตั้งบนเครื่องที่ build: -PpyVersion=3.11)
val pyVersion: String = (project.findProperty("pyVersion") as String?) ?: "3.11"
val buildPy: String? = project.findProperty("buildPython") as String?

android {
    namespace = "com.aibot.assistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.aibot.assistant"
        minSdk = 29
        targetSdk = 34
        // เลขรุ่นเพิ่มเองทุกครั้งที่ build (นาทีนับจากปี 2025) → ติดตั้งทับรุ่นเก่าได้เสมอ
        versionCode = ((System.currentTimeMillis() / 60000) - 29_000_000).toInt()
        versionName = "1.4"
        // arm64 = มือถือทั่วไป · armeabi-v7a = มือถือราคาประหยัดที่ใช้ Android แบบ 32 บิต (Redmi/Vivo/Oppo บางรุ่น)
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }
    // กุญแจเซ็นแอปตายตัว — build จากคอมหรือ GitHub ก็ติดตั้งทับกันได้
    signingConfigs {
        getByName("debug") {
            storeFile = file("aibot.keystore")
            storePassword = "aibot123"
            keyAlias = "aibot"
            keyPassword = "aibot123"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = pyVersion
        if (buildPy != null) buildPython(buildPy!!)
        // requests ฯลฯ ใส่ไว้ใน src/main/python แล้ว (ไม่ต้องมี Python/pip บนเครื่องที่ build)
        // edge-tts 7.3+ : ใช้แค่ไฟล์ drm.py (รหัสยืนยันแบบใหม่ v2 ที่ Microsoft บังคับตั้งแต่ ต.ค. 2026)
        // --no-deps = ไม่ลง aiohttp (ลงในแอปไม่ได้) — เสียงยังส่งผ่าน edge_ws.py ของเราเอง
        pip {
            options("--no-deps")
            install("edge-tts>=7.3.0")
        }
        pyc {
            src = false
        }
    }
}

// คัดลอกโค้ดบอท (Python) เข้าไปใน assets/bot → แอปแตกไปไว้ในที่เขียนได้ → ซ่อม/ปรับปรุงตัวเองได้
val copyBot by tasks.registering(Copy::class) {
    // หาโฟลเดอร์โค้ดบอท: ข้างโฟลเดอร์ aibot-app (เปิดได้ทั้ง aibot-app และโฟลเดอร์นอกสุด)
    val botDir = listOf(rootProject.file("../huawei-ai-bot"), rootProject.file("huawei-ai-bot"))
        .firstOrNull { it.resolve("bot.py").exists() } ?: rootProject.file("../huawei-ai-bot")
    from(botDir) {
        // tester_defaults.env = ค่าตั้งต้นของรุ่นผู้ทดลอง (มีเฉพาะเมื่อ GitHub Actions สร้างให้)
        include("*.py", "tests/*.py", "config.example.env", "tester_defaults.env")
        exclude("**/__pycache__/**")
    }
    into(layout.projectDirectory.dir("src/main/assets/bot"))
}
tasks.named("preBuild") { dependsOn(copyBot) }
