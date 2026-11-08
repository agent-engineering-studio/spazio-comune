"""Server MCP di Spazio Comune: il luogo prenotabile come strumento per altri agenti.

Espone ad assistenti e sistemi agentici (Claude, IDE, orchestratori) le stesse
informazioni del sito, passando dalle API HTTP dell'app: non legge il database
e non conosce i segreti dell'app.

Regola invariata: l'agente propone, la persona decide. Il server MCP non
prenota e non paga; restituisce il link che il cittadino apre per completare
la prenotazione con SPID/CIE e pagoPA.

Strumenti per tutti:      info_spazio, disponibilita, cerca_orari, domanda, link_prenotazione
Strumenti per l'ufficio:  occupazione_slot, dettaglio_prenotazione
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

ISTRUZIONI = (
    "Strumenti per consultare un luogo comunale prenotabile (orari, disponibilità, tariffe, regole). "
    "Non puoi prenotare né pagare: quando la persona ha scelto un orario, dalle il link_prenotazione "
    "da aprire; completerà lei l'accesso con SPID/CIE e il pagamento pagoPA. "
    "Non chiedere né inviare dati personali (codice fiscale, telefono, email)."
)


class ErroreApp(Exception):
    pass


class ClientApp:
    """Chiamate all'app Spazio Comune; gli errori diventano messaggi leggibili per l'agente."""

    def __init__(self, base_url: str, client: httpx.Client | None = None,
                 ufficio: tuple[str, str] | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.ufficio = ufficio
        self._http = client or httpx.Client(timeout=timeout)

    def get(self, percorso: str, riservato: bool = False, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self._http.get(f"{self.base_url}{percorso}", params=params,
                               auth=self.ufficio if riservato else None)
        except httpx.HTTPError as e:
            raise ErroreApp(f"App Spazio Comune non raggiungibile su {self.base_url}: {e}") from None
        if r.status_code >= 400:
            try:
                messaggio = r.json().get("errore") or r.json().get("detail")
            except ValueError:
                messaggio = r.text[:200]
            raise ErroreApp(f"Errore {r.status_code}: {messaggio}")
        return r.json()


def _data(valore: str | None, campo: str) -> str | None:
    if valore in (None, ""):
        return None
    try:
        return date.fromisoformat(valore).isoformat()
    except ValueError:
        raise ErroreApp(f"{campo}: usare il formato AAAA-MM-GG") from None


def crea_server(app: ClientApp | None = None) -> FastMCP:
    if app is None:
        user, pwd = os.getenv("SPAZIO_COMUNE_UFFICIO_USER"), os.getenv("SPAZIO_COMUNE_UFFICIO_PASSWORD")
        app = ClientApp(os.getenv("SPAZIO_COMUNE_URL", "http://localhost:8000"),
                        ufficio=(user, pwd) if user and pwd else None)
    host = os.getenv("MCP_HOST", "127.0.0.1")
    consentiti = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",") if h.strip()]
    mcp = FastMCP(
        "spazio-comune", instructions=ISTRUZIONI, host=host, port=int(os.getenv("MCP_PORT", "8090")),
        transport_security=TransportSecuritySettings(  # protezione da DNS rebinding sul trasporto HTTP
            enable_dns_rebinding_protection=True, allowed_hosts=consentiti,
            allowed_origins=[f"http://{h.replace(':*', '')}" for h in consentiti]),
    )

    @mcp.tool()
    def info_spazio() -> dict:
        """Il luogo prenotabile: nome, indirizzo, Comune, ufficio, orari, attività e tariffe (in centesimi)."""
        return app.get("/api/v1/spazio")

    @mcp.tool()
    def disponibilita(dal: str | None = None, giorni: int = 7, solo_liberi: bool = False) -> list[dict]:
        """Calendario degli slot da `dal` (AAAA-MM-GG, predefinito oggi) per `giorni` giorni (1-14).

        Ogni slot ha uno stato: libero, occupato, in_pagamento, riservato (dall'ufficio) o passato.
        Con solo_liberi=true restituisce soltanto gli slot prenotabili.
        """
        cal = app.get("/api/v1/disponibilita", dal=_data(dal, "dal"), giorni=max(1, min(giorni, 14)))
        if solo_liberi:
            cal = [{**g, "slot": [s for s in g["slot"] if s["libero"]]} for g in cal]
        return cal

    @mcp.tool()
    def cerca_orari(richiesta: str) -> dict:
        """Dalla frase in italiano agli orari liberi più vicini, es. "calcetto venerdì sera alle 20".

        Restituisce l'intento riconosciuto (attività, data, fascia, ora) e fino a 4 proposte,
        ciascuna con il link_prenotazione da dare alla persona.
        """
        return app.get("/api/v1/assistente", testo=richiesta[:500])

    @mcp.tool()
    def domanda(testo: str) -> dict:
        """Risponde su tariffe, pagamento, annullamento, accesso, privacy, citando le fonti ufficiali.

        Se la risposta non è nella base di conoscenza, `trovata` è false: rimanda all'ufficio.
        """
        return app.get("/api/v1/faq", domanda=testo[:500])

    @mcp.tool()
    def link_prenotazione(inizio: str, attivita: str) -> dict:
        """Link che la persona apre per prenotare lo slot `inizio` (ISO 8601, come in disponibilita).

        La prenotazione si completa sul sito con SPID/CIE e pagamento pagoPA: l'agente non prenota.
        """
        info = app.get("/api/v1/spazio")
        codici = [a["codice"] for a in info["attivita"]]
        if attivita not in codici:
            raise ErroreApp(f"attivita deve essere una tra: {', '.join(codici)}")
        giorno = inizio[:10]
        cal = app.get("/api/v1/disponibilita", dal=_data(giorno, "inizio"), giorni=1)
        slot = next((s for g in cal for s in g["slot"] if s["inizio"] == inizio), None)
        if slot is None:
            raise ErroreApp("Orario non previsto dal calendario: usa un 'inizio' restituito da disponibilita")
        if not slot["libero"]:
            return {"disponibile": False, "stato": slot["stato"],
                    "messaggio": "Slot non disponibile: proponi un altro orario con cerca_orari o disponibilita"}
        return {"disponibile": True, "inizio": inizio, "attivita": attivita,
                "link": f"{info['url']}/prenota?inizio={quote(inizio)}&attivita={attivita}",
                "nota": "Apri il link per accedere con SPID/CIE e pagare con pagoPA."}

    if app.ufficio:
        @mcp.tool()
        def occupazione_slot(dal: str | None = None, giorni: int = 7) -> list[dict]:
            """[Ufficio] Per ogni slot, il numero di prenotazione che lo occupa, lo stato e l'intestatario."""
            return app.get("/api/v1/ufficio/occupazione", riservato=True,
                           dal=_data(dal, "dal"), giorni=max(1, min(giorni, 14)))

        @mcp.tool()
        def dettaglio_prenotazione(codice: str) -> dict:
            """[Ufficio] Dettaglio di una prenotazione dal suo numero (es. GDC-7KQ2-M4XP), senza codice fiscale."""
            return app.get(f"/api/v1/ufficio/prenotazioni/{quote(codice.strip().upper())}", riservato=True)

    return mcp


if __name__ == "__main__":
    trasporto = os.getenv("MCP_TRANSPORT", "stdio")
    crea_server().run("streamable-http" if trasporto == "http" else "stdio")
