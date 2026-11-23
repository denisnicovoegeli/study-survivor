// DocArea.jsx: Dokumentbereich mit Tabs, Editor, Vorschau und PDF-Spalte
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Loading } from "../ui/Loading.jsx";
import { linkifyFolien, onFolieClick, firstFolieIn } from "../ui/folien.js";
import { findPathInTree } from "../explorer/tree-utils.js";
import * as files from "../lib/files.js";
import { renderMarkdown } from "../lib/markdown.js";
import { createEditor } from "../lib/editor.js";
import { PdfView } from "../pdf/PdfView.jsx";
import { ModulView } from "../modul/ModulView.jsx";
import "./doc.css";

const { useState, useEffect, useRef, useMemo, useCallback } = React;

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp", "ico"]);

// Modulweiter Speicher: ueberlebt das Aushaengen von DocArea (z. B. bei Ansichtswechsel)
// tabId -> { text: string, mtimeNs: string|number|null, cleanContent: string, isDirty: boolean }
const draftsStore = new Map();
const fileContentCache = new Map();
const imageBlobCache = new Map();

function getFileExtension(filename = "") {
  return (filename.split(".").pop() || "").toLowerCase();
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function formatDate(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return String(isoString);
    return d.toLocaleString("de-CH", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(isoString);
  }
}

// Relative vertikale Position eines Elements im Scroll-Container
function getRelativeTop(element, container) {
  if (!element || !container) return 0;
  const elRect = element.getBoundingClientRect();
  const cRect = container.getBoundingClientRect();
  return elRect.top - cRect.top + container.scrollTop;
}

// Synchronisiert den ungespeichert-Zustand aller Tabs mit dem zentralen Store
function syncStoreDirty(setStoreDirty) {
  if (typeof setStoreDirty !== "function") return;
  let anyDirty = false;
  for (const entry of draftsStore.values()) {
    if (entry.isDirty) {
      anyDirty = true;
      break;
    }
  }
  setStoreDirty(anyDirty);
}

export function DocArea() {
  const {
    mobile,
    dark,
    cycleTheme,
    setView,
    rightOpen,
    setRightOpen,
    tabs = [],
    activeId,
    activeTab,
    closeTab,
    setActive,
    pdfOpen,
    setPdfOpen,
    pdfPage,
    setPdfPage,
    openFolie,
    pdfFor,
    tree,
    openFile,
    sync,
    setSync,
    setDirty: setStoreDirty,
    toast,
    course,
  } = useStudio();

  // Aktiver Tab mit Rueckfall auf den ersten Tab der Liste
  const currentTab = activeTab || (tabs.length > 0 ? tabs[0] : null);

  // Sicherstellen, dass activeId gesetzt ist, wenn Tabs vorhanden sind
  useEffect(() => {
    if (tabs.length > 0 && (!activeId || !tabs.some((t) => t.id === activeId))) {
      setActive(tabs[0].id);
    }
  }, [tabs, activeId, setActive]);

  // Lokale Zustaende fuer Editor, Aenderungen und Speichern (initialisiert aus draftsStore)
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => {
    if (!currentTab) return "";
    return draftsStore.get(currentTab.id)?.text || "";
  });
  const [fileContent, setFileContent] = useState(() => {
    if (!currentTab) return "";
    return draftsStore.get(currentTab.id)?.cleanContent || "";
  });
  const [mtimeNs, setMtimeNs] = useState(() => {
    if (!currentTab) return null;
    return draftsStore.get(currentTab.id)?.mtimeNs ?? null;
  });
  const [dirty, setDirty] = useState(() => {
    if (!currentTab) return false;
    return draftsStore.get(currentTab.id)?.isDirty || false;
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(null); // { serverMtimeNs, detail }

  // Versionen-Dialog
  const [showVersions, setShowVersions] = useState(false);
  const [versionsList, setVersionsList] = useState([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [previewVersion, setPreviewVersion] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Bildanzeige
  const [imageBlobUrl, setImageBlobUrl] = useState(() => {
    if (!currentTab) return null;
    return imageBlobCache.get(currentTab.id) || null;
  });

  // Referenzen
  const cleanContentRef = useRef("");
  const previewRef = useRef(null);
  const editorRef = useRef(null);
  const editorContainerRef = useRef(null);

  // Ref auf die aktuelle Speicher-Funktion, um Mehrfach-Aufrufe und veraltete Closures zu verhindern
  const handleSaveRef = useRef(null);

  // Synchronisation, Ziel-Folien-Ref und Schleifensperre
  const lockRef = useRef({ who: "", until: 0 });
  const syncRef = useRef(sync);
  syncRef.current = sync;
  const pdfPageRef = useRef(pdfPage);
  pdfPageRef.current = pdfPage;
  const targetFolieRef = useRef(null);
  const scrollEndCleanupRef = useRef(null);

  function setLock(who, ms = 150) {
    lockRef.current = { who, until: Date.now() + ms };
  }

  function isLocked(who) {
    const { who: lockedWho, until } = lockRef.current;
    return lockedWho && lockedWho !== who && Date.now() < until;
  }

  // Ungespeichert-Status mit dem globalen Store abgleichen
  useEffect(() => {
    syncStoreDirty(setStoreDirty);
  }, [dirty, setStoreDirty]);

  // Aufraeumen des scrollend-Listeners beim Entladen
  useEffect(() => {
    return () => {
      if (scrollEndCleanupRef.current) {
        scrollEndCleanupRef.current();
      }
    };
  }, []);

  // Dateitypen des aktiven Tabs ermitteln
  const activeExt = getFileExtension(currentTab?.name || currentTab?.path || "");
  const isMarkdown = currentTab?.kind === "markdown" || activeExt === "md";
  const isPdf = currentTab?.kind === "pdf" || activeExt === "pdf";
  const isImage = IMAGE_EXTENSIONS.has(activeExt);
  const isOther = currentTab && !isMarkdown && !isPdf && !isImage;

  // Zugehoerige PDF-Datei pruefen
  const relatedPdf = useMemo(() => {
    if (!currentTab || isPdf) return null;
    return pdfFor(currentTab);
  }, [currentTab, isPdf, pdfFor]);

  // Zugehoerige Zusammenfassung fuer geöffnete PDF-Datei pruefen
  const relatedSummary = useMemo(() => {
    if (!currentTab || !isPdf) return null;
    const baseStem = currentTab.path.replace(/\.pdf$/i, "");
    const zfCandidate = `${baseStem}.zusammenfassung.md`;
    if (findPathInTree(tree, "lernen", zfCandidate)) {
      return { root: "lernen", path: zfCandidate };
    }
    return null;
  }, [currentTab, isPdf, tree]);

  const [summaryContent, setSummaryContent] = useState("");
  useEffect(() => {
    if (!isPdf || !relatedSummary) {
      setSummaryContent("");
      return;
    }
    let active = true;
    files
      .read(relatedSummary.root, relatedSummary.path)
      .then((data) => {
        if (active) setSummaryContent(data.content || "");
      })
      .catch(() => {
        if (active) setSummaryContent("");
      });
    return () => {
      active = false;
    };
  }, [isPdf, relatedSummary]);

  const renderedSummaryHtml = useMemo(() => {
    if (!summaryContent) return "";
    return linkifyFolien(renderMarkdown(summaryContent));
  }, [summaryContent]);

  // Tab-Wechsel und Laden des Dateiinhalts
  useEffect(() => {
    setConflict(null);
    setShowVersions(false);
    setPreviewVersion(null);

    if (!currentTab) {
      setFileContent("");
      setDraft("");
      cleanContentRef.current = "";
      setDirty(false);
      setEditing(false);
      return;
    }

    // Markdown-Dateien immer standardmaessig zum Lesen oeffnen
    setEditing(false);

    const tabId = currentTab.id;

    if (isMarkdown) {
      const cached = draftsStore.get(tabId);
      if (cached) {
        // Bereits im modulweiten Entwurfsspeicher vorhanden
        setFileContent(cached.cleanContent);
        setDraft(cached.text);
        setMtimeNs(cached.mtimeNs);
        cleanContentRef.current = cached.cleanContent;
        setDirty(cached.isDirty);
        setLoading(false);
        return;
      }

      // Noch nicht geladen: vom Server abrufen
      let active = true;
      setLoading(true);

      files
        .read(currentTab.root, currentTab.path)
        .then((data) => {
          if (!active) return;
          const text = data.content || "";
          const serverMtime = data.mtime_ns ?? null;

          draftsStore.set(tabId, {
            text,
            mtimeNs: serverMtime,
            cleanContent: text,
            isDirty: false,
          });
          fileContentCache.set(tabId, text);

          setFileContent(text);
          setDraft(text);
          setMtimeNs(serverMtime);
          cleanContentRef.current = text;
          setDirty(false);
          setLoading(false);
        })
        .catch((err) => {
          if (!active) return;
          setLoading(false);
          toast(`Fehler beim Lesen der Datei: ${err.message || ""}`);
        });

      return () => {
        active = false;
      };
    } else if (isImage) {
      const cachedBlob = imageBlobCache.get(tabId);
      if (cachedBlob) {
        setImageBlobUrl(cachedBlob);
        setLoading(false);
        return;
      }

      let active = true;
      setLoading(true);
      files
        .rawBlobUrl(currentTab.root, currentTab.path)
        .then((url) => {
          if (!active) {
            URL.revokeObjectURL(url);
            return;
          }
          imageBlobCache.set(tabId, url);
          setImageBlobUrl(url);
          setLoading(false);
        })
        .catch((err) => {
          if (!active) return;
          setLoading(false);
          toast(`Fehler beim Laden des Bildes: ${err.message || ""}`);
        });

      return () => {
        active = false;
      };
    } else {
      setLoading(false);
    }
  }, [currentTab?.id, isMarkdown, isImage, toast]);

  // CodeMirror-Editor initialisieren, wenn in den Bearbeitungsmodus gewechselt wird
  useEffect(() => {
    if (!editing || !isMarkdown || !editorContainerRef.current) return;

    const initialDoc = draftsStore.get(currentTab?.id)?.text ?? fileContent;
    const ed = createEditor({
      parent: editorContainerRef.current,
      doc: initialDoc,
      readOnly: !currentTab?.editable,
      onChange: (text) => {
        const tabId = currentTab?.id;
        const entry = draftsStore.get(tabId) || { mtimeNs, cleanContent: fileContent };
        const hasChanges = text !== (entry.cleanContent ?? cleanContentRef.current);

        draftsStore.set(tabId, {
          text,
          mtimeNs: entry.mtimeNs ?? mtimeNs,
          cleanContent: entry.cleanContent ?? cleanContentRef.current,
          isDirty: hasChanges,
        });

        setDraft(text);
        setDirty(hasChanges);
        syncStoreDirty(setStoreDirty);
      },
      onSave: (text) => {
        handleSaveRef.current?.(text);
      },
    });

    editorRef.current = ed;

    // Scroll-Synchronisation vom Editor zur Vorschau
    const scrollDOM = ed.view.scrollDOM;
    function onEditorScroll() {
      if (!syncRef.current || isLocked("editor")) return;
      setLock("editor", 120);

      const maxEd = scrollDOM.scrollHeight - scrollDOM.clientHeight;
      const ratio = maxEd > 0 ? scrollDOM.scrollTop / maxEd : 0;

      if (previewRef.current) {
        const maxPrev = previewRef.current.scrollHeight - previewRef.current.clientHeight;
        previewRef.current.scrollTop = ratio * maxPrev;
      }
    }

    scrollDOM.addEventListener("scroll", onEditorScroll, { passive: true });

    return () => {
      scrollDOM.removeEventListener("scroll", onEditorScroll);
      ed.destroy();
      editorRef.current = null;
    };
  }, [editing, isMarkdown, currentTab?.id]);

  // Gerendertes Markdown mit KaTeX und Folien-Links
  const renderedHtml = useMemo(() => {
    if (!draft) return "";
    const html = renderMarkdown(draft);
    return linkifyFolien(html);
  }, [draft]);

  // Scrollen der Vorschau: Editor synchronisieren und oberste sichtbare Folie mit Toleranz ermitteln
  const handlePreviewScroll = useCallback(() => {
    if (!syncRef.current || isLocked("preview")) return;
    setLock("preview", 120);

    const prev = previewRef.current;
    if (!prev) return;

    // 1. Proportionales Scrollen zum Editor
    if (editing && editorRef.current?.view?.scrollDOM) {
      const maxPrev = prev.scrollHeight - prev.clientHeight;
      const ratio = maxPrev > 0 ? prev.scrollTop / maxPrev : 0;
      const edDom = editorRef.current.view.scrollDOM;
      const maxEd = edDom.scrollHeight - edDom.clientHeight;
      edDom.scrollTop = ratio * maxEd;
    }

    // Wenn gerade ein Ziel aktiv angefahren wird, Rueckmeldungen an PDF ignorieren
    if (targetFolieRef.current !== null) {
      return;
    }

    // 2. Foliennummer des obersten sichtbaren Absatzes ermitteln mit Toleranz
    const cRect = prev.getBoundingClientRect();
    const blocks = prev.querySelectorAll("p, h1, h2, h3, h4, h5, h6, li, blockquote, div, .stu-flink");
    let foundFolie = null;

    // Ersten Block suchen, dessen Unterkante mindestens 24px unterhalb des oberen Container-Rands liegt
    for (const el of blocks) {
      const elRect = el.getBoundingClientRect();
      const relativeBottom = elRect.bottom - cRect.top;
      if (relativeBottom >= 24) {
        const f = firstFolieIn(el);
        if (f) {
          foundFolie = f;
          break;
        }
      }
    }

    if (!foundFolie) {
      const links = prev.querySelectorAll(".stu-flink");
      for (const a of links) {
        const aRect = a.getBoundingClientRect();
        if (aRect.bottom - cRect.top >= 16) {
          const f = Number(a.dataset.folie || a.getAttribute("data-folie"));
          if (!Number.isNaN(f) && f > 0) {
            foundFolie = f;
            break;
          }
        }
      }
    }

    if (foundFolie && foundFolie !== pdfPageRef.current) {
      setPdfPage(foundFolie);
    }
  }, [editing, setPdfPage]);

  // Sichtbare Seite aus PdfView: Vorschau zum Folien-Absatz scrollen und Editor nachziehen
  const handleVisiblePage = useCallback(
    (n) => {
      if (!syncRef.current || isLocked("pdf")) return;

      setPdfPage(n);

      const prev = previewRef.current;
      if (!prev) return;

      const link = prev.querySelector(`.stu-flink[data-folie="${n}"]`);
      if (!link) {
        // Keine Folie im Dokument vorhanden: Flag und Sperre nicht setzen bzw. zuruecksetzen
        targetFolieRef.current = null;
        return;
      }

      targetFolieRef.current = n;
      setLock("pdf", 1200);

      const block = link.closest("p, h1, h2, h3, h4, h5, h6, li, blockquote") || link;
      const targetTop = Math.max(0, getRelativeTop(block, prev) - 16);

      if (scrollEndCleanupRef.current) {
        scrollEndCleanupRef.current();
      }

      let fallbackTimer = null;
      const onScrollEnd = () => {
        if (fallbackTimer) clearTimeout(fallbackTimer);
        prev.removeEventListener("scrollend", onScrollEnd);
        scrollEndCleanupRef.current = null;
        if (lockRef.current.who === "pdf") {
          lockRef.current = { who: "", until: 0 };
        }
        targetFolieRef.current = null;
      };

      prev.addEventListener("scrollend", onScrollEnd, { once: true });
      fallbackTimer = setTimeout(onScrollEnd, 1200);
      scrollEndCleanupRef.current = () => {
        if (fallbackTimer) clearTimeout(fallbackTimer);
        prev.removeEventListener("scrollend", onScrollEnd);
        scrollEndCleanupRef.current = null;
      };

      prev.scrollTo({ top: targetTop, behavior: "smooth" });

      if (editing && editorRef.current?.view?.scrollDOM) {
        const maxPrev = prev.scrollHeight - prev.clientHeight;
        const ratio = maxPrev > 0 ? targetTop / maxPrev : 0;
        const edDom = editorRef.current.view.scrollDOM;
        const maxEd = edDom.scrollHeight - edDom.clientHeight;
        edDom.scrollTo({ top: ratio * maxEd, behavior: "smooth" });
      }
    },
    [editing, setPdfPage]
  );

  // Speichern ueber files.write mit dem mtime_ns des Entwurfs
  const handleSave = useCallback(
    async (textOverride) => {
      if (!currentTab || saving) return;
      const textToSave =
        textOverride !== undefined
          ? textOverride
          : editorRef.current
          ? editorRef.current.getText()
          : draft;

      const tabId = currentTab.id;
      const saveMtimeNs = draftsStore.get(tabId)?.mtimeNs ?? mtimeNs;

      setSaving(true);
      try {
        const res = await files.write(currentTab.root, currentTab.path, textToSave, saveMtimeNs);
        const newMtime = res?.mtime_ns ?? saveMtimeNs;
        setMtimeNs(newMtime);
        setFileContent(textToSave);
        cleanContentRef.current = textToSave;

        draftsStore.set(tabId, {
          text: textToSave,
          mtimeNs: newMtime,
          cleanContent: textToSave,
          isDirty: false,
        });
        fileContentCache.set(tabId, textToSave);

        setDirty(false);
        editorRef.current?.markClean(textToSave);
        setConflict(null);
        syncStoreDirty(setStoreDirty);
        toast("Gespeichert");
      } catch (err) {
        if (err?.isConflict || err?.status === 409) {
          setConflict({
            serverMtimeNs: err.current?.mtime_ns ?? null,
            detail: err.detail,
          });
        } else {
          toast(`Fehler beim Speichern: ${err.message || "Unbekannter Fehler"}`);
        }
      } finally {
        setSaving(false);
      }
    },
    [currentTab, saving, draft, mtimeNs, setStoreDirty, toast]
  );

  // Ref stets auf die aktuelle Version von handleSave setzen
  handleSaveRef.current = handleSave;

  // Globaler Tastaturbefehl Mod-S (Cmd+S / Strg+S)
  useEffect(() => {
    function onKeyDown(e) {
      if (e.defaultPrevented) return;
      if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        if (editing && currentTab?.editable) {
          handleSaveRef.current?.();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editing, currentTab]);

  // Konfliktloesung: Neu laden (Server-Stand uebernehmen)
  const handleReloadFromServer = useCallback(async () => {
    if (!currentTab) return;
    try {
      setLoading(true);
      const data = await files.read(currentTab.root, currentTab.path);
      const content = data.content || "";
      const serverMtime = data.mtime_ns ?? null;
      const tabId = currentTab.id;

      draftsStore.set(tabId, {
        text: content,
        mtimeNs: serverMtime,
        cleanContent: content,
        isDirty: false,
      });
      fileContentCache.set(tabId, content);

      setFileContent(content);
      setDraft(content);
      cleanContentRef.current = content;
      setMtimeNs(serverMtime);
      setDirty(false);
      if (editorRef.current) {
        editorRef.current.setText(content);
      }
      setConflict(null);
      syncStoreDirty(setStoreDirty);
      toast("Server-Stand neu geladen");
    } catch (err) {
      toast(`Fehler beim Laden: ${err.message || ""}`);
    } finally {
      setLoading(false);
    }
  }, [currentTab, setStoreDirty, toast]);

  // Konfliktloesung: Ueberschreiben (mit aktuellem mtime_ns des Servers)
  const handleOverwriteServer = useCallback(async () => {
    if (!currentTab || !conflict) return;
    const textToSave = editorRef.current ? editorRef.current.getText() : draft;
    const tabId = currentTab.id;
    setSaving(true);
    try {
      const res = await files.write(
        currentTab.root,
        currentTab.path,
        textToSave,
        conflict.serverMtimeNs
      );
      const newMtime = res?.mtime_ns ?? conflict.serverMtimeNs;
      setMtimeNs(newMtime);
      setFileContent(textToSave);
      cleanContentRef.current = textToSave;

      draftsStore.set(tabId, {
        text: textToSave,
        mtimeNs: newMtime,
        cleanContent: textToSave,
        isDirty: false,
      });
      fileContentCache.set(tabId, textToSave);

      setDirty(false);
      editorRef.current?.markClean(textToSave);
      setConflict(null);
      syncStoreDirty(setStoreDirty);
      toast("Datei überschrieben");
    } catch (err) {
      toast(`Fehler beim Überschreiben: ${err.message || ""}`);
    } finally {
      setSaving(false);
    }
  }, [currentTab, conflict, draft, setStoreDirty, toast]);

  // Bearbeiten abbrechen
  const handleCancelEditing = useCallback(() => {
    if (dirty) {
      if (!window.confirm("Ungespeicherte Änderungen verwerfen?")) {
        return;
      }
    }
    const tabId = currentTab?.id;
    const cleanText = cleanContentRef.current;
    setDraft(cleanText);
    if (tabId) {
      const entry = draftsStore.get(tabId);
      draftsStore.set(tabId, {
        text: cleanText,
        mtimeNs: entry?.mtimeNs ?? mtimeNs,
        cleanContent: cleanText,
        isDirty: false,
      });
    }
    setDirty(false);
    setConflict(null);
    syncStoreDirty(setStoreDirty);
    setEditing(false);
  }, [dirty, currentTab, mtimeNs, setStoreDirty]);

  // Tab schliessen
  const handleCloseTab = useCallback(
    (idToClose) => {
      const isTabDirty = draftsStore.get(idToClose)?.isDirty || false;
      if (isTabDirty) {
        if (!window.confirm("Ungespeicherte Änderungen verwerfen?")) {
          return;
        }
      }
      draftsStore.delete(idToClose);
      fileContentCache.delete(idToClose);
      if (imageBlobCache.has(idToClose)) {
        URL.revokeObjectURL(imageBlobCache.get(idToClose));
        imageBlobCache.delete(idToClose);
      }
      syncStoreDirty(setStoreDirty);
      closeTab(idToClose);
    },
    [setStoreDirty, closeTab]
  );

  // Versionen-Dialog oeffnen
  const handleOpenVersions = useCallback(async () => {
    if (!currentTab) return;
    setShowVersions(true);
    setPreviewVersion(null);
    setVersionsLoading(true);
    try {
      const list = await files.versions(currentTab.root, currentTab.path);
      setVersionsList(Array.isArray(list) ? list : []);
    } catch (err) {
      toast(`Fehler beim Laden der Versionen: ${err.message || ""}`);
      setVersionsList([]);
    } finally {
      setVersionsLoading(false);
    }
  }, [currentTab, toast]);

  // Einzelne Version ansehen (Datum aus der Versionsliste uebernehmen)
  const handleViewVersion = useCallback(
    async (versionId) => {
      if (!currentTab) return;
      setPreviewLoading(true);
      try {
        const meta = versionsList.find((v) => v.id === versionId);
        const data = await files.version(currentTab.root, currentTab.path, versionId);
        setPreviewVersion({
          ...data,
          created: data.created || meta?.created,
          size: data.size ?? meta?.size,
        });
      } catch (err) {
        toast(`Fehler beim Laden der Version: ${err.message || ""}`);
      } finally {
        setPreviewLoading(false);
      }
    },
    [currentTab, versionsList, toast]
  );

  // Version wiederherstellen (mit Bestaetigung bei ungespeicherten Aenderungen)
  const handleRestoreVersion = useCallback(
    async (versionId) => {
      if (!currentTab) return;
      if (dirty) {
        if (
          !window.confirm(
            "Ungespeicherte Änderungen werden überschrieben. Wirklich fortfahren?"
          )
        ) {
          return;
        }
      }
      try {
        setLoading(true);
        const tabId = currentTab.id;
        const currentMtime = draftsStore.get(tabId)?.mtimeNs ?? mtimeNs;
        await files.restore(currentTab.root, currentTab.path, versionId, currentMtime);
        // Danach neu laden
        const data = await files.read(currentTab.root, currentTab.path);
        const content = data.content || "";
        const serverMtime = data.mtime_ns ?? null;

        draftsStore.set(tabId, {
          text: content,
          mtimeNs: serverMtime,
          cleanContent: content,
          isDirty: false,
        });
        fileContentCache.set(tabId, content);

        setFileContent(content);
        setDraft(content);
        cleanContentRef.current = content;
        setMtimeNs(serverMtime);
        setDirty(false);
        if (editorRef.current) {
          editorRef.current.setText(content);
        }
        setShowVersions(false);
        setPreviewVersion(null);
        syncStoreDirty(setStoreDirty);
        toast("Version wiederhergestellt");
      } catch (err) {
        toast(`Fehler beim Wiederherstellen: ${err.message || ""}`);
      } finally {
        setLoading(false);
      }
    },
    [currentTab, dirty, mtimeNs, setStoreDirty, toast]
  );

  // Rendern des Hauptinhalts (PDF, Bild, andere Dateien oder Markdown)
  let mainDocContent = null;

  if (!currentTab || tabs.length === 0) {
    if (course) {
      mainDocContent = <ModulView course={course} />;
    } else {
      mainDocContent = (
        <div className="stu-doc-empty">
          <div className="stu-doc-empty-icon">
            <Icon n="doc" />
          </div>
          <h3>Kein Dokument geöffnet</h3>
          <p className="stu-muted">Wähle eine Datei im Explorer aus, um sie anzuzeigen.</p>
        </div>
      );
    }
  } else if (isPdf) {
    if (relatedSummary && summaryContent) {
      mainDocContent = (
        <div className="stu-panes has-pdf">
          <section className="stu-pdf" aria-label="PDF-Vorschau">
            <PdfView
              root={currentTab.root}
              path={currentTab.path}
              page={pdfPage}
              onVisiblePage={handleVisiblePage}
            />
          </section>
          <section className="stu-md" aria-label="Zusammenfassung">
            <div className="stu-paneh">
              <span className="stu-paneh-status stu-muted">Zusammenfassung</span>
              <div className="stu-paneh-actions">
                <button
                  type="button"
                  className="stu-tbtn"
                  onClick={() => openFile(relatedSummary.root, relatedSummary.path)}
                  title="Als separaten Tab öffnen und bearbeiten"
                >
                  <Icon n="edit" />
                  <span>Bearbeiten</span>
                </button>
              </div>
            </div>
            <div className="stu-mdbody">
              <article
                className="stu-doc"
                onClick={(e) => onFolieClick(e, openFolie)}
                dangerouslySetInnerHTML={{ __html: renderedSummaryHtml }}
              />
            </div>
          </section>
        </div>
      );
    } else {
      mainDocContent = (
        <div className="stu-panes">
          <PdfView
            root={currentTab.root}
            path={currentTab.path}
            page={pdfPage}
            onVisiblePage={handleVisiblePage}
          />
        </div>
      );
    }
  } else if (isImage) {
    mainDocContent = (
      <div className="stu-doc-media">
        {imageBlobUrl ? (
          <img src={imageBlobUrl} alt={currentTab.name} className="stu-doc-img" />
        ) : (
          <p className="stu-muted">Bild konnte nicht geladen werden.</p>
        )}
      </div>
    );
  } else if (isOther) {
    mainDocContent = (
      <div className="stu-doc-download">
        <Badge name={currentTab.name} />
        <div className="stu-doc-download-info">
          <div className="stu-doc-download-name">{currentTab.name}</div>
          <div className="stu-doc-download-path stu-muted">{currentTab.path}</div>
        </div>
        <a
          href={files.rawUrl(currentTab.root, currentTab.path)}
          download={currentTab.name}
          className="stu-tbtn is-pri"
        >
          <Icon n="exit" />
          <span>Herunterladen</span>
        </a>
      </div>
    );
  } else {
    // Markdown-Dokument
    const showSidePdf = Boolean(pdfOpen && relatedPdf);
    const panesClass = `stu-panes ${showSidePdf ? "has-pdf" : ""} ${
      editing ? "is-editing" : ""
    }`.trim();

    mainDocContent = (
      <div className={panesClass}>
        {showSidePdf && (
          <section className="stu-pdf" aria-label="PDF-Vorschau daneben">
            <PdfView
              root={relatedPdf.root}
              path={relatedPdf.path}
              page={pdfPage}
              onVisiblePage={handleVisiblePage}
            />
          </section>
        )}

        <section className="stu-md" aria-label="Markdown-Bereich">
          {conflict && (
            <div className="stu-conflict-bar" role="alert">
              <span className="stu-conflict-text">
                Konflikt: Die Datei wurde zwischenzeitlich auf dem Server geändert.
              </span>
              <div className="stu-conflict-actions">
                <button
                  type="button"
                  className="stu-tbtn"
                  onClick={handleReloadFromServer}
                >
                  Neu laden
                </button>
                <button
                  type="button"
                  className="stu-tbtn is-pri"
                  onClick={handleOverwriteServer}
                >
                  Überschreiben
                </button>
              </div>
            </div>
          )}

          <div className="stu-paneh">
            <span className="stu-paneh-status stu-muted">
              {editing
                ? `Bearbeiten · ${dirty ? "ungespeichert" : "gespeichert"}`
                : "Lesen"}
            </span>

            <div className="stu-paneh-actions">
              <button
                type="button"
                className={`stu-tbtn ${showVersions ? "is-on" : ""}`.trim()}
                onClick={handleOpenVersions}
                title="Versionen anzeigen"
              >
                <Icon n="sessions" />
                <span>Versionen</span>
              </button>

              <button
                type="button"
                className={`stu-tbtn ${sync ? "is-on" : ""}`.trim()}
                onClick={() => setSync(!sync)}
                title="Gemeinsam scrollen"
              >
                <Icon n="link" />
                <span>Sync</span>
              </button>

              {currentTab.editable &&
                (editing ? (
                  <>
                    <button
                      type="button"
                      className="stu-tbtn"
                      onClick={handleCancelEditing}
                    >
                      Abbrechen
                    </button>
                    <button
                      type="button"
                      className="stu-tbtn is-pri"
                      onClick={() => handleSave()}
                      disabled={saving}
                    >
                      {saving ? "Wird gespeichert …" : "Speichern"}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="stu-tbtn is-pri"
                    onClick={() => setEditing(true)}
                  >
                    <Icon n="edit" />
                    <span>Bearbeiten</span>
                  </button>
                ))}
            </div>
          </div>

          <div className="stu-mdbody">
            {editing && <div className="stu-src" ref={editorContainerRef} />}

            <article
              className="stu-doc"
              ref={previewRef}
              onScroll={handlePreviewScroll}
              onClick={(e) => onFolieClick(e, openFolie)}
              dangerouslySetInnerHTML={{ __html: renderedHtml }}
            />
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="stu-docarea">
      {/* Tab-Leiste */}
      <div className="stu-tabs" role="tablist">
        <div className="stu-tablist">
          {tabs.map((tab) => {
            const isTabActive = currentTab ? tab.id === currentTab.id : false;
            const isTabDirty = draftsStore.get(tab.id)?.isDirty || false;
            return (
              <div
                key={tab.id}
                role="tab"
                aria-selected={isTabActive}
                className={`stu-tab ${isTabActive ? "is-on" : ""}`.trim()}
                onClick={() => setActive(tab.id)}
              >
                <Badge name={tab.name} />
                <span className="stu-tab-name" title={tab.name}>
                  {tab.name}
                </span>
                {isTabDirty && <span className="stu-dirty" title="Ungespeicherte Änderungen" />}
                <button
                  type="button"
                  className="stu-tab-close"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCloseTab(tab.id);
                  }}
                  title="Schliessen"
                  aria-label={`Tab ${tab.name} schliessen`}
                >
                  <Icon n="x" />
                </button>
              </div>
            );
          })}
        </div>

        {relatedPdf && (
          <button
            type="button"
            className={`stu-icbtn ${pdfOpen ? "is-on" : ""}`.trim()}
            onClick={() => setPdfOpen(!pdfOpen)}
            title={pdfOpen ? "PDF ausblenden" : "PDF daneben"}
            aria-label="PDF daneben"
          >
            <Icon n="split" />
          </button>
        )}

        {!mobile && !rightOpen && (
          <button
            type="button"
            className="stu-icbtn"
            onClick={() => setRightOpen(true)}
            title="Agent öffnen"
            aria-label="Agent öffnen"
          >
            <Icon n="right" />
          </button>
        )}

        {mobile && (
          <button
            type="button"
            className="stu-icbtn"
            onClick={() => setView("read")}
            title="Lesemodus"
            aria-label="Lesemodus"
          >
            <Icon n="read" />
          </button>
        )}

        {mobile && (
          <button
            type="button"
            className="stu-icbtn"
            onClick={cycleTheme}
            title="Hell/Dunkel"
            aria-label="Farbschema wechseln"
          >
            <Icon n={dark ? "sun" : "moon"} />
          </button>
        )}
      </div>

      {/* Hauptbereich (bleibt gemountet, um CodeMirror nicht zu zerstoeren) */}
      {mainDocContent}

      {/* Lade-Overlay statt Aushaengen des DOM-Inhalts */}
      {loading && (
        <div className="stu-doc-loading-overlay">
          <Loading text="Wird geladen …" />
        </div>
      )}

      {/* Versionen-Dialog */}
      {showVersions && (
        <div
          className="stu-versions-overlay"
          onClick={() => {
            setShowVersions(false);
            setPreviewVersion(null);
          }}
        >
          <div
            className="stu-versions-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="stu-versions-title"
          >
            <div className="stu-versions-h">
              <h3 id="stu-versions-title">
                {previewVersion
                  ? `Version vom ${formatDate(previewVersion.created || "")}`
                  : `Versionen von ${currentTab?.name || ""}`}
              </h3>
              <button
                type="button"
                className="stu-icbtn"
                onClick={() => {
                  setShowVersions(false);
                  setPreviewVersion(null);
                }}
                title="Schliessen"
              >
                <Icon n="x" />
              </button>
            </div>

            <div className="stu-versions-body">
              {versionsLoading || previewLoading ? (
                <Loading text="Versionen werden geladen …" />
              ) : previewVersion ? (
                <div className="stu-version-preview">
                  <div className="stu-version-preview-h">
                    <button
                      type="button"
                      className="stu-tbtn"
                      onClick={() => setPreviewVersion(null)}
                    >
                      ← Zurück zur Liste
                    </button>
                    <button
                      type="button"
                      className="stu-tbtn is-pri"
                      onClick={() => handleRestoreVersion(previewVersion.id)}
                    >
                      Diese Version wiederherstellen
                    </button>
                  </div>
                  {isMarkdown ? (
                    <div
                      className="stu-version-preview-content"
                      dangerouslySetInnerHTML={{
                        __html: linkifyFolien(
                          renderMarkdown(previewVersion.content || "")
                        ),
                      }}
                    />
                  ) : (
                    <div className="stu-version-preview-content">
                      <pre>{previewVersion.content || ""}</pre>
                    </div>
                  )}
                </div>
              ) : versionsList.length === 0 ? (
                <p className="stu-muted">Keine früheren Versionen vorhanden.</p>
              ) : (
                <div className="stu-versions-list">
                  {versionsList.map((v) => (
                    <div key={v.id} className="stu-versions-item">
                      <div className="stu-versions-meta">
                        <span className="stu-versions-date">
                          {formatDate(v.created)}
                        </span>
                        <span className="stu-versions-info">
                          ID: {v.id.slice(0, 8)} · {formatBytes(v.size)}
                        </span>
                      </div>
                      <div className="stu-versions-actions">
                        <button
                          type="button"
                          className="stu-tbtn"
                          onClick={() => handleViewVersion(v.id)}
                        >
                          Ansehen
                        </button>
                        <button
                          type="button"
                          className="stu-tbtn is-pri"
                          onClick={() => handleRestoreVersion(v.id)}
                        >
                          Wiederherstellen
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DocArea;
