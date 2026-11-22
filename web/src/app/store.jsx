// store.jsx: Zentraler Zustand fuer den Studium-Workspace (Studio)
import React from "react";
import * as files from "../lib/files.js";
import { api } from "./api.js";
import { load, save } from "../ui/storage.js";
import { useMedia } from "../ui/hooks.js";

const { createContext, useContext, useState, useEffect, useMemo, useCallback, useRef } = React;

function findPathInTree(tree, rootName, targetPath) {
  if (!tree?.roots) return null;
  const rootNode = tree.roots.find((r) => r.root === rootName);
  if (!rootNode) return null;

  function walk(nodes) {
    if (!nodes) return null;
    for (const node of nodes) {
      if (node.path === targetPath) return node;
      if (node.children) {
        const found = walk(node.children);
        if (found) return found;
      }
    }
    return null;
  }
  return walk(rootNode.children);
}

function findNameInTree(tree, rootName, targetName, courseFolder) {
  if (!tree?.roots || !courseFolder) return null;
  const rootNode = tree.roots.find((r) => r.root === rootName);
  if (!rootNode?.children) return null;

  const courseNode = rootNode.children.find(
    (c) => c.name === courseFolder || c.path === courseFolder
  );
  if (!courseNode) return null;

  function walk(nodes) {
    if (!nodes) return null;
    for (const node of nodes) {
      if (node.name === targetName && node.type !== "dir") return node;
      if (node.children) {
        const found = walk(node.children);
        if (found) return found;
      }
    }
    return null;
  }
  return walk(courseNode.children || [courseNode]);
}

export function pdfForTab(tab, tree) {
  if (!tab || !tab.path) return null;

  // Wenn der Tab selbst bereits eine PDF-Datei ist
  if (tab.root === "moodle" && tab.path.toLowerCase().endsWith(".pdf")) {
    return { root: "moodle", path: tab.path };
  }

  let candidate = tab.path;
  if (candidate.endsWith(".folien.md")) {
    candidate = candidate.slice(0, -".folien.md".length);
  } else if (candidate.endsWith(".zusammenfassung.md")) {
    candidate = candidate.slice(0, -".zusammenfassung.md".length);
  } else if (candidate.endsWith(".cheatsheet.md")) {
    candidate = candidate.slice(0, -".cheatsheet.md".length);
  } else if (candidate.endsWith(".md")) {
    candidate = candidate.slice(0, -3);
  }

  if (!candidate.toLowerCase().endsWith(".pdf")) {
    candidate += ".pdf";
  }

  // 1. Suche nach exaktem Pfad unter moodle
  const direct = findPathInTree(tree, "moodle", candidate);
  if (direct) {
    return { root: "moodle", path: direct.path };
  }

  // 2. Fallback: Suche nach Dateinamen unter moodle, beschraenkt auf den Kursordner
  const pathParts = tab.path.split("/");
  const courseFolder = pathParts.length > 1 ? pathParts[0] : null;
  const fileName = candidate.split("/").pop();

  if (courseFolder && fileName) {
    const byName = findNameInTree(tree, "moodle", fileName, courseFolder);
    if (byName) {
      return { root: "moodle", path: byName.path };
    }
  }

  return null;
}

const StudioContext = createContext(null);

const _norm = (s) => String(s || "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();

// Farbe zu einem Kursnamen; Kalender und Suche liefern den Namen manchmal leicht abweichend
function modulFarbeAus(farben, palette, name) {
  if (!name) return "var(--muted)";
  if (farben[name]) return farben[name];
  const n = _norm(name);
  for (const [k, f] of Object.entries(farben)) {
    const kn = _norm(k);
    if (kn === n || kn.startsWith(n) || n.startsWith(kn)) return f;
  }
  const p = palette.length ? palette : ["#64748b"];
  return p[[...n].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 9973, 7) % p.length];
}

