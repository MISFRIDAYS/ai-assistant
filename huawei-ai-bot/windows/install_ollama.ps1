# ติดตั้ง Ollama บนคอม ให้แท็บเล็ตเรียกใช้ผ่าน Wi-Fi บ้าน (ฟรี ไม่จำกัด)
# สเปกที่ออกแบบไว้: RTX 5060 Ti 16GB — โมเดล qwen3.5:9b + บริบท 32K
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Model = 'qwen3.5:9b'
$Port  = 11434

function Step($n, $t) { Write-Host ""; Write-Host "[$n/8] $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  !!  $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "  XX  $t" -ForegroundColor Red; Read-Host "กด Enter เพื่อปิด"; exit 1 }

Write-Host "=== ติดตั้ง Ollama สำหรับผู้ช่วย AI บนแท็บเล็ต ===" -ForegroundColor White

# ---------------------------------------------------------------- 1) ติดตั้ง Ollama
Step 1 "ติดตั้ง Ollama"
function Find-Ollama {
  $c = Get-Command ollama -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($p in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
    if (Test-Path $p) { return $p }
  }
  return $null
}
$exe = Find-Ollama
if (-not $exe) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "  กำลังดาวน์โหลดและติดตั้งผ่าน winget..."
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  } else {
    Warn "ไม่พบ winget — จะเปิดหน้าดาวน์โหลด ให้ติดตั้งเองแล้วกลับมากด Enter"
    Start-Process "https://ollama.com/download/windows"
    Read-Host "  ติดตั้งเสร็จแล้วกด Enter"
  }
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  $exe = Find-Ollama
}
if (-not $exe) { Fail "ยังหา Ollama ไม่เจอ ลองติดตั้งจาก https://ollama.com/download แล้วรันสคริปต์นี้ใหม่" }
Ok "พบ Ollama: $exe"

# ---------------------------------------------------------------- 2) ตั้งค่า
Step 2 "ตั้งค่าให้แท็บเล็ตเชื่อมต่อได้ + รองรับเครื่องมือครบ"
$vars = [ordered]@{
  OLLAMA_HOST            = "0.0.0.0:$Port"   # รับการเชื่อมต่อจากเครื่องอื่นในบ้าน
  OLLAMA_CONTEXT_LENGTH  = '32768'           # บริบทยาวพอสำหรับเครื่องมือ 54 ตัว + ประวัติแชท
  OLLAMA_KEEP_ALIVE      = '24h'             # ค้างโมเดลไว้ในการ์ดจอ ไม่ต้องโหลดใหม่ทุกครั้ง
  OLLAMA_FLASH_ATTENTION = '1'               # ประหยัดหน่วยความจำ ตอบเร็วขึ้น
  OLLAMA_KV_CACHE_TYPE   = 'q8_0'            # ลดหน่วยความจำของบริบทยาวลงครึ่งหนึ่ง
}
foreach ($k in $vars.Keys) {
  [Environment]::SetEnvironmentVariable($k, $vars[$k], 'Machine')
  [Environment]::SetEnvironmentVariable($k, $null, 'User')    # กันค่าเก่าระดับผู้ใช้ทับ
  Set-Item "env:$k" $vars[$k]
  Ok "$k = $($vars[$k])"
}

# ---------------------------------------------------------------- 3) Firewall
Step 3 "เปิด Firewall พอร์ต $Port (เฉพาะเครือข่ายในบ้าน)"
$rule = 'Ollama (แท็บเล็ต AI)'
if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private,Domain | Out-Null
}
Ok "อนุญาตพอร์ต $Port แล้ว (Private network)"
$pub = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' })
foreach ($p in $pub) {
  Warn "Wi-Fi '$($p.Name)' ถูกตั้งเป็น Public — แท็บเล็ตจะเชื่อมไม่ได้"
  $a = Read-Host "  เปลี่ยน '$($p.Name)' เป็น Private (เครือข่ายในบ้านที่เชื่อถือได้) ไหม? [Y/n]"
  if ($a -notmatch '^[nN]') {
    Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
    Ok "เปลี่ยนเป็น Private แล้ว"
  } else {
    Warn "ข้าม — ถ้าแท็บเล็ตเชื่อมไม่ได้ ให้ตั้งเครือข่ายนี้เป็น Private ภายหลัง"
  }
}

