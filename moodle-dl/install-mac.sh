#!/usr/bin/env bash
# Installiert moodle-dl lokal auf macOS und richtet optional den täglichen Sync ein.
# Aufruf:  bash moodle-dl/install-mac.sh [Datenordner]     (Standard: ~/moodle-dl)
set -euo pipefail

VERSION="2.3.13"
DATA_DIR="${1:-$HOME/moodle-dl}"
VENV="$HOME/.local/share/moodle-dl-venv"
LABEL="ch.fhnw.moodle-dl"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ZEIT="${ZEIT:-08:00}"

command -v python3 >/dev/null || { echo "python3 fehlt. Installieren mit: brew install python (oder python.org)"; exit 1; }

echo "== moodle-dl $VERSION in $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q "moodle-dl==$VERSION"
"$VENV/bin/moodle-dl" --version

mkdir -p "$DATA_DIR"
if [ -f "$DATA_DIR/config.json" ]; then
  echo "== config.json vorhanden, Ersteinrichtung übersprungen"
else
  echo "== Ersteinrichtung (Moodle-URL: https://moodle.fhnw.ch, Login per SSO, siehe moodle-dl/README.md)"
  "$VENV/bin/moodle-dl" -p "$DATA_DIR" -i -sso
fi

read -r -p "Täglichen Sync um $ZEIT einrichten? [J/n] " antwort
if [[ ! "$antwort" =~ ^[nN] ]]; then
  stunde="${ZEIT%%:*}"; minute="${ZEIT##*:}"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/moodle-dl</string>
    <string>-p</string>
    <string>$DATA_DIR</string>
  </array>
  <key>WorkingDirectory</key><string>$DATA_DIR</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$((10#$stunde))</integer><key>Minute</key><integer>$((10#$minute))</integer></dict>
  <key>StandardOutPath</key><string>$DATA_DIR/launchd.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/launchd.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "== launchd-Job $LABEL aktiv (Log: $DATA_DIR/launchd.log)"
fi

echo
echo "Fertig. Sync von Hand:  $VENV/bin/moodle-dl -p \"$DATA_DIR\""
