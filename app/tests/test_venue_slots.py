"""Un solo luogo configurato da .env, tabella slot con numero di prenotazione, API per agenti."""
import threading
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import IntegrityError

from venue_booking.adapters.identity import Citizen
from venue_booking.ai import AIAssistant
from venue_booking.booking import BookingError
from venue_booking.catalog import Venue, national_holidays, easter
from venue_booking.main import create_app

from test_web import FRI_20, _book_and_pay

GYM_ENV = {
    "SPAZIO_NOME": "Palestra comunale Pinco Pallino", "SPAZIO_INDIRIZZO": "Via Roma 1, 70100 Paese (BA)",
    "COMUNE_NOME": "Comune di Paese", "COMUNE_INDIRIZZO": "Piazza del Municipio 1", "COMUNE_SITO": "https://paese.example.it/",
    "UFFICIO_NOME": "Ufficio Sport di Paese", "SPAZIO_ATTIVITA": "calcetto", "SPAZIO_GIORNI": "lun,mer,ven",
    "SPAZIO_ORARIO": "17-20", "CODICE_PREFISSO": "pae",
}


def _slot(service, start):
    r = service.db.query("SELECT * FROM slot WHERE inizio=%s", (start,))
    return dict(r[0]) if r else None


# ------------------------------------------------------------ configurazione del luogo
def test_venue_from_env():
    s = Venue.from_env(GYM_ENV)
    assert s.name == "Palestra comunale Pinco Pallino" and s.municipality == "Comune di Paese"
    assert s.activities == ("calcetto",) and s.code_prefix == "PAE"
    assert sorted(s.calendar) == [0, 2, 4]
    assert s.calendar[0] == (time(17), time(18), time(19))
    assert "lun, mer, ven" in s.readable_hours


def test_default_venue_without_env():
    s = Venue.from_env({})
    assert s.name.startswith("Campo comunale coperto") and s.activities == ("calcetto", "tennis_singolo", "tennis_doppio")
    assert sorted(s.calendar) == [0, 1, 2, 3, 4, 5] and len(s.calendar[0]) == 7


def test_hours_with_pause_summer_period_and_holidays():
    s = Venue.from_env({"SPAZIO_GIORNI": "lun,mar,mer,gio,ven,sab,dom", "SPAZIO_ORARIO": "9-13,14-22",
                       "SPAZIO_ORARIO_PERIODI": "01/06-15/09=9-13,16-24; 20/12-06/01=15-20",
                       "SPAZIO_FESTIVI_EXTRA": "26/05,14/08/2027"})
    hours_ = lambda g: [t.hour for t in s.slots_on(g)]
    assert hours_(date(2026, 11, 18)) == [9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21]   # pausa 13-14, mai a mezzanotte
    assert hours_(date(2026, 7, 10)) == [9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 23]    # estate: fino alle 24
    assert hours_(date(2027, 1, 4)) == [15, 16, 17, 18, 19] and hours_(date(2027, 1, 7))[0] == 9   # periodo a cavallo dell'anno
    # giorni rossi: chiusi in automatico, anche dentro un periodo
    for holiday in (date(2026, 12, 8), date(2026, 12, 25), date(2026, 8, 15), date(2027, 3, 29), date(2027, 5, 26), date(2027, 8, 14)):
        assert s.is_holiday(holiday) and hours_(holiday) == []
    assert not s.is_holiday(date(2026, 8, 14)) and hours_(date(2026, 8, 14))        # extra valido solo nel 2027
    assert "09:00–13:00, 14:00–22:00" in s.readable_hours and "dal 01/06 al 15/09: 09:00–13:00, 16:00–24:00" in s.readable_hours
    assert s.readable_hours.endswith("nei giorni festivi: chiuso")


