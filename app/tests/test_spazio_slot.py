"""Un solo luogo configurato da .env, tabella slot con numero di prenotazione, API per agenti."""
import threading
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import IntegrityError

from prenota.adapters.identity import Cittadino
from prenota.ai import AssistenteIA
from prenota.booking import ErrorePrenotazione
from prenota.catalog import Spazio, festivita_nazionali, pasqua
from prenota.main import create_app

from test_web import VEN_20, _prenota_e_paga

ENV_PALESTRA = {
    "SPAZIO_NOME": "Palestra comunale Pinco Pallino", "SPAZIO_INDIRIZZO": "Via Roma 1, 70100 Paese (BA)",
    "COMUNE_NOME": "Comune di Paese", "COMUNE_INDIRIZZO": "Piazza del Municipio 1", "COMUNE_SITO": "https://paese.example.it/",
    "UFFICIO_NOME": "Ufficio Sport di Paese", "SPAZIO_ATTIVITA": "calcetto", "SPAZIO_GIORNI": "lun,mer,ven",
    "SPAZIO_ORARIO": "17-20", "CODICE_PREFISSO": "pae",
}


def _slot(servizio, inizio):
    r = servizio.db.query("SELECT * FROM slot WHERE inizio=%s", (inizio,))
    return dict(r[0]) if r else None


# ------------------------------------------------------------ configurazione del luogo
def test_spazio_da_env():
    s = Spazio.da_env(ENV_PALESTRA)
    assert s.nome == "Palestra comunale Pinco Pallino" and s.comune == "Comune di Paese"
    assert s.attivita == ("calcetto",) and s.prefisso_codice == "PAE"
    assert sorted(s.calendario) == [0, 2, 4]
    assert s.calendario[0] == (time(17), time(18), time(19))
    assert "lun, mer, ven" in s.orario_leggibile


def test_spazio_predefinito_senza_env():
    s = Spazio.da_env({})
    assert s.nome.startswith("Campo comunale coperto") and s.attivita == ("calcetto", "tennis_singolo", "tennis_doppio")
    assert sorted(s.calendario) == [0, 1, 2, 3, 4, 5] and len(s.calendario[0]) == 7


def test_orario_con_pausa_periodo_estivo_e_festivi():
    s = Spazio.da_env({"SPAZIO_GIORNI": "lun,mar,mer,gio,ven,sab,dom", "SPAZIO_ORARIO": "9-13,14-22",
                       "SPAZIO_ORARIO_PERIODI": "01/06-15/09=9-13,16-24; 20/12-06/01=15-20",
                       "SPAZIO_FESTIVI_EXTRA": "26/05,14/08/2027"})
    ore = lambda g: [t.hour for t in s.orari_del(g)]
    assert ore(date(2026, 11, 18)) == [9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21]   # pausa 13-14, mai a mezzanotte
    assert ore(date(2026, 7, 10)) == [9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 23]    # estate: fino alle 24
    assert ore(date(2027, 1, 4)) == [15, 16, 17, 18, 19] and ore(date(2027, 1, 7))[0] == 9   # periodo a cavallo dell'anno
    # giorni rossi: chiusi in automatico, anche dentro un periodo
    for festa in (date(2026, 12, 8), date(2026, 12, 25), date(2026, 8, 15), date(2027, 3, 29), date(2027, 5, 26), date(2027, 8, 14)):
        assert s.festivo(festa) and ore(festa) == []
    assert not s.festivo(date(2026, 8, 14)) and ore(date(2026, 8, 14))        # extra valido solo nel 2027
    assert "09:00–13:00, 14:00–22:00" in s.orario_leggibile and "dal 01/06 al 15/09: 09:00–13:00, 16:00–24:00" in s.orario_leggibile
    assert s.orario_leggibile.endswith("nei giorni festivi: chiuso")


