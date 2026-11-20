"""Back-office /amministrazione: impostazioni salvate nel database, valide subito, segreti cifrati."""
import base64
import json
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from venue_booking import main as main_module
from venue_booking.adapters.identity import OIDCIdentity
from venue_booking.ai import AIAssistant
from venue_booking.settings_store import SecretBox, hash_password, verify_password
from venue_booking.main import create_app

from test_web import _book_and_pay

ADMIN = ("admin", "admin-pw")
API = "/api/v1/amministrazione"


def _log_in(c, user="admin", password="admin-pw"):
    r = c.post(f"{API}/accesso", json={"utente": user, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf"]
    return r.json()


def _state(c):
    if "X-CSRF-Token" not in c.headers:
        _log_in(c)
    r = c.get(f"{API}/impostazioni")
    assert r.status_code == 200, r.text
    return r.json()


def _save(c, section, **changes):
    """Salva una sezione partendo dai valori attuali, come fa l'interfaccia."""
    data = {**_state(c)[section], **changes}
    return c.put(f"{API}/impostazioni/{section}", json=data)


def _save_schedule(c, week=None, **changes):
    o = _state(c)["orari"]
    o = {**o, "settimana": {**o["settimana"], **(week or {})}, **changes}
    return c.put(f"{API}/impostazioni/orari", json=o)


# ------------------------------------------------------------ accesso
def test_react_ui_served_by_app(app_client):
    r = app_client.get("/amministrazione/orari")
    assert r.status_code == 200 and '<div id="root">' in r.text and "/static/admin/assets/" in r.text
    asset = re.search(r'src="(/static/admin/assets/[^"]+\.js)"', r.text).group(1)
    assert app_client.get(asset).status_code == 200


def test_admin_requires_administrator(app_client):
    assert app_client.get(f"{API}/impostazioni").status_code == 401
    assert app_client.post(f"{API}/accesso", json={"utente": "u", "password": "p"}).status_code == 401   # l'ufficio non basta
    assert app_client.post(f"{API}/accesso", json={"utente": "admin", "password": "no"}).status_code == 401
    _log_in(app_client)
    assert app_client.get(f"{API}/sessione").json()["utente"] == "admin"
    app_client.post(f"{API}/uscita")
    assert app_client.get(f"{API}/impostazioni").status_code == 401


def test_too_many_attempts_block_login(app_client):
    for _ in range(10):
        app_client.post(f"{API}/accesso", json={"utente": "admin", "password": "no"})
    assert app_client.post(f"{API}/accesso", json={"utente": "admin", "password": "admin-pw"}).status_code == 429


def test_admin_closed_without_admin_password(settings, clock, inference_client):
    settings.admin_password = None
    c = TestClient(create_app(settings, now=clock, assistant=AIAssistant("http://x", client=inference_client)))
    r = c.post(f"{API}/accesso", json={"utente": "admin", "password": "admin-pw"})
    assert r.status_code == 403 and "ADMIN_PASSWORD" in r.text
    c.app.state.db.close()


def test_csrf_required_in_admin(app_client):
    _log_in(app_client)
    token = app_client.headers.pop("X-CSRF-Token")
    assert app_client.put(f"{API}/impostazioni/luogo", json={"nome": "X"}).status_code == 403
    app_client.headers["X-CSRF-Token"] = token + "x"
    assert app_client.put(f"{API}/impostazioni/luogo", json={"nome": "X"}).status_code == 403


def test_secrets_never_returned_to_browser(app_client):
    state = _state(app_client)
    assert state["accessi"].get("feed_token") is None and state["pagamenti"]["mypay_password"] is False
    assert "feed" not in json.dumps(state["accessi"])


# ------------------------------------------------------------ luogo
def test_saved_venue_applies_immediately_and_is_logged(app_client):
    r = _save(app_client, "luogo", nome="Palazzetto dello sport", prefisso_codice="pds")
    assert r.status_code == 200, r.text
    assert r.json()["luogo"]["prefisso_codice"] == "PDS" and r.json()["salvate"]["luogo"]["aggiornata_da"] == "admin"
    assert "Palazzetto dello sport" in app_client.get("/").text
    assert app_client.get("/api/v1/spazio").json()["nome"] == "Palazzetto dello sport"
    audit_log = app_client.get(f"{API}/registro").json()
    assert audit_log[0]["sezione"] == "luogo" and audit_log[0]["utente"] == "admin"
    assert "PDS-" in _book_and_pay(app_client).text
    # si torna al .env
    assert app_client.post(f"{API}/impostazioni/luogo/ripristina").status_code == 200
    assert "Campo comunale coperto" in app_client.get("/").text


def test_invalid_venue_not_saved(app_client):
    r = _save(app_client, "luogo", nome="  ", prefisso_codice="G")
    assert r.status_code == 422 and "obbligatorio" in r.json()["errore"]
    assert "Campo comunale coperto" in app_client.get("/").text


# ------------------------------------------------------------ orari
def _days(c, from_="2026-11-09", n=10):
    return {g["data"]: g for g in c.get(f"/api/v1/disponibilita?dal={from_}&giorni={n}").json()}


def test_time_bands_per_weekday(app_client):
    r = _save_schedule(app_client, {"lun": "9-13, 15:30-18:30", "mar": "", "sab": "08:30-10:30"}, durata_min="60")
    assert r.status_code == 200, r.text
    assert r.json()["orari"]["settimana"]["lun"] == "09:00-13:00, 15:30-18:30"   # normalizzato
    g = _days(app_client)
    assert [s["ora"] for s in g["2026-11-16"]["slot"]] == ["09:00", "10:00", "11:00", "12:00", "15:30", "16:30", "17:30"]
    assert g["2026-11-10"]["slot"] == []                                    # martedì chiuso
    assert [s["ora"] for s in g["2026-11-14"]["slot"]] == ["08:30", "09:30"]
    assert "lun 09:00–13:00, 15:30–18:30" in app_client.get("/api/v1/spazio").json()["orario"]


def test_period_and_extraordinary_closure(app_client):
    week = {**_state(app_client)["orari"]["settimana"], "lun": "10-12", "ven": ""}
    r = _save_schedule(app_client, periodi=[{"nome": "Natale", "dal": "10/11", "al": "06/01", "settimana": week}],
                     chiusure=[{"dal": "2026-11-11", "al": "2026-11-12", "motivo": "Lavori al tetto"}])
    assert r.status_code == 200, r.text
    g = _days(app_client)
    assert [s["ora"] for s in g["2026-11-09"]["slot"]][0] == "15:00"        # prima del periodo
    assert [s["ora"] for s in g["2026-11-16"]["slot"]] == ["10:00", "11:00"]   # nel periodo
    assert g["2026-11-13"]["slot"] == []                                    # venerdì chiuso nel periodo
    assert g["2026-11-11"]["chiusura"] == "Lavori al tetto" and g["2026-11-11"]["slot"] == []
    assert "Chiuso: Lavori al tetto" in app_client.get("/?dal=2026-11-11").text
    # eliminare chiusura e periodo
    r = _save_schedule(app_client, periodi=[], chiusure=[])
    assert r.status_code == 200 and _days(app_client)["2026-11-11"]["chiusura"] is None


@pytest.mark.parametrize("change,message", [
    ({"settimana": {"lun": "22-15"}}, "apertura"), ({"settimana": {"lun": "mattina"}}, "intervalli"),
    ({"settimana": {"lun": "9-9:30"}}, "più corta"), ({"durata_min": "5"}, "Durata"),
    ({"festivi_extra": "26 maggio"}, "GG/MM"), ({"periodi": [{"dal": "31/02", "al": "01/03", "settimana": {}}]}, "GG/MM"),
    ({"chiusure": [{"dal": "2026-12-10", "al": "2026-12-01"}]}, "prima")])
def test_invalid_schedule(app_client, change, message):
    r = _save_schedule(app_client, change.pop("settimana", None), **change)
    assert r.status_code == 422 and message in r.json()["errore"]


def test_schedule_change_flags_off_schedule_bookings(app_client):
    _book_and_pay(app_client)                                             # venerdì 13 alle 20
    r = _save_schedule(app_client, {"ven": "15-19"})
    assert r.status_code == 200
    outside = r.json()["fuori_calendario"]
    assert len(outside) == 1 and outside[0]["codice"].startswith("GDC-") and "cf" not in outside[0]
    assert "fuori dall'orario in vigore" in app_client.get("/ufficio", auth=("u", "p")).text
    assert "20:00" not in [s["ora"] for s in _days(app_client)["2026-11-13"]["slot"]]


# ------------------------------------------------------------ attività e tariffe
def test_fees_and_new_activity(app_client):
    a = _state(app_client)["attivita"]
    items = a["elenco"]
    items[0]["tariffa_cent"] = 4550
    items[1]["attiva"] = False
    items.append({"codice": "pallavolo", "nome": "Pallavolo", "tariffa_cent": 3000, "giocatori": "12", "preparazione": "", "attiva": True})
    r = app_client.put(f"{API}/impostazioni/attivita", json={"fonte_tariffe": "D.G.C. n. 1/2027", "elenco": items})
    assert r.status_code == 200, r.text
    info = app_client.get("/api/v1/spazio").json()
    fees = {a["codice"]: a["tariffa_cent"] for a in info["attivita"]}
    assert fees == {"calcetto": 4550, "tennis_doppio": 2000, "pallavolo": 3000}
    assert info["fonte_tariffe"] == "D.G.C. n. 1/2027"
    home = app_client.get("/?attivita=pallavolo").text
    assert "Pallavolo" in home and "45,50" in home
    _book_and_pay(app_client, activity="pallavolo")
    p = app_client.app.state.service.items()[0]
    assert p["attivita"] == "pallavolo" and p["importo_cent"] == 3000


def test_existing_activities_cannot_be_deleted(app_client):
    a = _state(app_client)["attivita"]
    r = app_client.put(f"{API}/impostazioni/attivita", json={**a, "elenco": a["elenco"][:1]})
    assert r.status_code == 422 and "non si eliminano" in r.json()["errore"]
    disabled = [{**x, "attiva": False} for x in a["elenco"]]
    r = app_client.put(f"{API}/impostazioni/attivita", json={**a, "elenco": disabled})
    assert r.status_code == 422 and "almeno una" in r.json()["errore"]
    r = app_client.put(f"{API}/impostazioni/attivita", json={**a, "elenco": a["elenco"] + [
        {"codice": "Blocco!", "nome": "x", "tariffa_cent": 1, "attiva": True}]})
    assert r.status_code == 422 and "codice non valido" in r.json()["errore"]


# ------------------------------------------------------------ pagamenti
def test_pagopa_credentials_encrypted_never_shown(app_client):
    r = _save(app_client, "pagamenti", backend="mypay", mypay_endpoint="https://mypay.example.it/sil",
               mypay_ipa_ente="c_e038", mypay_tipo_dovuto="IMPIANTI_SPORTIVI", mypay_password="Segreto-SIL-123")
    assert r.status_code == 200, r.text
    assert "Segreto-SIL-123" not in r.text and r.json()["pagamenti"]["mypay_password"] is True
    raw = json.dumps(app_client.app.state.db.query("SELECT valori FROM impostazioni WHERE sezione='pagamenti'"))
    assert "Segreto-SIL-123" not in raw and "enc:v1:" in raw
    assert "Segreto-SIL-123" not in app_client.get(f"{API}/impostazioni").text
    assert "Segreto-SIL-123" not in app_client.get(f"{API}/registro").text
    cfg = app_client.app.state.config
    assert cfg.payments["mypay_password"] == "Segreto-SIL-123"
    # campo vuoto: la password resta
    assert _save(app_client, "pagamenti", mypay_ipa_ente="c_e039", mypay_password="").status_code == 200
    assert cfg.payments["mypay_password"] == "Segreto-SIL-123" and cfg.payments["mypay_ipa_ente"] == "c_e039"
    # con pagoPA reale la pagina di pagamento simulata non esiste più
    assert app_client.get("/pagopa-simulato/RF00?ritorno=x").status_code == 404
    assert "Pagamenti simulati" not in app_client.get("/").text


def test_mypay_requires_credentials(app_client):
    r = _save(app_client, "pagamenti", backend="mypay", mypay_endpoint="http://insicuro.example.it")
    assert r.status_code == 422 and "https" in r.json()["errore"]
    r = _save(app_client, "pagamenti", backend="mypay", mypay_endpoint="https://mypay.example.it",
               mypay_ipa_ente="c_e038", mypay_tipo_dovuto="X", mypay_password="")
    assert r.status_code == 422 and "password SIL" in r.json()["errore"]


def test_minutes_to_pay(app_client, clock):
    assert _save(app_client, "pagamenti", ttl_attesa_min="30", mypay_password="").status_code == 200
    assert app_client.app.state.service.ttl.total_seconds() == 30 * 60


def test_secrets_unreadable_with_another_key():
    c1, c2 = SecretBox("chiave-uno"), SecretBox("chiave-due")
    ciphertext = c1.encrypt("ciao")
    assert c1.decrypt(ciphertext) == "ciao" and c2.decrypt(ciphertext) is None and c1.decrypt("in chiaro") is None


# ------------------------------------------------------------ accessi
def _staff_access(c, **changes):
    a = _state(c)["accessi"]
    return c.put(f"{API}/impostazioni/accessi", json={"admin_user": a["admin_user"], "ufficio_user": a["ufficio_user"], **changes})


def test_staff_passwords(app_client):
    assert hash_password("x") != hash_password("x") and verify_password("x", hash_password("x"))
    r = _staff_access(app_client, ufficio_password="nuova-password-ufficio", custode_password="corta")
    assert r.status_code == 422 and "almeno 12" in r.json()["errore"]
    r = _staff_access(app_client, ufficio_user="sport.ufficio", ufficio_password="nuova-password-ufficio")
    assert r.status_code == 200, r.text
    assert app_client.get("/ufficio", auth=("u", "p")).status_code == 401
    assert app_client.get("/ufficio", auth=("sport.ufficio", "nuova-password-ufficio")).status_code == 200
    assert app_client.get("/custode", auth=("custode", "c")).status_code == 200   # invariata
    raw = json.dumps(app_client.app.state.db.query("SELECT valori FROM impostazioni WHERE sezione='accessi'"))
    assert "nuova-password-ufficio" not in raw and "scrypt$" in raw


def test_new_admin_password(app_client, settings, clock, inference_client):
    assert _staff_access(app_client, admin_password="nuova-password-admin").status_code == 200
    assert app_client.get(f"{API}/impostazioni").status_code == 200       # la sessione di chi l'ha cambiata resta
    other = TestClient(app_client.app)
    assert other.post(f"{API}/accesso", json={"utente": "admin", "password": "admin-pw"}).status_code == 401
    _log_in(other, password="nuova-password-admin")


def test_new_calendar_address(app_client):
    assert app_client.get("/ufficio/agenda.ics?token=feed").status_code == 200
    assert _staff_access(app_client, rigenera_feed=True).status_code == 200
    assert app_client.get("/ufficio/agenda.ics?token=feed").status_code == 404
    new = app_client.app.state.config.access["feed_token"]
    assert app_client.get(f"/ufficio/agenda.ics?token={new}").status_code == 200
    assert new in app_client.get("/ufficio", auth=("u", "p")).text


# ------------------------------------------------------------ più istanze
def test_other_instances_reload_settings(app_client, settings, clock, inference_client):
    other = TestClient(create_app(settings, now=clock, assistant=AIAssistant("http://x", client=inference_client)))
    assert _save(app_client, "luogo", nome="Piscina comunale").status_code == 200
    other.app.state.config.CHECK_INTERVAL = 0
    assert "Piscina comunale" in other.get("/").text
    other.app.state.db.close()


# ------------------------------------------------------------ SPID/CIE con OpenID Connect
ISSUER = "https://login.comune.example.it"


def _jwt(payload: dict) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(payload)}.firma"


class FakeGateway:
    """Gateway OIDC SPID/CIE simulato: discovery, token e userinfo."""

    def __init__(self):
        self.nonce = None
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                                             "token_endpoint": f"{ISSUER}/token", "userinfo_endpoint": f"{ISSUER}/userinfo"})
        if req.url.path == "/token":
            body = parse_qs(req.content.decode())
            assert body["code"] == ["codice-ok"] and body["code_verifier"][0]
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer", "id_token": _jwt(
                {"iss": ISSUER, "aud": "spazio-comune", "sub": "u1", "nonce": self.nonce, "exp": 4_000_000_000,
                 "acr": "https://www.spid.gov.it/SpidL2"})})
        if req.url.path == "/userinfo":
            assert req.headers["authorization"] == "Bearer at"
            return httpx.Response(200, json={"sub": "u1", "https://attributes.eid.gov.it/fiscal_number": "TINIT-BNCNNA90B41E038Y",
                                             "given_name": "Anna", "family_name": "Bianchi", "email": "anna@example.org"})
        return httpx.Response(404)


