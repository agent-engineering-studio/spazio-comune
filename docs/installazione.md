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
cp .env.example .env           # luogo, Comune, segreti: vedi "Configurazione (.env)"
docker compose up --build -d
```

Apri **http://localhost:8000**.

| Pagina | Indirizzo | Accesso |
|---|---|---|
| Cittadino | `/` | libero; prenotazione con SPID/CIE (simulato) |
| Le mie prenotazioni | `/mie-prenotazioni` | SPID/CIE (simulato) |
| Ufficio Sport | `/ufficio` | Basic auth `UFFICIO_USER` / `UFFICIO_PASSWORD` |
| Custode (smartphone) | `/custode` | Basic auth utente `custode` / `CUSTODE_PASSWORD` |
| API e documentazione OpenAPI | `/api/docs` | libero; `/api/v1/ufficio/*` con le credenziali dell'ufficio |
| Server MCP | `http://localhost:8090/mcp` | solo dalla macchina locale, vedi [Server MCP](mcp.md) |

### Profili e container

Ogni servizio ha un nome di container univoco, così è facile riconoscerlo con `docker ps` e `docker logs`.

| Comando | Container | Porta |
|---|---|---|
| `docker compose up -d` | `spazio-comune-app`, `spazio-comune-inference`, `spazio-comune-mcp` | 8000, 127.0.0.1:8090 (inferenza solo interna) |
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

### Un luogo per installazione

Ogni installazione gestisce un solo luogo, descritto nel `.env`. Per un secondo luogo dello stesso Comune si
clona il repository in un'altra cartella, con il suo `.env`. Si cambia anche la porta pubblicata, oppure lo si
mette dietro un altro nome host del reverse proxy:

```bash
git clone https://github.com/agent-engineering-studio/spazio-comune palestra-roma && cd palestra-roma
cp .env.example .env    # SPAZIO_NOME, SPAZIO_INDIRIZZO, CODICE_PREFISSO, BASE_URL…
docker compose -p palestra-roma up -d
```

I nomi dei container sono fissi (`spazio-comune-*`), quindi due copie sulla stessa macchina vanno avviate su
host diversi, oppure si cambia `container_name` nel `docker-compose.yml` della copia.

### Il database

Il database è **SQLite**: un file `/data/prenota.db` nel volume `dati`, scritto solo dall'app. La tabella
`slot` riporta per ogni orario il numero di prenotazione che lo occupa. Dettagli e modello dati in
[Architettura](architettura.md#il-database).

```bash
docker exec spazio-comune-app python -c "import sqlite3; [print(*r) for r in sqlite3.connect('/data/prenota.db').execute(
  \"SELECT inizio, stato, codice_prenotazione, cognome FROM v_occupazione WHERE codice_prenotazione IS NOT NULL\")]"
```

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
pip install -r app/requirements.txt -r inference/requirements.txt -r mcp_server/requirements.txt pytest
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
pytest                                           # senza Docker: 84 test
```

La suite copre:

- il dominio: doppia prenotazione impossibile, scadenza dell'attesa, pagamento tardivo, annullamento entro 24 ore, check-in;
- il luogo da `.env` e la tabella `slot`: numero di prenotazione registrato, liberato e ripreso, 40 prenotazioni simultanee sullo stesso slot, migrazione dalla prima versione;
- il web: flusso completo, CSRF, open redirect, accesso al ticket, slot impegnati visibili, griglia dell'ufficio;
- l'inferenza: 11 casi di intenti in italiano, FAQ con fonte, redazione dei dati personali, fallback dell'LLM;
- il server MCP: tutti gli strumenti contro l'app reale, tramite il protocollo MCP.

## Simulazione

`app/scripts/simula.py` fa prenotare in parallelo dei cittadini virtuali attraverso il sito vero: SPID
simulato, scelta dello slot, pagamento pagoPA simulato. Metà di loro punta di proposito agli stessi tre orari.
Alla fine lo script controlla sul database, tramite l'API dell'ufficio, che ogni slot occupato porti un solo
numero di prenotazione.

```bash
docker compose --profile demo up -d && docker compose restart demo
python app/scripts/simula.py --url http://localhost:8001 --cittadini 30
```

```text
30 cittadini, 17 slot liberi, 3 slot contesi da metà dei cittadini

Prenotazioni confermate: 10   rifiutate (slot già preso): 20

Slot contesi: chi ha vinto
  slot                       richieste  numero di prenotazione registrato
  2026-11-13T15:00:00+01:00          6  GDC-MWX5-RLU6  (1 confermata)
  2026-11-11T18:00:00+01:00          5  GDC-EWDX-EC6M  (1 confermata)
  2026-11-12T17:00:00+01:00          7  GDC-CU7C-VB58  (1 confermata)

OK: 10 prenotazioni, ognuna registrata sul proprio slot; nessuno slot venduto due volte.
```

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