def test_festivita_nazionali_e_orario_festivo():
    assert pasqua(2026) == date(2026, 4, 5) and pasqua(2027) == date(2027, 3, 28) and pasqua(2038) == date(2038, 4, 25)
    feste = festivita_nazionali(2027)
    assert {date(2027, 1, 1), date(2027, 3, 29), date(2027, 4, 25), date(2027, 6, 2), date(2027, 10, 4), date(2027, 12, 26)} <= feste
    assert len(feste) == 13 and date(2025, 10, 4) not in festivita_nazionali(2025)
    aperto = Spazio.da_env({"SPAZIO_FESTIVI": "aperto"})
    assert len(aperto.orari_del(date(2026, 12, 8))) == 7 and "festivi" not in aperto.orario_leggibile
    ridotto = Spazio.da_env({"SPAZIO_FESTIVI": "16-19"})
    assert [t.hour for t in ridotto.orari_del(date(2026, 12, 8))] == [16, 17, 18]
    assert ridotto.orari_del(date(2026, 12, 25)) == ridotto.orari_del(date(2026, 12, 8))
    assert ridotto.orari_del(date(2027, 3, 28)) == ()    # Pasqua è domenica: il luogo è chiuso comunque


def test_giorno_festivo_non_prenotabile(servizio, orologio, mario):
    orologio.avanza(days=22)   # martedì 1 dicembre 2026
    immacolata = servizio.disponibilita(date(2026, 12, 8), 1)[0]
    assert immacolata["festivo"] is True and immacolata["slot"] == []
    with pytest.raises(ErrorePrenotazione, match="calendario"):
        servizio.prenota("calcetto", "2026-12-08T18:00:00+01:00", mario)
    assert servizio.disponibilita(date(2026, 12, 9), 1)[0]["festivo"] is False


@pytest.mark.parametrize("chiave,valore", [
    ("SPAZIO_ATTIVITA", "nuoto"), ("SPAZIO_GIORNI", "lunedi,xyz"), ("SPAZIO_ORARIO", "22-15"), ("SPAZIO_ORARIO", "9-25"),
    ("SPAZIO_ORARIO", "mattina"), ("SPAZIO_ORARIO_PERIODI", "estate=9-13"), ("SPAZIO_ORARIO_PERIODI", "31/02-15/09=9-13"),
    ("SPAZIO_FESTIVI", "forse"), ("SPAZIO_FESTIVI_EXTRA", "26 maggio"), ("SPAZIO_FESTIVI_EXTRA", "26/05/27")])
def test_spazio_env_non_valido(chiave, valore):
    with pytest.raises(ValueError):
        Spazio.da_env({chiave: valore})


def test_app_mostra_il_luogo_configurato(settings, orologio, inference_client):
    settings.spazio = Spazio.da_env(ENV_PALESTRA)
    c = TestClient(create_app(settings, adesso=orologio, assistente=AssistenteIA("http://x", client=inference_client)))
    home = c.get("/").text
    assert "Palestra comunale Pinco Pallino" in home and "Via Roma 1, 70100 Paese (BA)" in home
    assert "Comune di Paese" in home and "Gioia del Colle" not in home and "Tennis" not in home
    info = c.get("/api/v1/spazio").json()
    assert info["comune"] == "Comune di Paese" and [a["codice"] for a in info["attivita"]] == ["calcetto"]
    # martedì chiuso, lunedì 17-19
    giorni = {g["data"]: g for g in c.get("/api/v1/disponibilita?giorni=3").json()}
    assert giorni["2026-11-10"]["slot"] == [] and [s["ora"] for s in giorni["2026-11-09"]["slot"]] == ["17:00", "18:00", "19:00"]
    r = _prenota_e_paga(c, inizio="2026-11-11T18:00:00+01:00")
    assert "PAE-" in r.text
    c.app.state.db.chiudi()


# ------------------------------------------------------------ tabella slot
def test_numero_di_prenotazione_registrato_sullo_slot(servizio, mario):
    p = servizio.prenota("calcetto", VEN_20, mario)
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == p["codice"]
    v = servizio.db.query("SELECT * FROM v_occupazione WHERE inizio=%s", (VEN_20,))[0]
    assert v["stato"] == "ATTESA_PAGAMENTO" and v["cognome"] == "Rossi"


