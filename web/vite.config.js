// Eigenständige Vite-App. Ausgabe nach web/dist, ausgeliefert von FastAPI unter /dashboard-plugins/studium/dist/.
// Entwicklung: npm run dev (Proxy auf das Backend unter localhost:8765).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { cpSync, mkdirSync, readdirSync } from "node:fs";

const outDir = "dist";
const katexDist = fileURLToPath(new URL("./node_modules/katex/dist/", import.meta.url));
const pdfDist = fileURLToPath(new URL("./node_modules/pdfjs-dist/build/pdf.min.mjs", import.meta.url));
const pdfWorkerDist = fileURLToPath(new URL("./node_modules/pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url));

// KaTeX-CSS/Fonts und pdf.js als eigene Dateien nach dist/katex/ und dist/pdfjs/ (Laufzeit-Imports)
function staticAssets() {
  return {
    name: "static-assets",
    apply: "build",
    closeBundle() {
      const target = fileURLToPath(new URL(`./${outDir}/katex/`, import.meta.url));
      mkdirSync(`${target}fonts`, { recursive: true });
      cpSync(`${katexDist}katex.min.css`, `${target}katex.min.css`);
      for (const f of readdirSync(`${katexDist}fonts`)) {
        if (f.endsWith(".woff2")) cpSync(`${katexDist}fonts/${f}`, `${target}fonts/${f}`);
      }
      const pdfjsTarget = fileURLToPath(new URL(`./${outDir}/pdfjs/`, import.meta.url));
      mkdirSync(pdfjsTarget, { recursive: true });
      cpSync(pdfDist, `${pdfjsTarget}pdf.min.mjs`);
      cpSync(pdfWorkerDist, `${pdfjsTarget}pdf.worker.min.mjs`);
    },
  };
}

export default defineConfig({
  base: "/dashboard-plugins/studium/dist/",
  plugins: [react(), staticAssets()],
  build: { target: "es2022", outDir, emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
