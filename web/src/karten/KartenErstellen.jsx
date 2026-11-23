// KartenErstellen.jsx: Dokumente eines Moduls wählen, der Agent erstellt daraus Karteikarten
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";

const { useState, useEffect, useRef, useCallback } = React;

const ANZAHLEN = [5, 10, 15, 20];

export function KartenErstellen({ course, onFertig, onSchliessen }) {
  const { api, toast } = useStudio();
  const [doks, setDoks] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [wahl, setWahl] = useState(new Set());
  const [anzahl, setAnzahl] = useState(10);
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  const fertigRef = useRef(onFertig);
  fertigRef.current = onFertig;

  const abfragen = useCallback(async () => {
    try {
      const j = await api("karten/erstellen");
      setJob(j);
      if (j.status === "läuft") {
        timer.current = setTimeout(abfragen, 2000);
      } else if (j.status === "fertig" || j.status === "fehler") {
        const text = j.neu
          ? `${j.neu} neue Karteikarten erstellt`
          : "Keine neuen Karten (alles schon vorhanden oder nichts Passendes gefunden)";
        toast(j.fehler?.length ? `${text}. Probleme bei ${j.fehler.length} Dokument(en).` : text, 5000);
        fertigRef.current?.(j);
      }
    } catch {
      /* Status nicht erreichbar */
    }
  }, [api, toast]);

  useEffect(() => {
    setDoks(null);
    api(`karten/dokumente?course=${encodeURIComponent(course)}`)
      .then((d) => {
        setDoks(d.dokumente);
        // Vorauswahl: Lernstoff, aus dem noch keine Karten entstanden sind
        setWahl(new Set(d.dokumente.filter((x) => x.lernstoff && !x.karten).map((x) => x.rel)));
        if (d.job?.status === "läuft") { setJob(d.job); timer.current = setTimeout(abfragen, 1000); }
      })
      .catch((e) => setFehler(e.message || "Dokumente konnten nicht geladen werden."));
    return () => clearTimeout(timer.current);
  }, [api, course, abfragen]);

  const umschalten = (rel) => setWahl((w) => {
    const n = new Set(w);
    if (n.has(rel)) n.delete(rel); else n.add(rel);
    return n;
  });

  const starten = async () => {
    try {
      const j = await api("karten/erstellen", { method: "POST", body: { course, rels: [...wahl], anzahl } });
      setJob(j);
      clearTimeout(timer.current);
      timer.current = setTimeout(abfragen, 1500);
    } catch (err) {
      toast(err.message || "Konnte nicht starten.");
    }
  };

  const laeuft = job?.status === "läuft";
  const gruppen = [];
  for (const d of doks || []) {
    const g = gruppen[gruppen.length - 1];
    if (g && g.name === d.abschnitt) g.doks.push(d);
    else gruppen.push({ name: d.abschnitt, doks: [d] });
  }

  return (
    <section className="ke" aria-labelledby="ke-titel">
      <div className="ke-kopf">
        <h2 id="ke-titel">Karteikarten erstellen</h2>
        <button type="button" className="stu-tbtn" onClick={onSchliessen} disabled={laeuft}>Schliessen</button>
      </div>
      <p className="ke-text">
        Wähle die Dokumente, aus denen der Agent Karteikarten machen soll. Er liest die Folien-Notizen
        (inklusive Bildbeschreibungen) und schreibt pro Dokument Begriffe mit Definition und Folienangabe.
        Begriffe, die es schon gibt, bleiben unverändert, dein Lernstand geht nicht verloren.
      </p>

      {fehler ? (
        <div className="stu-error-box"><span>{fehler}</span></div>
      ) : !doks ? (
        <Loading text="Dokumente werden geladen …" />
      ) : doks.length === 0 ? (
        <p className="stu-muted">
          Noch keine durchsuchbaren Dokumente in diesem Modul. Hol sie mit «Moodle aktualisieren» unter Module.
        </p>
      ) : laeuft ? (
        <div className="ke-lauf" role="status" aria-live="polite">
          <div className="ke-balken" aria-hidden="true">
            <span style={{ width: `${Math.round((100 * (job.index || 0)) / Math.max(1, job.total))}%` }} />
          </div>
          <span>Dokument {Math.min((job.index || 0) + 1, job.total)} von {job.total}: {job.datei || "…"}</span>
          <span className="stu-muted">Pro Dokument etwa 20 bis 40 Sekunden. Du kannst weiterarbeiten.</span>
        </div>
      ) : (
        <>
          <div className="ke-schnell">
            <button type="button" className="stu-tbtn" onClick={() => setWahl(new Set(doks.filter((d) => d.lernstoff).map((d) => d.rel)))}>
              Alle Folien
            </button>
            <button type="button" className="stu-tbtn" onClick={() => setWahl(new Set(doks.map((d) => d.rel)))}>Alle</button>
            <button type="button" className="stu-tbtn" onClick={() => setWahl(new Set())}>Keine</button>
          </div>
          <div className="ke-liste">
            {gruppen.map((g) => (
              <fieldset key={g.name} className="ke-gruppe">
                <legend>{g.name}</legend>
                {g.doks.map((d) => {
                  const id = "ke-" + d.rel.replace(/[^a-zA-Z0-9]/g, "").slice(-50);
                  return (
                    <label key={d.rel} htmlFor={id} className="ke-dok">
                      <input id={id} type="checkbox" checked={wahl.has(d.rel)} onChange={() => umschalten(d.rel)} />
                      <span className="ke-dok-name">{d.titel}</span>
                      <span className="ke-dok-meta">
                        {d.klasse || "Dokument"}{d.karten ? ` · ${d.karten} Karten vorhanden` : ""}
                      </span>
                    </label>
                  );
                })}
              </fieldset>
            ))}
          </div>
          <div className="ke-fuss">
            <label className="ke-anzahl">
              Karten pro Dokument
              <select value={anzahl} onChange={(e) => setAnzahl(Number(e.target.value))}>
                {ANZAHLEN.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <button type="button" className="stu-tbtn is-pri" disabled={wahl.size === 0} onClick={starten}>
              {wahl.size === 0
                ? "Dokumente wählen"
                : `Aus ${wahl.size} ${wahl.size === 1 ? "Dokument" : "Dokumenten"} erstellen`}
            </button>
          </div>
          {job?.status === "fertig" && job.fehler?.length ? (
            <ul className="ke-fehler">{job.fehler.map((f, i) => <li key={i}>{f}</li>)}</ul>
          ) : null}
        </>
      )}
    </section>
  );
}

export default KartenErstellen;
