#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PLIST_NAME="com.focusguard.app.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_FILE="$SCRIPT_DIR/logs/focusguard.log"

# ── 1. Ensure venv + deps ────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

if ! python -c "import rumps" 2>/dev/null; then
  echo "Installing dependencies..."
  pip install --upgrade pip -q
  pip install -r "$SCRIPT_DIR/requirements.txt" -q
fi

PLIST="$VENV/bin/Info.plist"
if [ ! -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string "com.focusguard.app"' "$PLIST"
fi

PYTHON="$VENV/bin/python"
mkdir -p "$SCRIPT_DIR/logs"

# ── 2. Write the LaunchAgent plist ───────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_DEST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.focusguard.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>ThrottleInterval</key>
    <integer>5</integer>
</dict>
</plist>
PLIST

# ── 3. Load (or reload) the agent ────────────────────────────────────────────
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo ""
echo "✓ FocusGuard installed and running."
echo "  Logs:      $LOG_FILE"
echo "  Uninstall: bash $SCRIPT_DIR/uninstall.sh"
echo ""
echo "It will restart automatically at every login."
