// LernplanView.jsx: Themen jedes Moduls auf die Wochen bis zur Prüfung verteilt, mit Wiederholungswoche
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import { save } from "../ui/storage.js";
import "../plan/plan.css";
import "../modul/module.css";
import "./lernplan.css";

const { useState, useEffect, useCallback } = React;

function tag(iso, opt) {
  const [j, m, t] = iso.split("-").map(Number);
  return new Date(j, m - 1, t).toLocaleDateString("de-CH", opt);
}

function plusTage(iso, n) {
  const [j, m, t] = iso.split("-").map(Number);
  const d = new Date(j, m - 1, t + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function wochenTitel(start, aktuell) {
  if (start === aktuell) return "Diese Woche";
  if (start === plusTage(aktuell, 7)) return "Nächste Woche";
  return `${tag(start, { day: "numeric", month: "short" })} – ${tag(plusTage(start, 6), { day: "numeric", month: "short" })}`;
}

const LN_TEXT = { pruefung: "Prüfung", projekt: "Projekt, keine Prüfung", beides: "Prüfung & Projekt" };

function ModulKopf({ m, onKarten, onModul }) {
  const fertig = m.themen.filter((t) => t.erledigt).length;
  const k = m.karten;
  return (
    <li className="stu-panel lp-modul">
      <div className="lp-modul-kopf">
        <strong>{m.name}</strong>
        <span className="lp-tage">{m.tage === 0 ? "heute" : m.tage === 1 ? "morgen" : `noch ${m.tage} Tage`}</span>
      </div>
      <span className="lp-sub">Prüfung {tag(m.pruefung, { weekday: "short", day: "numeric", month: "long", year: "numeric" })}</span>
      <span className="mu-fortschritt">
        <span className="mu-balken" aria-hidden="true">
          <span style={{ width: `${m.themen.length ? Math.round((100 * fertig) / m.themen.length) : 0}%` }} />
        </span>
        <span>{fertig} von {m.themen.length} Themen gelernt</span>
      </span>
      <span className="lp-sub">
        {k.total ? `Karteikarten: ${k.fach3} von ${k.total} sitzen` : "Noch keine Karteikarten"}
      </span>
      <span className="mu-aktionen">
        <button type="button" className="stu-tbtn" onClick={onModul}>Modul</button>
        {k.total ? <button type="button" className="stu-tbtn" onClick={onKarten}>Karteikarten</button> : null}
      </span>
    </li>
  );
}

function Woche({ w, aktuell, erledigt, onToggle }) {
  const jetzt = w.start === aktuell;
  return (
    <section className={"stu-panel lp-woche" + (jetzt ? " is-jetzt" : "")} aria-label={wochenTitel(w.start, aktuell)}>
      <div className="stu-panel-head">
        <h3>{wochenTitel(w.start, aktuell)}</h3>
        {w.start !== aktuell && w.start !== plusTage(aktuell, 7) ? null : (
          <span className="lp-sub">
            {tag(w.start, { day: "numeric", month: "short" })} – {tag(plusTage(w.start, 6), { day: "numeric", month: "short" })}
          </span>
        )}
      </div>
      {w.module.map((m) => (
        <div key={m.modul} className="lp-eintrag">
          <span className="lp-eintrag-modul">{m.modul}</span>
          {m.pruefung ? (
            <span className="lp-pruefung">Prüfung {tag(m.pruefung, { weekday: "long", day: "numeric", month: "long" })}</span>
          ) : null}
          {m.themen.length ? (
            <ul className="lp-themen">
              {m.themen.map((t) => {
                const id = `lp-${m.modul}-${t.id}`.replace(/\s+/g, "-");
                const an = erledigt(m.modul, t.id);
                return (
                  <li key={t.id} className={an ? "is-erledigt" : ""}>
                    <input id={id} type="checkbox" checked={an} onChange={() => onToggle(m.modul, t.id, !an)} />
                    <label htmlFor={id}>{t.name}</label>
                    {!t.aufbereitet ? <span className="lp-chip" title="Der Agent hat dieses Thema noch nicht zusammengefasst">noch nicht aufbereitet</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {m.wiederholung && !(m.pruefung && m.pruefung <= plusTage(w.start, 1)) ? (
            <p className="lp-wiederholung">
              Wiederholung: Zusammenfassungen und Cheatsheets durchgehen, Karteikarten bis Fach 3 bringen.
            </p>
          ) : null}
        </div>
      ))}
    </section>
  );
}

export function LernplanView() {
  const { api, toast, setView, setCourse } = useStudio();
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);

  const laden = useCallback(() => {
    setFehler(null);
    api("lernplan").then(setDaten).catch((e) => setFehler(e.message || "Lernplan konnte nicht geladen werden."));
  }, [api]);
  useEffect(laden, [laden]);

  const erledigt = (modul, thema) =>
    !!daten?.module.find((m) => m.name === modul)?.themen.find((t) => t.id === thema)?.erledigt;

  const umschalten = async (modul, thema, an) => {
    // sofort anzeigen, der Plan wird danach neu gerechnet (erledigte Themen fallen aus den Wochen)
    setDaten((d) => ({
      ...d,
      module: d.module.map((m) => m.name !== modul ? m : {
        ...m, themen: m.themen.map((t) => (t.id === thema ? { ...t, erledigt: an } : t)),
      }),
    }));
    try {
      await api("lernplan/thema", { method: "POST", body: { modul, thema, erledigt: an } });
      if (an) toast("Als gelernt markiert. Der Rest verteilt sich neu.");
      laden();
    } catch (err) {
      toast(`Nicht gespeichert: ${err.message}`);
      laden();
    }
  };

  const modulOeffnen = (name) => {
    setCourse(name);
    save("modul-detail", name);
    setView("modul");
  };

  if (fehler) {
    return (
      <div className="lp-body">
        <div className="stu-error-box">
          <span>{fehler}</span>
          <button type="button" className="stu-tbtn is-pri" onClick={laden}>Erneut versuchen</button>
        </div>
      </div>
    );
  }
  if (!daten) return <Loading text="Lernplan wird gerechnet …" />;

  const gelernt = daten.module.flatMap((m) => m.themen.filter((t) => t.erledigt).map((t) => ({ modul: m.name, ...t })));

  return (
    <div className="lp-body">
      <header className="lp-kopf">
        <h2>Lernplan</h2>
        <p className="st-text">
          Die Themen jedes Moduls verteilt auf die Wochen bis zur Prüfung, die letzte Woche ist für die Wiederholung.
          Hake ab, was sitzt: Der Rest verteilt sich neu. Neue Wochen aus Moodle kommen von selbst dazu.
        </p>
      </header>

      {daten.module.length === 0 ? (
        <div className="stu-empty-box">
          <span>
            Noch keine Prüfung eingetragen. Übernimm deine Prüfungen aus dem Prüfungsplan, dann entsteht hier der Plan.
          </span>
          <button type="button" className="stu-tbtn is-pri" onClick={() => setView("studium")}>Zum Prüfungsplan</button>
        </div>
      ) : (
        <>
          <ul className="lp-module">
            {daten.module.map((m) => (
              <ModulKopf
                key={m.name}
                m={m}
                onModul={() => modulOeffnen(m.name)}
                onKarten={() => { setCourse(m.name); setView("karten"); }}
              />
            ))}
          </ul>
          <div className="lp-wochen">
            {daten.wochen.map((w) => (
              <Woche key={w.start} w={w} aktuell={daten.woche} erledigt={erledigt} onToggle={umschalten} />
            ))}
          </div>
        </>
      )}

      {gelernt.length ? (
        <details className="stu-panel lp-gelernt">
          <summary>Schon gelernt ({gelernt.length})</summary>
          <ul className="lp-themen">
            {gelernt.map((t) => {
              const id = `lp-g-${t.modul}-${t.id}`.replace(/\s+/g, "-");
              return (
                <li key={id} className="is-erledigt">
                  <input id={id} type="checkbox" checked onChange={() => umschalten(t.modul, t.id, false)} />
                  <label htmlFor={id}>{t.name}</label>
                  <span className="lp-chip">{t.modul}</span>
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}

      {daten.ohne_pruefung.length ? (
        <section className="stu-panel">
          <div className="stu-panel-head"><h3>Ohne Prüfungsdatum</h3></div>
          <ul className="lp-ohne">
            {daten.ohne_pruefung.map((m) => (
              <li key={m.name}>
                <strong>{m.name}</strong>
                <span className="lp-sub">
                  {LN_TEXT[m.leistungsnachweis] || "Leistungsnachweis unbekannt"} · {m.themen} Themen
                </span>
              </li>
            ))}
          </ul>
          <p className="st-text">
            Für einen Plan braucht das Modul eine Prüfung im Kalender.{" "}
            <button type="button" className="stu-tbtn" onClick={() => setView("studium")}>Prüfungsplan</button>
          </p>
        </section>
      ) : null}
    </div>
  );
}

// Kurzfassung für «Heute»: was diese Woche laut Lernplan dran ist. Ohne Prüfung im Kalender: nichts.
export function DieseWoche() {
  const { api, setView } = useStudio();
  const [daten, setDaten] = useState(null);
  useEffect(() => {
    api("lernplan").then(setDaten).catch(() => setDaten(null));
  }, [api]);
  const w = daten?.wochen.find((x) => x.start === daten.woche);
  if (!w) return null;
  return (
    <section className="stu-panel lp-heute" aria-label="Diese Woche lernen">
      <div className="stu-panel-head">
        <h3>{daten.woche > daten.heute ? "Nächste Woche lernen" : "Diese Woche lernen"}</h3>
        <button type="button" className="stu-tbtn" onClick={() => setView("lernplan")}>Lernplan</button>
      </div>
      <ul className="lp-heute-liste">
        {w.module.map((m) => (
          <li key={m.modul}>
            <span className="lp-eintrag-modul">{m.modul}</span>
            <span>
              {[...m.themen.map((t) => t.name), ...(m.wiederholung ? ["Wiederholung und Karteikarten"] : [])].join(" · ")}
              {m.pruefung ? ` · Prüfung ${tag(m.pruefung, { weekday: "short", day: "numeric", month: "short" })}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default LernplanView;