def test_national_holidays_and_holiday_hours():
    assert easter(2026) == date(2026, 4, 5) and easter(2027) == date(2027, 3, 28) and easter(2038) == date(2038, 4, 25)
    holidays = national_holidays(2027)
    assert {date(2027, 1, 1), date(2027, 3, 29), date(2027, 4, 25), date(2027, 6, 2), date(2027, 10, 4), date(2027, 12, 26)} <= holidays
    assert len(holidays) == 13 and date(2025, 10, 4) not in national_holidays(2025)
    open_ = Venue.from_env({"SPAZIO_FESTIVI": "aperto"})
    assert len(open_.slots_on(date(2026, 12, 8))) == 7 and "festivi" not in open_.readable_hours
    reduced = Venue.from_env({"SPAZIO_FESTIVI": "16-19"})
    assert [t.hour for t in reduced.slots_on(date(2026, 12, 8))] == [16, 17, 18]
    assert reduced.slots_on(date(2026, 12, 25)) == reduced.slots_on(date(2026, 12, 8))
    assert reduced.slots_on(date(2027, 3, 28)) == ()    # Pasqua è domenica: il luogo è chiuso comunque


def test_holiday_not_bookable(service, clock, mario):
    clock.advance(days=22)   # martedì 1 dicembre 2026
    immaculate = service.availability(date(2026, 12, 8), 1)[0]
    assert immaculate["festivo"] is True and immaculate["slot"] == []
    with pytest.raises(BookingError, match="calendario"):
        service.book("calcetto", "2026-12-08T18:00:00+01:00", mario)
    assert service.availability(date(2026, 12, 9), 1)[0]["festivo"] is False


@pytest.mark.parametrize("key,value", [
    ("SPAZIO_ATTIVITA", "nuoto"), ("SPAZIO_GIORNI", "lunedi,xyz"), ("SPAZIO_ORARIO", "22-15"), ("SPAZIO_ORARIO", "9-25"),
    ("SPAZIO_ORARIO", "mattina"), ("SPAZIO_ORARIO_PERIODI", "estate=9-13"), ("SPAZIO_ORARIO_PERIODI", "31/02-15/09=9-13"),
    ("SPAZIO_FESTIVI", "forse"), ("SPAZIO_FESTIVI_EXTRA", "26 maggio"), ("SPAZIO_FESTIVI_EXTRA", "26/05/27")])
def test_invalid_venue_env(key, value):
    with pytest.raises(ValueError):
        Venue.from_env({key: value})


def test_app_shows_configured_venue(settings, clock, inference_client):
    settings.venue = Venue.from_env(GYM_ENV)
    c = TestClient(create_app(settings, now=clock, assistant=AIAssistant("http://x", client=inference_client)))
    home = c.get("/").text
    assert "Palestra comunale Pinco Pallino" in home and "Via Roma 1, 70100 Paese (BA)" in home
    assert "Comune di Paese" in home and "Gioia del Colle" not in home and "Tennis" not in home
    info = c.get("/api/v1/spazio").json()
    assert info["comune"] == "Comune di Paese" and [a["codice"] for a in info["attivita"]] == ["calcetto"]
    # martedì chiuso, lunedì 17-19
    days = {g["data"]: g for g in c.get("/api/v1/disponibilita?giorni=3").json()}
    assert days["2026-11-10"]["slot"] == [] and [s["ora"] for s in days["2026-11-09"]["slot"]] == ["17:00", "18:00", "19:00"]
    r = _book_and_pay(c, start="2026-11-11T18:00:00+01:00")
    assert "PAE-" in r.text
    c.app.state.db.close()


# ------------------------------------------------------------ tabella slot
def test_booking_code_recorded_on_slot(service, mario):
    p = service.book("calcetto", FRI_20, mario)
    assert _slot(service, FRI_20)["codice_prenotazione"] == p["codice"]
    v = service.db.query("SELECT * FROM v_occupazione WHERE inizio=%s", (FRI_20,))[0]
    assert v["stato"] == "ATTESA_PAGAMENTO" and v["cognome"] == "Rossi"


