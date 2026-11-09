# Sicurezza

Se trovi una vulnerabilità non aprire una issue pubblica: usa la segnalazione privata del repository ("Report a vulnerability"), indicando versione, passi per riprodurre e impatto. Riceverai una risposta entro 7 giorni.

Controlli da eseguire a ogni rilascio:

- `pip-audit -r app/requirements.txt -r inference/requirements.txt -r mcp_server/requirements.txt` (vulnerabilità note nelle dipendenze)
- `bandit -r app/prenota inference mcp_server` (analisi statica del codice Python); oggi segnala due B608 su query che interpolano solo la costante degli stati attivi (`booking.py`, `db.py`): falsi positivi, nessun input esterno
- suite `pytest`, che copre CSRF, protezione open-redirect, QR firmati e visibilità delle prenotazioni

Gli enti che installano Spazio Comune restano responsabili di HTTPS, gestione dei segreti (`SECRET_KEY`, credenziali del database e dell'ufficio), backup e conformità al Regolamento ACN per il cloud della PA.
