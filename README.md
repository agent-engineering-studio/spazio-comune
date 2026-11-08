# Spazio Comune

**Prenotazione online di un luogo comunale con SPID/CIE, pagoPA, QR code e un assistente IA che trova gli orari
partendo da una frase.** Open source (EUPL-1.2), riusabile da qualsiasi Comune.
Pilota proposto: campo coperto di via Benagiano, Comune di Gioia del Colle.

**Un'installazione = un luogo.** Nome, indirizzo, Comune, orari e attività si scrivono nel file `.env`.
Un Comune con più luoghi installa una copia del repository per ciascuno: ogni luogo ha il suo indirizzo web,
il suo database e il suo ufficio di riferimento, e resta semplice da gestire.

📖 **Documentazione completa:** https://agentengineering.it/spazio-comune/

![Demo](docs/demo/spazio-comune-demo.gif)

> Proposta indipendente, non un servizio ufficiale del Comune. SPID/CIE e pagoPA sono simulati; i dati della demo
> sono fittizi.

Il README è diviso in tre parti: **[Cittadini](#1-per-i-cittadini)** ·
**[Comune](#2-per-il-comune)** · **[Sviluppatori e ufficio IT](#3-per-sviluppatori-e-ufficio-it)**.

---

## 1. Per i cittadini

Oggi per un'ora di calcetto servono **sette passaggi su due portali**, e si paga *prima* di sapere se l'orario è
libero. Con Spazio Comune bastano **quattro passi dal telefono**, e si paga *dopo* aver scelto.

| # | Cosa fai | Cosa succede |
|---|---|---|
| 1 | Scrivi all'**assistente IA** *"calcetto venerdì sera alle 20"*, oppure scegli dal calendario | Ti propone gli orari liberi più vicini; se le 20 sono prese, le 19 o le 21 |
| 2 | Entri con **SPID o CIE** | Nome, cognome e codice fiscale si compilano da soli |
| 3 | Paghi con **pagoPA** | Importo già pronto (calcetto 40 €, tennis 10 € o 20 €); l'orario resta tuo per 15 minuti |
| 4 | Mostri il **QR** al custode | Niente ricevute da stampare; annulli online fino a 24 ore prima |

**L'assistente ti aiuta, ma decidi tu.** È un sistema di intelligenza artificiale, e la pagina lo dichiara.
Propone orari e risponde alle domande su tariffe, pagamento e annullamento citando la fonte ufficiale;
se non sa una risposta lo dice. Non prenota e non paga al posto tuo, e non riceve i tuoi dati personali.

→ [Guida per i cittadini](https://agentengineering.it/spazio-comune/cittadini/) ·
[video verticale](docs/demo/spazio-comune-demo-verticale.mp4)

---

## 2. Per il Comune

| Beneficio | Come |
|---|---|
| **Più entrate** | Ogni ora libera è visibile e vendibile fino all'ultimo; meno rinunce davanti al pagamento anticipato. Stima illustrativa per il solo campo: **14.000–28.000 € l'anno** con occupazione tra il 25 e il 50 %. |
| **Incassi riconciliati** | Ogni prenotazione ha il suo IUV pagoPA (MyPay Regione Puglia): niente controllo a vista dei PDF, niente rimborsi per orari già presi. |
| **L'ufficio non cambia mestiere** | Stesse decisioni su aperture e riserve; una pagina con i prossimi 14 giorni, riserve per scuole e società, pagamenti allo sportello, CSV per la ragioneria, calendario iCal. |
| **Custode digitale** | Verifica QR o codice dal telefono; sa già se montare porte o rete. |
| **IA sotto controllo** | Uso informativo a basso rischio, trasparenza (AI Act art. 50), decisione umana (L. 132/2025), motore offline senza dati a terzi. |
| **Riuso** | Un luogo nuovo = una copia del repository e un `.env` (nome, indirizzo, orari, attività); codice EUPL-1.2 con `publiccode.yml`. |

Piano proposto: dimostrazione → attivazioni tecniche (MyPay SIL, SPID/CIE, cloud qualificato) → **pilota di 8 settimane** →
valutazione ed estensione.

→ [Benefici per il Comune](https://agentengineering.it/spazio-comune/comune/) ·
[Analisi e proposta](docs/ANALISI.md) · [Conformità normativa](docs/conformita.md)

---

## 3. Per sviluppatori e ufficio IT

### Avvio rapido

```bash
cp .env.example .env                              # valori di sviluppo; per la produzione vedi i commenti
docker compose up --build -d                      # app :8000 + IA + server MCP :8090
docker compose --profile demo up --build -d       # + istanza con dati fittizi su http://localhost:8001
docker compose --profile test run --rm test       # 84 test
docker compose --profile llm up --build -d        # + LLM locale con Ollama (opzionale)
```

| Pagina | Indirizzo | Accesso |
|---|---|---|
| Cittadino | `/` | SPID/CIE simulato |
| Ufficio | `/ufficio` | Basic auth `UFFICIO_USER` / `UFFICIO_PASSWORD` |
| Custode | `/custode` | utente `custode` / `CUSTODE_PASSWORD` |
| API (OpenAPI) | `/api/docs` | libero; `/api/v1/ufficio/*` con le credenziali dell'ufficio |
| Server MCP | `http://localhost:8090/mcp` | solo dalla macchina locale |

### Schema architetturale

```mermaid
flowchart LR
  ENV[[".env<br/>SPAZIO_* · COMUNE_*"]]
  subgraph Utenti
    C([Cittadino])
    U([Ufficio])
    K([Custode])
    AG([Agenti IA esterni<br/>Claude · IDE · orchestratori])
  end
  subgraph Stack["Docker Compose: un'installazione per luogo"]
    APP["spazio-comune-app<br/>FastAPI · Jinja2 · Bootstrap Italia<br/>:8000"]
    DB[("SQLite /data/prenota.db<br/>volume dati<br/>prenotazioni · slot")]
    INF["spazio-comune-inference<br/>IA: regole in italiano<br/>o LLM OpenAI-compatibile"]
    MCP["spazio-comune-mcp<br/>server MCP · :8090/mcp"]
    OLL[("spazio-comune-ollama<br/>LLM locale, opzionale")]
  end
  subgraph Esterni["Servizi esterni (produzione)"]
    SPID["SPID / CIE"]
    PAGO["pagoPA · MyPay"]
    CAL["Outlook · eAgenda<br/>iCal · CSV"]
  end
  ENV -.-> APP
  C & U & K -->|HTTPS| APP
  AG -->|MCP| MCP
  MCP -->|"API REST /api/v1"| APP
  APP --> DB
  APP -->|rete interna| INF
  INF -.-> OLL
  APP -.-> SPID & PAGO
  APP --> CAL
```

| Container | Ruolo | Porta |
|---|---|---|
| `spazio-comune-app` | sito, back-office, custode, API REST; scrive il database | 8000 |
| `spazio-comune-inference` | assistente IA (intenti e FAQ), non tocca il database | solo rete interna |
| `spazio-comune-mcp` | server MCP per altri agenti; usa solo le API dell'app | 127.0.0.1:8090 |
| `spazio-comune-demo` | istanza con orologio fisso e dati fittizi (profilo `demo`) | 8001 |
| `spazio-comune-ollama`, `-ollama-pull` | LLM locale (profilo `llm`) | solo rete interna |
| `spazio-comune-test` | suite pytest (profilo `test`) | – |

### Il database

Sì, c'è un database: **SQLite**, un unico file `/data/prenota.db` nel volume Docker `dati`, scritto solo
dall'app. Per un luogo solo non serve un server di database separato: il backup è la copia di un file.

| Tabella | Contenuto |
|---|---|
| `prenotazioni` | una riga per prenotazione: **numero** (`GDC-7KQ2-M4XP`), attività, orario, stato, IUV pagoPA, intestatario |
| `slot` | una riga per ogni orario del calendario, con **`codice_prenotazione`**: il numero della prenotazione che lo occupa (`NULL` = libero) |
| `v_occupazione` | vista che unisce le due: per ogni slot stato, numero, attività, intestatario |

La doppia prenotazione è impossibile per costruzione: indice univoco sugli slot attivi, vincolo `UNIQUE` su
`slot.codice_prenotazione` e transazioni `BEGIN IMMEDIATE`. Annullamento e scadenza del pagamento liberano lo
slot nella stessa transazione.

```bash
docker exec spazio-comune-app python -c "import sqlite3; [print(*r) for r in sqlite3.connect('/data/prenota.db').execute(
  \"SELECT inizio, stato, codice_prenotazione, cognome FROM v_occupazione WHERE codice_prenotazione IS NOT NULL\")]"
```

### Configurazione `.env`

Un solo modello, **`.env.example`**: i valori funzionano subito in locale, e sopra ogni variabile un commento
`PRODUZIONE:` dice cosa mettere quando il Comune mette in esercizio il servizio
(`cp .env.example .env && chmod 600 .env`). In sintesi:

**Il luogo e il Comune**

| Variabile | Sviluppo (predefinito) | Produzione | A cosa serve |
|---|---|---|---|
| `SPAZIO_NOME` | Campo comunale coperto di via Benagiano | nome del luogo | Titolo del sito, ticket, causale pagoPA |
| `SPAZIO_INDIRIZZO` | Via Benagiano, 70023 Gioia del Colle (BA) | indirizzo del luogo | Pagine, ticket, calendario |
| `SPAZIO_ATTIVITA` | `calcetto,tennis_singolo,tennis_doppio` | attività ammesse | Sottoinsieme di quelle in `catalog.py` |
| `SPAZIO_GIORNI` | `lun,mar,mer,gio,ven,sab` | come da atto dell'ufficio | Giorni di apertura |
| `SPAZIO_ORARIO` | `15-22` | apertura-chiusura | Primo e ultimo slot (es. 15:00 … 21:00) |
| `SPAZIO_DURATA_MIN` | `60` | `60` | Durata di uno slot |
| `SPAZIO_PREAVVISO_GIORNI` | `14` | `14` | Quanti giorni avanti si può prenotare |
| `CODICE_PREFISSO` | `GDC` | sigla del Comune | Prefisso dei numeri di prenotazione |
| `COMUNE_NOME` / `COMUNE_INDIRIZZO` / `COMUNE_SITO` | Comune di Gioia del Colle | dati dell'ente | Intestazione, privacy, ente creditore |
| `UFFICIO_NOME` | Ufficio Cultura, Istruzione e Sport | ufficio competente | Back-office, FAQ, contatti |
| `FONTE_TARIFFE` | D.G.C. n. 37/2025 | estremi della delibera | Citata accanto ai prezzi |

**Applicazione e sicurezza**

| Variabile | Sviluppo (predefinito) | Produzione | A cosa serve |
|---|---|---|---|
| `BASE_URL` | `http://localhost:8000` | `https://prenota.comune.<nome>.it` | URL pubblico senza `/` finale: QR, iCal, ritorno da pagoPA |
| `SECRET_KEY` | casuale a ogni avvio | `openssl rand -hex 32`, **fisso** | Firma sessioni e QR; se cambia, i QR emessi non valgono più |
| `UFFICIO_USER` / `UFFICIO_PASSWORD` | `ufficio.sport` / `cambiami` | utente nominativo / `openssl rand -base64 24` | Back-office e API `/api/v1/ufficio/*` |
| `CUSTODE_PASSWORD` | `custode` | `openssl rand -base64 18` | Pagina `/custode` (utente `custode`) |
| `FEED_TOKEN` | casuale a ogni avvio | `openssl rand -hex 24`, **fisso** | Token del calendario iCal dell'ufficio |
| `TTL_ATTESA_MIN` | `15` | `15` | Minuti di riserva dello slot durante il pagamento |
| `COOKIE_SECURE` | `false` | **`true`** | Cookie solo su HTTPS |
| `PAYMENT_BACKEND` / `IDENTITY_BACKEND` | `mock` | `mock` fino all'integrazione di MyPay SIL e SPID/CIE | Simulazioni pagoPA e SPID/CIE |

**Intelligenza artificiale e MCP**

| Variabile | Sviluppo (predefinito) | Produzione | A cosa serve |
|---|---|---|---|
| `INFERENCE_BACKEND` | `rules` | `rules`; `openai` solo dopo la valutazione d'impatto | Motore offline o LLM compatibile OpenAI |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | Ollama, `qwen2.5:1.5b-instruct` | LLM interno o fornitore qualificato ACN | Endpoint, modello, chiave |
| `LLM_TIMEOUT` | `20` | `20` | Secondi prima di ripiegare sul motore a regole |
| `MCP_UFFICIO_USER` / `MCP_UFFICIO_PASSWORD` | vuoti (strumenti ufficio spenti) | vuoti, o un utente dedicato | Abilitano gli strumenti MCP con i numeri di prenotazione |
| `MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*` | host del reverse proxy | Header Host ammessi (protezione DNS rebinding) |
| `DEMO_ORA` | `2026-11-09T18:35:00` | – | Solo istanza demo: istante di partenza dell'orologio |

`DB_PATH` e `INFERENCE_URL` sono già impostati da `docker-compose.yml`. Dopo una modifica:
`docker compose up -d --force-recreate`. Dettagli: [Configurazione](https://agentengineering.it/spazio-comune/configurazione/).

### IA

- L'IA non prenota né paga; rimuove CF, email, telefono e IBAN prima di chiamare un LLM; ogni risposta dichiara il motore; se il server IA cade il sito funziona con il calendario.
- Funziona senza JavaScript.

### Server MCP per altri sistemi agentici

`mcp_server/server.py` (SDK ufficiale `mcp`, FastMCP) espone il luogo come strumenti per Claude, IDE e
orchestratori. Passa solo dalle API REST dell'app: non legge il database e non conosce i segreti dell'app.
**L'agente propone, la persona decide**: nessuno strumento prenota o paga, `link_prenotazione` restituisce il
link da aprire per completare con SPID/CIE e pagoPA.

| Strumento | Cosa fa |
|---|---|
| `info_spazio` | luogo, Comune, orari, attività e tariffe |
| `disponibilita` | calendario con lo stato di ogni slot (libero, occupato, in pagamento, riservato, passato) |
| `cerca_orari` | dalla frase *"calcetto venerdì sera alle 20"* agli orari liberi più vicini |
| `domanda` | FAQ con le fonti ufficiali |
| `link_prenotazione` | verifica lo slot e restituisce il link di prenotazione |
| `occupazione_slot` *(ufficio)* | per ogni slot, il numero di prenotazione registrato |
| `dettaglio_prenotazione` *(ufficio)* | dettaglio dal numero di prenotazione, senza codice fiscale |

```jsonc
// Claude Desktop / Claude Code (stdio)
{ "mcpServers": { "spazio-comune": {
    "command": "python", "args": ["mcp_server/server.py"],
    "env": { "SPAZIO_COMUNE_URL": "http://localhost:8000" } } } }
```

Via HTTP (container `spazio-comune-mcp`): `http://localhost:8090/mcp`, ad esempio
`claude mcp add --transport http spazio-comune http://localhost:8090/mcp`.

### Test e simulazione

```bash
docker compose --profile test run --rm test                   # 84 test: dominio, web, slot, IA, MCP
docker compose --profile demo up -d && docker compose restart demo
python app/scripts/simula.py --url http://localhost:8001 --cittadini 30
```

La simulazione lancia 30 cittadini virtuali in parallelo sul flusso reale (SPID simulato → slot → pagoPA
simulato), metà dei quali sugli stessi tre orari, e poi controlla sul database che ogni slot occupato porti un
solo numero di prenotazione. Esito su questa versione: 10 prenotazioni confermate e 20 rifiutate perché lo slot
era già preso; ognuno dei 3 slot contesi ha un solo vincitore e nessuno slot è stato venduto due volte.

### Messa in esercizio nella PA

| Ambito | Riferimento | Da fare |
|---|---|---|
| Cloud | Regolamento ACN cloud PA | Hosting su servizio qualificato ACN |
| Identità | CAD art. 64 | Gateway SPID/CIE al posto di `MockIdentity` |
| Pagamenti | CAD art. 5, pagoPA | `MyPaySILGateway` con credenziali SIL di Regione Puglia |
| Sicurezza | Misure minime ICT AgID | HTTPS, segreti, rate limiting, audit log, backup |
| Accessibilità | L. 4/2004, WCAG 2.1 AA | Test utenti, dichiarazione di accessibilità |
| Privacy | GDPR | Registro trattamenti, nomina responsabile, informativa RPD |
| IA | AI Act art. 50, L. 132/2025, Linee guida AgID | Valutazione d'impatto prima di attivare un LLM |
| Riuso | CAD artt. 68-69 | `publiccode.yml`, Developers Italia; un repository per luogo |

→ [Installazione conforme per la PA](https://agentengineering.it/spazio-comune/normativa-it/)

### Senza Docker

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt -r inference/requirements.txt -r mcp_server/requirements.txt pytest
pytest
(cd inference && uvicorn server:app --port 8080) &
(cd app && INFERENCE_URL=http://127.0.0.1:8080 DB_PATH=./prenota.db uvicorn --factory prenota.main:create_app --port 8000)
```

### Demo, video e documentazione

```bash
pip install playwright zensical && playwright install chromium
python app/scripts/registra_demo.py                # video 16:9 (MP4 + GIF) contro :8001
python app/scripts/registra_demo.py --verticale    # video 9:16
python app/scripts/registra_demo.py --screenshot   # screenshot per la documentazione
zensical serve -a 127.0.0.1:8002                   # anteprima del sito
```

Il sito viene pubblicato su GitHub Pages da `.github/workflows/docs.yml` a ogni push su `main`.

## Licenza

EUPL-1.2 · metadati di riuso in [`publiccode.yml`](publiccode.yml).
