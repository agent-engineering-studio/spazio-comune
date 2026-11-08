import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

RADICE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RADICE / "app"))
sys.path.insert(0, str(RADICE / "inference"))

from prenota.adapters.agenda import NoopAgenda  # noqa: E402
from prenota.adapters.identity import Cittadino  # noqa: E402
from prenota.adapters.payments import MockPagoPA  # noqa: E402
from prenota.ai import AssistenteIA  # noqa: E402
from prenota.booking import TZ, ServizioPrenotazioni  # noqa: E402
from prenota.config import Settings  # noqa: E402
from prenota.db import Database  # noqa: E402
from prenota.main import create_app  # noqa: E402


# PostgreSQL per i test: in Docker è il servizio "db"; in locale va indicato.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def nuovo_schema() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


def pytest_configure(config):
    if not TEST_DATABASE_URL:
        raise pytest.UsageError("Impostare TEST_DATABASE_URL (es. postgresql://spazio:spazio@localhost:5432/spazio_comune) "
                                "oppure eseguire: docker compose --profile test run --rm test")


class Orologio:
    """Orologio controllabile: lunedì 9 novembre 2026, ore 10:00."""

    def __init__(self):
        self.ora = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)

    def __call__(self):
        return self.ora

    def avanza(self, **kw):
        from datetime import timedelta
        self.ora += timedelta(**kw)


@pytest.fixture
def orologio():
    return Orologio()


@pytest.fixture
def db():
    """Schema PostgreSQL usa-e-getta: ogni test parte da tabelle vuote."""
    d = Database(TEST_DATABASE_URL, nuovo_schema())
    yield d
    d.elimina_schema()
    d.chiudi()


@pytest.fixture
def servizio(orologio, db):
    return ServizioPrenotazioni(db, MockPagoPA("http://test"), NoopAgenda(), "segreto-test", adesso=orologio)


@pytest.fixture
def mario():
    return Cittadino(cf="RSSMRA80A01E038X", nome="Mario", cognome="Rossi", email="m@example.org")


@pytest.fixture
def anna():
    return Cittadino(cf="BNCNNA90B41E038Y", nome="Anna", cognome="Bianchi")


@pytest.fixture
def inference_client():
    import server  # inference/server.py
    return TestClient(server.app)


@pytest.fixture
def settings():
    s = Settings(base_url="http://testserver", database_url=TEST_DATABASE_URL, database_schema=nuovo_schema(),
                 secret_key="k" * 32,
                 inference_url="http://inference", ufficio_user="u", ufficio_password="p",
                 custode_password="c", feed_token="feed")
    yield s
    # qualunque app creata con queste impostazioni ha usato questo schema: lo si elimina
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{s.database_schema}" CASCADE')


@pytest.fixture
def app_client(settings, orologio, inference_client):
    ia = AssistenteIA("http://testserver", client=inference_client)
    app = create_app(settings, adesso=orologio, assistente=ia)
    yield TestClient(app)
    app.state.db.chiudi()
