#!/bin/zsh
# Richtet den täglichen Lauf (08:00) als launchd-Job ch.fhnw.study-survivor ein und
# löst den alten Job ch.fhnw.study-agent ab, damit nicht zwei Crons parallel laden.
set -eu
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
NEU="$AGENTS/ch.fhnw.study-survivor.plist"
ALT="$AGENTS/ch.fhnw.study-agent.plist"
if [ -f "$ALT" ]; then
  launchctl bootout "gui/$(id -u)/ch.fhnw.study-agent" 2>/dev/null || true
  mv "$ALT" "$ALT.disabled"
  echo "alter Job ch.fhnw.study-agent entladen (plist -> .disabled)"
fi
sed "s#__PROJECT__#$PROJECT#g" "$PROJECT/launchd/ch.fhnw.study-survivor.plist.template" > "$NEU"
launchctl bootout "gui/$(id -u)/ch.fhnw.study-survivor" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$NEU"
echo "launchd-Job ch.fhnw.study-survivor aktiv: $PROJECT/scripts/daily.sh täglich 08:00"
