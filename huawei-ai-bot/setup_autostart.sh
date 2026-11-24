#!/data/data/com.termux/files/usr/bin/bash
# ตั้งค่าครั้งเดียว: เริ่มเองตอนเปิดเครื่อง + ปุ่มบนหน้าจอหลัก (ไม่ต้องพิมพ์คำสั่งอีก)
cd "$(dirname "$0")"
DIR="$(pwd)"
chmod +x start.sh start_all.sh stop_all.sh
pkg install -y procps >/dev/null 2>&1 || true

# เปิดเครื่อง → เริ่มเอง (ต้องมีแอป Termux:Boot และเคยเปิดแอปนั้น 1 ครั้ง)
mkdir -p ~/.termux/boot
rm -f ~/.termux/boot/start-ai-bot.sh ~/.termux/boot/start-voice.sh
cat > ~/.termux/boot/start-ai.sh <<B
#!/data/data/com.termux/files/usr/bin/bash
sleep 15
bash "$DIR/start_all.sh"
B
chmod +x ~/.termux/boot/start-ai.sh

# ปุ่มบนหน้าจอหลัก (Termux:Widget)
mkdir -p ~/.shortcuts/tasks
rm -f ~/.shortcuts/tasks/*.sh
cat > ~/.shortcuts/tasks/▶️\ เริ่มผู้ช่วย.sh <<B
#!/data/data/com.termux/files/usr/bin/bash
bash "$DIR/start_all.sh"
B
cat > ~/.shortcuts/tasks/⏹️\ หยุดผู้ช่วย.sh <<B
#!/data/data/com.termux/files/usr/bin/bash
bash "$DIR/stop_all.sh"
B
cat > ~/.shortcuts/tasks/🎤\ ถามครั้งเดียว.sh <<B
#!/data/data/com.termux/files/usr/bin/bash
cd "$DIR" && python voice_chat.py --once >> data/voice.log 2>&1
B
chmod +x ~/.shortcuts/tasks/*.sh

echo "✅ ตั้งค่าเสร็จ!"
echo "- รีสตาร์ทเครื่องเมื่อไหร่ ผู้ช่วยจะเริ่มเอง"
echo "- หรือกดปุ่ม '▶️ เริ่มผู้ช่วย' ใน widget / ปุ่ม 'หยุด' ในแถบแจ้งเตือน"
bash "$DIR/start_all.sh"
