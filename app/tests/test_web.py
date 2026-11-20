import re
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from venue_booking.ai import AIAssistant
from venue_booking.main import create_app

FRI_20 = "2026-11-13T20:00:00+01:00"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def _login(c):
    c.get("/auth/mock?return_url=/")


def _book_and_pay(c, start=FRI_20, activity="calcetto"):
    _login(c)
    r = c.get("/book", params={"start": start, "activity": activity})
    assert r.status_code == 200
    r = c.post("/book", data={"start": start, "activity": activity, "csrf_token": _csrf(r.text)},
               follow_redirects=False)
    assert r.status_code == 303 and "/pagopa-mock/" in r.headers["location"]
    page_html = c.get(r.headers["location"])
    return_url = parse_qs(urlparse(r.headers["location"]).query)["return_url"][0]
    r = c.post(urlparse(r.headers["location"]).path,
               data={"return_url": return_url, "csrf_token": _csrf(page_html.text)}, follow_redirects=True)
    return r


def test_home_bootstrap_italia_and_calendar(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "/static/bootstrap-italia/dist/css/bootstrap-italia.min.css" in r.text
    assert 'lang="it"' in r.text and "Vai ai contenuti" in r.text
    assert r.text.count('class="btn btn-sm w-100 slot slot-free"') == 6 * 7  # lun–sab, 15:00–21:00
    assert "€ 40,00" in r.text or "40,00" in r.text


def test_static_assets_served(app_client):
    assert app_client.get("/static/bootstrap-italia/dist/css/bootstrap-italia.min.css").status_code == 200
    assert app_client.get("/static/bootstrap-italia/dist/svg/sprites.svg").status_code == 200


def test_full_citizen_flow(app_client):
    r = _book_and_pay(app_client)
    assert r.status_code == 200
    assert "Prenotazione confermata" in r.text and "<svg" in r.text
    code = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    ics = app_client.get(f"/booking/{code}/calendar.ics")
    assert ics.headers["content-type"].startswith("text/calendar")
    mine = app_client.get("/my-bookings")
    assert code in mine.text and "Confermata" in mine.text
    home = app_client.get("/?activity=calcetto&from=2026-11-13")
    assert "20:00<span class=\"visually-hidden\">, occupato</span>" in home.text and "slot-taken" in home.text


def test_booking_requires_login(app_client):
    r = app_client.get("/book", params={"start": FRI_20, "activity": "calcetto"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/auth/login")


def test_csrf_required(app_client):
    _login(app_client)
    r = app_client.post("/book", data={"start": FRI_20, "activity": "calcetto"})
    assert r.status_code == 400


def test_open_redirect_blocked(app_client):
    r = app_client.get("/auth/mock?return_url=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"


def test_ticket_visible_only_to_owner(app_client, settings, clock, inference_client):
    r = _book_and_pay(app_client)
    code = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    other = TestClient(app_client.app)
    assert other.get(f"/booking/{code}").status_code == 404


def test_taken_slot_shows_clear_error(app_client):
    _book_and_pay(app_client)
    r = app_client.get("/book", params={"start": FRI_20, "activity": "calcetto"})
    r = app_client.post("/book", data={"start": FRI_20, "activity": "calcetto", "csrf_token": _csrf(r.text)})
    assert r.status_code == 409 and "appena stato prenotato" in r.text


def test_assistant_proposes_times(app_client):
    home = app_client.get("/")
    r = app_client.post("/assistant", data={"text": "calcetto venerdì sera alle 20", "csrf_token": _csrf(home.text)})
    assert r.status_code == 200
    assert "Venerdì 13 novembre 2026, ore 20:00" in r.text
    assert "intelligenza artificiale" in r.text


def test_assistant_proposes_alternatives_when_taken(app_client):
    _book_and_pay(app_client)
    home = app_client.get("/")
    r = app_client.post("/assistant", data={"text": "calcetto venerdì alle 20", "csrf_token": _csrf(home.text)})
    assert "ore 19:00" in r.text and "ore 21:00" in r.text and "Venerdì 13 novembre 2026, ore 20:00" not in r.text


def test_faq(app_client):
    home = app_client.get("/")
    r = app_client.post("/faq", data={"question": "quanto costa il tennis doppio?", "csrf_token": _csrf(home.text)})
    assert "20,00" in r.text and "tariffe" in r.text


def test_degrades_without_ai_server(settings, clock):
    ai = AIAssistant("http://127.0.0.1:9", timeout=0.2)
    c = TestClient(create_app(settings, now=clock, assistant=ai))
    home = c.get("/")
    r = c.post("/assistant", data={"text": "calcetto domani", "csrf_token": _csrf(home.text)})
    assert r.status_code == 200 and "non è disponibile" in r.text


def test_ai_disabled_hides_assistant(settings, clock):
    c = TestClient(create_app(settings, now=clock, assistant=AIAssistant(None)))
    assert "Dimmi cosa vuoi fare" not in c.get("/").text


def test_office_protected_and_working(app_client):
    assert app_client.get("/backoffice").status_code == 401
    _book_and_pay(app_client)
    r = app_client.get("/backoffice", auth=("u", "p"))
    assert r.status_code == 200 and "€ 40,00" in r.text
    csv = app_client.get("/backoffice/export.csv", auth=("u", "p"))
    assert csv.text.startswith("codice;") and "CONFERMATA" in csv.text
    assert app_client.get("/backoffice/calendar.ics?token=sbagliato").status_code == 404
    assert "BEGIN:VEVENT" in app_client.get("/backoffice/calendar.ics?token=feed").text
    r = app_client.post("/backoffice/block", auth=("u", "p"), follow_redirects=False,
                        data={"start": "2026-11-14T16:00:00+01:00", "reason": "Torneo scuole", "csrf_token": _csrf(r.text)})
    assert r.status_code == 303
    assert "16:00<span class=\"visually-hidden\">, riservato</span>" in app_client.get("/?from=2026-11-14").text


def test_keeper_page_check_in(app_client, clock):
    r = _book_and_pay(app_client, start="2026-11-09T15:00:00+01:00")
    code = re.search(r"GDC-[A-Z2-9]{4}-[A-Z2-9]{4}", r.text).group(0)
    token = app_client.app.state.service.token_ticket(code)
    assert app_client.get(f"/checkin?token={token}").status_code == 401
    clock.advance(hours=5)
    r = app_client.get(f"/checkin?token={token}", auth=("custode", "c"))
    assert "Ingresso registrato" in r.text
    r = app_client.get(f"/checkin?token={token}", auth=("custode", "c"))
    assert "già utilizzato" in r.text


def test_public_api(app_client):
    venue = app_client.get("/api/v1/venue").json()
    assert {a["codice"] for a in venue["attivita"]} == {"calcetto", "tennis_singolo", "tennis_doppio"}
    avail = app_client.get("/api/v1/availability?days=3").json()
    assert len(avail) == 3
    assert app_client.get("/api/v1/health").json()["ia"] is True

