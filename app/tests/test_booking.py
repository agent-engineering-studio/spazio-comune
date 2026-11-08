import pytest

from prenota.adapters.agenda import to_csv, to_ics
from prenota.booking import ErrorePrenotazione

VEN_20 = "2026-11-13T20:00:00+01:00"


def test_calendario_settimanale(servizio):
    giorni = servizio.disponibilita("benagiano", giorni=7)
    assert [g["data"] for g in giorni][0] == "2026-11-09"
    lunedi, domenica = giorni[0], giorni[6]
    assert len(lunedi["slot"]) == 7 and domenica["slot"] == []
    assert lunedi["slot"][0]["ora"] == "15:00" and lunedi["slot"][-1]["ora"] == "21:00"


def test_finestra_di_prenotabilita(servizio):
    giorni = servizio.disponibilita("benagiano", giorni=30)
    assert len(giorni) == 15  # oggi + 14 giorni


def test_prenotazione_e_doppia_prenotazione(servizio, mario, anna):
    p = servizio.prenota("benagiano", "calcetto", VEN_20, mario)
    assert p["stato"] == "ATTESA_PAGAMENTO" and p["importo_cent"] == 4000
    with pytest.raises(ErrorePrenotazione) as e:
        servizio.prenota("benagiano", "tennis_singolo", VEN_20, anna)
    assert e.value.codice_http == 409
    venerdi = next(g for g in servizio.disponibilita("benagiano") if g["data"] == "2026-11-13")
    assert not next(s for s in venerdi["slot"] if s["ora"] == "20:00")["libero"]


def test_attesa_scade_e_libera_lo_slot(servizio, mario, anna, orologio):
    servizio.prenota("benagiano", "calcetto", VEN_20, mario)
    orologio.avanza(minutes=16)
    p = servizio.prenota("benagiano", "calcetto", VEN_20, anna)
    assert p["cognome"] == "Bianchi"


def test_pagamento_conferma_e_pubblica_in_agenda(servizio, mario):
    p = servizio.prenota("benagiano", "tennis_doppio", VEN_20, mario)
    p = servizio.avvia_pagamento(p["codice"], "http://test/esito")
    assert p["iuv"] and p["url_pagamento"]
    assert servizio.verifica_pagamento(p["codice"])["stato"] == "ATTESA_PAGAMENTO"
    servizio.pagamenti.segna_pagato(p["iuv"])
    conf = servizio.verifica_pagamento(p["codice"])
    assert conf["stato"] == "CONFERMATA"
    assert p["codice"] in servizio.agenda.eventi
    assert servizio.verifica_pagamento(p["codice"])["stato"] == "CONFERMATA"  # idempotente


def test_pagamento_tardivo_su_slot_ripreso(servizio, mario, anna, orologio):
    p = servizio.avvia_pagamento(servizio.prenota("benagiano", "calcetto", VEN_20, mario)["codice"], "x")
    orologio.avanza(minutes=20)
    servizio.prenota("benagiano", "calcetto", VEN_20, anna)
    servizio.pagamenti.segna_pagato(p["iuv"])
    with pytest.raises(ErrorePrenotazione, match="rimborso"):
        servizio.verifica_pagamento(p["codice"])


def test_pagamento_tardivo_su_slot_ancora_libero(servizio, mario, orologio):
    p = servizio.avvia_pagamento(servizio.prenota("benagiano", "calcetto", VEN_20, mario)["codice"], "x")
    orologio.avanza(minutes=20)
    servizio.disponibilita("benagiano")  # forza la scadenza
    servizio.pagamenti.segna_pagato(p["iuv"])
    assert servizio.verifica_pagamento(p["codice"])["stato"] == "CONFERMATA"


