# ผู้ช่วย AI — แอป Android (APK)

- `huawei-ai-bot/` สมองบอท (Python) — ตัวเดียวกับที่ใช้ใน Termux + โหมดแอป (`android_shim.py`)
- `aibot-app/` แอป Android (Kotlin + Chaquopy ฝัง Python)
  - คุมจอด้วย Accessibility (ไม่ต้องใช้ ADB/Termux), อ่าน/ตอบแจ้งเตือนโดยตรง, ไมค์/ลำโพงของแอป
  - โค้ดบอทถูกแตกไปไว้ในที่เขียนได้ → ระบบซ่อมตัวเอง (self_heal) แก้โค้ด รันเทสต์ในโปรเซสแยก แล้วรีสตาร์ทเองได้

## สร้าง APK
- Linux/WSL: `bash aibot-app/build_apk.sh` (ดาวน์โหลด JDK/Android SDK/Gradle ให้เอง)
- หรือ GitHub: อัปโหลดทั้งโฟลเดอร์นี้ขึ้น repo → แท็บ Actions → Build APK → ดาวน์โหลด artifact
