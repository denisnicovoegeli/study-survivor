// Icon.jsx: SVG-Symbole fuer die Shell, Navigation und Schaltflaechen
import React from "react";

const PATHS = {
  files: "M3 6h6l2 2h10v11H3z",
  chat: "M4 5h16v11H9l-5 4z",
  sessions: "M5 6h14M5 12h14M5 18h9",
  search: "M11 5a6 6 0 1 0 0 12a6 6 0 0 0 0-12zM20 20l-4.5-4.5",
  read: "M4 5h7a2 2 0 0 1 2 2v12a2 2 0 0 0-2-2H4zM20 5h-7a2 2 0 0 0-2 2v12a2 2 0 0 1 2-2h7z",
  sun: "M12 4v2M12 18v2M4 12h2M18 12h2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4M12 8a4 4 0 1 0 0 8a4 4 0 0 0 0-8z",
  moon: "M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z",
  exit: "M10 5H5v14h5M14 8l4 4l-4 4M18 12H9",
  left: "M4 4h16v16H4zM9 4v16",
  right: "M4 4h16v16H4zM15 4v16",
  split: "M4 4h16v16H4zM12 4v16",
  doc: "M6 3h9l4 4v14H6zM14 3v5h5",
  lock: "M7 11h10v9H7zM9 11V8a3 3 0 0 1 6 0v3",
  plus: "M12 5v14M5 12h14",
  send: "M12 19V5M6 11l6-6l6 6",
  cal: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  board: "M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v13h-4z",
  edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  overview: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  projects: "M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z",
  toc: "M4 6h16M4 12h10M4 18h14",
  cards: "M4 4h12v16H4zM8 2h12v16h-2",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5l-5 5M12 3v12",
  x: "M18 6L6 18M6 6l12 12",
  check: "M20 6L9 17l-5-5",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  modul: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
};

export function Icon({ n, className = "" }) {
  const d = PATHS[n];
  return (
    <svg
      className={`stu-ic ${className}`.trim()}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {d ? <path d={d} /> : null}
    </svg>
  );
}

export default Icon;