export function StudioProvider({ children }) {
  // Geraete-Erkennung
  const mobile = useMedia("(max-width: 760px)");
  const sysDark = useMedia("(prefers-color-scheme: dark)");

  // Theme
  const [theme, setThemeState] = useState(() => load("theme", "system"));
  const dark = theme === "dark" || (theme === "system" && sysDark);

  const cycleTheme = useCallback(() => {
    setThemeState((curr) => {
      const next = curr === "system" ? "light" : curr === "light" ? "dark" : "system";
      save("theme", next);
      return next;
    });
  }, []);

  // Ansichten und Leisten
  const [view, setView] = useState("overview");  // Startseite «Heute»
  const [leftTab, setLeftTab] = useState("files");
  const [leftOpen, setLeftOpen] = useState(true);
  // Zwischenbreiten (<= 1200 px): Chat startet eingeklappt, damit die Mitte Platz hat
  const [rightOpen, setRightOpen] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return true;
    return !window.matchMedia("(max-width: 1200px)").matches;
  });
  const [mobilePane, setMobilePane] = useState("doc");

  // Kurse
  const [courses, setCourses] = useState([]);
  const [coursesLoading, setCoursesLoading] = useState(true);
  const [coursesError, setCoursesError] = useState(null);
  const [course, setCourseState] = useState(() => load("course", ""));
  const [coursesTick, setCoursesTick] = useState(0);
  const reloadCourses = useCallback(() => setCoursesTick((t) => t + 1), []);

  useEffect(() => {
    let active = true;
    setCoursesLoading(true);
    api("kurse")
      .then((res) => {
        if (!active) return;
        const list = Array.isArray(res) ? res : res?.kurse || [];
        setCourses(list);
        setCoursesLoading(false);
        setCourseState((curr) => {
          if (curr && list.some((k) => (k.name || k) === curr)) return curr;
          const first = list[0]?.name || (typeof list[0] === "string" ? list[0] : "");
          if (first) save("course", first);
          return first || "";
        });
      })
      .catch((err) => {
        if (!active) return;
        setCoursesError(err);
        setCoursesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [coursesTick]);

  const setCourse = useCallback((name) => {
    setCourseState(name);
    save("course", name);
  }, []);

  // Modulfarben (state/modulfarben.json): pro Modul eine feste, eindeutige Farbe
  const [farben, setFarben] = useState({});
  const [palette, setPalette] = useState([]);
  useEffect(() => {
    api("modulfarben")
      .then((d) => { setFarben(d.farben || {}); setPalette(d.palette || []); })
      .catch(() => {});
  }, [coursesTick]);
  const setModulFarbe = useCallback(async (name, farbe) => {
    const d = await api("modulfarben", { method: "PUT", body: { name, farbe } });
    setFarben(d.farben || {});
  }, []);
  const modulFarbe = useCallback((name) => modulFarbeAus(farben, palette, name), [farben, palette]);

  // Dateibaum
  const [tree, setTree] = useState(null);
  const [treeLoading, setTreeLoading] = useState(true);

  const reloadTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const data = await files.tree();
      setTree(data);
      return data;
    } catch (err) {
      setTree({ roots: [], error: err.message });
      return null;
    } finally {
      setTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadTree();
  }, [reloadTree]);

  // Tabs: offene Dokumente, aktiver Tab und PDF-Zustand ueberleben ein Neuladen (localStorage)
  const [tabs, setTabs] = useState(() => {
    const saved = load("open-tabs", []);
    if (!Array.isArray(saved)) return [];
    return saved.filter((t) => t && typeof t.id === "string" && t.root && t.path);
  });
  const [activeId, setActiveId] = useState(() => {
    const id = load("active-tab", null);
    return typeof id === "string" ? id : null;
  });

  const activeTab = useMemo(
    () => tabs.find((t) => t.id === activeId) || null,
    [tabs, activeId]
  );

  const setActive = useCallback(
    (id) => {
      setActiveId(id);
      if (mobile) setMobilePane("doc");
    },
    [mobile]
  );

  // PDF
  const [pdfOpen, setPdfOpen] = useState(() => load("pdf-open", false) === true);
  const [pdfPage, setPdfPage] = useState(() => {
    const n = Number(load("pdf-page", 1));
    return Number.isFinite(n) && n > 0 ? n : 1;
  });

  useEffect(() => {
    // Nur die Felder speichern, die zum Wiederoeffnen noetig sind
    const slim = tabs.map(({ id, root, path, name, kind, editable, page }) => ({
      id, root, path, name, kind, editable, ...(page !== undefined ? { page } : {}),
    }));
    save("open-tabs", slim);
    const valid = activeId && tabs.some((t) => t.id === activeId) ? activeId : tabs[0]?.id || null;
    save("active-tab", valid);
  }, [tabs, activeId]);

  useEffect(() => {
    save("pdf-open", pdfOpen);
    save("pdf-page", pdfPage);
  }, [pdfOpen, pdfPage]);
  const [sync, setSync] = useState(true);

  const openFile = useCallback(
    (root, path, opts = {}) => {
      if (path && (path.endsWith("/begriffe.md") || path === "begriffe.md")) {
        setView("karten");
        return;
      }

      let actualPath = path;
      let node = findPathInTree(tree, root, actualPath);
      if (!node && root === "moodle") {
        const parts = actualPath.split("/");
        const courseFolder = parts.length > 1 ? parts[0] : course;
        const fileName = parts[parts.length - 1];
        const found = findNameInTree(tree, "moodle", fileName, courseFolder);
        if (found) {
          actualPath = found.path;
          node = found;
        }
      }

      const id = root + ":" + actualPath;
      const name = actualPath.split("/").pop() || actualPath;
      const ext = (name.split(".").pop() || "").toLowerCase();
      const kind = ext === "pdf" ? "pdf" : ext === "md" ? "markdown" : "text";

      const editable = node?.editable ?? (root !== "moodle");

      setTabs((prev) => {
        if (prev.some((t) => t.id === id)) return prev;
        return [...prev, { id, root, path: actualPath, name, kind, editable, ...opts }];
      });

      setActiveId(id);

      if (opts.page !== undefined) {
        setPdfPage(Number(opts.page));
        setPdfOpen(true);
      }

      if (kind === "pdf") {
        setPdfOpen(true);
      }

      setMobilePane("doc");
      setView((prevView) =>
        prevView === "work" || prevView === "read" ? prevView : "work"
      );
    },
    [tree, course]
  );

  const closeTab = useCallback(
    (id) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.id !== id);
        if (activeId === id) {
          const idx = prev.findIndex((t) => t.id === id);
          const fallback = next[idx] || next[idx - 1] || null;
          setActiveId(fallback ? fallback.id : null);
        }
        return next;
      });
    },
    [activeId]
  );

  const openFolie = useCallback(
    (n) => {
      const pageNum = Number(n);
      const validPage = !Number.isNaN(pageNum) && pageNum > 0 ? pageNum : 1;
      setPdfPage(validPage);
      setPdfOpen(true);
      setView("work");
      if (mobile) {
        setMobilePane("doc");
      }
    },
    [mobile]
  );

  const pdfFor = useCallback(
    (targetTab) => pdfForTab(targetTab || activeTab, tree),
    [tree, activeTab]
  );

  // Ungespeicherte Aenderungen
  const [dirty, setDirty] = useState(false);

  // Chat
  const [chatRequest, setChatRequest] = useState(null);

  const clearChatRequest = useCallback(() => {
    setChatRequest(null);
  }, []);

  const sendToChat = useCallback(
    (req) => {
      setChatRequest({ ...(req || {}), timestamp: Date.now() });
      setRightOpen(true);
      if (mobile) {
        setMobilePane("chat");
      }
    },
    [mobile]
  );

  const chatContext = useMemo(
    () => ({
      file: activeTab || undefined,
      folie: pdfOpen ? pdfPage : undefined,
    }),
    [activeTab, pdfOpen, pdfPage]
  );

  // Toast
  const [toastMessage, setToastMessage] = useState("");
  const toastTimeoutRef = useRef(null);

  // Upload Modal
  const [uploadOpen, setUploadOpen] = useState(false);

  const toast = useCallback((text, timeoutMs = 2800) => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToastMessage(text);
    if (text) {
      toastTimeoutRef.current = setTimeout(() => {
        setToastMessage("");
        toastTimeoutRef.current = null;
      }, timeoutMs);
    }
  }, []);

  const value = useMemo(
    () => ({
      course,
      setCourse,
      courses,
      coursesLoading,
      coursesError,
      reloadCourses,
      modulFarbe,
      setModulFarbe,
      farbPalette: palette,
      theme,
      dark,
      cycleTheme,
      view,
      setView,
      leftTab,
      setLeftTab,
      leftOpen,
      setLeftOpen,
      rightOpen,
      setRightOpen,
      mobile,
      mobilePane,
      setMobilePane,
      tree,
      treeLoading,
      reloadTree,
      tabs,
      activeId,
      activeTab,
      openFile,
      closeTab,
      setActive,
      pdfOpen,
      setPdfOpen,
      pdfPage,
      setPdfPage,
      openFolie,
      pdfFor,
      sync,
      setSync,
      chatContext,
      chatRequest,
      clearChatRequest,
      sendToChat,
      toast,
      toastMessage,
      uploadOpen,
      setUploadOpen,
      api,
      dirty,
      setDirty,
      isDirty: dirty,
      setIsDirty: setDirty,
    }),
    [
      course,
      setCourse,
      courses,
      coursesLoading,
      coursesError,
      reloadCourses,
      modulFarbe,
      setModulFarbe,
      palette,
      theme,
      dark,
      cycleTheme,
      view,
      leftTab,
      leftOpen,
      rightOpen,
      mobile,
      mobilePane,
      tree,
      treeLoading,
      reloadTree,
      tabs,
      activeId,
      activeTab,
      openFile,
      closeTab,
      setActive,
      pdfOpen,
      pdfPage,
      openFolie,
      pdfFor,
      sync,
      chatContext,
      chatRequest,
      clearChatRequest,
      sendToChat,
      toast,
      toastMessage,
      uploadOpen,
      dirty,
    ]
  );

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio() {
  const ctx = useContext(StudioContext);
  if (!ctx) {
    throw new Error("useStudio muss innerhalb von StudioProvider verwendet werden.");
  }
  return ctx;
}