def test_annullamento_libera_lo_slot(servizio, mario, anna):
    p = servizio.prenota("calcetto", VEN_20, mario)
    servizio.annulla(p["codice"])
    assert _slot(servizio, VEN_20)["codice_prenotazione"] is None
    q = servizio.prenota("calcetto", VEN_20, anna)
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == q["codice"]


def test_scadenza_libera_lo_slot_e_pagamento_tardivo_lo_rioccupa(servizio, orologio, mario):
    p = servizio.avvia_pagamento(servizio.prenota("calcetto", VEN_20, mario)["codice"], "x")
    orologio.avanza(minutes=16)
    servizio.disponibilita()
    assert _slot(servizio, VEN_20)["codice_prenotazione"] is None
    servizio.pagamenti.segna_pagato(p["iuv"])
    assert servizio.verifica_pagamento(p["codice"])["stato"] == "CONFERMATA"
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == p["codice"]


def test_blocco_ufficio_registrato_sullo_slot(servizio):
    b = servizio.blocca(VEN_20, "Torneo scuole")
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == b["codice"]


def test_calendario_genera_tutti_gli_slot(servizio):
    servizio.disponibilita(giorni=7)
    n = servizio.db.query("SELECT COUNT(*) n, COUNT(codice_prenotazione) occupati FROM slot")[0]
    assert n["n"] == 6 * 7 and n["occupati"] == 0  # lun-sab, 7 slot al giorno


def test_stati_pubblici_e_occupazione(servizio, orologio, mario, anna):
    servizio.conferma_manuale(servizio.prenota("calcetto", "2026-11-13T19:00:00+01:00", mario)["codice"], "RIF1")
    attesa = servizio.prenota("tennis_singolo", VEN_20, anna)
    servizio.blocca("2026-11-13T21:00:00+01:00", "Manutenzione")
    venerdi = next(g for g in servizio.disponibilita() if g["data"] == "2026-11-13")
    stati = {s["ora"]: s["stato"] for s in venerdi["slot"]}
    assert stati["19:00"] == "occupato" and stati["20:00"] == "in_pagamento" and stati["21:00"] == "riservato"
    assert stati["18:00"] == "libero" and venerdi["liberi"] == 4
    assert all("codice" not in s for s in venerdi["slot"])   # il calendario pubblico non espone i numeri
    occ = next(g for g in servizio.occupazione() if g["data"] == "2026-11-13")
    per_ora = {s["ora"]: s for s in occ["slot"]}
    assert per_ora["20:00"]["codice"] == attesa["codice"] and per_ora["20:00"]["intestatario"] == "Bianchi Anna"
    assert per_ora["21:00"]["intestatario"] == "Manutenzione"
    lunedi = servizio.disponibilita()[0]
    assert {s["stato"] for s in lunedi["slot"]} == {"libero"}  # alle 10 nessuno slot pomeridiano è passato
    orologio.avanza(hours=7)                                    # ore 17: l'attesa di pagamento è scaduta
    assert [s["stato"] for s in servizio.disponibilita()[0]["slot"][:3]] == ["passato", "passato", "passato"]
    venerdi = next(g for g in servizio.occupazione() if g["data"] == "2026-11-13")
    assert {s["ora"]: s["codice"] for s in venerdi["slot"]}["20:00"] is None


