#!/data/data/com.termux/files/usr/bin/bash
# หยุดบอท Telegram + ผู้ช่วยเสียง (รวมลูปเก่าที่ค้างจากการอัปเดตครั้งก่อนๆ)
cd "$(dirname "$0")"
[ -f data/bot_loop.pid ] && kill "$(cat data/bot_loop.pid)" 2>/dev/null
pkill -f "bash .*start\.sh" 2>/dev/null
pkill -f "huawei-ai-bot/start\.sh" 2>/dev/null
pkill -f "python.* bot\.py" 2>/dev/null
pkill -f "voice_chat\.py" 2>/dev/null
pkill -f "parec -d" 2>/dev/null
pulseaudio -k 2>/dev/null          # ปิด PulseAudio ให้สะอาด รอบหน้าเปิดใหม่ไม่ค้าง
termux-microphone-record -q >/dev/null 2>&1
sleep 1
pkill -9 -f "python.* bot\.py" 2>/dev/null
pkill -9 -f "voice_chat\.py" 2>/dev/null
rm -f data/voice_chat.pid data/bot_loop.pid
if [ "$1" != "quiet" ]; then
  termux-notification-remove aibot 2>/dev/null
  termux-wake-unlock 2>/dev/null
  echo "⏹️ หยุดผู้ช่วยแล้ว"
fi
