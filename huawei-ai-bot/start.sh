#!/data/data/com.termux/files/usr/bin/bash
# รันบอท Telegram และรีสตาร์ทอัตโนมัติถ้าหลุด (มีได้แค่ลูปเดียว)
cd "$(dirname "$0")"
command -v termux-wake-lock >/dev/null && termux-wake-lock
mkdir -p data
# กันลูปซ้อน: ถ้ามีลูปอื่นถือล็อกอยู่ ออกเลย
if command -v flock >/dev/null; then
  exec 9>data/bot_loop.lock
  if ! flock -n 9; then
    echo "มีลูปบอททำงานอยู่แล้ว" >> data/bot.log
    exit 0
  fi
fi
echo $$ > data/bot_loop.pid
while true; do
  echo "=== start $(date) ===" >> data/bot.log
  # เขียน log ลงไฟล์ตรงๆ (ไม่ผ่าน tee — ถ้า tee ตาย บอทจะตายตามแบบเงียบๆ)
  python -u bot.py >> data/bot.log 2>&1
  code=$?
  python self_heal.py --exit $code >> data/bot.log 2>&1   # ล่มหลังซ่อมตัวเอง → ย้อนโค้ดกลับอัตโนมัติ
  echo "=== บอทหยุด (exit $code$( [ $code -eq 137 ] && echo ' = ระบบฆ่าทิ้ง/แรมไม่พอ' )) $(date +%T) — เริ่มใหม่ใน 5 วิ ===" >> data/bot.log
  sleep 5
done
