#!/usr/bin/env bash
PLIST_DEST="$HOME/Library/LaunchAgents/com.focusguard.app.plist"

if [ -f "$PLIST_DEST" ]; then
  launchctl unload -w "$PLIST_DEST" 2>/dev/null || true
  rm "$PLIST_DEST"
  echo "✓ FocusGuard uninstalled and stopped."
else
  echo "FocusGuard is not installed."
fi
