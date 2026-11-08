"""Spazio Comune: prenotazione di un luogo comunale (prototipo).

Un'installazione gestisce un solo luogo, descritto nel file .env (SPAZIO_*, COMUNE_*).

Applicazione FastAPI con interfaccia Bootstrap Italia 2.x, renderizzata lato
server (funziona anche senza JavaScript, requisito utile per l'accessibilità).
"""
from __future__ import annotations

import io
import logging
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .adapters.agenda import NoopAgenda, to_csv, to_ics
from .adapters.identity import Cittadino, MockIdentity
from .adapters.payments import MockPagoPA
from .ai import AssistenteIA, filtra_slot
from .booking import TZ, ErrorePrenotazione, ServizioPrenotazioni
from .catalog import ATTIVITA, FONTE_TARIFFE
from .config import Settings
from .db import Database

log = logging.getLogger("prenota")
QUI = Path(__file__).parent
GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"]
STATI_LEGGIBILI = {"ATTESA_PAGAMENTO": ("In attesa di pagamento", "warning"), "CONFERMATA": ("Confermata", "success"),
                   "ANNULLATA": ("Annullata", "secondary"), "SCADUTA": ("Scaduta", "secondary"),
                   "BLOCCO": ("Riservato dall'ufficio", "dark"), "UTILIZZATA": ("Utilizzata", "primary")}
# stato dello slot nel calendario: (etichetta, classe CSS)
STATI_SLOT = {"libero": ("Libero", "slot-libero"), "occupato": ("Occupato", "slot-occupato"),
              "in_pagamento": ("In pagamento", "slot-in-pagamento"), "riservato": ("Riservato", "slot-riservato"),
              "passato": ("Passato", "slot-passato")}


def data_lunga(v: str | date | datetime) -> str:
    d = datetime.fromisoformat(v) if isinstance(v, str) else v
    return f"{GIORNI_IT[d.weekday()]} {d.day} {MESI_IT[d.month - 1]} {d.year}"


def euro(cent: int) -> str:
    return f"€ {cent / 100:.2f}".replace(".", ",")


def qr_svg(dati: str) -> str:
    img = qrcode.make(dati, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.find("<svg"):]


