---
title: Configurazione (.env)
description: Significato, valori ammessi e raccomandazioni per ogni variabile d'ambiente di Spazio Comune.
---

# Configurazione

Tutta la configurazione passa da variabili d'ambiente. Con Docker si scrivono nel file `.env` nella radice del
progetto, che `docker-compose.yml` legge automaticamente:

```bash
cp .env.example .env
```

!!! danger "Prima di andare in produzione"
    Cambia **sempre** `SECRET_KEY`, `UFFICIO_PASSWORD`, `CUSTODE_PASSWORD` e `FEED_TOKEN`, e imposta
    `COOKIE_SECURE=true` dietro HTTPS. Il file `.env` non va mai messo nel repository (è già in `.gitignore`).

Per generare valori casuali robusti:

```bash
openssl rand -hex 32          # SECRET_KEY
openssl rand -base64 18       # password
openssl rand -hex 12          # FEED_TOKEN
```

## Applicazione

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Indirizzo pubblico dell'app, **senza** `/` finale. Serve per il QR del ticket, per il link del calendario iCal e per l'URL di ritorno da pagoPA (i ritorni verso altri domini vengono rifiutati). In produzione: `https://prenota.comune.gioiadelcolle.ba.it`. |
| `SECRET_KEY` | casuale a ogni avvio | Firma i cookie di sessione e i **QR dei ticket** (HMAC). Se manca, ne viene generata una a ogni riavvio: le sessioni si chiudono e **i QR già emessi non sono più validi**. Usa almeno 64 caratteri casuali e non cambiarla una volta in esercizio. |
| `DB_PATH` | `/data/prenota.db` | Percorso del database SQLite. Con Docker è già impostato da `docker-compose.yml` sul volume `dati`, quindi non va messo nel `.env`. |
| `TTL_ATTESA_MIN` | `15` | Minuti per cui uno slot resta riservato mentre il cittadino paga. Scaduto il tempo, lo slot torna libero; un pagamento arrivato dopo conferma comunque la prenotazione se lo slot è ancora libero. |
| `COOKIE_SECURE` | `false` | `true` invia il cookie di sessione solo su HTTPS. **Obbligatorio** in produzione; lascia `false` solo su `http://localhost`. |

## Accessi riservati

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `UFFICIO_USER` | `ufficio.sport` | Utente del back-office `/ufficio` (Basic auth). |
| `UFFICIO_PASSWORD` | `cambiami` | Password del back-office. **Da cambiare.** |
| `CUSTODE_PASSWORD` | `custode` | Password della pagina `/custode`; l'utente è sempre `custode`. **Da cambiare.** |
| `FEED_TOKEN` | casuale a ogni avvio | Token segreto del calendario iCal per Outlook o Thunderbird (`/ufficio/agenda.ics?token=…`). Se manca, cambia a ogni riavvio e il calendario sottoscritto smette di aggiornarsi. Chi conosce il token vede gli orari prenotati, quindi trattalo come una password. |

## Integrazioni

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `PAYMENT_BACKEND` | `mock` | `mock` simula il checkout pagoPA. È l'unico valore supportato dal prototipo: la produzione richiede l'adapter `MyPaySILGateway` con le credenziali SIL di Regione Puglia. |
| `IDENTITY_BACKEND` | `mock` | `mock` simula SPID/CIE con un utente di prova (Mario Rossi). In produzione si collega il gateway SPID/CIE del portale o un proxy OIDC certificato. |
| `INFERENCE_URL` | vuoto | Indirizzo del server di inferenza. Con Docker è già impostato a `http://inference:8080`. **Vuoto = assistente IA disattivato**: il sito mostra solo il calendario. |

## Server di inferenza (IA)

Queste variabili sono lette dal container `spazio-comune-inference`. Dettagli in
[Intelligenza artificiale](intelligenza-artificiale.md#collegare-un-modello-linguistico).

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `INFERENCE_BACKEND` | `rules` | `rules`: motore deterministico in italiano, offline, senza GPU. `openai`: usa un LLM compatibile OpenAI, sempre con il motore a regole come base e come riserva. |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | Endpoint compatibile OpenAI: Ollama del profilo `llm`, vLLM, llama.cpp o Azure OpenAI. |
| `LLM_MODEL` | `qwen2.5:1.5b-instruct` | Nome del modello o del deployment. Con Ollama viene scaricato da `spazio-comune-ollama-pull`. |
| `LLM_API_KEY` | `ollama` | Chiave API, inviata come `Authorization: Bearer`. Per Ollama qualsiasi valore va bene. |
| `LLM_TIMEOUT` | `20` | Secondi di attesa per l'LLM; scaduti, si usa la risposta del motore a regole. |
| `LOG_LEVEL` | `INFO` | Livello di log del server di inferenza. |

## Istanza demo

Lette solo da `app/scripts/demo.py` (servizio `spazio-comune-demo`).

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `DEMO_ORA` | `2026-11-09T18:35:00` | Istante da cui parte l'orologio della demo (ora di Roma). Scegli un giorno da lunedì a sabato prima delle 19 per avere ingressi da verificare. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Interfaccia e porta del server demo. |

## Esempi di `.env`

=== "Sviluppo locale"

    ```bash
    BASE_URL=http://localhost:8000
    SECRET_KEY=dev-solo-locale-0123456789abcdef0123456789abcdef0123456789abcdef
    UFFICIO_USER=ufficio.sport
    UFFICIO_PASSWORD=cambiami
    CUSTODE_PASSWORD=custode
    FEED_TOKEN=dev
    TTL_ATTESA_MIN=15
    PAYMENT_BACKEND=mock
    IDENTITY_BACKEND=mock
    COOKIE_SECURE=false
    INFERENCE_BACKEND=rules
    ```

=== "Pilota (HTTPS, LLM locale)"

    ```bash
    BASE_URL=https://prenota.comune.gioiadelcolle.ba.it
    SECRET_KEY=<openssl rand -hex 32>
    UFFICIO_USER=ufficio.sport
    UFFICIO_PASSWORD=<password robusta>
    CUSTODE_PASSWORD=<password robusta>
    FEED_TOKEN=<openssl rand -hex 12>
    TTL_ATTESA_MIN=15
    PAYMENT_BACKEND=mock          # fino all'attivazione MyPay SIL
    IDENTITY_BACKEND=mock         # fino all'attivazione SPID/CIE
    COOKIE_SECURE=true
    INFERENCE_BACKEND=openai
    LLM_BASE_URL=http://ollama:11434/v1
    LLM_MODEL=qwen2.5:1.5b-instruct
    LLM_API_KEY=ollama
    ```

Dopo una modifica del `.env`, ricrea i container perché la leggano:

```bash
docker compose up -d --force-recreate
```
