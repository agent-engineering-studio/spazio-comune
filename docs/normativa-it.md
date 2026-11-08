---
title: Installazione conforme per la PA
description: Checklist per l'ufficio IT per mettere in esercizio Spazio Comune secondo le norme ICT della Pubblica Amministrazione.
---

# Installazione conforme per la PA

Questa pagina è per l'**ufficio IT** e il **Responsabile per la transizione digitale (RTD)**. Elenca, norma per
norma, cosa fa già il software e cosa resta da fare in fase di installazione e messa in esercizio.

!!! warning "Da validare"
    La checklist è un supporto tecnico. Classificazione dei dati, valutazioni d'impatto e atti formali
    vanno confermati con RTD, RPD e Segretario comunale.

## Checklist

| Ambito | Riferimento | Cosa fa il software | Cosa fa l'IT all'installazione |
|---|---|---|---|
| **Riuso e open source** | CAD artt. 68-69; Linee guida AgID su acquisizione e riuso del software | Licenza EUPL-1.2, `publiccode.yml` | Pubblicare il riuso su Developers Italia; valutazione comparativa ex art. 68 nell'atto di adozione |
| **Cloud** | Regolamento ACN per le infrastrutture e i servizi cloud della PA | Container Docker, nessun servizio esterno obbligatorio | Ospitare su infrastruttura o servizio cloud **qualificato ACN** adeguato alla classificazione dei dati |
| **Identità digitale** | CAD art. 64; regole tecniche SPID e CIE | Adapter `identity` con attributi minimi (CF, nome, cognome, email) | Collegare il gateway SPID/CIE del portale o un proxy OIDC certificato, sostituendo `MockIdentity` |
| **Pagamenti** | CAD art. 5; Linee guida pagoPA | Dovuto con importo e causale esatti, IUV per prenotazione, verifica idempotente | Chiedere a Regione Puglia l'accesso MyPay SIL, completare `MyPaySILGateway` e il job di verifica dei pagamenti |
| **Design** | Linee guida di design per i servizi digitali della PA | Bootstrap Italia 2.18.3 ospitato in locale con verifica sha512 | Link dalla sezione *Prenota appuntamento* del portale |
| **Accessibilità** | L. 4/2004; Linee guida AgID sull'accessibilità; WCAG 2.1 AA / EN 301 549 | Render lato server, funziona senza JavaScript; audit axe-core senza violazioni | Test con utenti; aggiornare la **dichiarazione di accessibilità** su form.agid.gov.it |
| **Protezione dati** | GDPR artt. 6.1.e, 25, 28, 30, 32 | Minimizzazione: telefono facoltativo, CF escluso dagli export; cookie solo tecnico | Registro dei trattamenti, nomina del fornitore come responsabile, informativa validata dal RPD, tempi di conservazione |
| **Sicurezza ICT** | Misure minime di sicurezza ICT per le PA (circolare AgID 2/2017) | CSRF, cookie firmati, QR firmati HMAC, anti open-redirect, container non-root, inferenza non esposta | HTTPS, segreti robusti, rate limiting, log di audit, backup, aggiornamenti, vulnerability assessment |
| **Interoperabilità** | Linee guida AgID sull'interoperabilità tecnica | API REST documentate in OpenAPI (`/api/docs`) | Valutare la pubblicazione su PDND se le API servono ad altri enti |
| **Intelligenza artificiale** | AI Act (Reg. UE 2024/1689) art. 50; L. 132/2025; Linee guida AgID per l'IA nella PA | Trasparenza in interfaccia, decisione umana, redazione dei dati personali, tracciabilità del motore | Valutazione d'impatto prima di attivare un LLM; iscrizione nel registro dei sistemi IA dell'ente |

## Messa in esercizio passo per passo

### 1. Infrastruttura

- Una VM o un servizio container su cloud **qualificato ACN**, con almeno 1 vCPU e 1 GB di RAM per app e motore a regole. Un LLM locale (`--profile llm`) richiede almeno 4 vCPU e 8 GB di RAM.
- Docker Engine e Compose v2, con aggiornamenti di sicurezza automatici del sistema operativo.
- Database: SQLite va bene per il pilota; in esercizio PostgreSQL gestito (lo schema è portabile, l'indice univoco parziale è supportato).

### 2. Rete e HTTPS

Mettere un reverse proxy davanti all'app, con TLS 1.2 o superiore e certificato valido. Pubblicare **solo**
la porta dell'app: il server di inferenza e Ollama restano sulla rete interna di Compose.

```nginx
server {
  listen 443 ssl http2;
  server_name prenota.comune.example.it;
  ssl_protocols TLSv1.2 TLSv1.3;
  add_header Strict-Transport-Security "max-age=31536000" always;
  limit_req zone=prenota burst=20 nodelay;     # rate limiting

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
```

### 3. Configurazione e segreti

```bash
cp .env.example .env && chmod 600 .env
# BASE_URL=https://prenota.comune.example.it
# SECRET_KEY, UFFICIO_PASSWORD, CUSTODE_PASSWORD, FEED_TOKEN: valori casuali robusti
# COOKIE_SECURE=true
docker compose up --build -d
```

Il significato di ogni variabile è in [Configurazione (.env)](configurazione.md). In esercizio i segreti vanno
in un vault o nei *secret* della piattaforma, non in chiaro sul disco.

### 4. Backup e continuità

```bash
# backup giornaliero del database SQLite (volume "dati")
docker run --rm -v spazio-comune_dati:/data -v /backup:/backup alpine \
  sh -c 'cp /data/prenota.db /backup/prenota-$(date +%F).db'
```

Conservare i backup cifrati su un sito diverso e provare il ripristino almeno una volta prima del pilota.

### 5. Log, monitoraggio e aggiornamenti

- Healthcheck: `GET /api/v1/health` (app) e `GET /health` (inferenza), già usati dai container.
- Centralizzare i log (`docker logs spazio-comune-app`) con una conservazione coerente con l'informativa privacy.
- Aggiornare con regolarità le immagini e le dipendenze Python, ad esempio con `pip-audit` e una scansione delle immagini in CI.

### 6. Prima del pilota

- [ ] HTTPS attivo e `COOKIE_SECURE=true`
- [ ] Segreti robusti e non versionati
- [ ] Integrazioni MyPay SIL e SPID/CIE collaudate in ambiente di test
- [ ] Backup provato
- [ ] Registro dei trattamenti e informativa approvati dal RPD
- [ ] Dichiarazione di accessibilità aggiornata
- [ ] Valutazione d'impatto IA (se si attiva un LLM)
- [ ] Repository pubblico e `publiccode.yml` aggiornati
