// ModuleBereich.jsx: Übersicht aller Module (Moodle und eigene) und Einstieg ins Modul-Cockpit
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import { load, save } from "../ui/storage.js";
import { ModulView } from "./ModulView.jsx";
import { MoodleAktualisieren } from "./MoodleAktualisieren.jsx";
import { FarbWahl } from "./FarbWahl.jsx";
import "../plan/plan.css";
import "./module.css";

const { useState, useEffect, useCallback } = React;

function datumKurz(ev) {
  if (!ev?.due) return "";
  const d = new Date(String(ev.due).replace(" ", "T"));
  if (isNaN(d)) return "";
  const tag = d.toLocaleDateString("de-CH", { timeZone: "Europe/Zurich", weekday: "short", day: "numeric", month: "short" });
  if (ev.all_day) return tag;
  return `${tag}, ${d.toLocaleTimeString("de-CH", { timeZone: "Europe/Zurich", hour: "2-digit", minute: "2-digit" })}`;
}

const LN_TEXT = {
  pruefung: "Prüfung, Datum noch offen",
  projekt: "Projekt, keine Prüfung",
  beides: "Prüfung & Projekt, Datum noch offen",
};

function NeuesModul({ onAngelegt }) {
  const { api, toast } = useStudio();
  const [offen, setOffen] = useState(false);
  const [name, setName] = useState("");
  const [fehler, setFehler] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!offen) {
    return (
      <button type="button" className="stu-tbtn is-pri" onClick={() => setOffen(true)}>
        + Eigenes Modul
      </button>
    );
  }

  const anlegen = async (e) => {
    e.preventDefault();
    setBusy(true);
    setFehler(null);
    try {
      const d = await api("module", { method: "POST", body: { name } });
      toast(`Modul «${d.name}» angelegt`);
      setName("");
      setOffen(false);
      onAngelegt(d.name);
    } catch (err) {
      setFehler(err.message || "Anlegen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="mu-neu" onSubmit={anlegen}>
      <label htmlFor="mu-neu-name" className="mu-sr">Name des Moduls</label>
      <input
        id="mu-neu-name"
        autoFocus
        maxLength={80}
        value={name}
        placeholder="z. B. Statistik & Mathematik"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOffen(false)}
      />
      <button type="submit" className="stu-tbtn is-pri" disabled={busy || !name.trim()}>Anlegen</button>
      <button type="button" className="stu-tbtn" onClick={() => { setOffen(false); setFehler(null); }}>Abbrechen</button>
      {fehler ? <span className="mu-fehler" role="alert">{fehler}</span> : null}
    </form>
  );
}

function ModulKarte({ m, onOeffnen, onHochladen, onEntfernen }) {
  const f = m.fortschritt || { prozent: 100, total: 0, offen: 0 };
  const leer = m.quelle === "eigene" && f.total === 0 && m.dateien_eigene === 0;
  return (
    <li className={"stu-panel mu-karte" + (m.ignoriert ? " is-ignoriert" : "")}>
      <FarbWahl name={m.name} />
      <button type="button" className="mu-karte-haupt" onClick={onOeffnen}>
        <span className="mu-karte-kopf">
          <strong>{m.name}</strong>
          <span className={"mu-badge is-" + m.quelle}>{m.quelle === "eigene" ? "Eigenes Modul" : "Moodle"}</span>
        </span>
        {m.ignoriert ? <span className="mu-hinweis">Wird vom Agenten ignoriert (Agent → Einstellungen)</span> : null}
        {leer ? (
          <span className="mu-hinweis">Noch leer. Lade Folien oder Unterlagen hoch, der Agent verarbeitet sie beim nächsten Lauf.</span>
        ) : (
          <span className="mu-fortschritt">
            <span className="mu-balken" aria-hidden="true"><span style={{ width: `${f.prozent}%` }} /></span>
            <span>{f.total ? `${f.prozent}% aufbereitet` : "Noch nichts verarbeitet"}{f.offen ? `, ${f.offen} offen` : ""}</span>
          </span>
        )}
        <span className="mu-zeilen">
          <span className="mu-zeile">
            <span className="mu-label">Quellen</span>
            <span>{m.quellen ? `${m.quellen} ${m.quellen === 1 ? "Datei nutzt" : "Dateien nutzt"} der Agent` : "noch keine"}</span>
          </span>
          <span className="mu-zeile">
            <span className="mu-label">{m.pruefung ? "Prüfung" : "Leistungsnachweis"}</span>
            <span>{m.pruefung ? datumKurz(m.pruefung) : LN_TEXT[m.leistungsnachweis] || "noch nicht bekannt"}</span>
          </span>
          {m.naechster_termin ? (
            <span className="mu-zeile">
              <span className="mu-label">Nächster Termin</span>
              <span className="mu-ellipse" title={m.naechster_termin.name}>
                {datumKurz(m.naechster_termin)} · {m.naechster_termin.name}
              </span>
            </span>
          ) : null}
        </span>
      </button>
      <span className="mu-aktionen">
        <button type="button" className="stu-tbtn" onClick={onHochladen}>Hochladen</button>
        {leer ? <button type="button" className="stu-tbtn" onClick={onEntfernen}>Entfernen</button> : null}
      </span>
    </li>
  );
}

