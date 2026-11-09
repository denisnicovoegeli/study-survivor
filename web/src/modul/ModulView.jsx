// ModulView.jsx: Moduluebersicht als Kurs-Startseite (T8)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Loading } from "../ui/Loading.jsx";
import "./modul.css";

const { useState, useEffect, useCallback } = React;

// Datum (und Uhrzeit, ausser ganztaegig) in Zuercher Zeit. due kommt als UTC
// ("2027-01-10 22:59:00+00:00" = ganztaegig 10.01.), nie den Text roh anzeigen.
function formatEventDate(ev) {
  const raw = ev.due || ev.date || ev.datum;
  if (!raw) return "";
  const str = String(raw).trim();
  const dOnly = str.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dOnly) return `${dOnly[3]}.${dOnly[2]}.`;
  const d = new Date(str.replace(" ", "T"));
  if (isNaN(d.getTime())) return str.slice(0, 10);
  const opts = { timeZone: "Europe/Zurich" };
  const day = d.toLocaleDateString("de-CH", { ...opts, day: "2-digit", month: "2-digit" });
  const allDay = ev.all_day === true || ev.all_day === "true";
  const time = allDay ? "" : ` ${d.toLocaleTimeString("de-CH", { ...opts, hour: "2-digit", minute: "2-digit" })}`;
  return `${day}${time}`;
}