@pytest.mark.parametrize("inizio, messaggio", [
    ("2026-11-13T20:30:00+01:00", "calendario"),
    ("2026-11-15T20:00:00+01:00", "calendario"),     # domenica chiuso
    ("2026-11-09T09:00:00+01:00", "calendario"),
    ("2026-11-02T20:00:00+01:00", "passato"),
    ("2026-12-01T20:00:00+01:00", "14 giorni"),
    ("non-una-data", "non valido"),
])
def test_orari_non_validi(servizio, mario, inizio, messaggio):
    with pytest.raises(ErrorePrenotazione, match=messaggio):
        servizio.prenota("benagiano", "calcetto", inizio, mario)


def test_attivita_e_impianto_non_validi(servizio, mario):
    with pytest.raises(ErrorePrenotazione):
        servizio.prenota("benagiano", "nuoto", VEN_20, mario)
    with pytest.raises(ErrorePrenotazione) as e:
        servizio.prenota("stadio", "calcetto", VEN_20, mario)
    assert e.value.codice_http == 404


def _confermata(servizio, cittadino, inizio=VEN_20):
    p = servizio.avvia_pagamento(servizio.prenota("benagiano", "calcetto", inizio, cittadino)["codice"], "x")
    servizio.pagamenti.segna_pagato(p["iuv"])
    return servizio.verifica_pagamento(p["codice"])


def test_annullamento_regola_24_ore(servizio, mario, orologio):
    p = _confermata(servizio, mario, "2026-11-10T15:00:00+01:00")
    orologio.avanza(hours=6)  # mancano 23 ore
    with pytest.raises(ErrorePrenotazione, match="24 ore"):
        servizio.annulla(p["codice"])
    assert servizio.annulla(p["codice"], da_ufficio=True)["stato"] == "ANNULLATA"
    assert p["codice"] not in servizio.agenda.eventi


def test_annullamento_libera_lo_slot(servizio, mario, anna):
    p = _confermata(servizio, mario)
    servizio.annulla(p["codice"])
    assert servizio.prenota("benagiano", "calcetto", VEN_20, anna)["stato"] == "ATTESA_PAGAMENTO"


def test_blocco_ufficio(servizio, mario):
    b = servizio.blocca("benagiano", VEN_20, "Manutenzione impianto luci")
    assert b["stato"] == "BLOCCO" and b["importo_cent"] == 0
    with pytest.raises(ErrorePrenotazione):
        servizio.prenota("benagiano", "calcetto", VEN_20, mario)


def test_conferma_manuale_sportello(servizio, mario):
    p = servizio.prenota("benagiano", "calcetto", VEN_20, mario)
    c = servizio.conferma_manuale(p["codice"], "RICEVUTA-123")
    assert c["stato"] == "CONFERMATA" and c["iuv"] == "RICEVUTA-123"
    with pytest.raises(ErrorePrenotazione):
        servizio.conferma_manuale(p["codice"], "di nuovo")


def test_check_in_custode(servizio, mario, orologio):
    p = _confermata(servizio, mario, "2026-11-09T15:00:00+01:00")
    token = servizio.token_ticket(p["codice"])
    orologio.avanza(hours=4, minutes=55)
    assert servizio.check_in(token)["esito"] == "OK"
    assert servizio.check_in(token)["esito"] == "GIA_REGISTRATA"


def test_check_in_qr_contraffatto_o_fuori_orario(servizio, mario):
    p = _confermata(servizio, mario)
    with pytest.raises(ErrorePrenotazione) as e:
        servizio.check_in(p["codice"] + ".0000000000000000")
    assert e.value.codice_http == 403
    assert servizio.check_in(servizio.token_ticket(p["codice"]))["esito"] == "FUORI_ORARIO"


def test_export_ics_e_csv(servizio, mario):
    p = _confermata(servizio, mario)
    ics = to_ics([p])
    assert "BEGIN:VEVENT" in ics and "DTSTART;TZID=Europe/Rome:20261113T200000" in ics
    assert "Montare porte calcetto" in ics and ics.endswith("\r\n")
    csv = to_csv([p])
    assert csv.splitlines()[0].startswith("codice;impianto") and p["iuv"] in csv
    assert "RSSMRA80A01E038X" not in csv  # il CF non va nell'export per la ragioneria
