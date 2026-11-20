# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il versionamento [SemVer](https://semver.org/lang/it/).

## [Non rilasciato]

### Sicurezza
- Dipendenze aggiornate: FastAPI 0.162.0, Starlette 1.10.0, python-multipart 0.0.32, uvicorn 0.54.0, pydantic 2.14.1, mcp 1.30.0, sse-starlette 3.6.0. Le versioni precedenti avevano vulnerabilità note segnalate da `pip-audit`.

### Modificato
- Tutti gli indirizzi in inglese: pagine (`/book`, `/booking/{code}`, `/my-bookings`, `/checkin`, `/backoffice`, `/admin`, `/payment/result/{code}`, `/pagopa-mock/{iuv}`, `/auth/mock`, `/auth/oidc/start`), API (`/api/v1/venue`, `/availability`, `/assistant`, `/faq`, `/backoffice/occupancy`, `/backoffice/bookings/{code}`), parametri e campi dei moduli (`from`, `days`, `activity`, `start`, `text`, `question`, `return_url`…) e tool MCP (`venue_info`, `availability`, `search_slots`, `ask`, `booking_link`, `slot_occupancy`, `booking_detail`). Nessun rimando dai vecchi indirizzi: il servizio non è ancora in esercizio.
- Calendario a colori pieni: verde libero, rosso occupato, grigio passato, giallo in pagamento, grigio-blu riservato; lo stato resta leggibile dai lettori di schermo.
- Screenshot (nomi in inglese) e video della demo rigenerati con la nuova interfaccia, galleria nel README.
- Identificatori del codice in inglese in tutto il repository (pacchetto `app/venue_booking`); variabili del `.env`, URL e campi JSON delle API, tool MCP, opzioni da riga di comando e tabelle del database restano invariati.
- `publiccode.yml` allineato allo standard: categorie ammesse, sezione `IT` maiuscola, `codiceIPA` vuoto per il software di terze parti, schermate e pubblico di riferimento.

### Corretto
- Assistente (`/api/v1/assistente`, strumento MCP `cerca_orari`, sito): se il giorno richiesto è tutto impegnato propone gli orari liberi dei giorni successivi, con un messaggio che lo spiega, invece di non proporre nulla.

### Aggiunto
- **Pagina di amministrazione** `/admin` (indirizzi in inglese; i vecchi `/amministrazione/...` rimandano a `/admin/...`) (React + Vite, compilata e servita dall'app, nessun servizio in più): luogo, Comune e **logo nell'intestazione**; attività, tariffe e fasce tariffarie; **fasce orarie per ogni giorno** secondo il regolamento comunale (anche al minuto), periodi dell'anno con orario settimanale proprio, festivi, **chiusure straordinarie**; pagoPA (MyPay SIL); stato dell'accesso SPID/CIE; password di amministratore, ufficio e custode; registro delle modifiche. Le modifiche valgono subito, anche su più processi o server.
- **Fasce tariffarie** dal back-office: tariffa diversa per gli slot che iniziano in una fascia oraria (es. serale con illuminazione), anche solo in alcuni giorni; l'importo del dovuto pagoPA, il calendario, il riepilogo, `/api/v1/spazio` e le FAQ dell'assistente usano la tariffa della fascia.
- Accesso SPID/CIE tramite gateway OpenID Connect (authorization code con PKCE, `state`, `nonce`), configurato **nel `.env`** (`IDENTITY_BACKEND=oidc`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, …) con controllo all'avvio; in amministrazione la sezione è in sola lettura con la verifica del gateway. Con il gateway attivo l'accesso simulato non esiste più.
- Segreti salvati cifrati nel database (Fernet, chiave derivata da `SECRET_KEY`), password del personale come hash scrypt, limite ai tentativi di accesso all'amministrazione.
- `ADMIN_USER` / `ADMIN_PASSWORD` nel `.env` per il primo accesso all'amministrazione.
- **Installazione su macchina virtuale senza Docker**: `deploy/install.sh` (Debian, Ubuntu, RHEL/Rocky/Alma) con PostgreSQL, servizi systemd protetti, backup notturno, nginx e HTTPS facoltativi; idempotente per gli aggiornamenti.
- Le prenotazioni rimaste fuori da un nuovo orario sono segnalate in amministrazione e in `/ufficio`.
- Orari con più intervalli al giorno (`SPAZIO_ORARIO=9-13,14-22`), orari per periodo dell'anno (`SPAZIO_ORARIO_PERIODI`) e chiusura fino alle 24.
- Giorni festivi nazionali calcolati in automatico, chiusi per impostazione predefinita (`SPAZIO_FESTIVI`), e festività locali (`SPAZIO_FESTIVI_EXTRA`). Il calendario indica i giorni festivi con `festivo`.
- Porte sull'host configurabili dal `.env`: `APP_PORT`, `MCP_PORT`, `DEMO_PORT`.
- Guida al riuso e alla pubblicazione nel Catalogo Developers Italia (`docs/riuso.md`).
- `CONTRIBUTING.md`, `SECURITY.md`, questo changelog.
- Test di validità di `publiccode.yml`.

## [0.1.0] – 2026-11-08

Prima versione: prenotazione a slot con SPID/CIE e pagoPA simulati, QR per il custode, back-office, server di inferenza, server MCP, PostgreSQL, Docker Compose.
