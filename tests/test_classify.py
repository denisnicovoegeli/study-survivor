import pytest

from study_agent.pipeline.classify import ROUTES, classify, load_overrides, set_override
from study_agent.pipeline.pdf_pages import PageInfo


def pages(n, landscape=True, chars=300):
    return [PageInfo(i, "T", "x" * chars, landscape, 0.0, 0, False) for i in range(1, n + 1)]


@pytest.mark.parametrize("name, module, expected", [
    ("GenAI  Agents Semesterprogramm_neu.pdf", "Semesterprogramm", "semesterprogramm"),
    ("Semsterprogramm 2026 2027.pdf", "", "semesterprogramm"),  # Tippfehler im echten Dateinamen
    ("HS26_DeepLearning_BAI.pdf", "Lernziele & Programm", "semesterprogramm"),
    ("Wegleitung Praxisprojekt WI_BAI 2026_fin.pdf", "Wegleitung", "projekt"),
    ("HS26_DL_Projektthemen.pdf", "Vorschläge Projektthemen", "projekt"),
    ("Übung Woche 1 - Lösung.pdf", "Lösung Übung 1", "loesung"),
    ("U1_Vorwärtsdurchgang_FCNN.pdf", "Übung 1", "uebung"),
    ("978-3-658-43789-3.pdf", "Literatur Marketing", "literatur"),
    ("W03_training.pdf", "Folien Woche 3", "folien"),
    ("2026_SW4_Agentensystem.pdf", "2026_SW4_Agentensystem", "folien"),
    ("Cybersecurity - Session 2.pdf", "Session 2", "folien"),
])
def test_name_rules(name, module, expected):
    assert classify(name, module, ".pdf") == expected


def test_notebook_is_not_literature():
    assert classify("Jupyter Notebook SW4.pdf", "", ".pdf", pages(30)) == "folien"


def test_format_fallback():
    assert classify("13 Post Training III.pdf", "13 Post Training III", ".pdf", pages(55)) == "folien"
    assert classify("CMA-Timeline.pdf", "Case", ".pdf", pages(17, landscape=False, chars=1100)) == "unklar"
    assert classify("CMA-Summary.pdf", "Case", ".pdf", pages(5, chars=5000)) == "unklar"
    assert classify("Handout.pdf", "Handout", ".pdf", pages(328, landscape=False)) == "literatur"
    assert classify("Start-up Finanzierung.pptx", "Unterricht", ".pptx") == "folien"
    assert classify("Notizen.docx", "Notizen", ".docx") == "unklar"


def test_routes():
    assert ROUTES["folien"] == "voll"
    assert ROUTES["semesterprogramm"] == ROUTES["projekt"] == "info"
    assert ROUTES["unklar"] == "fragen"
    assert "uebung" not in ROUTES and "literatur" not in ROUTES and "ueberspringen" not in ROUTES


def test_overrides_roundtrip_with_special_chars(tmp_path):
    path = tmp_path / "klassen.yaml"
    assert load_overrides(path) == ({}, [])
    rel = "3-26HS.W-B-BAI-000405.EN⧸VZTZ Praxisprojekt/Semesterplan/Wegleitung.pdf"
    set_override(path, rel, "projekt")
    set_override(path, "Kurs/a.pdf", "ueberspringen")
    assert load_overrides(path) == ({rel: "projekt", "Kurs/a.pdf": "ueberspringen"}, [])
    assert "⧸" in path.read_text()


def test_invalid_overrides(tmp_path):
    path = tmp_path / "klassen.yaml"
    with pytest.raises(ValueError, match="unbekannt"):
        set_override(path, "a.pdf", "party")
    path.write_text("a.pdf: party\nb.pdf: folien\n")
    good, errors = load_overrides(path)
    assert good == {"b.pdf": "folien"} and len(errors) == 1
    with pytest.raises(ValueError, match="zuerst korrigieren"):
        set_override(path, "c.pdf", "folien")
    path.write_text("kurs: [kaputt\n")
    assert load_overrides(path)[0] == {} and len(load_overrides(path)[1]) == 1
