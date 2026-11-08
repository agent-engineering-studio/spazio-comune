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

from ..catalog import ATTIVITA


class AgendaSync(Protocol):
    def pubblica(self, prenotazione: dict) -> None: ...
    def rimuovi(self, codice: str) -> None: ...


class NoopAgenda:
    def __init__(self):
        self.eventi: dict[str, dict] = {}

    def pubblica(self, prenotazione: dict) -> None:
        self.eventi[prenotazione["codice"]] = prenotazione

    def rimuovi(self, codice: str) -> None:
        self.eventi.pop(codice, None)


class EAgendaISWEBAdapter:  # pragma: no cover - dipende dal fornitore
    def pubblica(self, prenotazione: dict) -> None:
        raise NotImplementedError("Richiedere a ISWEB le API di scrittura eAgenda")

    def rimuovi(self, codice: str) -> None:
        raise NotImplementedError


def _ics_dt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%dT%H%M%S")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(prenotazioni: Iterable[dict], nome: str = "Spazio Comune", luogo: str = "") -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    righe = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Spazio Comune//IT",
        f"X-WR-CALNAME:{_ics_escape(nome)}", "X-WR-TIMEZONE:Europe/Rome",
    ]
    for p in prenotazioni:
        att = ATTIVITA.get(p["attivita"])
        titolo = "BLOCCO / manutenzione" if p["stato"] == "BLOCCO" else (att.nome if att else p["attivita"])
        righe += [
            "BEGIN:VEVENT",
            f"UID:{p['codice']}@spaziocomune",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Rome:{_ics_dt(p['inizio'])}",
            f"DTEND;TZID=Europe/Rome:{_ics_dt(p['fine'])}",
            f"SUMMARY:{_ics_escape(titolo + ' – ' + p['codice'])}",
            f"LOCATION:{_ics_escape(luogo)}",
            f"DESCRIPTION:{_ics_escape((att.preparazione if att else '') + ' · stato ' + p['stato'])}",
            "END:VEVENT",
        ]
    righe.append("END:VCALENDAR")
    return "\r\n".join(righe) + "\r\n"


CSV_CAMPI = ["codice", "attivita", "inizio", "fine", "stato", "canale",
             "importo_cent", "iuv", "cognome", "nome", "creata_il"]


def to_csv(prenotazioni: Iterable[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_CAMPI, extrasaction="ignore", delimiter=";")
    w.writeheader()
    for p in prenotazioni:
        w.writerow(p)
    return buf.getvalue()
