// Studio.jsx: Hauptansicht und Layout-Geruest des Studium-Workspace
import React from "react";
import { StudioProvider, useStudio } from "./store.jsx";
import { Rail } from "./Rail.jsx";
import { Icon } from "../ui/Icon.jsx";
import { ResizeHandle } from "../ui/ResizeHandle.jsx";
import { load, save } from "../ui/storage.js";
import { useMedia } from "../ui/hooks.js";
import { Explorer } from "../explorer/Explorer.jsx";
import { DocArea } from "../doc/DocArea.jsx";
import { ReadMode } from "../read/ReadMode.jsx";
import { KartenView } from "../karten/KartenView.jsx";
import { Calendar } from "../plan/Calendar.jsx";
import { Overview } from "../plan/Overview.jsx";
import { Search } from "../plan/Search.jsx";
import { ModulView } from "../modul/ModulView.jsx";
import { GraphView } from "../graph/GraphView.jsx";
import { ChatPanel } from "../chat/ChatPanel.jsx";
import { UploadModal } from "../upload/UploadModal.jsx";
import { ErrorBoundary } from "../ui/ErrorBoundary.jsx";

import "../styles/tokens.css";
import "../styles/shell.css";

const { useEffect, useState, useCallback } = React;

function injectFonts() {
  if (typeof document === "undefined") return;
  if (!document.getElementById("stu-fonts")) {
    const link = document.createElement("link");
    link.id = "stu-fonts";
    link.rel = "stylesheet";
    link.href =
      "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&family=Manrope:wght@400;500;600;700;800&family=Newsreader:ital,opsz,wght@0,6..72,400..700;1,6..72,400..700&display=swap";
    document.head.appendChild(link);
  }
}

