// Loading.jsx: Ladeanzeige mit Spinner fuer asynchrone Daten und Aktionen
import React from "react";

export function Loading({ text = "Wird geladen …", className = "" }) {
  return (
    <div className={`stu-loading ${className}`.trim()} role="status">
      <span className="stu-spinner" aria-hidden="true" />
      <span className="stu-loading-text">{text}</span>
    </div>
  );
}

export default Loading;
