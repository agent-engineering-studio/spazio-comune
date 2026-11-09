# Riuso e Catalogo Developers Italia

Come pubblicare Spazio Comune nel Catalogo del software della PA e come un altro Comune può adottarlo. Le indicazioni seguono le fonti istituzionali consultate il 9 novembre 2026, elencate in fondo.

## Due percorsi di pubblicazione

**Oggi: software open source di terze parti.** Il codice non è di proprietà di una PA, quindi entra nel Catalogo come software di interesse pubblico sviluppato da terzi. La guida "Pubblicare software per la PA" di Developers Italia (passo 8, aggiornata il 30 settembre 2026) chiede due cose: il file `publiccode.yml` nel repository con il campo `codiceIPA` vuoto, e una segnalazione sul repository GitHub del Catalogo con il modello "add new software". Il Regolamento del Catalogo descrive anche una pull request sulla lista `thirdparty.yml`: in caso di dubbio vale la guida, più recente.

**Domani: software a riuso.** Se un Comune adotta Spazio Comune e ne diventa titolare (art. 69 CAD), lo dichiara con l'onboarding di Developers Italia registrando il proprio spazio di code hosting. A quel punto `codiceIPA` riporta il codice IPA dell'ente (per Gioia del Colle `c_e038`) e gli enti che lo usano compaiono in `usedBy`.

## Checklist di pubblicazione

- [x] Repository pubblico: `github.com/agent-engineering-studio/spazio-comune`
- [x] Licenza EUPL-1.2, raccomandata dalla guida per la PA
- [x] README, documentazione tecnica e istruzioni di installazione
- [x] `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`
- [x] Dipendenze senza vulnerabilità note (`pip-audit`); analisi statica `bandit` con due soli falsi positivi documentati in `SECURITY.md`
- [x] `publiccode.yml` con categorie ammesse dallo standard e `codiceIPA` vuoto, verificato dal test `app/tests/test_publiccode.py`
- [ ] Verifica finale con l'editor/validatore ufficiale
- [ ] Segnalazione sul repository `italia/catalogo-software` con il modello "add new software"
- [ ] Licenza dei metadati: la guida consiglia CC0 o CC BY 4.0 per descrizioni e documentazione

## Come un Comune adotta Spazio Comune

**Valutazione comparativa (art. 68 CAD).** Prima di acquisire software l'ente confronta le soluzioni disponibili, privilegiando quelle open source e già a catalogo. Una ricerca nel Catalogo del 9 novembre 2026 non ha restituito risultati per "impianti sportivi" e "palestre". Esistono soluzioni generali di prenotazione appuntamenti per i Comuni, come OpenCity Italia – La Stanza del Cittadino e Città Facile, e Partecipo per la prenotazione di eventi. La relazione dell'ente dovrebbe spiegare perché servono la prenotazione a slot con pagamento contestuale e il controllo accessi del custode, oppure valutare di integrare queste funzioni in una piattaforma già adottata.

**Configurazione.** Ogni installazione gestisce un solo luogo: nome, indirizzo, Comune, ufficio, giorni, orari e attività si impostano nel file `.env` (vedi [Configurazione](configurazione.md)). Un Comune con più luoghi installa una copia per ciascuno.

**Componenti di produzione già a catalogo.** Per l'identità digitale c'è `pa-sso-proxy` (SPID, CIE, eIDAS). Per pagoPA si usa l'intermediario tecnologico dell'ente (MyPay per i Comuni pugliesi, ad esempio) oppure GovPay.

**Ospitalità.** I dati delle prenotazioni sono dati ordinari della PA: secondo il Regolamento ACN per il cloud della PA (D.D. 21007/24, in vigore dal 1° agosto 2024) vanno ospitati su infrastrutture o servizi cloud qualificati, compreso il PostgreSQL. Se un fornitore offre Spazio Comune come servizio SaaS, quel servizio deve essere qualificato ACN.

**Prima dell'avvio.** Aggiornare il registro dei trattamenti con il RPD, nominare il fornitore responsabile del trattamento (art. 28 GDPR), pubblicare la dichiarazione di accessibilità e, se si attiva un modello linguistico, fare la valutazione d'impatto prevista dalle Linee guida AgID per l'IA nella PA. Dettagli in [Installazione conforme PA](normativa-it.md).

## Fonti istituzionali

- [Developers Italia – Pubblicare software per la PA](https://developers.italia.it/it/guide/pubblicare-software-per-la-pa)
- [Developers Italia – Regolamento del Catalogo software](https://docs.italia.it/italia/developers-italia/policy-inserimento-catalogo-docs/it/stabile/catalogo-di-developers-italia.html)
- [Developers Italia – Catalogo del software](https://catalogo-software.developers.italia.it/)
- [Developers Italia – Onboarding delle amministrazioni](https://onboarding.developers.italia.it/)
- [Editor e validatore publiccode.yml](https://publiccode-editor.developers.italia.it/)
- [AgID – Linee guida su acquisizione e riuso di software per la PA](https://www.agid.gov.it/it/design-servizi/riuso-open-source/linee-guida-acquisizione-riuso-software-pa)
- [Agenda Digitale – Regolamento ACN cloud per i piccoli Comuni](https://www.agendadigitale.eu/cittadinanza-digitale/passaggio-al-cloud-dei-piccoli-comuni-cosa-dice-il-nuovo-regolamento-acn/)
