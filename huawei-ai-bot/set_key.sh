#!/data/data/com.termux/files/usr/bin/bash
# ตั้งค่า Gemini API key: รับได้ทั้งแบบใหม่ (AQ.) และเก่า (AIza) แล้วทดสอบกับรุ่นที่ใช้ได้จริง
cd "$(dirname "$0")"
echo ""
echo "🔑 วาง Gemini API key (รับได้ทั้ง AQ... และ AIza...) จาก aistudio.google.com/apikey"
echo "   แตะหน้าจอค้าง > Paste แล้วกด Enter:"
printf "> "
read -r KEY
KEY="$(echo "$KEY" | tr -d ' \t\r\n')"
[ -z "$KEY" ] && { echo "❌ ไม่ได้ใส่อะไรเลย"; exit 1; }
echo "⏳ กำลังทดสอบ key และหารุ่นที่ใช้ได้..."
export _TK="$KEY"
RESULT="$(python - <<'PY'
import os, requests, json
k=os.environ["_TK"]; base="https://generativelanguage.googleapis.com/v1beta"
h={"x-goog-api-key":k}
try:
    r=requests.get(base+"/models", headers=h, timeout=25)
except Exception as e:
    print("NET "+str(e)); raise SystemExit
if r.status_code!=200:
    print(f"ERR {r.status_code}: {r.text[:200]}"); raise SystemExit
models=[m["name"].split("/")[-1] for m in r.json().get("models",[])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])]
if not models:
    print("ERR ไม่มีรุ่นที่ใช้ได้ — ลองเปิด Gemini API ให้โปรเจกต์ก่อน"); raise SystemExit
import re
def ver(m):
    n=re.findall(r"(\d+(?:\.\d+)?)", m); return float(n[0]) if n else 0.0
flash=[m for m in models if "flash" in m and "lite" not in m and "latest" not in m] or models
flash.sort(key=ver, reverse=True)
tried=set()
def test(model):
    return requests.post(f"{base}/models/{model}:generateContent", headers=h,
                         json={"contents":[{"parts":[{"text":"hi"}]}]}, timeout=25)
model=flash[0]
for _ in range(4):
    tried.add(model)
    r2=test(model)
    if r2.status_code==200:
        print("OK "+model); break
    sug=re.search(r"use models/([\w.\-]+)", r2.text)
    if sug and sug.group(1) not in tried:
        model=sug.group(1); continue
    nxt=[m for m in flash if m not in tried]
    if nxt: model=nxt[0]; continue
    print(f"ERR {r2.status_code}: {r2.text[:200]}"); break
else:
    print(f"ERR ลองหลายรุ่นแล้วไม่ได้")
PY
)"
if [ "${RESULT:0:2}" != "OK" ]; then
  echo "❌ ใช้ไม่ได้: $RESULT"
  exit 1
fi
MODEL="$(echo "$RESULT" | cut -d' ' -f2)"
sed -i '/^GEMINI_API_KEY=/d; /^LLM_PROVIDER=/d; /^GEMINI_MODEL=/d' .env 2>/dev/null
{ echo "GEMINI_API_KEY=$KEY"; echo "LLM_PROVIDER=gemini"; echo "GEMINI_MODEL=$MODEL"; } >> .env
echo "✅ key ใช้ได้! รุ่น: $MODEL — บันทึกแล้วและตั้งให้ใช้ Gemini"
echo "   เปิดบอทต่อด้วย:  bash start_all.sh"
