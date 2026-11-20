"""Back-office delle impostazioni: interfaccia React (Vite) su /admin e API JSON.

L'interfaccia è una pagina statica compilata con Vite (cartella admin/ del
repository, build in static/admin/): la serve questa stessa app, quindi
sulla VM non c'è un servizio in più né Node.js.

API (solo amministratore, sessione con cookie firmato + header X-CSRF-Token):
  POST /api/v1/admin/login                  {utente, password} -> {utente, csrf}
  POST /api/v1/admin/logout
  GET  /api/v1/admin/session
  GET  /api/v1/admin/settings               tutte le sezioni (segreti: solo impostato sì/no)
  PUT  /api/v1/admin/settings/{section}     salva e valida: venue, activities, schedule, payments, access
                                            (identity no: SPID/CIE sta nel .env)
  POST /api/v1/admin/settings/{section}/restore   torna al .env
  POST /api/v1/admin/identity/verify        legge la discovery OIDC del gateway
  GET  /api/v1/admin/audit-log              chi ha cambiato cosa e quando
  PUT  /api/v1/admin/logo                   logo dell'ente per l'header (PNG, JPEG o WebP, max 512 KB)
  DELETE /api/v1/admin/logo

I vecchi indirizzi /amministrazione/... rimandano a /admin/... (301).
  GET  /logo                                       il logo, pubblico (header del sito)

I segreti non tornano mai al browser: un segreto vuoto o assente conserva il
valore salvato.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .adapters.identity import IdentityError, OIDCIdentity
from .booking import BookingService
from .catalog import WEEKDAYS, WEEKDAY_NAMES, Venue
from .settings_store import IDENTITY_BACKENDS, PAYMENT_BACKENDS, SECTIONS, RuntimeConfig, hash_password

log = logging.getLogger("venue_booking.admin")
SPA = Path(__file__).parent / "static" / "admin" / "index.html"
MIN_PASSWORD = 12
# sezione nell'URL (inglese) -> chiave della sezione salvata nel database
URL_SECTIONS = {"venue": "luogo", "activities": "attivita", "schedule": "orari", "payments": "pagamenti",
                "identity": "identita", "access": "accessi", "audit-log": "registro"}
ENV_ONLY = ("Il gateway SPID/CIE si configura nel file .env (IDENTITY_BACKEND e OIDC_*, compreso OIDC_REDIRECT_URI), "
            "poi si riavvia il servizio")
MAX_IDLE = 30 * 60          # secondi senza richieste prima di dover rientrare
MAX_ATTEMPTS, WINDOW = 10, 15 * 60   # accessi falliti per indirizzo IP in 15 minuti
LOGO_MAX = 512 * 1024
# formati ammessi riconosciuti dai primi byte (niente SVG: può contenere script)
LOGO_SIGNATURES = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",), "image/webp": (b"RIFF",)}


def logo_type(data: bytes) -> str:
    for kind, signatures in LOGO_SIGNATURES.items():
        if any(data.startswith(f) for f in signatures) and (kind != "image/webp" or data[8:12] == b"WEBP"):
            return kind
    raise ValueError("Logo: formato non ammesso, usare PNG, JPEG o WebP")


def _truthy(v) -> bool:
    return v is True or str(v).lower() in ("1", "true", "on", "si", "sì")


def _text(d: dict, key: str) -> str:
    v = d.get(key)
    return "" if v is None else str(v).strip()


def _require_https(url: str, field_name: str) -> str:
    url = url.strip().rstrip("/")
    locale = re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?(/|$)", url)
    if not (url.startswith("https://") or locale):
        raise ValueError(f"{field_name}: indirizzo https:// (http è ammesso solo per localhost)")
    return url


def _secret_value(d: dict, field_name: str, current: str | None) -> str | None:
    if _truthy(d.get(f"{field_name}_cancella")):
        return None
    new = _text(d, field_name)
    return new or current


# ------------------------------------------------------------ validazione delle sezioni
def validate_venue(section: str, d: dict, current_data: dict) -> dict:
    """luogo, attivita, orari: validazione completa del luogo e valori normalizzati (es. 9-13 -> 09:00-13:00)."""
    if section == "attivita":
        codes = {_text(a, "codice").lower() for a in d.get("elenco", [])}
        missing = {a["codice"] for a in current_data["attivita"]["elenco"]} - codes
        if missing:
            raise ValueError(f"Le attività già create non si eliminano ({', '.join(sorted(missing))}): "
                             "togli \"prenotabile\" per disattivarle")
    venue = Venue.from_data({**current_data, section: d})
    return venue.to_data()[section]


def validate_payments(d: dict, current: dict) -> dict:
    backend = _text(d, "backend") or "mock"
    if backend not in PAYMENT_BACKENDS:
        raise ValueError("Intermediario pagoPA non valido")
    try:
        ttl = int(_text(d, "ttl_attesa_min"))
    except ValueError:
        raise ValueError("Minuti per completare il pagamento: numero intero") from None
    if not 5 <= ttl <= 60:
        raise ValueError("Minuti per completare il pagamento: tra 5 e 60")
    v = {"backend": backend, "ttl_attesa_min": ttl, "mypay_endpoint": _text(d, "mypay_endpoint"),
         "mypay_ipa_ente": _text(d, "mypay_ipa_ente"), "mypay_tipo_dovuto": _text(d, "mypay_tipo_dovuto"),
         "mypay_password": _secret_value(d, "mypay_password", current.get("mypay_password"))}
    if backend == "mypay":
        v["mypay_endpoint"] = _require_https(v["mypay_endpoint"], "Endpoint SIL MyPay")
        if not v["mypay_ipa_ente"] or not v["mypay_tipo_dovuto"]:
            raise ValueError("MyPay: codice IPA dell'ente e tipo dovuto sono obbligatori")
        if not v["mypay_password"]:
            raise ValueError("MyPay: inserire la password SIL")
    return v


def validate_access(d: dict, current: dict) -> dict:
    v = {k: current.get(k) for k in ("admin_user", "ufficio_user", "feed_token", "admin_hash", "ufficio_hash", "custode_hash")}
    for field_name, label in (("admin_user", "Utente amministratore"), ("ufficio_user", "Utente dell'ufficio")):
        name = _text(d, field_name)
        if not re.fullmatch(r"[A-Za-z0-9._@-]{1,60}", name):
            raise ValueError(f"{label}: fino a 60 caratteri tra lettere, cifre e . _ @ -")
        v[field_name] = name
    if v["admin_user"] == v["ufficio_user"] or "custode" in (v["admin_user"], v["ufficio_user"]):
        raise ValueError("Amministratore, ufficio e custode devono avere utenti diversi")
    for role, label in (("admin", "amministratore"), ("ufficio", "ufficio"), ("custode", "custode")):
        new = d.get(f"{role}_password") or ""
        if not new:
            continue
        if len(new) < MIN_PASSWORD:
            raise ValueError(f"Password {label}: almeno {MIN_PASSWORD} caratteri")
        v[f"{role}_hash"] = hash_password(new)
    if _truthy(d.get("rigenera_feed")):
        v["feed_token"] = secrets.token_urlsafe(24)
    return v


# ------------------------------------------------------------ rotte
def register(app: FastAPI, *, cfg: RuntimeConfig, service: BookingService,
             oidc: Callable[[], OIDCIdentity | None]) -> None:
    s = cfg.settings
    failed: dict[str, deque] = defaultdict(deque)

    def fingerprint() -> str:
        """Cambia se cambiano utente o password dell'amministratore: le sessioni aperte decadono."""
        a = cfg.access
        base = f"{a['admin_user']}|{a.get('admin_hash') or s.admin_password or ''}"
        return hashlib.sha256(base.encode()).hexdigest()[:16]

    def admin(request: Request) -> str:
        sess = request.session
        user = sess.get("admin")
        if not user or sess.get("admin_fingerprint") != fingerprint() \
                or time.time() - sess.get("admin_last_seen", 0) > MAX_IDLE:
            sess.pop("admin", None)
            raise HTTPException(401, "Accesso richiesto")
        if request.method not in ("GET", "HEAD"):
            token = request.headers.get("x-csrf-token", "")
            if not token or not secrets.compare_digest(token, sess.get("admin_csrf", "")):
                raise HTTPException(403, "Token CSRF mancante o non valido: ricarica la pagina")
        sess["admin_last_seen"] = int(time.time())
        return user

    def mask(values_: dict) -> dict:
        v = dict(values_)
        for k in [k for k in v if k.endswith(("_password", "_secret", "_hash"))]:
            v[k] = bool(v[k])   # al browser arriva solo "impostato sì/no"
        v.pop("feed_token", None)
        return v

    def state() -> dict:
        data = cfg.venue.to_data()
        return {
            **data, "pagamenti": mask(cfg.payments), "identita": mask(cfg.identity),
            "accessi": mask(cfg.access),
            "salvate": {k: {"aggiornata_il": v["aggiornata_il"], "aggiornata_da": v["aggiornata_da"]}
                        for k, v in cfg.archive.saved().items() if k != "identita"},   # SPID/CIE: solo .env
            "non_decifrabili": sorted(f"{a}.{b}" for a, b in cfg.archive.unreadable),
            "errori": cfg.errors, "anteprima": cfg.venue.readable_hours,
            "fuori_calendario": [{k: p[k] for k in ("codice", "inizio", "stato", "cognome", "nome", "note")}
                                 for p in service.off_schedule()],
            "meta": {"base_url": s.base_url, "redirect_uri": cfg.identity["redirect_uri"],
                     "feed": f"{s.base_url}/ufficio/agenda.ics?token={cfg.access['feed_token']}",
                     "backend_pagamento": PAYMENT_BACKENDS, "backend_identita": IDENTITY_BACKENDS,
                     "giorni": WEEKDAYS, "giorni_lunghi": WEEKDAY_NAMES, "password_minima": MIN_PASSWORD,
                     "ufficio": cfg.venue.office, "comune": cfg.venue.municipality, "luogo": cfg.venue.name,
                     "logo": cfg.logo_url, "logo_max_kb": LOGO_MAX // 1024},
        }

    # ---------------------------------------------------------------- interfaccia
    @app.get("/amministrazione", include_in_schema=False)
    @app.get("/amministrazione/{_path:path}", include_in_schema=False)
    def old_admin_url(_path: str = ""):
        """Indirizzo italiano delle prime versioni: si rimanda a /admin, con la sezione equivalente."""
        target = {v: k for k, v in URL_SECTIONS.items()}.get(_path.strip("/"), "")
        return RedirectResponse(f"/admin/{target}" if target else "/admin", status_code=301)

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{_path:path}", include_in_schema=False)
    def admin_ui(_path: str = ""):
        if not SPA.exists():
            return HTMLResponse("<h1>Interfaccia di amministrazione non compilata</h1>"
                                "<p>Eseguire: <code>cd admin && npm ci && npm run build</code></p>", status_code=503)
        return FileResponse(SPA, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    # ---------------------------------------------------------------- sessione
    @app.post("/api/v1/admin/login", tags=["admin"])
    async def log_in(request: Request):
        if not cfg.admin_enabled:
            raise HTTPException(403, "Amministrazione disattivata: impostare ADMIN_PASSWORD nel file .env")
        ip = request.client.host if request.client else "?"
        coda, now = failed[ip], time.time()
        while coda and now - coda[0] > WINDOW:
            coda.popleft()
        if len(coda) >= MAX_ATTEMPTS:
            raise HTTPException(429, "Troppi tentativi non riusciti: riprova tra 15 minuti")
        try:
            d = await request.json()
        except ValueError:
            raise HTTPException(400, "Richiesta non valida") from None
        user, password = str(d.get("utente") or ""), str(d.get("password") or "")
        if not await run_in_threadpool(cfg.verify, "admin", user, password):
            coda.append(now)
            log.warning("accesso amministrazione non riuscito da %s", ip)
            raise HTTPException(401, "Utente o password non corretti")
        coda.clear()
        request.session.update(admin=user, admin_csrf=secrets.token_urlsafe(24), admin_fingerprint=fingerprint(),
                               admin_last_seen=int(now))
        return {"utente": user, "csrf": request.session["admin_csrf"]}

    @app.post("/api/v1/admin/logout", tags=["admin"])
    def log_out(request: Request):
        for k in ("admin", "admin_csrf", "admin_fingerprint", "admin_last_seen"):
            request.session.pop(k, None)
        return {"ok": True}

    @app.get("/api/v1/admin/session", tags=["admin"])
    def session_info(request: Request, user: str = Depends(admin)):
        return {"utente": user, "csrf": request.session["admin_csrf"]}

    # ---------------------------------------------------------------- impostazioni
    @app.get("/api/v1/admin/settings", tags=["admin"])
    def read_settings(_: str = Depends(admin)):
        return state()

    @app.put("/api/v1/admin/settings/{section}", tags=["admin"])
    async def save(request: Request, section: str, user: str = Depends(admin)):
        section = URL_SECTIONS.get(section, "")
        if section not in SECTIONS:
            raise HTTPException(404, "Sezione sconosciuta")
        if section == "identita":
            return JSONResponse({"errore": ENV_ONLY}, status_code=409)
        try:
            d = await request.json()
            if not isinstance(d, dict):
                raise ValueError("Dati non validi")
            if section in ("luogo", "attivita", "orari"):
                values_ = validate_venue(section, d, cfg.venue.to_data())
            elif section == "pagamenti":
                values_ = validate_payments(d, cfg.payments)
            else:
                values_ = validate_access(d, cfg.access)
        except ValueError as e:
            return JSONResponse({"errore": str(e)}, status_code=422)
        changed = await run_in_threadpool(cfg.save, section, values_, user, service.now())
        if section == "orari":
            await run_in_threadpool(service.rebuild_calendar)
        if section == "accessi":   # la sessione resta valida anche se l'amministratore ha cambiato le proprie credenziali
            request.session.update(admin=cfg.access["admin_user"], admin_fingerprint=fingerprint())
        return {**state(), "campi_modificati": changed}

    @app.post("/api/v1/admin/settings/{section}/restore", tags=["admin"])
    async def restore(request: Request, section: str, user: str = Depends(admin)):
        section = URL_SECTIONS.get(section, "")
        if section not in SECTIONS:
            raise HTTPException(404, "Sezione sconosciuta")
        if section == "identita":
            return JSONResponse({"errore": ENV_ONLY}, status_code=409)
        await run_in_threadpool(cfg.restore, section, user, service.now())
        if section == "orari":
            await run_in_threadpool(service.rebuild_calendar)
        if section == "accessi":
            request.session.update(admin=cfg.access["admin_user"], admin_fingerprint=fingerprint())
        return state()

    @app.post("/api/v1/admin/identity/verify", tags=["admin"])
    async def verify_oidc(_: str = Depends(admin)):
        client = oidc() or (OIDCIdentity(cfg.identity, cfg.identity["redirect_uri"])
                            if cfg.identity.get("oidc_issuer") else None)
        if client is None:
            return JSONResponse({"errore": "Impostare OIDC_ISSUER nel file .env e riavviare il servizio"}, status_code=422)
        try:
            meta = await run_in_threadpool(client.discovery, True)
        except IdentityError as e:
            return JSONResponse({"errore": f"Verifica non riuscita: {e}"}, status_code=422)
        return {k: meta.get(k) for k in ("issuer", "authorization_endpoint", "token_endpoint", "userinfo_endpoint",
                                         "scopes_supported", "acr_values_supported", "claims_supported")}

    @app.get("/api/v1/admin/audit-log", tags=["admin"])
    def audit_log(_: str = Depends(admin)):
        return cfg.archive.audit_log()

    # ---------------------------------------------------------------- logo
    @app.put("/api/v1/admin/logo", tags=["admin"])
    async def upload_logo(request: Request, user: str = Depends(admin)):
        data = await request.body()
        if not data:
            return JSONResponse({"errore": "Logo: nessun file ricevuto"}, status_code=422)
        if len(data) > LOGO_MAX:
            return JSONResponse({"errore": f"Logo: file troppo grande (massimo {LOGO_MAX // 1024} KB)"}, status_code=422)
        try:
            kind = logo_type(data)
        except ValueError as e:
            return JSONResponse({"errore": str(e)}, status_code=422)
        await run_in_threadpool(cfg.save_logo, kind, data, user, service.now())
        return state()

    @app.delete("/api/v1/admin/logo", tags=["admin"])
    async def delete_logo(user: str = Depends(admin)):
        await run_in_threadpool(cfg.save_logo, None, None, user, service.now())
        return state()

    @app.get("/logo", include_in_schema=False)
    def logo():
        r = cfg.archive.logo()
        if not r:
            raise HTTPException(404)
        return Response(bytes(r["dati"]), media_type=r["tipo"], headers={
            "Cache-Control": "public, max-age=31536000, immutable",   # l'URL cambia (?v=) a ogni nuovo logo
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})