def test_concorrenza_un_solo_vincitore_per_slot(servizio):
    """Simulazione: 40 cittadini prenotano insieme lo stesso slot, su connessioni PostgreSQL diverse."""
    esiti, barriera = [], threading.Barrier(40)

    def prova(i):
        barriera.wait()
        try:
            esiti.append(servizio.prenota("calcetto", VEN_20, Cittadino(f"CF{i:014d}", "N", f"C{i}"))["codice"])
        except ErrorePrenotazione as e:
            esiti.append(e.codice_http)

    fili = [threading.Thread(target=prova, args=(i,)) for i in range(40)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    vincitori = [e for e in esiti if isinstance(e, str)]
    assert len(vincitori) == 1 and esiti.count(409) == 39
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == vincitori[0]


def test_vincoli_del_database(servizio, mario):
    """Anche scrivendo direttamente in tabella, il database rifiuta sovrapposizioni e doppioni."""
    servizio.prenota("calcetto", VEN_20, mario)
    riga = ("X-1", "calcetto", "2026-11-13T20:30:00+01:00", "2026-11-13T21:30:00+01:00", "CONFERMATA", "UFFICIO", 0,
            "2026-11-09T10:00:00+01:00", "2026-11-09T10:00:00+01:00")
    with pytest.raises(IntegrityError, match="ex_nessuna_sovrapposizione"):
        with servizio.db.tx() as conn:
            conn.execute("INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, importo_cent, "
                         "creata_il, aggiornata_il) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", riga)
    altro = servizio.prenota("calcetto", "2026-11-13T19:00:00+01:00", mario)
    with pytest.raises(IntegrityError):
        with servizio.db.tx() as conn:
            conn.execute("UPDATE slot SET codice_prenotazione=%s WHERE inizio=%s", (altro["codice"], VEN_20))
    tipi = {r["column_name"]: r["data_type"] for r in servizio.db.query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=current_schema() AND table_name='slot'")}
    assert tipi["inizio"] == "timestamp with time zone"


# ------------------------------------------------------------ interfaccia e API
def test_home_mostra_slot_impegnati_con_legenda(app_client):
    _prenota_e_paga(app_client)
    html = app_client.get("/?dal=2026-11-13").text
    assert "20:00 · occupato" in html and "Legenda" in html and "1 impegnato" in html


def test_ufficio_vede_numero_prenotazione_nella_griglia(app_client):
    r = _prenota_e_paga(app_client)
    codice = app_client.app.state.servizio.elenco()[0]["codice"]
    html = app_client.get("/ufficio", auth=("u", "p")).text
    assert "Occupazione degli slot" in html and html.count(codice) >= 2  # griglia + elenco


def test_api_assistente_faq_e_ufficio(app_client):
    _prenota_e_paga(app_client)
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto venerdì sera alle 20"}).json()
    assert r["intento"]["data"] == "2026-11-13"
    ore = [p["ora"] for p in r["proposte"]]
    assert "20:00" not in ore and ore[0] in ("19:00", "21:00")
    assert r["proposte"][0]["link_prenotazione"].startswith("http://testserver/prenota?inizio=")
    assert app_client.get("/api/v1/faq", params={"domanda": "posso annullare?"}).json()["trovata"] is True
    assert app_client.get("/api/v1/ufficio/occupazione").status_code == 401
    occ = app_client.get("/api/v1/ufficio/occupazione?dal=2026-11-13&giorni=1", auth=("u", "p")).json()
    codice = next(s["codice"] for s in occ[0]["slot"] if s["ora"] == "20:00")
    det = app_client.get(f"/api/v1/ufficio/prenotazioni/{codice}", auth=("u", "p")).json()
    assert det["stato"] == "CONFERMATA" and "cf" not in det
    assert app_client.get("/api/v1/ufficio/prenotazioni/GDC-XXXX-XXXX", auth=("u", "p")).status_code == 404


def test_assistente_giorno_pieno_propone_i_giorni_successivi(app_client):
    servizio = app_client.app.state.servizio
    venerdi = servizio.disponibilita(date(2026, 11, 13), 1)[0]
    for s in venerdi["slot"]:
        servizio.blocca(s["inizio"], "Torneo")
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto venerdì sera alle 20"}).json()
    assert r["intento"]["data"] == "2026-11-13" and "giorni successivi" in r["messaggio"]
    assert [(p["data"], p["ora"]) for p in r["proposte"]][:3] == [
        ("2026-11-14", "20:00"), ("2026-11-14", "19:00"), ("2026-11-14", "21:00")]
    # giorno e fascia in cui il campo è chiuso: nessuna proposta, ma con una spiegazione
    r = app_client.get("/api/v1/assistente", params={"testo": "calcetto domenica mattina"}).json()
    assert r["proposte"] == [] and "disponibilita" in r["messaggio"]
    # giorno con posti liberi: nessun messaggio
    assert "messaggio" not in app_client.get("/api/v1/assistente", params={"testo": "calcetto sabato sera"}).json()
