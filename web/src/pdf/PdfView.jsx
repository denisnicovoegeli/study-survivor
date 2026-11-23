// PdfView.jsx: PDF-Betrachter mit Folien-Navigation und Seitensynchronisation
import React from "react";
import { BASE_URL } from "../lib/assets.js";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import { Icon } from "../ui/Icon.jsx";
import "./pdf.css";

const { useState, useEffect, useRef, useMemo, useCallback } = React;

// pdf.js wird zur Laufzeit als eigenstaendiges ESM geladen
let pdfjsPromise = null;

async function getPdfJs() {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const pdfjs = await import(/* @vite-ignore */ new URL("pdfjs/pdf.min.mjs", BASE_URL).href);
      const workerUrl = new URL("pdfjs/pdf.worker.min.mjs", BASE_URL).href;
      if (pdfjs.GlobalWorkerOptions) {
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      }
      return pdfjs;
    })().catch((err) => {
      pdfjsPromise = null;
      throw err;
    });
  }
  return pdfjsPromise;
}

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.25;

// Unterkomponente: Einzelne Seite als Canvas rendern, darueber Textebene (auswaehlbar) und Links
function PdfPageCanvas({ doc, pageNum, targetWidth, onAspectMeasured }) {
  const canvasRef = useRef(null);
  const textRef = useRef(null);
  const linksRef = useRef(null);
  const renderTaskRef = useRef(null);
  const textLayerRef = useRef(null);

  useEffect(() => {
    let isCancelled = false;
    let pageProxy = null;

    async function renderPage() {
      if (!doc || !canvasRef.current || targetWidth <= 0) return;

      try {
        pageProxy = await doc.getPage(pageNum);
        if (isCancelled || !canvasRef.current) return;

        const unscaledVp = pageProxy.getViewport({ scale: 1 });
        const aspect = unscaledVp.width / unscaledVp.height;
        if (typeof onAspectMeasured === "function") {
          onAspectMeasured(pageNum, aspect);
        }

        const availableWidth = targetWidth > 0 ? targetWidth : unscaledVp.width;
        const scale = availableWidth / unscaledVp.width;
        const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
        const viewport = pageProxy.getViewport({ scale: scale * dpr });

        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);

        if (renderTaskRef.current) {
          try {
            renderTaskRef.current.cancel();
          } catch {}
          renderTaskRef.current = null;
        }

        const task = pageProxy.render({
          canvasContext: ctx,
          viewport: viewport,
        });
        renderTaskRef.current = task;

        await task.promise;
        if (isCancelled) return;
        await renderTextAndLinks(pageProxy, unscaledVp);
      } catch (err) {
        if (err?.name === "RenderingCancelledException" || isCancelled) {
          return;
        }
        console.error(`Fehler beim Rendern von Seite ${pageNum}:`, err);
      } finally {
        if (pageProxy) {
          try {
            pageProxy.cleanup();
          } catch {}
        }
      }
    }

    // Textebene mit pdfjs TextLayer (6.x: textContentSource, container, viewport) und
    // einfache Link-Ebene aus den Annotationen. Viewport in CSS-Pixeln, ohne devicePixelRatio.
    async function renderTextAndLinks(proxy, unscaledVp) {
      const textDiv = textRef.current;
      const linkDiv = linksRef.current;
      const canvas = canvasRef.current;
      if (!textDiv || !canvas) return;
      const cssWidth = canvas.clientWidth || targetWidth;
      const cssScale = cssWidth / unscaledVp.width;
      const cssVp = proxy.getViewport({ scale: cssScale });

      textLayerRef.current?.cancel?.();
      textDiv.replaceChildren();
      textDiv.style.setProperty("--total-scale-factor", String(cssScale));

      const pdfjs = await getPdfJs();
      if (isCancelled) return;
      const textContent = await proxy.getTextContent();
      if (isCancelled) return;
      const layer = new pdfjs.TextLayer({ textContentSource: textContent, container: textDiv, viewport: cssVp });
      textLayerRef.current = layer;
      try {
        await layer.render();
      } catch (err) {
        if (!isCancelled) console.warn(`Textebene Folie ${pageNum}:`, err);
      }
      // Ende-Markierung wie im pdf.js-Viewer, damit die Auswahl nicht springt
      if (!isCancelled && !textDiv.querySelector(".endOfContent")) {
        const end = document.createElement("div");
        end.className = "endOfContent";
        textDiv.append(end);
      }

      if (!linkDiv) return;
      linkDiv.replaceChildren();
      let annots = [];
      try {
        annots = await proxy.getAnnotations({ intent: "display" });
      } catch {
        annots = [];
      }
      if (isCancelled) return;
      for (const a of annots) {
        if (a.subtype !== "Link" || !a.url || !Array.isArray(a.rect)) continue;
        const [x1, y1, x2, y2] = cssVp.convertToViewportRectangle(a.rect);
        const link = document.createElement("a");
        link.href = a.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = a.url;
        link.className = "stu-pdf-link";
        link.style.left = `${Math.min(x1, x2)}px`;
        link.style.top = `${Math.min(y1, y2)}px`;
        link.style.width = `${Math.abs(x2 - x1)}px`;
        link.style.height = `${Math.abs(y2 - y1)}px`;
        link.addEventListener("click", (e) => e.stopPropagation());
        linkDiv.append(link);
      }
    }

    renderPage();

    return () => {
      isCancelled = true;
      textLayerRef.current?.cancel?.();
      textLayerRef.current = null;
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel();
        } catch {}
        renderTaskRef.current = null;
      }
      if (pageProxy) {
        try {
          pageProxy.cleanup();
        } catch {}
      }
    };
  }, [doc, pageNum, targetWidth, onAspectMeasured]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="stu-slide-canvas"
        aria-label={`Folie ${pageNum}`}
      />
      <div ref={textRef} className="textLayer stu-pdf-text" />
      <div ref={linksRef} className="stu-pdf-links" />
    </>
  );
}

