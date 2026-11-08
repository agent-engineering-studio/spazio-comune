---
title: Installazione
description: Avviare Spazio Comune con Docker o in locale, eseguire i test e aprire l'istanza demo.
---

# Installazione

## Requisiti

| Modalità | Serve |
|---|---|
| Docker (consigliata) | Docker Engine 24+ con Compose v2 |
| Senza Docker | Python 3.12, `pip` (oppure `uv`) |
| Registrazione video | Playwright (Chromium) e `ffmpeg` |
| Sito di documentazione | `pip install zensical` |

## Con Docker

```bash
git clone <url-del-repository> spazio-comune && cd spazio-comune
cp .env.example .env           # poi personalizzare: vedi "Configurazione (.env)"
docker compose up --build -d
```

Apri **http://localhost:8000**.

| Pagina | Indirizzo | Accesso |
|---|---|---|
| Cittadino | `/` | libero; prenotazione con SPID/CIE (simulato) |
| Le mie prenotazioni | `/mie-prenotazioni` | SPID/CIE (simulato) |
| Ufficio Sport | `/ufficio` | Basic auth `UFFICIO_USER` / `UFFICIO_PASSWORD` |
| Custode (smartphone) | `/custode` | Basic auth utente `custode` / `CUSTODE_PASSWORD` |
| API e documentazione OpenAPI | `/api/docs` | libero |

### Profili e container

Ogni servizio ha un nome di container univoco, così è facile riconoscerlo con `docker ps` e `docker logs`.

| Comando | Container | Porta |
|---|---|---|
| `docker compose up -d` | `spazio-comune-app`, `spazio-comune-inference` | 8000 (inferenza solo interna) |
| `docker compose --profile demo up -d` | + `spazio-comune-demo` | **8001**, con dati fittizi |
| `docker compose --profile llm up -d` | + `spazio-comune-ollama`, `spazio-comune-ollama-pull` | solo interna |
| `docker compose --profile test run --rm test` | `spazio-comune-test` | — |

### Istanza demo con dati fittizi

```bash
docker compose --profile demo up --build -d     # http://localhost:8001
docker compose restart demo                      # riparte da zero
```

L'istanza demo ha un orologio che parte da **lunedì 9 novembre 2026 alle 18:35** (si cambia con `DEMO_ORA`)
e un database popolato con cittadini inventati: metà circa degli slot occupati, riserve per società sportive e
scuole, una prenotazione in attesa di pagamento allo sportello e tre ingressi per la sera, così il custode ha
qualcosa da verificare. Venerdì alle 20 è già preso, per vedere l'assistente proporre gli orari vicini.

!!! tip "Percorso di prova manuale"
    1. Su `:8001` scrivi all'assistente *calcetto venerdì sera alle 20* e scegli un orario proposto.
    2. *Entra con SPID* → *Paga con pagoPA* → *Paga*: ottieni il ticket con il QR.
    3. Apri `/ufficio` (`ufficio.sport` / `cambiami`): la nuova prenotazione compare con il suo IUV.
    4. Apri `/custode` (`custode` / `custode`), inserisci il codice della prenotazione delle 19:00 di oggi
       (lo trovi in `/ufficio`): esito *Valida, ingresso registrato*. Riprova: *QR già utilizzato*.

### Comandi utili

```bash
docker compose ps                         # stato dei container
docker logs -f spazio-comune-app          # log dell'app
docker compose down                       # ferma tutto (i dati restano nel volume "dati")
docker compose down -v                    # ferma e cancella anche i dati
```

## Senza Docker

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt -r inference/requirements.txt pytest
python app/scripts/fetch_bootstrap_italia.py     # solo se manca app/prenota/static/bootstrap-italia

# server di inferenza
(cd inference && uvicorn server:app --port 8080) &

# app
(cd app && INFERENCE_URL=http://127.0.0.1:8080 DB_PATH=./prenota.db \
   uvicorn --factory prenota.main:create_app --port 8000)
```

Istanza demo in locale: `INFERENCE_URL=http://127.0.0.1:8080 python app/scripts/demo.py`.

## Test

```bash
docker compose --profile test run --rm test      # con Docker
pytest                                           # senza Docker: 63 test
```

La suite copre il dominio (doppia prenotazione impossibile, scadenza dell'attesa, pagamento tardivo,
annullamento entro 24 ore, check-in), il web (flusso completo, CSRF, open redirect, accesso al ticket) e
l'inferenza (11 casi di intenti in italiano, FAQ con fonte, redazione dei dati personali, fallback dell'LLM).

## Pubblicare questa documentazione

Il sito è generato con [Zensical](https://zensical.org) da `zensical.toml` e dalla cartella `docs/`.

```bash
pip install zensical
zensical serve -a 127.0.0.1:8002     # anteprima (la 8000 è occupata dall'app)
zensical build                       # genera ./site
```

Su GitHub il workflow `.github/workflows/docs.yml` pubblica il sito a ogni push su `main`.
Per un fork basta attivarlo una volta (**Settings › Pages › Build and deployment › Source: GitHub Actions**)
e aggiornare `site_url` e `repo_url` in `zensical.toml`.
