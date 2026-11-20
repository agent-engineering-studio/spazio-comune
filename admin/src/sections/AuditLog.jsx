import { useEffect, useState } from "react";
import { api } from "../api.js";
import { formatDateTime } from "../components.jsx";

// Le chiavi sono i nomi delle sezioni restituiti dall'API (campo "sezione").
const SECTION_TITLES = { luogo: "Luogo e Comune", attivita: "Attività e tariffe", orari: "Orari e disponibilità",
  pagamenti: "Pagamenti pagoPA", identita: "Accesso SPID/CIE", accessi: "Accessi del personale" };

export default function AuditLog({ handleError }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.auditLog().then(setRows).catch(handleError); }, [handleError]);
  if (!rows) return <p>Caricamento…</p>;
  return (
    <>
      <p>Chi ha modificato le impostazioni e quando. Si registrano i nomi dei campi cambiati, mai i valori dei segreti.</p>
      <div className="table-responsive">
        <table className="table table-sm">
          <caption className="visually-hidden">Ultime 200 modifiche alle impostazioni</caption>
          <thead><tr><th scope="col">Quando</th><th scope="col">Utente</th><th scope="col">Sezione</th><th scope="col">Campi</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={4}>Nessuna modifica: tutte le impostazioni seguono il file .env.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}><td className="text-nowrap">{formatDateTime(r.quando)}</td><td>{r.utente}</td>
                <td>{SECTION_TITLES[r.sezione] || r.sezione}</td><td className="small">{r.campi.join(", ")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
