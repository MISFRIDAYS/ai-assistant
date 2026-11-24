#!/data/data/com.termux/files/usr/bin/bash
# ตั้งให้ใช้ Ollama บนคอมเป็นสมอง (ฟรี ไม่จำกัด เครื่องมือครบ) + Claude สำรองตอนคอมปิด
# ใส่ได้หลาย IP — แนะนำ: IP Tailscale (ใช้ได้ทุกที่) ตามด้วย IP Wi-Fi บ้าน (สำรองตอน Tailscale ปิด)
#   bash set_ollama.sh 100.101.102.103 192.168.1.50
cd "$(dirname "$0")"
IPS="$*"
if [ -z "$IPS" ]; then
  echo "💻 ใส่ IP ของคอม (จากหน้าต่างติดตั้งบนคอม) — ใส่ได้ 2 ตัว คั่นด้วยเว้นวรรค แล้วกด Enter:"
  echo "   เช่น  100.101.102.103 192.168.1.50   (ตัวที่ขึ้นต้น 100. คือ Tailscale)"
  printf "> "; read -r IPS
fi

URLS=""
for ip in $IPS; do
  ip="$(echo "$ip" | sed 's#^http://##; s#:11434.*##; s#/.*##; s#,##g')"
  [ -n "$ip" ] && URLS="${URLS:+$URLS,}http://$ip:11434"
done
[ -z "$URLS" ] && { echo "❌ ไม่ได้ใส่ IP"; exit 1; }
MODEL="$(grep '^OLLAMA_MODEL=' .env | cut -d= -f2)"; MODEL="${MODEL:-qwen3.5:9b}"

echo "⏳ ทดสอบเชื่อมต่อ..."
ANY=""; TS_FAIL=""
for u in $(echo "$URLS" | tr ',' ' '); do
  export _OU="$u" _OM="$MODEL"
  R="$(python - <<'PY'
import os, requests, time
u, m = os.environ["_OU"], os.environ["_OM"]
try:
    tags = requests.get(u + "/api/tags", timeout=6).json()
except Exception as e:
    print("NET " + e.__class__.__name__); raise SystemExit
names = [x.get("name", "") for x in tags.get("models", [])]
if not any(n == m or n.split(":")[0] == m for n in names):
    print("NOMODEL " + (", ".join(names) or "-")); raise SystemExit
t = time.time()
body = {"model": m, "max_tokens": 20, "reasoning_effort": "none",
        "messages": [{"role": "user", "content": "ตอบคำเดียวว่า พร้อม"}]}
try:
    r = requests.post(u + "/v1/chat/completions", timeout=300, json=body)
    if r.status_code == 400 and "reasoning" in r.text.lower():
        body.pop("reasoning_effort"); r = requests.post(u + "/v1/chat/completions", timeout=300, json=body)
except Exception as e:
    print("NET " + e.__class__.__name__); raise SystemExit
print(f"OK {time.time() - t:.1f}" if r.status_code == 200 else f"ERR {r.status_code}: {r.text[:120]}")
PY
)"
  case "$R" in
    OK*) echo "  ✅ $u  ตอบใน ${R#OK } วินาที"; ANY=1;;
    NOMODEL*) echo "  ⚠️  $u  คอมเปิดอยู่ แต่ยังไม่มีโมเดล $MODEL — บนคอมพิมพ์: ollama pull $MODEL";;
    NET*) echo "  ⚪ $u  ยังเชื่อมไม่ได้ตอนนี้ ($R)"; case "$u" in *//100.*) TS_FAIL=1;; esac;;
    *) echo "  ❌ $u  $R";;
  esac
done

if [ -n "$TS_FAIL" ]; then
  echo
  echo "📲 IP Tailscale ยังเชื่อมไม่ได้ — ต้องมีแอป Tailscale บนแท็บเล็ตและกดเชื่อมต่ออยู่:"
  echo "   1) ติดตั้ง Tailscale จาก F-Droid (กำลังเปิดหน้าให้)  2) ล็อกอินบัญชีเดียวกับบนคอม"
  echo "   3) กดเชื่อมต่อ + อนุญาต VPN  4) แนะนำ: ตั้งค่า > VPN > Tailscale > เปิด Always-on VPN"
  echo "   ทำเสร็จแล้วรันคำสั่งนี้ซ้ำเพื่อทดสอบ (ระหว่างนี้ในบ้านยังใช้ผ่าน Wi-Fi ได้ ถ้าใส่ IP 192.168.x ไว้ด้วย)"
  termux-open-url "https://f-droid.org/packages/com.tailscale.ipn/" 2>/dev/null
fi
if [ -z "$ANY" ]; then
  echo "❌ ยังเชื่อมคอมไม่ได้เลยสักที่อยู่ ตรวจ:"
  echo "   1) คอมเปิดอยู่และรัน ติดตั้งOllama.bat แล้ว   2) IP ถูกต้อง"
  echo "   3) ถ้าใช้ IP 100.x: แอป Tailscale บนแท็บเล็ตต้องเชื่อมต่ออยู่ (บัญชีเดียวกับคอม)"
  echo "   4) ถ้าใช้ IP 192.168.x: แท็บเล็ตต้องต่อ Wi-Fi บ้านเดียวกับคอม"
  exit 1
fi

sed -i '/^LLM_PROVIDER=/d; /^LLM_FALLBACK=/d; /^OLLAMA_URL=/d; /^OLLAMA_MODEL=/d' .env
FB=none
grep -q '^ANTHROPIC_API_KEY=..*' .env && FB=claude
[ "$FB" = none ] && grep -q '^GROQ_API_KEY=..*' .env && FB=groq
{ echo "LLM_PROVIDER=ollama"; echo "LLM_FALLBACK=$FB"; echo "OLLAMA_URL=$URLS"; echo "OLLAMA_MODEL=$MODEL"; } >> .env
echo "✅ ตั้งค่าเสร็จ! สมองหลัก: $MODEL บนคอม | ตัวสำรองตอนคอมปิด: $FB"
echo "   ที่อยู่ที่บอทจะลองตามลำดับ: $URLS"
echo "   รีสตาร์ทบอท: pkill -9 -f python; sleep 2; bash start_all.sh"
