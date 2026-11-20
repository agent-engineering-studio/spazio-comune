import { useState } from "react";
import { api } from "./api.js";
import { Alert, Field } from "./components.jsx";

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onLoggedIn((await api.login(username, password)).utente); }
    catch (err) { setError(err.message); setPassword(""); }
    finally { setBusy(false); }
  };

  return (
    <main className="container my-5" id="main-content">
      <div className="row justify-content-center"><div className="col-md-6 col-lg-5">
        <h1 className="h2">Amministrazione</h1>
        <p>Impostazioni del servizio di prenotazione: luogo, tariffe, orari, pagamenti, SPID/CIE e accessi del personale.</p>
        {error && <Alert type="danger">{error}</Alert>}
        <form onSubmit={submit}>
          <Field id="username" label="Utente" value={username} onChange={setUsername} autoComplete="username" required />
          <Field id="password" label="Password" type="password" value={password} onChange={setPassword}
                 autoComplete="current-password" required help="Credenziali ADMIN_USER e ADMIN_PASSWORD del file .env, o quelle impostate in Accessi del personale." />
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Accesso…" : "Entra"}</button>
        </form>
      </div></div>
    </main>
  );
}
