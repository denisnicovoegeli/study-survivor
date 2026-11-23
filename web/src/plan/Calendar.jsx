// Calendar.jsx: Monats- und Agendaansicht fuer Termine, Fristen und Deadlines (T5)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Loading } from "../ui/Loading.jsx";
import { useAsync } from "../ui/hooks.js";
import { load, save } from "../ui/storage.js";
import {
  parseDue,
  dueDateStr,
  isDateOnly,
  dayKey,
  fmtTime,
  kindLabel,
  courseShort,
} from "./utils.js";
import "./plan.css";

const { useState, useMemo, useCallback, useEffect } = React;

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

const KINDS = [
  { value: "abgabe", label: "Abgabe" },
  { value: "pruefung", label: "Prüfung" },
  { value: "praesentation", label: "Präsentation" },
  { value: "meilenstein", label: "Meilenstein" },
  { value: "praesenz", label: "Präsenzpflicht" },
  { value: "ausfall", label: "Vorlesungsausfall" },
  { value: "termin", label: "Allgemeiner Termin" },
];

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const montag = (d) => addDays(startOfDay(d), -((d.getDay() + 6) % 7));
const ganztaegig = (e) => Boolean(e.all_day || isDateOnly(e.due));
const istWichtig = (e) => e.kind === "abgabe" || e.kind === "pruefung";

function zeitraumTitel(ansicht, anker, tage) {
  if (ansicht === "tag") {
    return anker.toLocaleDateString("de-CH", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }
  if (ansicht === "monat") return anker.toLocaleDateString("de-CH", { month: "long", year: "numeric" });
  const a = tage[0];
  const b = tage[tage.length - 1];
  const kw = kalenderwoche(a);
  const von = a.toLocaleDateString("de-CH", { day: "numeric", month: a.getMonth() === b.getMonth() ? undefined : "short" });
  return `KW ${kw} · ${von} – ${b.toLocaleDateString("de-CH", { day: "numeric", month: "short", year: "numeric" })}`;
}

function kalenderwoche(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  return Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 86400000 + 1) / 7);
}

// Ein Termin als Zeile: Zeit, Farbbalken des Moduls, Titel, Modul und Art
function TerminZeile({ e, farbe, onClick, kompakt, gross, mitDatum }) {
  const d = parseDue(e.due);
  const zeit = ganztaegig(e) ? (kompakt ? "" : "ganztägig") : fmtTime(e.due);
  return (
    <button type="button" className={"kal-termin" + (kompakt ? " is-kompakt" : "") + (gross ? " is-gross" : "")
      + (istWichtig(e) ? " is-wichtig" : "") + (e.kind === "lektion" ? " is-lektion" : "")}
      style={{ "--mc": farbe }} onClick={(evt) => onClick(evt, e)} title={`${e.course}: ${e.name}`}>
      {mitDatum && d ? (
        <span className="kal-termin-datum"><b>{d.getDate()}</b>{d.toLocaleDateString("de-CH", { month: "short" })}</span>
      ) : null}
      {zeit ? <span className="kal-termin-zeit">{zeit}</span> : null}
      <span className="kal-termin-text">
        <span className="kal-termin-titel">{e.name}</span>
        <span className="kal-termin-meta">
          {courseShort(e.course)} · {kindLabel(e.kind)}
          {gross && e.source ? ` · ${e.source}` : ""}
        </span>
      </span>
    </button>
  );
}

