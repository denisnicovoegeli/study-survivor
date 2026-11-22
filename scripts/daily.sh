#!/bin/zsh
# Täglicher Lauf: moodle-dl → convert → verarbeiten → Index → Briefing, nacheinander,
# damit ein Nachholen nach dem Ruhezustand nie parallel läuft.
# Zeitpunkt: launchd-Job aus dem Dashboard (Agent → Zeitplan) oder `study zeitplan anwenden`.
#   SKIP_MOODLE_DL=1   moodle-dl überspringen (Test von Hand)
#   DAILY_FORCE=1      auch laufen, wenn heute schon ein Lauf war
#   VERARBEITEN_LIMIT  Dateien pro Lauf (sonst aus den Einstellungen im Dashboard, Standard 3)
#   RAG_MAX            neue Chunks pro Lauf einbetten (sonst aus den Einstellungen, Standard 600)
#   OCR_MAX            gescannte PDFs pro Lauf per Texterkennung lesen (sonst aus den Einstellungen, Standard 1)
set -u
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${STUDY_DATA_DIR:-$HOME/Apps/moodle-dl}"
if [ -z "${UV:-}" ]; then  # uv suchen: PATH, Installer (~/.local/bin), Homebrew
  for kandidat in "$(command -v uv 2>/dev/null)" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [ -n "$kandidat" ] && [ -x "$kandidat" ] && { UV="$kandidat"; break; }
  done
fi
UV="${UV:-/opt/homebrew/bin/uv}"
MOODLE_DL="${MOODLE_DL:-$HOME/.local/share/moodle-dl-venv/bin/moodle-dl}"
[ -x "$MOODLE_DL" ] || MOODLE_DL=/Library/Frameworks/Python.framework/Versions/3.10/bin/moodle-dl

mkdir -p "$PROJECT/logs"
exec >> "$PROJECT/logs/daily.log" 2>&1
# Höchstens ein Lauf pro Tag (Zeitplan im Dashboard); DAILY_FORCE=1 erzwingt einen weiteren
MARKE="$PROJECT/logs/daily-letzter-lauf"
HEUTE="$(date +%F)"
if [ "${DAILY_FORCE:-0}" != "1" ] && [ "$(cat "$MARKE" 2>/dev/null)" = "$HEUTE" ]; then
  echo "=== übersprungen $(date '+%F %T'): heute schon gelaufen (DAILY_FORCE=1 erzwingt)"
  exit 0
fi
echo "$HEUTE" > "$MARKE"
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
# Werte aus data/state/einstellungen.yaml (Dashboard); Umgebungsvariablen gehen vor
einstellung() { "$UV" run study einstellungen --get "$1" 2>/dev/null || echo "$2"; }
LIMIT="${VERARBEITEN_LIMIT:-$(einstellung verarbeitung.dateien_pro_lauf 3)}"
RAG_MAX="${RAG_MAX:-$(einstellung verarbeitung.rag_max 600)}"
OCR_MAX="${OCR_MAX:-$(einstellung verarbeitung.ocr_pro_lauf 1)}"
schritt convert "$UV" run study convert --current --ocr "$OCR_MAX"
# Freigabefälle bleiben als interrupt offen (Dashboard oder `study freigabe`), der Lauf geht weiter.
"$UV" run study verarbeiten --limit "$LIMIT" --auto; rc=$?
echo "--- verarbeiten: Exit $rc (3 = Freigabe offen)"
[ $rc -eq 0 ] || [ $rc -eq 3 ] || fehler=1
schritt index "$UV" run study index
schritt rag-index "$UV" run study rag-index --max "$RAG_MAX"
schritt freigaben "$UV" run study freigabe
schritt briefing "$UV" run study briefing
echo "=== Ende $(date '+%F %T'), Fehler: $fehler"
exit $fehler
