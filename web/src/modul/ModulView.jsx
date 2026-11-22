// ModulView.jsx: Moduluebersicht als Kurs-Startseite (T8)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Loading } from "../ui/Loading.jsx";
import { QuellenKarte } from "./QuellenKarte.jsx";
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

const ART_TEXT = { pruefung: "Prüfung", abgabe: "Abgabe", praesentation: "Präsentation", modul: "Leistungsnachweis" };

function datumLang(iso) {
  const [j, m, t] = iso.split("-").map(Number);
  return new Date(j, m - 1, t).toLocaleDateString("de-CH", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

// Prüfung, Abgaben und Präsentationen, pro Tag zusammengefasst; vergangene ausgegraut
function WichtigeDaten({ daten }) {
  if (!daten.length) {
    return <span className="stu-muted">Noch keine Prüfungs-, Abgabe- oder Präsentationsdaten bekannt.</span>;
  }
  const tage = [];
  for (const d of daten) {
    const letzter = tage[tage.length - 1];
    if (letzter && letzter.datum === d.datum) letzter.eintraege.push(d);
    else tage.push({ datum: d.datum, vergangen: d.vergangen, eintraege: [d] });
  }
  return (
    <ul className="mv-daten">
      {tage.map((t) => (
        <li key={t.datum} className={t.vergangen ? "is-vergangen" : ""}>
          <span className="mv-daten-tag">{datumLang(t.datum)}</span>
          <span className="mv-daten-texte">
            {t.eintraege.map((e, i) => (
              <span key={i} className="mv-daten-eintrag">
                <span className={"mv-art is-" + e.art}>{ART_TEXT[e.art] || e.art}</span> {e.text}
              </span>
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}

// «Datei, Folie 3» … → [[Datei, ["Folie 3", …]], …]
function quellenNachDatei(quellen) {
  const map = new Map();
  for (const q of quellen) {
    const m = String(q).match(/^(.*?),\s*((?:Seite|Seiten|Folie|Folien)\b.*)$/);
    const datei = (m ? m[1] : String(q)).trim();
    if (!map.has(datei)) map.set(datei, []);
    if (m && !map.get(datei).includes(m[2])) map.get(datei).push(m[2]);
  }
  return [...map.entries()];
}

export function ModulView({ course: courseProp, onBack }) {
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
          {onBack ? (
            <button type="button" className="stu-tbtn mu-zurueck" onClick={onBack}>← Alle Module</button>
          ) : null}
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

            <div className="stu-modul-field stu-modul-field--block">
              <span className="stu-modul-label">Wichtige Daten:</span>
              <WichtigeDaten daten={data.wichtige_daten || []} />
            </div>

            {ln.quellen && ln.quellen.length > 0 && (
              <details className="mv-quellen">
                <summary>Woher diese Angaben stammen ({quellenNachDatei(ln.quellen).length} Dokumente)</summary>
                <ul>
                  {quellenNachDatei(ln.quellen).map(([datei, stellen]) => (
                    <li key={datei}>
                      <span className="mv-quelle-datei">{datei}</span>
                      {stellen.length ? <span className="stu-muted"> · {stellen.join(", ")}</span> : null}
                    </li>
                  ))}
                </ul>
              </details>
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

      {/* Quellen des Agenten, nach Moodle-Abschnitt */}
      <QuellenKarte course={data.course} />

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
