import { Field } from "../components.jsx";
import { SaveBar, useDraft, useSubmit } from "../draft.jsx";
import FeeBands, { bandsFromDraft, bandsToDraft } from "./FeeBands.jsx";

const toEuro = (cents) => (cents == null ? "" : (cents / 100).toFixed(2).replace(".", ","));

function toCents(text, name) {
  const t = String(text).trim().replace("€", "").replace(/\s/g, "");
  if (!/^\d{1,6}([.,]\d{1,2})?$/.test(t)) throw new Error(`Attività ${name}: tariffa in euro, es. 40 oppure 12,50`);
  const [whole, decimals = ""] = t.replace(",", ".").split(".");
  return Number(whole) * 100 + Number((decimals + "00").slice(0, 2));
}

export default function Activities({ data, meta, save, onChange, handleError }) {
  const savedCodes = new Set(data.attivita.elenco.map((a) => a.codice));
  // "fee" è solo locale (testo in euro): all'API va tariffa_cent.
  const [d, set, replace] = useDraft(
    { ...data.attivita, elenco: data.attivita.elenco.map((a) => ({ ...a, fee: toEuro(a.tariffa_cent) })),
      fasce_tariffarie: bandsToDraft(data.attivita.fasce_tariffarie || [], toEuro) }, onChange);
  const [busy, submit] = useSubmit(save);
  const setRow = (i, field, value) => replace((x) => ({ ...x, elenco: x.elenco.map((a, j) => (j === i ? { ...a, [field]: value } : a)) }));
  const addRow = () => replace((x) => ({ ...x, elenco: [...x.elenco, { codice: "", nome: "", fee: "", giocatori: "", preparazione: "", attiva: true }] }));
  const removeRow = (i) => replace((x) => ({ ...x, elenco: x.elenco.filter((_, j) => j !== i) }));

  const values = () => {
    try {
      return { fonte_tariffe: d.fonte_tariffe,
               elenco: d.elenco.map(({ fee, ...a }) => ({ ...a, tariffa_cent: toCents(fee, a.nome || a.codice) })),
               fasce_tariffarie: bandsFromDraft(d.fasce_tariffarie, toCents) };
    } catch (e) { handleError(e); throw e; }
  };

  return (
    <form onSubmit={(e) => submit(values)(e).catch(() => {})} noValidate>
      <p>Le attività prenotabili e le tariffe approvate dall'ente: l'importo è per l'intero slot e diventa il dovuto pagoPA.
        Un'attività già salvata non si elimina (serve a leggere le prenotazioni passate): si rende non prenotabile.</p>
      <Field id="fee-source" label="Atto che approva le tariffe" value={d.fonte_tariffe} onChange={(v) => set("fonte_tariffe", v)}
             help="Citato accanto ai prezzi, es. D.G.C. n. 37/2025 – approvazione tariffe impianti sportivi 2025." />
      {d.elenco.map((a, i) => {
        const existing = savedCodes.has(a.codice);
        return (
          <fieldset className="border rounded p-3 mb-3" key={i}>
            <legend className="h6 float-none w-auto px-2 mb-0">{a.nome || "Nuova attività"}</legend>
            <div className="row g-2">
              <div className="col-md-3">
                <label className="form-label small" htmlFor={`a-${i}-code`}>Codice</label>
                <input id={`a-${i}-code`} className="form-control form-control-sm border" value={a.codice} readOnly={existing}
                       placeholder="es. pallavolo" aria-describedby={`a-${i}-code-help`}
                       onChange={(e) => setRow(i, "codice", e.target.value.toLowerCase())} />
                <small id={`a-${i}-code-help`} className="form-text">{existing ? "non modificabile" : "minuscole, cifre e _"}</small>
              </div>
              <div className="col-md-5">
                <label className="form-label small" htmlFor={`a-${i}-name`}>Nome mostrato</label>
                <input id={`a-${i}-name`} className="form-control form-control-sm border" value={a.nome} maxLength={80}
                       onChange={(e) => setRow(i, "nome", e.target.value)} />
              </div>
              <div className="col-md-2">
                <label className="form-label small" htmlFor={`a-${i}-fee`}>Tariffa (€)</label>
                <input id={`a-${i}-fee`} className="form-control form-control-sm border" inputMode="decimal" value={a.fee}
                       onChange={(e) => setRow(i, "fee", e.target.value)} />
              </div>
              <div className="col-md-2">
                <label className="form-label small" htmlFor={`a-${i}-players`}>Giocatori</label>
                <input id={`a-${i}-players`} className="form-control form-control-sm border" value={a.giocatori} maxLength={40}
                       onChange={(e) => setRow(i, "giocatori", e.target.value)} />
              </div>
              <div className="col-md-8">
                <label className="form-label small" htmlFor={`a-${i}-setup`}>Nota per il custode</label>
                <input id={`a-${i}-setup`} className="form-control form-control-sm border" value={a.preparazione} maxLength={120}
                       placeholder="es. Montare la rete" onChange={(e) => setRow(i, "preparazione", e.target.value)} />
              </div>
              <div className="col-md-4 d-flex align-items-end gap-3">
                <div className="form-check">
                  <input className="form-check-input" type="checkbox" id={`a-${i}-active`} checked={!!a.attiva}
                         onChange={(e) => setRow(i, "attiva", e.target.checked)} />
                  <label className="form-check-label" htmlFor={`a-${i}-active`}>Prenotabile</label>
                </div>
                {!existing && <button type="button" className="btn btn-link btn-sm" onClick={() => removeRow(i)}>Rimuovi</button>}
              </div>
            </div>
          </fieldset>
        );
      })}
      <button type="button" className="btn btn-outline-primary btn-sm mb-4" onClick={addRow}>Aggiungi un'attività</button>
      <FeeBands bands={d.fasce_tariffarie} meta={meta} onChange={(v) => set("fasce_tariffarie", v)}
                activities={d.elenco.filter((a) => a.attiva && a.codice)} />
      <SaveBar busy={busy} />
    </form>
  );
}
