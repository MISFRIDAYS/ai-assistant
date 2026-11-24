#!/data/data/com.termux/files/usr/bin/bash
# ตั้งให้ใช้ Groq เป็นสมอง (ฟรี เร็ว โควตาเยอะ) — ใช้ GROQ_API_KEY ที่มีอยู่แล้ว
cd "$(dirname "$0")"
K="$(grep '^GROQ_API_KEY=' .env | cut -d= -f2)"
if [ -z "$K" ]; then
  echo "🔑 ยังไม่มี GROQ_API_KEY — ขอฟรีที่ console.groq.com/keys แล้ววางที่นี่ กด Enter:"
  printf "> "; read -r K; K="$(echo "$K" | tr -d ' \t\r\n')"
  [ -z "$K" ] && { echo "❌ ไม่ได้ใส่"; exit 1; }
fi
echo "⏳ ทดสอบ Groq และหารุ่นที่ใช้ได้..."
export _GK="$K"
R="$(python - <<'PY'
import os, requests
k=os.environ["_GK"]; h={"Authorization":f"Bearer {k}"}
try:
    m=requests.get("https://api.groq.com/openai/v1/models", headers=h, timeout=25)
except Exception as e:
    print("NET "+str(e)); raise SystemExit
if m.status_code!=200:
    print(f"ERR {m.status_code}: {m.text[:150]}"); raise SystemExit
ids=[x["id"] for x in m.json().get("data",[])]
skip=("whisper","guard","tts","embed","vision","distil","moderation","allam-")
order=("llama-3.3-70b","gpt-oss-120b","120b","qwen3","qwen","gpt-oss-20b","gpt-oss","llama-3.1-70b","70b","versatile","deepseek","kimi","gemma2-9b","mixtral","8b","instant")
chat=[i for i in ids if not any(k in i.lower() for k in skip)]
def sc(x):
    xl=x.lower()
    for n,k in enumerate(order):
        if k in xl: return n
    return len(order)
chat.sort(key=sc)
if not chat: print(f"ERR ไม่พบรุ่นแชท มีแต่: {ids[:8]}"); raise SystemExit
# ลองทีละรุ่นจนเจอที่รองรับ
model=None
for cand in chat[:6]:
    r=requests.post("https://api.groq.com/openai/v1/chat/completions", headers=h,
        json={"model":cand,"messages":[{"role":"user","content":"hi"}],"max_tokens":10}, timeout=25)
    if r.status_code==200: model=cand; break
if not model: print(f"ERR ลองแล้วไม่ได้: {chat[:6]}"); raise SystemExit
print("OK "+model); raise SystemExit
PY
)"
[ "${R:0:2}" != "OK" ] && { echo "❌ $R"; exit 1; }
MODEL="$(echo "$R"|cut -d' ' -f2)"
sed -i '/^LLM_PROVIDER=/d; /^GROQ_MODEL=/d; /^GROQ_API_KEY=/d' .env
{ echo "GROQ_API_KEY=$K"; echo "GROQ_MODEL=$MODEL"; echo "LLM_PROVIDER=groq"; } >> .env
echo "✅ ใช้ Groq ได้! รุ่น: $MODEL — เปิดบอทต่อด้วย: bash start_all.sh"
