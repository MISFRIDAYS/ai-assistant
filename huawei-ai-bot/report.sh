#!/data/data/com.termux/files/usr/bin/bash
# รวมข้อมูลตรวจปัญหา (ส่งผลนี้ให้ผู้ช่วยดูได้เลย)
cd "$(dirname "$0")"
echo "===== สถานะ ====="
pgrep -f "python.* bot\.py" >/dev/null && echo "บอท Telegram: ทำงาน" || echo "บอท Telegram: ❌ ไม่ทำงาน"
pgrep -f "voice_chat\.py" >/dev/null && echo "โหมดเสียง: ทำงาน" || echo "โหมดเสียง: ❌ ไม่ทำงาน"
adb devices 2>/dev/null | grep -q "device$" && echo "ADB: เชื่อมอยู่" || echo "ADB: ❌ ไม่ได้เชื่อม"
python -c "import uiautomator2" 2>/dev/null && echo "อ่านจอแบบเร็ว: ติดตั้งแล้ว" || echo "อ่านจอแบบเร็ว: ยังไม่ติดตั้ง (bash setup_fast.sh)"
[ -f data/voiceprint.json ] && echo "จำเสียง: สอนแล้ว" || echo "จำเสียง: ยังไม่สอน/ลบแล้ว"
[ -f data/always_listen ] && echo "โหมด: ฟังตลอด" || echo "โหมด: รอคำปลุก"
grep -E "^(LLM_PROVIDER|SPEAKER_|ALWAYS_LISTEN|FAST_SCREEN)" .env 2>/dev/null
echo "===== bot.log ====="
grep -vE "^\s*$" data/bot.log 2>/dev/null | tail -25
echo "===== voice.log ====="
grep -vE "^\s*$|รอคำปลุก" data/voice.log 2>/dev/null | tail -25
