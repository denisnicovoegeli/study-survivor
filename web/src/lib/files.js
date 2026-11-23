// API-Client fuer die Datei-Routen unter /api/plugins/studium/files/.
// Wurzeln: "moodle" (nur lesen), "lernen", "knowledge".

const BASE = "/api/plugins/studium/files";

// Fehler mit HTTP-Status. Bei 409 enthaelt `current` die Metadaten des
// aktuellen Stands auf dem Server (oder null, wenn die Datei geloescht wurde).
export class FileApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`;
    super(message);
    this.status = status;
    this.detail = detail;
    this.current = detail && typeof detail === "object" ? detail.current ?? null : null;
  }
  get isConflict() {
    return this.status === 409;
  }
}

function qs(params) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) s.set(k, v);
  return s.toString();
}

async function request(method, path, { params, body } = {}) {
  const url = BASE + path + (params ? "?" + qs(params) : "");
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  // authedFetch wirft nicht bei Fehlercodes, so kommt das detail (z. B. 409) durch.
  const res = await fetch(url, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) throw new FileApiError(res.status, data?.detail ?? res.statusText);
  return data;
}

// Baum aller Wurzeln oder nur einer: {roots: [{root, dir, editable, children: [...]}]}
export function tree(root) {
  return request("GET", "/tree", { params: root ? { root } : undefined });
}

// Textdatei: {root, path, name, kind, size, mtime, mtime_ns, editable, content}
export function read(root, path) {
  return request("GET", "/read", { params: { root, path } });
}

// URL fuer <iframe>/<img>. Funktioniert im Gate-Modus (Cookie), nicht mit Token-Header.
export function rawUrl(root, path) {
  return `${BASE}/raw?${qs({ root, path })}`;
}

// Fallback fuer den Loopback-Modus: Blob-URL ueber authedFetch.
// Aufrufer muss URL.revokeObjectURL() aufrufen.
export async function rawBlobUrl(root, path) {
  const res = await fetch(rawUrl(root, path));
  if (!res.ok) throw new FileApiError(res.status, res.statusText);
  return URL.createObjectURL(await res.blob());
}

// Speichern mit optimistischer Sperre. mtimeNs vom letzten read/write,
// null fuer eine neue Datei. Wirft FileApiError (isConflict) bei Konflikt.
export function write(root, path, content, mtimeNs) {
  return request("PUT", "/write", { body: { root, path, content, mtime_ns: mtimeNs ?? null } });
}

// Gesicherte Versionen, neueste zuerst: [{id, size, created}]
export async function versions(root, path) {
  return (await request("GET", "/versions", { params: { root, path } })).versions;
}

// Inhalt einer Version: {root, path, id, content}
export function version(root, path, id) {
  return request("GET", "/version", { params: { root, path, id } });
}

// Version wiederherstellen; der aktuelle Stand wird vorher selbst gesichert.
export function restore(root, path, id, mtimeNs) {
  return request("POST", "/restore", { body: { root, path, id, mtime_ns: mtimeNs ?? null } });
}

// Absoluter Pfad auf dem Server (fuer Kontext im Chat), aus der Baum-Antwort.
export function absolutePath(treeData, root, path) {
  const dir = treeData?.roots?.find((r) => r.root === root)?.dir;
  return dir ? `${dir.replace(/\/$/, "")}/${path}` : `${root}/${path}`;
}
