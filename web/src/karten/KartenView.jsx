// KartenView.jsx: Leitner-Karteikartenansicht fuer Begriffe mit 3 Faechern und Folien-Links
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Loading } from "../ui/Loading.jsx";
import { useAsync } from "../ui/hooks.js";
import "./karten.css";

const { useState, useEffect, useMemo, useCallback } = React;

export function KartenView() {
  const {
    course,
    setCourse,
    courses,
    openFolie,
    openFile,
    api,
    toast,
  } = useStudio();

  // Filter-Zustaende
  const [activeBox, setActiveBox] = useState(0); // 0 = Alle, 1-3 = Fach 1-3
  const [weekFilter, setWeekFilter] = useState("all");
  const [fileFilter, setFileFilter] = useState("all");

  // Karten-Navigation
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [cardsList, setCardsList] = useState([]);

  // Karten vom Backend abrufen
  const {
    data: kartenRes,
    loading,
    reload,
  } = useAsync(async () => {
    if (!course) return null;
    return await api("karten?course=" + encodeURIComponent(course));
  }, [course]);

  useEffect(() => {
    if (kartenRes?.cards) {
      setCardsList(kartenRes.cards);
    }
  }, [kartenRes]);

  // Extrahiere alle verfuegbaren Wochen und Quelldateien fuer Filter
  const availableWeeks = useMemo(() => {
    const s = new Set();
    for (const c of cardsList) {
      for (const w of c.weeks || []) s.add(w);
    }
    return Array.from(s).sort((a, b) => a - b);
  }, [cardsList]);

  const availableFiles = useMemo(() => {
    const s = new Set();
    for (const c of cardsList) {
      for (const src of c.sources || []) {
        if (src.filename) s.add(src.filename);
      }
    }
    return Array.from(s).sort();
  }, [cardsList]);

  // Fächer-Zähler
  const boxCounts = useMemo(() => {
    const counts = { all: cardsList.length, b1: 0, b2: 0, b3: 0 };
    for (const c of cardsList) {
      const b = c.box || 1;
      if (b === 1) counts.b1++;
      else if (b === 2) counts.b2++;
      else if (b === 3) counts.b3++;
    }
    return counts;
  }, [cardsList]);

  // Gefilterte Karten
  const filteredCards = useMemo(() => {
    return cardsList.filter((c) => {
      // Fach-Filter
      if (activeBox > 0 && (c.box || 1) !== activeBox) return false;
      // Wochen-Filter
      if (weekFilter !== "all" && !(c.weeks || []).includes(Number(weekFilter))) return false;
      // Datei-Filter
      if (fileFilter !== "all") {
        const matches = (c.sources || []).some((s) => s.filename === fileFilter);
        if (!matches) return false;
      }
      return true;
    });
  }, [cardsList, activeBox, weekFilter, fileFilter]);

  // Index korrigieren bei Filterwechsel
  useEffect(() => {
    setCurrentIndex(0);
    setFlipped(false);
  }, [activeBox, weekFilter, fileFilter, course]);

  const currentCard = filteredCards[currentIndex] || null;

  // Antwort nach Leitner verarbeiten (Gewusst / Nicht gewusst)
  const handleAnswer = useCallback(
    async (known) => {
      if (!currentCard || !course) return;

      const cardId = currentCard.id;
      const targetBox = known ? Math.min(3, (currentCard.box || 1) + 1) : 1;

      // Optimistisches Update im UI
      setCardsList((prev) =>
        prev.map((c) =>
          c.id === cardId
            ? {
                ...c,
                box: targetBox,
                streak: known ? (c.streak || 0) + 1 : 0,
                reviewed_at: new Date().toISOString(),
              }
            : c
        )
      );

      // Backend-Speicherung (state/karten.json)
      try {
        await api("karten/review", {
          method: "POST",
          body: JSON.stringify({
            course,
            card_id: cardId,
            known,
          }),
        });
      } catch (err) {
        toast("Konnte Lernstand nicht speichern: " + (err.message || ""));
      }

      // Zur naechsten Karte wechseln
      setFlipped(false);
      if (currentIndex < filteredCards.length - 1) {
        setCurrentIndex((i) => i + 1);
      } else {
        // Durchlauf beendet
        toast(known ? "Runde abgeschlossen!" : "Runde abgeschlossen, weiter so!");
        setCurrentIndex(0);
      }
    },
    [currentCard, course, currentIndex, filteredCards.length, api, toast]
  );

  // Klick auf Folien-Link oeffnet das PDF auf der entsprechenden Seite
  const handleFolieClick = useCallback(
    (e, src, page) => {
      e.stopPropagation();
      if (typeof openFolie === "function") {
        openFolie(page);
      }
      // Falls Datei und Kurs bekannt, oeffne Moodle-PDF
      if (src?.filename && course && typeof openFile === "function") {
        // Suche passenden Pfad
        openFile("moodle", `${course}/${src.filename}`, { page });
      }
    },
    [openFolie, openFile, course]
  );

  // Tastatursteuerung
  useEffect(() => {
    function onKeyDown(e) {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;

      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        handleAnswer(false);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        handleAnswer(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleAnswer]);

  return (
    <div className="stu-karten">
      {/* Kopfbereich */}
      <header className="stu-karten-h">
        <div className="stu-karten-title-row">
          <div>
            <h1>Karteikarten</h1>
          </div>

          {/* Kursauswahl */}
          <select
            className="stu-karten-filter-select"
            value={course || ""}
            onChange={(e) => setCourse(e.target.value)}
            aria-label="Kurs auswählen"
          >
            {courses &&
              courses.map((k) => {
                const name = typeof k === "string" ? k : k?.name;
                return (
                  <option key={name} value={name}>
                    {name}
                  </option>
                );
              })}
          </select>
        </div>

        {/* Leitner-Fächer und Filter */}
        <div className="stu-karten-controls">
          <div className="stu-leitner-boxes" role="tablist">
            <button
              type="button"
              className={`stu-leitner-box-btn ${activeBox === 0 ? "is-on" : ""}`}
              onClick={() => setActiveBox(0)}
            >
              <span>Alle</span>
              <span className="stu-leitner-count">{boxCounts.all}</span>
            </button>
            <button
              type="button"
              className={`stu-leitner-box-btn ${activeBox === 1 ? "is-on" : ""}`}
              onClick={() => setActiveBox(1)}
              title="Fach 1: Neu oder falsch beantwortet"
            >
              <span>Fach 1</span>
              <span className="stu-leitner-count">{boxCounts.b1}</span>
            </button>
            <button
              type="button"
              className={`stu-leitner-box-btn ${activeBox === 2 ? "is-on" : ""}`}
              onClick={() => setActiveBox(2)}
              title="Fach 2: Einmal gewusst"
            >
              <span>Fach 2</span>
              <span className="stu-leitner-count">{boxCounts.b2}</span>
            </button>
            <button
              type="button"
              className={`stu-leitner-box-btn ${activeBox === 3 ? "is-on" : ""}`}
              onClick={() => setActiveBox(3)}
              title="Fach 3: Gemeistert"
            >
              <span>Fach 3</span>
              <span className="stu-leitner-count">{boxCounts.b3}</span>
            </button>
          </div>

          {/* Filter nach Woche */}
          {availableWeeks.length > 0 && (
            <select
              className="stu-karten-filter-select"
              value={weekFilter}
              onChange={(e) => setWeekFilter(e.target.value)}
              aria-label="Woche filtern"
            >
              <option value="all">Alle Wochen</option>
              {availableWeeks.map((w) => (
                <option key={w} value={w}>
                  Woche {String(w).padStart(2, "0")}
                </option>
              ))}
            </select>
          )}

          {/* Filter nach Quelldatei */}
          {availableFiles.length > 0 && (
            <select
              className="stu-karten-filter-select"
              value={fileFilter}
              onChange={(e) => setFileFilter(e.target.value)}
              aria-label="Quelldatei filtern"
            >
              <option value="all">Alle Quellen</option>
              {availableFiles.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          )}
        </div>
      </header>

      {/* Hauptbereich */}
      <main className="stu-karten-body">
        {loading ? (
          <Loading text="Begriffe werden geladen …" />
        ) : filteredCards.length === 0 ? (
          <div className="stu-karten-empty">
            <h3>Keine Karteikarten vorhanden</h3>
            <p>
              In diesem Fach oder Filter liegen keine Begriffe. Wähle ein anderes Fach
              oder setze die Filter zurück.
            </p>
          </div>
        ) : currentCard ? (
          <div className="stu-card-wrap">
            {/* Karte als echte 3D-Karteikarte */}
            <div
              className={`stu-card ${flipped ? "is-flipped" : ""}`}
              onClick={() => setFlipped(!flipped)}
              role="button"
              tabIndex={0}
              aria-label="Karteikarte umdrehen"
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  setFlipped(!flipped);
                }
              }}
            >
              <div className="stu-card-inner">
                {/* Vorderseite mit zentriertem Begriff */}
                <div className="stu-card-face stu-card-front">
                  <div className="stu-card-side-tag">
                    <span>Vorderseite · Begriff</span>
                    <span className="stu-card-box-indicator">Fach {currentCard.box || 1}</span>
                  </div>

                  <div className="stu-card-center">
                    <h2 className="stu-card-term">{currentCard.begriff}</h2>
                  </div>

                  <div className="stu-card-hint">
                    <span>Klicken oder Leertaste zum Umdrehen</span>
                  </div>
                </div>

                {/* Rückseite mit Definition und Quellen/Folien */}
                <div className="stu-card-face stu-card-back">
                  <div className="stu-card-side-tag">
                    <span>Rückseite · Definition</span>
                    <span className="stu-card-box-indicator">Fach {currentCard.box || 1}</span>
                  </div>

                  <div className="stu-card-back-body">
                    <p className="stu-card-definition">{currentCard.definition}</p>

                    {/* Quellen mit Folien-Links ins PDF */}
                    {currentCard.sources && currentCard.sources.length > 0 && (
                      <div className="stu-card-sources">
                        <span className="stu-card-sources-title">Quellen und Folien</span>
                        <div className="stu-card-source-links">
                          {currentCard.sources.map((src, i) => {
                            if (!src.pages || src.pages.length === 0) {
                              return (
                                <span key={i} className="stu-card-folie-link">
                                  {src.filename || src.raw}
                                </span>
                              );
                            }
                            return src.pages.map((p) => (
                              <button
                                key={`${i}-${p}`}
                                type="button"
                                className="stu-card-folie-link"
                                onClick={(e) => handleFolieClick(e, src, p)}
                                title={`${src.filename || "PDF"} auf Folie ${p} öffnen`}
                              >
                                <span>{src.filename ? `${src.filename.replace(/\.pdf$/i, "")} · Folie ${p}` : `Folie ${p}`}</span>
                              </button>
                            ));
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="stu-card-hint">
                    <span>Klicken oder Leertaste zum Umdrehen</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Antwort-Knöpfe */}
            <div className="stu-card-actions">
              <button
                type="button"
                className="stu-btn-answer is-no"
                onClick={() => handleAnswer(false)}
                title="Nicht gewusst (← Taste): Zurück zu Fach 1"
              >
                <Icon n="x" />
                <span>Nicht gewusst</span>
              </button>

              <button
                type="button"
                className="stu-btn-answer is-yes"
                onClick={() => handleAnswer(true)}
                title="Gewusst (→ Taste): Aufstieg in nächstes Fach"
              >
                <Icon n="check" />
                <span>Gewusst</span>
              </button>
            </div>

            {/* Navigation und Zähler */}
            <div className="stu-card-nav">
              <button
                type="button"
                disabled={currentIndex === 0}
                onClick={() => {
                  setCurrentIndex((i) => Math.max(0, i - 1));
                  setFlipped(false);
                }}
              >
                Vorherige
              </button>

              <span>
                Karte {currentIndex + 1} von {filteredCards.length}
              </span>

              <button
                type="button"
                disabled={currentIndex >= filteredCards.length - 1}
                onClick={() => {
                  setCurrentIndex((i) => Math.min(filteredCards.length - 1, i + 1));
                  setFlipped(false);
                }}
              >
                Nächste
              </button>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default KartenView;
