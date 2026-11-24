@echo off
chcp 65001 >nul
title Install Ollama for tablet AI
echo กำลังเปิดตัวติดตั้ง (จะมีหน้าต่างขอสิทธิ์ Administrator ให้กด Yes)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','\"%~dp0install_ollama.ps1\"')"
