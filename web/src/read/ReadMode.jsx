// ReadMode.jsx: Magazin-Lesemodus mit Kurs-Kopf, Wochen-Zeitleiste, TOC und Lesepapier
import React from "react";
import { useStudio } from "../app/store.jsx";
import * as files from "../lib/files.js";
import { renderMarkdown } from "../lib/markdown.js";
import { linkifyFolien, onFolieClick } from "../ui/folien.js";
import { Icon } from "../ui/Icon.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Loading } from "../ui/Loading.jsx";
import { useAsync } from "../ui/hooks.js";
import { load, save } from "../ui/storage.js";
import { normalizeFolderName } from "../explorer/tree-utils.js";
import "./read.css";

const { useState, useEffect, useMemo, useRef, useCallback } = React;

/**
 * Normalisiert Kursnamen fuer den flexiblen Abgleich mit den Backend-Daten.
 */
function normalizeCourse(name) {
  if (!name || typeof name !== "string") return "";
  return name
    .toLowerCase()
    .replace(/[⧸：｜？＜＞＂]/g, "/")
    .replace(/[^a-z0-9]/g, "");
}

/**
 * Formatiert ein Datum im Schweizer Format (TT.MM.).
 */
function formatSwissDate(d) {
  if (!d || isNaN(d.getTime())) return "";
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}.`;
}

/**
 * Ermittelt Kennzahlen aus /api/plugins/studium/overview fuer den gewaehlten Kurs.
 * Liest ausschliesslich die existierenden Felder: deadlines, termine, pending, new_files.
 * Fehlt ein Wert, wird er weggelassen statt erfunden.
 */
function computeCourseMetrics(courseName, overviewData) {
  if (!courseName || !overviewData) return [];

  const {
    deadlines = [],
    termine = [],
    pending = [],
    new_files = [],
  } = overviewData;

  const normCourse = normalizeCourse(courseName);
  const matches = (item) => {
    if (!item?.course) return false;
    const norm = normalizeCourse(item.course);
    return norm === normCourse || norm.includes(normCourse) || normCourse.includes(norm);
  };

  const courseDeadlines = deadlines.filter(matches);
  const courseTermine = termine.filter(matches);
  const coursePending = pending.filter(matches);
  const courseNewFiles = new_files.filter(matches);

  const metrics = [];

  // 1. Semester-Kuerzel aus dem Kursnamen (z. B. "26HS", "HS26", "FS26")
  const semMatch = courseName.match(/\b(\d{2}[HhFf][Ss]|[HhFf][Ss]\d{2})\b/);
  if (semMatch) {
    metrics.push(semMatch[0].toUpperCase());
  }

  // 2. Anstehende Termine und Abgaben
  const allEvents = [...courseDeadlines, ...courseTermine]
    .filter((e) => e && e.due)
    .map((e) => {
      const d = new Date(String(e.due).replace(" ", "T"));
      return { ...e, dueDate: d };
    })
    .filter((e) => !isNaN(e.dueDate.getTime()))
    .sort((a, b) => a.dueDate.getTime() - b.dueDate.getTime());

  const now = new Date();
  const upcomingEvents = allEvents.filter(
    (e) => e.dueDate >= new Date(now.getTime() - 86400000)
  );

  // Pruefungstermin ermitteln
  const upcomingExam = upcomingEvents.find(
    (e) => e.kind === "pruefung" || /pruefung|prüfung|exam/i.test(e.name || "")
  );
  if (upcomingExam) {
    const dStr = formatSwissDate(upcomingExam.dueDate);
    metrics.push(`Prüfung ${dStr}`);
  }

  // Naechste Abgabe ermitteln (falls separat von Pruefung)
  const upcomingDeadline = upcomingEvents.find(
    (e) =>
      e !== upcomingExam &&
      (e.kind === "abgabe" || /abgabe/i.test(e.kind || "") || /abgabe/i.test(e.name || ""))
  );
  if (upcomingDeadline) {
    const dStr = formatSwissDate(upcomingDeadline.dueDate);
    metrics.push(`Abgabe ${dStr}`);
  } else if (!upcomingExam && upcomingEvents.length > 0) {
    // Anderes anstehendes Ereignis
    const nextEv = upcomingEvents[0];
    const dStr = formatSwissDate(nextEv.dueDate);
    const label = nextEv.name ? `${nextEv.name} ${dStr}` : `Termin ${dStr}`;
    metrics.push(label);
  }

  // Ueberfaellige Abgaben
  const overdueCount = courseDeadlines.filter((d) => d.overdue).length;
  if (overdueCount > 0) {
    metrics.push(`${overdueCount} überfällig`);
  }

  // 3. Zu verarbeitende Dokumente
  if (coursePending.length > 0) {
    metrics.push(`${coursePending.length} zu verarbeiten`);
  }

  // 4. Neue Dateien
  if (courseNewFiles.length > 0) {
    const count = courseNewFiles.length;
    metrics.push(`${count} neue ${count === 1 ? "Datei" : "Dateien"}`);
  }

  return metrics;
}

/**
 * Liest die Wochennummer aus dem Abschnittsnamen oder den enthaltenen Dateinamen.
 */
function extractWeekNumber(name, filesList = []) {
  const mName = (name || "").match(/(?:Woche|W)\s*0?(\d+)/i);
  if (mName) return parseInt(mName[1], 10);

  const allFiles = (filesList || []).join(" ");
  const mFiles = allFiles.match(/(?:Woche|W)\s*0?(\d+)/i);
  if (mFiles) return parseInt(mFiles[1], 10);

  return 99;
}

/**
 * Bereinigt den Abschnittsnamen fuer die kompakte Darstellung in der Zeitleiste.
 */
function formatSectionTitle(name) {
  if (!name) return "";
  const clean = normalizeFolderName(name);
  return clean
    .replace(/^(?:Woche\s*\d+|W\d+)\s*[-_：:–—/]\s*/i, "")
    .replace(/^(?:Woche\s*\d+|W\d+)\s+/i, "")
    .replace(/^./, (c) => c.toUpperCase());
}

/**
 * Waehlt die primaere Markdown-Datei eines Abschnitts (z. B. Zusammenfassung).
 */
function pickPrimaryFile(filesList = []) {
  if (!filesList || filesList.length === 0) return null;
  const zf = filesList.find((f) => /zusammenfassung/i.test(f) && f.endsWith(".md"));
  if (zf) return zf;
  const cs = filesList.find((f) => /cheatsheet/i.test(f) && f.endsWith(".md"));
  if (cs) return cs;
  const anyMd = filesList.find((f) => f.endsWith(".md"));
  if (anyMd) return anyMd;
  return filesList[0];
}

/**
 * Lesbare Kurzbezeichnung fuer Dateien in der Wochenliste.
 */
function formatFileName(filename) {
  if (/zusammenfassung/i.test(filename)) return "Zusammenfassung";
  if (/cheatsheet/i.test(filename)) return "Cheatsheet";
  return filename.replace(/\.md$/, "");
}

export function ReadMode() {
  const {
    course,
    courses,
    tree,
    activeTab,
    openFile,
    setView,
    openFolie,
    mobile,
    api,
  } = useStudio();

  const containerRef = useRef(null);
  const paperRef = useRef(null);

  // Inhaltsverzeichnis und aktiver Abschnitt
  const [toc, setToc] = useState([]);
  const [activeHeadingId, setActiveHeadingId] = useState("");
  const [tocOpen, setTocOpen] = useState(() => load("read-toc-open", true));

  const toggleToc = useCallback(() => {
    setTocOpen((prev) => {
      const next = !prev;
      save("read-toc-open", next);
      return next;
    });
  }, []);

  // Kennzahlen aus /api/plugins/studium/overview
  const {
    data: overviewRes,
    loading: overviewLoading,
  } = useAsync(async () => {
    try {
      return await api("overview");
    } catch {
      return null;
    }
  }, []);

  const overviewData = overviewRes?.data || overviewRes || {};

  const metrics = useMemo(() => {
    return computeCourseMetrics(course, overviewData);
  }, [course, overviewData]);

  const metricsText = metrics.join(" · ");

  // Pruefen, ob der aktive Tab ein Markdown-Dokument ist
  const isMarkdownTab = Boolean(
    activeTab &&
    (activeTab.kind === "markdown" ||
     activeTab.name?.toLowerCase().endsWith(".md") ||
     activeTab.path?.toLowerCase().endsWith(".md"))
  );

  // Inhalt der aktiven Markdown-Datei laden
  const {
    data: fileData,
    loading: fileLoading,
    error: fileError,
    reload: reloadFile,
  } = useAsync(async () => {
    if (!isMarkdownTab || !activeTab?.root || !activeTab?.path) {
      return null;
    }
    return await files.read(activeTab.root, activeTab.path);
  }, [isMarkdownTab, activeTab?.root, activeTab?.path]);

  // Abschnitte fuer den gewaehlten Kurs aus kurse_listing oder tree ermitteln
  const courseSections = useMemo(() => {
    const curCourse = courses?.find((k) => k.name === course);
    if (curCourse?.sections && curCourse.sections.length > 0) {
      return curCourse.sections;
    }
    if (tree?.roots) {
      const lernenRoot = tree.roots.find((r) => r.root === "lernen");
      const courseFolder = lernenRoot?.children?.find((c) => c.name === course);
      if (courseFolder?.children) {
        return courseFolder.children
          .filter((child) => child.type === "dir" || child.children)
          .map((dir) => ({
            name: dir.name,
            files: (dir.children || []).map((f) => f.name),
          }));
      }
    }
    return [];
  }, [courses, tree, course]);

  // Abschnitte nach Wochennummer sortieren
  const sortedSections = useMemo(() => {
    return [...courseSections].sort(
      (a, b) => extractWeekNumber(a.name, a.files) - extractWeekNumber(b.name, b.files)
    );
  }, [courseSections]);

  // Aktiver Abschnitt anhand des Dateipfads bestimmen
  const activeSectionName = useMemo(() => {
    if (!activeTab?.path) return "";
    const parts = activeTab.path.split("/");
    if (parts.length >= 2) {
      const folderName = parts[parts.length - 2];
      const match = sortedSections.find((s) => s.name === folderName);
      if (match) return match.name;
    }
    const found = sortedSections.find((s) => activeTab.path.includes(s.name));
    return found ? found.name : "";
  }, [activeTab?.path, sortedSections]);

  // Markdown rendern und Folien-Links einbinden
  const renderedContent = useMemo(() => {
    if (!fileData?.content) return "";
    const rawHtml = renderMarkdown(fileData.content);
    return linkifyFolien(rawHtml);
  }, [fileData?.content]);

  // Ueberschriften fuer das Inhaltsverzeichnis aus dem gerenderten DOM extrahieren
  useEffect(() => {
    if (!paperRef.current || !renderedContent) {
      setToc([]);
      return;
    }

    const headings = paperRef.current.querySelectorAll("h1, h2, h3, h4");
    const items = [];
    headings.forEach((el, index) => {
      if (!el.id) {
        el.id = `stu-heading-${index}`;
      }
      const text = (el.textContent || "").trim();
      if (text) {
        const level = parseInt(el.tagName.replace(/^h/i, ""), 10) || 2;
        items.push({ id: el.id, text, level });
      }
    });

    setToc(items);
    if (items.length > 0) {
      setActiveHeadingId(items[0].id);
    } else {
      setActiveHeadingId("");
    }
  }, [renderedContent]);

  // Aktive Ueberschrift beim Scrollen des Lesebereichs ermitteln
  useEffect(() => {
    const container = containerRef.current;
    if (!container || toc.length === 0) return;

    function handleScroll() {
      const containerTop = container.getBoundingClientRect().top;
      let currentId = toc[0]?.id || "";

      for (const item of toc) {
        const el = document.getElementById(item.id);
        if (el) {
          const rect = el.getBoundingClientRect();
          if (rect.top - containerTop <= 80) {
            currentId = item.id;
          } else {
            break;
          }
        }
      }
      setActiveHeadingId(currentId);
    }

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [toc]);

  // Klick auf Inhaltsverzeichnis scrollt zur Ueberschrift
  const handleTocClick = useCallback((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeadingId(id);
    }
  }, []);

  // Klick auf eine Woche in der Zeitleiste
  const handleWeekClick = useCallback(
    (s) => {
      const targetFile = pickPrimaryFile(s.files);
      if (!targetFile) return;
      const relPath = `${course}/${s.name}/${targetFile}`;
      openFile("lernen", relPath);
      setView("read");
    },
    [course, openFile, setView]
  );

  // Titel fuer die Kopfzeile
  const displayTitle = useMemo(() => {
    if (!course) return "Kurs";
    return course.replace(/^\d{2}[HhFf][Ss]\s+|^[HhFf][Ss]\d{2}\s+/, "").trim() || course;
  }, [course]);

  return (
    <div className="stu-read" ref={containerRef}>
      {/* Kopfbereich */}
      <header className="stu-read-h">
        {overviewLoading ? (
          <div className="stu-kicker">
            <span className="stu-kicker-loading">
              <span className="stu-spinner" aria-hidden="true" />
              <span>Kennzahlen werden geladen …</span>
            </span>
          </div>
        ) : metricsText ? (
          <div className="stu-kicker">{metricsText}</div>
        ) : null}

        <div className="stu-read-title-row">
          <h1>{displayTitle}</h1>
          <div className="stu-read-actions">
            {isMarkdownTab && toc.length > 0 && (
              <button
                type="button"
                className={`stu-tbtn ${tocOpen ? "is-on" : ""}`}
                onClick={toggleToc}
                title={tocOpen ? "Inhaltsverzeichnis ausblenden" : "Inhaltsverzeichnis einblenden"}
                aria-label="Inhaltsverzeichnis umschalten"
              >
                <Icon n="toc" />
                <span>{tocOpen ? "Inhalt verbergen" : "Inhalt zeigen"}</span>
              </button>
            )}
            <button
              type="button"
              className="stu-tbtn is-pri"
              onClick={() => setView("work")}
              title="In Arbeitsansicht bearbeiten"
            >
              <Icon n="edit" />
              <span>Bearbeiten</span>
            </button>
          </div>
        </div>

        {sortedSections.length > 0 ? (
          <ol className="stu-weeks" aria-label="Wochen-Zeitleiste">
            {sortedSections.map((s) => {
              const wNum = extractWeekNumber(s.name, s.files);
              const wLabel = wNum < 99 ? `W${String(wNum).padStart(2, "0")}` : "W";
              const shortTitle = formatSectionTitle(s.name);
              const isOn = activeSectionName === s.name;
              return (
                <li
                  key={s.name}
                  className={isOn ? "is-on" : ""}
                  onClick={() => handleWeekClick(s)}
                  title={`${wLabel}: ${normalizeFolderName(s.name)}`}
                >
                  <b>{wLabel}</b>
                  <span>{shortTitle}</span>
                </li>
              );
            })}
          </ol>
        ) : null}
      </header>

      {/* Hauptbereich */}
      {isMarkdownTab ? (
        <div className={`stu-read-b ${mobile || !tocOpen || toc.length === 0 ? "no-toc" : ""}`}>
          {/* Inhaltsverzeichnis links (auf Mobilgeraeten oder bei Zuklappen ausgeblendet) */}
          {!mobile && tocOpen && toc.length > 0 && (
            <nav className="stu-toc" aria-label="Inhaltsverzeichnis">
              <div className="stu-toc-h">
                <div className="stu-label">Auf dieser Seite</div>
                <button
                  type="button"
                  className="stu-icbtn"
                  onClick={toggleToc}
                  title="Inhaltsverzeichnis einklappen"
                  aria-label="Inhaltsverzeichnis einklappen"
                >
                  <Icon n="x" />
                </button>
              </div>
              {toc.map((item) => (
                <a
                  key={item.id}
                  className={`lvl-${item.level} ${activeHeadingId === item.id ? "is-on" : ""}`}
                  onClick={(e) => {
                    e.preventDefault();
                    handleTocClick(item.id);
                  }}
                  href={`#${item.id}`}
                  title={item.text}
                >
                  {item.text}
                </a>
              ))}
            </nav>
          )}

          {/* Lese-Papier rechts */}
          {fileLoading ? (
            <div className="stu-read-loading">
              <Loading text="Dokument wird geladen …" />
            </div>
          ) : fileError ? (
            <div className="stu-read-error" role="alert">
              <p>Datei konnte nicht geladen werden.</p>
              <button
                type="button"
                className="stu-tbtn"
                onClick={() => reloadFile()}
              >
                Erneut versuchen
              </button>
            </div>
          ) : (
            <article
              ref={paperRef}
              className="stu-paper"
              onClick={(e) => onFolieClick(e, openFolie)}
              dangerouslySetInnerHTML={{ __html: renderedContent }}
            />
          )}
        </div>
      ) : (
        /* Kursuebersicht, wenn kein aktiver Markdown-Tab gewaehlt ist */
        <div className="stu-read-b no-toc">
          <div className="stu-read-overview">
            <div className="stu-read-hint">
              <Icon n="files" />
              <div>
                <strong>Datei im Explorer wählen</strong>
                <p>
                  Wählen Sie eine Markdown-Datei im Explorer links aus oder klicken
                  Sie auf einen der Abschnitte in der Wochen-Zeitleiste oben.
                </p>
              </div>
            </div>

            <div className="stu-read-overview-weeks">
              <h3>Abschnitte und Materialien</h3>
              {sortedSections.length === 0 ? (
                <p className="stu-muted">Keine Abschnitte für diesen Kurs gefunden.</p>
              ) : (
                <div className="stu-read-weeklist">
                  {sortedSections.map((s) => {
                    const wNum = extractWeekNumber(s.name, s.files);
                    const wLabel = wNum < 99 ? `W${String(wNum).padStart(2, "0")}` : "W";
                    const shortTitle = formatSectionTitle(s.name);

                    return (
                      <div key={s.name} className="stu-read-weekitem">
                        <div className="stu-read-weekitem-h">
                          <span className="stu-read-weeknum">{wLabel}</span>
                          <span className="stu-read-weektitle">{shortTitle}</span>
                        </div>
                        {s.files && s.files.length > 0 ? (
                          <div className="stu-read-files">
                            {s.files.map((file) => {
                              const isMd = file.endsWith(".md");
                              return (
                                <button
                                  key={file}
                                  type="button"
                                  className={`stu-read-filebtn ${isMd ? "is-md" : ""}`}
                                  onClick={() => {
                                    const root = isMd ? "lernen" : "moodle";
                                    openFile(root, `${course}/${s.name}/${file}`);
                                    if (isMd) setView("read");
                                  }}
                                  title={file}
                                >
                                  <Badge name={file} />
                                  <span>{formatFileName(file)}</span>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <p className="stu-no-files">Keine Dokumente abgelegt.</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ReadMode;
