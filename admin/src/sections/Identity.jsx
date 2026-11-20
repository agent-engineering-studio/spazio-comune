import { useState } from "react";
import { api } from "../api.js";
import { Alert } from "../components.jsx";

// SPID/CIE si configura nel file .env (IDENTITY_BACKEND e OIDC_*): qui si vede la configurazione in uso e si verifica il gateway.
const ROWS = [
  ["IDENTITY_BACKEND", "backend", "Modalità di accesso"],
  ["OIDC_ISSUER", "oidc_issuer", "Issuer del gateway"],
  ["OIDC_CLIENT_ID", "oidc_client_id", "Client ID"],
  ["OIDC_CLIENT_SECRET", "oidc_client_secret", "Client secret"],
  ["OIDC_REDIRECT_URI", "redirect_uri", "Redirect URI (callback)"],
  ["OIDC_SCOPE", "oidc_scope", "Scope"],
  ["OIDC_ACR_VALUES", "oidc_acr_values", "Livello SPID (acr_values)"],
  ["OIDC_AUTH_METHOD", "oidc_auth_metodo", "Autenticazione al token endpoint"],
  ["OIDC_CLAIM_TAX_CODE", "claim_cf", "Attributo codice fiscale"],
  ["OIDC_CLAIM_NAME", "claim_nome", "Attributo nome"],
  ["OIDC_CLAIM_FAMILY_NAME", "claim_cognome", "Attributo cognome"],
  ["OIDC_CLAIM_EMAIL", "claim_email", "Attributo email"],
];

export default function Identity({ data, meta, handleError }) {
  const current = data.identita;
  const [check, setCheck] = useState(null);
  const [checkError, setCheckError] = useState(null);

  const verifyGateway = async () => {
    setCheck(null); setCheckError(null);
    try { setCheck(await api.verifyOidc()); }
    catch (e) { if (e.status === 422) setCheckError(e.message); else handleError(e); }
  };

  const shown = (key) => {
    const value = current[key];
    if (key === "oidc_client_secret") return value ? "impostato (non mostrato)" : "non impostato";
    if (key === "backend") return meta.backend_identita[value] || value;
    return value || "—";
  };

  return (
    <>
      <p>L'accesso dei cittadini con SPID e CIE (art. 64 CAD) passa da un gateway già accreditato che parla <strong>OpenID Connect</strong> con
        questo servizio: l'area personale del portale del Comune, il proxy SPID/CIE dell'intermediario regionale, un Keycloak o SATOSA con i
        plugin SPID/CIE. Il servizio riceve solo codice fiscale, nome, cognome ed email.</p>
      {current.backend !== "oidc" && <Alert type="warning" title="Accesso simulato.">Chiunque entra come utente di prova: va bene per prove e
        dimostrazioni, non per l'esercizio.</Alert>}
      <div className="callout note mb-4"><div className="callout-title">Si configura nel file .env</div>
        <p className="small mb-1">Per motivi di sicurezza le credenziali del gateway non si cambiano da questa pagina. Sul server:</p>
        <ol className="small mb-1">
          <li>comunicare al gestore del gateway il redirect URI <code>{meta.redirect_uri}</code>;</li>
          <li>scrivere nel file <code>.env</code> (sulla VM: <code>/etc/spazio-comune/spazio-comune.env</code>) <code>IDENTITY_BACKEND=oidc</code> e
            le variabili <code>OIDC_*</code> ricevute;</li>
          <li>riavviare il servizio (<code>sudo systemctl restart spazio-comune-app</code>, oppure <code>docker compose up -d --force-recreate</code>)
            e premere <em>Verifica il gateway</em>.</li>
        </ol>
        <p className="small mb-0">Se una variabile manca o non è valida il servizio non parte e il log indica quale correggere.</p>
      </div>
      <div className="table-responsive">
        <table className="table table-sm">
          <caption className="small">Configurazione in uso</caption>
          <thead><tr><th scope="col">Impostazione</th><th scope="col">Variabile del .env</th><th scope="col">Valore</th></tr></thead>
          <tbody>
            {ROWS.map(([variable, key, label]) => (
              <tr key={variable}><th scope="row" className="fw-normal">{label}</th><td><code>{variable}</code></td>
                <td className="text-break">{shown(key)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3">
        <button type="button" className="btn btn-outline-primary" onClick={verifyGateway}>Verifica il gateway</button>
        <span className="small text-muted ms-2">Legge la configurazione OpenID del gateway, senza effettuare accessi.</span>
      </div>
      <div aria-live="polite" className="mt-3">
        {checkError && <Alert type="danger">{checkError}</Alert>}
        {check && (
          <Alert type="success" title="Gateway raggiungibile.">
            <ul className="small mb-0">
              <li>Issuer: <code>{check.issuer}</code></li>
              <li>Autorizzazione: <code>{check.authorization_endpoint}</code></li>
              <li>Token: <code>{check.token_endpoint}</code></li>
              <li>Userinfo: <code>{check.userinfo_endpoint || "non dichiarato (si usano gli attributi dell'ID token)"}</code></li>
              {check.scopes_supported && <li>Scope: {check.scopes_supported.join(", ")}</li>}
              {check.acr_values_supported && <li>Livelli (acr): {check.acr_values_supported.join(", ")}</li>}
            </ul>
          </Alert>
        )}
      </div>
    </>
  );
}