function StudioLayout() {
  const {
    dark,
    mobile,
    mobilePane,
    setMobilePane,
    view,
    setView,
    leftOpen,
    setLeftOpen,
    leftTab,
    setLeftTab,
    rightOpen,
    setRightOpen,
    toastMessage,
    uploadOpen,
    setUploadOpen,
    dirty,
    activeId,
    theme,
    cycleTheme,
  } = useStudio();

  // Zwischenbreiten: Chat (<= 1200 px) und Dateien (<= 900 px) als Overlay statt im Layout,
  // damit die Mitte mindestens rund 560 px breit bleibt
  const chatOverlay = useMedia("(max-width: 1200px)") && !mobile;
  const leftOverlay = useMedia("(max-width: 900px)") && !mobile;
  const [moreOpen, setMoreOpen] = useState(false);

  // Beim Wechsel in die Zwischenbreite den Chat einklappen
  useEffect(() => {
    if (chatOverlay) setRightOpen(false);
  }, [chatOverlay, setRightOpen]);

  // Datei geoeffnet: Overlay der Dateien schliessen
  useEffect(() => {
    if (leftOverlay && activeId) setLeftOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // Warnung beim Neuladen oder Schliessen, solange der Editor ungespeicherte Aenderungen hat
  useEffect(() => {
    if (!dirty) return undefined;
    function onBeforeUnload(e) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // Verstellbare Breiten fuer linke und rechte Seitenleiste mit Speicherung
  const [leftWidth, setLeftWidth] = useState(() => {
    const val = Number(load("sidebar-left-width", 272));
    return Number.isFinite(val) && val >= 180 && val <= 600 ? val : 272;
  });
  const [rightWidth, setRightWidth] = useState(() => {
    const val = Number(load("sidebar-right-width", 392));
    return Number.isFinite(val) && val >= 280 && val <= 800 ? val : 392;
  });

  const handleResizeLeft = useCallback((w) => {
    setLeftWidth(w);
    save("sidebar-left-width", w);
  }, []);

  const handleResetLeft = useCallback(() => {
    setLeftWidth(272);
    save("sidebar-left-width", 272);
  }, []);

  const handleResizeRight = useCallback((w) => {
    setRightWidth(w);
    save("sidebar-right-width", w);
  }, []);

  const handleResetRight = useCallback(() => {
    setRightWidth(392);
    save("sidebar-right-width", 392);
  }, []);

  // Globale Tastenkombinationen: ⌘K (Suche), ⌘B (Linke Leiste), ⌘J (Agent), ⌘1 (Dateien).
  // ⌘2 (alter Sessions-Tab) entfaellt, Sessions waehlt man im Chat-Kopf.
  useEffect(() => {
    function onKeyDown(e) {
      if (!(e.metaKey || e.ctrlKey)) return;

      if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        setView((prev) => (prev === "search" ? "work" : "search"));
      } else if (e.key === "b" || e.key === "B") {
        e.preventDefault();
        setLeftOpen((prev) => !prev);
      } else if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        setRightOpen((prev) => !prev);
      } else if (e.key === "1") {
        e.preventDefault();
        setView((prev) => (prev !== "work" ? "work" : prev));
        setLeftTab("files");
        setLeftOpen(true);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setLeftOpen, setLeftTab, setRightOpen, setView]);

  useEffect(() => {
    injectFonts();
  }, []);

  // Auf mobilen Geraeten steuert mobilePane die sichtbare Ansicht
  const showLeft = mobile ? mobilePane === "files" : leftOpen;
  const showRight = mobile ? mobilePane === "chat" : rightOpen;
  const showMain = mobile
    ? mobilePane === "doc" || mobilePane === "calendar"
    : true;

  // Bestimme die in der Mitte anzuzeigende Hauptkomponente
  let mainContent = null;
  const activeView = mobile && mobilePane === "calendar"
    ? "calendar"
    : view;

  switch (activeView) {
    case "read":
      mainContent = <ReadMode />;
      break;
    case "karten":
      mainContent = <KartenView />;
      break;
    case "calendar":
      mainContent = <Calendar />;
      break;
    case "overview":
      mainContent = <Overview />;
      break;
    case "modul":
      mainContent = <ModulView />;
      break;
    case "graph":
      mainContent = <GraphView />;
      break;
    case "search":
      mainContent = <Search />;
      break;
    case "work":
    default:
      mainContent = <DocArea />;
      break;
  }

  const rootClass = `stu ${dark ? "stu-dark" : "stu-light"} ${mobile ? "is-mobile" : ""}`.trim();
  const showOverlayBackdrop = (leftOverlay && showLeft) || (chatOverlay && showRight);

  // Ansichten, die in der unteren Leiste keinen eigenen Knopf haben
  const moreItems = [
    { id: "read", icon: "read", label: "Lesemodus" },
    { id: "karten", icon: "cards", label: "Karteikarten" },
    { id: "search", icon: "search", label: "Suche" },
    { id: "modul", icon: "modul", label: "Modulübersicht" },
    { id: "overview", icon: "overview", label: "Übersicht" },
    { id: "graph", icon: "graph", label: "LangGraph" },
  ];
  const moreActive = mobilePane === "doc" && moreItems.some((m) => m.id === view && m.id !== "read");

  return (
    <div className={rootClass}>
      {!mobile && <Rail />}

      {showLeft && (
        <>
          <aside
            className={"stu-left" + (leftOverlay ? " is-overlay" : "")}
            style={!mobile ? { width: `${leftWidth}px` } : undefined}
            aria-label="Seitenleiste"
          >
            <div className="stu-left-h">
              <span className="stu-left-title">Dateien</span>
              {!mobile && (
                <button
                  type="button"
                  className="stu-icbtn"
                  onClick={() => setLeftOpen(false)}
                  title="Seitenleiste einklappen (⌘B)"
                  aria-label="Seitenleiste einklappen"
                >
                  <Icon n="left" />
                </button>
              )}
            </div>
            <div className="stu-left-body">
              <ErrorBoundary name="Dateien">
                <Explorer />
              </ErrorBoundary>
            </div>
          </aside>
          {!mobile && !leftOverlay && (
            <ResizeHandle
              direction="left"
              width={leftWidth}
              onResize={handleResizeLeft}
              onReset={handleResetLeft}
              minWidth={180}
              maxWidth={500}
            />
          )}
        </>
      )}

      {showMain && (
        <main className="stu-main">
          <ErrorBoundary name="Diese Ansicht" resetKey={activeView}>
            {mainContent}
          </ErrorBoundary>
        </main>
      )}

      {showOverlayBackdrop && (
        <div
          className="stu-overlay-backdrop"
          onClick={() => {
            if (leftOverlay) setLeftOpen(false);
            if (chatOverlay) setRightOpen(false);
          }}
          aria-hidden="true"
        />
      )}

      {!mobile && showRight && !chatOverlay && (
        <ResizeHandle
          direction="right"
          width={rightWidth}
          onResize={handleResizeRight}
          onReset={handleResetRight}
          minWidth={280}
          maxWidth={700}
        />
      )}

      <aside
        className={"stu-chat" + (showRight ? "" : " is-hidden") + (chatOverlay ? " is-overlay" : "")}
        style={!mobile && showRight ? { width: `${rightWidth}px` } : undefined}
        aria-label="Study Agent Chat"
      >
        <ErrorBoundary name="Chat">
          <ChatPanel />
        </ErrorBoundary>
      </aside>

      {mobile && (
        <nav className="stu-bottom" aria-label="Mobile Hauptnavigation">
          <button
            type="button"
            className={mobilePane === "files" ? "is-on" : ""}
            onClick={() => setMobilePane("files")}
          >
            <Icon n="files" />
            <span>Dateien</span>
          </button>
          <button
            type="button"
            className={
              mobilePane === "doc" && (view === "work" || view === "read") ? "is-on" : ""
            }
            onClick={() => {
              setMobilePane("doc");
              if (view !== "work" && view !== "read") setView("work");
            }}
          >
            <Icon n="doc" />
            <span>Dokument</span>
          </button>
          <button
            type="button"
            className={mobilePane === "chat" ? "is-on" : ""}
            onClick={() => setMobilePane("chat")}
          >
            <Icon n="chat" />
            <span>Agent</span>
          </button>
          <button
            type="button"
            className={
              mobilePane === "calendar" || (mobilePane === "doc" && view === "calendar")
                ? "is-on"
                : ""
            }
            onClick={() => {
              setView("calendar");
              setMobilePane("calendar");
            }}
          >
            <Icon n="cal" />
            <span>Kalender</span>
          </button>
          <button
            type="button"
            className={moreActive || moreOpen ? "is-on" : ""}
            onClick={() => setMoreOpen((v) => !v)}
            aria-expanded={moreOpen}
          >
            <Icon n="more" />
            <span>Mehr</span>
          </button>
        </nav>
      )}

      {mobile && moreOpen && (
        <div className="stu-moremenu-backdrop" onClick={() => setMoreOpen(false)}>
          <div className="stu-moremenu" role="menu" onClick={(e) => e.stopPropagation()}>
            {moreItems.map((m) => (
              <button
                key={m.id}
                type="button"
                role="menuitem"
                className={mobilePane === "doc" && view === m.id ? "is-on" : ""}
                onClick={() => {
                  setView(m.id);
                  setMobilePane("doc");
                  setMoreOpen(false);
                }}
              >
                <Icon n={m.icon} />
                <span>{m.label}</span>
              </button>
            ))}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMoreOpen(false);
                setUploadOpen(true);
              }}
            >
              <Icon n="upload" />
              <span>Hochladen</span>
            </button>
            <button type="button" role="menuitem" onClick={cycleTheme}>
              <Icon n={dark ? "sun" : "moon"} />
              <span>Darstellung: {theme === "system" ? "System" : theme === "light" ? "Hell" : "Dunkel"}</span>
            </button>
          </div>
        </div>
      )}

      {/* Toast auf oberster Ebene, damit er auch ueber Fenstern sichtbar ist */}
      {toastMessage ? <div className="stu-toast" role="status">{toastMessage}</div> : null}

      <ErrorBoundary name="Upload-Fenster" overlay resetKey={uploadOpen} onReset={() => setUploadOpen(false)}>
        <UploadModal isOpen={uploadOpen} onClose={() => setUploadOpen(false)} />
      </ErrorBoundary>
    </div>
  );
}

export function Studio() {
  return (
    <StudioProvider>
      <StudioLayout />
    </StudioProvider>
  );
}

export default Studio;
