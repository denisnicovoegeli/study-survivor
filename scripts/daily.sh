#!/bin/zsh
# Täglicher Lauf: moodle-dl → convert → verarbeiten → Index → Briefing, nacheinander,
# damit ein Nachholen nach dem Ruhezustand nie parallel läuft.
#   SKIP_MOODLE_DL=1   moodle-dl überspringen (Test von Hand)
#   VERARBEITEN_LIMIT  Dateien pro Lauf für den Graphen verarbeiten (Standard 3)
set -u
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${STUDY_DATA_DIR:-$HOME/Apps/moodle-dl}"
UV="${UV:-/opt/homebrew/bin/uv}"
MOODLE_DL="${MOODLE_DL:-$HOME/.local/share/moodle-dl-venv/bin/moodle-dl}"
[ -x "$MOODLE_DL" ] || MOODLE_DL=/Library/Frameworks/Python.framework/Versions/3.10/bin/moodle-dl
LIMIT="${VERARBEITEN_LIMIT:-3}"
mkdir -p "$PROJECT/logs"
exec >> "$PROJECT/logs/daily.log" 2>&1
echo "=== $(date '+%F %T') ==="
fehler=0
schritt() {  # schritt NAME BEFEHL...: Exit-Code protokollieren, weitermachen
  local name=$1; shift
  echo "--- $name"
  "$@"; local rc=$?
  [ $rc -eq 0 ] || { echo "$name: Exit $rc"; fehler=1; }
  return 0
}

if [ "${SKIP_MOODLE_DL:-0}" = "1" ]; then
  echo "--- moodle-dl übersprungen (SKIP_MOODLE_DL=1)"
else
  schritt moodle-dl "$MOODLE_DL" -p "$DATA"
fi
cd "$PROJECT"
schritt convert "$UV" run study convert --current
# Freigabefälle bleiben als interrupt offen (Dashboard oder `study freigabe`), der Lauf geht weiter.
"$UV" run study verarbeiten --limit "$LIMIT" --auto; rc=$?
echo "--- verarbeiten: Exit $rc (3 = Freigabe offen)"
[ $rc -eq 0 ] || [ $rc -eq 3 ] || fehler=1
schritt index "$UV" run study index
schritt rag-index "$UV" run study rag-index --max "${RAG_MAX:-600}"
schritt freigaben "$UV" run study freigabe
schritt briefing "$UV" run study briefing
echo "=== Ende $(date '+%F %T'), Fehler: $fehler"
exit $fehler
