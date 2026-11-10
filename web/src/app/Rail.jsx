// Rail.jsx: Vertikale Navigations- und Werkzeugleiste am linken Fensterrand
import React from "react";
import { Icon } from "../ui/Icon.jsx";
import { useStudio } from "./store.jsx";

export function Rail() {
  const {
    leftOpen,
    setLeftOpen,
    view,
    setView,
    dark,
    theme,
    cycleTheme,
    dirty,
    setUploadOpen,
  } = useStudio();


  function toggleView(targetView) {
    setView(view === targetView ? "work" : targetView);
  }

  return (
    <nav className="stu-rail" aria-label="Werkzeuge und Navigation">
      <div className="stu-logo" title="Studium Studio">
        St
      </div>

      {/* Datei-Seitenleiste: in allen Ansichten ein- und ausklappbar */}
      <button
        type="button"
        className={leftOpen ? "is-on" : ""}
        onClick={() => setLeftOpen((prev) => !prev)}
        title={leftOpen ? "Dateien ausblenden (⌘B)" : "Dateien einblenden (⌘B)"}
        aria-label={leftOpen ? "Dateien ausblenden" : "Dateien einblenden"}
        aria-pressed={leftOpen}
      >
        <Icon n="files" />
      </button>

      <button
        type="button"
        className={view === "search" ? "is-on" : ""}
        onClick={() => toggleView("search")}
        title="Suche (⌘K)"
      >
        <Icon n="search" />
      </button>

      <span className="stu-sep" />

      <button
        type="button"
        className={view === "read" ? "is-on" : ""}
        onClick={() => toggleView("read")}
        title="Lesemodus"
      >
        <Icon n="read" />
      </button>

      <button
        type="button"
        className={view === "karten" ? "is-on" : ""}
        onClick={() => toggleView("karten")}
        title="Karteikarten (Begriffe)"
      >
        <Icon n="cards" />
      </button>

      <button
        type="button"
        className={view === "calendar" ? "is-on" : ""}
        onClick={() => toggleView("calendar")}
        title="Kalender"
      >
        <Icon n="cal" />
      </button>


      <button
        type="button"
        className={view === "modul" ? "is-on" : ""}
        onClick={() => toggleView("modul")}
        title="Modulübersicht"
      >
        <Icon n="modul" />
      </button>

      <button
        type="button"
        className={view === "overview" ? "is-on" : ""}
        onClick={() => toggleView("overview")}
        title="Übersicht"
      >
        <Icon n="overview" />
      </button>

      <button
        type="button"
        className={view === "graph" ? "is-on" : ""}
        onClick={() => toggleView("graph")}
        title="LangGraph: wie der Agent gebaut ist"
      >
        <Icon n="graph" />
      </button>


      <button
        type="button"
        onClick={() => setUploadOpen(true)}
        title="Ordner oder Dokumente hochladen"
      >
        <Icon n="upload" />
      </button>

      <span className="stu-grow" />

      <button
        type="button"
        onClick={cycleTheme}
        title={`Darstellung: ${theme} (${dark ? "Dunkel" : "Hell"})`}
      >
        <Icon n={dark ? "sun" : "moon"} />
      </button>

    </nav>
  );
}

export default Rail;
