"""Server MCP di Spazio Comune: il luogo prenotabile come strumento per altri agenti.

Espone ad assistenti e sistemi agentici (Claude, IDE, orchestratori) le stesse
informazioni del sito, passando dalle API HTTP dell'app: non legge il database
e non conosce i segreti dell'app.

Regola invariata: l'agente propone, la persona decide. Il server MCP non
prenota e non paga; restituisce il link che il cittadino apre per completare
la prenotazione con SPID/CIE e pagoPA.

Strumenti per tutti:      venue_info, availability, search_slots, ask, booking_link
Strumenti per l'ufficio:  slot_occupancy, booking_detail
                          (solo se SPAZIO_COMUNE_UFFICIO_USER/PASSWORD sono impostati)

    python mcp_server/server.py                         # stdio (Claude Desktop, Claude Code, IDE)
    MCP_TRANSPORT=http python mcp_server/server.py      # HTTP streamable su :8090/mcp
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

INSTRUCTIONS = (
    "Strumenti per consultare un luogo comunale prenotabile (orari, disponibilità, tariffe, regole). "
    "Non puoi prenotare né pagare: quando la persona ha scelto un orario, dalle il booking_link "
    "da aprire; completerà lei l'accesso con SPID/CIE e il pagamento pagoPA. "
    "Non chiedere né inviare dati personali (codice fiscale, telefono, email)."
)


class AppError(Exception):
    pass


class AppClient:
    """Chiamate all'app Spazio Comune; gli errori diventano messaggi leggibili per l'agente."""

    def __init__(self, base_url: str, client: httpx.Client | None = None,
                 office: tuple[str, str] | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.office = office
        self._http = client or httpx.Client(timeout=timeout)

    def get(self, path: str, restricted: bool = False, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self._http.get(f"{self.base_url}{path}", params=params,
                               auth=self.office if restricted else None)
        except httpx.HTTPError as e:
            raise AppError(f"App Spazio Comune non raggiungibile su {self.base_url}: {e}") from None
        if r.status_code >= 400:
            try:
                message = r.json().get("errore") or r.json().get("detail")
            except ValueError:
                message = r.text[:200]
            raise AppError(f"Errore {r.status_code}: {message}")
        return r.json()


def _iso_date(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise AppError(f"{field}: usare il formato AAAA-MM-GG") from None


def create_server(app: AppClient | None = None) -> FastMCP:
    if app is None:
        user, pwd = os.getenv("SPAZIO_COMUNE_UFFICIO_USER"), os.getenv("SPAZIO_COMUNE_UFFICIO_PASSWORD")
        app = AppClient(os.getenv("SPAZIO_COMUNE_URL", "http://localhost:8000"),
                        office=(user, pwd) if user and pwd else None)
    host = os.getenv("MCP_HOST", "127.0.0.1")
    allowed_hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",") if h.strip()]
    mcp = FastMCP(
        "spazio-comune", instructions=INSTRUCTIONS, host=host, port=int(os.getenv("MCP_PORT", "8090")),
        transport_security=TransportSecuritySettings(  # protezione da DNS rebinding sul trasporto HTTP
            enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts,
            allowed_origins=[f"http://{h.replace(':*', '')}" for h in allowed_hosts]),
    )

    @mcp.tool()
    def venue_info() -> dict:
        """Il luogo prenotabile: nome, indirizzo, Comune, ufficio, orari, attività e tariffe (in centesimi)."""
        return app.get("/api/v1/venue")

    @mcp.tool()
    def availability(start_date: str | None = None, days: int = 7, only_free: bool = False) -> list[dict]:
        """Calendario degli slot da `start_date` (AAAA-MM-GG, predefinito oggi) per `days` giorni (1-14).

        Ogni slot ha uno stato: libero, occupato, in_pagamento, riservato (dall'ufficio) o passato.
        Un giorno senza slot è chiuso; `festivo` indica i giorni festivi.
        Con only_free=true restituisce soltanto gli slot prenotabili.
        """
        calendar = app.get("/api/v1/availability", **{"from": _iso_date(start_date, "start_date")}, days=max(1, min(days, 14)))
        if only_free:
            calendar = [{**day, "slot": [s for s in day["slot"] if s["libero"]]} for day in calendar]
        return calendar

    @mcp.tool()
    def search_slots(request: str) -> dict:
        """Dalla frase in italiano agli orari liberi più vicini, es. "calcetto venerdì sera alle 20".

        Restituisce l'intento riconosciuto (attività, data, fascia, ora) e fino a 4 proposte,
        ciascuna con il link_prenotazione (link di prenotazione) da dare alla persona.
        """
        return app.get("/api/v1/assistant", text=request[:500])

    @mcp.tool()
    def ask(question: str) -> dict:
        """Risponde su tariffe, pagamento, annullamento, accesso, privacy, citando le fonti ufficiali.

        Se la risposta non è nella base di conoscenza, `trovata` è false: rimanda all'ufficio.
        """
        return app.get("/api/v1/faq", question=question[:500])

    @mcp.tool()
    def booking_link(start: str, activity: str) -> dict:
        """Link che la persona apre per prenotare lo slot `start` (ISO 8601, il campo inizio di availability).

        La prenotazione si completa sul sito con SPID/CIE e pagamento pagoPA: l'agente non prenota.
        """
        info = app.get("/api/v1/venue")
        codes = [a["codice"] for a in info["attivita"]]
        if activity not in codes:
            raise AppError(f"activity deve essere una tra: {', '.join(codes)}")
        day = start[:10]
        calendar = app.get("/api/v1/availability", **{"from": _iso_date(day, "start")}, days=1)
        slot = next((s for d in calendar for s in d["slot"] if s["inizio"] == start), None)
        if slot is None:
            raise AppError("Orario non previsto dal calendario: usa un 'inizio' restituito da availability")
        if not slot["libero"]:
            return {"disponibile": False, "stato": slot["stato"],
                    "messaggio": "Slot non disponibile: proponi un altro orario con search_slots o availability"}
        return {"disponibile": True, "inizio": start, "attivita": activity,
                "link": f"{info['url']}/book?start={quote(start)}&activity={activity}",
                "nota": "Apri il link per accedere con SPID/CIE e pagare con pagoPA."}

    if app.office:
        @mcp.tool()
        def slot_occupancy(start_date: str | None = None, days: int = 7) -> list[dict]:
            """[Ufficio] Per ogni slot, il numero di prenotazione che lo occupa, lo stato e l'intestatario."""
            return app.get("/api/v1/backoffice/occupancy", restricted=True,
                           **{"from": _iso_date(start_date, "start_date")}, days=max(1, min(days, 14)))

        @mcp.tool()
        def booking_detail(code: str) -> dict:
            """[Ufficio] Dettaglio di una prenotazione dal suo numero (es. GDC-7KQ2-M4XP), senza codice fiscale."""
            return app.get(f"/api/v1/backoffice/bookings/{quote(code.strip().upper())}", restricted=True)

    return mcp


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    create_server().run("streamable-http" if transport == "http" else "stdio")
