#!/bin/zsh
# Richtet den täglichen Lauf als launchd-Job ch.fhnw.study-survivor ein, mit Uhrzeit und
# Wochentagen aus data/state/einstellungen.yaml und schaltet ihn ein (Standard täglich 08:00, im Dashboard unter
# Agent → Zeitplan änderbar). Löst den alten Job ch.fhnw.study-agent ab.
set -eu
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
cd "$PROJECT"
"$UV" run study zeitplan ein
