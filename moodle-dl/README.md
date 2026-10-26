# moodle-dl lokal installieren (Mac und Windows)

Lädt alle Moodle-Kurse von `moodle.fhnw.ch` in einen lokalen Ordner und hält ihn täglich aktuell. Grundlage ist [moodle-dl](https://github.com/C0D3D3V/Moodle-DL) 2.3.13, installiert in ein eigenes venv.

| | Mac | Windows |
|---|---|---|
| Skript | `install-mac.sh` | `install-windows.ps1` |
| Datenordner (Standard) | `~/moodle-dl` | `%USERPROFILE%\moodle-dl` |
| venv | `~/.local/share/moodle-dl-venv` | `%LOCALAPPDATA%\moodle-dl-venv` |
| Täglicher Sync | launchd-Job `ch.fhnw.moodle-dl` | Aufgabenplanung, Aufgabe `moodle-dl` |

Voraussetzung: Python 3.8 oder neuer und Google Chrome (für den SSO-Login).

- Mac: `brew install python` oder Installer von python.org
- Windows: `winget install Python.Python.3.12`, danach ein neues Terminal öffnen

## Installation

**Mac** (Terminal, im Repo-Ordner):

```bash
bash moodle-dl/install-mac.sh
```

Anderer Datenordner: `bash moodle-dl/install-mac.sh ~/Apps/moodle-dl`

**Windows** (PowerShell, im Repo-Ordner):

```powershell
powershell -ExecutionPolicy Bypass -File moodle-dl\install-windows.ps1
```

Anderer Ordner oder andere Zeit: `... -DataDir D:\Moodle -Zeit 07:30`

Das Skript installiert moodle-dl, startet die Ersteinrichtung und fragt am Ende, ob der tägliche Sync (Standard 08:00) eingerichtet werden soll. Liegt im Datenordner schon eine `config.json`, wird die Ersteinrichtung übersprungen.

## Ersteinrichtung (SSO-Login)

moodle-dl fragt nacheinander:

1. **Moodle-URL:** `https://moodle.fhnw.ch`
2. **SSO-Token:** moodle-dl zeigt eine Anleitung und einen Link. So gehts:
   - In Chrome bei `moodle.fhnw.ch` einloggen (normaler FHNW-Login).
   - Entwicklerwerkzeuge öffnen (F12 oder Cmd+Option+I), Tab **Network**.
   - Im selben Tab den angezeigten Link öffnen (`https://moodle.fhnw.ch/admin/tool/mobile/launch.php?...`). Die Seite lädt nicht, das ist richtig.
   - In der Network-Liste den fehlerhaften Eintrag suchen, der mit `moodledl://token=` beginnt. Rechtsklick, Copy, **Copy link address**.
   - Im Terminal einfügen und Enter.
3. **Kursauswahl und Inhaltstypen:** Kurse an- oder abwählen. Bei den Fragen zu Foren, Quizzen usw. reicht für den Anfang die Vorgabe.

Danach startet der erste Download. Je nach Anzahl Kurse dauert das einige Minuten und braucht mehrere GB.

Das Token steht in `config.json` im Datenordner. Diese Datei nicht teilen und nicht in Git einchecken.

## Betrieb

| | Mac | Windows |
|---|---|---|
| Sync von Hand | `~/.local/share/moodle-dl-venv/bin/moodle-dl -p ~/moodle-dl` | `& "$env:LOCALAPPDATA\moodle-dl-venv\Scripts\moodle-dl.exe" -p "$env:USERPROFILE\moodle-dl" -mplw` |
| Log | `launchd.log` im Datenordner | `MoodleDL.log` im Datenordner |
| Sync abschalten | `launchctl bootout gui/$(id -u)/ch.fhnw.moodle-dl` | `Unregister-ScheduledTask moodle-dl` |
| Einstellungen ändern | `moodle-dl -p <Ordner> -c` | gleich, plus `-mplw` |
| Token abgelaufen | `moodle-dl -p <Ordner> -nt -sso` | gleich, plus `-mplw` |

Hinweise:

- Der Sync läuft nur, wenn der Rechner an ist. Mac holt einen verpassten Lauf nach dem Aufwachen aus dem Ruhezustand nach, aber nicht, wenn der Rechner ausgeschaltet war. Windows holt ihn in beiden Fällen nach (Einstellung "StartWhenAvailable").
- Unter Windows öffnet sich beim geplanten Lauf kurz ein Konsolenfenster.
- `-mplw` unter Windows ist nötig, weil FHNW-Kursnamen lang sind und Pfade sonst die 260-Zeichen-Grenze überschreiten.
