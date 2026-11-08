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
from .adapters.identity import Cittadino
from .adapters.payments import Dovuto, PaymentGateway
from .catalog import ATTIVITA, Spazio
from .db import Database

TZ = ZoneInfo("Europe/Rome")
STATI_ATTIVI = ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO", "UTILIZZATA")
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O/1/I: si dettano al telefono


class ErrorePrenotazione(Exception):
    """Errore di dominio con messaggio comprensibile per il cittadino."""

    def __init__(self, messaggio: str, codice_http: int = 400):
        super().__init__(messaggio)
        self.messaggio, self.codice_http = messaggio, codice_http


# stato in banca dati -> stato mostrato al cittadino
STATO_PUBBLICO = {"LIBERO": "libero", "ATTESA_PAGAMENTO": "in_pagamento", "CONFERMATA": "occupato",
                  "UTILIZZATA": "occupato", "BLOCCO": "riservato"}


@dataclass
class Slot:
    inizio: datetime
    fine: datetime
    stato: str                 # libero | occupato | in_pagamento | riservato | passato

    @property
    def libero(self) -> bool:
        return self.stato == "libero"

    def to_dict(self) -> dict:
        return {"inizio": self.inizio.isoformat(), "fine": self.fine.isoformat(),
                "ora": self.inizio.strftime("%H:%M"), "libero": self.libero, "stato": self.stato}


def nuovo_codice(prefisso: str = "GDC") -> str:
    parte = lambda: "".join(secrets.choice(_ALFABETO) for _ in range(4))  # noqa: E731
    return f"{prefisso}-{parte()}-{parte()}"