export function Calendar() {
  const { api, toast, mobile, courses, course: activeCourse, modulFarbe } = useStudio();

  // Ansicht (Tag, Woche, Monat) und Bezugsdatum, gemerkt pro Gerät
  const [ansicht, setAnsichtState] = useState(() => {
    const a = load("calendar-ansicht", "woche");
    return ["tag", "woche", "monat"].includes(a) ? a : "woche";
  });
  const setAnsicht = (a) => { setAnsichtState(a); save("calendar-ansicht", a); };
  const [anker, setAnker] = useState(() => startOfDay(new Date()));

  // Filter: ausgeblendete Module, Unterricht, Moodle-Fristen
  const [ausgeblendet, setAusgeblendet] = useState(() => new Set(load("calendar-module-aus", []) || []));
  const [hideMoodle, setHideMoodle] = useState(() => load("calendar-hide-moodle", false) === true);
  const [hideLektion, setHideLektion] = useState(() => load("calendar-hide-lektion", false) === true);

  // Modal-Zustand: null | "create" | "edit" | "view"
  const [modalMode, setModalMode] = useState(null);
  const [activeEvent, setActiveEvent] = useState(null);
  // Fehlermeldung im Fenster selbst (Toast liegt sonst hinter dem Overlay)
  const [modalError, setModalError] = useState("");

  const closeModal = useCallback(() => {
    setModalMode(null);
    setModalError("");
  }, []);

  // Escape schliesst das Termin-Fenster
  useEffect(() => {
    if (!modalMode) return undefined;
    function onKey(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeModal();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modalMode, closeModal]);

  // Formulardaten
  const [formData, setFormData] = useState({
    course: "",
    datum: "",
    zeit: "",
    titel: "",
    art: "termin",
    quelle: "",
  });
  const [saving, setSaving] = useState(false);

  // Termine vom Server abrufen
  const { data, loading, error, reload } = useAsync(
    useCallback(() => api("calendar?days=240&vergangen=120"), [api]),
    [api]
  );

  const rawEvents = useMemo(() => data?.events || [], [data]);

  // Module für die Filterleiste: eingetragene Kurse plus Kurse, die nur in Terminen vorkommen
  const modulNamen = useMemo(() => {
    const namen = (courses || []).map((k) => (typeof k === "string" ? k : k?.name)).filter(Boolean);
    for (const e of rawEvents) if (e.course && !namen.includes(e.course)) namen.push(e.course);
    return namen;
  }, [courses, rawEvents]);

  const umschalten = (name) => setAusgeblendet((alt) => {
    const neu = new Set(alt);
    if (neu.has(name)) neu.delete(name); else neu.add(name);
    save("calendar-module-aus", [...neu]);
    return neu;
  });
  const nurModul = (name) => {
    const neu = new Set(modulNamen.filter((n) => n !== name));
    save("calendar-module-aus", [...neu]);
    setAusgeblendet(neu);
  };
  const alleModule = () => { save("calendar-module-aus", []); setAusgeblendet(new Set()); };

  const events = useMemo(() => rawEvents.filter((e) => {
    if (hideMoodle && e.is_moodle && !e.is_termin) return false;
    if (hideLektion && e.kind === "lektion") return false;
    return !ausgeblendet.has(e.course);
  }), [rawEvents, hideMoodle, hideLektion, ausgeblendet]);

  // Gruppierung nach Tag, innerhalb des Tages: ganztägig zuerst, dann nach Uhrzeit
  const byDay = useMemo(() => {
    const map = {};
    for (const ev of events) {
      const d = parseDue(ev.due);
      if (!d) continue;
      (map[dayKey(d)] ||= []).push(ev);
    }
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => (ganztaegig(b) - ganztaegig(a)) || (parseDue(a.due) - parseDue(b.due)));
    }
    return map;
  }, [events]);

  const todayKey = dayKey(new Date());

  // Tage der aktuellen Ansicht
  const tage = useMemo(() => {
    if (ansicht === "tag") return [anker];
    if (ansicht === "woche") return Array.from({ length: 7 }, (_, i) => addDays(montag(anker), i));
    const erster = new Date(anker.getFullYear(), anker.getMonth(), 1);
    const start = montag(erster);
    const imMonat = new Date(anker.getFullYear(), anker.getMonth() + 1, 0).getDate();
    const n = ((erster.getDay() + 6) % 7) + imMonat > 35 ? 42 : 35;
    return Array.from({ length: n }, (_, i) => addDays(start, i));
  }, [ansicht, anker]);

  const blaettern = (richtung) => {
    if (ansicht === "tag") setAnker(addDays(anker, richtung));
    else if (ansicht === "woche") setAnker(addDays(anker, 7 * richtung));
    else setAnker(new Date(anker.getFullYear(), anker.getMonth() + richtung, 1));
  };
  const zuTag = (d) => { setAnker(startOfDay(d)); setAnsicht("tag"); };

  // Kommende Termine (Seitenleiste der Monatsansicht)
  const upcoming = useMemo(() => {
    const heute = startOfDay(new Date());
    return events.filter((e) => { const d = parseDue(e.due); return d && d >= heute; }).slice(0, 25);
  }, [events]);

  // Dialog oeffnen: Neuer Termin
  const handleOpenCreate = (prefillDate = "") => {
    const defaultCourse = activeCourse || (courses[0]?.name || courses[0] || "");
    const todayStr = prefillDate || dayKey(new Date());
    setFormData({
      course: typeof defaultCourse === "object" ? defaultCourse.name : defaultCourse,
      datum: todayStr,
      zeit: "",
      titel: "",
      art: "abgabe",
      quelle: "Eigene Notiz",
    });
    setActiveEvent(null);
    setModalError("");
    setModalMode("create");
  };

  // Dialog oeffnen: Termin anklicken (Bearbeiten oder Anschauen)
  const handleEventClick = (e, ev) => {
    e.stopPropagation();
    setActiveEvent(ev);
    const d = parseDue(ev.due);
    const dateStr = dueDateStr(ev.due);
    const isAllDay = Boolean(ev.all_day || isDateOnly(ev.due));
    const timeStr = !isAllDay && d ? fmtTime(ev.due) : "";

    setFormData({
      course: ev.course || "",
      datum: dateStr,
      zeit: timeStr,
      titel: ev.name || "",
      art: ev.kind || "termin",
      quelle: ev.source || "",
    });

    setModalError("");
    if (ev.editable) {
      setModalMode("edit");
    } else {
      setModalMode("view");
    }
  };

  // Termin speichern (neu oder aktualisiert)
  const handleSave = async (e) => {
    e.preventDefault();
    if (!formData.course) {
      setModalError("Bitte einen Kurs auswählen.");
      return;
    }
    if (!formData.datum) {
      setModalError("Bitte ein Datum eingeben.");
      return;
    }
    if (!formData.titel.trim()) {
      setModalError("Bitte einen Titel eingeben.");
      return;
    }

    setModalError("");
    setSaving(true);
    try {
      if (modalMode === "create") {
        await api("calendar/events", {
          method: "POST",
          body: {
            course: formData.course,
            datum: formData.datum,
            titel: formData.titel.trim(),
            art: formData.art,
            zeit: formData.zeit.trim() || null,
            quelle: formData.quelle.trim() || null,
          },
        });
        toast("Termin erfolgreich angelegt.");
      } else if (modalMode === "edit" && activeEvent) {
        const origDateStr = dueDateStr(activeEvent.due) || formData.datum;
        await api("calendar/events", {
          method: "PUT",
          body: {
            course: formData.course,
            original: {
              datum: origDateStr,
              titel: activeEvent.termin_titel || activeEvent.name,
            },
            updated: {
              datum: formData.datum,
              titel: formData.titel.trim(),
              art: formData.art,
              zeit: formData.zeit.trim() || null,
              quelle: formData.quelle.trim() || null,
            },
          },
        });
        toast("Termin erfolgreich geändert.");
      }
      closeModal();
      await reload();
    } catch (err) {
      const msg = "Fehler beim Speichern: " + (err.message || String(err));
      setModalError(msg);
      toast(msg);
    } finally {
      setSaving(false);
    }
  };

  // Termin loeschen
  const handleDelete = async () => {
    if (!activeEvent || !activeEvent.editable) return;
    const ok = window.confirm(`Termin "${activeEvent.name}" wirklich löschen?`);
    if (!ok) return;

    setModalError("");
    setSaving(true);
    try {
      const origDateStr = dueDateStr(activeEvent.due) || formData.datum;
      await api("calendar/events", {
        method: "DELETE",
        body: {
          course: activeEvent.course || formData.course,
          datum: origDateStr,
          titel: activeEvent.termin_titel || activeEvent.name,
        },
      });
      toast("Termin gelöscht.");
      closeModal();
      await reload();
    } catch (err) {
      const msg = "Fehler beim Löschen: " + (err.message || String(err));
      setModalError(msg);
      toast(msg);
    } finally {
      setSaving(false);
    }
  };

  // ICS-Datei herunterladen
  const handleDownloadIcs = async () => {
    try {
      const SDK = window.__HERMES_PLUGIN_SDK__;
      const fetchFn = SDK?.authedFetch || window.fetch;
      const res = await fetchFn("/api/plugins/studium/calendar.ics");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "studium.ics";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast("Kalender als studium.ics heruntergeladen.");
    } catch (err) {
      toast("Fehler beim Herunterladen: " + (err?.message || err));
    }
  };

  // Abo-Link in die Zwischenablage kopieren
  const handleCopyIcsLink = () => {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const url = `${origin}/api/plugins/studium/calendar.ics`;
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard
        .writeText(url)
        .then(() => toast("ICS-Abo-Link kopiert."))
        .catch(() => toast(url));
    } else {
      toast(url);
    }
  };

  const titel = zeitraumTitel(ansicht, anker, tage);
  const imZeitraum = tage.reduce((n, d) => n + (byDay[dayKey(d)]?.length || 0), 0);

  return (
    <div className="stu-board kal">
      <header className="kal-kopf">
        <div className="kal-zeile">
          <h2 className="kal-titel">{titel}</h2>
          <span className="stu-viewh-desc">
            {loading && !data ? "Termine werden geladen …" : `${imZeitraum} ${imZeitraum === 1 ? "Termin" : "Termine"}`}
          </span>
          <div className="stu-grow" />
          <div className="kal-nav">
            <button type="button" className="stu-tbtn" onClick={() => blaettern(-1)} aria-label="Zurück">‹</button>
            <button type="button" className="stu-tbtn" onClick={() => setAnker(startOfDay(new Date()))}>Heute</button>
            <button type="button" className="stu-tbtn" onClick={() => blaettern(1)} aria-label="Weiter">›</button>
          </div>
          <div className="stu-seg kal-ansicht" role="tablist" aria-label="Ansicht">
            {[["tag", "Tag"], ["woche", "Woche"], ["monat", "Monat"]].map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={ansicht === id}
                className={ansicht === id ? "is-on" : ""} onClick={() => setAnsicht(id)}>{label}</button>
            ))}
          </div>
          <button type="button" className="stu-tbtn is-pri" onClick={() => handleOpenCreate(ansicht === "tag" ? dayKey(anker) : "")}>
            <Icon n="plus" /><span>Termin</span>
          </button>
        </div>

        <div className="kal-filter" aria-label="Filter">
          <span className="kal-filter-label">Module</span>
          {modulNamen.map((n) => {
            const an = !ausgeblendet.has(n);
            return (
              <button key={n} type="button" className={"kal-modul" + (an ? " is-an" : "")}
                style={{ "--mc": modulFarbe(n) }} aria-pressed={an} title={`${n} (Doppelklick: nur dieses Modul)`}
                onClick={() => umschalten(n)} onDoubleClick={() => nurModul(n)}>
                <span className="kal-punkt" aria-hidden="true" />
                {courseShort(n) || n}
              </button>
            );
          })}
          {ausgeblendet.size ? (
            <button type="button" className="kal-link" onClick={alleModule}>Alle zeigen</button>
          ) : null}
          <span className="kal-trenner" aria-hidden="true" />
          <label className="kal-schalter">
            <input type="checkbox" checked={!hideLektion}
              onChange={(e) => { setHideLektion(!e.target.checked); save("calendar-hide-lektion", !e.target.checked); }} />
            Unterricht
          </label>
          <label className="kal-schalter">
            <input type="checkbox" checked={!hideMoodle}
              onChange={(e) => { setHideMoodle(!e.target.checked); save("calendar-hide-moodle", !e.target.checked); }} />
            Moodle-Fristen
          </label>
          <div className="stu-grow" />
          <button type="button" className="kal-link" onClick={handleDownloadIcs} title="Kalender als .ics-Datei herunterladen">.ics</button>
          <button type="button" className="kal-link" onClick={handleCopyIcsLink} title="Abo-Link für Kalender-Apps kopieren">Abo-Link</button>
        </div>
      </header>

      {error ? (
        <div style={{ padding: "16px 20px" }}>
          <div className="stu-error-box">
            <span>Fehler beim Laden der Kalenderdaten: {error.message || String(error)}</span>
            <button type="button" className="stu-tbtn is-pri" onClick={reload}>Erneut versuchen</button>
          </div>
        </div>
      ) : loading && !data ? (
        <div style={{ padding: "40px", display: "grid", placeItems: "center" }}>
          <Loading text="Kalender wird geladen …" />
        </div>
      ) : ansicht === "monat" ? (
        <div className="stu-cal">
          <div className="stu-cal-main">
            <div className="stu-month" style={{ gridTemplateRows: `auto repeat(${tage.length / 7}, minmax(0, 1fr))` }}>
              {WEEKDAYS.map((w) => <div key={w} className="stu-dow">{w}</div>)}
              {tage.map((d) => {
                const k = dayKey(d);
                const dayEvs = byDay[k] || [];
                return (
                  <div key={k}
                    className={`stu-day ${d.getMonth() !== anker.getMonth() ? "is-out" : ""} ${k === todayKey ? "is-today" : ""}`.trim()}
                    onClick={() => zuTag(d)} title={`${d.toLocaleDateString("de-CH")}: Tagesansicht öffnen`}>
                    <span className="stu-dnum">{d.getDate()}</span>
                    {dayEvs.slice(0, 3).map((e, idx) => (
                      <div key={idx} className={`stu-ev ${istWichtig(e) ? "is-bold" : ""}`.trim()}
                        style={{ "--mc": modulFarbe(e.course) }} title={`${e.course}: ${e.name}`}
                        onClick={(evt) => handleEventClick(evt, e)}>
                        {!ganztaegig(e) ? <span className="kal-zeit">{fmtTime(e.due)}</span> : null}{e.name}
                      </div>
                    ))}
                    {dayEvs.length > 3 && <div className="stu-more">+{dayEvs.length - 3} weitere</div>}
                  </div>
                );
              })}
            </div>
          </div>
          <aside className="stu-agenda" aria-label="Als Nächstes">
            <span className="stu-label" style={{ margin: 0 }}>Als Nächstes</span>
            {upcoming.length === 0 ? (
              <div className="stu-empty-box"><span>Keine anstehenden Termine.</span></div>
            ) : upcoming.map((e, idx) => (
              <TerminZeile key={idx} e={e} farbe={modulFarbe(e.course)} onClick={handleEventClick} mitDatum />
            ))}
          </aside>
        </div>
      ) : ansicht === "woche" ? (
        <div className="kal-woche">
          {tage.map((d) => {
            const k = dayKey(d);
            const dayEvs = byDay[k] || [];
            return (
              <section key={k} className={"kal-wtag" + (k === todayKey ? " is-heute" : "") + (d < startOfDay(new Date()) ? " is-vorbei" : "")}
                aria-label={d.toLocaleDateString("de-CH", { weekday: "long", day: "numeric", month: "long" })}>
                <button type="button" className="kal-wtag-kopf" onClick={() => zuTag(d)} title="Tagesansicht">
                  <span className="kal-wtag-name">{WEEKDAYS[(d.getDay() + 6) % 7]}</span>
                  <span className="kal-wtag-nr">{d.getDate()}.{d.getMonth() + 1}.</span>
                </button>
                <div className="kal-wtag-liste">
                  {dayEvs.length === 0 ? <span className="kal-leer">–</span> : dayEvs.map((e, idx) => (
                    <TerminZeile key={idx} e={e} farbe={modulFarbe(e.course)} onClick={handleEventClick} kompakt />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <div className="kal-tag">
          {(byDay[dayKey(anker)] || []).length === 0 ? (
            <div className="stu-empty-box">
              <span>Keine Termine an diesem Tag{ausgeblendet.size || hideLektion || hideMoodle ? " (Filter aktiv)" : ""}.</span>
              <button type="button" className="stu-tbtn" onClick={() => handleOpenCreate(dayKey(anker))}>Termin erfassen</button>
            </div>
          ) : (byDay[dayKey(anker)] || []).map((e, idx) => (
            <TerminZeile key={idx} e={e} farbe={modulFarbe(e.course)} onClick={handleEventClick} gross />
          ))}
        </div>
      )}

      {/* Modal-Dialog: Termin erfassen, bearbeiten oder ansehen */}
      {modalMode && (
        <div
          className="stu-modal-backdrop"
          onClick={() => closeModal()}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="stu-modal"
            style={{ maxWidth: "480px", width: "100%" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="stu-modal-head">
              <h3>
                {modalMode === "create"
                  ? "Termin hinzufügen"
                  : modalMode === "edit"
                  ? "Termin bearbeiten"
                  : "Termin-Details (Moodle)"}
              </h3>
              <button
                type="button"
                className="stu-icbtn"
                onClick={() => closeModal()}
                aria-label="Dialog schliessen"
              >
                <Icon n="x" />
              </button>
            </div>

            {modalError ? (
              <div className="stu-modal-error" role="alert">
                {modalError}
              </div>
            ) : null}

            {modalMode === "view" ? (
              <div className="stu-modal-body">
                <div className="stu-form-group">
                  <label>Kurs</label>
                  <div style={{ fontSize: "13.5px", fontWeight: 600 }}>{formData.course}</div>
                </div>
                <div className="stu-form-group">
                  <label>Titel</label>
                  <div style={{ fontSize: "14px" }}>{formData.titel}</div>
                </div>
                <div className="stu-form-group">
                  <label>Datum und Uhrzeit</label>
                  <div>
                    {formData.datum} {formData.zeit ? `um ${formData.zeit} Uhr` : "(ganztägig)"}
                  </div>
                </div>
                <div className="stu-form-group">
                  <label>Art</label>
                  <div>{kindLabel(formData.art)}</div>
                </div>
                <div className="stu-form-group">
                  <label>Hinweis</label>
                  <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                    Dieser Termin stammt aus dem Moodle-Kalender und ist schreibgeschützt.
                  </div>
                </div>
                {activeEvent?.url && (
                  <div className="stu-form-group">
                    <label>Moodle-Link</label>
                    <a
                      href={activeEvent.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--acc)", textDecoration: "none", fontSize: "13px" }}
                    >
                      In Moodle öffnen ↗
                    </a>
                  </div>
                )}
                <div className="stu-modal-foot">
                  <button
                    type="button"
                    className="stu-tbtn is-pri"
                    onClick={() => closeModal()}
                  >
                    Schliessen
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSave} className="stu-modal-body">
                <div className="stu-form-group">
                  <label htmlFor="ev-course">Kurs</label>
                  <select
                    id="ev-course"
                    className="stu-select"
                    value={formData.course}
                    onChange={(e) => setFormData({ ...formData, course: e.target.value })}
                    required
                  >
                    <option value="" disabled>
                      Kurs auswählen …
                    </option>
                    {courses.map((c) => {
                      const name = typeof c === "string" ? c : c.name;
                      return (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      );
                    })}
                  </select>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div className="stu-form-group">
                    <label htmlFor="ev-date">Datum (JJJJ-MM-TT)</label>
                    <input
                      id="ev-date"
                      type="date"
                      className="stu-input"
                      value={formData.datum}
                      onChange={(e) => setFormData({ ...formData, datum: e.target.value })}
                      required
                    />
                  </div>

                  <div className="stu-form-group">
                    <label htmlFor="ev-time">Uhrzeit (optional, z.B. 13:00)</label>
                    <input
                      id="ev-time"
                      type="text"
                      placeholder="HH:MM"
                      className="stu-input"
                      value={formData.zeit}
                      onChange={(e) => setFormData({ ...formData, zeit: e.target.value })}
                    />
                  </div>
                </div>

                <div className="stu-form-group">
                  <label htmlFor="ev-title">Titel</label>
                  <input
                    id="ev-title"
                    type="text"
                    className="stu-input"
                    value={formData.titel}
                    onChange={(e) => setFormData({ ...formData, titel: e.target.value })}
                    placeholder="z.B. Projektabgabe Zwischenbericht"
                    required
                  />
                </div>

                <div className="stu-form-group">
                  <label htmlFor="ev-kind">Art des Termins</label>
                  <select
                    id="ev-kind"
                    className="stu-select"
                    value={formData.art}
                    onChange={(e) => setFormData({ ...formData, art: e.target.value })}
                  >
                    {KINDS.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="stu-form-group">
                  <label htmlFor="ev-source">Quelle (optional)</label>
                  <input
                    id="ev-source"
                    type="text"
                    className="stu-input"
                    value={formData.quelle}
                    onChange={(e) => setFormData({ ...formData, quelle: e.target.value })}
                    placeholder="z.B. Semesterprogramm HS 2026.pdf, Seite 1"
                  />
                </div>

                <div className="stu-modal-foot">
                  {modalMode === "edit" && (
                    <button
                      type="button"
                      className="stu-tbtn is-danger"
                      onClick={handleDelete}
                      disabled={saving}
                      style={{ marginRight: "auto" }}
                    >
                      Löschen
                    </button>
                  )}

                  <button
                    type="button"
                    className="stu-tbtn"
                    onClick={() => closeModal()}
                    disabled={saving}
                  >
                    Abbrechen
                  </button>

                  <button
                    type="submit"
                    className="stu-tbtn is-pri"
                    disabled={saving}
                  >
                    {saving ? "Wird gespeichert …" : modalMode === "create" ? "Hinzufügen" : "Speichern"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Calendar;
