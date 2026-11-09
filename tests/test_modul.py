from study_agent.pipeline.modul import kombiniere_leistungsnachweis, load_modul, merge_modul, normalisiere_daten


def test_leistungsnachweis_aus_mehreren_quellen_ergibt_beides(tmp_path):
    merge_modul(tmp_path, "W01.pdf", {"leistungsnachweis": "pruefung"})
    merge_modul(tmp_path, "Projekt.pdf", {"leistungsnachweis": "projekt"})
    assert load_modul(tmp_path).leistungsnachweis == "beides"
    assert kombiniere_leistungsnachweis("beides", "projekt") == "beides"
    assert kombiniere_leistungsnachweis(None, "projekt") == "projekt"


def test_gewichtung_mit_pruefung_und_projekt_ergibt_beides(tmp_path):
    merge_modul(tmp_path, "W01.pdf", {"leistungsnachweis": "projekt", "gewichtung": "70 % schriftliche Prüfung, 30 % Projekt"})
    assert load_modul(tmp_path).leistungsnachweis == "beides"


def test_daten_einheitlich_und_ohne_doppelte():
    daten = [
        "2026-12-18 Projektabgabe (Moodle-Upload)",
        "18.12.2026: Projektabgabe (Moodle-Upload)",
        "2026-12-18",
        "16.12.2026 Besprechung Probeprüfung und Q&A",
        "2026-12-16: Besprechung Probeprüfung und Q&A (Lektion 14)",
        "2026-10-21 Peer-Feedback Projektmethoden",
        "Datensatz melden bis Ende der 4. Semesterwoche",
    ]
    assert normalisiere_daten(daten) == [
        "2026-10-21 Peer-Feedback Projektmethoden",
        "2026-12-16 Besprechung Probeprüfung und Q&A (Lektion 14)",
        "2026-12-18 Projektabgabe (Moodle-Upload)",
        "Datensatz melden bis Ende der 4. Semesterwoche",
    ]


def test_verschiedene_termine_am_selben_tag_bleiben():
    assert len(normalisiere_daten(["2026-12-18 Projektabgabe", "2026-12-18 Prüfung"])) == 2

