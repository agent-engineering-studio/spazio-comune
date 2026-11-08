# Spazio Comune

**Prenotazione online degli spazi comunali con SPID/CIE, pagoPA, QR code e un assistente IA che trova gli orari
partendo da una frase.** Open source (EUPL-1.2), riusabile da qualsiasi Comune.
Pilota proposto: campo coperto di via Benagiano, Comune di Gioia del Colle.

📖 **Documentazione completa:** https://agent-engineering-studio.github.io/spazio-comune/

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

→ [Guida per i cittadini](https://agent-engineering-studio.github.io/spazio-comune/cittadini/) ·
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
| **Riuso** | Nuovi impianti con una scheda di configurazione; codice EUPL-1.2 con `publiccode.yml`. |

Piano proposto: dimostrazione → attivazioni tecniche (MyPay SIL, SPID/CIE, cloud qualificato) → **pilota di 8 settimane** →
valutazione ed estensione.

→ [Benefici per il Comune](https://agent-engineering-studio.github.io/spazio-comune/comune/) ·
[Analisi e proposta](docs/ANALISI.md) · [Conformità normativa](docs/conformita.md)

---

## 3. Per sviluppatori e ufficio IT

### Avvio rapido

```bash
cp .env.example .env                              # poi personalizzare (vedi sotto)
docker compose up --build -d                      # http://localhost:8000
docker compose --profile demo up --build -d       # + istanza con dati fittizi su http://localhost:8001
docker compose --profile test run --rm test       # 63 test
docker compose --profile llm up --build -d        # + LLM locale con Ollama (opzionale)
```

| Pagina | Indirizzo | Accesso |
|---|---|---|
| Cittadino | `/` | SPID/CIE simulato |
| Ufficio Sport | `/ufficio` | Basic auth `UFFICIO_USER` / `UFFICIO_PASSWORD` |
| Custode | `/custode` | utente `custode` / `CUSTODE_PASSWORD` |
| API (OpenAPI) | `/api/docs` | libero |

Container: `spazio-comune-app`, `spazio-comune-inference`, `spazio-comune-demo`, `spazio-comune-ollama`,
`spazio-comune-ollama-pull`, `spazio-comune-test`.

### Configurazione `.env`

| Variabile | Predefinito | A cosa serve |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | URL pubblico senza `/` finale: QR, iCal, ritorno da pagoPA |
| `SECRET_KEY` | casuale a ogni avvio | Firma sessioni e QR. **Fissala** (`openssl rand -hex 32`), altrimenti a ogni riavvio i QR emessi diventano invalidi |
| `UFFICIO_USER` / `UFFICIO_PASSWORD` | `ufficio.sport` / `cambiami` | Accesso al back-office. **Cambiare la password** |
| `CUSTODE_PASSWORD` | `custode` | Accesso a `/custode` (utente `custode`). **Cambiare** |
| `FEED_TOKEN` | casuale a ogni avvio | Token segreto del calendario iCal dell'ufficio; fissalo, o il feed sottoscritto smette di funzionare |
| `TTL_ATTESA_MIN` | `15` | Minuti di riserva dello slot durante il pagamento |
| `COOKIE_SECURE` | `false` | `true` obbligatorio dietro HTTPS |
| `PAYMENT_BACKEND` / `IDENTITY_BACKEND` | `mock` | Simulazioni pagoPA e SPID/CIE (unico valore supportato dal prototipo) |
| `INFERENCE_BACKEND` | `rules` | `rules` = motore IA offline; `openai` = LLM compatibile OpenAI |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | Ollama, `qwen2.5:1.5b-instruct` | Endpoint, modello e chiave dell'LLM (Ollama, vLLM, Azure OpenAI) |
| `LLM_TIMEOUT` | `20` | Secondi prima di ripiegare sul motore a regole |
| `DEMO_ORA` | `2026-11-09T18:35:00` | Solo istanza demo: istante di partenza dell'orologio |

`DB_PATH` e `INFERENCE_URL` sono già impostati da `docker-compose.yml`. Dopo una modifica:
`docker compose up -d --force-recreate`. Dettagli ed esempi:
[Configurazione](https://agent-engineering-studio.github.io/spazio-comune/configurazione/).

### Architettura e IA

```
 cittadino ──► app (FastAPI + Jinja2 + Bootstrap Italia 2.18.3) ──► SQLite / PostgreSQL
                 │   ├─ adapters/identity  SPID/CIE (mock → gateway OIDC/SAML)
                 │   ├─ adapters/payments  pagoPA (mock → MyPay SIL)
                 │   └─ adapters/agenda    feed iCal + CSV
                 └──► inference (rete interna, API OpenAI-compatibile)
                         ├─ "rules": intenti in italiano + FAQ BM25, offline, deterministico (default)
                         └─ "openai": Ollama / vLLM / llama.cpp / Azure OpenAI, con redazione PII
```

- Doppia prenotazione impossibile per costruzione: indice univoco parziale + `BEGIN IMMEDIATE`.
- L'IA non prenota né paga; rimuove CF, email, telefono e IBAN prima di chiamare un LLM; ogni risposta dichiara il motore; se il server IA cade il sito funziona con il calendario.
- Funziona senza JavaScript.

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
| Riuso | CAD artt. 68-69 | `publiccode.yml`, Developers Italia |

→ [Installazione conforme per la PA](https://agent-engineering-studio.github.io/spazio-comune/normativa-it/)

### Senza Docker

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt -r inference/requirements.txt pytest
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
