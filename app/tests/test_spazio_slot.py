"""Un solo luogo configurato da .env, tabella slot con numero di prenotazione, API per agenti."""
import sqlite3
import threading
from datetime import time

import pytest
from fastapi.testclient import TestClient

from prenota.adapters.agenda import NoopAgenda
from prenota.adapters.identity import Cittadino
from prenota.adapters.payments import MockPagoPA
from prenota.ai import AssistenteIA
from prenota.booking import ErrorePrenotazione, ServizioPrenotazioni
from prenota.catalog import Spazio
from prenota.db import Database
from prenota.main import create_app

from test_web import VEN_20, _prenota_e_paga

ENV_PALESTRA = {
    "SPAZIO_NOME": "Palestra comunale Pinco Pallino", "SPAZIO_INDIRIZZO": "Via Roma 1, 70100 Paese (BA)",
    "COMUNE_NOME": "Comune di Paese", "COMUNE_INDIRIZZO": "Piazza del Municipio 1", "COMUNE_SITO": "https://paese.example.it/",
    "UFFICIO_NOME": "Ufficio Sport di Paese", "SPAZIO_ATTIVITA": "calcetto", "SPAZIO_GIORNI": "lun,mer,ven",
    "SPAZIO_ORARIO": "17-20", "CODICE_PREFISSO": "pae",
}


def _slot(servizio, inizio):
    r = servizio.db.query("SELECT * FROM slot WHERE inizio=?", (inizio,))
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


@pytest.mark.parametrize("chiave,valore", [("SPAZIO_ATTIVITA", "nuoto"), ("SPAZIO_GIORNI", "lunedi,xyz")])
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


# ------------------------------------------------------------ tabella slot
def test_numero_di_prenotazione_registrato_sullo_slot(servizio, mario):
    p = servizio.prenota("calcetto", VEN_20, mario)
    assert _slot(servizio, VEN_20)["codice_prenotazione"] == p["codice"]
    v = servizio.db.query("SELECT * FROM v_occupazione WHERE inizio=?", (VEN_20,))[0]
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


def test_concorrenza_un_solo_vincitore_per_slot(tmp_path, orologio):
    """Simulazione: 40 cittadini prenotano insieme lo stesso slot su database su file."""
    servizio = ServizioPrenotazioni(Database(str(tmp_path / "c.db")), MockPagoPA("http://t"), NoopAgenda(),
                                    "k", adesso=orologio)
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


def test_migrazione_da_schema_v1(tmp_path):
    f = tmp_path / "v1.db"
    con = sqlite3.connect(f)
    con.executescript("""
    CREATE TABLE prenotazioni (id INTEGER PRIMARY KEY AUTOINCREMENT, codice TEXT NOT NULL UNIQUE,
      impianto TEXT NOT NULL, attivita TEXT NOT NULL, inizio TEXT NOT NULL, fine TEXT NOT NULL,
      stato TEXT NOT NULL, canale TEXT NOT NULL, importo_cent INTEGER NOT NULL, iuv TEXT, url_pagamento TEXT,
      cf TEXT, nome TEXT, cognome TEXT, email TEXT, telefono TEXT, note TEXT, creata_il TEXT NOT NULL,
      aggiornata_il TEXT NOT NULL);
    CREATE UNIQUE INDEX ux_slot_attivo ON prenotazioni (impianto, inizio)
      WHERE stato IN ('ATTESA_PAGAMENTO','CONFERMATA','BLOCCO','UTILIZZATA');
    INSERT INTO prenotazioni VALUES (1,'GDC-AAAA-BBBB','benagiano','calcetto','2026-11-13T20:00:00+01:00',
      '2026-11-13T21:00:00+01:00','CONFERMATA','ONLINE',4000,NULL,NULL,'X','M','R',NULL,NULL,NULL,'t','t');
    """)
    con.close()
    db = Database(str(f))
    assert db.query("SELECT codice_prenotazione FROM slot")[0][0] == "GDC-AAAA-BBBB"
    assert "impianto" not in {r[1] for r in db.query("PRAGMA table_info(prenotazioni)")}


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
