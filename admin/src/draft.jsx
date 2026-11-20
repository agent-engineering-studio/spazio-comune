import { useState } from "react";

// Copia modificabile di una sezione; ogni modifica segnala "non salvato" all'app.
export function useDraft(initial, onChange) {
  const [draft, setDraft] = useState(() => structuredClone(initial));
  const setField = (field, value) => { setDraft((d) => ({ ...d, [field]: value })); onChange(); };
  const replace = (f) => { setDraft(f); onChange(); };
  return [draft, setField, replace];
}

export function SaveBar({ busy, label = "Salva" }) {
  return (
    <div className="save-bar">
      <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Salvataggio…" : label}</button>
    </div>
  );
}

export function useSubmit(save) {
  const [busy, setBusy] = useState(false);
  const submit = (values) => async (e) => {
    e.preventDefault(); setBusy(true);
    try { return await save(typeof values === "function" ? values() : values); } finally { setBusy(false); }
  };
  return [busy, submit];
}
