#!/usr/bin/env bash
# สร้าง APK ของ "ผู้ช่วย AI" — ดาวน์โหลดเครื่องมือที่ต้องใช้เองทั้งหมด (JDK 17, Android SDK, Gradle) ไว้ใน ~/.aibot-build
# ใช้: bash build_apk.sh   → ได้ไฟล์ aibot-app/app/build/outputs/apk/debug/app-debug.apk
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${AIBOT_TOOLS:-$HOME/.aibot-build}"
mkdir -p "$T"
cd "$T"
ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && JARCH=aarch64 || JARCH=x64

# ---- JDK 17
if [ ! -x "$T/jdk/bin/java" ]; then
  echo "⬇️  JDK 17"
  curl -fsSL -o jdk.tgz "https://api.adoptium.net/v3/binary/latest/17/ga/linux/$JARCH/jdk/hotspot/normal/eclipse"
  mkdir -p jdk && tar xzf jdk.tgz -C jdk --strip-components=1 && rm jdk.tgz
fi
export JAVA_HOME="$T/jdk" PATH="$T/jdk/bin:$PATH"

# ---- Android SDK
export ANDROID_HOME="$T/sdk" ANDROID_SDK_ROOT="$T/sdk"
if [ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  echo "⬇️  Android command-line tools"
  curl -fsSL -o clt.zip "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
  mkdir -p "$ANDROID_HOME/cmdline-tools" && unzip -q -o clt.zip -d "$ANDROID_HOME/cmdline-tools" && rm clt.zip
  rm -rf "$ANDROID_HOME/cmdline-tools/latest" && mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
fi
yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null 2>&1 || true
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platforms;android-34" "build-tools;34.0.0" "platform-tools" >/dev/null

# ---- Gradle
GV=8.7
if [ ! -x "$T/gradle-$GV/bin/gradle" ]; then
  echo "⬇️  Gradle $GV"
  curl -fsSL -o gradle.zip "https://services.gradle.org/distributions/gradle-$GV-bin.zip"
  unzip -q -o gradle.zip -d "$T" && rm gradle.zip
fi

# ---- Python สำหรับ Chaquopy (ต้องรุ่นเดียวกับที่ฝังในแอป)
PY=""
for v in 3.11 3.12 3.10; do command -v "python$v" >/dev/null && { PY="python$v"; PYV=$v; break; }; done
if [ -z "$PY" ]; then
  PY=python3; PYV=$($PY -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
fi
echo "🐍 ใช้ $PY ($PYV)"
$PY -m pip --version >/dev/null 2>&1 || echo "⚠️  $PY ไม่มี pip — Chaquopy ต้องใช้ pip ติดตั้ง requests"

cd "$HERE"
echo "sdk.dir=$ANDROID_HOME" > local.properties
"$T/gradle-$GV/bin/gradle" --no-daemon -PpyVersion="$PYV" -PbuildPython="$(command -v $PY)" assembleDebug
APK="$HERE/app/build/outputs/apk/debug/app-debug.apk"
ls -la "$APK"
cp "$APK" "$HERE/../ผู้ช่วยAI.apk" 2>/dev/null || true
echo "✅ เสร็จ: $APK"
