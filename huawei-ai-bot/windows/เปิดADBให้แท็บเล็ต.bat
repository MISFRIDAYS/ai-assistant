@echo off
chcp 65001 >nul
title Enable ADB for tablet
set "HERE=%~dp0"
set "ADB=%HERE%platform-tools\adb.exe"

if not exist "%ADB%" (
  echo [1/3] กำลังดาวน์โหลด Android Platform Tools จาก Google...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile '%HERE%pt.zip'; Expand-Archive -Force '%HERE%pt.zip' '%HERE%'; Remove-Item '%HERE%pt.zip'"
)
if not exist "%ADB%" (
  echo ดาวน์โหลดไม่สำเร็จ กรุณาเช็คอินเทอร์เน็ต
  pause
  exit /b 1
)

"%ADB%" kill-server >nul 2>&1
"%ADB%" start-server >nul 2>&1
echo.
echo [2/3] เสียบสาย USB จากแท็บเล็ตเข้าคอม
echo       - ถ้าแท็บเล็ตถามโหมด USB ให้เลือก "ถ่ายโอนไฟล์"
echo       - ถ้าแท็บเล็ตถาม "อนุญาตการดีบัก USB?" ให้ติ๊ก "อนุญาตเสมอ" แล้วกด ตกลง
echo       (ถ้ารอนานเกิน 1 นาที: เปลี่ยนสาย USB หรือติดตั้ง HUAWEI HiSuite เพื่อลงไดรเวอร์)
echo.
:wait
set "ST="
for /f "delims=" %%s in ('"%ADB%" get-state 2^>nul') do set "ST=%%s"
if /i not "%ST%"=="device" (
  timeout /t 2 /nobreak >nul
  goto wait
)

echo [3/3] เปิดโหมด ADB ไร้สาย (พอร์ต 5555)...
"%ADB%" tcpip 5555
timeout /t 3 /nobreak >nul
echo.
echo ===============================================
echo  เสร็จแล้ว! ถอดสาย USB ได้เลย
echo  ครั้งแรก: ใน Termux พิมพ์  adb connect 127.0.0.1:5555
echo  แล้วกด "อนุญาตเสมอ" บนแท็บเล็ตอีกครั้ง
echo  (หลังจากนั้นบอทจะเชื่อมต่อเองอัตโนมัติ)
echo  * ต้องทำขั้นตอนนี้ใหม่ทุกครั้งที่รีสตาร์ทแท็บเล็ต *
echo ===============================================
pause
