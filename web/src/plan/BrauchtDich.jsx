// BrauchtDich.jsx: alles, was auf eine Entscheidung wartet (Freigaben, Dateien mit unklarer Klasse)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { FreigabeCard } from "../chat/ChatPanel.jsx";
import { courseShort } from "./utils.js";

const { useState, useEffect, useCallback } = React;

// Was der Agent mit einer Datei tut, in Worten statt Klassennamen
const KLASSEN_LABEL = {
  folien: "Lernstoff: zusammenfassen und Folien-Notizen schreiben",
  semesterprogramm: "Semesterprogramm: Termine in den Kalender übernehmen",
  projekt: "Leistungsnachweis oder Projekt: Anforderungen ins Modul übernehmen",
  uebung: "Übung: nur durchsuchbar",
  loesung: "Lösung: nur durchsuchbar",
  literatur: "Literatur: nur durchsuchbar",
  ueberspringen: "Unwichtig: nicht zusammenfassen, bleibt durchsuchbar",
};
const NICHT_NUTZEN = "__nicht_nutzen";

function Vorschau({ p }) {
  const { api, openFile } = useStudio();
  const [text, setText] = useState(null);
  const [fehler, setFehler] = useState(null);
  useEffect(() => {
    api(`quellen/vorschau?rel=${encodeURIComponent(p.rel)}`)
      .then((d) => setText(d.text + (d.gekuerzt ? "\n…" : "")))
      .catch(() => setFehler("Kein ausgelesener Text vorhanden."));
  }, [api, p.rel]);
  return (
    <div className="bd-vorschau">
      {fehler ? (
        <span className="stu-row-sub">{fehler}</span>
      ) : text === null ? (
        <span className="stu-row-sub">Text wird geladen …</span>
      ) : (
        <pre className="bd-vorschau-text">
          {text || "(leer: die Datei enthält keinen Text)"}
        </pre>
      )}
      <button type="button" className="stu-tbtn" onClick={() => openFile("moodle", p.rel)}>Original öffnen</button>
    </div>
  );
}

function UnklareDatei({ p, klassen, onDone }) {
  const { api, toast } = useStudio();
  const [klasse, setKlasse] = useState("");
  const [offen, setOffen] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = "bd-" + p.rel.replace(/[^a-zA-Z0-9]/g, "").slice(-40);

  const uebernehmen = async () => {
    setBusy(true);
    try {
      if (klasse === NICHT_NUTZEN) {
        await api("quellen/nutzen", { method: "PUT", body: { rels: [p.rel], nutzen: false, kurs: p.course } });
        toast(`${p.name}: wird nicht genutzt (im Modul unter «Dokumente und Quellen» wieder anhakbar)`);
      } else {
        await api("klasse", { method: "POST", body: { rel: p.rel, klasse } });
        toast(`${p.name}: ${KLASSEN_LABEL[klasse] || klasse}`);
      }
      onDone();
    } catch (err) {
      toast(`Nicht gespeichert: ${err.message}`);
      setBusy(false);
    }
  };

  return (
    <li className="stu-row bd-row">
      <div className="stu-row-grow">
        <button type="button" className="bd-name" aria-expanded={offen} onClick={() => setOffen((o) => !o)} title={p.rel}>
          <span aria-hidden="true">{offen ? "▾" : "▸"}</span> {p.name}
        </button>
        <span className="stu-row-sub">{courseShort(p.course)}{p.section ? ` · ${p.section}` : ""}</span>
      </div>
      <label className="bd-sr" htmlFor={id}>Was soll der Agent mit {p.name} tun?</label>
      <select id={id} value={klasse} disabled={busy} onChange={(e) => setKlasse(e.target.value)}>
        <option value="" disabled>Was ist das?</option>
        {klassen.map((k) => (
          <option key={k} value={k}>{KLASSEN_LABEL[k] || k}</option>
        ))}
        <option value={NICHT_NUTZEN}>Gar nicht nutzen: aus Suche und Chat entfernen</option>
      </select>
      <button type="button" className="stu-tbtn is-pri" disabled={busy || !klasse} onClick={uebernehmen}>
        Übernehmen
      </button>
      {offen ? <Vorschau p={p} /> : null}
    </li>
  );
}

export function BrauchtDich({ unklar, onChange }) {
  const { api } = useStudio();
  const [freigaben, setFreigaben] = useState([]);
  const [klassen, setKlassen] = useState(Object.keys(KLASSEN_LABEL));

  const ladeFreigaben = useCallback(() => {
    api("freigaben").then((d) => setFreigaben(d.freigaben || [])).catch(() => {});
  }, [api]);

  useEffect(() => {
    ladeFreigaben();
    api("klassen").then((d) => d.klassen?.length && setKlassen(d.klassen)).catch(() => {});
  }, [api, ladeFreigaben]);

  const anzahl = freigaben.length + unklar.length;

  return (
    <section className={"stu-panel bd" + (anzahl ? " has-items" : "")} aria-label="Braucht dich">
      <div className="stu-panel-head">
        <h3>Braucht dich</h3>
        <span className="stu-col-count">{anzahl}</span>
      </div>
      {anzahl === 0 ? (
        <div className="stu-empty-box"><span>Nichts offen. Der Agent kommt ohne dich weiter.</span></div>
      ) : (
        <>
          {freigaben.length > 0 && (
            <div className="bd-group">
              <span className="bd-label">Freigaben: Der Prüfer hat Einwände, du entscheidest</span>
              {freigaben.map((f) => (
                <FreigabeCard key={f.thread_id} f={f} onDone={() => setTimeout(() => { ladeFreigaben(); onChange(); }, 8000)} />
              ))}
            </div>
          )}
          {unklar.length > 0 && (
            <div className="bd-group">
              <span className="bd-label">Unklare Dateien: Was soll der Agent damit tun?</span>
              <p className="bd-erklaerung">
                Bei diesen Dateien konnte der Agent nicht erkennen, ob es Lernstoff, Termine oder etwas Unwichtiges ist.
                Bis du entscheidest, sind sie durchsuchbar, werden aber nicht zusammengefasst. Klick auf den Namen, um
                den Inhalt anzusehen.
              </p>
              <ul className="stu-list">
                {unklar.map((p) => (
                  <UnklareDatei key={p.rel} p={p} klassen={klassen} onDone={onChange} />
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default BrauchtDich;
