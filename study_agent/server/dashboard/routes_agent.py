"""Routen für die Agent-Einstellungen und das Festlegen von Dateiklassen im Dashboard."""
from typing import Any, Dict

from study_agent import einstellungen, zeitplan
from study_agent.pipeline.classify import CLASSES, set_override

# Klassen, die im Dashboard zur Auswahl stehen (Reihenfolge = Anzeige)
KLASSEN_AUSWAHL = ("folien", "semesterprogramm", "projekt", "uebung", "loesung", "literatur", "ueberspringen")


def register_routes(router: Any, get_settings_fn: Any, cache_invalidate_fn: Any) -> None:
    from fastapi import Body, HTTPException

    @router.get("/einstellungen")
    def get_einstellungen():
        settings = get_settings_fn()
        return {"einstellungen": einstellungen.laden(settings.state_dir), "standard": einstellungen.DEFAULTS}

    @router.put("/einstellungen")
    def put_einstellungen(payload: Dict[str, Any] = Body(...)):
        settings = get_settings_fn()
        vorher = einstellungen.laden(settings.state_dir)["zeitplan"]
        try:
            gespeichert = einstellungen.speichern(settings.state_dir, payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        cache_invalidate_fn("pending")
        antwort: Dict[str, Any] = {"einstellungen": gespeichert}
        z = gespeichert["zeitplan"]
        # launchd nur anfassen, wenn sich der Zeitplan geändert hat
        if z != vorher:
            try:
                antwort["zeitplan"] = zeitplan.anwenden(z)
            except (OSError, RuntimeError) as exc:
                antwort["zeitplan_fehler"] = str(exc)
        return antwort

    @router.post("/benachrichtigung/test")
    def post_benachrichtigung_test(payload: Dict[str, Any] = Body(default={})):
        """Schickt eine Probemeldung mit den übergebenen (noch nicht gespeicherten) Einstellungen."""
        from study_agent import benachrichtigung

        try:
            b = einstellungen.validieren({"benachrichtigungen": payload or {}})["benachrichtigungen"]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not b["mac"] and not b["ntfy_thema"]:
            raise HTTPException(400, "Weder Mac noch ntfy eingeschaltet")
        m = benachrichtigung.Meldung("Study Survivor", "Probemeldung: so sehen Mitteilungen des Agenten aus.")
        return benachrichtigung.senden(m, b)

    @router.get("/zeitplan")
    def get_zeitplan():
        settings = get_settings_fn()
        z = einstellungen.laden(settings.state_dir)["zeitplan"]
        return {"zeitplan": z, "status": zeitplan.status(z)}

    @router.post("/zeitplan/anwenden")
    def post_zeitplan_anwenden():
        """Richtet den Job neu ein, z. B. wenn er gelöscht wurde oder das Projekt verschoben ist."""
        settings = get_settings_fn()
        z = einstellungen.laden(settings.state_dir)["zeitplan"]
        try:
            return {"zeitplan": z, "status": zeitplan.anwenden(z)}
        except (OSError, RuntimeError) as exc:
            raise HTTPException(500, str(exc)) from exc

    @router.get("/klassen")
    def get_klassen():
        return {"klassen": list(KLASSEN_AUSWAHL)}

    @router.post("/klasse")
    def post_klasse(payload: Dict[str, Any] = Body(...)):
        rel = str(payload.get("rel") or "").strip()
        klasse = str(payload.get("klasse") or "").strip()
        if not rel or ".." in rel.split("/"):
            raise HTTPException(400, "rel fehlt oder ist ungültig")
        if klasse not in CLASSES:
            raise HTTPException(400, f"Klasse {klasse!r} unbekannt")
        settings = get_settings_fn()
        try:
            set_override(settings.klassen_path, rel, klasse)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        cache_invalidate_fn("pending")
        return {"rel": rel, "klasse": klasse}
