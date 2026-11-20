// Chiamate all'API di amministrazione: cookie di sessione firmato + header X-CSRF-Token.
let csrf = "";

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(method, path, body, file) {
  const r = await fetch(`/api/v1/admin${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": file ? (file.type || "application/octet-stream") : "application/json", "X-CSRF-Token": csrf },
    body: file || (body === undefined ? undefined : JSON.stringify(body)),
  });
  let data = null;
  try { data = await r.json(); } catch { /* risposta senza JSON */ }
  if (!r.ok) {
    const msg = data?.errore || (typeof data?.detail === "string" ? data.detail : null) || `Errore ${r.status}`;
    throw new ApiError(msg, r.status);
  }
  return data;
}

export const api = {
  async session() { const d = await request("GET", "/session"); csrf = d.csrf; return d; },
  async login(utente, password) { const d = await request("POST", "/login", { utente, password }); csrf = d.csrf; return d; },
  async logout() { await request("POST", "/logout"); csrf = ""; },
  settings: () => request("GET", "/settings"),
  save: (section, values) => request("PUT", `/settings/${section}`, values),
  restore: (section) => request("POST", `/settings/${section}/restore`),
  verifyOidc: () => request("POST", "/identity/verify"),
  auditLog: () => request("GET", "/audit-log"),
  uploadLogo: (file) => request("PUT", "/logo", undefined, file),
  deleteLogo: () => request("DELETE", "/logo"),
};
