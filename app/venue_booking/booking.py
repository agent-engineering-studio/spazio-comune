"""Logica di dominio delle prenotazioni.

Ciclo di vita:
  ATTESA_PAGAMENTO --(esito pagoPA positivo)--> CONFERMATA --(check-in custode)--> UTILIZZATA
         |                                          |
         +--(15 min senza pagamento)--> SCADUTA     +--(annullamento)--> ANNULLATA
  BLOCCO: slot riservato dall'ufficio (manutenzione, eventi, società sportive)

Ogni stato attivo (ATTESA_PAGAMENTO, CONFERMATA, BLOCCO, UTILIZZATA) tiene il
numero di prenotazione registrato sulla riga dello slot; annullamento e
scadenza lo liberano, nella stessa transazione.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from psycopg.errors import IntegrityError

from .adapters.agenda import AgendaSync
from .adapters.identity import Citizen
from .adapters.payments import PaymentDue, PaymentGateway
from .catalog import Venue
from .db import Database

TZ = ZoneInfo("Europe/Rome")
ACTIVE_STATES = ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO", "UTILIZZATA")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O/1/I: si dettano al telefono


class BookingError(Exception):
    """Errore di dominio con messaggio comprensibile per il cittadino."""

    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.message, self.http_status = message, http_status


# stato in banca dati -> stato mostrato al cittadino
PUBLIC_STATE = {"LIBERO": "libero", "ATTESA_PAGAMENTO": "in_pagamento", "CONFERMATA": "occupato",
                  "UTILIZZATA": "occupato", "BLOCCO": "riservato"}


@dataclass
class Slot:
    start: datetime
    end: datetime
    state: str                 # libero | occupato | in_pagamento | riservato | passato

    @property
    def free(self) -> bool:
        return self.state == "libero"

    def to_dict(self) -> dict:
        return {"inizio": self.start.isoformat(), "fine": self.end.isoformat(),
                "ora": self.start.strftime("%H:%M"), "libero": self.free, "stato": self.state}


def new_code(prefix: str = "GDC") -> str:
    part = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))  # noqa: E731
    return f"{prefix}-{part()}-{part()}"


class BookingService:
    def __init__(self, db: Database, payments: PaymentGateway, agenda: AgendaSync,
                 ticket_secret: str, pending_ttl_min: int = 15,
                 min_cancel_hours: int | None = None,
                 now: Callable[[], datetime] | None = None, venue: Venue | None = None):
        # spazio, pagamenti e ttl si sostituiscono a caldo quando il back-office salva le impostazioni
        self.db, self.payments, self.agenda = db, payments, agenda
        self.venue = venue or Venue()
        self._secret_value = ticket_secret.encode()
        self.ttl = timedelta(minutes=pending_ttl_min)
        self._cancel_hours = min_cancel_hours
        self._now = now or (lambda: datetime.now(TZ))

    @property
    def cancel_hours(self) -> int:
        return self.venue.cancel_hours if self._cancel_hours is None else self._cancel_hours

    # ------------------------------------------------------------ utilità
    def now(self) -> datetime:
        return self._now()

    def _expire_pending(self, conn) -> None:
        limit = (self.now() - self.ttl).isoformat()
        for row in conn.execute("SELECT codice FROM prenotazioni "
                                 "WHERE stato='ATTESA_PAGAMENTO' AND creata_il < %s", (limit,)).fetchall():
            code = row["codice"]
            self._release_slot(conn, code)
            conn.execute("UPDATE prenotazioni SET stato='SCADUTA', aggiornata_il=%s WHERE codice=%s",
                         (self.now().isoformat(), code))

    # ------------------------------------------------------------ tabella slot
    def _generate_slots(self, conn, day: date) -> None:
        conn.cursor().executemany(
            "INSERT INTO slot (inizio, fine, aggiornato_il) VALUES (%s,%s,%s) ON CONFLICT (inizio) DO UPDATE "
            "SET fine=excluded.fine, aggiornato_il=excluded.aggiornato_il "
            "WHERE slot.codice_prenotazione IS NULL AND slot.fine <> excluded.fine",
            [(a.isoformat(), b.isoformat(), self.now().isoformat()) for a, b in self.scheduled_slots(day)])

    def _occupy_slot(self, conn, start: str, end: str, code: str) -> None:
        """Registra il numero di prenotazione sulla riga dello slot."""
        cur = conn.execute(
            "INSERT INTO slot (inizio, fine, codice_prenotazione, aggiornato_il) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (inizio) DO UPDATE SET codice_prenotazione=excluded.codice_prenotazione, "
            "aggiornato_il=excluded.aggiornato_il "
            "WHERE slot.codice_prenotazione IS NULL OR slot.codice_prenotazione=excluded.codice_prenotazione",
            (start, end, code, self.now().isoformat()))
        if cur.rowcount != 1:
            raise BookingError("Questo orario è appena stato prenotato da un'altra persona", 409)

    def _release_slot(self, conn, code: str) -> None:
        conn.execute("UPDATE slot SET codice_prenotazione=NULL, aggiornato_il=%s WHERE codice_prenotazione=%s",
                     (self.now().isoformat(), code))

    def _row(self, code: str) -> dict:
        r = self.db.query("SELECT * FROM prenotazioni WHERE codice=%s", (code,))
        if not r:
            raise BookingError("Prenotazione non trovata", 404)
        return dict(r[0])

    # ------------------------------------------------------------ disponibilità
    def scheduled_slots(self, day: date) -> list[tuple[datetime, datetime]]:
        out = []
        for t in self.venue.slots_on(day):
            start = datetime.combine(day, t, tzinfo=TZ)
            out.append((start, start + timedelta(minutes=self.venue.slot_minutes)))
        return out

    def _days(self, from_: date | None, days: int) -> list[date]:
        today = self.now().date()
        from_ = max(from_ or today, today)
        last = today + timedelta(days=self.venue.advance_days)
        return [g for g in (from_ + timedelta(days=i) for i in range(days)) if g <= last]

    def occupancy(self, from_: date | None = None, days: int = 7) -> list[dict]:
        """Calendario con, per ogni slot, il numero di prenotazione che lo occupa (uso ufficio)."""
        items = self._days(from_, days)
        with self.db.tx() as conn:
            self._expire_pending(conn)
            for g in items:
                self._generate_slots(conn, g)
        if not items:
            return []
        rows = {r["inizio"]: dict(r) for r in self.db.query(
            "SELECT * FROM v_occupazione WHERE inizio >= %s AND inizio < %s",
            (items[0].isoformat(), (items[-1] + timedelta(days=1)).isoformat()))}
        result = []
        for g in items:
            slot = []
            for a, b in self.scheduled_slots(g):
                r = rows.get(a.isoformat(), {"stato": "LIBERO", "codice_prenotazione": None})
                state = "passato" if a <= self.now() and r["stato"] == "LIBERO" else PUBLIC_STATE[r["stato"]]
                slot.append({**Slot(a, b, state).to_dict(), "codice": r["codice_prenotazione"],
                             "stato_prenotazione": r["stato"] if r["codice_prenotazione"] else None,
                             "attivita": r.get("attivita"), "intestatario":
                                 " ".join(x for x in (r.get("cognome"), r.get("nome")) if x) or r.get("note")})
            closure = self.venue.closure_on(g)
            result.append({"data": g.isoformat(), "slot": slot, "liberi": sum(s["libero"] for s in slot),
                              "festivo": self.venue.is_holiday(g),
                              "chiusura": (closure.reason or "chiusura straordinaria") if closure else None})
        return result

    def rebuild_calendar(self) -> None:
        """Dopo un cambio d'orario: elimina gli slot futuri liberi, che si rigenerano col nuovo calendario."""
        with self.db.tx() as conn:
            conn.execute("DELETE FROM slot WHERE inizio > %s AND codice_prenotazione IS NULL", (self.now().isoformat(),))

    def off_schedule(self) -> list[dict]:
        """Prenotazioni future ancora attive in orari che il calendario attuale non prevede più."""
        out = []
        for p in self.items(self.now().date(), None, ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO")):
            start = datetime.fromisoformat(p["inizio"])
            if start > self.now() and start not in dict(self.scheduled_slots(start.date())):
                out.append(p)
        return out

    def availability(self, from_: date | None = None, days: int = 7) -> list[dict]:
        """Calendario pubblico: stato di ogni slot, senza numeri di prenotazione né nomi."""
        public_keys = ("inizio", "fine", "ora", "libero", "stato")
        return [{**g, "slot": [{k: s[k] for k in public_keys} for s in g["slot"]]}
                for g in self.occupancy(from_, days)]

    # ------------------------------------------------------------ prenotazione
    def book(self, activity: str, start_iso: str, citizen: Citizen,
                phone: str | None = None, note: str | None = None,
                channel: str = "ONLINE") -> dict:
        if activity not in self.venue.activities:
            raise BookingError("Attività non disponibile in questo luogo")
        try:
            start = datetime.fromisoformat(start_iso)
        except ValueError:
            raise BookingError("Orario non valido") from None
        if start.tzinfo is None:
            start = start.replace(tzinfo=TZ)
        valid = {a: b for a, b in self.scheduled_slots(start.date())}
        if start not in valid:
            raise BookingError("L'orario scelto non è previsto dal calendario")
        if start <= self.now():
            raise BookingError("Non è possibile prenotare un orario passato")
        if start.date() > self.now().date() + timedelta(days=self.venue.advance_days):
            raise BookingError(f"Si può prenotare al massimo {self.venue.advance_days} giorni prima")

        now = self.now().isoformat()
        code = new_code(self.venue.code_prefix)
        with self.db.tx() as conn:
            self._expire_pending(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, "
                    "importo_cent, cf, nome, cognome, email, telefono, note, creata_il, aggiornata_il) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (code, activity, start.isoformat(), valid[start].isoformat(),
                     "ATTESA_PAGAMENTO", channel, self.venue.fee_for(activity, start), citizen.tax_code, citizen.name,
                     citizen.last_name, citizen.email, phone, (note or "")[:280], now, now))
            except IntegrityError:  # vincolo univoco o di esclusione: slot già preso
                raise BookingError("Questo orario è appena stato prenotato da un'altra persona", 409) from None
            self._occupy_slot(conn, start.isoformat(), valid[start].isoformat(), code)
        return self._row(code)

    def start_payment(self, code: str, return_url: str) -> dict:
        p = self._row(code)
        if p["stato"] != "ATTESA_PAGAMENTO":
            raise BookingError("La prenotazione non è in attesa di pagamento", 409)
        if p["iuv"]:
            return p
        act = self.venue.catalog.get(p["attivita"])
        when = datetime.fromisoformat(p["inizio"]).strftime("%d/%m/%Y %H:%M")
        outcome = self.payments.create_payment_due(PaymentDue(
            booking_code=code, amount_cents=p["importo_cent"],
            reason=f"{act.name if act else p['attivita']} {self.venue.name} {when} pren. {code}"[:140],
            payer_tax_code=p["cf"] or "ANONIMO", payer_name=f"{p['nome']} {p['cognome']}",
            email=p["email"]), return_url)
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET iuv=%s, url_pagamento=%s, aggiornata_il=%s WHERE codice=%s",
                         (outcome.iuv, outcome.payment_url, self.now().isoformat(), code))
        return self._row(code)

    def check_payment(self, code: str) -> dict:
        """Idempotente: può essere chiamata dal ritorno utente, da polling o da notifica."""
        p = self._row(code)
        if p["stato"] == "CONFERMATA" or not p["iuv"]:
            return p
        if self.payments.is_paid(p["iuv"]):
            confirmed = False
            try:
                with self.db.tx() as conn:
                    # Si conferma anche se nel frattempo l'attesa era scaduta, purché lo slot sia ancora libero.
                    cur = conn.execute(
                        "UPDATE prenotazioni SET stato='CONFERMATA', aggiornata_il=%s "
                        "WHERE codice=%s AND stato IN ('ATTESA_PAGAMENTO','SCADUTA') "
                        f"AND NOT EXISTS (SELECT 1 FROM prenotazioni q "
                        f"WHERE q.inizio=prenotazioni.inizio AND q.codice<>prenotazioni.codice AND q.stato IN {ACTIVE_STATES})",
                        (self.now().isoformat(), code))
                    confirmed = cur.rowcount == 1
                    if confirmed:
                        self._occupy_slot(conn, p["inizio"], p["fine"], code)
            except (IntegrityError, BookingError):  # slot preso da altri nello stesso istante
                confirmed = False
            p = self._row(code)
            if confirmed:
                self.agenda.publish(p)
            elif p["stato"] != "CONFERMATA":
                # pagato ma slot perso: va rimborsato dall'ufficio, lo segnaliamo
                raise BookingError("Pagamento ricevuto ma l'orario non è più disponibile: "
                                         "l'Ufficio Sport ti contatterà per il rimborso o un nuovo orario", 409)
        return p

    # ------------------------------------------------------------ operazioni ufficio
    def confirm_manually(self, code: str, reference: str) -> dict:
        """L'ufficio registra un pagamento ricevuto allo sportello (modus operandi attuale)."""
        with self.db.tx() as conn:
            cur = conn.execute(
                "UPDATE prenotazioni SET stato='CONFERMATA', iuv=COALESCE(iuv, %s), aggiornata_il=%s "
                "WHERE codice=%s AND stato='ATTESA_PAGAMENTO'",
                (reference, self.now().isoformat(), code))
        if cur.rowcount != 1:
            raise BookingError("Prenotazione non confermabile", 409)
        p = self._row(code)
        self.agenda.publish(p)
        return p

    def block(self, start_iso: str, reason: str) -> dict:
        start = datetime.fromisoformat(start_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=TZ)
        valid = dict(self.scheduled_slots(start.date()))
        if start not in valid:
            raise BookingError("Orario non previsto dal calendario")
        code, now = new_code(self.venue.code_prefix), self.now().isoformat()
        with self.db.tx() as conn:
            self._expire_pending(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, "
                    "importo_cent, note, creata_il, aggiornata_il) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (code, "blocco", start.isoformat(), valid[start].isoformat(),
                     "BLOCCO", "UFFICIO", 0, reason[:280], now, now))
            except IntegrityError:
                raise BookingError("Slot già occupato", 409) from None
            self._occupy_slot(conn, start.isoformat(), valid[start].isoformat(), code)
        p = self._row(code)
        self.agenda.publish(p)
        return p

    def cancel(self, code: str, by_office: bool = False) -> dict:
        p = self._row(code)
        if p["stato"] not in ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO"):
            raise BookingError("Prenotazione non annullabile", 409)
        start = datetime.fromisoformat(p["inizio"])
        if (not by_office and p["stato"] == "CONFERMATA"
                and start - self.now() < timedelta(hours=self.cancel_hours)):
            raise BookingError(
                f"L'annullamento online è possibile fino a {self.cancel_hours} ore prima; contatta l'Ufficio Sport", 409)
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET stato='ANNULLATA', aggiornata_il=%s WHERE codice=%s",
                         (self.now().isoformat(), code))
            self._release_slot(conn, code)
        self.agenda.remove(code)
        return self._row(code)

    def items(self, from_: date | None = None, to_: date | None = None, states: tuple[str, ...] | None = None) -> list[dict]:
        sql, params_ = "SELECT * FROM prenotazioni WHERE 1=1", []
        if from_:
            sql += " AND inizio >= %s"; params_.append(from_.isoformat())
        if to_:
            sql += " AND inizio < %s"; params_.append((to_ + timedelta(days=1)).isoformat())
        if states:
            sql += f" AND stato IN ({','.join(['%s'] * len(states))})"; params_ += list(states)
        return [dict(r) for r in self.db.query(sql + " ORDER BY inizio", tuple(params_))]

    def bookings_of(self, tax_code: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM prenotazioni WHERE cf=%s AND stato<>'SCADUTA' ORDER BY inizio DESC", (tax_code,))]

    # ------------------------------------------------------------ ticket e custode
    def signature(self, code: str) -> str:
        return hmac.new(self._secret_value, code.encode(), hashlib.sha256).hexdigest()[:16]

    def token_ticket(self, code: str) -> str:
        return f"{code}.{self.signature(code)}"

    def check_in(self, token: str) -> dict:
        try:
            code, signature = token.rsplit(".", 1)
        except ValueError:
            raise BookingError("QR non valido") from None
        if not hmac.compare_digest(signature, self.signature(code)):
            raise BookingError("QR non valido o contraffatto", 403)
        p = self._row(code)
        if p["stato"] == "UTILIZZATA":
            return {**p, "esito": "GIA_REGISTRATA"}
        if p["stato"] != "CONFERMATA":
            raise BookingError(f"Prenotazione non valida (stato: {p['stato']})", 409)
        start = datetime.fromisoformat(p["inizio"])
        if abs(start - self.now()) > timedelta(hours=2):
            return {**p, "esito": "FUORI_ORARIO"}
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET stato='UTILIZZATA', aggiornata_il=%s WHERE codice=%s",
                         (self.now().isoformat(), code))
        return {**self._row(code), "esito": "OK"}
