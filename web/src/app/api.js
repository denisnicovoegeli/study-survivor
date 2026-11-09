// api.js: API-Client fuer das Studium-Backend unter /api/plugins/studium/

const BASE = "/api/plugins/studium/";

export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function api(path, init) {
  const url = BASE + String(path || "").replace(/^\//, "");
  const options = init ? { ...init } : {};

  if (
    options.body &&
    typeof options.body === "object" &&
    !(options.body instanceof FormData) &&
    !(options.body instanceof Blob)
  ) {
    options.headers = { "Content-Type": "application/json", ...options.headers };
    options.body = JSON.stringify(options.body);
  }

  // authedFetch liefert auch bei Fehlercodes die Antwort mit Body zurueck
  const res = await fetch(url, options);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    throw new ApiError(res.status, data?.detail ?? data ?? res.statusText);
  }

  return data;
}

export default api;
