#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# Activate and install deps if needed
source "$VENV/bin/activate"

if ! python -c "import rumps" 2>/dev/null; then
  echo "Installing dependencies into venv..."
  pip install --upgrade pip -q
  pip install -r requirements.txt -q
  echo "Done."
fi

# rumps requires an Info.plist with CFBundleIdentifier to use the notification center
PLIST="$VENV/bin/Info.plist"
if [ ! -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string "com.focusguard.app"' "$PLIST"
fi

echo "Starting FocusGuard... (look for 🎯 in your menu bar)"
python app.py
