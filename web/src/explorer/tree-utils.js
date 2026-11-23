// tree-utils.js: Hilfsfunktionen fuer Dateibaum, Wochengruppierung und Moodle-Status
// Reines Javascript ohne externe Abhaengigkeiten.

/**
 * Sucht einen Knoten nach absolutem/relativem Pfad unter einer Wurzel.
 */
export function findPathInTree(tree, rootName, targetPath) {
  if (!tree?.roots || !targetPath) return null;
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

/**
 * Sucht einen Knoten nach Dateinamen unter einer Wurzel.
 */
export function findNameInTree(tree, rootName, targetName) {
  if (!tree?.roots || !targetName) return null;
  const rootNode = tree.roots.find((r) => r.root === rootName);
  if (!rootNode) return null;

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
  return walk(rootNode.children);
}

/**
 * Findet den Kurs-Ordner unter einer gegebenen Wurzel.
 * Erste Ebene unter jeder Wurzel ist der Kursordner.
 */
export function getCourseNode(tree, rootName, courseName) {
  if (!tree?.roots || !courseName) return null;
  const rootObj = tree.roots.find((r) => r.root === rootName);
  if (!rootObj || !Array.isArray(rootObj.children)) return null;

  // 1. Exakter Name
  let found = rootObj.children.find((c) => c.name === courseName);
  if (found) return found;

  // 2. Case-insensitiver Vergleich
  const lower = courseName.toLowerCase();
  found = rootObj.children.find((c) => c.name?.toLowerCase() === lower);
  if (found) return found;

  // 3. Teilstring-Vergleich (z. B. falls Prefix "26HS" abweicht)
  found = rootObj.children.find((c) => {
    const cLower = (c.name || "").toLowerCase();
    return cLower.includes(lower) || lower.includes(cLower);
  });
  return found || null;
}

/**
 * Ermittelt die Wochennummer aus Abschnittsname oder Dateinamen.
 * Erkennt Formate wie "W01", "W1", "Woche 1", "woche 02".
 */
export function extractWeekNumber(sectionName, files = []) {
  // 1. Pruefung im Abschnittsnamen
  const secMatch = (sectionName || "").match(/(?:Woche\s*|W)0?(\d+)\b/i);
  if (secMatch) return parseInt(secMatch[1], 10);

  // 2. Pruefung in den enthaltenen Dateien
  if (Array.isArray(files)) {
    for (const f of files) {
      const fname = typeof f === "string" ? f : f?.name || "";
      const fMatch = fname.match(/(?:Woche\s*|W)0?(\d+)\b/i);
      if (fMatch) return parseInt(fMatch[1], 10);
    }
  }

  return 999;
}

/**
 * Normalisiert Ordner- und Abschnittsnamen fuer die Anzeige:
 * - Entfernt HTML-Tags (auch Vollbreiten wie ＜span ...＞...＜⧸span＞)
 * - Bereinigt Vollbreiten-Zeichen (：, ⧸, ｜, ？, ＂)
 * - Entfernt ueberfluessige Trennzeichen ("W01 ： Organisatorisches" -> "W01 Organisatorisches")
 */
export function normalizeFolderName(name) {
  if (!name || typeof name !== "string") return "";
  let s = cleanHtml(name);

  // "W01 ： Organisatorisches" -> "W01 Organisatorisches"
  s = s.replace(/^((?:Woche\s*\d+|W\d+))\s*[：:]\s*/i, "$1 ");

  // Vollbreiten-Doppelpunkt generell ersetzen
  s = s.replace(/\s*：\s*/g, ": ");

  // Vollbreiten-Slash ⧸ (U+29F8) und ／ (U+FF0F) durch Slash mit Leerzeichen ersetzen
  s = s.replace(/\s*[⧸／]\s*/g, " / ");

  // Vollbreite Anfuehrungszeichen ＂ durch "
  s = s.replace(/＂/g, '"');

  // Vollbreite Pipes ｜ durch |
  s = s.replace(/｜/g, "|");

  // Vollbreite Fragezeichen ？ durch ?
  s = s.replace(/？/g, "?");

  return s.replace(/\s+/g, " ").trim();
}

/**
 * Bereinigt den Abschnittsnamen fuer die Kopfzeile "W01 <Abschnitt kurz>".
 * Entfernt fuehrende Wochennummern wie "Woche 1: " oder "W01 - ".
 */
export function cleanShortSection(sectionName) {
  if (!sectionName) return "";
  let s = normalizeFolderName(sectionName);
  // Entferne fuehrende Wochenspezifikation
  s = s.replace(/^(?:Woche\s*\d+|W\d+)\s*[-_：:–—/]\s*/i, "").trim();
  s = s.replace(/^(?:Woche\s*\d+|W\d+)\s+/i, "").trim();
  if (!s) s = normalizeFolderName(sectionName);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * Bereinigt HTML-Tags (auch Vollbreiten) und unescaped Entities aus Text.
 */
export function cleanHtml(raw) {
  if (!raw || typeof raw !== "string") return "";
  const withoutTags = raw.replace(/[<＜][^>＞]+[>＞]/g, "");
  return withoutTags
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Dateianzeige fuer Lernen: "Zusammenfassung" bzw. "Cheatsheet"
 * statt des Dateinamens (*.zusammenfassung.md, *.cheatsheet.md).
 */
export function formatLernenFileName(filename) {
  if (!filename) return "";
  if (filename.endsWith(".zusammenfassung.md")) return "Zusammenfassung";
  if (filename.endsWith(".cheatsheet.md")) return "Cheatsheet";
  return filename.replace(/\.md$/, "");
}

/**
 * Prueft, ob eine Moodle-Datei neu (unverarbeitet) ist.
 * Gilt nur fuer PDF, PPTX und DOCX ohne zugehoerige knowledge/.../<Datei>.folien.md.
 */
export function isMoodleFileNeu(file, tree) {
  if (!file || !file.name) return false;
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!["pdf", "pptx", "docx"].includes(ext)) {
    return false;
  }

  // 1. Exakter Pfad: moodle/<Kurs>/.../<Datei> -> knowledge/<Kurs>/.../<Datei>.folien.md
  const expectedPath = file.path + ".folien.md";
  if (findPathInTree(tree, "knowledge", expectedPath)) {
    return false;
  }

  // 2. Dateiname als Fallback: <Datei>.folien.md in knowledge
  const expectedName = file.name + ".folien.md";
  if (findNameInTree(tree, "knowledge", expectedName)) {
    return false;
  }

  return true;
}
