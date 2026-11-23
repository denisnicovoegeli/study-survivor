// storage.js: Zugriff auf localStorage mit Fehlerbehandlung und stu-Praefix

const PREFIX = "stu-";

export function load(key, def) {
  try {
    const val = localStorage.getItem(PREFIX + key);
    if (val === null || val === undefined) return def;
    try {
      return JSON.parse(val);
    } catch {
      return val;
    }
  } catch {
    return def;
  }
}

export function save(key, v) {
  try {
    if (v === undefined || v === null) {
      localStorage.removeItem(PREFIX + key);
    } else {
      const serialized = typeof v === "object" ? JSON.stringify(v) : String(v);
      localStorage.setItem(PREFIX + key, serialized);
    }
  } catch {
    // Fehler ignorieren, z. B. bei deaktiviertem localStorage oder vollem Speicher
  }
}
