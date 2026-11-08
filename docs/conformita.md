# Matrice di conformità

Documento tecnico di supporto alla proposta. Da validare con Segretario comunale, RPD e Responsabile per la transizione digitale.

## Identità digitale – CAD art. 64
Accesso con SPID/CIE (simulato nel prototipo). In produzione si delega al gateway già in uso dal portale
eCOMUNE o a un proxy SPID/CIE OpenID Connect; l'app riceve solo CF, nome, cognome, email.

## Pagamenti – CAD art. 5 e Linee guida pagoPA
Il Comune è già su MyPay Regione Puglia (ente C_E038). L'integrazione SIL di MyPay4
(`PagamentiTelematiciDovutiPagati`) consente di creare il dovuto con importo e causale e di leggere l'esito:
scompaiono il pagamento "spontaneo" compilato a mano e il caricamento della ricevuta PDF.
Le tariffe applicate sono quelle della D.G.C. 37/2025, centralizzate in `catalog.py`.

## Design e accessibilità – L. 4/2004, Linee guida AgID, WCAG 2.1 AA
Bootstrap Italia 2.x ospitato in locale con verifica di integrità; skip link, landmark, etichette sui campi,
`aria-live` sui risultati, slot occupati non solo colorati ma barrati e testuali.
Audit automatico axe-core (WCAG 2 A/AA, 2.1 AA): 0 violazioni. Serve comunque un test con utenti e
l'aggiornamento della dichiarazione di accessibilità su form.agid.gov.it.

## Protezione dati – GDPR
Base giuridica art. 6.1.e (compito di interesse pubblico): il modulo attuale chiede un "consenso" che non è la base
corretta e va rimosso. Minimizzazione: telefono facoltativo, CF escluso dall'export CSV. Da predisporre:
registro dei trattamenti, nomina del fornitore come responsabile ex art. 28, tempi di conservazione.

## Intelligenza artificiale – AI Act, L. 132/2025, Linee guida AgID
Uso a basso rischio (assistente informativo, non decisionale). Trasparenza: l'interfaccia dichiara che è IA
(AI Act art. 50). Decisione finale umana: l'IA propone slot, il cittadino sceglie (L. 132/2025).
Tracciabilità: ogni risposta riporta il backend usato. Dati: redazione PII prima di qualsiasi chiamata a modelli
esterni; backend predefinito interamente locale. Prima della messa in esercizio: valutazione d'impatto secondo
le Linee guida AgID e registrazione nel registro dei sistemi IA dell'ente.

## Riuso e open source – CAD artt. 68-69
Licenza EUPL-1.2, `publiccode.yml` per la pubblicazione su Developers Italia.

## Sicurezza
CSRF su tutti i form, cookie di sessione firmati (SameSite=Lax, Secure in produzione), QR firmati HMAC,
protezione open-redirect, container non-root, server di inferenza non esposto all'esterno.
Da aggiungere in produzione: rate limiting, log di audit dell'ufficio, backup, penetration test.
