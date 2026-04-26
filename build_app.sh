#!/usr/bin/env bash
# build_app.sh — Build SarcomaAI.app (macOS) and SarcomaAI.dmg
#
# Usage:
#   cd sarcomaAI-gui
#   ./build_app.sh
#
# Requires: dist_venv/ (already set up with all deps + pyinstaller)
# Requires: create-dmg  →  brew install create-dmg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/dist_venv"

echo "==> Step 1: Build React frontend"
cd frontend
npm run build
cd ..
echo "    React build complete → frontend/build/"

echo ""
echo "==> Step 2: Run PyInstaller (using dist_venv)"
"$VENV/bin/pyinstaller" sarcomaai.spec --noconfirm --clean

echo ""
echo "==> Step 3: Clean up intermediate build folder"
rm -rf dist/SarcomaAI

echo ""
echo "==> Step 4: Package into .dmg"
rm -f dist/SarcomaAI.dmg
create-dmg \
  --volname "SarcomaAI" \
  --volicon "sarcomaai.icns" \
  --background "sarcomaai.iconset/icon_512x512.png" \
  --window-pos 200 120 \
  --window-size 660 400 \
  --icon-size 128 \
  --icon "SarcomaAI.app" 180 185 \
  --hide-extension "SarcomaAI.app" \
  --app-drop-link 480 185 \
  "dist/SarcomaAI.dmg" \
  "dist/SarcomaAI.app"

echo ""
echo "==> Done."
echo "    App:  dist/SarcomaAI.app  ($(du -sh dist/SarcomaAI.app | cut -f1))"
echo "    DMG:  dist/SarcomaAI.dmg  ($(du -sh dist/SarcomaAI.dmg | cut -f1))"
echo "    Share the .dmg — users drag SarcomaAI to Applications and double-click."
