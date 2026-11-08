"""Server MCP (mcp_server/server.py) contro l'app reale, via protocollo MCP in memoria."""
import asyncio
import json
import importlib.util

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from conftest import RADICE
from test_web import _prenota_e_paga

_spec = importlib.util.spec_from_file_location("mcp_spazio", RADICE / "mcp_server" / "server.py")
mcp_spazio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_spazio)


def _chiama(server, strumento=None, **argomenti):
    async def giro():
        async with create_connected_server_and_client_session(server._mcp_server) as sessione:
            if strumento is None:
                return [t.name for t in (await sessione.list_tools()).tools]
            r = await sessione.call_tool(strumento, argomenti)
            if r.isError:
                return {"errore": r.content[0].text}
            dati = r.structuredContent
            if dati is None:  # strumenti che restituiscono dict: JSON nel contenuto testuale
                return json.loads(r.content[0].text)
            return dati["result"] if set(dati) == {"result"} else dati
    return asyncio.run(giro())


@pytest.fixture
def mcp_pubblico(app_client):
    return mcp_spazio.crea_server(mcp_spazio.ClientApp("http://testserver", client=app_client))


@pytest.fixture
def mcp_ufficio(app_client):
    return mcp_spazio.crea_server(mcp_spazio.ClientApp("http://testserver", client=app_client, ufficio=("u", "p")))


def test_strumenti_esposti(mcp_pubblico, mcp_ufficio):
    pubblici = {"info_spazio", "disponibilita", "cerca_orari", "domanda", "link_prenotazione"}
    assert set(_chiama(mcp_pubblico)) == pubblici
    assert set(_chiama(mcp_ufficio)) == pubblici | {"occupazione_slot", "dettaglio_prenotazione"}


def test_info_e_disponibilita(app_client, mcp_pubblico):
    _prenota_e_paga(app_client)
    info = _chiama(mcp_pubblico, "info_spazio")
    assert info["nome"].startswith("Campo comunale") and info["comune"] == "Comune di Gioia del Colle"
    cal = _chiama(mcp_pubblico, "disponibilita", dal="2026-11-13", giorni=1)
    stati = {s["ora"]: s["stato"] for s in cal[0]["slot"]}
    assert stati["20:00"] == "occupato" and "codice" not in cal[0]["slot"][0]
    liberi = _chiama(mcp_pubblico, "disponibilita", dal="2026-11-13", giorni=1, solo_liberi=True)
    assert "20:00" not in [s["ora"] for s in liberi[0]["slot"]]
    assert "AAAA-MM-GG" in _chiama(mcp_pubblico, "disponibilita", dal="13/11/2026")["errore"]


def test_cerca_orari_e_link(app_client, mcp_pubblico):
    _prenota_e_paga(app_client)
    r = _chiama(mcp_pubblico, "cerca_orari", richiesta="calcetto venerdì sera alle 20")
    proposta = r["proposte"][0]
    assert proposta["ora"] in ("19:00", "21:00")
    link = _chiama(mcp_pubblico, "link_prenotazione", inizio=proposta["inizio"], attivita="calcetto")
    assert link["disponibile"] and link["link"] == proposta["link_prenotazione"]
    occupato = _chiama(mcp_pubblico, "link_prenotazione", inizio="2026-11-13T20:00:00+01:00", attivita="calcetto")
    assert occupato == {**occupato, "disponibile": False, "stato": "occupato"}
    assert "attivita" in _chiama(mcp_pubblico, "link_prenotazione", inizio=proposta["inizio"], attivita="nuoto")["errore"]
    assert _chiama(mcp_pubblico, "domanda", testo="quanto costa il calcetto?")["trovata"] is True


def test_strumenti_ufficio(app_client, mcp_ufficio):
    _prenota_e_paga(app_client)
    occ = _chiama(mcp_ufficio, "occupazione_slot", dal="2026-11-13", giorni=1)
    codice = {s["ora"]: s["codice"] for s in occ[0]["slot"]}["20:00"]
    assert codice.startswith("GDC-")
    det = _chiama(mcp_ufficio, "dettaglio_prenotazione", codice=codice.lower())
    assert det["stato"] == "CONFERMATA" and det["codice"] == codice and "cf" not in det


def test_credenziali_ufficio_errate(app_client):
    srv = mcp_spazio.crea_server(mcp_spazio.ClientApp("http://testserver", client=app_client, ufficio=("u", "x")))
    assert "401" in _chiama(srv, "occupazione_slot")["errore"]