class ServizioPrenotazioni:
    def __init__(self, db: Database, pagamenti: PaymentGateway, agenda: AgendaSync,
                 segreto_ticket: str, ttl_attesa_min: int = 15,
                 ore_minime_annullamento: int = 24,
                 adesso: Callable[[], datetime] | None = None, spazio: Spazio | None = None):
        self.db, self.pagamenti, self.agenda = db, pagamenti, agenda
        self.spazio = spazio or Spazio()
        self._segreto = segreto_ticket.encode()
        self.ttl = timedelta(minutes=ttl_attesa_min)
        self.ore_annullamento = ore_minime_annullamento
        self._adesso = adesso or (lambda: datetime.now(TZ))

    # ------------------------------------------------------------ utilità
    def adesso(self) -> datetime:
        return self._adesso()

    def _scadi_attese(self, conn) -> None:
        limite = (self.adesso() - self.ttl).isoformat()
        for riga in conn.execute("SELECT codice FROM prenotazioni "
                                 "WHERE stato='ATTESA_PAGAMENTO' AND creata_il < %s", (limite,)).fetchall():
            codice = riga["codice"]
            self._libera_slot(conn, codice)
            conn.execute("UPDATE prenotazioni SET stato='SCADUTA', aggiornata_il=%s WHERE codice=%s",
                         (self.adesso().isoformat(), codice))

    # ------------------------------------------------------------ tabella slot
    def _genera_slot(self, conn, giorno: date) -> None:
        conn.cursor().executemany(
            "INSERT INTO slot (inizio, fine, aggiornato_il) VALUES (%s,%s,%s) ON CONFLICT (inizio) DO NOTHING",
            [(a.isoformat(), b.isoformat(), self.adesso().isoformat()) for a, b in self.slot_teorici(giorno)])

    def _occupa_slot(self, conn, inizio: str, fine: str, codice: str) -> None:
        """Registra il numero di prenotazione sulla riga dello slot."""
        cur = conn.execute(
            "INSERT INTO slot (inizio, fine, codice_prenotazione, aggiornato_il) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (inizio) DO UPDATE SET codice_prenotazione=excluded.codice_prenotazione, "
            "aggiornato_il=excluded.aggiornato_il "
            "WHERE slot.codice_prenotazione IS NULL OR slot.codice_prenotazione=excluded.codice_prenotazione",
            (inizio, fine, codice, self.adesso().isoformat()))
        if cur.rowcount != 1:
            raise ErrorePrenotazione("Questo orario è appena stato prenotato da un'altra persona", 409)

    def _libera_slot(self, conn, codice: str) -> None:
        conn.execute("UPDATE slot SET codice_prenotazione=NULL, aggiornato_il=%s WHERE codice_prenotazione=%s",
                     (self.adesso().isoformat(), codice))

    def _riga(self, codice: str) -> dict:
        r = self.db.query("SELECT * FROM prenotazioni WHERE codice=%s", (codice,))
        if not r:
            raise ErrorePrenotazione("Prenotazione non trovata", 404)
        return dict(r[0])

    # ------------------------------------------------------------ disponibilità
    def slot_teorici(self, giorno: date) -> list[tuple[datetime, datetime]]:
        out = []
        for t in self.spazio.calendario.get(giorno.weekday(), ()):
            inizio = datetime.combine(giorno, t, tzinfo=TZ)
            out.append((inizio, inizio + timedelta(minutes=self.spazio.durata_min)))
        return out

    def _giorni(self, dal: date | None, giorni: int) -> list[date]:
        oggi = self.adesso().date()
        dal = max(dal or oggi, oggi)
        ultimo = oggi + timedelta(days=self.spazio.preavviso_giorni)
        return [g for g in (dal + timedelta(days=i) for i in range(giorni)) if g <= ultimo]

    def occupazione(self, dal: date | None = None, giorni: int = 7) -> list[dict]:
        """Calendario con, per ogni slot, il numero di prenotazione che lo occupa (uso ufficio)."""
        elenco = self._giorni(dal, giorni)
        with self.db.tx() as conn:
            self._scadi_attese(conn)
            for g in elenco:
                self._genera_slot(conn, g)
        if not elenco:
            return []
        righe = {r["inizio"]: dict(r) for r in self.db.query(
            "SELECT * FROM v_occupazione WHERE inizio >= %s AND inizio < %s",
            (elenco[0].isoformat(), (elenco[-1] + timedelta(days=1)).isoformat()))}
        risultato = []
        for g in elenco:
            slot = []
            for a, b in self.slot_teorici(g):
                r = righe.get(a.isoformat(), {"stato": "LIBERO", "codice_prenotazione": None})
                stato = "passato" if a <= self.adesso() and r["stato"] == "LIBERO" else STATO_PUBBLICO[r["stato"]]
                slot.append({**Slot(a, b, stato).to_dict(), "codice": r["codice_prenotazione"],
                             "stato_prenotazione": r["stato"] if r["codice_prenotazione"] else None,
                             "attivita": r.get("attivita"), "intestatario":
                                 " ".join(x for x in (r.get("cognome"), r.get("nome")) if x) or r.get("note")})
            risultato.append({"data": g.isoformat(), "slot": slot, "liberi": sum(s["libero"] for s in slot)})
        return risultato

    def disponibilita(self, dal: date | None = None, giorni: int = 7) -> list[dict]:
        """Calendario pubblico: stato di ogni slot, senza numeri di prenotazione né nomi."""
        pubblici = ("inizio", "fine", "ora", "libero", "stato")
        return [{**g, "slot": [{k: s[k] for k in pubblici} for s in g["slot"]]}
                for g in self.occupazione(dal, giorni)]

    # ------------------------------------------------------------ prenotazione
    def prenota(self, attivita: str, inizio_iso: str, cittadino: Cittadino,
                telefono: str | None = None, note: str | None = None,
                canale: str = "ONLINE") -> dict:
        if attivita not in self.spazio.attivita:
            raise ErrorePrenotazione("Attività non disponibile in questo luogo")
        att = ATTIVITA[attivita]
        try:
            inizio = datetime.fromisoformat(inizio_iso)
        except ValueError:
            raise ErrorePrenotazione("Orario non valido") from None
        if inizio.tzinfo is None:
            inizio = inizio.replace(tzinfo=TZ)
        validi = {a: b for a, b in self.slot_teorici(inizio.date())}
        if inizio not in validi:
            raise ErrorePrenotazione("L'orario scelto non è previsto dal calendario")
        if inizio <= self.adesso():
            raise ErrorePrenotazione("Non è possibile prenotare un orario passato")
        if inizio.date() > self.adesso().date() + timedelta(days=self.spazio.preavviso_giorni):
            raise ErrorePrenotazione(f"Si può prenotare al massimo {self.spazio.preavviso_giorni} giorni prima")

        ora = self.adesso().isoformat()
        codice = nuovo_codice(self.spazio.prefisso_codice)
        with self.db.tx() as conn:
            self._scadi_attese(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, "
                    "importo_cent, cf, nome, cognome, email, telefono, note, creata_il, aggiornata_il) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (codice, attivita, inizio.isoformat(), validi[inizio].isoformat(),
                     "ATTESA_PAGAMENTO", canale, att.tariffa_cent, cittadino.cf, cittadino.nome,
                     cittadino.cognome, cittadino.email, telefono, (note or "")[:280], ora, ora))
            except IntegrityError:  # vincolo univoco o di esclusione: slot già preso
                raise ErrorePrenotazione("Questo orario è appena stato prenotato da un'altra persona", 409) from None
            self._occupa_slot(conn, inizio.isoformat(), validi[inizio].isoformat(), codice)
        return self._riga(codice)

    def avvia_pagamento(self, codice: str, url_ritorno: str) -> dict:
        p = self._riga(codice)
        if p["stato"] != "ATTESA_PAGAMENTO":
            raise ErrorePrenotazione("La prenotazione non è in attesa di pagamento", 409)
        if p["iuv"]:
            return p
        att = ATTIVITA[p["attivita"]]
        quando = datetime.fromisoformat(p["inizio"]).strftime("%d/%m/%Y %H:%M")
        esito = self.pagamenti.crea_dovuto(Dovuto(
            codice_prenotazione=codice, importo_cent=p["importo_cent"],
            causale=f"{att.nome} {self.spazio.nome} {quando} pren. {codice}"[:140],
            cf_debitore=p["cf"] or "ANONIMO", nome_debitore=f"{p['nome']} {p['cognome']}",
            email=p["email"]), url_ritorno)
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET iuv=%s, url_pagamento=%s, aggiornata_il=%s WHERE codice=%s",
                         (esito.iuv, esito.url_pagamento, self.adesso().isoformat(), codice))
        return self._riga(codice)

    def verifica_pagamento(self, codice: str) -> dict:
        """Idempotente: può essere chiamata dal ritorno utente, da polling o da notifica."""
        p = self._riga(codice)
        if p["stato"] == "CONFERMATA" or not p["iuv"]:
            return p
        if self.pagamenti.verifica_pagato(p["iuv"]):
            confermata = False
            try:
                with self.db.tx() as conn:
                    # Si conferma anche se nel frattempo l'attesa era scaduta, purché lo slot sia ancora libero.
                    cur = conn.execute(
                        "UPDATE prenotazioni SET stato='CONFERMATA', aggiornata_il=%s "
                        "WHERE codice=%s AND stato IN ('ATTESA_PAGAMENTO','SCADUTA') "
                        f"AND NOT EXISTS (SELECT 1 FROM prenotazioni q "
                        f"WHERE q.inizio=prenotazioni.inizio AND q.codice<>prenotazioni.codice AND q.stato IN {STATI_ATTIVI})",
                        (self.adesso().isoformat(), codice))
                    confermata = cur.rowcount == 1
                    if confermata:
                        self._occupa_slot(conn, p["inizio"], p["fine"], codice)
            except (IntegrityError, ErrorePrenotazione):  # slot preso da altri nello stesso istante
                confermata = False
            p = self._riga(codice)
            if confermata:
                self.agenda.pubblica(p)
            elif p["stato"] != "CONFERMATA":
                # pagato ma slot perso: va rimborsato dall'ufficio, lo segnaliamo
                raise ErrorePrenotazione("Pagamento ricevuto ma l'orario non è più disponibile: "
                                         "l'Ufficio Sport ti contatterà per il rimborso o un nuovo orario", 409)
        return p

    # ------------------------------------------------------------ operazioni ufficio
    def conferma_manuale(self, codice: str, riferimento: str) -> dict:
        """L'ufficio registra un pagamento ricevuto allo sportello (modus operandi attuale)."""
        with self.db.tx() as conn:
            cur = conn.execute(
                "UPDATE prenotazioni SET stato='CONFERMATA', iuv=COALESCE(iuv, %s), aggiornata_il=%s "
                "WHERE codice=%s AND stato='ATTESA_PAGAMENTO'",
                (riferimento, self.adesso().isoformat(), codice))
        if cur.rowcount != 1:
            raise ErrorePrenotazione("Prenotazione non confermabile", 409)
        p = self._riga(codice)
        self.agenda.pubblica(p)
        return p

    def blocca(self, inizio_iso: str, motivo: str) -> dict:
        inizio = datetime.fromisoformat(inizio_iso)
        if inizio.tzinfo is None:
            inizio = inizio.replace(tzinfo=TZ)
        validi = dict(self.slot_teorici(inizio.date()))
        if inizio not in validi:
            raise ErrorePrenotazione("Orario non previsto dal calendario")
        codice, ora = nuovo_codice(self.spazio.prefisso_codice), self.adesso().isoformat()
        with self.db.tx() as conn:
            self._scadi_attese(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, attivita, inizio, fine, stato, canale, "
                    "importo_cent, note, creata_il, aggiornata_il) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (codice, "blocco", inizio.isoformat(), validi[inizio].isoformat(),
                     "BLOCCO", "UFFICIO", 0, motivo[:280], ora, ora))
            except IntegrityError:
                raise ErrorePrenotazione("Slot già occupato", 409) from None
            self._occupa_slot(conn, inizio.isoformat(), validi[inizio].isoformat(), codice)
        p = self._riga(codice)
        self.agenda.pubblica(p)
        return p

    def annulla(self, codice: str, da_ufficio: bool = False) -> dict:
        p = self._riga(codice)
        if p["stato"] not in ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO"):
            raise ErrorePrenotazione("Prenotazione non annullabile", 409)
        inizio = datetime.fromisoformat(p["inizio"])
        if (not da_ufficio and p["stato"] == "CONFERMATA"
                and inizio - self.adesso() < timedelta(hours=self.ore_annullamento)):
            raise ErrorePrenotazione(
                f"L'annullamento online è possibile fino a {self.ore_annullamento} ore prima; contatta l'Ufficio Sport", 409)
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET stato='ANNULLATA', aggiornata_il=%s WHERE codice=%s",
                         (self.adesso().isoformat(), codice))
            self._libera_slot(conn, codice)
        self.agenda.rimuovi(codice)
        return self._riga(codice)

    def elenco(self, dal: date | None = None, al: date | None = None, stati: tuple[str, ...] | None = None) -> list[dict]:
        sql, par = "SELECT * FROM prenotazioni WHERE 1=1", []
        if dal:
            sql += " AND inizio >= %s"; par.append(dal.isoformat())
        if al:
            sql += " AND inizio < %s"; par.append((al + timedelta(days=1)).isoformat())
        if stati:
            sql += f" AND stato IN ({','.join(['%s'] * len(stati))})"; par += list(stati)
        return [dict(r) for r in self.db.query(sql + " ORDER BY inizio", tuple(par))]

    def prenotazioni_di(self, cf: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM prenotazioni WHERE cf=%s AND stato<>'SCADUTA' ORDER BY inizio DESC", (cf,))]

    # ------------------------------------------------------------ ticket e custode
    def firma(self, codice: str) -> str:
        return hmac.new(self._segreto, codice.encode(), hashlib.sha256).hexdigest()[:16]

    def token_ticket(self, codice: str) -> str:
        return f"{codice}.{self.firma(codice)}"

    def check_in(self, token: str) -> dict:
        try:
            codice, firma = token.rsplit(".", 1)
        except ValueError:
            raise ErrorePrenotazione("QR non valido") from None
        if not hmac.compare_digest(firma, self.firma(codice)):
            raise ErrorePrenotazione("QR non valido o contraffatto", 403)
        p = self._riga(codice)
        if p["stato"] == "UTILIZZATA":
            return {**p, "esito": "GIA_REGISTRATA"}
        if p["stato"] != "CONFERMATA":
            raise ErrorePrenotazione(f"Prenotazione non valida (stato: {p['stato']})", 409)
        inizio = datetime.fromisoformat(p["inizio"])
        if abs(inizio - self.adesso()) > timedelta(hours=2):
            return {**p, "esito": "FUORI_ORARIO"}
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET stato='UTILIZZATA', aggiornata_il=%s WHERE codice=%s",
                         (self.adesso().isoformat(), codice))
        return {**self._riga(codice), "esito": "OK"}
