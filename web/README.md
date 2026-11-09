# Studium-Workspace (Frontend)

Vite-Build als IIFE fuer das Hermes-Plugin-SDK (React extern ueber `window.__HERMES_PLUGIN_SDK__`, `react/jsx-runtime` ueber `src/jsx-shim.js`).

## Build

```bash
npm install
npm run build   # Erstellt ../dashboard/dist/ (index.js, style.css, katex/, pdfjs/)
```

Die Build-Ausgabe landet direkt in `../dashboard/dist/` (ersetzt das alte Bundle) und wird ueber `manifest.json` eingebunden.

## Ordnerstruktur

- `src/app/`: Hauptansicht (`Studio.jsx`), Store und Zustand (`store.jsx`), Navigationsleiste (`Rail.jsx`) und Backend-API-Client (`api.js`)
- `src/ui/`: Wiederverwendbare UI-Komponenten (`Icon.jsx`, `Badge.jsx`, `Loading.jsx`), Speicher-Helfer (`storage.js`), Hooks (`hooks.js`) und Folien-Link-Erkennung (`folien.js`)
- `src/styles/`: Globale Design-Tokens (`tokens.css`) und Shell-Layout (`shell.css`)
- `src/explorer/`: Dateibaum fuer Kursmaterialien (`Explorer.jsx`) und fruehere Sessions (`Sessions.jsx`)
- `src/doc/`: Dokumentbereich (`DocArea.jsx`) mit Tab-Leiste, CodeMirror-Markdown-Editor, Vorschau und Versionshistorie
- `src/pdf/`: PDF-Viewer (`PdfView.jsx`) mit Foliensynchronisation und Zoom
- `src/chat/`: Hermes-Chat-Panel (`ChatPanel.jsx`) mit Singleton-Gateway (`gw.js`), Skill-Ausfuehrung, Freigaben und Datei-Karten
- `src/read/`: Magazin-Lesemodus (`ReadMode.jsx`) mit Kurs-Kopf, Kennzahlen, Wochen-Zeitleiste und Inhaltsverzeichnis
- `src/plan/`: Planungsansichten (Kalender, Kanban, Uebersicht, Projekte, Suche)
- `src/lib/`: Kernbibliotheken fuer Dateioperationen (`files.js`), WebSocket-Gateway (`gateway.js`), Markdown und KaTeX (`markdown.js`), Editor (`editor.js`) sowie Asset-URLs (`assets.js`)

## Laufzeit-Laden von pdf.js

`pdfjs-dist` wird zur Laufzeit dynamisch geladen und ist nicht Teil des Hauptbundles, wodurch das Bundle unter 1,5 MB bleibt. Beim Build werden `pdf.min.mjs` und `pdf.worker.min.mjs` als eigenstaendige ESM-Dateien nach `dist/pdfjs/` kopiert. `PdfView.jsx` laedt das Modul einmalig ueber einen dynamischen Import und konfiguriert den Worker-Pfad relativ zu `BASE_URL`.
