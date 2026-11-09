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
  courseHue,
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

export function Calendar() {
  const { api, toast, mobile, courses, course: activeCourse } = useStudio();

  // Aktueller Monat
  const [month, setMonth] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });

  // Ausgewaehlter Tag (optional zur Filterung)
  const [selectedDayKey, setSelectedDayKey] = useState(null);

  // Moodle-Termine ausblenden
  const [hideMoodle, setHideMoodle] = useState(() => load("calendar-hide-moodle", false));

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
    useCallback(() => api("calendar?days=180"), [api]),
    [api]
  );

  const rawEvents = useMemo(() => data?.events || [], [data]);

  // Gefilterte Termine nach Moodle-Ausblendung
  const events = useMemo(() => {
    if (!hideMoodle) return rawEvents;
    // Reine Moodle-Termine ausblenden (is_moodle und nicht is_termin)
    return rawEvents.filter((e) => !(e.is_moodle && !e.is_termin));
  }, [rawEvents, hideMoodle]);

  // Gruppierung nach Tag
  const byDay = useMemo(() => {
    const map = {};
    for (const ev of events) {
      const d = parseDue(ev.due);
      if (!d) continue;
      const k = dayKey(d);
      if (!map[k]) map[k] = [];
      map[k].push(ev);
    }
    return map;
  }, [events]);

  // Kalender-Gitter berechnen (Montag als erster Tag)
  const days = useMemo(() => {
    const firstDayOfWeek = (month.getDay() + 6) % 7;
    const start = new Date(month);
    start.setDate(1 - firstDayOfWeek);
    const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const cellCount = firstDayOfWeek + daysInMonth > 35 ? 42 : 35;
    return Array.from({ length: cellCount }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [month]);

  const todayKey = useMemo(() => dayKey(new Date()), []);

  // Kommende Termine fuer "Als Naechstes"
  const upcoming = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    if (selectedDayKey) {
      return events
        .filter((e) => {
          const d = parseDue(e.due);
          return d && dayKey(d) === selectedDayKey;
        })
        .slice(0, 30);
    }

    return events
      .filter((e) => {
        const d = parseDue(e.due);
        return d && d >= startOfToday;
      })
      .slice(0, 30);
  }, [events, selectedDayKey]);

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

  const monthLabel = month.toLocaleDateString("de-CH", {
    month: "long",
    year: "numeric",
  });

  return (
    <div className="stu-board">
      <header className="stu-viewh">
        <h2>{monthLabel}</h2>
        <span className="stu-viewh-desc">
          {loading && !data
            ? "Termine werden geladen …"
            : `${events.length} ${events.length === 1 ? "Termin" : "Termine"} geladen`}
        </span>

        <div className="stu-grow" />

        {/* Monatsnavigation */}
        <button
          type="button"
          className="stu-tbtn"
          onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
          title="Vorheriger Monat"
          aria-label="Vorheriger Monat"
        >
          ‹
        </button>
        <button
          type="button"
          className="stu-tbtn"
          onClick={() => {
            const now = new Date();
            setMonth(new Date(now.getFullYear(), now.getMonth(), 1));
            setSelectedDayKey(null);
          }}
          title="Zum aktuellen Monat springen"
        >
          Heute
        </button>
        <button
          type="button"
          className="stu-tbtn"
          onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
          title="Nächster Monat"
          aria-label="Nächster Monat"
        >
          ›
        </button>

        {/* Moodle-Filter umschalten */}
        <button
          type="button"
          className={`stu-tbtn ${hideMoodle ? "is-on" : ""}`}
          onClick={() => {
            setHideMoodle((h) => {
              const next = !h;
              save("calendar-hide-moodle", next);
              return next;
            });
          }}
          title={hideMoodle ? "Moodle-Termine wieder einblenden" : "Moodle-Termine ausblenden"}
        >
          <span>{hideMoodle ? "Moodle ausgeblendet" : "Moodle sichtbar"}</span>
        </button>

        {/* Termin hinzufügen */}
        <button
          type="button"
          className="stu-tbtn is-pri"
          onClick={() => handleOpenCreate()}
          title="Eigenen Termin für einen Kurs erfassen"
        >
          <Icon n="plus" />
          <span>Termin hinzufügen</span>
        </button>

        {/* ICS-Aktionen */}
        <button
          type="button"
          className="stu-tbtn"
          onClick={handleDownloadIcs}
          title="Kalender als .ics-Datei herunterladen"
        >
          <Icon n="cal" />
          <span>.ics herunterladen</span>
        </button>

        <button
          type="button"
          className="stu-tbtn"
          onClick={handleCopyIcsLink}
          title="Abo-Link in Zwischenablage kopieren"
        >
          <Icon n="link" />
          <span>Abo-Link</span>
        </button>
      </header>

      {error ? (
        <div style={{ padding: "16px 20px" }}>
          <div className="stu-error-box">
            <span>Fehler beim Laden der Kalenderdaten: {error.message || String(error)}</span>
            <button type="button" className="stu-tbtn is-pri" onClick={reload}>
              Erneut versuchen
            </button>
          </div>
        </div>
      ) : loading && !data ? (
        <div style={{ padding: "40px", display: "grid", placeItems: "center" }}>
          <Loading text="Kalender wird geladen …" />
        </div>
      ) : (
        <div className="stu-cal">
          <div className="stu-cal-main">
            {/* Zeilen nach Anzahl Wochen (5 oder 6), sonst bleibt unten eine leere graue Zeile */}
            <div
              className="stu-month"
              style={{ gridTemplateRows: `auto repeat(${days.length / 7}, minmax(0, 1fr))` }}
            >
              {WEEKDAYS.map((w) => (
                <div key={w} className="stu-dow">
                  {w}
                </div>
              ))}

              {days.map((d) => {
                const k = dayKey(d);
                const isOut = d.getMonth() !== month.getMonth();
                const isToday = k === todayKey;
                const isSelected = k === selectedDayKey;
                const dayEvs = byDay[k] || [];

                return (
                  <div
                    key={k}
                    className={`stu-day ${isOut ? "is-out" : ""} ${isToday ? "is-today" : ""} ${isSelected ? "is-selected" : ""}`.trim()}
                    onClick={() => setSelectedDayKey(isSelected ? null : k)}
                    title={`${d.toLocaleDateString("de-CH")}: ${dayEvs.length} Termine (Klick zum Filtern)`}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span className="stu-dnum">{d.getDate()}</span>
                      {isSelected && (
                        <button
                          type="button"
                          className="stu-tbtn"
                          style={{ padding: "1px 5px", fontSize: "10px", lineHeight: "1" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenCreate(k);
                          }}
                          title="Termin an diesem Tag erfassen"
                        >
                          +
                        </button>
                      )}
                    </div>

                    {dayEvs.slice(0, 3).map((e, idx) => {
                      const isBold = e.kind === "abgabe" || e.kind === "pruefung";
                      const isAllDay = Boolean(e.all_day || isDateOnly(e.due));
                      const time = !isAllDay ? fmtTime(e.due) : "";
                      const timeInfo = time ? ` · ${time} Uhr` : "";
                      const tooltip = `${e.course ? e.course + ": " : ""}${e.name} (${kindLabel(e.kind)}${timeInfo}) · Klick zum Öffnen`;
                      return (
                        <div
                          key={idx}
                          className={`stu-ev ${isBold ? "is-bold" : ""}`.trim()}
                          style={{ "--h": courseHue(e.course), cursor: "pointer" }}
                          title={tooltip}
                          onClick={(evt) => handleEventClick(evt, e)}
                        >
                          {e.name}
                        </div>
                      );
                    })}

                    {dayEvs.length > 3 && (
                      <div className="stu-more">+{dayEvs.length - 3} weitere</div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <aside className="stu-agenda" aria-label="Kommende Termine">
            <div className="stu-agenda-head">
              <span className="stu-label" style={{ margin: 0 }}>
                {selectedDayKey ? `Termine am ${selectedDayKey}` : "Als Nächstes"}
              </span>
              {selectedDayKey && (
                <button
                  type="button"
                  className="stu-tbtn"
                  style={{ fontSize: "11px", padding: "2px 6px" }}
                  onClick={() => setSelectedDayKey(null)}
                >
                  Alle zeigen
                </button>
              )}
            </div>

            {upcoming.length === 0 ? (
              <div className="stu-empty-box">
                <span>Keine anstehenden Termine vorhanden.</span>
              </div>
            ) : (
              upcoming.map((e, idx) => {
                const d = parseDue(e.due);
                const isBold = e.kind === "abgabe" || e.kind === "pruefung";
                const quelle = e.source || (e.quelle === "moodle" ? "Moodle" : "Termine");
                const isAllDay = Boolean(e.all_day || isDateOnly(e.due));
                const timeStr = !isAllDay ? fmtTime(e.due) : "";

                return (
                  <div
                    key={idx}
                    className="stu-agi"
                    style={{ "--h": courseHue(e.course), cursor: "pointer" }}
                    onClick={(evt) => handleEventClick(evt, e)}
                    title="Klicken zum Anzeigen oder Bearbeiten"
                  >
                    <div className="stu-agd">
                      <b>{d ? d.getDate() : "·"}</b>
                      <span>{d ? d.toLocaleDateString("de-CH", { month: "short" }) : ""}</span>
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className={`stu-agt ${isBold ? "is-bold" : ""}`.trim()}>
                        {e.name}
                      </div>

                      <div className="stu-ags">
                        <span className="stu-cdot" />
                        <span>{courseShort(e.course)}</span>
                        <span>·</span>
                        <span style={{ fontWeight: isBold ? 700 : 500 }}>
                          {kindLabel(e.kind)}
                        </span>
                        {timeStr && (
                          <>
                            <span>·</span>
                            <span>{timeStr} Uhr</span>
                          </>
                        )}
                      </div>

                      <div className="stu-src-ref">
                        Quelle: {quelle}
                        {e.url && (
                          <>
                            {" · "}
                            <a
                              href={e.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: "var(--acc)", textDecoration: "none" }}
                              onClick={(clickEv) => clickEv.stopPropagation()}
                            >
                              Moodle ↗
                            </a>
                          </>
                        )}
                      </div>
                    </div>

                    {e.editable && (
                      <button
                        type="button"
                        className="stu-tbtn"
                        style={{ padding: "4px 8px", fontSize: "11px", alignSelf: "center" }}
                        onClick={(evt) => handleEventClick(evt, e)}
                        title="Diesen Termin bearbeiten"
                      >
                        <Icon n="edit" />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </aside>
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