def test_cancellation_frees_slot(service, mario, anna):
    p = service.book("calcetto", FRI_20, mario)
    service.cancel(p["codice"])
    assert _slot(service, FRI_20)["codice_prenotazione"] is None
    q = service.book("calcetto", FRI_20, anna)
    assert _slot(service, FRI_20)["codice_prenotazione"] == q["codice"]


def test_expiry_frees_slot_and_late_payment_retakes_it(service, clock, mario):
    p = service.start_payment(service.book("calcetto", FRI_20, mario)["codice"], "x")
    clock.advance(minutes=16)
    service.availability()
    assert _slot(service, FRI_20)["codice_prenotazione"] is None
    service.payments.mark_paid(p["iuv"])
    assert service.check_payment(p["codice"])["stato"] == "CONFERMATA"
    assert _slot(service, FRI_20)["codice_prenotazione"] == p["codice"]


def test_office_block_recorded_on_slot(service):
    b = service.block(FRI_20, "Torneo scuole")
    assert _slot(service, FRI_20)["codice_prenotazione"] == b["codice"]


def test_calendar_generates_all_slots(service):
    service.availability(days=7)
    n = service.db.query("SELECT COUNT(*) n, COUNT(codice_prenotazione) occupati FROM slot")[0]
    assert n["n"] == 6 * 7 and n["occupati"] == 0  # lun-sab, 7 slot al giorno


def test_public_states_and_occupancy(service, clock, mario, anna):
    service.confirm_manually(service.book("calcetto", "2026-11-13T19:00:00+01:00", mario)["codice"], "RIF1")
    pending = service.book("tennis_singolo", FRI_20, anna)
    service.block("2026-11-13T21:00:00+01:00", "Manutenzione")
    friday = next(g for g in service.availability() if g["data"] == "2026-11-13")
    states = {s["ora"]: s["stato"] for s in friday["slot"]}
    assert states["19:00"] == "occupato" and states["20:00"] == "in_pagamento" and states["21:00"] == "riservato"
    assert states["18:00"] == "libero" and friday["liberi"] == 4
    assert all("codice" not in s for s in friday["slot"])   # il calendario pubblico non espone i numeri
    occ = next(g for g in service.occupancy() if g["data"] == "2026-11-13")
    by_hour = {s["ora"]: s for s in occ["slot"]}
    assert by_hour["20:00"]["codice"] == pending["codice"] and by_hour["20:00"]["intestatario"] == "Bianchi Anna"
    assert by_hour["21:00"]["intestatario"] == "Manutenzione"
    monday = service.availability()[0]
    assert {s["stato"] for s in monday["slot"]} == {"libero"}  # alle 10 nessuno slot pomeridiano è passato
    clock.advance(hours=7)                                    # ore 17: l'attesa di pagamento è scaduta
    assert [s["stato"] for s in service.availability()[0]["slot"][:3]] == ["passato", "passato", "passato"]
    friday = next(g for g in service.occupancy() if g["data"] == "2026-11-13")
    assert {s["ora"]: s["codice"] for s in friday["slot"]}["20:00"] is None


def test_concurrency_single_winner_per_slot(service):
    """Simulazione: 40 cittadini prenotano insieme lo stesso slot, su connessioni PostgreSQL diverse."""
    results, barrier = [], threading.Barrier(40)

    def probe(i):
        barrier.wait()
        try:
            results.append(service.book("calcetto", FRI_20, Citizen(f"CF{i:014d}", "N", f"C{i}"))["codice"])
        except BookingError as e:
            results.append(e.http_status)

    threads = [threading.Thread(target=probe, args=(i,)) for i in range(40)]
    for f in threads:
        f.start()
    for f in threads:
        f.join()
    winners = [e for e in results if isinstance(e, str)]
    assert len(winners) == 1 and results.count(409) == 39
    assert _slot(service, FRI_20)["codice_prenotazione"] == winners[0]


