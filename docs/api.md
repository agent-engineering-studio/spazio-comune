---
title: API REST
description: "Riferimento delle API REST di Spazio Comune: pubbliche, dell'ufficio, di amministrazione, pagine web e server di inferenza."
---

# API REST

Base URL: `BASE_URL` (in locale `http://localhost:8000`, demo `http://localhost:8001`). Risposte JSON; gli
errori hanno la forma `{"errore": "messaggio"}` con il codice HTTP appropriato (400, 401, 404, 409).
Documentazione interattiva OpenAPI su **`/api/docs`**, schema su `/openapi.json`.

## API pubbliche (nessuna autenticazione, nessun dato personale)

| Metodo e percorso | Parametri | Risposta |
|---|---|---|
| `GET /api/v1/health` | – | `{"stato":"ok","ia":true,"ora":"…"}`: stato dell'app e dell'assistente |
| `GET /api/v1/venue` | – | il luogo: nome, indirizzo, Comune, ufficio, orario, durata slot, preavviso, attività con `tariffa_cent`, `url` |
| `GET /api/v1/availability` | `from` (AAAA-MM-GG, predefinito oggi), `days` (1-14, predefinito 7) | per giorno: `data`, `liberi`, `festivo`, `slot[]` con `inizio`, `fine`, `ora`, `libero`, `stato` (`libero` · `occupato` · `in_pagamento` · `riservato` · `passato`) |
| `GET /api/v1/assistant` | `text` (max 500 caratteri), es. *calcetto venerdì sera alle 20* | `intento` (attività, data, fascia, ora, `backend`, `generato_da_ia`) e fino a 4 `proposte` con `link_prenotazione`; se il giorno richiesto è pieno le proposte sono nei giorni successivi e `messaggio` lo spiega |
| `GET /api/v1/faq` | `question` (max 500 caratteri) | `risposta`, `fonti`, `trovata`, `backend`, `generato_da_ia` |

## API dell'ufficio (Basic auth `UFFICIO_USER` / `UFFICIO_PASSWORD`)

| Metodo e percorso | Parametri | Risposta |
|---|---|---|
| `GET /api/v1/backoffice/occupancy` | `from`, `days` (1-14) | come `availability`, e per ogni slot anche `codice` (numero di prenotazione), `stato_prenotazione`, `attivita`, `intestatario` |
| `GET /api/v1/backoffice/bookings/{code}` | numero di prenotazione, es. `GDC-7KQ2-M4XP` | `codice`, `attivita`, `inizio`, `fine`, `stato`, `canale`, `importo_cent`, `iuv`, `cognome`, `nome`, `note`, `creata_il` (mai il codice fiscale) |
| `GET /backoffice/export.csv` | `from`, `to` | CSV per la ragioneria (separatore `;`) |
| `GET /backoffice/calendar.ics` | `token` = `FEED_TOKEN` (non Basic auth) | calendario iCal per Outlook, Thunderbird, eAgenda |

??? example "Esempi di chiamata e risposta (istanza demo)"

    ```bash
    curl http://localhost:8001/api/v1/venue
    ```
    ```json
    {"nome": "Campo comunale coperto di via Benagiano", "indirizzo": "Via Benagiano, 70023 Gioia del Colle (BA)",
     "comune": "Comune di Gioia del Colle", "ufficio": "Ufficio Cultura, Istruzione e Sport",
     "orario": "lun, mar, mer, gio, ven, sab, slot da 60 minuti dalle 15:00 alle 21:00",
     "durata_slot_min": 60, "preavviso_giorni": 14, "fonte_tariffe": "D.G.C. n. 37/2025 – …",
     "attivita": [{"codice": "calcetto", "nome": "Calcetto (calcio a 5)", "tariffa_cent": 4000, "giocatori": "fino a 10"}, "…"],
     "url": "http://localhost:8001"}
    ```

    ```bash
    curl "http://localhost:8001/api/v1/availability?from=2026-11-13&days=1"
    ```
    ```json
    [{"data": "2026-11-13", "liberi": 2, "slot": [
      {"inizio": "2026-11-13T19:00:00+01:00", "fine": "2026-11-13T20:00:00+01:00", "ora": "19:00", "libero": true, "stato": "libero"},
      {"inizio": "2026-11-13T20:00:00+01:00", "fine": "2026-11-13T21:00:00+01:00", "ora": "20:00", "libero": false, "stato": "occupato"}]}]
    ```

    ```bash
    curl -G http://localhost:8001/api/v1/assistant --data-urlencode "text=calcetto venerdì sera alle 20"
    ```
    ```json
    {"intento": {"attivita": "calcetto", "data": "2026-11-13", "fascia": "sera", "ora": "20:00", "giocatori": null,
                 "confidenza": 1.0, "backend": "rules", "generato_da_ia": false},
     "proposte": [{"data": "2026-11-13", "ora": "19:00", "inizio": "2026-11-13T19:00:00+01:00", "stato": "libero",
       "link_prenotazione": "http://localhost:8001/book?start=2026-11-13T19%3A00%3A00%2B01%3A00&activity=calcetto"}]}
    ```

    ```bash
    curl -G http://localhost:8001/api/v1/faq --data-urlencode "question=posso annullare?"
    ```
    ```json
    {"risposta": "Puoi annullare online dall'area 'Le mie prenotazioni' fino a 24 ore prima. …",
     "fonti": ["annullamento"], "trovata": true, "backend": "rules", "generato_da_ia": false}
    ```

    ```bash
    curl -u ufficio.sport:cambiami "http://localhost:8001/api/v1/backoffice/occupancy?from=2026-11-13&days=1"
    ```
    ```json
    [{"data": "2026-11-13", "liberi": 2, "slot": [
      {"inizio": "2026-11-13T15:00:00+01:00", "ora": "15:00", "libero": false, "stato": "occupato",
       "codice": "GDC-MWX5-RLU6", "stato_prenotazione": "CONFERMATA", "attivita": "calcetto", "intestatario": "Rossi Mario"}, "…"]}]
    ```

