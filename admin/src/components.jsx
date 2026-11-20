// Campi di modulo con le classi di Bootstrap Italia, etichette e aiuti collegati per l'accessibilità.
export function Field({ id, label, value, onChange, help, type = "text", required, ...rest }) {
  return (
    <div className="mb-3">
      <label htmlFor={id} className="form-label fw-semibold">
        {label}{required && <span aria-hidden="true"> *</span>}
      </label>
      <input id={id} type={type} className="form-control border" value={value ?? ""} required={required}
             aria-describedby={help ? `${id}-help` : undefined} onChange={(e) => onChange(e.target.value)} {...rest} />
      {help && <small id={`${id}-help`} className="form-text">{help}</small>}
    </div>
  );
}

export function SecretField({ id, label, isSet, value, onChange, clear, onClear, unreadable, help }) {
  return (
    <div className="mb-3">
      <label htmlFor={id} className="form-label fw-semibold">{label}</label>
      <input id={id} type="password" className="form-control border" autoComplete="new-password" value={value ?? ""}
             placeholder={isSet ? "impostato: lascia vuoto per non cambiarlo" : "non impostato"}
             aria-describedby={`${id}-help`} onChange={(e) => onChange(e.target.value)} disabled={clear} />
      <small id={`${id}-help`} className="form-text">
        {unreadable && <strong className="text-danger">Il valore salvato non è più leggibile (SECRET_KEY cambiata): reinseriscilo. </strong>}
        {help} Il valore è cifrato nel database e non torna mai al browser.
      </small>
      {isSet && (
        <div className="form-check mt-1">
          <input className="form-check-input" type="checkbox" id={`${id}-clear`} checked={!!clear}
                 onChange={(e) => onClear(e.target.checked)} />
          <label className="form-check-label small" htmlFor={`${id}-clear`}>Cancella il valore salvato</label>
        </div>
      )}
    </div>
  );
}

export function RadioGroup({ name, options, value, onChange, legend }) {
  return (
    <fieldset className="mb-3">
      <legend className="h6">{legend}</legend>
      {Object.entries(options).map(([code, text]) => (
        <div className="form-check" key={code}>
          <input className="form-check-input" type="radio" name={name} id={`${name}-${code}`} value={code}
                 checked={value === code} onChange={() => onChange(code)} />
          <label className="form-check-label" htmlFor={`${name}-${code}`}>{text}</label>
        </div>
      ))}
    </fieldset>
  );
}

export function WeekTable({ idPrefix, values, onChange, meta, caption }) {
  return (
    <table className="table table-sm align-middle time-slots">
      <caption className="small">{caption}</caption>
      <thead><tr><th scope="col" className="weekday-col">Giorno</th><th scope="col">Fasce orarie prenotabili</th></tr></thead>
      <tbody>
        {meta.giorni.map((day, i) => (
          <tr key={day}>
            <th scope="row"><label htmlFor={`${idPrefix}${day}`} className="mb-0 text-capitalize">{meta.giorni_lunghi[i]}</label></th>
            <td><input id={`${idPrefix}${day}`} className="form-control form-control-sm border" placeholder="chiuso"
                       value={values?.[day] ?? ""} onChange={(e) => onChange({ ...values, [day]: e.target.value })} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Alert({ type = "info", title, children, role }) {
  return (
    <div className={`alert alert-${type}`} role={role || (type === "danger" ? "alert" : "status")}>
      {title && <strong>{title} </strong>}{children}
    </div>
  );
}

export const formatDateTime = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "");
export const formatShortDate = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)} ${iso.slice(11, 16)}` : "");
