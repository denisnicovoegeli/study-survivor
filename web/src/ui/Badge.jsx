// Badge.jsx: Dateityp-Abzeichen nach Dateiendung (PDF, MD, IPYNB, DOCX etc.)
import React from "react";

function getExtension(filename) {
  if (!filename || typeof filename !== "string") return "";
  return (filename.split(".").pop() || "").toLowerCase();
}

export function Badge({ name, f, className = "" }) {
  const filename = name || f || "";
  const ext = getExtension(filename);
  const label = ext === "md" ? "MD" : ext.toUpperCase().slice(0, 4) || "DATEI";

  return (
    <span className={`stu-bdg stu-bdg-${ext} ${className}`.trim()}>
      {label}
    </span>
  );
}

export default Badge;
