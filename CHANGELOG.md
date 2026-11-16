# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il versionamento [SemVer](https://semver.org/lang/it/).

## [Non rilasciato]

### Sicurezza
- Dipendenze aggiornate: FastAPI 0.162.0, Starlette 1.10.0, python-multipart 0.0.32, uvicorn 0.54.0, pydantic 2.14.1, mcp 1.30.0, sse-starlette 3.6.0. Le versioni precedenti avevano vulnerabilità note segnalate da `pip-audit`.

### Modificato
- `publiccode.yml` allineato allo standard: categorie ammesse, sezione `IT` maiuscola, `codiceIPA` vuoto per il software di terze parti, schermate e pubblico di riferimento.

### Corretto
- Assistente (`/api/v1/assistente`, strumento MCP `cerca_orari`, sito): se il giorno richiesto è tutto impegnato propone gli orari liberi dei giorni successivi, con un messaggio che lo spiega, invece di non proporre nulla.

### Aggiunto
- Orari con più intervalli al giorno (`SPAZIO_ORARIO=9-13,14-22`), orari per periodo dell'anno (`SPAZIO_ORARIO_PERIODI`) e chiusura fino alle 24.
- Giorni festivi nazionali calcolati in automatico, chiusi per impostazione predefinita (`SPAZIO_FESTIVI`), e festività locali (`SPAZIO_FESTIVI_EXTRA`). Il calendario indica i giorni festivi con `festivo`.
- Porte sull'host configurabili dal `.env`: `APP_PORT`, `MCP_PORT`, `DEMO_PORT`.
- Guida al riuso e alla pubblicazione nel Catalogo Developers Italia (`docs/riuso.md`).
- `CONTRIBUTING.md`, `SECURITY.md`, questo changelog.
- Test di validità di `publiccode.yml`.

## [0.1.0] – 2026-11-08

Prima versione: prenotazione a slot con SPID/CIE e pagoPA simulati, QR per il custode, back-office, server di inferenza, server MCP, PostgreSQL, Docker Compose.
