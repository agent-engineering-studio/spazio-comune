"""Persistenza su SQLite: un file nel volume Docker "dati" (/data/prenota.db).

Due tabelle:
  - prenotazioni: una riga per prenotazione, con il numero (codice) e lo stato;
  - slot: una riga per ogni orario del calendario del luogo, con il numero
    della prenotazione che lo occupa (NULL se libero).
La vista v_occupazione le unisce per una lettura immediata.

L'indice univoco parziale sulle prenotazioni e il vincolo UNIQUE su
slot.codice_prenotazione impediscono a livello di database la doppia
prenotazione dello stesso orario: è l'invariante principale del sistema.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS prenotazioni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codice          TEXT NOT NULL UNIQUE,      -- numero di prenotazione, es. GDC-7KQ2-M4XP
    attivita        TEXT NOT NULL,
    inizio          TEXT NOT NULL,             -- ISO 8601, ora locale Europe/Rome
    fine            TEXT NOT NULL,
    stato           TEXT NOT NULL CHECK (stato IN
                      ('ATTESA_PAGAMENTO','CONFERMATA','ANNULLATA','SCADUTA','BLOCCO','UTILIZZATA')),
    canale          TEXT NOT NULL CHECK (canale IN ('ONLINE','SPORTELLO','UFFICIO')),
    importo_cent    INTEGER NOT NULL CHECK (importo_cent >= 0),
    iuv             TEXT,                      -- Identificativo Univoco di Versamento pagoPA
    url_pagamento   TEXT,
    cf              TEXT,
    nome            TEXT,
    cognome         TEXT,
    email           TEXT,
    telefono        TEXT,
    note            TEXT,
    creata_il       TEXT NOT NULL,
    aggiornata_il   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_slot_attivo
    ON prenotazioni (inizio)
    WHERE stato IN ('ATTESA_PAGAMENTO','CONFERMATA','BLOCCO','UTILIZZATA');
CREATE INDEX IF NOT EXISTS ix_iuv ON prenotazioni (iuv);
CREATE INDEX IF NOT EXISTS ix_cf ON prenotazioni (cf);

CREATE TABLE IF NOT EXISTS slot (
    inizio               TEXT PRIMARY KEY,     -- ISO 8601, ora locale Europe/Rome
    fine                 TEXT NOT NULL,
    codice_prenotazione  TEXT UNIQUE REFERENCES prenotazioni (codice),  -- NULL = libero
    aggiornato_il        TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS v_occupazione AS
SELECT s.inizio, s.fine,
       s.codice_prenotazione,
       CASE WHEN s.codice_prenotazione IS NULL THEN 'LIBERO' ELSE p.stato END AS stato,
       p.attivita, p.cognome, p.nome, p.canale, p.iuv, p.note
FROM slot s LEFT JOIN prenotazioni p ON p.codice = s.codice_prenotazione;
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migra_da_v1()
        self._conn.executescript(SCHEMA)
        if self._da_ricostruire_slot:
            self._conn.execute(
                "INSERT OR IGNORE INTO slot (inizio, fine, codice_prenotazione, aggiornato_il) "
                "SELECT inizio, fine, codice, aggiornata_il FROM prenotazioni "
                "WHERE stato IN ('ATTESA_PAGAMENTO','CONFERMATA','BLOCCO','UTILIZZATA')")
        self._lock = threading.Lock()

    def _migra_da_v1(self) -> None:
        """La prima versione aveva una colonna "impianto" e nessuna tabella slot."""
        colonne = {r[1] for r in self._conn.execute("PRAGMA table_info(prenotazioni)")}
        self._da_ricostruire_slot = "impianto" in colonne
        if self._da_ricostruire_slot:
            self._conn.execute("DROP INDEX IF EXISTS ux_slot_attivo")
            self._conn.execute("ALTER TABLE prenotazioni DROP COLUMN impianto")

    @contextmanager
    def tx(self):
        """Transazione serializzata (BEGIN IMMEDIATE) per evitare race sugli slot."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))
