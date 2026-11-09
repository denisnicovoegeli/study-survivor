// utils.js: Gemeinsame Hilfsfunktionen fuer Kalender, Kanban, Uebersicht, Projekte und Suche
import { api } from "../app/api.js";

/**
 * Prueft, ob ein Wert ein reines Datum ohne Zeitangabe (JJJJ-MM-TT) ist.
 */
export function isDateOnly(value) {
  if (!value) return false;
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value).trim());
}

/**
 * Parst ein Datum aus `due`.
 * Reines Datum YYYY-MM-DD wird lokal geparst, um UTC-Verschiebungen zu vermeiden.
 * Datums-/Zeitstempel werden per ISO mit "T" geparst.
 */
export function parseDue(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return isNaN(dt.getTime()) ? null : dt;
  }
  const iso = raw.replace(" ", "T");
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Datum eines due-Werts als JJJJ-MM-TT in Zuercher Zeit (wie die Termin-Dateien).
 * Reine Daten werden als Text uebernommen, nie ueber toISOString (UTC) umgerechnet.
 */
export function dueDateStr(value) {
  if (!value) return "";
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const d = parseDue(raw);
  if (!d) return raw.slice(0, 10);
  try {
    return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Zurich" }).format(d);
  } catch {
    return dayKey(d);
  }
}

/**
 * Erzeugt einen Datumsschluessel im Format JJJJ-MM-TT.
 */
export function dayKey(d) {
  if (!d) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Formatiert ein Datum nach Schweizer Konvention (TT.MM.JJJJ).
 */
export function fmtDate(value) {
  const d = parseDue(value);
  if (!d) return String(value || "");
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${day}.${m}.${y}`;
}

/**
 * Formatiert eine Uhrzeit (HH:MM). Liefert leer fuer reine Datumsangaben.
 */
export function fmtTime(value) {
  if (!value || isDateOnly(value)) return "";
  const d = parseDue(value);
  if (!d) return "";
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

/**
 * Formatiert eine Frist mit Datum und optionaler Uhrzeit.
 */
export function fmtDue(value, allDay) {
  const d = parseDue(value);
  if (!d) return String(value || "");
  if (allDay || isDateOnly(value)) return fmtDate(value);
  const time = fmtTime(value);
  return time && time !== "00:00" ? `${fmtDate(value)} ${time}` : fmtDate(value);
}

/**
 * Liefert die lesbare Bezeichnung einer Ereignis- oder Aufgabenart.
 */
export function kindLabel(kind) {
  const map = {
    abgabe: "Abgabe",
    pruefung: "Prüfung",
    praesentation: "Präsentation",
    meilenstein: "Meilenstein",
    praesenz: "Präsenz",
    ausfall: "Ausfall",
    termin: "Termin",
    verarbeiten: "Verarbeiten",
    custom: "Aufgabe",
  };
  return map[kind] || kind || "Termin";
}

/**
 * Berechnet einen deterministischen Farbton (Hue 0-360) anhand eines Kursnamens.
 */
export function courseHue(course) {
  return [...(course || "")].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
}

/**
 * Kuerzt laengere Kursnamen fuer platzsparende Badges und Tags.
 */
export function courseShort(course) {
  return (course || "")
    .replace(/^[\d-]+[A-Z]*\.?[\w.-]*⧸\S+\s*/, "")
    .replace(/^\d+HS\s|\s\d+H\d$|\s(BAI|HS|FS)\b.*$/g, "")
    .slice(0, 28);
}

/**
 * Berechnet die Tage bis zum Stichtag (negativ bei Ueberfaelligkeit).
 */
export function countdownDays(datumStr) {
  if (!datumStr) return null;
  const d = parseDue(datumStr);
  if (!d) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((target - today) / 86400000);
}

/**
 * Textuelle Beschreibung des Countdowns.
 */
export function countdownLabel(days) {
  if (days === null || days === undefined) return "";
  if (days < 0) return `überfällig seit ${-days} T.`;
  if (days === 0) return "heute fällig";
  if (days === 1) return "morgen";
  return `noch ${days} T.`;
}

/**
 * Durchsucht den Dateibaum nach Dateinamen oder Pfaden.
 */
export function searchTree(roots, query, limit = 30) {
  if (!roots || !query) return [];
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const results = [];

  function walk(nodes, rootName) {
    if (!nodes) return;
    for (const node of nodes) {
      if (node.type === "file") {
        const nameMatch = node.name && node.name.toLowerCase().includes(q);
        const pathMatch = node.path && node.path.toLowerCase().includes(q);
        if (nameMatch || pathMatch) {
          results.push({
            root: rootName,
            path: node.path,
            name: node.name,
            kind: node.kind,
            size: node.size,
          });
          if (results.length >= limit) return;
        }
      }
      if (node.children) {
        walk(node.children, rootName);
        if (results.length >= limit) return;
      }
    }
  }

  for (const r of roots) {
    if (r.children) {
      walk(r.children, r.root);
      if (results.length >= limit) break;
    }
  }
  return results;
}

/**
 * Findet eine Datei im Dateibaum anhand ihres Dateinamens oder Teilpfads.
 */
export function resolveFileInTree(tree, fileNameOrPath) {
  if (!tree?.roots || !fileNameOrPath) return null;
  const target = String(fileNameOrPath).trim();
  const targetLower = target.toLowerCase();
  const targetBase = target.split("/").pop()?.toLowerCase();

  for (const r of tree.roots) {
    let match = null;
    function walk(nodes) {
      if (!nodes || match) return;
      for (const node of nodes) {
        if (node.type === "file") {
          const pathLower = node.path.toLowerCase();
          const nameLower = node.name.toLowerCase();
          if (pathLower === targetLower || pathLower.endsWith("/" + targetLower)) {
            match = { root: r.root, path: node.path, name: node.name, kind: node.kind };
            return;
          }
          if (targetBase && nameLower === targetBase) {
            match = { root: r.root, path: node.path, name: node.name, kind: node.kind };
            return;
          }
        }
        if (node.children) {
          walk(node.children);
        }
      }
    }
    walk(r.children);
    if (match) return match;
  }
  return null;
}
