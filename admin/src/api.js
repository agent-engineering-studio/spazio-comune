// Chiamate all'API di amministrazione: cookie di sessione firmato + header X-CSRF-Token.
let csrf = "";

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(method, path, body, file) {
  const r = await fetch(`/api/v1/amministrazione${path}`, {
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
  async session() { const d = await request("GET", "/sessione"); csrf = d.csrf; return d; },
  async login(utente, password) { const d = await request("POST", "/accesso", { utente, password }); csrf = d.csrf; return d; },
  async logout() { await request("POST", "/uscita"); csrf = ""; },
  settings: () => request("GET", "/impostazioni"),
  save: (section, values) => request("PUT", `/impostazioni/${section}`, values),
  restore: (section) => request("POST", `/impostazioni/${section}/ripristina`),
  verifyOidc: () => request("POST", "/identita/verifica"),
  auditLog: () => request("GET", "/registro"),
  uploadLogo: (file) => request("PUT", "/logo", undefined, file),
  deleteLogo: () => request("DELETE", "/logo"),
};
