"""Spazio Comune: prenotazione di un luogo comunale (prototipo).

Un'installazione gestisce un solo luogo: il file .env dà i valori iniziali, il
back-office /admin li cambia senza riavvio (impostazioni.py).

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
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import admin
from .adapters.agenda import NoopAgenda, to_csv, to_ics
from .adapters.identity import Citizen, IdentityError, MockIdentity, OIDCIdentity, check_identity_config
from .adapters.payments import MockPagoPA, create_gateway
from .ai import AIAssistant, filter_slots
from .booking import TZ, BookingError, BookingService
from .catalog import WEEKDAYS
from .config import Settings
from .db import Database
from .settings_store import RuntimeConfig

log = logging.getLogger("prenota")
HERE = Path(__file__).parent
WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"]
STATE_LABELS = {"ATTESA_PAGAMENTO": ("In attesa di pagamento", "warning"), "CONFERMATA": ("Confermata", "success"),
                   "ANNULLATA": ("Annullata", "secondary"), "SCADUTA": ("Scaduta", "secondary"),
                   "BLOCCO": ("Riservato dall'ufficio", "dark"), "UTILIZZATA": ("Utilizzata", "primary")}
# stato dello slot nel calendario: (etichetta, classe CSS)
SLOT_STATES = {"libero": ("Libero", "slot-free"), "occupato": ("Occupato", "slot-taken"),
              "in_pagamento": ("In pagamento", "slot-pending"), "riservato": ("Riservato", "slot-reserved"),
              "passato": ("Passato", "slot-past")}


def long_date(v: str | date | datetime) -> str:
    d = datetime.fromisoformat(v) if isinstance(v, str) else v
    return f"{WEEKDAYS_IT[d.weekday()]} {d.day} {MONTHS_IT[d.month - 1]} {d.year}"


def euro(cent: int) -> str:
    return f"€ {cent / 100:.2f}".replace(".", ",")


def qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.find("<svg"):]


def create_app(settings: Settings | None = None, now: Callable[[], datetime] | None = None,
               assistant: AIAssistant | None = None) -> FastAPI:
    s = settings or Settings()
    db = Database(s.database_url, s.database_schema)
    cfg = RuntimeConfig(s, db, s.venue)
    try:
        check_identity_config(cfg.identity)
    except ValueError as e:
        db.close()
        raise RuntimeError(f"Configurazione SPID/CIE non valida: {e}") from None
    agenda = NoopAgenda()
    service = BookingService(db, create_gateway(cfg.payments, s.base_url), agenda, s.secret_key,
                                    now=now, venue=cfg.venue)
    ai = assistant or AIAssistant(s.inference_url, venue=cfg.venue)
    gateways: dict = {"payments": None, "identity": None, "oidc": None}

    def apply(c: RuntimeConfig) -> None:
        """Le impostazioni salvate valgono subito: luogo, orari, tariffe, gateway di pagamento e di accesso."""
        service.venue = ai.venue = c.venue
        service.ttl = timedelta(minutes=int(c.payments.get("ttl_attesa_min") or 15))
        if gateways["payments"] != c.payments:   # il gateway si ricrea solo se cambia (il simulato tiene in memoria i pagati)
            try:
                service.payments = create_gateway(c.payments, s.base_url)
            except ValueError as e:
                log.error("%s: resta in uso il gateway precedente", e)
            app.state.payments = service.payments
            gateways["payments"] = dict(c.payments)
        if gateways["identity"] != c.identity:
            gateways["oidc"] = OIDCIdentity(c.identity, c.identity["redirect_uri"]) \
                if c.identity.get("backend") == "oidc" else None
            gateways["identity"] = dict(c.identity)

    app = FastAPI(title=f"Spazio Comune – {cfg.venue.name}", version="0.3.0",
                  docs_url="/api/docs", redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=s.secret_key, same_site="lax",
                       https_only=s.cookie_secure, session_cookie="prenota_sess", max_age=60 * 60 * 8)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    tpl.env.filters.update(long_date=long_date, euro=euro)
    tpl.env.globals.update(STATES=STATE_LABELS, SLOT_STATES=SLOT_STATES,
                           ICO="/static/bootstrap-italia/dist/svg/sprites.svg")
    app.router.add_event_handler("shutdown", db.close)
    app.state.service, app.state.settings, app.state.db, app.state.config = service, s, db, cfg
    cfg.on_change(apply)
    mock_identity = MockIdentity()
    basic = HTTPBasic(realm="Spazio Comune")

    @app.middleware("http")
    async def reload_settings(request: Request, call_next):
        # un altro worker o un'altra VM può aver salvato le impostazioni: si ricaricano (al massimo ogni 3 s)
        if not request.url.path.startswith("/static/"):
            await run_in_threadpool(cfg.refresh_if_needed)
        return await call_next(request)

    # ------------------------------------------------------------ helper
    def csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(24)
        return request.session["csrf"]

    def check_csrf(request: Request, token: str) -> None:
        if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
            raise HTTPException(400, "Sessione scaduta: ricarica la pagina e riprova")

    def user(request: Request) -> Citizen | None:
        u = request.session.get("citizen")
        return Citizen(**u) if u else None

    def render(request: Request, name: str, ctx: dict | None = None, status: int = 200) -> HTMLResponse:
        sp = cfg.venue
        base = {"request": request, "user": user(request), "csrf": csrf(request), "ai_enabled": ai.enabled,
                "VENUE": sp, "ACTIVITIES": sp.catalog, "FEES_SOURCE": sp.fees_source, "LOGO": cfg.logo_url,
                "mock_payments": cfg.payments.get("backend") == "mock",
                "mock_identity": cfg.identity.get("backend") != "oidc",
                "slot_fee": lambda code, start_iso: sp.fee_for(code, datetime.fromisoformat(start_iso))}
        return tpl.TemplateResponse(request, name, {**base, **(ctx or {})}, status_code=status)

    def office_auth(cred: HTTPBasicCredentials = Depends(basic)) -> str:
        if not cfg.verify("ufficio", cred.username, cred.password):
            raise HTTPException(401, "Credenziali non valide", headers={"WWW-Authenticate": "Basic"})
        return cred.username

    def keeper_auth(cred: HTTPBasicCredentials = Depends(basic)) -> str:
        if not cfg.verify("custode", cred.username, cred.password):
            raise HTTPException(401, "Credenziali non valide", headers={"WWW-Authenticate": "Basic"})
        return "custode"

    def own_booking(request: Request, code: str) -> dict:
        u = user(request)
        p = service._row(code)
        if not u or p["cf"] != u.tax_code:
            raise HTTPException(404, "Prenotazione non trovata")
        return p

    @app.exception_handler(BookingError)
    async def _booking_error_handler(request: Request, exc: BookingError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"errore": exc.message}, status_code=exc.http_status)
        return render(request, "error.html", {"message": exc.message}, status=exc.http_status)

    @app.exception_handler(IdentityError)
    async def _identity_error_handler(request: Request, exc: IdentityError):
        return render(request, "error.html", {"message": str(exc)}, status=400)

    # ------------------------------------------------------------ cittadino
    def home_context(activity: str, from_: date | None) -> dict:
        venue = cfg.venue
        today = service.now().date()
        from_ = max(from_ or today, today)
        days = service.availability(from_, 7)
        return {"selected_activity": activity, "days": days,
                "from_date": from_, "prev_week": (from_ - timedelta(days=7)) if from_ > today else None,
                "next_week": from_ + timedelta(days=7) if from_ + timedelta(days=7) <= today + timedelta(days=venue.advance_days) else None}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, activity: str = Query("calcetto"), from_: date | None = Query(None, alias="from")):
        venue = cfg.venue
        if activity not in venue.activities:
            activity = venue.activities[0]
        return render(request, "home.html", home_context(activity, from_))

    @app.post("/assistant", response_class=HTMLResponse)
    def assistant_post(request: Request, text: str = Form(..., max_length=500), csrf_token: str = Form("")):
        venue = cfg.venue
        check_csrf(request, csrf_token)
        today = service.now().date()
        intent = ai.interpret(text, today)
        activity = (intent or {}).get("attivita")
        if activity not in venue.activities:
            activity = venue.activities[0]
            if intent:
                intent = {**intent, "attivita": activity}
        from_ = date.fromisoformat(intent["data"]) if intent and intent.get("data") else None
        ctx = home_context(activity, from_)
        proposals = filter_slots(ctx["days"], intent) if intent else []
        return render(request, "home.html", {**ctx, "request_text": text, "intent": intent, "proposals": proposals})

    @app.post("/faq", response_class=HTMLResponse)
    def faq_post(request: Request, question: str = Form(..., max_length=500), csrf_token: str = Form("")):
        venue = cfg.venue
        check_csrf(request, csrf_token)
        answer = ai.faq(question)
        return render(request, "home.html", {**home_context(venue.activities[0], None), "question": question, "faq": answer})

    @app.get("/book", response_class=HTMLResponse)
    def summary(request: Request, start: str = Query(...), activity: str = Query(...)):
        venue = cfg.venue
        if activity not in venue.activities:
            raise BookingError("Attività non valida")
        if not user(request):
            return_url = quote(f"/book?start={quote(start)}&activity={activity}", safe="")
            return RedirectResponse(f"/auth/login?return_url={return_url}", status_code=303)
        try:
            fee = venue.fee_for(activity, datetime.fromisoformat(start))
            band = venue.fee_band_for(activity, datetime.fromisoformat(start))
        except ValueError:
            raise BookingError("Orario non valido") from None
        return render(request, "summary.html", {"start": start, "activity": venue.catalog[activity],
                                                "fee_cents": fee, "fee_band": band})

    @app.post("/book")
    def book_post(request: Request, start: str = Form(...), activity: str = Form(...),
                     phone: str = Form("", max_length=20), note: str = Form("", max_length=280),
                     csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        u = user(request)
        if not u:
            raise HTTPException(401, "Accesso richiesto")
        p = service.book(activity, start, u, phone or None, note or None)
        p = service.start_payment(p["codice"], f"{s.base_url}/payment/result/{p['codice']}")
        return RedirectResponse(p["url_pagamento"], status_code=303)

    @app.get("/payment/result/{code}", response_class=HTMLResponse)
    def outcome(request: Request, code: str):
        own_booking(request, code)
        p = service.check_payment(code)
        if p["stato"] == "CONFERMATA":
            return RedirectResponse(f"/booking/{code}", status_code=303)
        return render(request, "pending.html", {"p": p})

    @app.get("/booking/{code}", response_class=HTMLResponse)
    def ticket(request: Request, code: str):
        venue = cfg.venue
        p = own_booking(request, code)
        token = service.token_ticket(code)
        qr = qr_svg(f"{s.base_url}/checkin?token={token}") if p["stato"] in ("CONFERMATA", "UTILIZZATA") else None
        return render(request, "ticket.html", {"p": p, "qr": qr, "activity": venue.catalog.get(p["attivita"])})

    @app.get("/booking/{code}/calendar.ics")
    def ticket_ics(request: Request, code: str):
        venue = cfg.venue
        p = own_booking(request, code)
        return Response(to_ics([p], "La mia prenotazione", venue.address, venue.catalog), media_type="text/calendar",
                        headers={"Content-Disposition": f'attachment; filename="{code}.ics"'})

    @app.post("/booking/{code}/cancel")
    def cancel_post(request: Request, code: str, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        own_booking(request, code)
        service.cancel(code)
        return RedirectResponse("/my-bookings", status_code=303)

    @app.get("/my-bookings", response_class=HTMLResponse)
    def mine(request: Request):
        u = user(request)
        if not u:
            return RedirectResponse("/auth/login?return_url=%2Fmy-bookings", status_code=303)
        return render(request, "my_bookings.html", {"bookings": service.bookings_of(u.tax_code)})

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return render(request, "privacy.html")

    # ------------------------------------------------------------ identità: SPID/CIE (OIDC) o simulata
    def _safe_return(r: str) -> str:
        return r if r.startswith("/") and not r.startswith("//") else "/"

    @app.get("/auth/login", response_class=HTMLResponse)
    def login(request: Request, return_url: str = Query("/")):
        return render(request, "login.html", {"return_url": _safe_return(return_url)})

    @app.get("/auth/mock")
    def login_mock(request: Request, return_url: str = Query("/")):
        if gateways["oidc"] is not None:   # con SPID/CIE reale l'accesso simulato non esiste
            raise HTTPException(404)
        request.session["citizen"] = mock_identity.complete().to_session()
        return RedirectResponse(_safe_return(return_url), status_code=303)

    @app.get("/auth/oidc/start")
    def login_oidc(request: Request, return_url: str = Query("/")):
        if gateways["oidc"] is None:
            raise HTTPException(404)
        return RedirectResponse(gateways["oidc"].start(request.session, _safe_return(return_url)), status_code=303)

    @app.get("/auth/oidc/callback")
    def login_oidc_callback(request: Request, code: str | None = None, state: str | None = None,
                            error: str | None = None):
        if gateways["oidc"] is None:
            raise HTTPException(404)
        citizen, return_url = gateways["oidc"].complete(request.session, code, state, error)
        request.session["citizen"] = citizen.to_session()
        return RedirectResponse(_safe_return(return_url), status_code=303)

    @app.get("/auth/logout")
    def logout(request: Request):
        request.session.pop("citizen", None)
        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------ pagoPA (simulato)
    def mock_payments() -> MockPagoPA:
        if not isinstance(service.payments, MockPagoPA):   # con pagoPA reale la pagina simulata non esiste
            raise HTTPException(404)
        return service.payments

    @app.get("/pagopa-mock/{iuv}", response_class=HTMLResponse)
    def pagopa_page(request: Request, iuv: str, return_url: str = Query(...)):
        mock_payments()
        rows = db.query("SELECT * FROM prenotazioni WHERE iuv=%s", (iuv,))
        if not rows:
            raise HTTPException(404)
        return render(request, "pagopa_mock.html", {"p": dict(rows[0]), "iuv": iuv, "return_url": return_url})

    @app.post("/pagopa-mock/{iuv}")
    def pagopa_pay(request: Request, iuv: str, return_url: str = Form(...), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        if not return_url.startswith(s.base_url):
            raise HTTPException(400, "URL di ritorno non valido")
        mock_payments().mark_paid(iuv)
        return RedirectResponse(return_url, status_code=303)

    # ------------------------------------------------------------ custode (mobile)
    @app.get("/checkin", response_class=HTMLResponse)
    def keeper(request: Request, token: str | None = None, _: str = Depends(keeper_auth)):
        outcome = None
        if token:
            try:
                outcome = service.check_in(token)
            except BookingError as e:
                outcome = {"esito": "ERRORE", "messaggio": e.message}
        today = service.now().date()
        items = service.items(today, today, ("CONFERMATA", "UTILIZZATA", "BLOCCO"))
        return render(request, "keeper.html", {"outcome": outcome, "bookings": items, "today": today})

    @app.post("/checkin")
    def keeper_code(request: Request, code: str = Form(...), _: str = Depends(keeper_auth)):
        code = code.strip().upper()
        return RedirectResponse(f"/checkin?token={service.token_ticket(code)}", status_code=303)

    # ------------------------------------------------------------ backoffice dell'ufficio
    @app.get("/backoffice", response_class=HTMLResponse)
    def office(request: Request, from_: date | None = Query(None, alias="from"), _: str = Depends(office_auth)):
        today = service.now().date()
        from_ = from_ or today
        items = service.items(from_, from_ + timedelta(days=13))
        confirmed = [p for p in items if p["stato"] in ("CONFERMATA", "UTILIZZATA")]
        days = [{**g, "by_hour": {sl["ora"]: sl for sl in g["slot"]}} for g in service.occupancy(from_, 14)]
        return render(request, "office.html", {
            "bookings": items, "from_date": from_, "days": days,
            "hours": sorted({sl["ora"] for g in days for sl in g["slot"]}),
            "revenue": sum(p["importo_cent"] for p in confirmed), "n_confirmed": len(confirmed),
            "feed": f"{s.base_url}/backoffice/calendar.ics?token={cfg.access['feed_token']}",
            "off_schedule": service.off_schedule()})

    @app.post("/backoffice/block")
    def office_block(request: Request, start: str = Form(...), reason: str = Form(...),
                       csrf_token: str = Form(""), _: str = Depends(office_auth)):
        check_csrf(request, csrf_token)
        service.block(start, reason)
        return RedirectResponse("/backoffice", status_code=303)

    @app.post("/backoffice/{code}/confirm")
    def office_confirm(request: Request, code: str, reference: str = Form(...),
                         csrf_token: str = Form(""), _: str = Depends(office_auth)):
        check_csrf(request, csrf_token)
        service.confirm_manually(code, reference)
        return RedirectResponse("/backoffice", status_code=303)

    @app.post("/backoffice/{code}/cancel")
    def office_cancel(request: Request, code: str, csrf_token: str = Form(""), _: str = Depends(office_auth)):
        check_csrf(request, csrf_token)
        service.cancel(code, by_office=True)
        return RedirectResponse("/backoffice", status_code=303)

    @app.get("/backoffice/export.csv")
    def office_csv(from_: date | None = Query(None, alias="from"), to_: date | None = Query(None, alias="to"), _: str = Depends(office_auth)):
        return PlainTextResponse(to_csv(service.items(from_, to_)), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="prenotazioni.csv"'})

    @app.get("/backoffice/calendar.ics")
    def office_ics(token: str):
        venue = cfg.venue
        if not secrets.compare_digest(token.encode(), cfg.access["feed_token"].encode()):
            raise HTTPException(404)
        active = service.items(service.now().date() - timedelta(days=7), None, ("CONFERMATA", "BLOCCO", "UTILIZZATA"))
        return Response(to_ics(active, venue.name, venue.address, venue.catalog), media_type="text/calendar")

    # ------------------------------------------------------------ API pubbliche (open data, app IO, server MCP)
    def venue_info() -> dict:
        venue = cfg.venue
        return {"nome": venue.name, "indirizzo": venue.address, "comune": venue.municipality,
                "ufficio": venue.office, "orario": venue.readable_hours,
                "durata_slot_min": venue.slot_minutes, "preavviso_giorni": venue.advance_days,
                "fonte_tariffe": venue.fees_source, "ore_annullamento": venue.cancel_hours,
                "attivita": [{"codice": a, "nome": venue.catalog[a].name, "tariffa_cent": venue.catalog[a].fee_cents,
                              "giocatori": venue.catalog[a].players} for a in venue.activities],
                "fasce_tariffarie": [{"nome": b.name, "dalle": f"{b.start_min // 60:02d}:{b.start_min % 60:02d}",
                                      "alle": f"{b.end_min // 60:02d}:{b.end_min % 60:02d}",
                                      "giorni": [WEEKDAYS[d] for d in sorted(b.weekdays)], "tariffe_cent": dict(b.fees)}
                                     for b in venue.fee_bands],
                "url": s.base_url}

    @app.get("/api/v1/health")
    def health():
        try:
            db.query("SELECT 1")
        except Exception:
            log.exception("database non raggiungibile")
            return JSONResponse({"stato": "errore", "database": "non raggiungibile"}, status_code=503)
        return {"stato": "ok", "database": "ok", "ia": ai.enabled, "ora": service.now().isoformat()}

    @app.get("/api/v1/venue")
    def api_venue():
        return venue_info()

    @app.get("/api/v1/availability")
    def api_availability(from_: date | None = Query(None, alias="from"), days: int = Query(7)):
        return service.availability(from_, min(max(days, 1), 14))

    @app.get("/api/v1/assistant")
    def api_assistant(text: str = Query(...)):
        """Dalla frase agli orari liberi: l'IA propone, la prenotazione la completa la persona."""
        venue = cfg.venue
        if len(text) > 500:
            raise BookingError("Testo troppo lungo (massimo 500 caratteri)")
        intent = ai.interpret(text, service.now().date())
        if intent is None:
            return {"intento": None, "proposte": [], "messaggio": "Assistente non disponibile: usa /api/v1/disponibilita"}
        if intent.get("attivita") not in venue.activities:
            intent = {**intent, "attivita": venue.activities[0]}
        from_ = date.fromisoformat(intent["data"]) if intent.get("data") else None
        proposals = filter_slots(service.availability(from_, 7), intent)
        for p in proposals:
            p["link_prenotazione"] = f"{s.base_url}/book?start={quote(p['inizio'])}&activity={intent['attivita']}"
        answer = {"intento": intent, "proposte": proposals}
        if not proposals:
            answer["messaggio"] = "Nessun orario libero corrispondente nei prossimi giorni: vedi /api/v1/disponibilita"
        elif intent.get("data") and proposals[0]["data"] != intent["data"]:
            answer["messaggio"] = "Nessun orario libero nel giorno richiesto: le proposte sono nei giorni successivi"
        return answer

    @app.get("/api/v1/faq")
    def api_faq(question: str = Query(...)):
        if len(question) > 500:
            raise BookingError("Domanda troppo lunga (massimo 500 caratteri)")
        return ai.faq(question) or {"trovata": False, "risposta": None, "fonti": []}

    # API riservate all'ufficio (Basic auth): occupazione con numeri di prenotazione
    @app.get("/api/v1/backoffice/occupancy")
    def api_occupancy(from_: date | None = Query(None, alias="from"), days: int = Query(7), _: str = Depends(office_auth)):
        return service.occupancy(from_, min(max(days, 1), 14))

    @app.get("/api/v1/backoffice/bookings/{code}")
    def api_booking(code: str, _: str = Depends(office_auth)):
        p = service._row(code.strip().upper())
        return {k: p[k] for k in ("codice", "attivita", "inizio", "fine", "stato", "canale", "importo_cent",
                                  "iuv", "cognome", "nome", "note", "creata_il")}

    admin.register(app, cfg=cfg, service=service, oidc=lambda: gateways["oidc"])
    return app
# Avvio: uvicorn --factory venue_booking.main:create_app
