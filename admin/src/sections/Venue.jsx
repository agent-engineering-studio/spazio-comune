import { useRef, useState } from "react";
import { api } from "../api.js";
import { Field } from "../components.jsx";
import { SaveBar, useDraft, useSubmit } from "../draft.jsx";

// Anteprima dell'header del sito: logo, nome del Comune (titolo) e nome del luogo (sottotitolo).
function HeaderPreview({ logo, municipality, venue }) {
  return (
    <div className="it-header-center-wrapper rounded mb-2" aria-label="Anteprima dell'header del sito">
      <div className="it-header-center-content-wrapper px-3"><div className="it-brand-wrapper"><span className="d-flex align-items-center">
        {logo ? <img className="icon venue-logo" src={logo} alt="" />
          : <svg className="icon" aria-hidden="true"><use href="/static/bootstrap-italia/dist/svg/sprites.svg#it-pa" /></svg>}
        <div className="it-brand-text">
          <div className="it-brand-title">{municipality || "Nome del Comune"}</div>
          <div className="it-brand-tagline">{venue || "Nome del luogo"}</div>
        </div>
      </span></div></div>
    </div>
  );
}

function LogoUpload({ meta, municipality, venue, updateData, handleError }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const upload = async (file) => {
    if (!file) return;
    if (file.size > meta.logo_max_kb * 1024) { handleError(new Error(`Logo: file troppo grande (massimo ${meta.logo_max_kb} KB)`)); return; }
    setBusy(true);
    try { updateData(await api.uploadLogo(file), "Logo salvato: è già nell'header del sito."); }
    catch (e) { handleError(e); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const remove = async () => {
    if (!window.confirm("Eliminare il logo? Nell'header tornerà il simbolo generico della PA.")) return;
    try { updateData(await api.deleteLogo(), "Logo eliminato."); } catch (e) { handleError(e); }
  };
  return (
    <fieldset className="mb-4"><legend className="h5">Intestazione del sito</legend>
      <p className="small">L'header mostra il logo dell'ente, il nome del Comune e il nome del luogo (campi qui sotto).
        Usa lo stemma ufficiale, preferibilmente quadrato e su sfondo trasparente.</p>
      <HeaderPreview logo={meta.logo} municipality={municipality} venue={venue} />
      <div className="d-flex flex-wrap align-items-center gap-2 mt-2">
        <label className="btn btn-outline-primary btn-sm mb-0" htmlFor="logo-file">{busy ? "Caricamento…" : meta.logo ? "Sostituisci il logo" : "Carica il logo"}</label>
        <input ref={input} id="logo-file" type="file" accept="image/png,image/jpeg,image/webp" className="visually-hidden"
               aria-describedby="logo-help" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
        {meta.logo && <button type="button" className="btn btn-link btn-sm text-danger" onClick={remove}>Elimina il logo</button>}
      </div>
      <small id="logo-help" className="form-text">PNG, JPEG o WebP, massimo {meta.logo_max_kb} KB (SVG non ammesso per sicurezza). Il logo si salva subito.</small>
    </fieldset>
  );
}

export default function Venue({ data, meta, save, onChange, updateData, handleError }) {
  const [d, set] = useDraft(data.luogo, onChange);
  const [busy, submit] = useSubmit(save);
  return (
    <form onSubmit={submit(() => d)} noValidate>
      <p>Dati mostrati nell'header, su ticket, causale pagoPA, calendario e informativa privacy.</p>
      <LogoUpload meta={meta} municipality={d.comune} venue={d.nome} updateData={updateData} handleError={handleError} />
      <fieldset className="mb-3"><legend className="h5">Il luogo</legend>
        <Field id="venue-name" label="Nome del luogo (sottotitolo dell'header)" value={d.nome} onChange={(v) => set("nome", v)} required
               help={'Il nome ufficiale, es. Palestra comunale "Giovanni Paolo II".'} />
        <Field id="venue-address" label="Indirizzo del luogo" value={d.indirizzo} onChange={(v) => set("indirizzo", v)} required
               help="Via, civico, CAP, Comune e provincia." />
      </fieldset>
      <fieldset className="mb-3"><legend className="h5">Il Comune (titolare del trattamento ed ente creditore pagoPA)</legend>
        <Field id="municipality-name" label="Denominazione dell'ente (titolo dell'header)" value={d.comune} onChange={(v) => set("comune", v)} required />
        <Field id="municipality-address" label="Sede dell'ente" value={d.comune_indirizzo} onChange={(v) => set("comune_indirizzo", v)} />
        <Field id="municipality-website" label="Sito istituzionale" type="url" value={d.comune_sito} onChange={(v) => set("comune_sito", v)} />
        <Field id="office" label="Ufficio competente" value={d.ufficio} onChange={(v) => set("ufficio", v)} required
               help="Compare nel back-office, nelle FAQ e nei contatti." />
      </fieldset>
      <fieldset className="mb-3"><legend className="h5">Numeri di prenotazione</legend>
        <Field id="code-prefix" label="Prefisso" value={d.prefisso_codice} maxLength={5} required
               onChange={(v) => set("prefisso_codice", v.toUpperCase())}
               help="Da 2 a 5 lettere o cifre (es. GDC-7KQ2-M4XP). Meglio non cambiarlo dopo l'avvio: i numeri già emessi restano col prefisso vecchio." />
      </fieldset>
      <SaveBar busy={busy} />
    </form>
  );
}
