import pytest

from venue_booking.adapters.agenda import to_csv, to_ics
from venue_booking.booking import BookingError

FRI_20 = "2026-11-13T20:00:00+01:00"


def test_weekly_calendar(service):
    days = service.availability(days=7)
    assert [g["data"] for g in days][0] == "2026-11-09"
    monday, sunday = days[0], days[6]
    assert len(monday["slot"]) == 7 and sunday["slot"] == []
    assert monday["slot"][0]["ora"] == "15:00" and monday["slot"][-1]["ora"] == "21:00"


def test_booking_window(service):
    days = service.availability(days=30)
    assert len(days) == 15  # oggi + 14 giorni


def test_booking_and_double_booking(service, mario, anna):
    p = service.book("calcetto", FRI_20, mario)
    assert p["stato"] == "ATTESA_PAGAMENTO" and p["importo_cent"] == 4000
    with pytest.raises(BookingError) as e:
        service.book("tennis_singolo", FRI_20, anna)
    assert e.value.http_status == 409
    friday = next(g for g in service.availability() if g["data"] == "2026-11-13")
    assert not next(s for s in friday["slot"] if s["ora"] == "20:00")["libero"]


def test_pending_expires_and_frees_slot(service, mario, anna, clock):
    service.book("calcetto", FRI_20, mario)
    clock.advance(minutes=16)
    p = service.book("calcetto", FRI_20, anna)
    assert p["cognome"] == "Bianchi"


def test_payment_confirms_and_publishes_to_agenda(service, mario):
    p = service.book("tennis_doppio", FRI_20, mario)
    p = service.start_payment(p["codice"], "http://test/esito")
    assert p["iuv"] and p["url_pagamento"]
    assert service.check_payment(p["codice"])["stato"] == "ATTESA_PAGAMENTO"
    service.payments.mark_paid(p["iuv"])
    conf = service.check_payment(p["codice"])
    assert conf["stato"] == "CONFERMATA"
    assert p["codice"] in service.agenda.events
    assert service.check_payment(p["codice"])["stato"] == "CONFERMATA"  # idempotente


def test_late_payment_on_retaken_slot(service, mario, anna, clock):
    p = service.start_payment(service.book("calcetto", FRI_20, mario)["codice"], "x")
    clock.advance(minutes=20)
    service.book("calcetto", FRI_20, anna)
    service.payments.mark_paid(p["iuv"])
    with pytest.raises(BookingError, match="rimborso"):
        service.check_payment(p["codice"])


def test_late_payment_on_still_free_slot(service, mario, clock):
    p = service.start_payment(service.book("calcetto", FRI_20, mario)["codice"], "x")
    clock.advance(minutes=20)
    service.availability()  # forza la scadenza
    service.payments.mark_paid(p["iuv"])
    assert service.check_payment(p["codice"])["stato"] == "CONFERMATA"


@pytest.mark.parametrize("start, message", [
    ("2026-11-13T20:30:00+01:00", "calendario"),
    ("2026-11-15T20:00:00+01:00", "calendario"),     # domenica chiuso
    ("2026-11-09T09:00:00+01:00", "calendario"),
    ("2026-11-02T20:00:00+01:00", "passato"),
    ("2026-12-01T20:00:00+01:00", "14 giorni"),
    ("non-una-data", "non valido"),
])
def test_invalid_schedule(service, mario, start, message):
    with pytest.raises(BookingError, match=message):
        service.book("calcetto", start, mario)


def test_invalid_activity(service, mario):
    with pytest.raises(BookingError, match="Attività non disponibile"):
        service.book("nuoto", FRI_20, mario)


def _confirmed(service, citizen, start=FRI_20):
    p = service.start_payment(service.book("calcetto", start, citizen)["codice"], "x")
    service.payments.mark_paid(p["iuv"])
    return service.check_payment(p["codice"])


def test_cancellation_24_hour_rule(service, mario, clock):
    p = _confirmed(service, mario, "2026-11-10T15:00:00+01:00")
    clock.advance(hours=6)  # mancano 23 ore
    with pytest.raises(BookingError, match="24 ore"):
        service.cancel(p["codice"])
    assert service.cancel(p["codice"], by_office=True)["stato"] == "ANNULLATA"
    assert p["codice"] not in service.agenda.events


def test_cancellation_frees_slot(service, mario, anna):
    p = _confirmed(service, mario)
    service.cancel(p["codice"])
    assert service.book("calcetto", FRI_20, anna)["stato"] == "ATTESA_PAGAMENTO"


def test_office_block(service, mario):
    b = service.block(FRI_20, "Manutenzione impianto luci")
    assert b["stato"] == "BLOCCO" and b["importo_cent"] == 0
    with pytest.raises(BookingError):
        service.book("calcetto", FRI_20, mario)


def test_manual_counter_confirmation(service, mario):
    p = service.book("calcetto", FRI_20, mario)
    c = service.confirm_manually(p["codice"], "RICEVUTA-123")
    assert c["stato"] == "CONFERMATA" and c["iuv"] == "RICEVUTA-123"
    with pytest.raises(BookingError):
        service.confirm_manually(p["codice"], "di nuovo")


def test_keeper_check_in(service, mario, clock):
    p = _confirmed(service, mario, "2026-11-09T15:00:00+01:00")
    token = service.token_ticket(p["codice"])
    clock.advance(hours=4, minutes=55)
    assert service.check_in(token)["esito"] == "OK"
    assert service.check_in(token)["esito"] == "GIA_REGISTRATA"


def test_check_in_forged_qr_or_wrong_time(service, mario):
    p = _confirmed(service, mario)
    with pytest.raises(BookingError) as e:
        service.check_in(p["codice"] + ".0000000000000000")
    assert e.value.http_status == 403
    assert service.check_in(service.token_ticket(p["codice"]))["esito"] == "FUORI_ORARIO"


def test_export_ics_and_csv(service, mario):
    p = _confirmed(service, mario)
    ics = to_ics([p])
    assert "BEGIN:VEVENT" in ics and "DTSTART;TZID=Europe/Rome:20261113T200000" in ics
    assert "Montare porte calcetto" in ics and ics.endswith("\r\n")
    csv = to_csv([p])
    assert csv.splitlines()[0].startswith("codice;attivita") and p["iuv"] in csv
    assert "RSSMRA80A01E038X" not in csv  # il CF non va nell'export per la ragioneria
