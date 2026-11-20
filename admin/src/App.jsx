import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api.js";
import { Alert, formatDateTime } from "./components.jsx";
import Login from "./Login.jsx";
import Venue from "./sections/Venue.jsx";
import Activities from "./sections/Activities.jsx";
import Schedule from "./sections/Schedule.jsx";
import Payments from "./sections/Payments.jsx";
import Identity from "./sections/Identity.jsx";
import StaffAccess from "./sections/StaffAccess.jsx";
import AuditLog from "./sections/AuditLog.jsx";

// Le chiavi sono sia segmenti dell'URL della pagina sia dell'API: restano in italiano.
export const SECTIONS = {
  venue: { dataKey: "luogo", title: "Luogo, Comune e logo", Component: Venue },
  activities: { dataKey: "attivita", title: "Attività e tariffe", Component: Activities },
  schedule: { dataKey: "orari", title: "Orari e disponibilità", Component: Schedule },
  payments: { dataKey: "pagamenti", title: "Pagamenti pagoPA", Component: Payments },
  identity: { dataKey: "identita", title: "Accesso SPID/CIE", Component: Identity },
  access: { dataKey: "accessi", title: "Accessi del personale", Component: StaffAccess },
  "audit-log": { dataKey: null, title: "Registro delle modifiche", Component: AuditLog },
};

function sectionFromUrl() {
  const s = window.location.pathname.replace(/^\/admin\/?/, "").split("/")[0];
  return SECTIONS[s] ? s : "venue";
}

export default function App() {
  const [user, setUser] = useState(undefined);   // undefined = verifica in corso, null = non entrato
  const [data, setData] = useState(null);
  const [section, setSection] = useState(sectionFromUrl);
  const [outcome, setOutcome] = useState(null);   // {type, text}
  const [dirty, setDirty] = useState(false);

  const handleError = useCallback((e) => {
    if (e instanceof ApiError && e.status === 401) { setUser(null); setData(null); return; }
    setOutcome({ type: "danger", text: e.message });
  }, []);

  useEffect(() => { api.session().then((s) => setUser(s.utente)).catch(() => setUser(null)); }, []);
  useEffect(() => { if (user) api.settings().then(setData).catch(handleError); }, [user, handleError]);
  useEffect(() => {
    const onPopState = () => setSection(sectionFromUrl());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    document.title = `${SECTIONS[section].title} – Amministrazione – Spazio Comune`;
  }, [section]);

  const navigate = (s) => {
    if (dirty && !window.confirm("Ci sono modifiche non salvate. Uscire comunque dalla sezione?")) return;
    window.history.pushState({}, "", `/admin/${s}`);
    setSection(s); setOutcome(null); setDirty(false);
    document.getElementById("main-content")?.focus();
  };

  const save = async (s, values) => {
    setOutcome(null);
    try {
      const updated = await api.save(s, values);
      setData(updated); setDirty(false);
      setOutcome({ type: "success", text: updated.campi_modificati?.length
        ? "Impostazioni salvate: sono già in uso." : "Nessuna modifica da salvare." });
      return true;
    } catch (e) { handleError(e); return false; }
  };

  const restore = async (s) => {
    if (!window.confirm("Eliminare le modifiche di questa sezione e tornare ai valori del file .env?")) return;
    try { setData(await api.restore(s)); setDirty(false); setOutcome({ type: "success", text: "Ripristinati i valori del file .env." }); }
    catch (e) { handleError(e); }
  };

  const logout = async () => { await api.logout().catch(() => {}); setUser(null); setData(null); };

  if (user === undefined) return <p className="container my-5">Caricamento…</p>;
  if (user === null) return <Login onLoggedIn={setUser} />;

  const { title, Component, dataKey } = SECTIONS[section];
  const saved = dataKey ? data?.salvate?.[dataKey] : null;
  return (
    <>
      <header className="it-header-wrapper">
        <div className="it-header-slim-wrapper">
          <div className="container"><div className="it-header-slim-wrapper-content">
            <span className="navbar-brand text-white">{data?.meta.comune || "Spazio Comune"}</span>
            <div className="it-header-slim-right-zone">
              <span className="text-white small me-3">{user}</span>
              <a className="btn btn-primary btn-sm me-2" href="/backoffice">Backoffice</a>
              <button type="button" className="btn btn-primary btn-sm" onClick={logout}>Esci</button>
            </div>
          </div></div>
        </div>
        <div className="it-nav-wrapper"><div className="it-header-center-wrapper"><div className="container">
          <div className="it-header-center-content-wrapper"><div className="it-brand-wrapper"><a href="/admin">
            {data?.meta.logo && <img className="icon venue-logo" src={data.meta.logo} alt="" />}
            <div className="it-brand-text">
              <div className="it-brand-title">{data?.meta.comune || "Spazio Comune"}</div>
              <div className="it-brand-tagline">Amministrazione · {data?.meta.luogo}</div>
            </div>
          </a></div></div>
        </div></div></div>
      </header>

      <div className="container my-4">
        <div className="row">
          <nav className="col-lg-3 mb-4 admin-nav" aria-label="Sezioni delle impostazioni">
            <ul className="list-group">
              {Object.entries(SECTIONS).map(([key, s]) => (
                <li className="list-group-item p-0" key={key}>
                  <a className="d-block px-3 py-2" href={`/admin/${key}`} aria-current={key === section ? "page" : undefined}
                     onClick={(e) => { e.preventDefault(); navigate(key); }}>
                    {s.title}
                    {s.dataKey && data?.salvate?.[s.dataKey] && <span className="badge bg-primary ms-2" title="Salvata dal back-office">personalizzata</span>}
                  </a>
                </li>
              ))}
            </ul>
            <p className="small text-muted mt-2">Le sezioni non personalizzate seguono il file <code>.env</code>.</p>
          </nav>

          <main className="col-lg-9" id="main-content" tabIndex={-1}>
            <h1 className="h2">{title}</h1>
            {data?.errori?.map((e) => <Alert key={e} type="danger">{e}</Alert>)}
            {outcome && <Alert type={outcome.type} title={outcome.type === "danger" ? "Non salvato." : null}>{outcome.text}</Alert>}
            {saved && <p className="small text-muted">Ultima modifica: {formatDateTime(saved.aggiornata_il)} da {saved.aggiornata_da}.</p>}
            {!data ? <p>Caricamento…</p> : (
              <Component key={`${section}-${(dataKey && data.salvate?.[dataKey]?.aggiornata_il) || "env"}`} data={data} meta={data.meta}
                         save={(v) => save(section, v)} onChange={() => setDirty(true)} handleError={handleError}
                         updateData={(updated, text) => { setData(updated); setOutcome({ type: "success", text }); }} />
            )}
            {saved && section !== "audit-log" && (
              <div className="mt-4 border-top pt-3">
                <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => restore(section)}>
                  Torna ai valori del file .env
                </button>
              </div>
            )}
          </main>
        </div>
      </div>
    </>
  );
}
