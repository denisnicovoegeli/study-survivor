// QuellenKarte.jsx: Dokumente eines Moduls als Status-Tabelle (geladen → Text → Zusammenfassung → Suche → RAG)
// mit Häkchen «Nutzen»: abgewählte Dokumente fehlen in Suche, Chat und Verarbeitung.
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Loading } from "../ui/Loading.jsx";
import { load, save } from "../ui/storage.js";
import { MoodleAktualisieren } from "./MoodleAktualisieren.jsx";
import "./quellen.css";

const { useState, useEffect, useCallback, useRef } = React;

const NICHT = ["fehlt", "link", "typ", "leer"];
const FILTER = [
  { id: "nutzt", label: "Genutzt", passt: (d) => d.status === "nutzt" },
  { id: "bald", label: "In Arbeit", passt: (d) => d.status === "bald" || d.status === "scan" },
  { id: "aus", label: "Abgewählt", passt: (d) => d.status === "aus" },
  { id: "nicht", label: "Nicht nutzbar", passt: (d) => NICHT.includes(d.status) },
  { id: "alle", label: "Alle", passt: () => true },
];
const SCHRITTE = [
  { id: "geladen", kurz: "Geladen", lang: "Aus Moodle heruntergeladen (oder hochgeladen)" },
  { id: "text", kurz: "Text", lang: "Text ausgelesen, bei Scans per Texterkennung" },
  { id: "zf", kurz: "Zusammenf.", mobil: "Zus.", lang: "Zusammenfassung und Folien-Notizen (mit Bildbeschreibungen) erstellt" },
  { id: "suche", kurz: "Suche", lang: "Im Volltext-Index: Der Chat findet das Dokument per Stichwort" },
  { id: "rag", kurz: "RAG", lang: "Im semantischen Index (Embeddings): Der Chat findet es auch sinngemäss" },
];
const ZEICHEN = { ok: "✓", wartet: "…", nein: "✕", na: "–", aus: "⊘" };
const ZEICHEN_TEXT = { ok: "erledigt", wartet: "steht noch aus", nein: "nicht möglich", na: "nicht nötig", aus: "abgewählt" };

const istDokument = (d) => d.art === "Datei" || d.art === "Eigene Datei";

function schritt(d, id) {
  const aus = d.status === "aus";
  switch (id) {
    case "geladen":
      if (d.art === "Link") return ["na", "Link, nichts herunterzuladen"];
      return d.geladen ? ["ok"] : ["nein", "Nicht heruntergeladen"];
    case "text":
      if (d.art === "Link") return ["na", "Der Agent öffnet keine Webseiten"];
      if (d.ausgelesen) return ["ok", d.texterkennung ? "Per Texterkennung gelesen" : ""];
      if (d.status === "scan") return ["wartet", "Gescannt, die Texterkennung folgt in einem der nächsten Läufe"];
      if (d.status === "typ") return ["nein", `.${d.endung}-Dateien kann der Agent nicht lesen`];
      return d.geladen ? ["wartet"] : ["na"];
    case "zf":
      if (d.aufbereitung === "fertig") return ["ok"];
      if (d.aufbereitung === "offen") return aus ? ["aus"] : ["wartet", "Kommt beim nächsten Lauf oder mit «verarbeiten»"];
      if (d.aufbereitung === "uebersprungen") return ["na", `Nicht nötig: ${d.grund}`];
      if (d.aufbereitung === "nicht_noetig") return ["na", `Nicht nötig für ${d.klasse || "diese Art"}, nur Suche`];
      return ["na"];
    case "suche":
      if (aus) return ["aus"];
      if (d.volltext) return ["ok", d.folien_aufbereitet ? "Mit Folien-Notizen" : "Mit dem ausgelesenen Text"];
      if (d.status === "leer") return ["nein", "Ohne lesbaren Text"];
      return d.ausgelesen ? ["wartet", "Kommt beim nächsten Lauf"] : ["na"];
    case "rag":
      if (aus) return ["aus"];
      if (d.semantisch) return ["ok", `${d.semantisch} Abschnitte eingebettet`];
      return d.volltext ? ["wartet", "Kommt beim nächsten Lauf"] : ["na"];
    default:
      return ["na"];
  }
}

function umfang(d) {
  if (d.folien_aufbereitet && d.abschnitte) return `${d.abschnitte} Folien`;
  if (d.seiten) return `${d.seiten} ${d.seiten === 1 ? "Seite" : "Seiten"}`;
  return null;
}