# ---------------------------------------------------------------- 4) รีสตาร์ท Ollama
Step 4 "เริ่ม Ollama ใหม่ด้วยค่าที่ตั้ง"
Get-Process -Name 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$app = Join-Path (Split-Path $exe) 'ollama app.exe'
if (Test-Path $app) {
  Start-Process explorer.exe -ArgumentList "`"$app`""        # เปิดแบบผู้ใช้ปกติ (ไม่ใช่ admin)
} else {
  Start-Process $exe -ArgumentList 'serve' -WindowStyle Hidden
}
$up = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try { Invoke-RestMethod "http://127.0.0.1:$Port/api/tags" -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
}
if (-not $up) {
  Warn "แอป Ollama ยังไม่ตอบ — เปิดแบบเบื้องหลังแทน"
  Start-Process $exe -ArgumentList 'serve' -WindowStyle Hidden
  Start-Sleep -Seconds 4
  try { Invoke-RestMethod "http://127.0.0.1:$Port/api/tags" -TimeoutSec 3 | Out-Null; $up = $true } catch {}
}
if (-not $up) { Fail "เปิด Ollama ไม่ขึ้น — ลองรีสตาร์ทคอมแล้วรันสคริปต์นี้ใหม่" }
$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalAddress
if ($listen -contains '0.0.0.0' -or $listen -contains '::') { Ok "Ollama รับการเชื่อมต่อจากแท็บเล็ตได้" }
else { Warn "Ollama ยังฟังแค่ในเครื่อง ($($listen -join ', ')) — ให้ Sign out/รีสตาร์ทคอมหนึ่งครั้ง" }

# ---------------------------------------------------------------- 5) โหลดโมเดล
Step 5 "ดาวน์โหลดโมเดล $Model (ประมาณ 6.6GB — ครั้งเดียว)"
& $exe pull $Model
if ($LASTEXITCODE -ne 0) { Fail "ดาวน์โหลดโมเดลไม่สำเร็จ — เช็คอินเทอร์เน็ตแล้วรันสคริปต์นี้ใหม่ (จะต่อจากเดิม)" }
Ok "โหลดโมเดลเสร็จ"

# ---------------------------------------------------------------- 6) ทดสอบ
Step 6 "ทดสอบให้โมเดลตอบ (ครั้งแรกจะช้ากว่าเพราะโหลดเข้าการ์ดจอ)"
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
  $body = @{ model = $Model; stream = $false;
             messages = @(@{ role = 'user'; content = 'ทักทายสั้นๆ 1 ประโยค' }) } | ConvertTo-Json -Depth 5
  $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/chat" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json' -TimeoutSec 300
  Ok ("ตอบใน {0:N1} วินาที: {1}" -f $sw.Elapsed.TotalSeconds, $r.message.content.Trim())
} catch { Warn "ทดสอบไม่ผ่าน: $($_.Exception.Message)" }
$ps = & $exe ps 2>$null
if ($ps -match 'GPU') { Ok "โมเดลรันบนการ์ดจอ" } else { Warn "ตรวจไม่พบว่ารันบน GPU — อัปเดตไดรเวอร์ NVIDIA เป็นรุ่นล่าสุด" }

# ---------------------------------------------------------------- 7) Tailscale (ใช้ได้แม้พกแท็บเล็ตออกนอกบ้าน)
Step 7 "ติดตั้ง Tailscale — ให้แท็บเล็ตเรียกใช้คอมได้จากทุกที่ (ฟรี)"
function Find-Tailscale {
  $c = Get-Command tailscale -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  $p = "$env:ProgramFiles\Tailscale\tailscale.exe"
  if (Test-Path $p) { return $p }
  return $null
}
$ts = Find-Tailscale
if (-not $ts -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "  กำลังติดตั้ง Tailscale ผ่าน winget..."
  winget install -e --id Tailscale.Tailscale --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  Start-Sleep -Seconds 5
  $ts = Find-Tailscale
}
$tsip = $null
if (-not $ts) {
  Warn "ติดตั้ง Tailscale ไม่สำเร็จ — ข้ามไปก่อน (ในบ้านยังใช้ได้ปกติ) ติดตั้งเองได้ที่ https://tailscale.com/download"
} else {
  $tsip = (& $ts ip -4 2>$null) | Where-Object { $_ -match '^100\.' } | Select-Object -First 1
  if (-not $tsip) {
    Write-Host "  ล็อกอิน Tailscale: ถ้าเบราว์เซอร์ไม่เปิดเอง ให้กด Ctrl+คลิก ลิงก์ที่ขึ้นด้านล่าง" -ForegroundColor White
    Write-Host "  (ใช้บัญชี Google/Microsoft/อีเมล — บนแท็บเล็ตต้องล็อกอินบัญชีเดียวกัน)" -ForegroundColor White
    & $ts up --unattended
    $tsip = (& $ts ip -4 2>$null) | Where-Object { $_ -match '^100\.' } | Select-Object -First 1
  }
  & $ts set --unattended=true 2>$null | Out-Null     # ทำงานต่อแม้ยังไม่ได้ล็อกอิน Windows
  if ($tsip) { Ok "IP Tailscale ของคอมนี้: $tsip" } else { Warn "ยังไม่ได้ IP Tailscale — เปิดแอป Tailscale จากถาดไอคอนแล้วล็อกอิน จากนั้นรันสคริปต์นี้ใหม่" }
}
$rule2 = 'Ollama (Tailscale)'
if (-not (Get-NetFirewallRule -DisplayName $rule2 -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $rule2 -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -RemoteAddress 100.64.0.0/10 -Profile Any | Out-Null
}
Ok "เปิด Firewall ให้เฉพาะเครื่องในวง Tailscale ของคุณ"

# ---------------------------------------------------------------- 8) กันคอมหลับ + แสดง IP
Step 8 "ตั้งค่าเสร็จ"
$a = Read-Host "  ปิดการพักเครื่อง (Sleep) ตอนเสียบปลั๊ก เพื่อให้ผู้ช่วยใช้ได้ตลอดไหม? [Y/n]"
if ($a -notmatch '^[nN]') { powercfg /change standby-timeout-ac 0; Ok "คอมจะไม่หลับเองตอนเสียบปลั๊ก (จอยังดับได้ตามปกติ)" }

$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|100\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback|VirtualBox|VMware|WSL|Tailscale' } |
  Select-Object -ExpandProperty IPAddress
# เลือก IP วงในบ้านก่อน (192.168.x / 10.x / 172.16-31.x) — ตัดพวก VPN เกม เช่น Radmin (26.x) ออก
$home_ips = @($ips | Where-Object { $_ -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' })
if ($home_ips.Count -gt 0) { $ips = $home_ips }
$lan = $ips | Select-Object -First 1
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
if ($tsip) { Write-Host "  IP Tailscale (ใช้ได้ทุกที่):  $tsip" -ForegroundColor Green }
Write-Host "  IP Wi-Fi บ้าน:               $($ips -join '  หรือ  ')" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "ขั้นต่อไป — บนแท็บเล็ต เปิด Termux แล้วพิมพ์ (ใส่ทั้ง 2 IP บอทจะเลือกตัวที่ใช้ได้เอง):"
Write-Host "  cd ~/huawei-ai-bot && bash set_ollama.sh $((@($tsip, $lan) -ne $null) -join ' ')" -ForegroundColor Yellow
Write-Host ""
Write-Host "แนะนำ: ตั้ง 'จอง IP' (DHCP reservation) ให้คอมนี้ในเราเตอร์ เพื่อไม่ให้ IP Wi-Fi บ้านเปลี่ยน"
Write-Host "Ollama และ Tailscale จะเปิดเองทุกครั้งที่เปิดคอม ไม่ต้องรันสคริปต์นี้ซ้ำ"
Read-Host "กด Enter เพื่อปิด"
