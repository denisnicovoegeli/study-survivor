// Rail.jsx: Hauptnavigation am linken Fensterrand, nach Bereichen statt nach Werkzeugen
import React from "react";
import { Icon } from "../ui/Icon.jsx";
import { useStudio } from "./store.jsx";

// Bereiche der Hauptnavigation; views = Ansichten, in denen der Eintrag aktiv ist
export const BEREICHE = [
  { id: "overview", icon: "overview", label: "Heute", views: ["overview"] },
  { id: "modul", icon: "modul", label: "Module", views: ["modul"] },
  { id: "read", icon: "read", label: "Lernen", views: ["read", "lernplan", "karten", "search"] },
  { id: "calendar", icon: "cal", label: "Kalender", views: ["calendar"] },
  { id: "studium", icon: "board", label: "Studium", views: ["studium"] },
  { id: "agent", icon: "graph", label: "Agent", views: ["agent"] },
];

function RailButton({ icon, label, title, on, onClick, pressed }) {
  return (
    <button
      type="button"
      className={"stu-rail-item" + (on ? " is-on" : "")}
      onClick={onClick}
      title={title || label}
      aria-pressed={pressed}
      aria-current={on && pressed === undefined ? "page" : undefined}
    >
      <Icon n={icon} />
      <span className="stu-rail-label">{label}</span>
    </button>
  );
}

export function Rail() {
  const { leftOpen, setLeftOpen, view, setView, dark, theme, cycleTheme, setUploadOpen } = useStudio();

  return (
    <nav className="stu-rail" aria-label="Hauptnavigation">
      <div className="stu-logo" title="Study Survivor">
        St
      </div>

      {BEREICHE.map((b) => (
        <RailButton
          key={b.id}
          icon={b.icon}
          label={b.label}
          on={b.views.includes(view)}
          onClick={() => setView(b.id)}
        />
      ))}

      <span className="stu-sep" />

      <RailButton
        icon="doc"
        label="Dokument"
        title="Geöffnete Dokumente"
        on={view === "work"}
        onClick={() => setView("work")}
      />
      <RailButton
        icon="files"
        label="Dateien"
        title={leftOpen ? "Dateien ausblenden (⌘B)" : "Dateien einblenden (⌘B)"}
        on={leftOpen}
        pressed={leftOpen}
        onClick={() => setLeftOpen((prev) => !prev)}
      />
      <RailButton
        icon="upload"
        label="Hochladen"
        title="Ordner oder Dokumente hochladen"
        onClick={() => setUploadOpen(true)}
      />

      <span className="stu-grow" />

      <RailButton
        icon={dark ? "sun" : "moon"}
        label="Design"
        title={`Darstellung: ${theme} (${dark ? "Dunkel" : "Hell"})`}
        onClick={cycleTheme}
      />
    </nav>
  );
}

export default Rail;
