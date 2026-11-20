"""Server MCP (mcp_server/server.py) contro l'app reale, via protocollo MCP in memoria."""
import asyncio
import json
import importlib.util

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from conftest import ROOT
from test_web import _book_and_pay

_spec = importlib.util.spec_from_file_location("mcp_spazio", ROOT / "mcp_server" / "server.py")
mcp_venue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_venue)


def _call(server, tool=None, **arguments):
    async def round_():
        async with create_connected_server_and_client_session(server._mcp_server) as session_info:
            if tool is None:
                return [t.name for t in (await session_info.list_tools()).tools]
            r = await session_info.call_tool(tool, arguments)
            if r.isError:
                return {"errore": r.content[0].text}
            data = r.structuredContent
            if data is None:  # strumenti che restituiscono dict: JSON nel contenuto testuale
                return json.loads(r.content[0].text)
            return data["result"] if set(data) == {"result"} else data
    return asyncio.run(round_())


@pytest.fixture
def mcp_public(app_client):
    return mcp_venue.create_server(mcp_venue.AppClient("http://testserver", client=app_client))


@pytest.fixture
def mcp_office(app_client):
    return mcp_venue.create_server(mcp_venue.AppClient("http://testserver", client=app_client, office=("u", "p")))


def test_exposed_tools(mcp_public, mcp_office):
    public_keys = {"venue_info", "availability", "search_slots", "ask", "booking_link"}
    assert set(_call(mcp_public)) == public_keys
    assert set(_call(mcp_office)) == public_keys | {"slot_occupancy", "booking_detail"}


def test_info_and_availability(app_client, mcp_public):
    _book_and_pay(app_client)
    info = _call(mcp_public, "venue_info")
    assert info["nome"].startswith("Campo comunale") and info["comune"] == "Comune di Gioia del Colle"
    cal = _call(mcp_public, "availability", start_date="2026-11-13", days=1)
    states = {s["ora"]: s["stato"] for s in cal[0]["slot"]}
    assert states["20:00"] == "occupato" and "codice" not in cal[0]["slot"][0]
    free = _call(mcp_public, "availability", start_date="2026-11-13", days=1, only_free=True)
    assert "20:00" not in [s["ora"] for s in free[0]["slot"]]
    assert "AAAA-MM-GG" in _call(mcp_public, "availability", start_date="13/11/2026")["errore"]


def test_search_times_and_link(app_client, mcp_public):
    _book_and_pay(app_client)
    r = _call(mcp_public, "search_slots", request="calcetto venerdì sera alle 20")
    proposal = r["proposte"][0]
    assert proposal["ora"] in ("19:00", "21:00")
    link = _call(mcp_public, "booking_link", start=proposal["inizio"], activity="calcetto")
    assert link["disponibile"] and link["link"] == proposal["link_prenotazione"]
    taken = _call(mcp_public, "booking_link", start="2026-11-13T20:00:00+01:00", activity="calcetto")
    assert taken == {**taken, "disponibile": False, "stato": "occupato"}
    assert "activity" in _call(mcp_public, "booking_link", start=proposal["inizio"], activity="nuoto")["errore"]
    assert _call(mcp_public, "ask", question="quanto costa il calcetto?")["trovata"] is True


def test_office_tools(app_client, mcp_office):
    _book_and_pay(app_client)
    occ = _call(mcp_office, "slot_occupancy", start_date="2026-11-13", days=1)
    code = {s["ora"]: s["codice"] for s in occ[0]["slot"]}["20:00"]
    assert code.startswith("GDC-")
    detail = _call(mcp_office, "booking_detail", code=code.lower())
    assert detail["stato"] == "CONFERMATA" and detail["codice"] == code and "cf" not in detail


def test_wrong_office_credentials(app_client):
    srv = mcp_venue.create_server(mcp_venue.AppClient("http://testserver", client=app_client, office=("u", "x")))
    assert "401" in _call(srv, "slot_occupancy")["errore"]
