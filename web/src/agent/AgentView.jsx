// AgentView.jsx: Bereich «Agent» mit Einstellungen und der Erklärung, wie der Agent gebaut ist
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import { GraphView } from "../graph/GraphView.jsx";
import { load, save } from "../ui/storage.js";
import "../plan/plan.css";
import "./agent.css";

const { useState, useEffect, useCallback } = React;

function Feld({ id, label, hint, children }) {
  return (
    <div className="ag-feld">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? <span className="ag-hint">{hint}</span> : null}
    </div>
  );
}

const TAGE = [
  ["mo", "Mo"], ["di", "Di"], ["mi", "Mi"], ["do", "Do"], ["fr", "Fr"], ["sa", "Sa"], ["so", "So"],
];
const TAG_INDEX = { so: 0, mo: 1, di: 2, mi: 3, do: 4, fr: 5, sa: 6 };

// Nächster geplanter Lauf ab jetzt (lokale Zeit), oder null
function naechsterLauf(z) {
  if (!z.aktiv || !z.tage.length) return null;
  const [h, m] = z.zeit.split(":").map(Number);
  const jetzt = new Date();
  for (let i = 0; i < 8; i++) {
    const d = new Date(jetzt);
    d.setDate(jetzt.getDate() + i);
    d.setHours(h, m, 0, 0);
    if (d > jetzt && z.tage.some((t) => TAG_INDEX[t] === d.getDay())) return d;
  }
  return null;
}

function datumText(d) {
  const heute = new Date();
  const morgen = new Date();
  morgen.setDate(heute.getDate() + 1);
  const zeit = d.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === heute.toDateString()) return `heute, ${zeit}`;
  if (d.toDateString() === morgen.toDateString()) return `morgen, ${zeit}`;
  return `${d.toLocaleDateString("de-CH", { weekday: "long", day: "numeric", month: "long" })}, ${zeit}`;
}

function LetzterLauf({ lauf }) {
  if (!lauf) return <span>Noch kein Lauf protokolliert.</span>;
  const start = datumText(new Date(lauf.start.replace(" ", "T")));
  if (lauf.ende === null) return <span>Letzter Lauf: {start}, läuft noch oder wurde abgebrochen.</span>;
  if (!lauf.fehler) return <span>Letzter Lauf: {start}, ohne Fehler.</span>;
  return (
    <span className="ag-warn">
      Letzter Lauf: {start}, mit Fehlern{lauf.schritte_fehler.length ? ` bei ${lauf.schritte_fehler.join(", ")}` : ""}.
      Details in logs/daily.log.
    </span>
  );
}

function ZeitplanFelder({ z, gespeichertZ, status, onChange, onReparieren, busy }) {
  const tagToggle = (t) =>
    onChange("tage", z.tage.includes(t) ? z.tage.filter((x) => x !== t) : [...z.tage, t]);
  const naechster = naechsterLauf(z);
  const ungespeichert = JSON.stringify(z) !== JSON.stringify(gespeichertZ);
  const passtNicht = gespeichertZ.aktiv && status && !status.stimmt;

  return (
    <section className="stu-panel">
      <div className="stu-panel-head">
        <h3>Zeitplan</h3>
        {status ? (
          <span className={"ag-chip" + (gespeichertZ.aktiv && status.stimmt ? " is-ok" : " is-off")}>
            {!gespeichertZ.aktiv ? "aus" : status.stimmt ? "eingerichtet" : "nicht eingerichtet"}
          </span>
        ) : null}
      </div>
      <p className="ag-text">
        Einmal am Tag: Moodle laden, Dateien umwandeln und verarbeiten, Suchindex ergänzen, Briefing schreiben.
      </p>
      <label className="ag-check ag-check-gross" htmlFor="ag-z-aktiv">
        <input id="ag-z-aktiv" type="checkbox" checked={z.aktiv} onChange={(e) => onChange("aktiv", e.target.checked)} />
        <span>Täglichen Lauf einschalten</span>
      </label>
      <div className="ag-grid">
        <Feld id="ag-z-zeit" label="Uhrzeit" hint="Schläft der Mac zu dieser Zeit, läuft der Agent beim Aufwachen. Ist er aus, fällt der Lauf aus.">
          <input id="ag-z-zeit" type="time" value={z.zeit} disabled={!z.aktiv}
            onChange={(e) => e.target.value && onChange("zeit", e.target.value)} />
        </Feld>
        <fieldset className="ag-fieldset" disabled={!z.aktiv}>
          <legend>Wochentage</legend>
          <div className="ag-tage">
            {TAGE.map(([t, kurz]) => (
              <label key={t} className={"ag-tag" + (z.tage.includes(t) ? " is-on" : "")} htmlFor={`ag-z-${t}`}>
                <input id={`ag-z-${t}`} type="checkbox" checked={z.tage.includes(t)} onChange={() => tagToggle(t)} />
                {kurz}
              </label>
            ))}
          </div>
          <span className="ag-hint">Höchstens ein Lauf pro Tag.</span>
        </fieldset>
      </div>
      <div className="ag-status" aria-live="polite">
        {naechster ? (
          <span>
            {ungespeichert ? "Nach dem Speichern: nächster Lauf " : "Nächster Lauf: "}
            <strong>{datumText(naechster)}</strong>
          </span>
        ) : null}
        {status ? <LetzterLauf lauf={status.letzter_lauf} /> : null}
        {passtNicht ? (
          <span className="ag-warn">
            Der Job im System passt nicht zu diesen Einstellungen.{" "}
            <button type="button" className="stu-tbtn" disabled={busy} onClick={onReparieren}>Neu einrichten</button>
          </span>
        ) : null}
      </div>
    </section>
  );
}

