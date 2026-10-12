#!/bin/sh
# Start Colony (and the OpenClaw Gateway it runs) automatically when you log in, so opening the app just works.
#   scripts/autostart.sh install     turn it on (and start it now)
#   scripts/autostart.sh uninstall   turn it off
#   scripts/autostart.sh status
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LABEL=dev.colony.local
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
NODE_DIR=$(dirname "$(command -v node)")

case "$1" in
install)
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.colony"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$ROOT/.venv/bin/colony</string><string>--no-open</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$NODE_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.colony/colony-server.log</string>
  <key>StandardErrorPath</key><string>$HOME/.colony/colony-server.log</string>
</dict></plist>
PLIST
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Colony will now start at login. Starting it now (the chat is ready after ~2 minutes)."
  ;;
uninstall)
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Autostart removed."
  ;;
status)
  launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state|pid" || echo "not installed"
  ;;
*)
  echo "usage: $0 install|uninstall|status"; exit 1 ;;
esac
