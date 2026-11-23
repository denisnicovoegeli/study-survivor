import pytest

from study_agent import einstellungen as e


def test_laden_ohne_datei_liefert_standard(tmp_path):
    assert e.laden(tmp_path) == e.DEFAULTS


def test_speichern_ergaenzt_und_ordnet(tmp_path):
    out = e.speichern(tmp_path, {"zeitplan": {"tage": ["fr", "mo", "mo"]}, "unbekannt": 1})
    assert out["zeitplan"]["tage"] == ["mo", "fr"]
    assert out["zeitplan"]["zeit"] == "08:00"
    assert "unbekannt" not in out
    assert e.laden(tmp_path) == out


@pytest.mark.parametrize("daten", [
    {"zeitplan": {"zeit": "25:00"}},
    {"zeitplan": {"tage": ["montag"]}},
    {"zeitplan": {"aktiv": "ja"}},
    {"verarbeitung": {"dateien_pro_lauf": -1}},
    {"verarbeitung": {"rag_max": True}},
    {"filter": {"kurse_ignorieren": "Kurs"}},
])
def test_ungueltige_werte(tmp_path, daten):
    with pytest.raises(ValueError):
        e.speichern(tmp_path, daten)


def test_kaputte_datei_liefert_standard(tmp_path):
    e.pfad(tmp_path).write_text("zeitplan: [")
    assert e.laden(tmp_path) == e.DEFAULTS


def test_wert_mit_punktpfad():
    assert e.wert(e.DEFAULTS, "verarbeitung.dateien_pro_lauf") == 3
    with pytest.raises(KeyError):
        e.wert(e.DEFAULTS, "verarbeitung.gibtsnicht")


def test_ueberspringen_grund(tmp_path):
    filt = e.DEFAULTS["filter"] | {"kurse_ignorieren": ["Alt"]}
    leer = tmp_path / "leer.md"
    leer.write_text("**\n**")
    voll = tmp_path / "voll.md"
    voll.write_text("x" * 500)
    assert e.ueberspringen_grund(filt, "Alt", "Folien.pdf", voll, "voll") == "Kurs ignoriert"
    assert e.ueberspringen_grund(filt, "K", "Forum intro.md", voll, "fragen") == "Moodle-Hilfsseite"
    assert e.ueberspringen_grund(filt, "K", "Gastvortrag.md", leer, "fragen") == "leere Seite"
    assert e.ueberspringen_grund(filt, "K", "Gastvortrag.md", voll, "fragen") is None
    # echtes Material (nicht „fragen“) wird nie automatisch ausgelassen
    assert e.ueberspringen_grund(filt, "K", "leer.md", leer, "voll") is None
