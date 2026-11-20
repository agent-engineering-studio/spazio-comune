import { useState } from "react";
import { Alert, Field } from "../components.jsx";
import { SaveBar, useDraft, useSubmit } from "../draft.jsx";

// Il primo elemento è il prefisso dei campi JSON dell'API (admin_user, ufficio_password, custode_password...).
const ROLES = [
  ["admin", "Amministratore (questa interfaccia)", "/admin"],
  ["ufficio", "Ufficio", "/ufficio"],
  ["custode", "Custode", "/custode"],
];

export default function StaffAccess({ data, meta, save, onChange }) {
  const a = data.accessi;
  const [d, set] = useDraft({ admin_user: a.admin_user, ufficio_user: a.ufficio_user, rigenera_feed: false,
    admin_password: "", admin_confirm: "", ufficio_password: "", ufficio_confirm: "", custode_password: "", custode_confirm: "" }, onChange);
  const [busy, submit] = useSubmit(save);
  const [error, setError] = useState(null);

  const onSubmit = (e) => {
    setError(null);
    for (const [role, label] of ROLES) {
      if (d[`${role}_password`] !== d[`${role}_confirm`]) { e.preventDefault(); setError(`Password ${label}: le due password non coincidono`); return; }
    }
    const { admin_confirm, ufficio_confirm, custode_confirm, ...values } = d;
    submit(values)(e);
  };

  return (
    <form onSubmit={onSubmit} noValidate autoComplete="off">
      <p>Credenziali del personale. Le password si salvano solo come hash (scrypt): nessuno, nemmeno l'amministratore, può rileggerle.
        Lascia vuoti i campi password che non vuoi cambiare.</p>
      {error && <Alert type="danger">{error}</Alert>}
      {ROLES.map(([role, label, page]) => (
        <fieldset className="border rounded p-3 mb-3" key={role}>
          <legend className="h6 float-none w-auto px-2 mb-0">{label} – <code>{page}</code></legend>
          {role === "custode" ? <p className="small mb-2">Utente: <code>custode</code></p> : (
            <Field id={`${role}-user`} label="Utente" value={d[`${role}_user`]} onChange={(v) => set(`${role}_user`, v)} required autoComplete="off"
                   help={role === "ufficio" ? "Lo usa anche il server MCP per gli strumenti dell'ufficio (MCP_UFFICIO_USER/PASSWORD nel .env): aggiornali insieme." : undefined} />
          )}
          <p className="small mb-2">Password attuale: {a[`${role}_hash`] ? "impostata da questa interfaccia" : "quella del file .env"}.</p>
          <div className="row">
            <div className="col-md-6"><Field id={`${role}-password`} type="password" label="Nuova password" value={d[`${role}_password`]}
              onChange={(v) => set(`${role}_password`, v)} autoComplete="new-password" minLength={meta.password_minima}
              help={`Almeno ${meta.password_minima} caratteri.`} /></div>
            <div className="col-md-6"><Field id={`${role}-confirm`} type="password" label="Ripeti la nuova password" value={d[`${role}_confirm`]}
              onChange={(v) => set(`${role}_confirm`, v)} autoComplete="new-password" /></div>
          </div>
        </fieldset>
      ))}
      <fieldset className="border rounded p-3 mb-3"><legend className="h6 float-none w-auto px-2 mb-0">Calendario iCal dell'ufficio</legend>
        <p className="small">Indirizzo attuale: <code className="text-break">{meta.feed}</code></p>
        <p className="small">Chi conosce l'indirizzo vede gli orari prenotati. Rigenerandolo, il vecchio smette di funzionare e va sottoscritto il nuovo.</p>
        <div className="form-check">
          <input className="form-check-input" type="checkbox" id="regenerate-feed" checked={d.rigenera_feed} onChange={(e) => set("rigenera_feed", e.target.checked)} />
          <label className="form-check-label" htmlFor="regenerate-feed">Genera un nuovo indirizzo del calendario</label>
        </div>
      </fieldset>
      <SaveBar busy={busy} />
    </form>
  );
}
