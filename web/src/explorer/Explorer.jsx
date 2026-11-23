// Explorer.jsx: Moodle-Struktur mit verknuepften Artefakten, Links und Verarbeitungsstand
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Loading } from "../ui/Loading.jsx";
import { useAsync } from "../ui/hooks.js";
import { cleanHtml, findPathInTree } from "./tree-utils.js";
import "./explorer.css";

const { useState, useMemo, useEffect, useRef } = React;

function FolienMenu({ folienPath, onOpen }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    window.addEventListener("click", onClickOutside);
    return () => window.removeEventListener("click", onClickOutside);
  }, [open]);

  return (
    <div className="stu-folien-menu" ref={menuRef}>
      <button
        type="button"
        className="stu-folien-menu-btn"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        title="Weitere Artefakte"
        aria-label="Weitere Artefakte"
      >
        …
      </button>
      {open && (
        <div className="stu-folien-dropdown">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              onOpen();
            }}
          >
            Folientext (.folien.md)
          </button>
        </div>
      )}
    </div>
  );
}

export function Explorer() {
  const {
    course,
    setCourse,
    courses,
    coursesLoading,
    tree,
    treeLoading,
    activeId,
    openFile,
    setPdfOpen,
    sendToChat,
    setView,
    api,
    toast,
  } = useStudio();

  const [query, setQuery] = useState("");
  const [openSections, setOpenSections] = useState({});

  // Explorer-Daten vom Backend abrufen (/explorer/tree)
  const {
    data: explorerData,
    loading: explorerLoading,
    reload: reloadExplorer,
  } = useAsync(async () => {
    if (!course) return null;
    try {
      return await api("explorer/tree?course=" + encodeURIComponent(course));
    } catch {
      return null;
    }
  }, [course]);

  // Fallback: Falls der spezifische Endpunkt noch nicht geantwortet hat, bauen wir aus tree
  const parsedSections = useMemo(() => {
    if (explorerData?.sections) {
      return explorerData.sections;
    }

    // Fallback ueber lokalen tree
    if (!tree?.roots || !course) return [];

    const moodleRoot = tree.roots.find((r) => r.root === "moodle");
    const courseNode = moodleRoot?.children?.find(
      (c) => c.name === course || c.name?.toLowerCase() === course.toLowerCase()
    );
    if (!courseNode?.children) return [];

    const sections = [];
    for (const sec of courseNode.children) {
      if (sec.type === "dir" || Array.isArray(sec.children)) {
        const secFiles = (sec.children || [])
          .filter((f) => f.type !== "dir")
          .map((f) => {
            const isPdf = f.name.toLowerCase().endsWith(".pdf");
            const isUrl = f.name.toLowerCase().endsWith(".desktop") || f.name.toLowerCase().endsWith(".webloc");
            const baseStem = isPdf ? f.name.slice(0, -4) : "";

            let hasZf = false;
            let zfPath = "";
            let hasCs = false;
            let csPath = "";
            let hasFolien = false;
            let folienPath = "";

            if (isPdf) {
              zfPath = `${course}/${sec.name}/${baseStem}.zusammenfassung.md`;
              hasZf = Boolean(findPathInTree(tree, "lernen", zfPath));
              csPath = `${course}/${sec.name}/${baseStem}.cheatsheet.md`;
              hasCs = Boolean(findPathInTree(tree, "lernen", csPath));
              folienPath = `${course}/${sec.name}/${f.name}.folien.md`;
              hasFolien = Boolean(findPathInTree(tree, "knowledge", folienPath));
            }

            return {
              name: f.name,
              path: f.path,
              root: "moodle",
              kind: isPdf ? "pdf" : isUrl ? "url" : f.kind || "other",
              has_zusammenfassung: hasZf,
              zusammenfassung_path: zfPath,
              has_cheatsheet: hasCs,
              cheatsheet_path: csPath,
              has_folien: hasFolien,
              folien_path: folienPath,
            };
          });

        const weekMatch = sec.name.match(/(?:Woche|W)\s*0?(\d+)/i);
        const weekNum = weekMatch ? parseInt(weekMatch[1], 10) : 999;
        const weekLabel = weekNum < 999 ? `W${String(weekNum).padStart(2, "0")}` : "";
        const cleanName = cleanHtml(sec.name);
        const displayName = weekLabel
          ? cleanName.replace(/^(?:W(?:oche)?\s*0?\d+\b\s*[:：.\-–—]?\s*)+/i, "").trim() || cleanName
          : cleanName;

        sections.push({
          name: sec.name,
          clean_name: cleanName,
          display_name: displayName,
          week_num: weekNum,
          week_label: weekLabel,
          is_current: false,
          files: secFiles,
        });
      }
    }

    return sections;
  }, [explorerData, tree, course]);

  // Eigene Dateien fuer den aktuellen Kurs
  const eigeneFiles = useMemo(() => {
    if (explorerData?.eigene) {
      return explorerData.eigene;
    }
    if (!tree?.roots || !course) return [];
    const moodleRoot = tree.roots.find((r) => r.root === "moodle");
    const eigeneNode = moodleRoot?.children?.find((c) => c.name === "_eigene");
    const courseEigene = eigeneNode?.children?.find((c) => c.name === course);
    if (!courseEigene?.children) return [];

    return courseEigene.children
      .filter((f) => f.type !== "dir")
      .map((f) => ({
        name: f.name,
        path: f.path,
        root: "moodle",
        kind: f.name.toLowerCase().endsWith(".pdf") ? "pdf" : "other",
        is_eigene: true,
      }));
  }, [explorerData, tree, course]);

  // Filter-Funktion
  const matchesFilter = (str) => {
    if (!query.trim()) return true;
    return (str || "").toLowerCase().includes(query.trim().toLowerCase());
  };

  // Sobald Abschnitte geladen sind oder der Kurs wechselt:
  // Nur die aktuelle Woche bzw. der eindeutig ausgewaehlte Abschnitt ist aufgeklappt.
  useEffect(() => {
    if (!parsedSections || parsedSections.length === 0) return;
    const initialOpen = {};
    for (const s of parsedSections) {
      initialOpen[s.name] = !!s.is_current;
    }
    setOpenSections(initialOpen);
  }, [course, parsedSections]);

  const filteredSections = useMemo(() => {
    return parsedSections
      .map((sec) => {
        const matchingFiles = sec.files.filter((f) => {
          return matchesFilter(f.name) || matchesFilter(f.link_name) || matchesFilter(sec.clean_name);
        });
        return {
          ...sec,
          files: matchingFiles,
          totalCount: sec.files.length,
        };
      })
      .filter((sec) => (query.trim() ? sec.files.length > 0 : sec.totalCount > 0));
  }, [parsedSections, query]);

  // PDF-Klick: Oeffnet PDF links und Zusammenfassung daneben (falls vorhanden)
  function handlePdfClick(file) {
    if (file.has_zusammenfassung && file.zusammenfassung_path) {
      // Zusammenfassung oeffnen mit automatischer PDF-Anzeige daneben
      openFile("lernen", file.zusammenfassung_path);
      setPdfOpen(true);
    } else {
      openFile("moodle", file.path);
    }
  }

  // Verarbeiten-Knopf startet den Skill im Chat
  // Startet den Graphen verarbeiten im Backend; Freigabefälle erscheinen als Karte im Chat
  async function handleVerarbeiten(e, file) {
    e.stopPropagation();
    try {
      await api("verarbeiten", { method: "POST", body: { rel: file.path } });
      toast(`Verarbeitung gestartet: ${file.name} (etwa 1 bis 3 Minuten)`);
    } catch (err) {
      toast(`Verarbeitung nicht gestartet: ${err.message}`);
    }
  }

  const currentWeek = explorerData?.current_week ?? 999;

  return (
    <div className="stu-explorer">
      {/* Kursauswahl */}
      <div className="stu-explorer-courserow">
        <select
          className="stu-course"
          value={course || ""}
          onChange={(e) => setCourse && setCourse(e.target.value)}
          aria-label="Kurs auswählen"
        >
          {coursesLoading && <option value="">Kurse werden geladen …</option>}
          {!coursesLoading && (!courses || courses.length === 0) && (
            <option value="">Keine Kurse verfügbar</option>
          )}
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
        <button
          type="button"
          className="stu-icbtn stu-modul-btn"
          onClick={() => setView && setView("modul")}
          title="Modulübersicht anzeigen"
          aria-label="Modulübersicht anzeigen"
        >
          <Icon n="modul" />
        </button>
      </div>

      {/* Filterfeld */}
      <input
        className="stu-filter"
        type="search"
        placeholder="Materialien filtern …"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Materialien filtern"
      />

      {/* Dateibaum */}
      {treeLoading || explorerLoading ? (
        <Loading text="Materialien werden geladen …" />
      ) : (
        <div className="stu-tree">
          {/* Moodle-Abschnitte (einziger Baum, keine Wurzeln Lernen/Folien) */}
          {filteredSections.map((sec) => {
            // Nur die aktuelle Woche (oder zuletzt geaenderte) ist standardmaessig offen
            const hasActiveFile = sec.files.some((f) => activeId?.includes(f.path));
            const shouldOpen =
              query.trim().length > 0 ||
              hasActiveFile ||
              (openSections[sec.name] !== undefined ? openSections[sec.name] : !!sec.is_current);

            return (
              <details
                key={sec.name}
                open={shouldOpen}
                onToggle={(e) => {
                  const isOpen = e.currentTarget.open;
                  setOpenSections((prev) => ({ ...prev, [sec.name]: isOpen }));
                }}
              >
                <summary className="stu-row">
                  {sec.week_label && <span className="stu-wk">{sec.week_label}</span>}
                  <span className="stu-row-title">
                    {sec.display_name || sec.clean_name || sec.name}
                  </span>
                </summary>

                {sec.files.map((file) => {
                  const fileId = "moodle:" + file.path;
                  const isPdfActive = activeId === fileId;
                  const isZfActive = file.zusammenfassung_path && activeId === `lernen:${file.zusammenfassung_path}`;
                  const isOn = isPdfActive || isZfActive;

                  // 1. Moodle-Link (.desktop, .webloc)
                  if (file.kind === "url") {
                    return (
                      <div
                        key={file.path}
                        className="stu-row lvl2 is-link"
                        onClick={() => {
                          if (file.url) {
                            window.open(file.url, "_blank", "noopener,noreferrer");
                          }
                        }}
                        title={file.url || file.name}
                        role="button"
                        tabIndex={0}
                      >
                        <Icon n="link" />
                        <span className="stu-row-title">{file.link_name || file.name.replace(/\.(desktop|webloc)$/i, "")}</span>
                        {file.url && (
                          <span className="stu-link-url">
                            {file.url.replace(/^https?:\/\//i, "").split("/")[0]}
                          </span>
                        )}
                      </div>
                    );
                  }

                  // 2. PDF mit Artefakt-Knoepfen
                  if (file.kind === "pdf") {
                    const hasArtifacts = file.has_zusammenfassung || file.has_cheatsheet || file.has_folien;

                    return (
                      <div key={file.path} className="stu-pdf-item">
                        <div
                          className={`stu-row lvl2 ${isOn ? "is-on" : ""}`.trim()}
                          onClick={() => handlePdfClick(file)}
                          role="button"
                          tabIndex={0}
                          title={file.path}
                        >
                          <Badge name={file.name} />
                          <span className="stu-row-title">{file.name}</span>
                          {file.pending && (
                            <span className={`stu-badge-pending is-${file.pending}`}>
                              {file.pending}
                            </span>
                          )}
                          {file.pending && (
                            <button
                              type="button"
                              className="stu-btn-verarbeiten"
                              onClick={(e) => handleVerarbeiten(e, file)}
                              title="Mit dem Graphen verarbeiten (Extraktion, Prüfung, Freigabe)"
                            >
                              verarbeiten
                            </button>
                          )}
                        </div>

                        {hasArtifacts && (
                          <div className="stu-artefakt-bar">
                            {file.has_zusammenfassung && (
                              <button
                                type="button"
                                className="stu-art-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openFile("lernen", file.zusammenfassung_path);
                                  setPdfOpen(true);
                                }}
                                title="Zusammenfassung mit PDF öffnen"
                              >
                                Zusammenfassung
                              </button>
                            )}
                            {file.has_cheatsheet && (
                              <button
                                type="button"
                                className="stu-art-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openFile("lernen", file.cheatsheet_path);
                                }}
                                title="Cheatsheet öffnen"
                              >
                                Cheatsheet
                              </button>
                            )}
                            {file.has_folien && (
                              <FolienMenu
                                folienPath={file.folien_path}
                                onOpen={() => openFile("knowledge", file.folien_path)}
                              />
                            )}
                          </div>
                        )}
                      </div>
                    );
                  }

                  // 3. Andere Dateien (z.B. Python, Markdown, Bilder, Notizen)
                  return (
                    <div
                      key={file.path}
                      className={`stu-row lvl2 ${isOn ? "is-on" : ""}`.trim()}
                      onClick={() => openFile("moodle", file.path)}
                      role="button"
                      tabIndex={0}
                      title={file.path}
                    >
                      <Badge name={file.name} />
                      <span className="stu-row-title">{file.name}</span>
                    </div>
                  );
                })}
              </details>
            );
          })}

          {/* Eigene Uploads des Kurses */}
          {eigeneFiles.length > 0 && (
            <details open={true}>
              <summary className="stu-row">
                <span className="stu-row-title">Eigene</span>
              </summary>
              {eigeneFiles.map((file) => {
                const fileId = "moodle:" + file.path;
                const isOn = activeId === fileId;
                return (
                  <div
                    key={file.path}
                    className={`stu-row lvl2 ${isOn ? "is-on" : ""}`.trim()}
                    onClick={() => openFile("moodle", file.path)}
                    role="button"
                    tabIndex={0}
                    title={file.path}
                  >
                    <Badge name={file.name} />
                    <span className="stu-row-title">{file.name}</span>
                  </div>
                );
              })}
            </details>
          )}

          {filteredSections.length === 0 && eigeneFiles.length === 0 && (
            <div className="stu-tree-empty stu-muted">
              {query ? "Keine passenden Materialien gefunden." : "Keine Kursmaterialien abgelegt."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default Explorer;
