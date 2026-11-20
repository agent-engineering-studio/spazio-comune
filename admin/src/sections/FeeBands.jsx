// Fasce tariffarie del regolamento: un importo diverso per gli slot che iniziano in una fascia oraria
// (es. "Serale con illuminazione" dalle 19 alle 24), eventualmente solo in alcuni giorni.

export function bandsToDraft(bands, toEuro) {
  return bands.map((b) => ({ ...b, fees: Object.fromEntries(Object.entries(b.tariffe).map(([c, v]) => [c, toEuro(v)])) }));
}

export function bandsFromDraft(bands, toCents) {
  return bands.map(({ fees, ...b }) => ({
    ...b,
    tariffe: Object.fromEntries(Object.entries(fees).filter(([, v]) => String(v).trim() !== "")
      .map(([c, v]) => [c, toCents(v, `${b.nome || "fascia"}, ${c}`)])),
  }));
}

export default function FeeBands({ bands, activities, meta, onChange }) {
  const setBand = (i, field, value) => onChange(bands.map((b, j) => (j === i ? { ...b, [field]: value } : b)));
  const toggleDay = (i, day) => {
    const days = bands[i].giorni.includes(day) ? bands[i].giorni.filter((d) => d !== day) : [...bands[i].giorni, day];
    setBand(i, "giorni", meta.giorni.filter((d) => days.includes(d)));
  };
  const add = () => onChange([...bands, { nome: "", dalle: "", alle: "", giorni: [], fees: {} }]);
  const remove = (i) => onChange(bands.filter((_, j) => j !== i));

  return (
    <fieldset className="mb-4"><legend className="h5">Fasce tariffarie</legend>
      <p className="small">Tariffe diverse secondo l'orario, come previsto dal regolamento (es. tariffa serale con illuminazione
        artificiale). Valgono per gli slot che <strong>iniziano</strong> nella fascia; se più fasce si sovrappongono vale la prima.
        Un'attività senza importo nella fascia mantiene la tariffa base.</p>
      {bands.map((b, i) => (
        <fieldset className="border rounded p-3 mb-3" key={i}>
          <legend className="h6 float-none w-auto px-2 mb-0">{b.nome || "Nuova fascia"}</legend>
          <div className="row g-2">
            <div className="col-md-6">
              <label className="form-label small" htmlFor={`band-${i}-name`}>Nome</label>
              <input id={`band-${i}-name`} className="form-control form-control-sm border" value={b.nome} maxLength={60}
                     placeholder="es. Serale con illuminazione" onChange={(e) => setBand(i, "nome", e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label small" htmlFor={`band-${i}-from`}>Dalle</label>
              <input id={`band-${i}-from`} className="form-control form-control-sm border" value={b.dalle} placeholder="19:00"
                     onChange={(e) => setBand(i, "dalle", e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label small" htmlFor={`band-${i}-to`}>Alle</label>
              <input id={`band-${i}-to`} className="form-control form-control-sm border" value={b.alle} placeholder="24:00"
                     onChange={(e) => setBand(i, "alle", e.target.value)} />
            </div>
          </div>
          <fieldset className="mt-2"><legend className="small fw-semibold mb-1">Giorni (nessuno = tutti)</legend>
            <div className="d-flex flex-wrap gap-3">
              {meta.giorni.map((day, k) => (
                <div className="form-check" key={day}>
                  <input className="form-check-input" type="checkbox" id={`band-${i}-${day}`} checked={b.giorni.includes(day)}
                         onChange={() => toggleDay(i, day)} />
                  <label className="form-check-label text-capitalize" htmlFor={`band-${i}-${day}`}>{meta.giorni_lunghi[k]}</label>
                </div>
              ))}
            </div>
          </fieldset>
          <div className="row g-2 mt-1">
            {activities.map((a) => (
              <div className="col-md-4" key={a.codice}>
                <label className="form-label small" htmlFor={`band-${i}-fee-${a.codice}`}>{a.nome} (€)</label>
                <input id={`band-${i}-fee-${a.codice}`} className="form-control form-control-sm border" inputMode="decimal"
                       placeholder={`base ${a.fee}`} value={b.fees[a.codice] ?? ""}
                       onChange={(e) => setBand(i, "fees", { ...b.fees, [a.codice]: e.target.value })} />
              </div>
            ))}
          </div>
          <button type="button" className="btn btn-link btn-sm text-danger mt-2" onClick={() => remove(i)}>Elimina la fascia</button>
        </fieldset>
      ))}
      <button type="button" className="btn btn-outline-primary btn-sm" onClick={add}>Aggiungi una fascia tariffaria</button>
    </fieldset>
  );
}
