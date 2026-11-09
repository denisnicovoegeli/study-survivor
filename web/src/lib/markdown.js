// Markdown-Vorschau: markdown-it + KaTeX ($...$, $$...$$, \(...\), \[...\]).
import MarkdownIt from "markdown-it";
import { katex } from "@mdit/plugin-katex";
import { ensureStylesheet } from "./assets.js";

// html: false, weil Kursmaterial im Dashboard-Origin gerendert wird (kein Roh-HTML).
const md = new MarkdownIt({ html: false, linkify: true, typographer: false, breaks: false });
md.use(katex, { delimiters: "all", throwOnError: false, strict: "ignore" });

// Links in einem neuen Tab oeffnen, damit das Dashboard nicht weg-navigiert.
const defaultLinkOpen = md.renderer.rules.link_open
  || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const href = tokens[idx].attrGet("href") || "";
  if (/^https?:/i.test(href)) {
    tokens[idx].attrSet("target", "_blank");
    tokens[idx].attrSet("rel", "noopener noreferrer");
  }
  return defaultLinkOpen(tokens, idx, options, env, self);
};

// KaTeX-CSS und Fonts liegen als eigene Dateien unter dist/katex/.
export function ensureKatexCss() {
  ensureStylesheet("katex/katex.min.css");
}

// Rendert Markdown zu HTML (fuer dangerouslySetInnerHTML).
export function renderMarkdown(text) {
  ensureKatexCss();
  return md.render(text || "");
}

export { md };
