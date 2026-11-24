#!/data/data/com.termux/files/usr/bin/bash
# สอนให้ผู้ช่วยจำเสียงเจ้าของ (ฟังเฉพาะเสียงคุณ ไม่สนเสียงคนอื่น/ทีวี)
cd "$(dirname "$0")"
if ! python -c "import numpy" 2>/dev/null; then
  echo "📦 ติดตั้ง numpy..."
  pkg install -y python-numpy
  if ! python -c "import numpy" 2>/dev/null; then
    echo "⚠️ mirror ที่ใช้อยู่มีปัญหา → สลับไปใช้ mirror หลักของ Termux แล้วลองใหม่"
    [ -f "$PREFIX/etc/apt/sources.list" ] && cp "$PREFIX/etc/apt/sources.list" "$PREFIX/etc/apt/sources.list.bak"
    echo "deb https://packages-cf.termux.dev/apt/termux-main stable main" > "$PREFIX/etc/apt/sources.list"
    rm -f "$PREFIX/etc/termux/chosen_mirrors" 2>/dev/null
    apt-get clean
    pkg update -y && pkg install -y python-numpy
  fi
  if ! python -c "import numpy" 2>/dev/null; then
    echo "❌ ติดตั้ง numpy ไม่สำเร็จ — ลองรัน termux-change-repo เลือก mirror อื่น แล้วรันสคริปต์นี้ใหม่"
    exit 1
  fi
fi
bash stop_all.sh quiet
python voice_chat.py --enroll
echo ""
echo "▶️ เริ่มผู้ช่วยใหม่..."
bash start_all.sh
