---
title: Configurazione (.env)
description: Significato, valori ammessi e raccomandazioni per ogni variabile d'ambiente di Spazio Comune.
---

# Configurazione

Tutta la configurazione sta in variabili d'ambiente, scritte nel file `.env` nella radice del progetto e lette
in automatico da `docker-compose.yml`. Il modello **`.env.example`** è commentato riga per riga: i valori
funzionano subito in locale, e sopra ogni variabile la riga `PRODUZIONE:` dice cosa mettere quando il Comune
mette in esercizio il servizio.

```bash
cp .env.example .env && chmod 600 .env
```

!!! info "Un'installazione, un luogo"
    Le variabili `SPAZIO_*` e `COMUNE_*` descrivono **l'unico luogo** gestito da questa installazione.
    Un Comune con più luoghi installa una copia del repository per ciascuno, ognuna con il suo `.env`,
    il suo indirizzo web e il suo database.

!!! danger "Prima di andare in produzione"
    Cambia **sempre** `SECRET_KEY`, `UFFICIO_PASSWORD`, `CUSTODE_PASSWORD` e `FEED_TOKEN`, e imposta
    `COOKIE_SECURE=true` dietro HTTPS. Il file `.env` non va mai nel repository (è già in `.gitignore`);
    in esercizio i segreti stanno meglio nel vault o nei *secret* della piattaforma.

Per generare valori casuali robusti:

```bash
openssl rand -hex 32          # SECRET_KEY
openssl rand -base64 24       # password
openssl rand -hex 24          # FEED_TOKEN
```

## Il luogo

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `SPAZIO_NOME` | Campo comunale coperto di via Benagiano | nome ufficiale del luogo | Titolo del sito, ticket, causale pagoPA, calendario. |
| `SPAZIO_INDIRIZZO` | Via Benagiano, 70023 Gioia del Colle (BA) | indirizzo completo | Pagine, ticket, campo *luogo* degli eventi iCal. |
| `SPAZIO_ATTIVITA` | `calcetto,tennis_singolo,tennis_doppio` | attività ammesse dall'atto dell'ufficio | Sottoinsieme delle attività definite in `app/prenota/catalog.py`, dove si aggiungono attività nuove con la loro tariffa. Un valore sconosciuto blocca l'avvio con un messaggio chiaro. |
| `SPAZIO_GIORNI` | `lun,mar,mer,gio,ven,sab` | calendario dell'ufficio | Giorni di apertura (`lun` … `dom`). |
| `SPAZIO_ORARIO` | `15-22` | fascia dell'ufficio | Apertura e chiusura in ore intere: con slot da 60 minuti il primo è alle 15:00, l'ultimo alle 21:00. Chiusure straordinarie: *Riserva uno slot* in `/ufficio`. |
| `SPAZIO_DURATA_MIN` | `60` | `60` | Durata di uno slot. |
| `SPAZIO_PREAVVISO_GIORNI` | `14` | `14` | Quanti giorni in anticipo si può prenotare. |
| `CODICE_PREFISSO` | `GDC` | sigla del Comune o del luogo | Prefisso dei numeri di prenotazione (`GDC-7KQ2-M4XP`); non va cambiato dopo l'avvio. |

## Il Comune

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `COMUNE_NOME` | Comune di Gioia del Colle | denominazione dell'ente | Intestazione, informativa privacy (titolare), ente creditore pagoPA. |
| `COMUNE_INDIRIZZO` | Piazza Margherita di Savoia, 10 … | sede municipale | Piè di pagina e informativa. |
| `COMUNE_SITO` | https://www.comune.gioiadelcolle.ba.it/ | sito istituzionale | Link nell'intestazione e nel percorso di navigazione. |
| `UFFICIO_NOME` | Ufficio Cultura, Istruzione e Sport | ufficio competente | Back-office, FAQ, messaggi di contatto. |
| `FONTE_TARIFFE` | D.G.C. n. 37/2025 … | delibera in vigore | Citata accanto ai prezzi e nelle risposte dell'assistente. |

## Applicazione

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `BASE_URL` | `http://localhost:8000` | `https://prenota.comune.<nome>.<pr>.it` | Indirizzo pubblico, **senza** `/` finale. Serve per il QR del ticket, il link del calendario iCal e l'URL di ritorno da pagoPA (i ritorni verso altri domini vengono rifiutati). |
| `SECRET_KEY` | casuale a ogni avvio | `openssl rand -hex 32`, **fissa** | Firma i cookie di sessione e i **QR dei ticket** (HMAC). Se cambia, le sessioni si chiudono e **i QR già emessi non sono più validi**. |
| `DB_PATH` | `/data/prenota.db` | invariato | File del database SQLite nel volume `dati`. Già impostato da `docker-compose.yml`, non va messo nel `.env`. |
| `TTL_ATTESA_MIN` | `15` | `15` | Minuti per cui uno slot resta riservato mentre il cittadino paga; poi torna libero. Un pagamento tardivo conferma comunque la prenotazione se lo slot è ancora libero. |
| `COOKIE_SECURE` | `false` | **`true`** | Cookie di sessione solo su HTTPS. `false` solo su `http://localhost`. |

