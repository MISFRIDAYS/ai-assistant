#!/data/data/com.termux/files/usr/bin/bash
# เริ่มใหม่สะอาด: ล้างประวัติแชท ความจำ สกิล/ความรู้เก่า (เก็บ .env, ADB, AI ที่เลือก, เสียง ไว้)
cd "$(dirname "$0")"
bash stop_all.sh quiet
mkdir -p data ~/huawei-ai-bot-backup
TS=$(date +%Y%m%d_%H%M)
tar czf ~/huawei-ai-bot-backup/data_$TS.tgz data 2>/dev/null && echo "📦 สำรองข้อมูลเก่าไว้ที่ ~/huawei-ai-bot-backup/data_$TS.tgz"
find data -mindepth 1 -maxdepth 1 ! -name adb_address.txt ! -name provider.txt ! -name voice.json \
  ! -name balance.json -exec rm -rf {} +
echo "✅ ล้างประวัติแชท/ความจำ/สกิลเก่าแล้ว"
bash start_all.sh
