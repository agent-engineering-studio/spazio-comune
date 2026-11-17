# Richiesta di attivazione dei servizi MyPay per gestionali locali (SIL)

**A:** Responsabile dei sistemi informativi / Responsabile per la transizione digitale, Comune di Gioia del Colle
**Da:** Giuseppe Zileni
**Data:** 17 novembre 2026
**Oggetto:** pagamento pagoPA delle prenotazioni del campo coperto di via Benagiano: richiesta a Regione Puglia dell'accesso SIL a MyPay

---

## 1. Cosa si chiede, in breve

Si chiede al Comune di inoltrare a Regione Puglia (gestore tecnico della piattaforma MyPay: InnovaPuglia) la
richiesta di **attivazione dei web service SIL** per l'ente, prima in ambiente di test e poi in produzione,
limitatamente al tipo dovuto degli impianti sportivi.

È l'unico passaggio che il Comune deve avviare in prima persona: le credenziali SIL vengono rilasciate solo
all'ente creditore. Una bozza pronta da inviare è al punto 6.

## 2. Perché serve

Oggi chi prenota il campo deve pagare **prima** su MyPay con un pagamento spontaneo compilato a mano, scaricare
la ricevuta PDF, caricarla nell'agenda online e portarla stampata al custode. Se l'orario è già occupato ha
pagato per niente e serve un rimborso; l'Ufficio Cultura, Istruzione e Sport controlla a vista ogni PDF.

Con l'accesso SIL il sistema di prenotazione crea da solo il dovuto con importo e causale esatti, manda il
cittadino al checkout pagoPA e riceve l'esito:

| | Oggi | Con accesso SIL |
|---|---|---|
| Quando si paga | prima di sapere se l'orario è libero | dopo aver scelto l'orario, riservato per 15 minuti |
| Importo e causale | scritti a mano dal cittadino | generati dal sistema (tariffe D.G.C. 37/2025) |
| Prova del pagamento | PDF caricato e stampato | esito automatico, QR sul telefono |
| Riconciliazione | controllo a vista dei PDF | uno IUV per prenotazione, export CSV per la ragioneria |
| Rimborsi per orario occupato | possibili | non più necessari |

Non cambiano l'intermediario pagoPA, il conto di accredito né il tipo dovuto: si usa ciò che il Comune ha già.

## 3. Cosa chiedere a Regione Puglia

1. Abilitazione dell'ente (codice IPA `c_e038`) ai web service SIL di MyPay
   (`PagamentiTelematiciDovutiPagati`), in **ambiente di test** e, dopo il collaudo, in **produzione**.
2. Per ciascun ambiente: **endpoint** del servizio, **WSDL/XSD** aggiornati e **password SIL** dell'ente.
3. **Codice del tipo dovuto** "Utilizzo impianti sportivi" e conferma che sia abilitato all'invio da SIL.
4. Operazioni necessarie: `paaSILInviaDovuti` (creazione del dovuto e indirizzo del checkout) e
   `paaSILChiediPagati` (esito e ricevuta telematica). Se disponibile, anche `paaSILChiediPagatiConRicevuta`.
5. Eventuali **vincoli di rete**: elenco di indirizzi IP autorizzati, certificati client, VPN.
6. Regole per l'**indirizzo di ritorno** dopo il pagamento (dominio da registrare, formato dei parametri).
7. **Specifiche tecniche** e manuale di integrazione della versione di MyPay in uso, con i dati di test
   (carte e utenti di prova) e la procedura di **collaudo** richiesta prima del passaggio in produzione.
8. Un **referente tecnico** per l'integrazione e i tempi previsti di attivazione.

## 4. Cosa serve dal Comune

- [ ] Invio della richiesta a Regione Puglia da parte del referente pagoPA dell'ente (bozza al punto 6)
- [ ] Nome del **referente dei pagamenti** dell'ente e del referente tecnico da indicare nella richiesta
- [ ] Conferma del tipo dovuto e del capitolo di entrata usati oggi per gli impianti sportivi
- [ ] Indicazione su dove sarà ospitato il servizio (dominio e indirizzo IP di uscita), per i vincoli di rete
- [ ] Consegna delle credenziali SIL attraverso un canale sicuro, non per email in chiaro

## 5. Cosa viene fornito dal progetto

- Il codice è pubblico con licenza EUPL-1.2: <https://github.com/agent-engineering-studio/spazio-comune>
- Il punto di integrazione è già isolato (`app/prenota/adapters/payments.py`, classe `MyPaySILGateway`):
  oggi è uno scheletro e il pagamento è simulato; con endpoint, WSDL e credenziali di test si completa e si
  collauda senza toccare il resto dell'applicazione.
- Dati inviati a MyPay per ogni dovuto: codice fiscale e nominativo del pagatore, email, importo, causale con
  codice della prenotazione, tipo dovuto. Nessun altro dato personale.
- Le credenziali restano nella configurazione del server del Comune e non entrano nel repository.
- Finché l'accesso SIL non è attivo il servizio può partire in forma ridotta: il cittadino prenota online,
  paga su MyPay come oggi e l'ufficio conferma l'incasso con un clic.

## 6. Bozza della richiesta a Regione Puglia

> **Oggetto:** Comune di Gioia del Colle (c_e038): richiesta di abilitazione ai web service SIL di MyPay
>
> Il Comune di Gioia del Colle, ente creditore aderente a pagoPA tramite la piattaforma regionale MyPay,
> intende integrare un proprio sistema di prenotazione degli impianti sportivi comunali con MyPay, per creare
> in automatico i dovuti e riceverne l'esito.
>
> Si chiede pertanto:
>
> 1. l'abilitazione dell'ente ai web service SIL (`PagamentiTelematiciDovutiPagati`) in ambiente di test e,
>    a collaudo concluso, in produzione;
> 2. per ciascun ambiente, endpoint, WSDL/XSD e password SIL dell'ente;
> 3. il codice del tipo dovuto "Utilizzo impianti sportivi" e la sua abilitazione all'invio da SIL;
> 4. l'indicazione di eventuali vincoli di rete (indirizzi IP autorizzati, certificati) e delle regole per
>    l'indirizzo di ritorno dopo il pagamento;
> 5. le specifiche tecniche di integrazione, i dati di test e la procedura di collaudo;
> 6. il nominativo di un referente tecnico e i tempi previsti.
>
> Operazioni che saranno utilizzate: `paaSILInviaDovuti`, `paaSILChiediPagati`.
> Volume stimato: fino a circa 40 pagamenti a settimana, importi da 10 a 40 euro.
>
> Referente dei pagamenti dell'ente: ______________________
> Referente tecnico: ______________________ (email, telefono)
> Indirizzo del servizio: https://______________________ · IP di uscita: ______________________
>
> Distinti saluti
> ______________________

## 7. Note

- I nomi delle operazioni e del servizio sono quelli della documentazione pubblica di MyPay
  (progetto `RegioneDelVeneto/mypay`, riusato da Regione Puglia): vanno confermati sul WSDL che la Regione
  fornirà, perché possono variare con la versione installata.
- Il canale esatto per presentare la richiesta (assistenza MyPay, PEC, portale di ticketing) è noto al
  referente pagoPA dell'ente e non è stato verificato in questo documento.
- Il volume indicato nella bozza deriva dal calendario di esempio del progetto (42 ore prenotabili a
  settimana): va sostituito con il dato reale se disponibile.

Contatto per chiarimenti tecnici: Giuseppe Zileni
