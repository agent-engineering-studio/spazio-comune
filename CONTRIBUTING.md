# Contribuire a Spazio Comune

Il progetto accoglie contributi da cittadini, enti e fornitori.

## Come proporre una modifica

1. Apri una issue che descriva il problema o la funzione, con il caso d'uso del tuo ente.
2. Crea un branch dal ramo `main` e mantieni le modifiche piccole e mirate.
3. Aggiungi o aggiorna i test: `docker compose --profile test run --rm test` deve passare (in locale serve `TEST_DATABASE_URL` verso un PostgreSQL).
4. Se tocchi l'interfaccia, usa solo componenti di Bootstrap Italia e verifica l'accessibilità (WCAG 2.1 AA).
5. Aggiorna `CHANGELOG.md` e, se cambia qualcosa per il riuso, `publiccode.yml`.
6. Apri una pull request descrivendo cosa cambia e come l'hai verificato.

## Regole del progetto

- Nessun dato specifico di un Comune nel codice: va nel file `.env` (vedi `docs/configurazione.md`).
- Nessun dato personale reale nei test, nei log, negli esempi o nelle demo.
- L'assistente IA propone, non decide: nessuna funzione IA o strumento MCP può pagare al posto del cittadino.
- Dipendenze nuove solo se necessarie, con versione fissata e senza vulnerabilità note (`pip-audit`).

## Licenza dei contributi

Inviando un contributo accetti che sia distribuito con licenza EUPL-1.2, la stessa del progetto.
