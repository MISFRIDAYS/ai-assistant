# Todo: ลดค่าใช้จ่าย + ปิดจุดอ่อน

## Task 1: ลดรอบ agent + ประวัติ (XS)
**ทำอะไร:** `agent.py` MAX_STEPS 25 → 8 (อ่านจาก env `MAX_STEPS`), `MAX_HISTORY` 30 → 14
**Acceptance:**
- [ ] คำสั่งเดียวเรียก AI ไม่เกิน 8 ครั้ง; ครบแล้วตอบ "ยังไม่เสร็จ พิมพ์ ต่อ"
- [ ] ประวัติที่ส่งไม่เกิน 14 ข้อความ
**Verify:** `python -m unittest discover tests` ผ่าน; สั่ง "เปิดไลน์แล้วส่งหาแม่" ยังทำได้
**Depends:** None · **Files:** `agent.py`, `config.py`, `config.example.env`

## Task 2: จำกัดโหมดมองจอ (XS)
**ทำอะไร:** `VISION_MAX_STEPS` 14 → 6, `screen_task.py:209` ใช้ `quality=False` (ตัวเร็ว/ฟรีก่อน) ยกเว้นขั้นที่ล้มเหลวซ้ำ
**Acceptance:**
- [ ] งานบนจอใช้ภาพไม่เกิน 6 ภาพ
- [ ] ขั้นแรกใช้ Groq/Gemini ก่อนรุ่นแพง
**Verify:** เทสต์ผ่าน; ลองงานบนจอ 3 งานที่ใช้บ่อย
**Depends:** None · **Files:** `screen_task.py`, `config.example.env`

## Task 3: autoreply ปิดค่าเริ่มต้น + เพดานต่อวัน (S)
**ทำอะไร:** `autoreply.py:39` `enabled` → False; เพิ่ม `AUTOREPLY_DAILY_MAX` (ค่าเริ่ม 30) ครบแล้วหยุดตอบ + แจ้งเจ้าของ
**Acceptance:**
- [ ] ติดตั้งใหม่ไม่ตอบแชทเองจนกว่าจะเปิด
- [ ] ครบเพดานแล้วไม่เรียก AI อีกในวันนั้น
**Verify:** เพิ่มเทสต์ใน `tests/test_bot.py`; เทสต์ผ่าน
**Depends:** None · **Files:** `autoreply.py`, `tests/test_bot.py`

## Task 4: ปิด self-heal เป็นค่าเริ่มต้น (XS)
**ทำอะไร:** `SELF_REPAIR` ค่าเริ่ม `ask` → `off`, max_tokens 8000 → 4000, เอาคำแนะนำ Sonnet ออก
**Acceptance:**
- [ ] ไม่มีการเรียก AI ซ่อมโค้ดถ้าไม่ได้เปิดเอง
**Verify:** เทสต์ผ่าน
**Depends:** None · **Files:** `self_heal.py`, `config.example.env`

## Checkpoint 1
- [ ] เทสต์ทั้งหมดผ่าน · [ ] Build APK ผ่าน · [ ] ใช้จริง 2-3 วัน เทียบบิล · [ ] คุยผลกับเจ้าของก่อนไปต่อ

## Task 5: ตัวนับ token + เพดานงบรายวัน (M)
**ทำอะไร:** จดยอด token เข้า/ออก ต่อผู้ให้บริการต่อวันจาก response ของ `claude_client` / `gemini_client` / `cloud_client` ลง `data/usage.json`; เกิน `DAILY_BUDGET_USD` → สลับไปตัวฟรีหรือหยุด + แจ้งเตือน
**Acceptance:**
- [ ] สั่ง "ใช้ไปเท่าไร" ได้ยอดวันนี้/เดือนนี้
- [ ] เกินงบแล้วไม่เรียกตัวที่เสียเงิน
**Verify:** เทสต์ใหม่จำลองยอดเกินงบ; เทสต์ผ่าน
**Depends:** None · **Files:** `agent.py`, `claude_client.py`, ไฟล์ใหม่ `usage.py`, `tests/test_bot.py`

## Task 6: CI build เฉพาะโค้ดแอป + รันเทสต์ (S)
**ทำอะไร:** `build.yml` ใส่ `paths:` (zip/โค้ด), จำกัด branch `main`, เพิ่มขั้นรัน unittest ก่อน build
**Acceptance:**
- [ ] push ที่แก้แค่ `.claude/` หรือ `tasks/` ไม่ build
- [ ] เทสต์พัง → build ไม่ออก release
**Verify:** ดูผลใน Actions 2 รอบ (แก้เอกสาร / แก้โค้ด)
**Depends:** None · **Files:** `.github/workflows/build.yml`

## Checkpoint 2
- [ ] เห็นยอดใช้รายวัน · [ ] CI ไม่ build เปล่า

## Task 7: แตก zip เป็นโค้ดจริง + ลบขยะ (M)
**ทำอะไร:** แตก v52 ลง repo, ลบ zip, `build-1.yml`, `.github/workflows/ai-assistant-apk-v12.zip`, ไม่ commit `python/` libs ที่ vendored ถ้า pip ทำได้; แก้ workflow ไม่ต้อง unzip
**Acceptance:** [ ] build จากโค้ดตรงได้ APK เดิม · [ ] ไม่มี zip ใน repo
**Depends:** T6 · **Files:** workflow + ย้ายไฟล์

## Task 8: ย้ายกุญแจเซ็นแอปไป Secrets (S)
**ทำอะไร:** keystore (ตัวเดิม) → base64 ใน GitHub Secrets, รหัสอ่านจาก env, ลบออกจาก repo
**Acceptance:** [ ] ไม่มี keystore/รหัสใน repo · [ ] APK ใหม่ติดตั้งทับรุ่นเก่าได้
**Depends:** T7 · **Files:** `aibot-app/app/build.gradle.kts`, workflow

## Task 9: ลดผู้ให้บริการ AI เหลือ 2 ตัว (M) — รอคำตอบเจ้าของก่อน
**ทำอะไร:** เก็บตัวหลักฟรี + Claude Haiku; ตัวที่เหลือปิด/ลบ
**Depends:** Checkpoint 2 · **Files:** `providers.py`, `agent.py`, `vision.py`, client ที่ไม่ใช้

## Task 10: ลด agent skills เหลือที่ใช้จริง (XS)
**ทำอะไร:** ลบ skills/commands ใน `.claude/` ที่ไม่เกี่ยวกับโปรเจกต์นี้ (เช่น browser-testing, observability, deprecation, ci-cd ฯลฯ)
**Depends:** None · **Files:** `.claude/skills/*`

## Checkpoint 3
- [ ] Build ผ่าน · [ ] ติดตั้งทับได้ · [ ] เทสต์ผ่าน · [ ] เจ้าของรีวิว
