#!/data/data/com.termux/files/usr/bin/bash
# เริ่มทุกอย่างเบื้องหลัง: บอท Telegram + ผู้ช่วยเสียง (ไม่ต้องเปิด Termux ค้างไว้)
cd "$(dirname "$0")"
DIR="$(pwd)"
mkdir -p data
bash "$DIR/stop_all.sh" quiet
termux-wake-lock
nohup bash "$DIR/start.sh" > /dev/null 2>&1 &
VOICE=""
if grep -q "^GROQ_API_KEY=..*" .env && ! grep -q "^VOICE_AUTOSTART=0" .env; then
  sleep 2
  nohup python voice_chat.py --wake >> data/voice.log 2>&1 &
  VOICE=" · พูด 'สวัสดีผู้ช่วย' ได้เลย"
fi
termux-notification --id aibot --ongoing --priority low \
  -t "🤖 ผู้ช่วยทำงานอยู่" -c "สั่งผ่าน Telegram ได้ทุกที่${VOICE}" \
  --button1 "หยุด" --button1-action "bash $DIR/stop_all.sh" \
  --button2 "เริ่มใหม่" --button2-action "bash $DIR/start_all.sh" >/dev/null 2>&1
echo "✅ เริ่มผู้ช่วยแล้ว (ทำงานเบื้องหลัง)"
