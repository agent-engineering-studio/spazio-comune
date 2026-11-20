import { Alert, Field, WeekTable, formatShortDate } from "../components.jsx";
import { SaveBar, useDraft, useSubmit } from "../draft.jsx";

// Valori del campo API "festivi": "chiuso", "aperto" oppure le fasce orarie dei festivi.
export default function Schedule({ data, meta, save, onChange }) {
  const s = data.orari;
  const initialMode = ["chiuso", "aperto"].includes(s.festivi) ? s.festivi : "orario";
  // holidayMode e holidaySlots sono solo locali: all'API si invia il solo campo "festivi".
  const [d, set, replace] = useDraft({ ...s, holidayMode: initialMode, holidaySlots: initialMode === "orario" ? s.festivi : "" }, onChange);
  const [busy, submit] = useSubmit(save);

  const setItem = (key, i, field, value) =>
    replace((x) => ({ ...x, [key]: x[key].map((el, j) => (j === i ? { ...el, [field]: value } : el)) }));
  const addItem = (key, el) => replace((x) => ({ ...x, [key]: [...x[key], el] }));
  const removeItem = (key, i) => replace((x) => ({ ...x, [key]: x[key].filter((_, j) => j !== i) }));

  const values = () => {
    const { holidayMode, holidaySlots, ...rest } = d;
    return { ...rest, festivi: holidayMode === "orario" ? holidaySlots : holidayMode };
  };

  return (
    <form onSubmit={submit(values)} noValidate>
      <p>Giorni e fasce orarie prenotabili secondo il regolamento comunale. Le modifiche valgono subito sul calendario
        pubblico; le prenotazioni già fatte restano valide.</p>
      <div className="callout note mb-4"><div className="callout-title">Come si scrivono le fasce</div>
        <p className="small mb-0">Intervalli apertura-chiusura separati da virgola: <code>15-22</code>, <code>9-13, 15-22</code> (pausa
          dalle 13 alle 15), <code>08:30-12:30, 16:00-23:30</code>. Fino a <code>24</code> per la mezzanotte. Campo vuoto = chiuso.
          Ogni fascia si divide in slot della durata indicata; un avanzo più corto di uno slot non è prenotabile.</p>
      </div>
      <Alert type="info" title="Orario in vigore:">{data.anteprima}</Alert>
      {data.fuori_calendario.length > 0 && (
        <Alert type="warning" role="alert" title={`${data.fuori_calendario.length} prenotazioni attive fuori dall'orario in vigore.`}>
          Restano valide: contatta gli intestatari o annullale dalla pagina <a href="/backoffice">Backoffice</a>.
          <ul className="mb-0 small">{data.fuori_calendario.map((b) => (
            <li key={b.codice}><span className="font-monospace">{b.codice}</span> – {formatShortDate(b.inizio)} – {b.cognome ? `${b.cognome} ${b.nome}` : b.note}</li>
          ))}</ul>
        </Alert>
      )}

      <fieldset className="mb-4"><legend className="h5">Regole di prenotazione</legend>
        <div className="row">
          <div className="col-md-4"><Field id="slot-minutes" type="number" label="Durata di uno slot (minuti)" value={d.durata_min}
            onChange={(v) => set("durata_min", v)} min={15} max={480} step={5} required help="Di norma 60." /></div>
          <div className="col-md-4"><Field id="booking-window-days" type="number" label="Prenotabile fino a (giorni prima)" value={d.preavviso_giorni}
            onChange={(v) => set("preavviso_giorni", v)} min={1} max={365} required help="Di norma 14." /></div>
          <div className="col-md-4"><Field id="cancellation-hours" type="number" label="Annullamento online fino a (ore prima)" value={d.ore_annullamento}
            onChange={(v) => set("ore_annullamento", v)} min={0} max={720} required help="Dopo, solo tramite ufficio." /></div>
        </div>
      </fieldset>

      <fieldset className="mb-4"><legend className="h5">Orario settimanale</legend>
        <WeekTable idPrefix="w-" meta={meta} values={d.settimana} onChange={(v) => set("settimana", v)}
                   caption="Fasce orarie per ogni giorno, valide tutto l'anno salvo i periodi qui sotto." />
      </fieldset>

      <fieldset className="mb-4"><legend className="h5">Periodi dell'anno con orario diverso</legend>
        <p className="small">Ripetuti ogni anno (es. orario estivo, vacanze di Natale): nel periodo sostituiscono l'orario settimanale;
          se due periodi si sovrappongono vale il primo.</p>
        {d.periodi.map((p, i) => (
          <details className="border rounded p-3 mb-2" key={i} open>
            <summary className="fw-semibold">{p.nome || "Periodo"} {p.dal && `– dal ${p.dal} al ${p.al}`}</summary>
            <div className="row g-2 mt-2">
              <div className="col-md-6"><label className="form-label small" htmlFor={`p-${i}-name`}>Nome</label>
                <input id={`p-${i}-name`} className="form-control form-control-sm border" value={p.nome} placeholder="es. Orario estivo"
                       onChange={(e) => setItem("periodi", i, "nome", e.target.value)} /></div>
              <div className="col-md-3"><label className="form-label small" htmlFor={`p-${i}-from`}>Dal (GG/MM)</label>
                <input id={`p-${i}-from`} className="form-control form-control-sm border" value={p.dal} placeholder="01/06"
                       onChange={(e) => setItem("periodi", i, "dal", e.target.value)} /></div>
              <div className="col-md-3"><label className="form-label small" htmlFor={`p-${i}-to`}>Al (GG/MM)</label>
                <input id={`p-${i}-to`} className="form-control form-control-sm border" value={p.al} placeholder="15/09"
                       onChange={(e) => setItem("periodi", i, "al", e.target.value)} /></div>
            </div>
            <WeekTable idPrefix={`p-${i}-`} meta={meta} values={p.settimana} onChange={(v) => setItem("periodi", i, "settimana", v)}
                       caption="Fasce orarie nel periodo (vuoto = chiuso)." />
            <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => removeItem("periodi", i)}>Elimina il periodo</button>
          </details>
        ))}
        <button type="button" className="btn btn-outline-primary btn-sm"
                onClick={() => addItem("periodi", { nome: "", dal: "", al: "", settimana: { ...d.settimana } })}>
          Aggiungi un periodo (parte dall'orario settimanale)
        </button>
      </fieldset>

      <fieldset className="mb-4"><legend className="h5">Giorni festivi</legend>
        <p className="small">Le festività nazionali (Capodanno, Epifania, Pasqua e Lunedì dell'Angelo, 25 aprile, 1° maggio, 2 giugno,
          Ferragosto, 4 ottobre, Ognissanti, Immacolata, Natale, Santo Stefano) si calcolano in automatico ogni anno.</p>
        {[["chiuso", "Chiuso"], ["aperto", "Aperto come un giorno normale"], ["orario", "Orario festivo ridotto"]].map(([v, t]) => (
          <div className="form-check" key={v}>
            <input className="form-check-input" type="radio" name="holiday-mode" id={`holiday-${v}`} checked={d.holidayMode === v}
                   onChange={() => set("holidayMode", v)} />
            <label className="form-check-label" htmlFor={`holiday-${v}`}>{t}</label>
          </div>
        ))}
        {d.holidayMode === "orario" && (
          <div className="mt-2"><Field id="holiday-slots" label="Fasce nei giorni festivi" value={d.holidaySlots}
            onChange={(v) => set("holidaySlots", v)} help="Es. 16-20. Vale nei giorni della settimana in cui il luogo è aperto." /></div>
        )}
        <div className="mt-3"><Field id="extra-holidays" label="Festività locali e chiusure ricorrenti" value={d.festivi_extra}
          onChange={(v) => set("festivi_extra", v)}
          help="GG/MM (ogni anno) o GG/MM/AAAA (solo quell'anno), separate da virgola. Almeno la festa del santo patrono, es. 26/05." /></div>
      </fieldset>

      <fieldset className="mb-4"><legend className="h5">Chiusure straordinarie</legend>
        <p className="small">Manutenzioni, eventi, ordinanze: nei giorni indicati non si prenota. Il motivo compare nel calendario pubblico.
          Per chiudere solo alcune ore usa "Riserva uno slot" nella pagina <a href="/backoffice">Backoffice</a>.</p>
        {d.chiusure.length > 0 && (
          <table className="table table-sm align-middle">
            <caption className="visually-hidden">Chiusure straordinarie</caption>
            <thead><tr><th scope="col">Dal</th><th scope="col">Al</th><th scope="col">Motivo (pubblico)</th><th scope="col"><span className="visually-hidden">Azioni</span></th></tr></thead>
            <tbody>{d.chiusure.map((c, i) => (
              <tr key={i}>
                <td><input type="date" aria-label={`Chiusura ${i + 1}: dal`} className="form-control form-control-sm border" value={c.dal}
                           onChange={(e) => setItem("chiusure", i, "dal", e.target.value)} /></td>
                <td><input type="date" aria-label={`Chiusura ${i + 1}: al`} className="form-control form-control-sm border" value={c.al}
                           onChange={(e) => setItem("chiusure", i, "al", e.target.value)} /></td>
                <td><input aria-label={`Chiusura ${i + 1}: motivo`} className="form-control form-control-sm border" value={c.motivo} maxLength={200}
                           placeholder="es. lavori al tetto" onChange={(e) => setItem("chiusure", i, "motivo", e.target.value)} /></td>
                <td><button type="button" className="btn btn-link btn-sm text-danger" onClick={() => removeItem("chiusure", i)}>Elimina</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
        <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => addItem("chiusure", { dal: "", al: "", motivo: "" })}>
          Aggiungi una chiusura
        </button>
      </fieldset>
      <SaveBar busy={busy} label="Salva gli orari" />
    </form>
  );
}
