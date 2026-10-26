# Installiert moodle-dl lokal auf Windows und richtet optional den täglichen Sync ein.
# Aufruf:  powershell -ExecutionPolicy Bypass -File moodle-dl\install-windows.ps1 [-DataDir C:\Pfad] [-Zeit 08:00]
param(
    [string]$DataDir = "$env:USERPROFILE\moodle-dl",
    [string]$Zeit = "08:00"
)
$ErrorActionPreference = "Stop"

$Version = "2.3.13"
$Venv = "$env:LOCALAPPDATA\moodle-dl-venv"
$MoodleDl = "$Venv\Scripts\moodle-dl.exe"
$TaskName = "moodle-dl"

# Python finden: zuerst der py-Launcher, dann python
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $PyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python"; $PyArgs = @() }
else {
    Write-Host "Python fehlt. Installieren mit: winget install Python.Python.3.12  (danach neues Terminal oeffnen)"
    exit 1
}

Write-Host "== moodle-dl $Version in $Venv"
& $Python @PyArgs -m venv $Venv
& "$Venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -q "moodle-dl==$Version"
& $MoodleDl --version

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
# -mplw: absolute Pfade, umgeht die 260-Zeichen-Grenze bei langen Kursnamen
if (Test-Path "$DataDir\config.json") {
    Write-Host "== config.json vorhanden, Ersteinrichtung uebersprungen"
} else {
    Write-Host "== Ersteinrichtung (Moodle-URL: https://moodle.fhnw.ch, Login per SSO, siehe moodle-dl\README.md)"
    & $MoodleDl -p $DataDir -i -sso -mplw
}

$antwort = Read-Host "Taeglichen Sync um $Zeit einrichten? [J/n]"
if ($antwort -notmatch '^[nN]') {
    $action = New-ScheduledTaskAction -Execute $MoodleDl -Argument "-p `"$DataDir`" -mplw -ltf" -WorkingDirectory $DataDir
    $trigger = New-ScheduledTaskTrigger -Daily -At $Zeit
    # StartWhenAvailable: verpassten Lauf nachholen, wenn der PC um diese Zeit aus war
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "== Aufgabe '$TaskName' in der Aufgabenplanung angelegt (Log: $DataDir\MoodleDL.log)"
}

Write-Host ""
Write-Host "Fertig. Sync von Hand:  & `"$MoodleDl`" -p `"$DataDir`" -mplw"
