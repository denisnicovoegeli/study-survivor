// Basis-URL des Bundles, fuer Dateien neben index.js (z. B. katex/, pdfjs/).
// document.currentScript ist nur waehrend der ersten Ausfuehrung gesetzt,
// deshalb hier auf oberster Ebene festhalten.
const script = typeof document !== "undefined" ? document.currentScript : null;
const base = typeof location !== "undefined" ? location.href : "http://localhost/";
export const BASE_URL = script?.src
  ? new URL(".", script.src).href
  : new URL("/dashboard-plugins/studium/dist/", base).href;

const loaded = new Set();

// Haengt ein Stylesheet einmalig an <head> an (Manifest erlaubt nur eine css).
export function ensureStylesheet(rel) {
  const href = new URL(rel, BASE_URL).href;
  if (loaded.has(href) || document.querySelector(`link[href="${href}"]`)) return;
  loaded.add(href);
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}