@pytest.fixture
def gateway(monkeypatch):
    g = FakeGateway()

    class OIDCWithFakeGateway(OIDCIdentity):
        def __init__(self, cfg, redirect_uri, client=None):
            super().__init__(cfg, redirect_uri, httpx.Client(transport=httpx.MockTransport(g)))

    monkeypatch.setattr(main_module, "OIDCIdentity", OIDCWithFakeGateway)
    monkeypatch.setattr("venue_booking.admin.OIDCIdentity", OIDCWithFakeGateway)
    return g


@pytest.fixture
def oidc_client(settings, clock, inference_client, gateway):
    """App con il gateway SPID/CIE configurato nel .env (variabili OIDC_*)."""
    settings.identity_backend = "oidc"
    settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret = ISSUER, "spazio-comune", "client-secret-123"
    settings.oidc_redirect_uri = "https://prenota.comune.example.it/auth/oidc/callback"
    app = create_app(settings, now=clock, assistant=AIAssistant("http://x", client=inference_client))
    yield TestClient(app)
    app.state.db.close()


def test_spid_cie_login_with_oidc(oidc_client, gateway):
    c = oidc_client
    assert c.get("/auth/simulato?ritorno=/").status_code == 404   # niente più utente di prova
    assert "Entra con SPID o CIE" in c.get("/auth/login").text
    r = c.get("/auth/oidc/avvia?ritorno=/mie-prenotazioni", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"{ISSUER}/authorize?")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["spazio-comune"] and q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["https://prenota.comune.example.it/auth/oidc/callback"]   # OIDC_REDIRECT_URI
    gateway.nonce = q["nonce"][0]
    r = c.get(f"/auth/oidc/callback?code=codice-ok&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/mie-prenotazioni"
    assert "Anna Bianchi" in c.get("/mie-prenotazioni").text
    token_request = next(x for x in gateway.requests if x.url.path == "/token")
    assert parse_qs(token_request.content.decode())["redirect_uri"] == ["https://prenota.comune.example.it/auth/oidc/callback"]
    # lo stesso state non si riusa
    r = c.get(f"/auth/oidc/callback?code=codice-ok&state={q['state'][0]}")
    assert r.status_code == 400 and "scaduta" in r.text


def test_oidc_rejects_wrong_state_and_nonce(oidc_client, gateway):
    c = oidc_client
    c.get("/auth/oidc/avvia", follow_redirects=False)
    assert c.get("/auth/oidc/callback?code=codice-ok&state=altro").status_code == 400
    r = c.get("/auth/oidc/avvia", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    gateway.nonce = "nonce-di-un-altro"
    r = c.get(f"/auth/oidc/callback?code=codice-ok&state={q['state'][0]}")
    assert r.status_code == 400 and "nonce" in r.text
    assert c.get("/mie-prenotazioni", follow_redirects=False).status_code == 303   # non autenticato


def test_identity_read_only_in_admin(oidc_client, gateway):
    c = oidc_client
    state = _state(c)["identita"]
    assert state["backend"] == "oidc" and state["oidc_issuer"] == ISSUER and state["oidc_client_secret"] is True
    assert state["redirect_uri"] == "https://prenota.comune.example.it/auth/oidc/callback"
    assert "client-secret-123" not in c.get(f"{API}/impostazioni").text
    r = c.put(f"{API}/impostazioni/identita", json={"backend": "mock"})
    assert r.status_code == 409 and ".env" in r.json()["errore"]
    r = c.post(f"{API}/identita/verifica")
    assert r.status_code == 200 and r.json()["token_endpoint"] == f"{ISSUER}/token"


def test_redirect_uri_defaults_to_base_url(settings, clock, inference_client, gateway):
    settings.identity_backend, settings.base_url = "oidc", "https://prenota.example.it"
    settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret = ISSUER, "x", "y"
    app = create_app(settings, now=clock, assistant=AIAssistant("http://x", client=inference_client))
    r = TestClient(app).get("/auth/oidc/avvia", follow_redirects=False)
    assert parse_qs(urlparse(r.headers["location"]).query)["redirect_uri"] == ["https://prenota.example.it/auth/oidc/callback"]
    app.state.db.close()


@pytest.mark.parametrize("change,message", [
    ({"oidc_issuer": ""}, "OIDC_ISSUER"), ({"oidc_client_secret": ""}, "OIDC_CLIENT_SECRET"),
    ({"oidc_issuer": "http://login.example.it"}, "https"), ({"oidc_redirect_uri": "http://prenota.example.it/cb"}, "OIDC_REDIRECT_URI"),
    ({"oidc_scope": "profile"}, "openid"), ({"identity_backend": "spid"}, "IDENTITY_BACKEND")])
def test_invalid_oidc_env_stops_startup(settings, clock, change, message):
    settings.identity_backend, settings.base_url = "oidc", "https://prenota.example.it"
    settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret = ISSUER, "x", "y"
    for k, v in change.items():
        setattr(settings, k, v)
    with pytest.raises(RuntimeError, match=message):
        create_app(settings, now=clock)


# ------------------------------------------------------------ logo e intestazione
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_logo_in_header(app_client):
    home = app_client.get("/").text
    assert '<div class="it-brand-title">Comune di Gioia del Colle</div>' in home and "venue-logo" not in home
    _log_in(app_client)
    r = app_client.put(f"{API}/logo", content=PNG, headers={"Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    url = r.json()["meta"]["logo"]
    assert url.startswith("/logo?v=")
    home = app_client.get("/").text
    assert f'src="{url}"' in home and 'it-brand-tagline">Campo comunale coperto di via Benagiano' in home
    logo = app_client.get(url)
    assert logo.content == PNG and logo.headers["content-type"] == "image/png"
    assert logo.headers["x-content-type-options"] == "nosniff"
    assert app_client.get(f"{API}/registro").json()[0]["sezione"] == "logo"
    # nome del Comune e del luogo dal back-office nell'header
    _save(app_client, "luogo", comune="Comune di Paese", nome="Palestra Rossi")
    home = app_client.get("/").text
    assert "it-brand-title\">Comune di Paese" in home and "it-brand-tagline\">Palestra Rossi" in home
    assert app_client.delete(f"{API}/logo").json()["meta"]["logo"] is None
    assert app_client.get("/logo").status_code == 404 and "venue-logo" not in app_client.get("/").text


@pytest.mark.parametrize("content,message", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "formato"),
    (b"GIF89a" + b"\x00" * 10, "formato"), (PNG + b"\x00" * 600_000, "troppo grande"), (b"", "nessun file")])
def test_logo_rejected(app_client, content, message):
    _log_in(app_client)
    r = app_client.put(f"{API}/logo", content=content, headers={"Content-Type": "image/svg+xml"})
    assert r.status_code == 422 and message in r.json()["errore"]


def test_logo_admin_only(app_client):
    assert app_client.put(f"{API}/logo", content=PNG).status_code == 401


# ------------------------------------------------------------ fasce tariffarie
EVENING = {"nome": "Serale con illuminazione", "dalle": "19:00", "alle": "24:00", "giorni": [],
           "tariffe": {"calcetto": 5000, "tennis_singolo": 1500}}


def _save_fee_bands(c, bands):
    act = _state(c)["attivita"]
    return c.put(f"{API}/impostazioni/attivita", json={**act, "fasce_tariffarie": bands})


def test_fee_bands_set_the_payment_amount(app_client):
    r = _save_fee_bands(app_client, [EVENING, {"nome": "Sabato mattina", "dalle": "9", "alle": "13", "giorni": ["sab"],
                                               "tariffe": {"calcetto": 3000}}])
    assert r.status_code == 200, r.text
    assert r.json()["attivita"]["fasce_tariffarie"][0]["dalle"] == "19:00"
    service = app_client.app.state.service
    _book_and_pay(app_client, start="2026-11-13T20:00:00+01:00")          # venerdì sera: fascia serale
    _book_and_pay(app_client, start="2026-11-13T15:00:00+01:00")          # pomeriggio: tariffa base
    _book_and_pay(app_client, start="2026-11-13T19:00:00+01:00", activity="tennis_doppio")   # nessuna tariffa in fascia
    fees = {p["inizio"][11:16] + p["attivita"]: p["importo_cent"] for p in service.items()}
    assert fees == {"20:00calcetto": 5000, "15:00calcetto": 4000, "19:00tennis_doppio": 2000}
    home = app_client.get("/?attivita=calcetto&dal=2026-11-13").text
    assert "Serale con illuminazione (19:00–24:00)" in home and "€ 50,00" in home
    assert "ore 21:00, Calcetto (calcio a 5), € 50,00" in home and "ore 16:00, Calcetto (calcio a 5), € 40,00" in home
    info = app_client.get("/api/v1/spazio").json()["fasce_tariffarie"]
    assert info[0]["tariffe_cent"] == {"calcetto": 5000, "tennis_singolo": 1500} and info[1]["giorni"] == ["sab"]


def test_summary_shows_band_fee(app_client):
    _save_fee_bands(app_client, [EVENING])
    app_client.get("/auth/simulato?ritorno=/")
    r = app_client.get("/prenota", params={"inizio": "2026-11-13T21:00:00+01:00", "attivita": "calcetto"})
    assert "€ 50,00" in r.text and "tariffa Serale con illuminazione" in r.text


@pytest.mark.parametrize("band,message", [
    ({**EVENING, "nome": ""}, "nome"), ({**EVENING, "dalle": "22", "alle": "20"}, "prima"),
    ({**EVENING, "giorni": ["lunedi"]}, "giorni"), ({**EVENING, "tariffe": {"nuoto": 100}}, "sconosciuta"),
    ({**EVENING, "tariffe": {}}, "almeno"), ({**EVENING, "alle": "25"}, "24:00")])
def test_invalid_fee_bands(app_client, band, message):
    r = _save_fee_bands(app_client, [band])
    assert r.status_code == 422 and message in r.json()["errore"]
