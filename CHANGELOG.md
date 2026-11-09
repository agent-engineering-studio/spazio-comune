# Changelog

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il versionamento [SemVer](https://semver.org/lang/it/).

## [Non rilasciato]

### Sicurezza
- Dipendenze aggiornate: FastAPI 0.162.0, Starlette 1.10.0, python-multipart 0.0.32, uvicorn 0.54.0, pydantic 2.14.1, mcp 1.30.0, sse-starlette 3.6.0. Le versioni precedenti avevano vulnerabilità note segnalate da `pip-audit`.

### Modificato
- `publiccode.yml` allineato allo standard: categorie ammesse, sezione `IT` maiuscola, `codiceIPA` vuoto per il software di terze parti, schermate e pubblico di riferimento.

### Aggiunto
- Guida al riuso e alla pubblicazione nel Catalogo Developers Italia (`docs/riuso.md`).
- `CONTRIBUTING.md`, `SECURITY.md`, questo changelog.
- Test di validità di `publiccode.yml`.

## [0.1.0] – 2026-11-08

Prima versione: prenotazione a slot con SPID/CIE e pagoPA simulati, QR per il custode, back-office, server di inferenza, server MCP, PostgreSQL, Docker Compose.
