"""Persistenza su PostgreSQL (container spazio-comune-db, o servizio gestito in produzione).

Due tabelle:
  - prenotazioni: una riga per prenotazione, con il numero (codice) e lo stato;
  - slot: una riga per ogni orario del calendario del luogo, con il numero
    della prenotazione che lo occupa (NULL se libero).
La vista v_occupazione le unisce per una lettura immediata.

La doppia prenotazione è impedita dal database, con tre vincoli indipendenti:
  - indice univoco parziale sull'inizio delle prenotazioni attive;
  - vincolo di esclusione sugli intervalli (tstzrange): due prenotazioni attive
    non possono sovrapporsi nel tempo, nemmeno con durate diverse;
  - UNIQUE su slot.codice_prenotazione.

Gli orari sono timestamptz; verso l'applicazione escono come stringhe ISO 8601
con il fuso Europe/Rome, così il resto del codice resta indipendente dal driver.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ATTIVI = "('ATTESA_PAGAMENTO','CONFERMATA','BLOCCO','UTILIZZATA')"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS prenotazioni (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codice          TEXT NOT NULL UNIQUE,      -- numero di prenotazione, es. GDC-7KQ2-M4XP
    attivita        TEXT NOT NULL,
    inizio          TIMESTAMPTZ NOT NULL,
    fine            TIMESTAMPTZ NOT NULL CHECK (fine > inizio),
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
    creata_il       TIMESTAMPTZ NOT NULL,
    aggiornata_il   TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_slot_attivo ON prenotazioni (inizio) WHERE stato IN {ATTIVI};
CREATE INDEX IF NOT EXISTS ix_iuv ON prenotazioni (iuv);
CREATE INDEX IF NOT EXISTS ix_cf ON prenotazioni (cf);
DO $$ BEGIN
    ALTER TABLE prenotazioni ADD CONSTRAINT ex_nessuna_sovrapposizione
        EXCLUDE USING gist (tstzrange(inizio, fine) WITH &&) WHERE (stato IN {ATTIVI});
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS slot (
    inizio               TIMESTAMPTZ PRIMARY KEY,
    fine                 TIMESTAMPTZ NOT NULL CHECK (fine > inizio),
    codice_prenotazione  TEXT UNIQUE REFERENCES prenotazioni (codice),  -- NULL = libero
    aggiornato_il        TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW v_occupazione AS
SELECT s.inizio, s.fine,
       s.codice_prenotazione,
       CASE WHEN s.codice_prenotazione IS NULL THEN 'LIBERO' ELSE p.stato END AS stato,
       p.attivita, p.cognome, p.nome, p.canale, p.iuv, p.note
FROM slot s LEFT JOIN prenotazioni p ON p.codice = s.codice_prenotazione;
"""

_NOME_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _in_uscita(riga: dict) -> dict:
    """timestamptz -> ISO 8601 (Europe/Rome, fuso della sessione)."""
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in riga.items()}


class Database:
    """Pool di connessioni PostgreSQL.

    `schema` separa più basi dati nello stesso database (es. "demo", o uno schema
    per test); di norma è "public".
    """

    def __init__(self, url: str, schema: str = "public", max_connessioni: int = 10):
        if not _NOME_SCHEMA.match(schema):
            raise ValueError(f"Nome di schema non valido: {schema!r}")
        self.schema = schema
        self._pool = ConnectionPool(
            url, min_size=1, max_size=max_connessioni, open=True, timeout=10,
            kwargs={"autocommit": True, "row_factory": dict_row,
                    "options": f"-c timezone=Europe/Rome -c search_path={schema}"})
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"spazio-comune:{schema}",))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            conn.execute(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        """Transazione: commit all'uscita, rollback su eccezione."""
        with self._pool.connection() as conn, conn.transaction():
            yield conn

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._pool.connection() as conn:
            return [_in_uscita(r) for r in conn.execute(sql, params).fetchall()]

    def azzera(self) -> None:
        """Cancella tutti i dati dello schema (istanza demo, test)."""
        with self.tx() as conn:
            conn.execute("TRUNCATE slot, prenotazioni RESTART IDENTITY CASCADE")

    def elimina_schema(self) -> None:
        if self.schema != "public":
            with self._pool.connection() as conn:
                conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')

    def chiudi(self) -> None:
        self._pool.close()
