// FarbWahl.jsx: Farbe eines Moduls wählen (Palette, eigene Farbe, Standard)
import React from "react";
import { useStudio } from "../app/store.jsx";

const { useState, useEffect, useRef } = React;

export function FarbWahl({ name }) {
  const { modulFarbe, setModulFarbe, farbPalette, toast } = useStudio();
  const [offen, setOffen] = useState(false);
  const box = useRef(null);
  const farbe = modulFarbe(name);

  useEffect(() => {
    if (!offen) return undefined;
    const zu = (e) => { if (box.current && !box.current.contains(e.target)) setOffen(false); };
    const esc = (e) => { if (e.key === "Escape") setOffen(false); };
    document.addEventListener("mousedown", zu);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", zu); document.removeEventListener("keydown", esc); };
  }, [offen]);

  const waehlen = async (f) => {
    try {
      await setModulFarbe(name, f);
      setOffen(false);
    } catch (err) {
      toast(`Farbe nicht gespeichert: ${err.message}`);
    }
  };

  return (
    <span className="fw" ref={box}>
      <button
        type="button"
        className="fw-knopf"
        style={{ "--mc": farbe }}
        aria-haspopup="true"
        aria-expanded={offen}
        aria-label={`Farbe von ${name} ändern`}
        title="Farbe ändern"
        onClick={(e) => { e.stopPropagation(); setOffen((o) => !o); }}
      />
      {offen ? (
        <span className="fw-pop" role="dialog" aria-label={`Farbe für ${name}`} onClick={(e) => e.stopPropagation()}>
          <span className="fw-raster">
            {farbPalette.map((f) => (
              <button
                key={f}
                type="button"
                className={"fw-feld" + (f === farbe ? " is-an" : "")}
                style={{ "--mc": f }}
                aria-label={`Farbe ${f}`}
                aria-pressed={f === farbe}
                onClick={() => waehlen(f)}
              />
            ))}
          </span>
          <label className="fw-eigen">
            Eigene Farbe
            <input type="color" value={/^#[0-9a-f]{6}$/i.test(farbe) ? farbe : "#3b82f6"} onChange={(e) => waehlen(e.target.value)} />
          </label>
          <button type="button" className="stu-tbtn fw-standard" onClick={() => waehlen(null)}>Standardfarbe</button>
        </span>
      ) : null}
    </span>
  );
}

export default FarbWahl;