function SemesterWechsel({ onFertig, onSchliessen }) {
  const { api, toast, setView } = useStudio();
  const [daten, setDaten] = useState(null);
  const [archiv, setArchiv] = useState([]);
  const [fehler, setFehler] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("semester")
      .then((d) => {
        setDaten(d);
        setArchiv(d.module.filter((m) => m.archiviert || m.vorschlag_archiv).map((m) => m.name));
      })
      .catch((e) => setFehler(e.message || "Konnte die Module nicht laden."));
  }, [api]);

  const umschalten = (name) =>
    setArchiv((a) => (a.includes(name) ? a.filter((n) => n !== name) : [...a, name]));

  const speichern = async () => {
    setBusy(true);
    setFehler(null);
    try {
      const d = await api("semester/archiv", { method: "PUT", body: { archiv } });
      toast(d.archiv.length ? `${d.archiv.length} Modul${d.archiv.length === 1 ? "" : "e"} im Archiv` : "Archiv ist leer");
      onFertig();
    } catch (err) {
      setFehler(err.message || "Speichern fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="stu-panel mu-semester" aria-label="Semesterwechsel">
      <div className="stu-panel-head">
        <h3>Semesterwechsel</h3>
        <button type="button" className="stu-tbtn" onClick={onSchliessen}>Schliessen</button>
      </div>
      {fehler ? <div className="stu-error-box"><span>{fehler}</span></div> : null}
      {!daten ? (
        fehler ? null : <Loading text="Module werden geladen …" />
      ) : (
        <ol className="mu-schritte">
          <li>
            <strong>Alte Module archivieren</strong>
            <span className="mu-hinweis">
              Archivierte Module bleiben lesbar. Der Agent verarbeitet sie nicht mehr, und sie fallen aus Lernplan und
              «Braucht dich».{daten.moodle_bekannt ? " Vorausgewählt ist, was Moodle nicht mehr als laufend führt." : ""}
            </span>
            <ul className="mu-auswahl">
              {daten.module.map((m, i) => (
                <li key={m.name}>
                  <input id={`mu-a-${i}`} type="checkbox" checked={archiv.includes(m.name)} onChange={() => umschalten(m.name)} />
                  <label htmlFor={`mu-a-${i}`}>{m.name}</label>
                  <span className={"mu-badge is-" + m.quelle}>{m.quelle === "eigene" ? "Eigenes Modul" : "Moodle"}</span>
                  {m.aktuell ? <span className="mu-badge">läuft</span> : null}
                </li>
              ))}
            </ul>
          </li>
          <li>
            <strong>Neue Moodle-Kurse</strong>
            {daten.neu_in_moodle.length ? (
              <span className="mu-hinweis">
                Neu eingeschrieben: {daten.neu_in_moodle.join(", ")}. moodle-dl lädt sie beim nächsten Lauf herunter,
                danach erscheinen sie hier als Module.
              </span>
            ) : (
              <span className="mu-hinweis">
                Neue Kurse, in die du in Moodle eingeschrieben bist, lädt moodle-dl beim nächsten Lauf von selbst.
                Gerade ist kein neuer dabei.
              </span>
            )}
          </li>
          <li>
            <strong>Prüfungsplan des neuen Semesters</strong>
            <span className="mu-hinweis">Lade den neuen Plan unter Studium hoch und übernimm deine Prüfungen.</span>
            <span>
              <button type="button" className="stu-tbtn" onClick={() => setView("studium")}>Zu Studium</button>
            </span>
          </li>
        </ol>
      )}
      {daten ? (
        <div className="mu-aktionen">
          <button type="button" className="stu-tbtn is-pri" disabled={busy} onClick={speichern}>
            {busy ? "Speichert …" : "Archiv übernehmen"}
          </button>
        </div>
      ) : null}
    </section>
  );
}

export function ModuleBereich() {
  const { api, toast, setCourse, setUploadOpen, reloadCourses } = useStudio();
  const [detail, setDetail] = useState(() => load("modul-detail", ""));
  const [module, setModule] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [wechsel, setWechsel] = useState(false);

  const laden = useCallback(() => {
    setFehler(null);
    api("module")
      .then((d) => setModule(d.module || []))
      .catch((e) => setFehler(e.message || "Module konnten nicht geladen werden."));
  }, [api]);
  useEffect(laden, [laden]);

  const oeffnen = (name) => {
    setCourse(name);
    setDetail(name);
    save("modul-detail", name);
  };
  const zurueck = () => {
    setDetail("");
    save("modul-detail", "");
    laden();
  };

  if (detail) return <ModulView course={detail} onBack={zurueck} />;

  const entfernen = async (name) => {
    if (!window.confirm(`Das leere Modul «${name}» entfernen?`)) return;
    try {
      await api(`module?name=${encodeURIComponent(name)}`, { method: "DELETE" });
      toast(`«${name}» entfernt`);
      reloadCourses();
      laden();
    } catch (err) {
      toast(`Nicht entfernt: ${err.message}`);
    }
  };

  const hochladen = (name) => {
    setCourse(name);
    setUploadOpen(true);
  };

  const zurueckholen = async (name) => {
    const archiv = module.filter((m) => m.archiviert && m.name !== name).map((m) => m.name);
    try {
      await api("semester/archiv", { method: "PUT", body: { archiv } });
      toast(`«${name}» ist wieder aktiv`);
      laden();
    } catch (err) {
      toast(`Nicht geändert: ${err.message}`);
    }
  };

  const aktiv = (module || []).filter((m) => !m.archiviert);
  const archiviert = (module || []).filter((m) => m.archiviert);

  return (
    <div className="mu">
      <header className="stu-viewh">
        <h2>Module</h2>
        <span className="stu-viewh-desc">Alle Module dieses Semesters, aus Moodle und eigene</span>
        <div className="stu-grow" />
        <MoodleAktualisieren kompakt onFertig={() => { reloadCourses(); laden(); }} />
        <button type="button" className="stu-tbtn" aria-expanded={wechsel} onClick={() => setWechsel((w) => !w)}>
          Semesterwechsel
        </button>
        <NeuesModul onAngelegt={() => { reloadCourses(); laden(); }} />
      </header>
      <div className="mu-body">
        {wechsel ? (
          <SemesterWechsel onSchliessen={() => setWechsel(false)} onFertig={() => { setWechsel(false); laden(); }} />
        ) : null}
        {fehler ? (
          <div className="stu-error-box">
            <span>{fehler}</span>
            <button type="button" className="stu-tbtn is-pri" onClick={laden}>Erneut versuchen</button>
          </div>
        ) : !module ? (
          <Loading text="Module werden geladen …" />
        ) : aktiv.length === 0 ? (
          <div className="stu-empty-box"><span>Keine aktiven Module. Lege ein eigenes Modul an oder warte auf den ersten Moodle-Lauf.</span></div>
        ) : (
          <ul className="mu-raster">
            {aktiv.map((m) => (
              <ModulKarte
                key={m.name}
                m={m}
                onOeffnen={() => oeffnen(m.name)}
                onHochladen={() => hochladen(m.name)}
                onEntfernen={() => entfernen(m.name)}
              />
            ))}
          </ul>
        )}
        {archiviert.length ? (
          <details className="mu-archiv">
            <summary>Archiv ({archiviert.length})</summary>
            <ul className="mu-archiv-liste">
              {archiviert.map((m) => (
                <li key={m.name}>
                  <button type="button" className="mu-archiv-name" onClick={() => oeffnen(m.name)}>{m.name}</button>
                  <button type="button" className="stu-tbtn" onClick={() => zurueckholen(m.name)}>Zurückholen</button>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <p className="mu-fuss">
          Eigene Module sind für Fächer ohne Moodle-Kurs. Was du hochlädst, verarbeitet der Agent wie Moodle-Material.
        </p>
      </div>
    </div>
  );
}

export default ModuleBereich;
