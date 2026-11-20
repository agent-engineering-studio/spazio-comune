---
title: Installazione
description: Avviare Spazio Comune con Docker o in locale, eseguire i test e aprire l'istanza demo.
---

# Installazione

## Requisiti

| Modalità | Serve |
|---|---|
| Macchina virtuale, senza Docker (esercizio) | Server Linux con `sudo`: vedi [Su una macchina virtuale](#su-una-macchina-virtuale-senza-docker) |
| Docker | Docker Engine 24+ con Compose v2 |
| Sviluppo senza Docker | Python 3.11+, `pip` (oppure `uv`), PostgreSQL |
| Interfaccia di amministrazione (solo per modificarla) | Node.js 20+ e `npm` |
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

Il database è **PostgreSQL 17** nel container `spazio-comune-db` (volume `pgdati`, solo rete interna), creato
al primo avvio con la password `POSTGRES_PASSWORD` del `.env`. La tabella `slot` riporta per ogni orario il
numero di prenotazione che lo occupa. Dettagli e modello dati in
[Architettura](architettura.md#il-database).

```bash
docker exec -it spazio-comune-db psql -U spazio -d spazio_comune -c \
  "SELECT inizio, stato, codice_prenotazione, cognome FROM v_occupazione WHERE codice_prenotazione IS NOT NULL ORDER BY inizio"
```

```bash
# backup e ripristino
docker exec spazio-comune-db pg_dump -U spazio -Fc spazio_comune > spazio-comune-$(date +%F).dump
docker exec -i spazio-comune-db pg_restore -U spazio -d spazio_comune --clean < spazio-comune-AAAA-MM-GG.dump
```

Con un PostgreSQL gestito basta impostare `DATABASE_URL` nel `.env`: l'app crea da sola tabelle, vincoli e
vista al primo avvio.

### Comandi utili

```bash
docker compose ps                         # stato dei container
docker logs -f spazio-comune-app          # log dell'app
docker compose down                       # ferma tutto (i dati restano nel volume "pgdati")
docker compose down -v                    # ferma e cancella anche i dati
```

## Su una macchina virtuale, senza Docker

Uno script installa tutto sulla macchina: PostgreSQL, Python con le librerie, i servizi di sistema, il backup
notturno e, se si indica un nome a dominio, nginx con HTTPS. Si rilancia identico per aggiornare: dati e
configurazione restano.

### Requisiti minimi del server

| Cosa | Minimo | Consigliato |
|---|---|---|
| Sistema operativo | Debian 12/13, Ubuntu 22.04/24.04 LTS (provati); RHEL, Rocky, Alma Linux 9 | Debian 12 o Ubuntu 24.04 LTS |
| Processore | 1 vCPU | 2 vCPU |
| Memoria | 2 GB | 4 GB (8 GB o più solo con un'IA generativa locale) |
| Disco | 10 GB | 20 GB |
| Rete in uscita | durante installazione e aggiornamenti (pacchetti del sistema, PyPI) | — |
| Rete in entrata | porta 8000 per una prova | 80 e 443 con un nome a dominio |
| Accesso | utente con `sudo` | — |

Non servono Docker né Node.js: l'interfaccia di amministrazione è già compilata nel repository.

### Installazione

```bash
git clone https://github.com/agent-engineering-studio/spazio-comune.git && cd spazio-comune
sudo ./deploy/install.sh                                                   # prova su http://<ip>:8000
sudo ./deploy/install.sh --dominio prenota.comune.esempio.it               # dietro nginx (http)
sudo ./deploy/install.sh --dominio prenota.comune.esempio.it --email-tls ced@comune.esempio.it   # + HTTPS Let's Encrypt
```

Altre opzioni: `--porta N` (porta locale dell'app, predefinita 8000), `--workers N` (processi, predefiniti 2),
`--senza-mcp`. L'aiuto completo si ottiene con `./deploy/install.sh --help`.

Alla fine lo script stampa indirizzi e **credenziali iniziali** di amministratore, ufficio e custode. Il passo
successivo è la [pagina di amministrazione](amministrazione.md).

### Cosa installa e dove

| Cosa | Dove |
|---|---|
| Codice | `/opt/spazio-comune/{app,inference,mcp_server}` (proprietario root, leggibile dal servizio) |
| Ambiente Python | `/opt/spazio-comune/venv` |
| Configurazione con i segreti generati | `/etc/spazio-comune/spazio-comune.env` (permessi 640) |
| Database | PostgreSQL locale, database `spazio_comune`, utente `spazio` con password generata |
| Servizi | `spazio-comune-app` (porta 8000), `spazio-comune-inference` (solo 127.0.0.1:8080), `spazio-comune-mcp` (solo 127.0.0.1:8090) |
| Backup | timer `spazio-comune-backup` alle 02:30, `pg_dump` in `/var/backups/spazio-comune`, conservati 14 giorni |
| Reverse proxy | `/etc/nginx/sites-available/spazio-comune.conf` (o `conf.d` su RHEL), solo con `--dominio` |

I servizi girano con l'utente di sistema `spaziocomune`, senza shell, con le protezioni di systemd
(`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`). Con `--dominio` l'app ascolta solo su 127.0.0.1 e
dall'esterno si passa da nginx.

### Gestione

```bash
systemctl status spazio-comune-app                 # stato
journalctl -u spazio-comune-app -f                 # log
sudo systemctl restart spazio-comune-app           # riavvio (dopo una modifica al file .env)
git pull && sudo ./deploy/install.sh               # aggiornamento
sudo -u postgres pg_restore --clean -d spazio_comune /var/backups/spazio-comune/<file>.dump   # ripristino
```

!!! warning "Backup fuori dal server"
    Il backup notturno resta sulla stessa macchina: copiarlo anche altrove (storage del Comune, backup della VM).

Per togliere tutto: `systemctl disable --now spazio-comune-{app,inference,mcp} spazio-comune-backup.timer`,
poi cancellare `/opt/spazio-comune`, `/etc/spazio-comune` e i file `spazio-comune-*` in `/etc/systemd/system`.
Il database si elimina con `sudo -u postgres dropdb spazio_comune`.

## Sviluppo senza Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt -r inference/requirements.txt -r mcp_server/requirements.txt pytest
python app/scripts/fetch_bootstrap_italia.py     # solo se manca app/venue_booking/static/bootstrap-italia

# un PostgreSQL 17 raggiungibile (anche solo il container: docker compose up -d db, con una porta pubblicata)
export DATABASE_URL=postgresql://spazio:<password>@localhost:5432/spazio_comune

# server di inferenza
(cd inference && uvicorn server:app --port 8080) &

# app
(cd app && INFERENCE_URL=http://127.0.0.1:8080 uvicorn --factory venue_booking.main:create_app --port 8000)
```

Istanza demo in locale: `INFERENCE_URL=http://127.0.0.1:8080 python app/scripts/demo.py` (usa lo schema `demo`).

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

`app/scripts/simulate.py` fa prenotare in parallelo dei cittadini virtuali attraverso il sito vero: SPID
simulato, scelta dello slot, pagamento pagoPA simulato. Metà di loro punta di proposito agli stessi tre orari.
Alla fine lo script controlla sul database, tramite l'API dell'ufficio, che ogni slot occupato porti un solo
numero di prenotazione.

```bash
docker compose --profile demo up -d && docker compose restart demo
python app/scripts/simulate.py --url http://localhost:8001 --cittadini 30
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
