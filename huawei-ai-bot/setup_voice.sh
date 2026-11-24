#!/data/data/com.termux/files/usr/bin/bash
# ติดตั้งผู้ช่วยเสียง (เรียลไทม์ + คำปลุก "สวัสดีผู้ช่วย") และปุ่มบนหน้าจอหลัก (Termux:Widget)
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "📦 ติดตั้งโปรแกรมเสียง (PulseAudio สำหรับฟังเรียลไทม์, ffmpeg สำหรับวิธีสำรอง)..."
pkg install -y play-audio pulseaudio ffmpeg procps
pip install gTTS
echo "🗣️ ติดตั้งเสียงพูดแบบคน (edge-tts)..."
MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1 \
  AIOHTTP_NO_EXTENSIONS=1 pip install edge-tts || echo "⚠️ ติดตั้ง edge-tts ไม่สำเร็จ จะใช้เสียง Google แทน"

grep -q "^GROQ_API_KEY=" .env || echo "GROQ_API_KEY=" >> .env

echo "🔘 สร้างปุ่มบนหน้าจอหลัก..."
mkdir -p ~/.shortcuts/tasks
rm -f ~/.shortcuts/tasks/เปิดโหมดรอคำปลุก.sh ~/.shortcuts/tasks/ปิดโหมดรอคำปลุก.sh
cat > ~/.shortcuts/tasks/เปิดผู้ช่วยเสียง.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "$DIR" && nohup python voice_chat.py --wake >> data/voice.log 2>&1 &
EOF
cat > ~/.shortcuts/tasks/ปิดผู้ช่วยเสียง.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
pkill -f "voice_chat.py" ; rm -f "$DIR/data/voice_chat.pid"
EOF
cat > ~/.shortcuts/tasks/คุยกับผู้ช่วย.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$DIR" && python voice_chat.py >> data/voice.log 2>&1
EOF
cat > ~/.shortcuts/tasks/ถามครั้งเดียว.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$DIR" && python voice_chat.py --once >> data/voice.log 2>&1
EOF
chmod +x ~/.shortcuts/tasks/*.sh

if [ "$1" = "--boot" ]; then
  mkdir -p ~/.termux/boot
  cat > ~/.termux/boot/start-voice.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
sleep 20
cd "$DIR" && nohup python voice_chat.py --wake >> data/voice.log 2>&1 &
EOF
  chmod +x ~/.termux/boot/start-voice.sh
  echo "🔁 ตั้งให้ผู้ช่วยเสียงเริ่มเองตอนเปิดเครื่องแล้ว"
fi

echo ""
echo "✅ เสร็จแล้ว!"
echo "1) ใส่ GROQ_API_KEY ใน .env  (nano .env)"
echo "2) ทดสอบไมค์เรียลไทม์:  python voice_chat.py --test"
echo "3) เปิดผู้ช่วย:  python voice_chat.py --wake   แล้วพูด 'สวัสดีผู้ช่วย'"