export function PdfView({ root, path, page = 1, onVisiblePage }) {
  const { mobile } = useStudio();

  const [doc, setDoc] = useState(null);
  const [numPages, setNumPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  const [zoom, setZoom] = useState(1.0);
  const [containerWidth, setContainerWidth] = useState(0);
  const [defaultAspect, setDefaultAspect] = useState(16 / 9);
  const [aspectMap, setAspectMap] = useState(() => new Map());

  const initialPage = Math.max(1, Number(page) || 1);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [visiblePages, setVisiblePages] = useState(() => new Set([initialPage]));

  const [scrollEl, setScrollEl] = useState(null);
  const slideRefs = useRef(new Map());
  const isProgrammaticScroll = useRef(false);
  const scrollEndTimeoutRef = useRef(null);
  const currentPageRef = useRef(initialPage);
  currentPageRef.current = currentPage;

  const prevPageProp = useRef(page);
  const initialScrollDone = useRef(false);

  const filename = useMemo(() => {
    if (!path) return "";
    return path.split("/").pop() || path;
  }, [path]);

  // PDF-Daten ueber SDK.authedFetch als ArrayBuffer laden
  useEffect(() => {
    let isCancelled = false;
    let loadingTask = null;
    let currentDoc = null;
    const abortCtrl = new AbortController();

    initialScrollDone.current = false;
    setAspectMap(new Map());

    if (!root || !path) {
      setDoc(null);
      setNumPages(0);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    async function loadPdf() {
      try {
        const SDK = typeof window !== "undefined" ? window.__HERMES_PLUGIN_SDK__ : null;
        const fetchFn = SDK?.authedFetch ? SDK.authedFetch.bind(SDK) : window.fetch.bind(window);
        const url = `/api/plugins/studium/files/raw?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`;

        const [res, pdfjsLib] = await Promise.all([
          fetchFn(url, { signal: abortCtrl.signal }),
          getPdfJs(),
        ]);

        if (!res.ok) {
          let detail = "";
          try {
            const data = await res.json();
            detail = data?.detail || data?.message || "";
          } catch {}
          throw new Error(detail || `HTTP ${res.status}: ${res.statusText || "Fehler beim Laden"}`);
        }

        const buffer = await res.arrayBuffer();
        if (isCancelled) return;

        loadingTask = pdfjsLib.getDocument({ data: new Uint8Array(buffer) });
        const loadedDoc = await loadingTask.promise;
        if (isCancelled) {
          try {
            if (typeof loadedDoc.destroy === "function") loadedDoc.destroy();
            else if (loadedDoc.loadingTask) loadedDoc.loadingTask.destroy();
          } catch {}
          return;
        }

        currentDoc = loadedDoc;
        setDoc(loadedDoc);
        setNumPages(loadedDoc.numPages);

        // Standard-Seitenverhaeltnis von Seite 1 ermitteln
        try {
          const p1 = await loadedDoc.getPage(1);
          const vp = p1.getViewport({ scale: 1 });
          setDefaultAspect(vp.width / vp.height);
          p1.cleanup();
        } catch {}

        setLoading(false);
      } catch (err) {
        if (isCancelled || err?.name === "AbortError") return;
        console.error("PDF-Ladefehler:", err);
        setError(err?.message || "PDF konnte nicht geladen werden.");
        setLoading(false);
      }
    }

    loadPdf();

    // Dokument beim Wechsel oder Unmount sauber zerstoeren
    return () => {
      isCancelled = true;
      abortCtrl.abort();
      if (loadingTask) {
        try {
          loadingTask.destroy();
        } catch {}
      }
      if (currentDoc) {
        try {
          if (typeof currentDoc.destroy === "function") {
            currentDoc.destroy();
          } else if (currentDoc.loadingTask && typeof currentDoc.loadingTask.destroy === "function") {
            currentDoc.loadingTask.destroy();
          }
        } catch {}
      }
    };
  }, [root, path, retry]);

  // Breite des Scrollbereichs mit ResizeObserver beobachten
  useEffect(() => {
    if (!scrollEl) return;

    if (scrollEl.clientWidth > 0) {
      setContainerWidth(scrollEl.clientWidth);
    }

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width || scrollEl.clientWidth;
        if (w > 0) {
          setContainerWidth(w);
        }
      }
    });

    ro.observe(scrollEl);
    return () => ro.disconnect();
  }, [scrollEl]);

  // Programmatisches Scrollen zu einer bestimmten Folie
  const scrollToPage = useCallback(
    (targetPage, smooth = true) => {
      if (!scrollEl) return;
      const slideEl =
        slideRefs.current.get(targetPage) || scrollEl.querySelector(`[data-slide="${targetPage}"]`);
      if (!slideEl) return;

      const containerRect = scrollEl.getBoundingClientRect();
      const slideRect = slideEl.getBoundingClientRect();

      let targetLeft = 0;
      let targetTop = 0;
      let delta = 0;

      if (mobile) {
        targetLeft = Math.max(0, scrollEl.scrollLeft + (slideRect.left - containerRect.left) - 12);
        delta = Math.abs(targetLeft - scrollEl.scrollLeft);
      } else {
        targetTop = Math.max(0, scrollEl.scrollTop + (slideRect.top - containerRect.top) - 16);
        delta = Math.abs(targetTop - scrollEl.scrollTop);
      }

      // Wenn die Folie bereits an der Zielposition liegt, keine Sperre aktivieren
      if (delta < 2) {
        isProgrammaticScroll.current = false;
        return;
      }

      isProgrammaticScroll.current = true;
      if (scrollEndTimeoutRef.current) {
        clearTimeout(scrollEndTimeoutRef.current);
      }
      // Rueckfall-Timer: Sperre wird bei scrollend sofort geloest; dieser Timer greift nur als Absicherung
      scrollEndTimeoutRef.current = setTimeout(
        () => {
          isProgrammaticScroll.current = false;
          scrollEndTimeoutRef.current = null;
        },
        smooth ? 1200 : 100
      );

      if (mobile) {
        scrollEl.scrollTo({ left: targetLeft, behavior: smooth ? "smooth" : "auto" });
      } else {
        scrollEl.scrollTo({ top: targetTop, behavior: smooth ? "smooth" : "auto" });
      }
    },
    [mobile, scrollEl]
  );

  // Nach Abschluss des Scrollens die Programmatisch-Sperre bei scrollend sofort aufheben
  useEffect(() => {
    if (!scrollEl) return;

    const handleScrollEnd = () => {
      isProgrammaticScroll.current = false;
      if (scrollEndTimeoutRef.current) {
        clearTimeout(scrollEndTimeoutRef.current);
        scrollEndTimeoutRef.current = null;
      }
    };

    scrollEl.addEventListener("scrollend", handleScrollEnd);
    return () => scrollEl.removeEventListener("scrollend", handleScrollEnd);
  }, [scrollEl]);

  // Wenn sich die page-Prop aendert: ohne onVisiblePage zur Seite scrollen
  useEffect(() => {
    if (page !== undefined && page !== null && page !== prevPageProp.current) {
      prevPageProp.current = page;
      const targetPage = Math.max(1, Math.min(Number(page) || 1, numPages || 1));
      if (targetPage !== currentPageRef.current) {
        currentPageRef.current = targetPage;
        setCurrentPage(targetPage);
        scrollToPage(targetPage, true);
      }
    }
  }, [page, numPages, scrollToPage]);

  // Nach dem ersten Laden zur initial gewuenschten Seite scrollen
  useEffect(() => {
    if (doc && numPages > 0 && scrollEl && !initialScrollDone.current) {
      initialScrollDone.current = true;
      const target = Math.max(1, Math.min(Number(page) || 1, numPages));
      currentPageRef.current = target;
      setCurrentPage(target);
      if (target > 1) {
        const timer = setTimeout(() => {
          scrollToPage(target, false);
        }, 40);
        return () => clearTimeout(timer);
      }
    }
  }, [doc, numPages, page, scrollEl, scrollToPage]);

  // Nutzer-Scrollen: oberste sichtbare Seite ermitteln und onVisiblePage ausloesen
  const handleScroll = useCallback(() => {
    if (isProgrammaticScroll.current) return;
    if (!scrollEl) return;

    const slides = Array.from(scrollEl.querySelectorAll(".stu-slide"));
    if (slides.length === 0) return;

    const containerRect = scrollEl.getBoundingClientRect();
    let topSlide = null;

    if (mobile) {
      // Horizontales Scrollen auf dem Smartphone
      if (scrollEl.scrollLeft + scrollEl.clientWidth >= scrollEl.scrollWidth - 10) {
        topSlide = slides[slides.length - 1];
      } else if (scrollEl.scrollLeft <= 5) {
        topSlide = slides[0];
      } else {
        topSlide = slides.find((el) => {
          const r = el.getBoundingClientRect();
          return r.left + r.width / 2 > containerRect.left;
        });
      }
    } else {
      // Vertikales Scrollen auf dem Desktop
      if (scrollEl.scrollTop + scrollEl.clientHeight >= scrollEl.scrollHeight - 10) {
        topSlide = slides[slides.length - 1];
      } else if (scrollEl.scrollTop <= 5) {
        topSlide = slides[0];
      } else {
        topSlide = slides.find((el) => {
          const r = el.getBoundingClientRect();
          return r.top + r.height / 2 > containerRect.top;
        });
      }
    }

    if (topSlide) {
      const n = Number(topSlide.dataset.slide);
      if (n && n !== currentPageRef.current) {
        currentPageRef.current = n;
        setCurrentPage(n);
        if (typeof onVisiblePage === "function") {
          onVisiblePage(n);
        }
      }
    }
  }, [mobile, onVisiblePage, scrollEl]);

  // IntersectionObserver: sichtbare Folien beobachten fuer Lazy-Rendering
  useEffect(() => {
    if (!scrollEl || !doc || numPages === 0) return;

    const intersecting = new Set();

    const observer = new IntersectionObserver(
      (entries) => {
        let changed = false;
        for (const entry of entries) {
          const p = Number(entry.target.dataset.slide);
          if (!p) continue;
          if (entry.isIntersecting) {
            if (!intersecting.has(p)) {
              intersecting.add(p);
              changed = true;
            }
          } else {
            if (intersecting.has(p)) {
              intersecting.delete(p);
              changed = true;
            }
          }
        }
        if (changed) {
          setVisiblePages(new Set(intersecting));
        }
      },
      {
        root: scrollEl,
        rootMargin: "100px",
        threshold: 0.01,
      }
    );

    const elements = scrollEl.querySelectorAll(".stu-slide");
    elements.forEach((el) => observer.observe(el));

    return () => {
      observer.disconnect();
    };
  }, [scrollEl, doc, numPages]);

  // Sichtbare Seiten plus Nachbarn (+/- 1) vorberechnen
  const pagesToRender = useMemo(() => {
    const set = new Set();
    const current = currentPage || 1;
    set.add(current);
    if (current > 1) set.add(current - 1);
    if (current < numPages) set.add(current + 1);

    for (const p of visiblePages) {
      set.add(p);
      if (p > 1) set.add(p - 1);
      if (p < numPages) set.add(p + 1);
    }
    return set;
  }, [visiblePages, currentPage, numPages]);

  const handleAspectMeasured = useCallback((pageNum, aspect) => {
    setAspectMap((prev) => {
      if (prev.get(pageNum) === aspect) return prev;
      const next = new Map(prev);
      next.set(pageNum, aspect);
      return next;
    });
  }, []);

  // Zoom-Aktionen
  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(MAX_ZOOM, Math.round((z + ZOOM_STEP) * 100) / 100));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(MIN_ZOOM, Math.round((z - ZOOM_STEP) * 100) / 100));
  }, []);

  const handleZoomReset = useCallback(() => {
    setZoom(1.0);
  }, []);

  // Berechne Zielbreite der Folien
  const baseWidth = Math.max(100, (containerWidth || 600) - 32);
  const slideWidth = mobile
    ? Math.round((containerWidth || 360) * 0.86 * zoom)
    : Math.round(baseWidth * zoom);

  if (error) {
    return (
      <section className="stu-pdf">
        <div className="stu-paneh">
          <span className="stu-pdf-title" title={filename}>
            {filename || "PDF"}
          </span>
          <span className="stu-muted">Fehler</span>
        </div>
        <div className="stu-pdf-error" role="alert">
          <Icon n="doc" />
          <p className="stu-pdf-error-text">
            Fehler beim Laden des PDFs: {error}
          </p>
          <button
            type="button"
            className="stu-pdf-retry-btn"
            onClick={() => {
              setError(null);
              setLoading(true);
              setDoc(null);
              setRetry((c) => c + 1);
            }}
          >
            Erneut versuchen
          </button>
        </div>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="stu-pdf">
        <div className="stu-paneh">
          <span className="stu-pdf-title" title={filename}>
            {filename || "PDF"}
          </span>
          <span className="stu-muted">Wird geladen …</span>
        </div>
        <div className="stu-pdf-loading">
          <Loading text="PDF wird geladen …" />
        </div>
      </section>
    );
  }

  if (!root || !path) {
    return (
      <section className="stu-pdf">
        <div className="stu-paneh">
          <span className="stu-pdf-title">PDF</span>
          <span className="stu-muted">Keine Datei ausgewählt</span>
        </div>
        <div className="stu-pdf-empty">
          <Icon n="doc" />
          <p className="stu-muted">Keine PDF-Datei ausgewählt.</p>
        </div>
      </section>
    );
  }

  const slideList = Array.from({ length: numPages }, (_, i) => i + 1);

  return (
    <section className="stu-pdf">
      <div className="stu-paneh">
        <span className="stu-pdf-title" title={filename}>
          {filename}
        </span>
        <span className="stu-muted">
          {numPages > 0 ? `Folie ${currentPage} / ${numPages}` : "Wird geladen …"}
        </span>
        <span className="stu-grow" />
        <button
          type="button"
          onClick={handleZoomOut}
          disabled={zoom <= MIN_ZOOM}
          title="Verkleinern"
          aria-label="Verkleinern"
        >
          −
        </button>
        <span
          className="stu-muted stu-pdf-zoom-val"
          onClick={handleZoomReset}
          title="Zoom zurücksetzen (100 %)"
          style={{ cursor: "pointer" }}
        >
          {Math.round(zoom * 100)} %
        </span>
        <button
          type="button"
          onClick={handleZoomIn}
          disabled={zoom >= MAX_ZOOM}
          title="Vergrössern"
          aria-label="Vergrössern"
        >
          +
        </button>
      </div>

      <div
        className="stu-pdfscroll"
        ref={setScrollEl}
        onScroll={handleScroll}
      >
        {slideList.map((n) => {
          const aspect = aspectMap.get(n) || defaultAspect || 16 / 9;
          const isCurrent = n === currentPage;
          const shouldRender = pagesToRender.has(n);

          const slideStyle = mobile
            ? {
                aspectRatio: `${aspect}`,
                ...(zoom !== 1.0 ? { width: `${slideWidth}px` } : {}),
              }
            : {
                width: `${slideWidth}px`,
                aspectRatio: `${aspect}`,
                maxWidth: zoom <= 1.0 ? "100%" : "none",
              };

          return (
            <div
              key={n}
              data-slide={n}
              className={`stu-slide ${isCurrent ? "is-on" : ""}`}
              style={slideStyle}
              ref={(el) => {
                if (el) slideRefs.current.set(n, el);
                else slideRefs.current.delete(n);
              }}
              onClick={() => {
                if (n !== currentPage) {
                  currentPageRef.current = n;
                  setCurrentPage(n);
                  if (typeof onVisiblePage === "function") {
                    onVisiblePage(n);
                  }
                }
              }}
            >
              {shouldRender ? (
                <PdfPageCanvas
                  doc={doc}
                  pageNum={n}
                  targetWidth={slideWidth}
                  onAspectMeasured={handleAspectMeasured}
                />
              ) : (
                <div
                  className="stu-slide-placeholder"
                  aria-label={`Folie ${n} (wird geladen)`}
                >
                  <span className="stu-muted" style={{ fontSize: "11px" }}>
                    Folie {n}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default PdfView;