const MELDEN = [
  ["neues_material", "Neues Material in Moodle oder eigenen Modulen"],
  ["fristen", "Fristen und Prüfungen, die näher rücken"],
  ["freigaben", "Freigaben, die auf dich warten"],
];

function Benachrichtigungen({ b, onChange }) {
  const { api, toast } = useStudio();
  const [busy, setBusy] = useState(false);
  const [ergebnis, setErgebnis] = useState(null);

  const testen = async () => {
    setBusy(true);
    setErgebnis(null);
    try {
      const d = await api("benachrichtigung/test", { method: "POST", body: b });
      const teile = [];
      if ("mac" in d) teile.push(d.mac ? "Mac: gesendet" : "Mac: nicht möglich");
      if ("ntfy" in d) teile.push(d.ntfy ? "ntfy: gesendet" : `ntfy: ${d.ntfy_fehler || "fehlgeschlagen"}`);
      setErgebnis(teile.join(" · "));
      if (d.mac || d.ntfy) toast("Probemeldung verschickt");
    } catch (err) {
      setErgebnis(err.message || "Test fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="stu-panel">
      <div className="stu-panel-head"><h3>Benachrichtigungen</h3></div>
      <p className="ag-text">Nach dem täglichen Lauf meldet sich der Agent, wenn etwas ansteht. Ist nichts los, bleibt er still.</p>
      <fieldset className="ag-fieldset">
        <legend>Wohin</legend>
        <label className="ag-check" htmlFor="ag-mac">
          <input id="ag-mac" type="checkbox" checked={b.mac} onChange={(e) => onChange("mac", e.target.checked)} />
          <span>Mitteilung auf dem Mac</span>
        </label>
      </fieldset>
      <div className="ag-grid">
        <Feld id="ag-ntfy" label="ntfy-Thema fürs Handy" hint="App «ntfy» installieren und dasselbe Thema abonnieren. Leer = aus. Wer das Thema kennt, liest mit: wähle einen Namen, den niemand errät.">
          <input
            id="ag-ntfy"
            type="text"
            maxLength={64}
            value={b.ntfy_thema}
            placeholder="z. B. studium-7f3k9q"
            onChange={(e) => onChange("ntfy_thema", e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))}
          />
        </Feld>
        <Feld id="ag-ntfy-server" label="ntfy-Server" hint="Standard ist der öffentliche Dienst ntfy.sh. Eigener Server: dessen https-Adresse.">
          <input
            id="ag-ntfy-server"
            type="url"
            value={b.ntfy_server}
            onChange={(e) => onChange("ntfy_server", e.target.value)}
          />
        </Feld>
      </div>
      <fieldset className="ag-fieldset">
        <legend>Was</legend>
        {MELDEN.map(([feld, text]) => (
          <label key={feld} className="ag-check" htmlFor={`ag-m-${feld}`}>
            <input id={`ag-m-${feld}`} type="checkbox" checked={b[feld]} onChange={(e) => onChange(feld, e.target.checked)} />
            <span>{text}</span>
          </label>
        ))}
      </fieldset>
      <div className="ag-grid">
        <Feld id="ag-frist" label="Fristen melden ab (Tage vorher)">
          <input
            id="ag-frist"
            type="number"
            min={1}
            max={30}
            value={b.frist_tage}
            disabled={!b.fristen}
            onChange={(e) => onChange("frist_tage", Number(e.target.value))}
          />
        </Feld>
      </div>
      <div className="ag-zeile">
        <button type="button" className="stu-tbtn" disabled={busy || (!b.mac && !b.ntfy_thema)} onClick={testen}>
          {busy ? "Sendet …" : "Probemeldung senden"}
        </button>
        {ergebnis ? <span className="ag-hint" role="status">{ergebnis}</span> : null}
      </div>
    </section>
  );
}

function Einstellungen() {
  const { api, toast, courses } = useStudio();
  const [werte, setWerte] = useState(null);
  const [gespeichert, setGespeichert] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  const ladeStatus = useCallback(() => {
    api("zeitplan").then((d) => setStatus(d.status)).catch(() => {});
  }, [api]);
  useEffect(ladeStatus, [ladeStatus]);

  const laden = useCallback(() => {
    setFehler(null);
    api("einstellungen")
      .then((d) => {
        setWerte(d.einstellungen);
        setGespeichert(JSON.stringify(d.einstellungen));
      })
      .catch((e) => setFehler(e.message || "Einstellungen konnten nicht geladen werden."));
  }, [api]);

  useEffect(laden, [laden]);

  if (fehler && !werte) {
    return (
      <div className="stu-error-box">
        <span>{fehler}</span>
        <button type="button" className="stu-tbtn is-pri" onClick={laden}>Erneut versuchen</button>
      </div>
    );
  }
  if (!werte) return <Loading text="Einstellungen werden geladen …" />;

  const set = (bereich, feld, wert) =>
    setWerte((w) => ({ ...w, [bereich]: { ...w[bereich], [feld]: wert } }));
  const geaendert = JSON.stringify(werte) !== gespeichert;
  const gespeichertZ = JSON.parse(gespeichert).zeitplan;

  const reparieren = async () => {
    setBusy(true);
    try {
      const d = await api("zeitplan/anwenden", { method: "POST" });
      setStatus(d.status);
      toast("Zeitplan neu eingerichtet");
    } catch (err) {
      setFehler(err.message || "Einrichten fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  const kursNamen = Array.from(
    new Set([...(courses || []).map((c) => c.name || c.course || c).filter((n) => typeof n === "string"),
      ...werte.filter.kurse_ignorieren])
  ).sort();
  const toggleKurs = (name) => {
    const liste = werte.filter.kurse_ignorieren;
    set("filter", "kurse_ignorieren", liste.includes(name) ? liste.filter((n) => n !== name) : [...liste, name]);
  };

  const speichern = async (e) => {
    e.preventDefault();
    setBusy(true);
    setFehler(null);
    try {
      const d = await api("einstellungen", { method: "PUT", body: werte });
      setWerte(d.einstellungen);
      setGespeichert(JSON.stringify(d.einstellungen));
      if (d.zeitplan) setStatus(d.zeitplan);
      if (d.zeitplan_fehler) {
        setFehler(`Gespeichert, aber der Zeitplan liess sich nicht einrichten: ${d.zeitplan_fehler}`);
        ladeStatus();
      } else {
        toast(d.zeitplan ? "Einstellungen und Zeitplan gespeichert" : "Einstellungen gespeichert");
      }
    } catch (err) {
      setFehler(err.message || "Speichern fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="ag-form" onSubmit={speichern}>
      <section className="stu-panel">
        <div className="stu-panel-head"><h3>Profil</h3></div>
        <Feld id="ag-name" label="Dein Name" hint="Erscheint im Dashboard. Das Gedächtnis des Agenten bleibt unverändert.">
          <input
            id="ag-name"
            type="text"
            maxLength={80}
            value={werte.profil.name}
            placeholder="z. B. Alex"
            onChange={(e) => set("profil", "name", e.target.value)}
          />
        </Feld>
      </section>

      <ZeitplanFelder
        z={werte.zeitplan}
        gespeichertZ={gespeichertZ}
        status={status}
        busy={busy}
        onChange={(feld, wert) => set("zeitplan", feld, wert)}
        onReparieren={reparieren}
      />

      <section className="stu-panel">
        <div className="stu-panel-head"><h3>Verarbeitung pro Lauf</h3></div>
        <div className="ag-grid">
          <Feld id="ag-limit" label="Dateien pro Lauf" hint="So viele Dateien fasst der Agent beim täglichen Lauf zusammen. 0 = keine.">
            <input
              id="ag-limit"
              type="number"
              min={0}
              max={100}
              value={werte.verarbeitung.dateien_pro_lauf}
              onChange={(e) => set("verarbeitung", "dateien_pro_lauf", Number(e.target.value))}
            />
          </Feld>
          <Feld id="ag-rag" label="Abschnitte für die Suche pro Lauf" hint="Neue Textabschnitte, die eingebettet werden. Etwa ein Abschnitt pro Sekunde.">
            <input
              id="ag-rag"
              type="number"
              min={0}
              max={100000}
              step={50}
              value={werte.verarbeitung.rag_max}
              onChange={(e) => set("verarbeitung", "rag_max", Number(e.target.value))}
            />
          </Feld>
          <Feld id="ag-ocr" label="Gescannte PDFs pro Lauf" hint="Eingescannte Unterlagen ohne Text liest das Vision-Modell Seite für Seite. Kostet Tokens. 0 = aus.">
            <input
              id="ag-ocr"
              type="number"
              min={0}
              max={10}
              value={werte.verarbeitung.ocr_pro_lauf}
              onChange={(e) => set("verarbeitung", "ocr_pro_lauf", Number(e.target.value))}
            />
          </Feld>
        </div>
      </section>

      <Benachrichtigungen b={werte.benachrichtigungen} onChange={(feld, wert) => set("benachrichtigungen", feld, wert)} />

      <section className="stu-panel">
        <div className="stu-panel-head"><h3>Was der Agent aus Moodle verwendet</h3></div>
        <p className="ag-text">moodle-dl lädt weiterhin alles herunter. Hier legst du fest, was der Agent davon beachtet.</p>
        <fieldset className="ag-fieldset">
          <legend>Kurse</legend>
          {kursNamen.length === 0 ? (
            <span className="ag-hint">Keine Kurse gefunden.</span>
          ) : (
            kursNamen.map((name, i) => (
              <label key={name} className="ag-check" htmlFor={`ag-kurs-${i}`}>
                <input
                  id={`ag-kurs-${i}`}
                  type="checkbox"
                  checked={!werte.filter.kurse_ignorieren.includes(name)}
                  onChange={() => toggleKurs(name)}
                />
                <span>{name}</span>
              </label>
            ))
          )}
          <span className="ag-hint">Abgewählte Kurse werden nicht mehr verarbeitet und erscheinen nicht unter «Braucht dich».</span>
        </fieldset>
        <div className="ag-grid">
          <Feld id="ag-leer" label="Leere Seiten bis (Byte)" hint="Unklare Moodle-Seiten bis zu dieser Grösse gelten als leere Platzhalter. 0 = aus.">
            <input
              id="ag-leer"
              type="number"
              min={0}
              max={100000}
              value={werte.filter.leere_seiten_bytes}
              onChange={(e) => set("filter", "leere_seiten_bytes", Number(e.target.value))}
            />
          </Feld>
          <Feld id="ag-namen" label="Namen überspringen" hint="Eine Zeile pro Namensteil. Gilt nur für unklare Dateien.">
            <textarea
              id="ag-namen"
              rows={3}
              value={werte.filter.namen_ueberspringen.join("\n")}
              onChange={(e) => set("filter", "namen_ueberspringen", e.target.value.split("\n"))}
            />
          </Feld>
        </div>
      </section>

      <div className="ag-actions">
        {fehler ? <span className="ag-fehler" role="alert">{fehler}</span> : null}
        <button type="button" className="stu-tbtn" disabled={!geaendert || busy} onClick={laden}>Verwerfen</button>
        <button type="submit" className="stu-tbtn is-pri" disabled={!geaendert || busy}>
          {busy ? "Speichert …" : "Speichern"}
        </button>
      </div>
    </form>
  );
}

const FUNKTIONEN = [
  { titel: "Moodle laden", wann: "täglich", text: "Holt neue Dateien und Termine aus deinen Moodle-Kursen. Nur lesend, es wird nichts abgegeben." },
  { titel: "Umwandeln", wann: "täglich", text: "Macht aus PDF, Word und PowerPoint lesbaren Text, damit der Agent damit arbeiten kann." },
  { titel: "Verarbeiten", wann: "täglich", text: "Ordnet jede Datei ein, fasst Folien zusammen und lässt einen Prüfer gegenlesen. Bei Einwänden fragt er dich.", ziel: "overview", knopf: "Offene Dateien" },
  { titel: "Suchindex", wann: "täglich", text: "Zerlegt das Material in Abschnitte, damit Suche und Chat die passende Stelle finden.", ziel: "search", knopf: "Suchen" },
  { titel: "Texterkennung", wann: "täglich", text: "Liest eingescannte PDFs ohne Text mit dem Vision-Modell, damit auch sie zusammengefasst und durchsucht werden." },
  { titel: "Briefing", wann: "täglich", text: "Schreibt eine kurze Übersicht mit Fristen, Terminen und Neuem und meldet sich auf dem Mac oder dem Handy.", ziel: "overview", knopf: "Heute" },
  { titel: "Fragen stellen", wann: "auf Abruf", text: "Beantwortet Fragen zum Stoff mit Quellenangabe und merkt sich, was du gelernt hast.", chat: true, knopf: "Chat öffnen" },
  { titel: "Lernplan", wann: "auf Abruf", text: "Verteilt die Themen jedes Moduls auf die Wochen bis zur Prüfung, mit einer Woche Wiederholung am Schluss.", ziel: "lernplan", knopf: "Lernplan" },
  { titel: "Karteikarten", wann: "auf Abruf", text: "Fragt die Begriffe aus den Zusammenfassungen als Karten ab. Was du nicht weisst, kommt öfter.", ziel: "karten", knopf: "Lernen" },
  { titel: "Prüfungsplan", wann: "auf Abruf", text: "Liest den Prüfungsplan der Hochschule und trägt deine Prüfungen in Kalender und Module ein.", ziel: "studium", knopf: "Studium" },
  { titel: "Semesterwechsel", wann: "auf Abruf", text: "Archiviert die Module des alten Semesters, nimmt neue Moodle-Kurse auf und führt zum neuen Prüfungsplan.", ziel: "modul", knopf: "Module" },
  { titel: "Termine", wann: "täglich", text: "Sammelt Prüfungen, Abgaben und Lektionen aus Moodle und Semesterprogrammen.", ziel: "calendar", knopf: "Kalender" },
];

function Funktionen() {
  const { setView, setRightOpen } = useStudio();
  return (
    <div className="ag-form ag-form-breit">
      <p className="ag-text">
        Was der Agent kann. «Täglich» läuft im Zeitplan, «auf Abruf» startest du selbst.
      </p>
      <ul className="ag-karten">
        {FUNKTIONEN.map((f) => (
          <li key={f.titel} className="stu-panel ag-karte">
            <div className="stu-panel-head">
              <h3>{f.titel}</h3>
              <span className={"ag-chip" + (f.wann === "täglich" ? "" : " is-off")}>{f.wann}</span>
            </div>
            <p className="ag-text">{f.text}</p>
            {f.knopf ? (
              <button type="button" className="stu-tbtn"
                onClick={() => (f.chat ? setRightOpen(true) : setView(f.ziel))}>
                {f.knopf}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

const TABS = [
  ["einstellungen", "Einstellungen"],
  ["funktionen", "Funktionen"],
  ["aufbau", "So funktioniert er"],
];

export function AgentView() {
  const [tab, setTab] = useState(() => load("agent-tab", "einstellungen"));
  const waehle = (t) => {
    setTab(t);
    save("agent-tab", t);
  };

  return (
    <div className="ag">
      <header className="stu-viewh ag-head">
        <h2>Agent</h2>
        <span className="stu-viewh-desc">Einstellen, was der Agent tut, und nachsehen, wie er arbeitet</span>
        <div className="stu-grow" />
        <div className="stu-seg" role="tablist" aria-label="Agent-Bereich">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id}
              className={tab === id ? "is-on" : ""} onClick={() => waehle(id)}>
              {label}
            </button>
          ))}
        </div>
      </header>
      {tab === "aufbau" ? (
        <div className="ag-graph"><GraphView /></div>
      ) : (
        <div className="ag-body">{tab === "funktionen" ? <Funktionen /> : <Einstellungen />}</div>
      )}
    </div>
  );
}

export default AgentView;
