import { Alert, Field, RadioGroup, SecretField } from "../components.jsx";
import { SaveBar, useDraft, useSubmit } from "../draft.jsx";

export default function Payments({ data, meta, save, onChange }) {
  const current = data.pagamenti;
  const [d, set] = useDraft({ ...current, mypay_password: "", mypay_password_cancella: false }, onChange);
  const [busy, submit] = useSubmit(save);
  return (
    <form onSubmit={submit(() => d)} noValidate autoComplete="off">
      <p>Il cittadino paga con pagoPA subito dopo aver scelto l'orario: il servizio crea il <em>dovuto</em> presso l'intermediario
        tecnologico dell'ente con importo e causale corretti e riceve l'esito. Le tariffe sono in <em>Attività e tariffe</em>.</p>
      {current.backend === "mock" && <Alert type="warning" title="Pagamenti simulati.">Nessun incasso reale: va bene per prove e
        dimostrazioni, non per l'esercizio. Il piè di pagina del sito lo segnala ai cittadini.</Alert>}
      <RadioGroup name="backend" legend="Intermediario pagoPA" options={meta.backend_pagamento} value={d.backend} onChange={(v) => set("backend", v)} />
      <Field id="payment-timeout-min" type="number" label="Minuti per completare il pagamento" value={d.ttl_attesa_min} min={5} max={60}
             onChange={(v) => set("ttl_attesa_min", v)} required
             help="Per questo tempo l'orario resta riservato al cittadino, poi torna libero. Di norma 15." />
      <fieldset className="mb-4"><legend className="h5">MyPay – servizi SIL (Regione Puglia)</legend>
        <p className="small">Credenziali fornite da Regione Puglia per l'integrazione "Sistema Informativo Locale"
          (<code>paaSILInviaDovuti</code>, <code>paaSILChiediPagati</code>). Il tipo dovuto deve esistere nella configurazione MyPay dell'ente.</p>
        <Alert type="info" role="note">Le credenziali si salvano e si conservano cifrate già ora. Il collegamento effettivo a MyPay
          richiede di completare l'adapter <code>MyPaySILGateway</code> con il WSDL fornito dalla Regione: finché non è completato,
          con MyPay selezionato il pagamento online non parte e l'ufficio conferma i pagamenti allo sportello.</Alert>
        <Field id="mypay-endpoint" type="url" label="Endpoint dei servizi SIL" value={d.mypay_endpoint}
               onChange={(v) => set("mypay_endpoint", v)} help="Indirizzo https:// comunicato da Regione Puglia." />
        <Field id="mypay-ipa-code" label="Codice IPA dell'ente" value={d.mypay_ipa_ente} onChange={(v) => set("mypay_ipa_ente", v)} help="Es. c_e038." />
        <Field id="mypay-debt-type" label="Codice tipo dovuto" value={d.mypay_tipo_dovuto} onChange={(v) => set("mypay_tipo_dovuto", v)} help="Es. IMPIANTI_SPORTIVI." />
        <SecretField id="mypay-password" label="Password SIL" isSet={current.mypay_password} value={d.mypay_password}
                     onChange={(v) => set("mypay_password", v)} clear={d.mypay_password_cancella}
                     onClear={(v) => set("mypay_password_cancella", v)} unreadable={data.non_decifrabili.includes("pagamenti.mypay_password")} />
      </fieldset>
      <SaveBar busy={busy} />
    </form>
  );
}
