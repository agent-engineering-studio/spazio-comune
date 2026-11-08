"""Persistenza minimale su SQLite (sostituibile con PostgreSQL in produzione).

L'indice univoco parziale impedisce a livello di database la doppia
prenotazione dello stesso slot: è l'invariante principale del sistema.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS prenotazioni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codice          TEXT NOT NULL UNIQUE,
    impianto        TEXT NOT NULL,
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
    ON prenotazioni (impianto, inizio)
    WHERE stato IN ('ATTESA_PAGAMENTO','CONFERMATA','BLOCCO','UTILIZZATA');
CREATE INDEX IF NOT EXISTS ix_iuv ON prenotazioni (iuv);
CREATE INDEX IF NOT EXISTS ix_inizio ON prenotazioni (inizio);
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
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

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