def create_app(settings: Settings | None = None, adesso: Callable[[], datetime] | None = None,
               assistente: AssistenteIA | None = None) -> FastAPI:
    s = settings or Settings()
    spazio = s.spazio
    db = Database(s.db_path)
    pagamenti = MockPagoPA(s.base_url) if s.payment_backend == "mock" else None
    if pagamenti is None:  # pragma: no cover
        raise RuntimeError("PAYMENT_BACKEND non supportato in questo prototipo: usare 'mock'")
    identita = MockIdentity()
    agenda = NoopAgenda()
    servizio = ServizioPrenotazioni(db, pagamenti, agenda, s.secret_key, s.ttl_attesa_min, adesso=adesso,
                                    spazio=spazio)
    ia = assistente or AssistenteIA(s.inference_url, spazio=spazio)
    ia.spazio = spazio

    app = FastAPI(title=f"Spazio Comune – {spazio.nome}", version="0.2.0",
                  docs_url="/api/docs", redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=s.secret_key, same_site="lax",
                       https_only=s.cookie_secure, session_cookie="prenota_sess", max_age=60 * 60 * 8)
    app.mount("/static", StaticFiles(directory=QUI / "static"), name="static")
    tpl = Jinja2Templates(directory=QUI / "templates")
    tpl.env.filters.update(data_lunga=data_lunga, euro=euro)
    tpl.env.globals.update(ATTIVITA=ATTIVITA, SPAZIO=spazio, STATI=STATI_LEGGIBILI, STATI_SLOT=STATI_SLOT,
                           FONTE_TARIFFE=FONTE_TARIFFE,
                           ICO="/static/bootstrap-italia/dist/svg/sprites.svg")
    app.state.servizio, app.state.pagamenti, app.state.settings = servizio, pagamenti, s
    basic = HTTPBasic(realm="Spazio Comune")

    # ------------------------------------------------------------ helper
    def csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(24)
        return request.session["csrf"]

    def verifica_csrf(request: Request, token: str) -> None:
        if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
            raise HTTPException(400, "Sessione scaduta: ricarica la pagina e riprova")

    def utente(request: Request) -> Cittadino | None:
        u = request.session.get("utente")
        return Cittadino(**u) if u else None

    def render(request: Request, nome: str, ctx: dict | None = None, status: int = 200) -> HTMLResponse:
        base = {"request": request, "utente": utente(request), "csrf": csrf(request), "ia_attiva": ia.attivo}
        return tpl.TemplateResponse(request, nome, {**base, **(ctx or {})}, status_code=status)

    def ufficio_auth(cred: HTTPBasicCredentials = Depends(basic)) -> str:
        ok = secrets.compare_digest(cred.username, s.ufficio_user) and secrets.compare_digest(cred.password, s.ufficio_password)
        if not ok:
            raise HTTPException(401, "Credenziali non valide", headers={"WWW-Authenticate": "Basic"})
        return cred.username

    def custode_auth(cred: HTTPBasicCredentials = Depends(basic)) -> str:
        if not (cred.username == "custode" and secrets.compare_digest(cred.password, s.custode_password)):
            raise HTTPException(401, "Credenziali non valide", headers={"WWW-Authenticate": "Basic"})
        return "custode"

    def mia(request: Request, codice: str) -> dict:
        u = utente(request)
        p = servizio._riga(codice)
        if not u or p["cf"] != u.cf:
            raise HTTPException(404, "Prenotazione non trovata")
        return p

    @app.exception_handler(ErrorePrenotazione)
    async def _errore(request: Request, exc: ErrorePrenotazione):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"errore": exc.messaggio}, status_code=exc.codice_http)
        return render(request, "errore.html", {"messaggio": exc.messaggio}, status=exc.codice_http)

    # ------------------------------------------------------------ cittadino
    def contesto_home(attivita: str, dal: date | None) -> dict:
        oggi = servizio.adesso().date()
        dal = max(dal or oggi, oggi)
        giorni = servizio.disponibilita(dal, 7)
        return {"attivita_sel": attivita, "giorni": giorni,
                "dal": dal, "prec": (dal - timedelta(days=7)) if dal > oggi else None,
                "succ": dal + timedelta(days=7) if dal + timedelta(days=7) <= oggi + timedelta(days=spazio.preavviso_giorni) else None}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, attivita: str = "calcetto", dal: date | None = None):
        if attivita not in spazio.attivita:
            attivita = spazio.attivita[0]
        return render(request, "home.html", contesto_home(attivita, dal))

    @app.post("/assistente", response_class=HTMLResponse)
    def assistente_post(request: Request, testo: str = Form(..., max_length=500), csrf_token: str = Form("")):
        verifica_csrf(request, csrf_token)
        oggi = servizio.adesso().date()
        intento = ia.interpreta(testo, oggi)
        attivita = (intento or {}).get("attivita")
        if attivita not in spazio.attivita:
            attivita = spazio.attivita[0]
            if intento:
                intento = {**intento, "attivita": attivita}
        dal = date.fromisoformat(intento["data"]) if intento and intento.get("data") else None
        ctx = contesto_home(attivita, dal)
        proposte = filtra_slot(ctx["giorni"], intento) if intento else []
        return render(request, "home.html", {**ctx, "richiesta": testo, "intento": intento, "proposte": proposte})

    @app.post("/faq", response_class=HTMLResponse)
    def faq_post(request: Request, domanda: str = Form(..., max_length=500), csrf_token: str = Form("")):
        verifica_csrf(request, csrf_token)
        risposta = ia.faq(domanda)
        return render(request, "home.html", {**contesto_home(spazio.attivita[0], None), "domanda": domanda, "faq": risposta})

    @app.get("/prenota", response_class=HTMLResponse)
    def riepilogo(request: Request, inizio: str, attivita: str):
        if attivita not in spazio.attivita:
            raise ErrorePrenotazione("Attività non valida")
        if not utente(request):
            ritorno = quote(f"/prenota?inizio={quote(inizio)}&attivita={attivita}", safe="")
            return RedirectResponse(f"/auth/login?ritorno={ritorno}", status_code=303)
        return render(request, "riepilogo.html", {"inizio": inizio, "att": ATTIVITA[attivita]})

    @app.post("/prenota")
    def prenota_post(request: Request, inizio: str = Form(...), attivita: str = Form(...),
                     telefono: str = Form("", max_length=20), note: str = Form("", max_length=280),
                     csrf_token: str = Form("")):
        verifica_csrf(request, csrf_token)
        u = utente(request)
        if not u:
            raise HTTPException(401, "Accesso richiesto")
        p = servizio.prenota(attivita, inizio, u, telefono or None, note or None)
        p = servizio.avvia_pagamento(p["codice"], f"{s.base_url}/pagamento/esito/{p['codice']}")
        return RedirectResponse(p["url_pagamento"], status_code=303)

    @app.get("/pagamento/esito/{codice}", response_class=HTMLResponse)
    def esito(request: Request, codice: str):
        mia(request, codice)
        p = servizio.verifica_pagamento(codice)
        if p["stato"] == "CONFERMATA":
            return RedirectResponse(f"/prenotazione/{codice}", status_code=303)
        return render(request, "attesa.html", {"p": p})

    @app.get("/prenotazione/{codice}", response_class=HTMLResponse)
    def ticket(request: Request, codice: str):
        p = mia(request, codice)
        token = servizio.token_ticket(codice)
        qr = qr_svg(f"{s.base_url}/custode?token={token}") if p["stato"] in ("CONFERMATA", "UTILIZZATA") else None
        return render(request, "ticket.html", {"p": p, "qr": qr, "att": ATTIVITA.get(p["attivita"])})

    @app.get("/prenotazione/{codice}/calendario.ics")
    def ticket_ics(request: Request, codice: str):
        p = mia(request, codice)
        return Response(to_ics([p], "La mia prenotazione", spazio.indirizzo), media_type="text/calendar",
                        headers={"Content-Disposition": f'attachment; filename="{codice}.ics"'})

    @app.post("/prenotazione/{codice}/annulla")
    def annulla_post(request: Request, codice: str, csrf_token: str = Form("")):
        verifica_csrf(request, csrf_token)
        mia(request, codice)
        servizio.annulla(codice)
        return RedirectResponse("/mie-prenotazioni", status_code=303)

    @app.get("/mie-prenotazioni", response_class=HTMLResponse)
    def mie(request: Request):
        u = utente(request)
        if not u:
            return RedirectResponse("/auth/login?ritorno=%2Fmie-prenotazioni", status_code=303)
        return render(request, "mie.html", {"elenco": servizio.prenotazioni_di(u.cf)})

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return render(request, "privacy.html")

    # ------------------------------------------------------------ identità (simulata)
    def _ritorno_sicuro(r: str) -> str:
        return r if r.startswith("/") and not r.startswith("//") else "/"

    @app.get("/auth/login", response_class=HTMLResponse)
    def login(request: Request, ritorno: str = "/"):
        return render(request, "login.html", {"ritorno": _ritorno_sicuro(ritorno)})

    @app.get("/auth/simulato")
    def login_simulato(request: Request, ritorno: str = "/"):
        request.session["utente"] = identita.completa().to_session()
        return RedirectResponse(_ritorno_sicuro(ritorno), status_code=303)

    @app.get("/auth/logout")
    def logout(request: Request):
        request.session.pop("utente", None)
        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------ pagoPA (simulato)
    @app.get("/pagopa-simulato/{iuv}", response_class=HTMLResponse)
    def pagopa_pagina(request: Request, iuv: str, ritorno: str):
        righe = db.query("SELECT * FROM prenotazioni WHERE iuv=?", (iuv,))
        if not righe:
            raise HTTPException(404)
        return render(request, "pagopa_simulato.html", {"p": dict(righe[0]), "iuv": iuv, "ritorno": ritorno})

    @app.post("/pagopa-simulato/{iuv}")
    def pagopa_paga(request: Request, iuv: str, ritorno: str = Form(...), csrf_token: str = Form("")):
        verifica_csrf(request, csrf_token)
        if not ritorno.startswith(s.base_url):
            raise HTTPException(400, "URL di ritorno non valido")
        pagamenti.segna_pagato(iuv)
        return RedirectResponse(ritorno, status_code=303)

    # ------------------------------------------------------------ custode (mobile)
    @app.get("/custode", response_class=HTMLResponse)
    def custode(request: Request, token: str | None = None, _: str = Depends(custode_auth)):
        esito = None
        if token:
            try:
                esito = servizio.check_in(token)
            except ErrorePrenotazione as e:
                esito = {"esito": "ERRORE", "messaggio": e.messaggio}
        oggi = servizio.adesso().date()
        elenco = servizio.elenco(oggi, oggi, ("CONFERMATA", "UTILIZZATA", "BLOCCO"))
        return render(request, "custode.html", {"esito": esito, "elenco": elenco, "oggi": oggi})

    @app.post("/custode")
    def custode_codice(request: Request, codice: str = Form(...), _: str = Depends(custode_auth)):
        codice = codice.strip().upper()
        return RedirectResponse(f"/custode?token={servizio.token_ticket(codice)}", status_code=303)

    # ------------------------------------------------------------ ufficio (back-office)
    @app.get("/ufficio", response_class=HTMLResponse)
    def ufficio(request: Request, dal: date | None = None, _: str = Depends(ufficio_auth)):
        oggi = servizio.adesso().date()
        dal = dal or oggi
        elenco = servizio.elenco(dal, dal + timedelta(days=13))
        confermate = [p for p in elenco if p["stato"] in ("CONFERMATA", "UTILIZZATA")]
        giorni = [{**g, "per_ora": {sl["ora"]: sl for sl in g["slot"]}} for g in servizio.occupazione(dal, 14)]
        return render(request, "ufficio.html", {
            "elenco": elenco, "dal": dal, "giorni": giorni,
            "orari": sorted({sl["ora"] for g in giorni for sl in g["slot"]}),
            "incasso": sum(p["importo_cent"] for p in confermate), "n_conf": len(confermate),
            "feed": f"{s.base_url}/ufficio/agenda.ics?token={s.feed_token}"})

    @app.post("/ufficio/blocca")
    def ufficio_blocca(request: Request, inizio: str = Form(...), motivo: str = Form(...),
                       csrf_token: str = Form(""), _: str = Depends(ufficio_auth)):
        verifica_csrf(request, csrf_token)
        servizio.blocca(inizio, motivo)
        return RedirectResponse("/ufficio", status_code=303)

    @app.post("/ufficio/{codice}/conferma")
    def ufficio_conferma(request: Request, codice: str, riferimento: str = Form(...),
                         csrf_token: str = Form(""), _: str = Depends(ufficio_auth)):
        verifica_csrf(request, csrf_token)
        servizio.conferma_manuale(codice, riferimento)
        return RedirectResponse("/ufficio", status_code=303)

    @app.post("/ufficio/{codice}/annulla")
    def ufficio_annulla(request: Request, codice: str, csrf_token: str = Form(""), _: str = Depends(ufficio_auth)):
        verifica_csrf(request, csrf_token)
        servizio.annulla(codice, da_ufficio=True)
        return RedirectResponse("/ufficio", status_code=303)

    @app.get("/ufficio/export.csv")
    def ufficio_csv(dal: date | None = None, al: date | None = None, _: str = Depends(ufficio_auth)):
        return PlainTextResponse(to_csv(servizio.elenco(dal, al)), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="prenotazioni.csv"'})

    @app.get("/ufficio/agenda.ics")
    def ufficio_ics(token: str):
        if not secrets.compare_digest(token, s.feed_token):
            raise HTTPException(404)
        attive = servizio.elenco(servizio.adesso().date() - timedelta(days=7), None, ("CONFERMATA", "BLOCCO", "UTILIZZATA"))
        return Response(to_ics(attive, spazio.nome, spazio.indirizzo), media_type="text/calendar")

    # ------------------------------------------------------------ API pubbliche (open data, app IO, server MCP)
    def info_spazio() -> dict:
        return {"nome": spazio.nome, "indirizzo": spazio.indirizzo, "comune": spazio.comune,
                "ufficio": spazio.ufficio, "orario": spazio.orario_leggibile,
                "durata_slot_min": spazio.durata_min, "preavviso_giorni": spazio.preavviso_giorni,
                "fonte_tariffe": FONTE_TARIFFE,
                "attivita": [{"codice": a, "nome": ATTIVITA[a].nome, "tariffa_cent": ATTIVITA[a].tariffa_cent,
                              "giocatori": ATTIVITA[a].giocatori} for a in spazio.attivita],
                "url": s.base_url}

    @app.get("/api/v1/health")
    def health():
        return {"stato": "ok", "ia": ia.attivo, "ora": servizio.adesso().isoformat()}

    @app.get("/api/v1/spazio")
    def api_spazio():
        return info_spazio()

    @app.get("/api/v1/disponibilita")
    def api_disponibilita(dal: date | None = None, giorni: int = 7):
        return servizio.disponibilita(dal, min(max(giorni, 1), 14))

    @app.get("/api/v1/assistente")
    def api_assistente(testo: str):
        """Dalla frase agli orari liberi: l'IA propone, la prenotazione la completa la persona."""
        if len(testo) > 500:
            raise ErrorePrenotazione("Testo troppo lungo (massimo 500 caratteri)")
        intento = ia.interpreta(testo, servizio.adesso().date())
        if intento is None:
            return {"intento": None, "proposte": [], "messaggio": "Assistente non disponibile: usa /api/v1/disponibilita"}
        if intento.get("attivita") not in spazio.attivita:
            intento = {**intento, "attivita": spazio.attivita[0]}
        dal = date.fromisoformat(intento["data"]) if intento.get("data") else None
        proposte = filtra_slot(servizio.disponibilita(dal, 7), intento)
        for p in proposte:
            p["link_prenotazione"] = f"{s.base_url}/prenota?inizio={quote(p['inizio'])}&attivita={intento['attivita']}"
        return {"intento": intento, "proposte": proposte}

    @app.get("/api/v1/faq")
    def api_faq(domanda: str):
        if len(domanda) > 500:
            raise ErrorePrenotazione("Domanda troppo lunga (massimo 500 caratteri)")
        return ia.faq(domanda) or {"trovata": False, "risposta": None, "fonti": []}

    # API riservate all'ufficio (Basic auth): occupazione con numeri di prenotazione
    @app.get("/api/v1/ufficio/occupazione")
    def api_occupazione(dal: date | None = None, giorni: int = 7, _: str = Depends(ufficio_auth)):
        return servizio.occupazione(dal, min(max(giorni, 1), 14))

    @app.get("/api/v1/ufficio/prenotazioni/{codice}")
    def api_prenotazione(codice: str, _: str = Depends(ufficio_auth)):
        p = servizio._riga(codice.strip().upper())
        return {k: p[k] for k in ("codice", "attivita", "inizio", "fine", "stato", "canale", "importo_cent",
                                  "iuv", "cognome", "nome", "note", "creata_il")}

    return app
# Avvio: uvicorn --factory prenota.main:create_app
