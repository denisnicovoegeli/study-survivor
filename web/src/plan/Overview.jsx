// Overview.jsx: Dashboard-Uebersicht mit Kennzahlen, Deadlines, neuen Dateien, Kursliste und Dokumenten-Upload
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Loading } from "../ui/Loading.jsx";
import { useAsync } from "../ui/hooks.js";
import {
  parseDue,
  fmtDate,
  fmtDue,
  kindLabel,
  courseHue,
  courseShort,
  resolveFileInTree,
} from "./utils.js";
import "./plan.css";

const { useState, useMemo, useCallback } = React;

export function Overview() {
  const {
    api,
    toast,
    openFile,
    sendToChat,
    setCourse,
    tree,
    reloadTree,
    courses: storeCourses,
  } = useStudio();

  // Uebersichts- und Kursdaten abrufen
  const {
    data: overviewRes,
    loading: overviewLoading,
    error: overviewError,
    reload: reloadOverview,
  } = useAsync(useCallback(() => api("overview"), [api]), [api]);

  const {
    data: kurseRes,
    loading: kurseLoading,
    reload: reloadKurse,
  } = useAsync(useCallback(() => api("kurse"), [api]), [api]);

  const overviewData = useMemo(() => overviewRes?.data || {}, [overviewRes]);

  // Termine und Deadlines zusammenfuehren und sortieren
  const termine = useMemo(() => {
    const list = [
      ...(overviewData.termine || []),
      ...(overviewData.deadlines || []),
    ];
    list.sort((a, b) => String(a.due || "").localeCompare(String(b.due || "")));
    return list;
  }, [overviewData]);

  const pending = useMemo(() => overviewData.pending || [], [overviewData]);
  const newFiles = useMemo(() => overviewData.new_files || [], [overviewData]);
  const kurse = useMemo(() => kurseRes?.kurse || storeCourses || [], [kurseRes, storeCourses]);

  // Upload eigener Dokumente
  const [uploadCourse, setUploadCourse] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);

  const handleUpload = async (e) => {
    if (e) e.preventDefault();
    const courseTrimmed = uploadCourse.trim();
    if (!courseTrimmed || !uploadFile) {
      setUploadMsg({ ok: false, text: "Bitte Kurs angeben und eine Datei auswählen." });
      return;
    }

    setUploadBusy(true);
    setUploadMsg(null);

    try {
      const fd = new FormData();
      fd.append("course", courseTrimmed);
      fd.append("file", uploadFile);

      const SDK = window.__HERMES_PLUGIN_SDK__;
      const fetchFn = SDK?.authedFetch || window.fetch;
      const res = await fetchFn("/api/plugins/studium/kurse/upload", {
        method: "POST",
        body: fd,
      });

      let json = null;
      try {
        json = await res.json();
      } catch {
        json = null;
      }

      if (!res.ok) {
        throw new Error(json?.detail || `Upload fehlgeschlagen (HTTP ${res.status})`);
      }

      setUploadMsg({
        ok: true,
        text: `Erfolgreich gespeichert: ${json.name || uploadFile.name} → ${json.course || courseTrimmed}.`,
      });
      toast(`Dokument ${uploadFile.name} hochgeladen.`);
      setUploadFile(null);
      setFileInputKey((k) => k + 1);

      // Daten und Baum aktualisieren
      reloadOverview();
      reloadKurse();
      if (reloadTree) reloadTree();
    } catch (err) {
      setUploadMsg({
        ok: false,
        text: err?.message || "Upload fehlgeschlagen.",
      });
    } finally {
      setUploadBusy(false);
    }
  };

  // Klick auf eine neue Datei oeffnet sie im Workspace
  const handleOpenFile = (f) => {
    const filename = f.name || "";
    const resolved = resolveFileInTree(tree, filename);
    if (resolved) {
      openFile(resolved.root, resolved.path);
      return;
    }
    // Fallback auf moodle mit relativer Ablage
    const path = f.course && f.section ? `${f.course}/${f.section}/${filename}` : filename;
    openFile("moodle", path);
  };

  const reloadAll = () => {
    reloadOverview();
    reloadKurse();
  };

  return (
    <div className="stu-overview">
      <header className="stu-viewh" style={{ margin: "-20px -24px 0 -24px" }}>
        <h2>Studium Cockpit</h2>
        <span className="stu-viewh-desc">
          {overviewLoading && !overviewRes
            ? "Übersicht wird geladen …"
            : "Zentrale Übersicht über Termine, Lernstoff, Kurse und Uploads"}
        </span>

        <div className="stu-grow" />

        <button
          type="button"
          className="stu-tbtn"
          onClick={reloadAll}
          title="Alle Daten neu laden"
        >
          <span>Aktualisieren</span>
        </button>
      </header>

      {overviewError && (
        <div className="stu-error-box">
          <span>Fehler beim Laden der Übersicht: {overviewError.message || String(overviewError)}</span>
          <button type="button" className="stu-tbtn is-pri" onClick={reloadAll}>
            Erneut versuchen
          </button>
        </div>
      )}

      {overviewLoading && !overviewRes ? (
        <div style={{ padding: "40px", display: "grid", placeItems: "center" }}>
          <Loading text="Übersicht wird geladen …" />
        </div>
      ) : (
        <>
          {/* Kennzahlen */}
          <section className="stu-stats" aria-label="Kennzahlen">
            <div className="stu-stat-card">
              <span className="stu-stat-num">{termine.length}</span>
              <span className="stu-stat-label">Termine & Deadlines (14 Tage)</span>
            </div>

            <div className="stu-stat-card">
              <span className="stu-stat-num">{pending.length}</span>
              <span className="stu-stat-label">Zu verarbeitende Dateien</span>
            </div>

            <div className="stu-stat-card">
              <span className="stu-stat-num">{newFiles.length}</span>
              <span className="stu-stat-label">Neue Dateien seit letztem Lauf</span>
            </div>

            <div className="stu-stat-card">
              <span className="stu-stat-num">{kurse.length}</span>
              <span className="stu-stat-label">Eingetragene Kurse</span>
            </div>
          </section>

          {/* Hauptbereich zweispaltig */}
          <div className="stu-overview-grid">
            {/* Linke Spalte: Termine, Verarbeiten, Neue Dateien */}
            <div className="stu-overview-col">
              {/* Termine & Deadlines */}
              <section className="stu-panel">
                <div className="stu-panel-head">
                  <h3>Termine & Deadlines (14 Tage)</h3>
                  <span className="stu-col-count">{termine.length}</span>
                </div>

                {termine.length === 0 ? (
                  <div className="stu-empty-box">
                    <span>Keine anstehenden Termine in den nächsten 14 Tagen.</span>
                  </div>
                ) : (
                  <ul className="stu-list">
                    {termine.slice(0, 15).map((t, idx) => {
                      const isBold = t.kind === "abgabe" || t.kind === "pruefung";
                      return (
                        <li
                          key={t.course + t.name + t.due + idx}
                          className="stu-row"
                          style={{ borderLeft: `3px solid hsl(${courseHue(t.course)} 65% 50%)` }}
                        >
                          <span className="stu-row-date">
                            {fmtDue(t.due, t.all_day)}
                          </span>

                          <div className="stu-row-grow">
                            <strong style={{ fontWeight: isBold ? 700 : 600 }}>
                              {t.name}
                            </strong>
                            {t.course && (
                              <span className="stu-row-sub">
                                {courseShort(t.course)}
                              </span>
                            )}
                          </div>

                          {t.kind && (
                            <span
                              className="stu-bdg"
                              style={{
                                background: isBold ? "var(--acc)" : "var(--raise)",
                                color: isBold ? "var(--acc-ink)" : "var(--muted)",
                                fontWeight: isBold ? 700 : 500,
                              }}
                            >
                              {kindLabel(t.kind)}
                            </span>
                          )}

                          {t.url && (
                            <a
                              href={t.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="stu-tbtn"
                              style={{ padding: "3px 7px", fontSize: "11px" }}
                            >
                              Moodle ↗
                            </a>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {/* Zu verarbeiten */}
              <section className="stu-panel">
                <div className="stu-panel-head">
                  <h3>Zu verarbeiten</h3>
                  <span className="stu-col-count">{pending.length}</span>
                </div>

                {pending.length === 0 ? (
                  <div className="stu-empty-box">
                    <span>Alles aktuell. Nichts zu verarbeiten.</span>
                  </div>
                ) : (
                  <>
                    <ul className="stu-list">
                      {pending.slice(0, 12).map((p, idx) => (
                        <li key={(p.rel || p.name) + idx} className="stu-row">
                          <div className="stu-row-grow">
                            <strong>{p.name}</strong>
                            <span className="stu-row-sub">
                              {p.course} · {p.section}
                            </span>
                          </div>

                          <span
                            className="stu-bdg"
                            style={{
                              background: p.reason === "neu" ? "rgba(47, 154, 103, 0.15)" : "var(--raise)",
                              color: p.reason === "neu" ? "var(--ok)" : "var(--muted)",
                            }}
                          >
                            {p.reason === "neu" ? "neu" : "veraltet"}
                          </span>

                          <button
                            type="button"
                            className="stu-tbtn"
                            style={{ background: "var(--acc)", color: "var(--acc-ink)", padding: "3px 8px" }}
                            onClick={() => {
                              sendToChat({
                                skill: "verarbeiten",
                                arg: p.course || p.name,
                              });
                              toast(`Skill /verarbeiten für ${p.course || p.name} gestartet.`);
                            }}
                            title="Mit Agent verarbeiten"
                          >
                            /verarbeiten
                          </button>
                        </li>
                      ))}
                    </ul>

                    {pending.length > 12 && (
                      <div className="stu-muted" style={{ fontSize: "12px", textAlign: "center" }}>
                        … und {pending.length - 12} weitere Dateien
                      </div>
                    )}
                  </>
                )}
              </section>

              {/* Neue Dateien */}
              <section className="stu-panel">
                <div className="stu-panel-head">
                  <h3>Neue Dateien</h3>
                  <span className="stu-col-count">{newFiles.length}</span>
                </div>

                {newFiles.length === 0 ? (
                  <div className="stu-empty-box">
                    <span>Keine neuen Dateien seit dem letzten Lauf.</span>
                  </div>
                ) : (
                  <ul className="stu-list">
                    {newFiles.slice(0, 12).map((f, idx) => (
                      <li
                        key={String(f.file_id || f.name) + idx}
                        className="stu-row stu-row--click"
                        onClick={() => handleOpenFile(f)}
                        title="Datei im Workspace öffnen"
                      >
                        <Badge name={f.name} />

                        <div className="stu-row-grow">
                          <strong>{f.name}</strong>
                          <span className="stu-row-sub">
                            {f.course} / {f.section}
                          </span>
                        </div>

                        {f.modified && (
                          <span className="stu-row-date" style={{ textAlign: "right" }}>
                            {fmtDate(f.modified)}
                          </span>
                        )}

                        <span className="stu-tbtn" style={{ padding: "3px 8px", fontSize: "11px" }}>
                          Öffnen
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            {/* Rechte Spalte: Upload & Kursliste */}
            <div className="stu-overview-col">
              {/* Eigene Datei hochladen */}
              <section className="stu-panel">
                <div className="stu-panel-head">
                  <h3>Eigene Datei hochladen</h3>
                  <Icon n="plus" />
                </div>

                <p className="stu-muted" style={{ margin: 0, fontSize: "12.5px" }}>
                  Material aus Teams oder Mails für die automatische Aufbereitung ablegen.
                </p>

                <form onSubmit={handleUpload} className="stu-upload-form">
                  <div className="stu-form-group">
                    <label>Kursname *</label>
                    <input
                      type="text"
                      className="stu-input"
                      list="stu-overview-course-list"
                      placeholder="z. B. Reinforcement Learning"
                      value={uploadCourse}
                      onChange={(e) => setUploadCourse(e.target.value)}
                      required
                    />
                    <datalist id="stu-overview-course-list">
                      {kurse.map((k) => (
                        <option key={k.name || k} value={k.name || k} />
                      ))}
                    </datalist>
                  </div>

                  <div className="stu-form-group">
                    <label>Datei auswählen *</label>
                    <input
                      key={fileInputKey}
                      type="file"
                      className="stu-file-input"
                      accept=".pdf,.pptx,.docx,.xlsx"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                      required
                    />
                  </div>

                  <button
                    type="submit"
                    className="stu-tbtn is-pri"
                    disabled={uploadBusy}
                    style={{ justifySelf: "start", padding: "6px 14px" }}
                  >
                    {uploadBusy ? "Wird hochgeladen …" : "Hochladen"}
                  </button>

                  {uploadMsg && (
                    <div className={`stu-upload-msg ${uploadMsg.ok ? "is-ok" : "is-err"}`}>
                      {uploadMsg.text}
                    </div>
                  )}

                  <span className="stu-muted" style={{ fontSize: "11px", lineHeight: 1.4 }}>
                    Unterstützt PDF, PPTX, DOCX oder XLSX bis max. 50 MB.
                  </span>
                </form>
              </section>

              {/* Kursliste */}
              <section className="stu-panel">
                <div className="stu-panel-head">
                  <h3>Kurse & Material</h3>
                  <span className="stu-col-count">{kurse.length}</span>
                </div>

                {kurseLoading && !kurseRes ? (
                  <div style={{ padding: "24px", display: "grid", placeItems: "center" }}>
                    <Loading text="Kurse werden geladen …" />
                  </div>
                ) : kurse.length === 0 ? (
                  <div className="stu-empty-box">
                    <span>Kein Kursmaterial unter lernen/ gefunden.</span>
                  </div>
                ) : (
                  <ul className="stu-list">
                    {kurse.map((k) => {
                      const courseName = k.name || k;
                      const sectionsCount = k.sections ? k.sections.length : 0;
                      const hasActions = k.begriffe || k.pruefung || k.projekt;

                      return (
                        <li
                          key={courseName}
                          className="stu-course-row stu-row--click"
                          onClick={() => {
                            setCourse(courseName);
                            setView("modul");
                            toast(`Modulübersicht: ${courseName}`);
                          }}
                        >
                          <div className="stu-course-main">
                            <span
                              className="stu-cdot"
                              style={{ background: `hsl(${courseHue(courseName)} 65% 50%)` }}
                            />

                            <div className="stu-course-info">
                              <strong className="stu-course-name" title={courseName}>
                                {courseName}
                              </strong>
                              <span className="stu-row-sub">
                                {sectionsCount} {sectionsCount === 1 ? "Abschnitt" : "Abschnitte"}
                              </span>
                            </div>
                          </div>

                          <div className="stu-course-actions">
                            <button
                              type="button"
                              className="stu-tbtn stu-course-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                setCourse(courseName);
                                setView("modul");
                              }}
                              title="Modulübersicht öffnen"
                            >
                              Modul
                            </button>
                            {k.begriffe && (
                              <button
                                type="button"
                                className="stu-tbtn stu-course-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openFile("lernen", `${courseName}/begriffe.md`);
                                }}
                                title="Begriffe öffnen"
                              >
                                Begriffe
                              </button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default Overview;
