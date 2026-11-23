// folien.js: Erkennung, Link-Erzeugung und Klick-Delegation fuer Folien-Referenzen

export function linkifyFolien(html) {
  if (!html || typeof html !== "string") return "";

  // Geschuetzte Tags (code, pre, a) und sonstige HTML-Tags unveraendert beibehalten
  const tagPattern = /(<code[\s\S]*?<\/code>|<pre[\s\S]*?<\/pre>|<a\b[\s\S]*?<\/a>|<[^>]+>)/gi;
  const parts = html.split(tagPattern);

  // Ein einziges Muster mit Alternation fuer Bereiche, Aufzaehlungen und Einzelfolien
  const folienPattern = /\b(Folien?)\s+(\d+)(?:\s*[–\-\u2013\u2014]\s*(\d+)|((?:,\s*\d+)+))?\b/g;

  for (let i = 0; i < parts.length; i += 2) {
    const text = parts[i];
    if (!text) continue;

    parts[i] = text.replace(
      folienPattern,
      (match, prefix, num, rangeEnd, commaList) => {
        if (rangeEnd !== undefined) {
          // Bereich "Folien 3–5" bzw. "Folien 3-5": ein Link auf 3 (Text bleibt vollstaendig)
          return `<a class="stu-flink" data-folie="${num}" href="#">${match}</a>`;
        }
        if (commaList !== undefined) {
          // Aufzaehlung "Folie 3, 5": getrennte Links
          const first = `<a class="stu-flink" data-folie="${num}" href="#">${prefix} ${num}</a>`;
          const others = commaList.replace(
            /\d+/g,
            (m) => `<a class="stu-flink" data-folie="${m}" href="#">${m}</a>`
          );
          return first + others;
        }
        // Einzelne "Folie N" oder "Folien N"
        return `<a class="stu-flink" data-folie="${num}" href="#">${prefix} ${num}</a>`;
      }
    );
  }

  return parts.join("");
}

export function onFolieClick(event, openFolie) {
  if (!event || typeof openFolie !== "function") return;
  const target = event.target?.closest?.(".stu-flink");
  if (!target) return;

  event.preventDefault();
  const raw = target.dataset.folie || target.getAttribute("data-folie");
  const num = Number(raw);
  if (!Number.isNaN(num) && num > 0) {
    openFolie(num);
  }
}

export function firstFolieIn(element) {
  if (!element) return null;
  const link = element.classList?.contains?.("stu-flink")
    ? element
    : element.querySelector?.(".stu-flink");
  if (!link) return null;

  const raw = link.dataset?.folie || link.getAttribute?.("data-folie");
  const num = Number(raw);
  return Number.isNaN(num) ? null : num;
}
