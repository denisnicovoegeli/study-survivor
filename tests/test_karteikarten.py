"""Karteikarten aus Folien-Notizen erstellen (Fake-Modell, ohne LLM)."""
import json

from study_agent.config import Settings
from study_agent.pipeline import karteikarten as kk
from study_agent.server.dashboard.routes_karten import get_course_cards

KURS = "GenKI"


def _settings(tmp_path):
    s = Settings(data_dir=tmp_path / "m", project_dir=tmp_path / "p")
    k = s.knowledge_dir / KURS / "Folien"
    k.mkdir(parents=True)
    (k / "1 Generative AI.pdf.folien.md").write_text("<!-- kopf -->\n# 1 Generative AI\n\n## Folie 3 · LLM\nEin LLM ist …\n")
    (s.knowledge_dir / ".manifest.json").write_text(json.dumps({f"{KURS}/Folien/1 Generative AI.pdf": {"sig": [1, 1]}}))
    return s


def test_erstellen_schreibt_begriffe_und_ueberspringt_doppelte(tmp_path):
    s = _settings(tmp_path)
    prompts = []

    def modell(prompt):
        prompts.append(prompt)
        return kk.Karten(karten=[
            kk.Karte(begriff="LLM", definition="Grosses Sprachmodell | mit Pipe", folien=[3]),
            kk.Karte(begriff="llm", definition="doppelt", folien=[3]),
            kk.Karte(begriff="Token", definition="Kleinste Texteinheit.\nZweite Zeile", folien=[]),
        ])

    rel = f"{KURS}/Folien/1 Generative AI.pdf"
    r = kk.erstellen(s, KURS, [rel], anzahl=10, modell=modell)
    assert r == {"neu": 2, "fehler": []}
    assert "## Folie 3 · LLM" in prompts[0] and "<!-- kopf -->" not in prompts[0]

    karten = get_course_cards(KURS, s.lernen_dir, s.state_dir)
    llm = next(c for c in karten if c["begriff"] == "LLM")
    assert llm["sources"][0] == {"raw": "1 Generative AI.pdf, Folie 3", "filename": "1 Generative AI.pdf", "pages": [3]}
    assert "Pipe" in llm["definition"] and len(karten) == 2

    # zweiter Lauf: bekannte Begriffe gehen ans Modell und werden nicht doppelt geschrieben
    r2 = kk.erstellen(s, KURS, [rel], modell=modell)
    assert r2["neu"] == 0 and "LLM" in prompts[1].replace("llm", "LLM")
    assert kk.dokumente.__name__  # Import geprüft


def test_erstellen_fehler_und_fremde_module(tmp_path):
    s = _settings(tmp_path)

    def kaputt(prompt):
        raise TimeoutError("Proxy")

    r = kk.erstellen(s, KURS, [f"{KURS}/Folien/1 Generative AI.pdf", "Anderes/x.pdf", f"{KURS}/fehlt.pdf"], modell=kaputt)
    assert r["neu"] == 0 and len(r["fehler"]) == 3
    assert "TimeoutError" in r["fehler"][0] and "nicht in diesem Modul" in r["fehler"][1]
