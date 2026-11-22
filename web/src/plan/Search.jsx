// Search.jsx: Suche nach Fragen im Kursmaterial und Dateinamen-Suche ueber den Dateibaum
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Loading } from "../ui/Loading.jsx";
import {
  searchTree,
  resolveFileInTree,
  courseShort,
} from "./utils.js";
import { renderMarkdown } from "../lib/markdown.js";
import "./plan.css";

const { useState, useEffect, useRef, useMemo, useCallback } = React;

export function Search() {
  const {
    api,
    toast,
    openFile,
    sendToChat,
    tree,
    courses,
    course: defaultCourse,
    modulFarbe,
  } = useStudio();

  // Eingabefeld fokussiert beim Oeffnen
  const inputRef = useRef(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const [query, setQuery] = useState("");
  const [selectedCourse, setSelectedCourse] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const [hits, setHits] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Dateinamen-Suche ueber den lokalen Dateibaum (tree)
  const treeHits = useMemo(() => {
    const q = (submittedQuery || query).trim();
    if (q.length < 2 || !tree?.roots) return [];
    return searchTree(tree.roots, q, 25);
  }, [tree, submittedQuery, query]);

  // Backend-Suche ueber /fragen
  const executeSearch = useCallback(
    async (qText, cText) => {
      const q = (qText || "").trim();
      if (!q) {
        setSubmittedQuery("");
        setHits([]);
        return;
      }

      setSubmittedQuery(q);
      setLoading(true);
      setError(null);

      try {
        let endpoint = `fragen?q=${encodeURIComponent(q)}&limit=25`;
        if (cText && cText.trim()) {
          endpoint += `&course=${encodeURIComponent(cText.trim())}`;
        }
        const res = await api(endpoint);
        setHits(res?.treffer || []);
      } catch (err) {
        setError(err?.message || "Fehler bei der Suche");
        setHits([]);
      } finally {
        setLoading(false);
      }
    },
    [api]
  );

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    executeSearch(query, selectedCourse);
  };

  const handleClear = () => {
    setQuery("");
    setSubmittedQuery("");
    setHits([]);
    setError(null);
    inputRef.current?.focus();
  };

  // Datei aus einem Inhalts-Treffer oeffnen
  const handleOpenHitFile = (hit) => {
    // 1. Wenn Treffer schon root und path enthaelt
    if (hit.root && hit.path) {
      openFile(hit.root, hit.path, { page: hit.folie });
      toast(`Datei ${hit.path.split("/").pop()} geöffnet.`);
      return;
    }

    // 2. Suche im Dateibaum nach datei oder rel
    const target = hit.datei || hit.path || hit.rel;
    const resolved = resolveFileInTree(tree, target);

    if (resolved) {
      openFile(resolved.root, resolved.path, { page: hit.folie });
      toast(`Datei ${resolved.name} geöffnet.`);
      return;
    }

    // 3. Wenn Moodle-Link vorliegt, diesen oeffnen
    if (hit.moodle) {
      window.open(hit.moodle, "_blank", "noopener,noreferrer");
      return;
    }

    toast(`Kein lokaler Pfad für «${hit.datei}» im Dateibaum gefunden.`);
  };

  return (
    <div className="stu-board">
      <header className="stu-viewh">
        <h2>Suche & Fragen</h2>
        <span className="stu-viewh-desc">
          Kursmaterial durchsuchen, Fragen stellen und Dateien im Workspace finden
        </span>

        <div className="stu-grow" />

        {submittedQuery && (
          <button
            type="button"
            className="stu-tbtn"
            onClick={handleClear}
            title="Suche zurücksetzen"
          >
            Suche leeren
          </button>
        )}
      </header>

      <div className="stu-search-view">
        {/* Suchleiste */}
        <form onSubmit={handleSubmit} className="stu-search-bar">
          <Icon n="search" className="stu-muted" />

          <input
            ref={inputRef}
            type="text"
            className="stu-search-input"
            placeholder="Frage ans Material stellen oder Dateinamen suchen (z. B. Max-Pooling, W02 …)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          {query && (
            <button
              type="button"
              className="stu-icbtn"
              onClick={handleClear}
              title="Eingabe leeren"
            >
              <Icon n="x" />
            </button>
          )}

          <select
            className="stu-search-select"
            value={selectedCourse}
            onChange={(e) => setSelectedCourse(e.target.value)}
          >
            <option value="">Alle Kurse</option>
            {courses.map((k) => {
              const name = k.name || k;
              return (
                <option key={name} value={name}>
                  {name}
                </option>
              );
            })}
          </select>

          <button
            type="submit"
            className="stu-tbtn is-pri"
            disabled={!query.trim() || loading}
          >
            {loading ? "Sucht …" : "Suchen"}
          </button>
        </form>

        {/* Fehlerbox */}
        {error && (
          <div className="stu-error-box">
            <span>Fehler bei der Suche: {error}</span>
            <button
              type="button"
              className="stu-tbtn is-pri"
              onClick={() => executeSearch(query, selectedCourse)}
            >
              Erneut versuchen
            </button>
          </div>
        )}

        {/* Ladezustand */}
        {loading && (
          <div style={{ padding: "30px", display: "grid", placeItems: "center" }}>
            <Loading text="Kursmaterial wird durchsucht …" />
          </div>
        )}

        {/* 1. Dateinamen-Treffer aus dem Dateibaum (tree) */}
        {treeHits.length > 0 && (
          <section className="stu-panel">
            <div className="stu-panel-head">
              <h3>Dateien im Dateibaum ({treeHits.length})</h3>
              <span className="stu-muted" style={{ fontSize: "12px" }}>
                Direkt per Klick im Workspace öffnen
              </span>
            </div>

            <ul className="stu-list">
              {treeHits.map((f, idx) => (
                <li
                  key={f.root + ":" + f.path + idx}
                  className="stu-row stu-row--click"
                  onClick={() => {
                    openFile(f.root, f.path);
                    toast(`Datei ${f.name} geöffnet.`);
                  }}
                  title={`Pfad: ${f.root}/${f.path}`}
                >
                  <Badge name={f.name} />

                  <div className="stu-row-grow">
                    <strong>{f.name}</strong>
                    <span className="stu-row-sub">
                      {f.root} / {f.path}
                    </span>
                  </div>

                  <span
                    className="stu-bdg"
                    style={{
                      background: f.root === "lernen" ? "rgba(75, 91, 216, 0.12)" : "var(--raise)",
                      color: f.root === "lernen" ? "var(--acc)" : "var(--muted)",
                    }}
                  >
                    {f.root}
                  </span>

                  <span className="stu-tbtn" style={{ fontSize: "11px", padding: "2px 7px" }}>
                    Öffnen
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 2. Treffer aus /fragen (Inhaltliche Suche) */}
        {submittedQuery && !loading && (
          <section style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span className="stu-label" style={{ margin: 0 }}>
                Inhaltliche Treffer zu «{submittedQuery}» ({hits.length})
              </span>

              {hits.length > 0 && (
                <button
                  type="button"
                  className="stu-tbtn"
                  onClick={() => {
                    sendToChat({
                      text: `Erkläre mir bitte ausführlich folgende Frage aus dem Studium:\n\n${submittedQuery}`,
                    });
                    toast("Frage an Agent übergeben.");
                  }}
                  title="Diese Frage direkt mit Agent besprechen"
                >
                  <Icon n="chat" />
                  <span>Agent dazu fragen</span>
                </button>
              )}
            </div>

            {hits.length === 0 ? (
              <div className="stu-empty-box">
                <Icon n="search" />
                <strong style={{ fontSize: "14px" }}>Keine inhaltlichen Treffer</strong>
                <span>
                  Keine Textpassagen für «{submittedQuery}» gefunden. Probiere andere Stichworte oder frage direkt Agent.
                </span>
                <button
                  type="button"
                  className="stu-tbtn is-pri"
                  style={{ marginTop: "8px" }}
                  onClick={() => {
                    sendToChat({ text: submittedQuery });
                    toast("Anfrage an Agent gesendet.");
                  }}
                >
                  <Icon n="send" />
                  <span>Agent direkt fragen</span>
                </button>
              </div>
            ) : (
              hits.map((h, idx) => {
                const art = h.quelle === "folien" ? `Folie ${h.folie || ""}` : `Seite ${h.folie || ""}`;
                const resolved = resolveFileInTree(tree, h.datei || h.path || h.rel);
                const canOpen = !!resolved || !!h.path;

                return (
                  <article key={String(h.datei || "") + String(h.folie || "") + idx} className="stu-hit-card">
                    <div className="stu-hit-head">
                      {h.kurs && (
                        <span
                          className="stu-bdg"
                          style={{
                            background: `color-mix(in srgb, ${modulFarbe(h.kurs)} 16%, transparent)`,
                            color: "var(--fg)",
                            fontWeight: 600,
                            padding: "2px 8px",
                            height: "auto",
                          }}
                        >
                          {courseShort(h.kurs)}
                        </span>
                      )}

                      <strong style={{ fontSize: "13px" }}>{h.datei}</strong>

                      {h.folie && (
                        <span className="stu-muted" style={{ fontSize: "12px" }}>
                          · {art}
                        </span>
                      )}

                      <div className="stu-grow" />

                      <span className="stu-bdg">
                        {h.quelle === "folien" ? "Folien" : "Rohtext"}
                      </span>
                    </div>

                    {h.text && (
                      <div
                        className="stu-hit-quote stu-markdown"
                        dangerouslySetInnerHTML={{
                          __html: renderMarkdown(
                            h.text.length > 500 ? `${h.text.slice(0, 500)} …` : h.text
                          ),
                        }}
                      />
                    )}

                    <div className="stu-hit-actions">
                      <button
                        type="button"
                        className="stu-tbtn is-pri"
                        onClick={() => handleOpenHitFile(h)}
                        title="Datei im Workspace öffnen"
                      >
                        <Icon n="doc" />
                        <span>{resolved ? "Datei öffnen" : "Im Workspace suchen"}</span>
                      </button>

                      {h.moodle && (
                        <a
                          href={h.moodle}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="stu-tbtn"
                        >
                          In Moodle öffnen ↗
                        </a>
                      )}

                      <button
                        type="button"
                        className="stu-tbtn"
                        onClick={() => {
                          sendToChat({
                            text: `Erkläre mir diese Passage aus ${h.kurs || ""} (${h.datei}, ${art}):\n\n"${h.text?.slice(0, 300) || ""}"`,
                          });
                          toast("Auszug an Agent gesendet.");
                        }}
                        title="Diesen Treffer an Agent schicken"
                      >
                        <Icon n="chat" />
                        <span>Agent fragen</span>
                      </button>
                    </div>
                  </article>
                );
              })
            )}
          </section>
        )}

        {/* Startzustand / Hilfe wenn noch keine Suche abgesetzt */}
        {!submittedQuery && treeHits.length === 0 && (
          <div className="stu-empty-box" style={{ marginTop: "10px" }}>
            <Icon n="search" />
            <strong style={{ fontSize: "14px" }}>Suchfunktion im Kursmaterial</strong>
            <span style={{ maxWidth: "460px" }}>
              Tippe oben einen Begriff ein, um live nach Dateinamen im Dateibaum zu filtern,
              oder drücke Enter, um das Kursmaterial semantisch nach Folien und Textstellen zu durchsuchen.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default Search;
