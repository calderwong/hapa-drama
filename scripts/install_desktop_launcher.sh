#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_APP="${1:-$HOME/Desktop/Hapa Drama.app}"
EXECUTABLE_NAME="Hapa Drama"

mkdir -p "$TARGET_APP/Contents/MacOS" "$TARGET_APP/Contents/Resources"

cat > "$TARGET_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>Hapa Drama</string>
  <key>CFBundleExecutable</key>
  <string>${EXECUTABLE_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>local.hapa.drama.launcher</string>
  <key>CFBundleName</key>
  <string>Hapa Drama</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$TARGET_APP/Contents/MacOS/$EXECUTABLE_NAME" <<LAUNCHER
#!/usr/bin/env zsh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
export HAPA_DRAMA_HOST="\${HAPA_DRAMA_HOST:-127.0.0.1}"
export HAPA_DRAMA_PORT="\${HAPA_DRAMA_PORT:-8758}"
cd "$ROOT_DIR"
exec "$ROOT_DIR/scripts/launch_hapa_drama.sh" --electron
LAUNCHER

chmod +x "$TARGET_APP/Contents/MacOS/$EXECUTABLE_NAME"
touch "$TARGET_APP"
echo "Installed $TARGET_APP"
