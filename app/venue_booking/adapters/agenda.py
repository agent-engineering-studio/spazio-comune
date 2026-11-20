"""Sincronizzazione con l'agenda degli uffici.

Principio: non cambiare il modo di lavorare dell'ufficio. Le prenotazioni
create qui vengono esposte come feed iCalendar (RFC 5545) e CSV, che
l'ufficio può aprire in Outlook/Thunderbird/Excel o importare in eAgenda.
Se ISWEB (fornitore eCOMUNE/eAgenda) mette a disposizione API o webhook,
basta implementare `EAgendaISWEBAdapter` senza toccare il resto.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Iterable, Protocol

from ..catalog import ACTIVITIES


class AgendaSync(Protocol):
    def publish(self, booking: dict) -> None: ...
    def remove(self, code: str) -> None: ...


class NoopAgenda:
    def __init__(self):
        self.events: dict[str, dict] = {}

    def publish(self, booking: dict) -> None:
        self.events[booking["codice"]] = booking

    def remove(self, code: str) -> None:
        self.events.pop(code, None)


class EAgendaISWEBAdapter:  # pragma: no cover - dipende dal fornitore
    def publish(self, booking: dict) -> None:
        raise NotImplementedError("Richiedere a ISWEB le API di scrittura eAgenda")

    def remove(self, code: str) -> None:
        raise NotImplementedError


def _ics_dt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%dT%H%M%S")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(bookings: Iterable[dict], name: str = "Spazio Comune", venue: str = "",
           catalog: dict | None = None) -> str:
    catalog = ACTIVITIES if catalog is None else catalog
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Spazio Comune//IT",
        f"X-WR-CALNAME:{_ics_escape(name)}", "X-WR-TIMEZONE:Europe/Rome",
    ]
    for p in bookings:
        act = catalog.get(p["attivita"])
        title = "BLOCCO / manutenzione" if p["stato"] == "BLOCCO" else (act.name if act else p["attivita"])
        rows += [
            "BEGIN:VEVENT",
            f"UID:{p['codice']}@spaziocomune",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Rome:{_ics_dt(p['inizio'])}",
            f"DTEND;TZID=Europe/Rome:{_ics_dt(p['fine'])}",
            f"SUMMARY:{_ics_escape(title + ' – ' + p['codice'])}",
            f"LOCATION:{_ics_escape(venue)}",
            f"DESCRIPTION:{_ics_escape((act.setup_note if act else '') + ' · stato ' + p['stato'])}",
            "END:VEVENT",
        ]
    rows.append("END:VCALENDAR")
    return "\r\n".join(rows) + "\r\n"


CSV_FIELDS = ["codice", "attivita", "inizio", "fine", "stato", "canale",
             "importo_cent", "iuv", "cognome", "nome", "creata_il"]


def to_csv(bookings: Iterable[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", delimiter=";")
    w.writeheader()
    for p in bookings:
        w.writerow(p)
    return buf.getvalue()
