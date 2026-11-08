import re
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from prenota.ai import AssistenteIA
from prenota.main import create_app

VEN_20 = "2026-11-13T20:00:00+01:00"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def _login(c):
    c.get("/auth/simulato?ritorno=/")


def _prenota_e_paga(c, inizio=VEN_20, attivita="calcetto"):
    _login(c)
    r = c.get("/prenota", params={"inizio": inizio, "attivita": attivita})
    assert r.status_code == 200
    r = c.post("/prenota", data={"inizio": inizio, "attivita": attivita, "csrf_token": _csrf(r.text)},
               follow_redirects=False)
    assert r.status_code == 303 and "/pagopa-simulato/" in r.headers["location"]
    pagina = c.get(r.headers["location"])
    ritorno = parse_qs(urlparse(r.headers["location"]).query)["ritorno"][0]
    r = c.post(urlparse(r.headers["location"]).path,
               data={"ritorno": ritorno, "csrf_token": _csrf(pagina.text)}, follow_redirects=True)
    return r


def test_home_bootstrap_italia_e_calendario(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "/static/bootstrap-italia/dist/css/bootstrap-italia.min.css" in r.text
    assert 'lang="it"' in r.text and "Vai ai contenuti" in r.text
    assert r.text.count('class="btn btn-outline-primary btn-sm w-100 slot"') == 6 * 7  # lun–sab, 15:00–21:00
    assert "€ 40,00" in r.text or "40,00" in r.text


def test_asset_statici_serviti(app_client):
    assert app_client.get("/static/bootstrap-italia/dist/css/bootstrap-italia.min.css").status_code == 200
    assert app_client.get("/static/bootstrap-italia/dist/svg/sprites.svg").status_code == 200


def test_flusso_completo_cittadino(app_client):
    r = _prenota_e_paga(app_client)
    assert r.status_code == 200
    assert "Prenotazione confermata" in r.text and "<svg" in r.text
    codice = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    ics = app_client.get(f"/prenotazione/{codice}/calendario.ics")
    assert ics.headers["content-type"].startswith("text/calendar")
    mie = app_client.get("/mie-prenotazioni")
    assert codice in mie.text and "Confermata" in mie.text
    home = app_client.get("/?attivita=calcetto&dal=2026-11-13")
    assert "20:00 · occupato" in home.text


def test_prenota_richiede_login(app_client):
    r = app_client.get("/prenota", params={"inizio": VEN_20, "attivita": "calcetto"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/auth/login")


def test_csrf_obbligatorio(app_client):
    _login(app_client)
    r = app_client.post("/prenota", data={"inizio": VEN_20, "attivita": "calcetto"})
    assert r.status_code == 400


def test_open_redirect_bloccato(app_client):
    r = app_client.get("/auth/simulato?ritorno=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"


def test_ticket_visibile_solo_al_titolare(app_client, settings, orologio, inference_client):
    r = _prenota_e_paga(app_client)
    codice = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    altro = TestClient(app_client.app)
    assert altro.get(f"/prenotazione/{codice}").status_code == 404


def test_slot_occupato_mostra_errore_chiaro(app_client):
    _prenota_e_paga(app_client)
    r = app_client.get("/prenota", params={"inizio": VEN_20, "attivita": "calcetto"})
    r = app_client.post("/prenota", data={"inizio": VEN_20, "attivita": "calcetto", "csrf_token": _csrf(r.text)})
    assert r.status_code == 409 and "appena stato prenotato" in r.text


def test_assistente_propone_orari(app_client):
    home = app_client.get("/")
    r = app_client.post("/assistente", data={"testo": "calcetto venerdì sera alle 20", "csrf_token": _csrf(home.text)})
    assert r.status_code == 200
    assert "Venerdì 13 novembre 2026, ore 20:00" in r.text
    assert "intelligenza artificiale" in r.text


def test_assistente_propone_alternative_se_occupato(app_client):
    _prenota_e_paga(app_client)
    home = app_client.get("/")
    r = app_client.post("/assistente", data={"testo": "calcetto venerdì alle 20", "csrf_token": _csrf(home.text)})
    assert "ore 19:00" in r.text and "ore 21:00" in r.text and "Venerdì 13 novembre 2026, ore 20:00" not in r.text


def test_faq(app_client):
    home = app_client.get("/")
    r = app_client.post("/faq", data={"domanda": "quanto costa il tennis doppio?", "csrf_token": _csrf(home.text)})
    assert "20,00" in r.text and "tariffe" in r.text


def test_degrado_senza_server_ia(settings, orologio):
    ia = AssistenteIA("http://127.0.0.1:9", timeout=0.2)
    c = TestClient(create_app(settings, adesso=orologio, assistente=ia))
    home = c.get("/")
    r = c.post("/assistente", data={"testo": "calcetto domani", "csrf_token": _csrf(home.text)})
    assert r.status_code == 200 and "non è disponibile" in r.text


def test_ia_disattivata_nasconde_assistente(settings, orologio):
    c = TestClient(create_app(settings, adesso=orologio, assistente=AssistenteIA(None)))
    assert "Dimmi cosa vuoi fare" not in c.get("/").text


def test_ufficio_protetto_e_operativo(app_client):
    assert app_client.get("/ufficio").status_code == 401
    _prenota_e_paga(app_client)
    r = app_client.get("/ufficio", auth=("u", "p"))
    assert r.status_code == 200 and "€ 40,00" in r.text
    csv = app_client.get("/ufficio/export.csv", auth=("u", "p"))
    assert csv.text.startswith("codice;") and "CONFERMATA" in csv.text
    assert app_client.get("/ufficio/agenda.ics?token=sbagliato").status_code == 404
    assert "BEGIN:VEVENT" in app_client.get("/ufficio/agenda.ics?token=feed").text
    r = app_client.post("/ufficio/blocca", auth=("u", "p"), follow_redirects=False,
                        data={"inizio": "2026-11-14T16:00:00+01:00", "motivo": "Torneo scuole", "csrf_token": _csrf(r.text)})
    assert r.status_code == 303
    assert "16:00 · riservato" in app_client.get("/?dal=2026-11-14").text


def test_custode_check_in(app_client, orologio):
    r = _prenota_e_paga(app_client, inizio="2026-11-09T15:00:00+01:00")
    codice = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    token = app_client.app.state.servizio.token_ticket(codice)
    assert app_client.get(f"/custode?token={token}").status_code == 401
    orologio.avanza(hours=5)
    r = app_client.get(f"/custode?token={token}", auth=("custode", "c"))
    assert "Ingresso registrato" in r.text
    r = app_client.get(f"/custode?token={token}", auth=("custode", "c"))
    assert "già utilizzato" in r.text


def test_api_pubbliche(app_client):
    spazio = app_client.get("/api/v1/spazio").json()
    assert {a["codice"] for a in spazio["attivita"]} == {"calcetto", "tennis_singolo", "tennis_doppio"}
    disp = app_client.get("/api/v1/disponibilita?giorni=3").json()
    assert len(disp) == 3
    assert app_client.get("/api/v1/health").json()["ia"] is True
