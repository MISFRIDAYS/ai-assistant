#!/data/data/com.termux/files/usr/bin/bash
# ติดตั้งบอทบน Termux (มือถือ Huawei)
set -e
cd "$(dirname "$0")"
echo "📦 อัปเดตแพ็กเกจ..."
pkg update -y && pkg upgrade -y
pkg install -y python termux-api android-tools python-pillow python-numpy ffmpeg aapt
echo "🐍 ติดตั้งไลบรารี Python..."
pip install -r requirements.txt
chmod +x start.sh
[ -f .env ] || cp config.example.env .env

echo "🔁 ตั้งค่าให้เริ่มเองตอนเปิดเครื่อง (ต้องมีแอป Termux:Boot)..."
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-ai-bot.sh <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "$(pwd)"
nohup ./start.sh > /dev/null 2>&1 &
BOOT
chmod +x ~/.termux/boot/start-ai-bot.sh

echo ""
echo "✅ ติดตั้งเสร็จ!"
echo "ขั้นต่อไป: แก้ไฟล์ .env ด้วยคำสั่ง  nano .env"
echo "แล้วรันบอทด้วย  ./start.sh"
