// StudiumView.jsx: modulübergreifende Dokumente (z. B. Prüfungsplan) und Import der eigenen Prüfungen
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import "../plan/plan.css";
import "../modul/module.css";

const { useState, useEffect, useCallback, useMemo } = React;
const BASE = "/api/plugins/studium/";

function groesse(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function tagText(iso) {
  const [j, m, t] = iso.split("-").map(Number);
  return new Date(j, m - 1, t).toLocaleDateString("de-CH", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
}

function PruefungsImport({ datei, onFertig, onSchliessen }) {
  const { api, toast } = useStudio();
  const [plan, setPlan] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [gang, setGang] = useState("");
  const [suche, setSuche] = useState("");
  const [auswahl, setAuswahl] = useState({}); // index → Modul
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPlan(null);
    setFehler(null);
    api(`pruefungsplan?datei=${encodeURIComponent(datei)}`)
      .then((d) => {
        setPlan(d);
        setGang(d.studiengang || "");
        const vor = {};
        d.pruefungen.forEach((p) => { if (p.vorschlag && !p.vorhanden) vor[p.index] = p.vorschlag; });
        setAuswahl(vor);
      })
      .catch((e) => setFehler(e.message || "Der Plan liess sich nicht lesen."));
  }, [api, datei]);

  const sichtbar = useMemo(() => {
    if (!plan) return [];
    const q = suche.trim().toLowerCase();
    return plan.pruefungen.filter((p) =>
      (p.index in auswahl) ||
      ((!gang || p.studiengang === gang) &&
        (!q || `${p.modul} ${p.dozierende} ${p.klasse}`.toLowerCase().includes(q)))
    );
  }, [plan, gang, suche, auswahl]);
  // Vorschläge (zu deinen Modulen passend) zuoberst, sonst nach Datum wie im Plan
  const sortiert = useMemo(
    () => [...sichtbar].sort((a, b) => Number(!a.vorschlag) - Number(!b.vorschlag) || a.index - b.index),
    [sichtbar]
  );

  if (fehler) {
    return (
      <div className="stu-error-box">
        <span>{fehler}</span>
        <button type="button" className="stu-tbtn" onClick={onSchliessen}>Schliessen</button>
      </div>
    );
  }
  if (!plan) return <Loading text="Prüfungsplan wird gelesen …" />;

  const umschalten = (p) =>
    setAuswahl((a) => {
      const n = { ...a };
      if (p.index in n) delete n[p.index];
      else n[p.index] = p.vorschlag || plan.module[0] || plan.ohne_modul;
      return n;
    });
  const anzahl = Object.keys(auswahl).length;

  const importieren = async () => {
    setBusy(true);
    try {
      const eintraege = Object.entries(auswahl).map(([index, modul]) => ({ index: Number(index), modul }));
      const d = await api("pruefungsplan/import", { method: "POST", body: { datei, eintraege } });
      toast(d.neu.length ? `${d.neu.length} Prüfung${d.neu.length === 1 ? "" : "en"} im Kalender eingetragen` : "Alles war schon eingetragen");
      onFertig();
    } catch (err) {
      setFehler(err.message || "Import fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="stu-panel" aria-label="Prüfungen übernehmen">
      <div className="stu-panel-head">
        <h3>Prüfungen aus «{plan.datei}» übernehmen</h3>
        <button type="button" className="stu-tbtn" onClick={onSchliessen}>Schliessen</button>
      </div>
      <p className="st-text">
        Der Plan enthält {plan.pruefungen.length} Prüfungen aller Studiengänge. Vorausgewählt sind die, die zu deinen
        Modulen passen. Haken setzen, Modul wählen, übernehmen: Sie erscheinen im Kalender, im Modul und im Briefing.
      </p>
      <div className="st-filter">
        <label htmlFor="st-gang">
          Studiengang
          <select id="st-gang" value={gang} onChange={(e) => setGang(e.target.value)}>
            <option value="">alle</option>
            {plan.studiengaenge.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label htmlFor="st-suche" className="mu-sr">Prüfungen durchsuchen</label>
        <input id="st-suche" type="search" placeholder="Modul, Dozierende, Klasse …" value={suche}
          onChange={(e) => setSuche(e.target.value)} />
      </div>
      <div className="st-tabelle-wrap">
        <table className="st-tabelle">
          <thead>
            <tr>
              <th scope="col"><span className="mu-sr">Auswählen</span></th>
              <th scope="col">Datum</th>
              <th scope="col">Zeit</th>
              <th scope="col">Prüfung</th>
              <th scope="col">In Modul</th>
            </tr>
          </thead>
          <tbody>
            {sortiert.length === 0 ? (
              <tr><td colSpan={5} className="st-text">Keine Prüfungen für diesen Filter.</td></tr>
            ) : sortiert.map((p) => {
              const an = p.index in auswahl;
              const id = `st-p-${p.index}`;
              return (
                <tr key={p.index} className={an ? "is-gewaehlt" : ""}>
                  <td>
                    <input id={id} type="checkbox" checked={an} disabled={p.vorhanden} onChange={() => umschalten(p)}
                      aria-label={`${p.modul} am ${tagText(p.datum)} übernehmen`} />
                  </td>
                  <td className="st-nowrap">{tagText(p.datum)}</td>
                  <td className="st-nowrap">
                    {p.von && p.bis ? `${p.von}–${p.bis}` : "–"}
                    {p.dauer ? <span className="st-sub">{p.dauer} Min.</span> : null}
                  </td>
                  <td className="st-modul">
                    <label htmlFor={id}>{p.modul}</label>
                    <span className="st-sub">{[p.studiengang, p.klasse, p.dozierende].filter(Boolean).join(" · ")}</span>
                  </td>
                  <td>
                    {p.vorhanden ? (
                      <span className="st-chip">schon im Kalender</span>
                    ) : (
                      <select value={auswahl[p.index] || p.vorschlag || ""} disabled={!an}
                        aria-label={`Modul für ${p.modul}`}
                        onChange={(e) => setAuswahl((a) => ({ ...a, [p.index]: e.target.value }))}>
                        {!an && !p.vorschlag ? <option value="">–</option> : null}
                        {plan.module.map((m) => <option key={m} value={m}>{m}</option>)}
                        <option value={plan.ohne_modul}>Studium (ohne Modul)</option>
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="st-aktionen">
        <span className="st-zaehler">{anzahl} ausgewählt</span>
        <button type="button" className="stu-tbtn is-pri" disabled={!anzahl || busy} onClick={importieren}>
          {busy ? "Trägt ein …" : `${anzahl || ""} Prüfung${anzahl === 1 ? "" : "en"} übernehmen`.trim()}
        </button>
      </div>
    </section>
  );
}

export function StudiumView() {
  const { api, toast, setView } = useStudio();
  const [dateien, setDateien] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [laedt, setLaedt] = useState(false);
  const [importDatei, setImportDatei] = useState("");

  const laden = useCallback(() => {
    api("studium").then((d) => setDateien(d.dateien || [])).catch((e) => setFehler(e.message));
  }, [api]);
  useEffect(laden, [laden]);

  const hochladen = async (e) => {
    const liste = Array.from(e.target.files || []);
    e.target.value = "";
    if (!liste.length) return;
    setLaedt(true);
    let letzte = "";
    for (const f of liste) {
      const fd = new FormData();
      fd.append("file", f);
      try {
        const d = await api("studium/upload", { method: "POST", body: fd });
        letzte = d.name;
        toast(`${d.name} hochgeladen`);
      } catch (err) {
        toast(`${f.name}: ${err.message}`);
      }
    }
    setLaedt(false);
    laden();
    if (letzte.toLowerCase().endsWith(".xlsx") && /pr[uü]f/i.test(letzte)) setImportDatei(letzte);
  };

  const entfernen = async (name) => {
    if (!window.confirm(`«${name}» entfernen? Die Datei kommt in den Papierkorb (data/studium/.papierkorb).`)) return;
    try {
      await api(`studium/datei?name=${encodeURIComponent(name)}`, { method: "DELETE" });
      if (importDatei === name) setImportDatei("");
      laden();
    } catch (err) {
      toast(`Nicht entfernt: ${err.message}`);
    }
  };

  return (
    <div className="st">
      <header className="stu-viewh">
        <h2>Studium</h2>
        <span className="stu-viewh-desc">Was für alle Module gilt: Prüfungsplan, Reglemente, Stundenplan</span>
        <div className="stu-grow" />
        <label className="st-upload" htmlFor="st-datei">
          <input id="st-datei" type="file" multiple accept=".pdf,.docx,.xlsx,.pptx,.csv,.md,.txt" onChange={hochladen} />
          <span className="stu-tbtn is-pri" aria-hidden="true">{laedt ? "Lädt hoch …" : "Dokument hochladen"}</span>
        </label>
      </header>
      <div className="st-body">
        <div className="st-raster">
          {importDatei ? (
            <PruefungsImport
              datei={importDatei}
              onSchliessen={() => setImportDatei("")}
              onFertig={() => setImportDatei("")}
            />
          ) : null}
          <section className="stu-panel">
            <div className="stu-panel-head">
              <h3>Dokumente</h3>
              {dateien ? <span className="stu-col-count">{dateien.length}</span> : null}
            </div>
            {fehler ? (
              <div className="stu-error-box"><span>{fehler}</span></div>
            ) : !dateien ? (
              <Loading text="Dokumente werden geladen …" />
            ) : dateien.length === 0 ? (
              <div className="stu-empty-box">
                <span>Noch nichts abgelegt. Lade zum Beispiel den Prüfungsplan der Hochschule (Excel) hoch.</span>
              </div>
            ) : (
              <ul className="st-dateien">
                {dateien.map((d) => (
                  <li key={d.name} className="st-datei">
                    <span className="st-endung">{d.endung}</span>
                    <span className="st-datei-name">
                      <a href={`${BASE}studium/datei?name=${encodeURIComponent(d.name)}`} target="_blank" rel="noreferrer">{d.name}</a>
                      <span className="st-datei-sub">
                        {groesse(d.groesse)} · {new Date(d.geaendert).toLocaleDateString("de-CH")}
                      </span>
                    </span>
                    {d.endung === "xlsx" ? (
                      <button type="button" className="stu-tbtn" onClick={() => setImportDatei(d.name)}>
                        Prüfungen übernehmen
                      </button>
                    ) : null}
                    <button type="button" className="stu-tbtn" onClick={() => entfernen(d.name)}
                      aria-label={`${d.name} entfernen`}>Entfernen</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <p className="st-text">
            Übernommene Prüfungen findest du im <button type="button" className="stu-tbtn" onClick={() => setView("calendar")}>Kalender</button>
            {" "}und auf der Karte des Moduls.
          </p>
        </div>
      </div>
    </div>
  );
}

export default StudiumView;
