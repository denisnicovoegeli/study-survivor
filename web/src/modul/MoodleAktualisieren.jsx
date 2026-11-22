// MoodleAktualisieren.jsx: Knopf, der moodle-dl, Umwandlung und Suchindex im Hintergrund startet
import React from "react";
import { useStudio } from "../app/store.jsx";

const { useState, useEffect, useRef, useCallback } = React;

function ergebnisText(z) {
  const teile = [];
  if (z.neue_dateien) teile.push(`${z.neue_dateien} neue ${z.neue_dateien === 1 ? "Datei" : "Dateien"} aus Moodle`);
  if (z.neu_umgewandelt) teile.push(`${z.neu_umgewandelt} neu lesbar`);
  if (!teile.length) teile.push("Nichts Neues in Moodle");
  return teile.join(" · ");
}

export function MoodleAktualisieren({ onFertig, kompakt = false }) {
  const { api, toast } = useStudio();
  const [z, setZ] = useState(null);
  const timer = useRef(null);
  const lief = useRef(false);
  const fertig = useRef(onFertig);
  fertig.current = onFertig;

  const abfragen = useCallback(async () => {
    try {
      const d = await api("moodle/aktualisieren");
      setZ(d);
      if (d.status === "läuft") {
        lief.current = true;
        timer.current = setTimeout(abfragen, 2500);
      } else if (lief.current) {
        lief.current = false;
        if (d.status === "fertig") toast(`Moodle aktualisiert: ${ergebnisText(d)}`, 5000);
        else toast("Aktualisierung mit Fehlern beendet, Details beim Knopf.", 5000);
        fertig.current?.(d);
      }
    } catch {
      /* Status nicht erreichbar: Knopf bleibt bedienbar */
    }
  }, [api, toast]);

  useEffect(() => {
    abfragen();
    return () => clearTimeout(timer.current);
  }, [abfragen]);

  const starten = async () => {
    try {
      const d = await api("moodle/aktualisieren", { method: "POST" });
      setZ(d);
      lief.current = true;
      clearTimeout(timer.current);
      timer.current = setTimeout(abfragen, 1500);
    } catch (err) {
      toast(err.message || "Konnte nicht starten.", 5000);
    }
  };

  const laeuft = z?.status === "läuft";
  const aktuell = laeuft ? z.schritte?.find((s) => s.status === "läuft") : null;
  const nr = aktuell ? z.schritte.indexOf(aktuell) + 1 : 0;
  const fehlgeschlagen = z?.status === "fehler" ? z.schritte?.filter((s) => s.status === "fehler") : [];

  return (
    <div className={"ma" + (kompakt ? " is-kompakt" : "")}>
      <button
        type="button"
        className="stu-tbtn is-pri"
        onClick={starten}
        disabled={laeuft}
        title="Holt neue Dateien aus Moodle (nur lesend), liest ihren Text aus und nimmt sie in die Suche des Agenten auf"
      >
        {laeuft ? "Aktualisiert …" : "Moodle aktualisieren"}
      </button>
      <span className="ma-status" role="status" aria-live="polite">
        {laeuft && aktuell
          ? `Schritt ${nr} von ${z.schritte.length}: ${aktuell.titel}`
          : z?.status === "fertig" && !kompakt
            ? ergebnisText(z)
            : fehlgeschlagen.length
              ? `Fehler bei: ${fehlgeschlagen.map((s) => s.titel).join(", ")} (logs/moodle-aktualisieren.log)`
              : ""}
      </span>
    </div>
  );
}

export default MoodleAktualisieren;