def test_database_constraints(service, mario):
    """Anche scrivendo direttamente in tabella, il database rifiuta sovrapposizioni e doppioni."""
    service.book("calcetto", FRI_20, mario)
    row = ("X-1", "calcetto", "2026-11-13T20:30:00+01:00", "2026-11-13T21:30:00+01:00", "CONFERMATA", "UFFICIO", 0,
            "2026-11-09T10:00:00+01:00", "2026-11-09T10:00:00+01:00")
    with pytest.raises(IntegrityError, match="ex_nessuna_sovrapposizione"):
        with service.db.tx() as conn:
            conn.execute("INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, importo_cent, "
                         "creata_il, aggiornata_il) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
    other = service.book("calcetto", "2026-11-13T19:00:00+01:00", mario)
    with pytest.raises(IntegrityError):
        with service.db.tx() as conn:
            conn.execute("UPDATE slot SET codice_prenotazione=%s WHERE inizio=%s", (other["codice"], FRI_20))
    types = {r["column_name"]: r["data_type"] for r in service.db.query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=current_schema() AND table_name='slot'")}
    assert types["inizio"] == "timestamp with time zone"


# ------------------------------------------------------------ interfaccia e API
def test_home_shows_busy_slots_with_legend(app_client):
    _book_and_pay(app_client)
    html = app_client.get("/?dal=2026-11-13").text
    assert "20:00 · occupato" in html and "Legenda" in html and "1 impegnato" in html


def test_office_sees_booking_code_in_grid(app_client):
    r = _book_and_pay(app_client)
    code = app_client.app.state.service.items()[0]["codice"]
    html = app_client.get("/ufficio", auth=("u", "p")).text
    assert "Occupazione degli slot" in html and html.count(code) >= 2  # griglia + elenco


def test_api_assistant_faq_and_office(app_client):
    _book_and_pay(app_client)
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto venerdì sera alle 20"}).json()
    assert r["intento"]["data"] == "2026-11-13"
    hours_ = [p["ora"] for p in r["proposte"]]
    assert "20:00" not in hours_ and hours_[0] in ("19:00", "21:00")
    assert r["proposte"][0]["link_prenotazione"].startswith("http://testserver/prenota?inizio=")
    assert app_client.get("/api/v1/faq", params={"domanda": "posso annullare?"}).json()["trovata"] is True
    assert app_client.get("/api/v1/ufficio/occupazione").status_code == 401
    occ = app_client.get("/api/v1/ufficio/occupazione?dal=2026-11-13&giorni=1", auth=("u", "p")).json()
    code = next(s["codice"] for s in occ[0]["slot"] if s["ora"] == "20:00")
    detail = app_client.get(f"/api/v1/ufficio/prenotazioni/{code}", auth=("u", "p")).json()
    assert detail["stato"] == "CONFERMATA" and "cf" not in detail
    assert app_client.get("/api/v1/ufficio/prenotazioni/GDC-XXXX-XXXX", auth=("u", "p")).status_code == 404


def test_assistant_full_day_proposes_next_days(app_client):
    service = app_client.app.state.service
    friday = service.availability(date(2026, 11, 13), 1)[0]
    for s in friday["slot"]:
        service.block(s["inizio"], "Torneo")
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto venerdì sera alle 20"}).json()
    assert r["intento"]["data"] == "2026-11-13" and "giorni successivi" in r["messaggio"]
    assert [(p["data"], p["ora"]) for p in r["proposte"]][:3] == [
        ("2026-11-14", "20:00"), ("2026-11-14", "19:00"), ("2026-11-14", "21:00")]
    # giorno e fascia in cui il campo è chiuso: nessuna proposta, ma con una spiegazione
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto domenica mattina"}).json()
    assert r["proposte"] == [] and "disponibilita" in r["messaggio"]
    # giorno con posti liberi: nessun messaggio
    assert "messaggio" not in app_client.get("/api/v1/assistente", params={"testo": "calcetto sabato sera"}).json()