## Accessi riservati

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `UFFICIO_USER` | `ufficio.sport` | utente nominativo | Utente del back-office `/ufficio` e delle API `/api/v1/ufficio/*` (Basic auth). |
| `UFFICIO_PASSWORD` | `cambiami` | `openssl rand -base64 24` | Password del back-office. |
| `CUSTODE_PASSWORD` | `custode` | `openssl rand -base64 18` | Password della pagina `/custode`; l'utente è sempre `custode`. |
| `FEED_TOKEN` | casuale a ogni avvio | `openssl rand -hex 24`, **fisso** | Token del calendario iCal (`/ufficio/agenda.ics?token=…`). Se cambia, il calendario sottoscritto smette di aggiornarsi. Chi lo conosce vede gli orari prenotati: va trattato come una password. |

## Integrazioni

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `PAYMENT_BACKEND` | `mock` | `mock` fino all'integrazione MyPay SIL | Simula il checkout pagoPA. La produzione richiede l'adapter `MyPaySILGateway` con le credenziali SIL di Regione Puglia. |
| `IDENTITY_BACKEND` | `mock` | `mock` fino all'integrazione SPID/CIE | Simula SPID/CIE con un utente di prova (Mario Rossi). In produzione si collega il gateway SPID/CIE del portale o un proxy OIDC certificato. |
| `INFERENCE_URL` | `http://inference:8080` (da compose) | invariato | Indirizzo del server di inferenza. **Vuoto = assistente IA disattivato**: il sito mostra solo il calendario. |

## Server di inferenza (IA)

Queste variabili sono lette dal container `spazio-comune-inference`. Dettagli in
[Intelligenza artificiale](intelligenza-artificiale.md#collegare-un-modello-linguistico).

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `INFERENCE_BACKEND` | `rules` | `rules`; `openai` solo dopo la valutazione d'impatto | `rules`: motore deterministico in italiano, offline, senza GPU. `openai`: LLM compatibile OpenAI, sempre con il motore a regole come base e come riserva. |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | LLM interno o fornitore qualificato ACN | Endpoint compatibile OpenAI: Ollama del profilo `llm`, vLLM, llama.cpp o Azure OpenAI. |
| `LLM_MODEL` | `qwen2.5:1.5b-instruct` | modello o deployment scelto | Con Ollama viene scaricato da `spazio-comune-ollama-pull`. |
| `LLM_API_KEY` | `ollama` | chiave dal vault | Inviata come `Authorization: Bearer`. Per Ollama qualsiasi valore va bene. |
| `LLM_TIMEOUT` | `20` | `20` | Secondi di attesa per l'LLM; scaduti, si usa la risposta del motore a regole. |
| `LOG_LEVEL` | `INFO` | `INFO` | Livello di log del server di inferenza. |

## Server MCP

Lette dal container `spazio-comune-mcp`. Dettagli in [Server MCP](mcp.md).

| Variabile | Sviluppo (predefinito) | Produzione | Descrizione |
|---|---|---|---|
| `MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*` | + host del reverse proxy, se esposto | Header `Host` ammessi: protezione da DNS rebinding. La porta 8090 è pubblicata solo su `127.0.0.1`. |
| `MCP_UFFICIO_USER` / `MCP_UFFICIO_PASSWORD` | vuote | vuote, o un utente dedicato | Abilitano gli strumenti dell'ufficio con i numeri di prenotazione (`occupazione_slot`, `dettaglio_prenotazione`). Vuote = strumenti spenti. |

## Istanza demo

Lette solo da `app/scripts/demo.py` (servizio `spazio-comune-demo`).

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `DEMO_ORA` | `2026-11-09T18:35:00` | Istante da cui parte l'orologio della demo (ora di Roma). Scegli un giorno da lunedì a sabato prima delle 19 per avere ingressi da verificare. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Interfaccia e porta del server demo. |

## Esempio di `.env` di produzione

Il file `.env.example` contiene già tutti i commenti; questo è il risultato per un luogo inventato, con i
segreti al posto giusto.

```bash
SPAZIO_NOME=Palestra comunale Giovanni Paolo II
SPAZIO_INDIRIZZO=Via Roma 10, 70100 Esempio (BA)
SPAZIO_ATTIVITA=calcetto
SPAZIO_GIORNI=lun,mar,mer,gio,ven
SPAZIO_ORARIO=16-23
CODICE_PREFISSO=ESP
COMUNE_NOME=Comune di Esempio
COMUNE_INDIRIZZO=Piazza Municipio 1, 70100 Esempio (BA)
COMUNE_SITO=https://www.comune.esempio.ba.it/
UFFICIO_NOME=Ufficio Sport
FONTE_TARIFFE=D.G.C. n. 12/2026

BASE_URL=https://prenota-palestra.comune.esempio.ba.it
SECRET_KEY=<openssl rand -hex 32>
UFFICIO_USER=m.rossi.sport
UFFICIO_PASSWORD=<openssl rand -base64 24>
CUSTODE_PASSWORD=<openssl rand -base64 18>
FEED_TOKEN=<openssl rand -hex 24>
TTL_ATTESA_MIN=15
COOKIE_SECURE=true
PAYMENT_BACKEND=mock
IDENTITY_BACKEND=mock

INFERENCE_BACKEND=rules
MCP_ALLOWED_HOSTS=localhost:*,127.0.0.1:*
MCP_UFFICIO_USER=
MCP_UFFICIO_PASSWORD=
```

Dopo una modifica del `.env`, ricrea i container perché la leggano:

```bash
docker compose up -d --force-recreate
```
