// ResizeHandle.jsx: Wiederverwendbarer Ziehgriff fuer verstellbare Seitenleisten
import React from "react";

const { useState, useEffect, useRef } = React;

/**
 * ResizeHandle ermoeglicht das Verstellen von Leisten per Ziehgriff.
 *
 * Props:
 * - direction: 'left' (Griff sitzt rechts an linker Leiste) oder 'right' (Griff sitzt links an rechter Leiste)
 * - width: aktuelle Breite in Pixeln
 * - onResize: (newWidth) => void
 * - onReset: () => void (Doppelklick setzt auf Standardwert zurueck)
 * - minWidth: minimale Breite (Standard: 180)
 * - maxWidth: maximale Breite (Standard: 600)
 */
export function ResizeHandle({
  direction = "left",
  width,
  onResize,
  onReset,
  minWidth = 180,
  maxWidth = 600,
  title = "Breite anpassen (Doppelklick zum Zurücksetzen)",
}) {
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startWidth: width });

  useEffect(() => {
    if (!dragging) return;

    function onMouseMove(e) {
      const delta = e.clientX - dragRef.current.startX;
      const rawWidth =
        direction === "left"
          ? dragRef.current.startWidth + delta
          : dragRef.current.startWidth - delta;
      const clamped = Math.max(minWidth, Math.min(maxWidth, Math.round(rawWidth)));
      if (typeof onResize === "function") {
        onResize(clamped);
      }
    }

    function onMouseUp() {
      setDragging(false);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
  }, [dragging, direction, minWidth, maxWidth, onResize]);

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startWidth: width };
    setDragging(true);
  }

  function handleDoubleClick(e) {
    e.preventDefault();
    if (typeof onReset === "function") {
      onReset();
    }
  }

  const cls = `stu-resizer stu-resizer-${direction} ${dragging ? "is-dragging" : ""}`.trim();

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-valuenow={Math.round(width)}
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      tabIndex={0}
      className={cls}
      onMouseDown={handleMouseDown}
      onDoubleClick={handleDoubleClick}
      title={title}
    />
  );
}

export default ResizeHandle;
