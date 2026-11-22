"""Modulfarben: eindeutige Standardfarben, stabil, eigene Farben."""
import pytest

from study_agent.pipeline import modulfarben as mf


def test_standardfarben_eindeutig_und_stabil(tmp_path):
    f = mf.farben(tmp_path, ["B", "A", "C"])
    assert len(set(f.values())) == 3 and f["A"] == mf.PALETTE[0]
    # neues Modul, das alphabetisch davor liegt, verschiebt die anderen nicht
    f2 = mf.farben(tmp_path, ["0 Neu", "A", "B", "C"])
    assert {k: f2[k] for k in "ABC"} == f and f2["0 Neu"] not in f.values()


def test_eigene_farbe_und_zuruecksetzen(tmp_path):
    module = ["A", "B"]
    mf.farben(tmp_path, module)
    f = mf.setzen(tmp_path, "A", "#123ABC", module)
    assert f["A"] == "#123abc"
    f = mf.setzen(tmp_path, "A", None, module)
    assert f["A"] != f["B"] and f["A"] in mf.PALETTE
    with pytest.raises(ValueError):
        mf.setzen(tmp_path, "A", "rot", module)
    with pytest.raises(ValueError):
        mf.setzen(tmp_path, "X", "#000000", module)


def test_palette_aufgebraucht(tmp_path):
    module = [f"M{i:02d}" for i in range(14)]
    assert len(set(mf.farben(tmp_path, module).values())) == 14
