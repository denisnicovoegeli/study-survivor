"""Mitteilungen nach dem täglichen Lauf: macOS-Mitteilung und/oder ntfy (Handy).

Was gemeldet wird, steht in den Einstellungen (benachrichtigungen.*). ntfy schickt
den Text an den eingestellten Server; ohne Thema geht nichts aus dem Rechner hinaus.
"""
import json
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Meldung:
    titel: str
    text: str
    wichtig: bool = False  # bei ntfy höhere Priorität (Frist rückt näher)


def meldung_bauen(b: dict, neue_dateien: int, fristen: list[tuple[str, datetime]], freigaben: int,
                  now: datetime, fehler: str | None = None) -> Meldung | None:
    """Fasst zusammen, was laut Einstellungen gemeldet werden soll. None, wenn nichts ansteht."""
    teile: list[str] = []
    wichtig = False
    if fehler:
        teile.append(f"⚠️ {fehler}")
    if b.get("neues_material") and neue_dateien:
        teile.append(f"{neue_dateien} neue Datei{'en' if neue_dateien != 1 else ''}")
    if b.get("fristen"):
        grenze = now + timedelta(days=b.get("frist_tage", 3))
        bald = sorted((due, name) for name, due in fristen if now <= due <= grenze)
        if bald:
            wichtig = True
            due, name = bald[0]
            tage = (due.date() - now.date()).days
            wann = "heute" if tage <= 0 else "morgen" if tage == 1 else f"in {tage} Tagen"
            mehr = f" (+{len(bald) - 1} weitere)" if len(bald) > 1 else ""
            teile.append(f"{name} {wann}{mehr}")
    if b.get("freigaben") and freigaben:
        teile.append("1 Freigabe wartet" if freigaben == 1 else f"{freigaben} Freigaben warten")
    if not teile:
        return None
    return Meldung("Study Survivor", " · ".join(teile), wichtig)


def mac(m: Meldung) -> bool:
    if not shutil.which("osascript"):
        return False  # Linux/Container: kein Mitteilungszentrum
    script = (f"display notification {json.dumps(m.text, ensure_ascii=False)}"
              f" with title {json.dumps(m.titel, ensure_ascii=False)}")
    return subprocess.run(["osascript", "-e", script], check=False).returncode == 0


def ntfy(m: Meldung, server: str, thema: str, timeout: float = 10) -> None:
    """Schickt die Meldung an <server>/<thema>. Wirft OSError/URLError bei Netzproblemen."""
    req = urllib.request.Request(
        f"{server.rstrip('/')}/{thema}", data=m.text.encode("utf-8"), method="POST",
        headers={"Title": m.titel.encode("ascii", "replace").decode(),
                 "Priority": "high" if m.wichtig else "default", "Tags": "books"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (Adresse aus den Einstellungen)
        resp.read()


def senden(m: Meldung, b: dict) -> dict:
    """Schickt die Meldung über alle eingeschalteten Wege. Liefert, was geklappt hat."""
    out: dict = {}
    if b.get("mac"):
        out["mac"] = mac(m)
    if b.get("ntfy_thema"):
        try:
            ntfy(m, b.get("ntfy_server") or "https://ntfy.sh", b["ntfy_thema"])
            out["ntfy"] = True
        except OSError as exc:
            out["ntfy"] = False
            out["ntfy_fehler"] = str(getattr(exc, "reason", exc))[:200]
    return out
