"""Logica di dominio delle prenotazioni.

Ciclo di vita:
  ATTESA_PAGAMENTO --(esito pagoPA positivo)--> CONFERMATA --(check-in custode)--> UTILIZZATA
         |                                          |
         +--(15 min senza pagamento)--> SCADUTA     +--(annullamento)--> ANNULLATA
  BLOCCO: slot riservato dall'ufficio (manutenzione, eventi, società sportive)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .adapters.agenda import AgendaSync
from .adapters.identity import Cittadino
from .adapters.payments import Dovuto, PaymentGateway
from .catalog import ATTIVITA, IMPIANTI, Impianto
from .db import Database

TZ = ZoneInfo("Europe/Rome")
STATI_ATTIVI = ("ATTESA_PAGAMENTO", "CONFERMATA", "BLOCCO", "UTILIZZATA")
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O/1/I: si dettano al telefono


class ErrorePrenotazione(Exception):
    """Errore di dominio con messaggio comprensibile per il cittadino."""

    def __init__(self, messaggio: str, codice_http: int = 400):
        super().__init__(messaggio)
        self.messaggio, self.codice_http = messaggio, codice_http


@dataclass
class Slot:
    inizio: datetime
    fine: datetime
    libero: bool

    def to_dict(self) -> dict:
        return {"inizio": self.inizio.isoformat(), "fine": self.fine.isoformat(),
                "ora": self.inizio.strftime("%H:%M"), "libero": self.libero}


def nuovo_codice() -> str:
    parte = lambda: "".join(secrets.choice(_ALFABETO) for _ in range(4))  # noqa: E731
    return f"GDC-{parte()}-{parte()}"


class ServizioPrenotazioni:
    def __init__(self, db: Database, pagamenti: PaymentGateway, agenda: AgendaSync,
                 segreto_ticket: str, ttl_attesa_min: int = 15,
                 ore_minime_annullamento: int = 24,
                 adesso: Callable[[], datetime] | None = None):
        self.db, self.pagamenti, self.agenda = db, pagamenti, agenda
        self._segreto = segreto_ticket.encode()
        self.ttl = timedelta(minutes=ttl_attesa_min)
        self.ore_annullamento = ore_minime_annullamento
        self._adesso = adesso or (lambda: datetime.now(TZ))

    # ------------------------------------------------------------ utilità
    def adesso(self) -> datetime:
        return self._adesso()

    def _impianto(self, codice: str) -> Impianto:
        try:
            return IMPIANTI[codice]
        except KeyError:
            raise ErrorePrenotazione("Impianto non trovato", 404) from None

    def _scadi_attese(self, conn) -> None:
        limite = (self.adesso() - self.ttl).isoformat()
        conn.execute(
            "UPDATE prenotazioni SET stato='SCADUTA', aggiornata_il=? "
            "WHERE stato='ATTESA_PAGAMENTO' AND creata_il < ?",
            (self.adesso().isoformat(), limite))

    def _riga(self, codice: str) -> dict:
        r = self.db.query("SELECT * FROM prenotazioni WHERE codice=?", (codice,))
        if not r:
            raise ErrorePrenotazione("Prenotazione non trovata", 404)
        return dict(r[0])

    # ------------------------------------------------------------ disponibilità
    def slot_teorici(self, imp: Impianto, giorno: date) -> list[tuple[datetime, datetime]]:
        out = []
        for t in imp.calendario.get(giorno.weekday(), ()):
            inizio = datetime.combine(giorno, t, tzinfo=TZ)
            out.append((inizio, inizio + timedelta(minutes=imp.durata_min)))
        return out

    def disponibilita(self, impianto: str, dal: date | None = None, giorni: int = 7) -> list[dict]:
        imp = self._impianto(impianto)
        oggi = self.adesso().date()
        dal = max(dal or oggi, oggi)
        ultimo = oggi + timedelta(days=imp.preavviso_giorni)
        with self.db.tx() as conn:
            self._scadi_attese(conn)
        occupati = {r["inizio"] for r in self.db.query(
            f"SELECT inizio FROM prenotazioni WHERE impianto=? AND stato IN {STATI_ATTIVI}",
            (impianto,))}
        risultato = []
        for i in range(giorni):
            g = dal + timedelta(days=i)
            if g > ultimo:
                break
            slot = [Slot(a, b, a.isoformat() not in occupati and a > self.adesso())
                    for a, b in self.slot_teorici(imp, g)]
            risultato.append({"data": g.isoformat(), "slot": [s.to_dict() for s in slot],
                              "liberi": sum(s.libero for s in slot)})
        return risultato

    # ------------------------------------------------------------ prenotazione
    def prenota(self, impianto: str, attivita: str, inizio_iso: str, cittadino: Cittadino,
                telefono: str | None = None, note: str | None = None,
                canale: str = "ONLINE") -> dict:
        imp = self._impianto(impianto)
        if attivita not in imp.attivita:
            raise ErrorePrenotazione("Attività non disponibile su questo impianto")
        att = ATTIVITA[attivita]
        try:
            inizio = datetime.fromisoformat(inizio_iso)
        except ValueError:
            raise ErrorePrenotazione("Orario non valido") from None
        if inizio.tzinfo is None:
            inizio = inizio.replace(tzinfo=TZ)
        validi = {a: b for a, b in self.slot_teorici(imp, inizio.date())}
        if inizio not in validi:
            raise ErrorePrenotazione("L'orario scelto non è previsto dal calendario dell'impianto")
        if inizio <= self.adesso():
            raise ErrorePrenotazione("Non è possibile prenotare un orario passato")
        if inizio.date() > self.adesso().date() + timedelta(days=imp.preavviso_giorni):
            raise ErrorePrenotazione(f"Si può prenotare al massimo {imp.preavviso_giorni} giorni prima")

        ora = self.adesso().isoformat()
        codice = nuovo_codice()
        with self.db.tx() as conn:
            self._scadi_attese(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, impianto, attivita, inizio, fine, stato, canale, "
                    "importo_cent, cf, nome, cognome, email, telefono, note, creata_il, aggiornata_il) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (codice, impianto, attivita, inizio.isoformat(), validi[inizio].isoformat(),
                     "ATTESA_PAGAMENTO", canale, att.tariffa_cent, cittadino.cf, cittadino.nome,
                     cittadino.cognome, cittadino.email, telefono, (note or "")[:280], ora, ora))
            except Exception as e:  # violazione indice univoco = slot già preso
                if "UNIQUE" in str(e):
                    raise ErrorePrenotazione("Questo orario è appena stato prenotato da un'altra persona", 409) from None
                raise
        return self._riga(codice)

    def avvia_pagamento(self, codice: str, url_ritorno: str) -> dict:
        p = self._riga(codice)
        if p["stato"] != "ATTESA_PAGAMENTO":
            raise ErrorePrenotazione("La prenotazione non è in attesa di pagamento", 409)
        if p["iuv"]:
            return p
        imp, att = IMPIANTI[p["impianto"]], ATTIVITA[p["attivita"]]
        quando = datetime.fromisoformat(p["inizio"]).strftime("%d/%m/%Y %H:%M")
        esito = self.pagamenti.crea_dovuto(Dovuto(
            codice_prenotazione=codice, importo_cent=p["importo_cent"],
            causale=f"{att.nome} {imp.nome} {quando} pren. {codice}"[:140],
            cf_debitore=p["cf"] or "ANONIMO", nome_debitore=f"{p['nome']} {p['cognome']}",
            email=p["email"]), url_ritorno)
        with self.db.tx() as conn:
            conn.execute("UPDATE prenotazioni SET iuv=?, url_pagamento=?, aggiornata_il=? WHERE codice=?",
                         (esito.iuv, esito.url_pagamento, self.adesso().isoformat(), codice))
        return self._riga(codice)

    def verifica_pagamento(self, codice: str) -> dict:
        """Idempotente: può essere chiamata dal ritorno utente, da polling o da notifica."""
        p = self._riga(codice)
        if p["stato"] == "CONFERMATA" or not p["iuv"]:
            return p
        if self.pagamenti.verifica_pagato(p["iuv"]):
            with self.db.tx() as conn:
                # Si conferma anche se nel frattempo l'attesa era scaduta, purché lo slot sia ancora libero.
                cur = conn.execute(
                    "UPDATE prenotazioni SET stato='CONFERMATA', aggiornata_il=? "
                    "WHERE codice=? AND stato IN ('ATTESA_PAGAMENTO','SCADUTA') "
                    f"AND NOT EXISTS (SELECT 1 FROM prenotazioni q WHERE q.impianto=prenotazioni.impianto "
                    f"AND q.inizio=prenotazioni.inizio AND q.codice<>prenotazioni.codice AND q.stato IN {STATI_ATTIVI})",
                    (self.adesso().isoformat(), codice))
            p = self._riga(codice)
            if cur.rowcount == 1:
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
                "UPDATE prenotazioni SET stato='CONFERMATA', iuv=COALESCE(iuv, ?), aggiornata_il=? "
                "WHERE codice=? AND stato='ATTESA_PAGAMENTO'",
                (riferimento, self.adesso().isoformat(), codice))
        if cur.rowcount != 1:
            raise ErrorePrenotazione("Prenotazione non confermabile", 409)
        p = self._riga(codice)
        self.agenda.pubblica(p)
        return p

    def blocca(self, impianto: str, inizio_iso: str, motivo: str) -> dict:
        imp = self._impianto(impianto)
        inizio = datetime.fromisoformat(inizio_iso)
        if inizio.tzinfo is None:
            inizio = inizio.replace(tzinfo=TZ)
        validi = dict(self.slot_teorici(imp, inizio.date()))
        if inizio not in validi:
            raise ErrorePrenotazione("Orario non previsto dal calendario")
        codice, ora = nuovo_codice(), self.adesso().isoformat()
        with self.db.tx() as conn:
            self._scadi_attese(conn)
            try:
                conn.execute(
                    "INSERT INTO prenotazioni (codice, impianto, attivita, inizio, fine, stato, canale, "
                    "importo_cent, note, creata_il, aggiornata_il) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (codice, impianto, "blocco", inizio.isoformat(), validi[inizio].isoformat(),
                     "BLOCCO", "UFFICIO", 0, motivo[:280], ora, ora))
            except Exception as e:
                if "UNIQUE" in str(e):
                    raise ErrorePrenotazione("Slot già occupato", 409) from None
                raise
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
            conn.execute("UPDATE prenotazioni SET stato='ANNULLATA', aggiornata_il=? WHERE codice=?",
                         (self.adesso().isoformat(), codice))
        self.agenda.rimuovi(codice)
        return self._riga(codice)

    def elenco(self, dal: date | None = None, al: date | None = None, stati: tuple[str, ...] | None = None) -> list[dict]:
        sql, par = "SELECT * FROM prenotazioni WHERE 1=1", []
        if dal:
            sql += " AND inizio >= ?"; par.append(dal.isoformat())
        if al:
            sql += " AND inizio < ?"; par.append((al + timedelta(days=1)).isoformat())
        if stati:
            sql += f" AND stato IN ({','.join('?' * len(stati))})"; par += list(stati)
        return [dict(r) for r in self.db.query(sql + " ORDER BY inizio", tuple(par))]

    def prenotazioni_di(self, cf: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM prenotazioni WHERE cf=? AND stato<>'SCADUTA' ORDER BY inizio DESC", (cf,))]

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
            conn.execute("UPDATE prenotazioni SET stato='UTILIZZATA', aggiornata_il=? WHERE codice=?",
                         (self.adesso().isoformat(), codice))
        return {**self._riga(codice), "esito": "OK"}