export function ModulView({ course: courseProp }) {
  const { api, course: activeCourse, setCourse, courses, toast } = useStudio();
  const currentCourse = courseProp || activeCourse || (courses[0]?.name || courses[0] || "");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  const loadModul = useCallback(async () => {
    if (!currentCourse) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api(`kurs/${encodeURIComponent(currentCourse)}/modul`);
      setData(res);
    } catch (err) {
      setError(err?.message || "Fehler beim Laden der Moduldaten");
    } finally {
      setLoading(false);
    }
  }, [api, currentCourse]);

  useEffect(() => {
    loadModul();
  }, [loadModul]);

  if (loading) {
    return (
      <div className="stu-modul-container">
        <Loading text="Modulübersicht wird geladen …" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="stu-modul-container">
        <div className="stu-modul-hint" style={{ background: "var(--acc-soft)", borderColor: "var(--line)", color: "var(--fg)" }}>
          <Icon n="x" />
          <span>{error || "Keine Moduldaten verfügbar"}</span>
        </div>
      </div>
    );
  }

  const ln = data.leistungsnachweis || {};
  const termine = data.termine || [];
  const fortschritt = data.fortschritt || { wochen: [], gesamt: { verarbeitet: 0, offen: 0, total: 0, prozent: 100 } };
  const noten = data.noten;
  const pruefung = data.pruefung || {};
  const projekt = data.projekt || {};

  const artLabel = {
    pruefung: "Prüfung",
    projekt: "Projekt",
    beides: "Prüfung & Projekt",
  }[ln.art] || ln.art || "Nicht spezifiziert";

  const badgeClass = `stu-modul-badge is-${ln.art || "default"}`;

  return (
    <div className="stu-modul-container">
      {/* Header mit Kursauswahl falls mehrere vorhanden */}
      <div className="stu-modul-header">
        <div>
          <h1 className="stu-modul-title">{data.course}</h1>
          <span className="stu-muted" style={{ fontSize: "13px" }}>
            Modul-Cockpit und Leistungsnachweis
          </span>
        </div>

        {courses && courses.length > 1 && (
          <select
            className="stu-course"
            value={currentCourse}
            onChange={(e) => setCourse && setCourse(e.target.value)}
            aria-label="Kurs wechseln"
          >
            {courses.map((k) => {
              const name = typeof k === "string" ? k : k?.name;
              return (
                <option key={name} value={name}>
                  {name}
                </option>
              );
            })}
          </select>
        )}
      </div>

      {/* Hinweis falls modul.md noch fehlt */}
      {data.hinweis && (
        <div className="stu-modul-hint">
          <Icon n="split" />
          <div>
            <strong>Hinweis:</strong> {data.hinweis}. Es werden die vorhandenen Informationen aus den bisherigen Kursunterlagen angezeigt.
          </div>
        </div>
      )}

      {/* Obere Kacheln: Leistungsnachweis & Noten / Termine */}
      <div className="stu-modul-grid">
        {/* Leistungsnachweis */}
        <div className="stu-modul-card">
          <h2 className="stu-modul-card-title">
            <Icon n="doc" />
            <span>Leistungsnachweis</span>
          </h2>

          <div className="stu-modul-fields">
            <div className="stu-modul-field">
              <span className="stu-modul-label">Art:</span>
              <span className={badgeClass}>{artLabel}</span>
            </div>

            {ln.gewichtung && (
              <div className="stu-modul-field">
                <span className="stu-modul-label">Gewichtung:</span>
                <span className="stu-modul-val">{ln.gewichtung}</span>
              </div>
            )}

            {ln.dauer && (
              <div className="stu-modul-field">
                <span className="stu-modul-label">Dauer:</span>
                <span className="stu-modul-val">{ln.dauer}</span>
              </div>
            )}

            {ln.hilfsmittel && (
              <div className="stu-modul-field">
                <span className="stu-modul-label">Hilfsmittel:</span>
                <span className="stu-modul-val">{ln.hilfsmittel}</span>
              </div>
            )}

            {ln.daten && ln.daten.length > 0 && (
              <div className="stu-modul-field stu-modul-field--block">
                <span className="stu-modul-label">Prüfungsdaten:</span>
                <ul className="stu-modul-daten-list">
                  {ln.daten.map((dItem, dIdx) => {
                    const m = String(dItem).match(/^(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})\s*[:–-]?\s*(.*)$/);
                    if (m) {
                      return (
                        <li key={dIdx} className="stu-modul-daten-item">
                          <span className="stu-modul-daten-date">{m[1]}</span>
                          <span className="stu-modul-daten-text">{m[2]}</span>
                        </li>
                      );
                    }
                    return (
                      <li key={dIdx} className="stu-modul-daten-item">
                        <span className="stu-modul-daten-text">{dItem}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {ln.quellen && ln.quellen.length > 0 && (
              <div className="stu-modul-field">
                <span className="stu-modul-label">Quellen:</span>
                <span className="stu-muted" style={{ fontSize: "12.5px", textAlign: "left" }}>
                  {ln.quellen.join("; ")}
                </span>
              </div>
            )}

            {/* Notenbox falls vorhanden */}
            {noten && (
              <div
                style={{
                  marginTop: "8px",
                  padding: "10px",
                  borderRadius: "8px",
                  background: "var(--raise)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span style={{ fontWeight: 600 }}>Note:</span>
                <span style={{ fontSize: "16px", fontWeight: 700, color: "var(--acc)" }}>
                  {noten.grade || noten.raw_grade || "–"}
                  {noten.rank ? ` (Rang ${noten.rank})` : ""}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Anstehende Termine */}
        <div className="stu-modul-card">
          <h2 className="stu-modul-card-title">
            <Icon n="cal" />
            <span>Anstehende Termine ({termine.length})</span>
          </h2>

          {termine.length === 0 ? (
            <p className="stu-muted" style={{ fontSize: "13.5px" }}>
              Keine anstehenden Termine für dieses Modul eingetragen.
            </p>
          ) : (
            <ul className="stu-modul-events">
              {termine.slice(0, 5).map((ev, i) => {
                const dateStr = formatEventDate(ev);
                const rawKind = (ev.kind || ev.art || "termin").toLowerCase();
                const isAbgabe = rawKind === "assign" || rawKind === "abgabe";
                const displayKind = isAbgabe ? "Abgabe" : rawKind === "pruefung" ? "Prüfung" : (ev.kind || ev.art || "Termin");
                const badgeKindClass = isAbgabe ? "abgabe" : rawKind;

                return (
                  <li key={i} className="stu-modul-event">
                    {dateStr && (
                      <span className="stu-modul-event-date">{dateStr}</span>
                    )}
                    <span className="stu-modul-event-title">{ev.name || ev.titel}</span>
                    <span className={`stu-modul-badge is-${badgeKindClass}`}>
                      {displayKind}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Fortschritt pro Woche */}
      <div className="stu-modul-card" style={{ marginBottom: "24px" }}>
        <h2 className="stu-modul-card-title">
          <Icon n="board" />
          <span>
            Verarbeitungsfortschritt ({fortschritt.gesamt.verarbeitet} von {fortschritt.gesamt.total} verarbeitet, {fortschritt.gesamt.prozent}%)
          </span>
        </h2>

        <div className="stu-modul-progress-bar">
          <div
            className="stu-modul-progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, fortschritt.gesamt.prozent))}%` }}
          />
        </div>

        {fortschritt.wochen && fortschritt.wochen.length > 0 ? (
          <div className="stu-modul-weeks">
            {fortschritt.wochen.map((w, idx) => (
              <div key={idx} className="stu-modul-week-row">
                <span className="stu-modul-week-tag">{w.week_label}</span>
                <span className="stu-muted" style={{ flex: 1, margin: "0 12px" }}>
                  {w.section !== w.week_label ? w.section : ""}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span className="stu-modul-week-counts">
                    {w.verarbeitet} verarbeitet / {w.offen} offen
                  </span>
                  <span
                    className={`stu-modul-badge ${w.offen === 0 && w.verarbeitet > 0 ? "is-pruefung" : ""}`}
                    style={{ minWidth: "42px", textAlign: "center" }}
                  >
                    {w.prozent}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="stu-muted" style={{ fontSize: "13.5px" }}>
            Noch keine Wochenabschnitte erfasst.
          </p>
        )}
      </div>

      {/* Einklappbare Details: Prüfung & Projekt */}
      <details className="stu-modul-details" open>
        <summary className="stu-modul-summary">
          <span>Prüfungsdetails & Anforderungen</span>
          <span className="stu-muted" style={{ fontSize: "12px" }}>
            {Object.keys(pruefung).length} {Object.keys(pruefung).length === 1 ? "Quelle" : "Quellen"}
          </span>
        </summary>
        <div className="stu-modul-detail-body">
          {Object.keys(pruefung).length > 0 ? (
            Object.entries(pruefung).map(([fname, items]) => (
              <div key={fname} className="stu-modul-detail-file">
                <div className="stu-modul-detail-file-title">{fname}</div>
                <ul className="stu-modul-detail-list">
                  {items.map((it, idx) => (
                    <li key={idx}>{it}</li>
                  ))}
                </ul>
              </div>
            ))
          ) : data.legacy_pruefung ? (
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
              {data.legacy_pruefung}
            </pre>
          ) : (
            <p className="stu-muted">Keine Prüfungshinweise erfasst.</p>
          )}
        </div>
      </details>

      <details className="stu-modul-details" open>
        <summary className="stu-modul-summary">
          <span>Projektdetails & Richtlinien</span>
          <span className="stu-muted" style={{ fontSize: "12px" }}>
            {Object.keys(projekt).length} {Object.keys(projekt).length === 1 ? "Quelle" : "Quellen"}
          </span>
        </summary>
        <div className="stu-modul-detail-body">
          {Object.keys(projekt).length > 0 ? (
            Object.entries(projekt).map(([fname, items]) => (
              <div key={fname} className="stu-modul-detail-file">
                <div className="stu-modul-detail-file-title">{fname}</div>
                <ul className="stu-modul-detail-list">
                  {items.map((it, idx) => (
                    <li key={idx}>{it}</li>
                  ))}
                </ul>
              </div>
            ))
          ) : data.legacy_projekt ? (
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
              {data.legacy_projekt}
            </pre>
          ) : (
            <p className="stu-muted">Keine Projekthinweise erfasst.</p>
          )}
        </div>
      </details>
    </div>
  );
}

export default ModulView;