## API di amministrazione (sessione dell'amministratore + header `X-CSRF-Token`)

Usate dall'interfaccia `/admin`. Si entra con `POST /api/v1/admin/login`
(`{"utente", "password"}` → `{"utente", "csrf"}`); dopo 10 tentativi sbagliati l'indirizzo IP aspetta 15 minuti e la
sessione scade dopo 30 minuti di inattività. I segreti non tornano mai indietro: si sa solo se sono impostati.

| Metodo e percorso | Cosa fa |
|---|---|
| `GET /api/v1/admin/settings` | Tutte le sezioni, l'orario in vigore e le prenotazioni rimaste fuori dal nuovo orario |
| `PUT /api/v1/admin/settings/{section}` | Valida e salva `venue`, `activities` (con `fasce_tariffarie`), `schedule`, `payments` o `access`; errore 422 con `{"errore"}`. `identity` è in sola lettura (409): si configura nel `.env` |
| `POST /api/v1/admin/settings/{section}/restore` | Torna ai valori del `.env` |
| `PUT` / `DELETE /api/v1/admin/logo` | Logo dell'ente nell'intestazione (PNG, JPEG o WebP, massimo 512 KB) |
| `POST /api/v1/admin/identity/verify` | Legge la configurazione OpenID del gateway SPID/CIE |
| `GET /api/v1/admin/audit-log` | Chi ha cambiato cosa e quando |

## Pagine web (per persone, non per integrazioni)

| Percorso | Chi | Cosa |
|---|---|---|
| `GET /` · `POST /assistant` · `POST /faq` | cittadino | calendario, assistente IA, domande |
| `GET /book?start=…&activity=…` · `POST /book` | cittadino (SPID/CIE) | riepilogo e conferma, poi pagoPA |
| `GET /payment/result/{code}` | cittadino | ritorno da pagoPA, verifica del pagamento |
| `GET /booking/{code}` · `/calendar.ics` · `POST …/cancel` | intestatario | ticket con QR, evento calendario, annullamento |
| `GET /my-bookings` · `/privacy` · `/auth/login` · `/auth/mock` · `/auth/logout` | cittadino | area personale e accesso |
| `GET /backoffice` · `POST /backoffice/block` · `POST /backoffice/{code}/confirm` · `POST /backoffice/{code}/cancel` | ufficio | back-office, griglia di occupazione, riserve, pagamenti allo sportello |
| `GET /checkin` · `POST /checkin` | custode | verifica QR o numero di prenotazione |
| `GET /admin` | amministratore | impostazioni: luogo e logo, tariffe, orari, pagoPA, SPID/CIE, accessi, registro |
| `GET /auth/oidc/start` · `/auth/oidc/callback` | cittadino | accesso SPID/CIE tramite il gateway OpenID Connect |

## Server di inferenza (solo rete interna Docker, `http://inference:8080`)

| Metodo e percorso | Uso |
|---|---|
| `GET /health` | stato, backend e modello attivo |
| `GET /v1/models` | elenco modelli (formato OpenAI) |
| `POST /v1/tasks/intent` | `{"testo", "oggi"}` → `{attivita, data, fascia, ora, giocatori, confidenza, backend, generato_da_ia}` |
| `POST /v1/tasks/faq` | `{"domanda", "documenti"}` → risposta fondata solo sui documenti, con `fonti` |
| `POST /v1/chat/completions` | compatibilità OpenAI: proxy verso l'LLM con redazione dei dati personali |

Per gli agenti IA c'è anche il [server MCP](mcp.md).
