#!/data/data/com.termux/files/usr/bin/bash
# ติดตั้งตัวอ่าน/คุมหน้าจอแบบเร็ว (uiautomator2) — อ่านจอ ~0.3 วิ แทน 2-5 วิ, พิมพ์ไทยทีเดียวไม่ผ่านคลิปบอร์ด
cd "$(dirname "$0")"
echo "📦 ติดตั้งแพ็กเกจที่ต้องใช้..."
pkg install -y python-lxml python-pillow || { echo "❌ pkg ติดตั้งไม่ได้ — ลอง termux-change-repo แล้วรันใหม่"; exit 1; }
pip install -U uiautomator2 || { echo "❌ pip ติดตั้ง uiautomator2 ไม่ได้"; exit 1; }
echo "🔌 ทดสอบกับเครื่อง (ต้องเชื่อม ADB อยู่)..."
python - <<'PY'
import time, screen_tools
s = screen_tools.adb_serial(force=True)
if not s:
    raise SystemExit("❌ ยังไม่ได้เชื่อม ADB — เชื่อมก่อนแล้วรันใหม่")
d = screen_tools.u2()
if d is None:
    raise SystemExit("❌ เชื่อม uiautomator2 ไม่ได้ (ดูข้อความด้านบน)")
t = time.time(); screen_tools._dump(); fast = time.time() - t
t = time.time(); screen_tools._dump_slow(); slow = time.time() - t
print(f"✅ อ่านจอแบบเร็ว {fast:.2f} วิ (แบบเดิม {slow:.2f} วิ)")
PY
bash stop_all.sh quiet && sleep 1 && bash start_all.sh