function stand(iso) {
  if (!iso) return "unbekannt";
  return new Date(iso).toLocaleString("de-CH", {
    timeZone: "Europe/Zurich", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function Zelle({ d, id, titel, mobil }) {
  const [art, grund] = schritt(d, id);
  const text = `${titel}: ${ZEICHEN_TEXT[art]}${grund ? `. ${grund}` : ""}`;
  return (
    <td className={"qk-schritt is-" + art} title={text} data-label={mobil || titel}>
      <span aria-hidden="true">{ZEICHEN[art]}</span>
      <span className="qk-sr">{text}</span>
    </td>
  );
}

function Zeile({ d, onNutzen, onOeffnen, busy }) {
  const id = "qk-" + d.rel.replace(/[^a-zA-Z0-9]/g, "").slice(-50);
  const meta = istDokument(d) ? [d.klasse, umfang(d)].filter(Boolean).join(" · ") : `Moodle-Text · ${d.art}`;
  return (
    <tr className={"qk-zeile is-" + d.status}>
      <td className="qk-nutzen">
        {d.waehlbar ? (
          <input
            id={id}
            type="checkbox"
            checked={d.nutzen}
            disabled={busy}
            onChange={(e) => onNutzen([d.rel], e.target.checked)}
            aria-label={`${d.titel} für den Agenten nutzen`}
          />
        ) : null}
      </td>
      <td className="qk-doc">
        {d.oeffnen ? (
          <button type="button" className="qk-titel" onClick={() => onOeffnen(d)} title="Ansehen">{d.titel}</button>
        ) : (
          <span className="qk-titel">{d.titel}</span>
        )}
        {meta ? <span className="qk-meta">{meta}</span> : null}
      </td>
      {SCHRITTE.map((s) => <Zelle key={s.id} d={d} id={s.id} titel={s.kurz} mobil={s.mobil} />)}
    </tr>
  );
}

function Abschnitt({ a, onNutzen, onOeffnen, busy }) {
  const box = useRef(null);
  const waehlbar = a.alle.filter((d) => d.waehlbar);
  const an = waehlbar.filter((d) => d.nutzen).length;
  useEffect(() => {
    if (box.current) box.current.indeterminate = an > 0 && an < waehlbar.length;
  }, [an, waehlbar.length]);
  const id = "qka-" + a.name.replace(/[^a-zA-Z0-9]/g, "").slice(-40);
  return (
    <details className="qk-abschnitt" open>
      <summary>
        <span className="qk-abschnitt-name">{a.name}</span>
        <span className="qk-abschnitt-zahl">{a.genutzt} von {a.alle.length} genutzt</span>
      </summary>
      {waehlbar.length > 1 ? (
        <label className="qk-alle" htmlFor={id}>
          <input
            id={id}
            ref={box}
            type="checkbox"
            checked={an === waehlbar.length}
            disabled={busy}
            onChange={(e) => onNutzen(waehlbar.map((d) => d.rel), e.target.checked)}
          />
          Ganzen Abschnitt nutzen
        </label>
      ) : null}
      <div className="qk-tabelle-rahmen">
        <table className="qk-tabelle">
          <thead>
            <tr>
              <th scope="col" className="qk-nutzen">Nutzen</th>
              <th scope="col">Dokument</th>
              {SCHRITTE.map((s) => <th key={s.id} scope="col" title={s.lang}>{s.kurz}</th>)}
            </tr>
          </thead>
          <tbody>
            {a.sichtbar.map((d) => (
              <Zeile key={d.rel} d={d} onNutzen={onNutzen} onOeffnen={onOeffnen} busy={busy} />
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function QuellenKarte({ course }) {
  const { api, openFile, toast } = useStudio();
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState(() => load("quellen-filter", "alle"));
  const [texte, setTexte] = useState(() => load("quellen-moodletexte", false) === true);

  const laden = useCallback(() => {
    setFehler(null);
    return api(`quellen?kurs=${encodeURIComponent(course)}`)
      .then(setDaten)
      .catch((e) => setFehler(e.message || "Quellen konnten nicht geladen werden."));
  }, [api, course]);
  useEffect(() => { laden(); }, [laden]);

  const nutzen = async (rels, an) => {
    setBusy(true);
    setDaten((alt) => ({
      ...alt,
      abschnitte: alt.abschnitte.map((a) => ({
        ...a,
        dateien: a.dateien.map((d) => (rels.includes(d.rel) ? { ...d, nutzen: an, status: an ? d.status : "aus" } : d)),
      })),
    }));
    const was = rels.length === 1 ? "Dokument" : `${rels.length} Dokumente`;
    try {
      await api("quellen/nutzen", { method: "PUT", body: { rels, nutzen: an, kurs: course } });
      toast(an ? `${was} wieder für den Agenten freigegeben` : `${was} abgewählt: nicht mehr in Suche und Chat`);
    } catch (err) {
      toast(`Nicht gespeichert: ${err.message}`);
    } finally {
      await laden();
      setBusy(false);
    }
  };

  const z = daten?.zusammenfassung;
  const f = FILTER.find((x) => x.id === filter) || FILTER[4];
  const sichtbarBasis = (d) => texte || istDokument(d);
  const alle = daten ? daten.abschnitte.flatMap((a) => a.dateien) : [];
  const anzahl = (x) => alle.filter((d) => sichtbarBasis(d) && x.passt(d)).length;
  const abschnitte = (daten?.abschnitte || [])
    .map((a) => ({
      name: a.name,
      alle: a.dateien.filter(sichtbarBasis),
      sichtbar: [...a.dateien.filter((d) => istDokument(d) && f.passt(d)),
        ...a.dateien.filter((d) => texte && !istDokument(d) && f.passt(d))],
      genutzt: a.dateien.filter((d) => sichtbarBasis(d) && d.status === "nutzt").length,
    }))
    .filter((a) => a.sichtbar.length);

  return (
    <section className="stu-modul-card qk" aria-labelledby="qk-titel">
      <div className="qk-kopf">
        <h2 id="qk-titel" className="stu-modul-card-title">
          <Icon n="files" />
          <span>Dokumente und Quellen</span>
        </h2>
        <MoodleAktualisieren onFertig={laden} />
      </div>

      {fehler ? (
        <div className="stu-error-box">
          <span>{fehler}</span>
          <button type="button" className="stu-tbtn is-pri" onClick={laden}>Erneut versuchen</button>
        </div>
      ) : !daten ? (
        <Loading text="Dokumente werden gezählt …" />
      ) : z.total === 0 ? (
        <p className="stu-muted">Noch keine Dokumente in diesem Modul. Hol sie mit «Moodle aktualisieren» oder lade eigene hoch.</p>
      ) : (
        <>
          <div className="qk-zahlen">
            <div className="qk-zahl is-ok"><strong>{anzahl(FILTER[0])}</strong><span>nutzt der Agent</span></div>
            <div className="qk-zahl"><strong>{alle.filter((d) => sichtbarBasis(d) && d.aufbereitung === "fertig").length}</strong><span>zusammengefasst</span></div>
            <div className="qk-zahl"><strong>{anzahl(FILTER[1])}</strong><span>in Arbeit</span></div>
            <div className="qk-zahl is-aus"><strong>{anzahl(FILTER[2])}</strong><span>von dir abgewählt</span></div>
          </div>

          <details className="qk-legende">
            <summary>Was bedeuten die Spalten?</summary>
            <dl>
              {SCHRITTE.map((s) => (
                <div key={s.id}><dt>{s.kurz}</dt><dd>{s.lang}</dd></div>
              ))}
              <div><dt>Nutzen</dt><dd>Ohne Häkchen fehlt das Dokument in Suche, Chat und Zusammenfassung. Es bleibt heruntergeladen, du kannst es jederzeit wieder anhaken.</dd></div>
            </dl>
            <p>
              <span className="qk-schritt is-ok">✓</span> erledigt · <span className="qk-schritt is-wartet">…</span> steht noch aus ·{" "}
              <span className="qk-schritt is-na">–</span> nicht nötig · <span className="qk-schritt is-nein">✕</span> nicht möglich ·{" "}
              <span className="qk-schritt is-aus">⊘</span> abgewählt. Moodle zuletzt geholt: {stand(daten.stand.moodle)}.
            </p>
          </details>

          <div className="qk-steuerung">
            <div className="qk-filter" role="group" aria-label="Dokumente filtern">
              {FILTER.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  className={"qk-filter-knopf" + (x.id === f.id ? " is-an" : "")}
                  aria-pressed={x.id === f.id}
                  onClick={() => { setFilter(x.id); save("quellen-filter", x.id); }}
                >
                  {x.label} <span className="qk-filter-zahl">{anzahl(x)}</span>
                </button>
              ))}
            </div>
            <label className="qk-texte">
              <input
                type="checkbox"
                checked={texte}
                onChange={(e) => { setTexte(e.target.checked); save("quellen-moodletexte", e.target.checked); }}
              />
              Moodle-Texte zeigen (Ankündigungen, Beschreibungen)
            </label>
          </div>

          {abschnitte.length === 0 ? (
            <p className="stu-muted">Keine Dokumente in dieser Auswahl.</p>
          ) : (
            <div className="qk-abschnitte">
              {abschnitte.map((a) => (
                <Abschnitt
                  key={a.name}
                  a={a}
                  busy={busy}
                  onNutzen={nutzen}
                  onOeffnen={(x) => openFile("moodle", x.rel)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default QuellenKarte;
