import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "inference"))

from venue_booking.adapters.agenda import NoopAgenda  # noqa: E402
from venue_booking.adapters.identity import Citizen  # noqa: E402
from venue_booking.adapters.payments import MockPagoPA  # noqa: E402
from venue_booking.ai import AIAssistant  # noqa: E402
from venue_booking.booking import TZ, BookingService  # noqa: E402
from venue_booking.config import Settings  # noqa: E402
from venue_booking.db import Database  # noqa: E402
from venue_booking.main import create_app  # noqa: E402


# PostgreSQL per i test: in Docker è il servizio "db"; in locale va indicato.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def new_schema() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


def pytest_configure(config):
    if not TEST_DATABASE_URL:
        raise pytest.UsageError("Impostare TEST_DATABASE_URL (es. postgresql://spazio:spazio@localhost:5432/spazio_comune) "
                                "oppure eseguire: docker compose --profile test run --rm test")


class Clock:
    """Orologio controllabile: lunedì 9 novembre 2026, ore 10:00."""

    def __init__(self):
        self.now = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        from datetime import timedelta
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db():
    """Schema PostgreSQL usa-e-getta: ogni test parte da tabelle vuote."""
    d = Database(TEST_DATABASE_URL, new_schema())
    yield d
    d.drop_schema()
    d.close()


@pytest.fixture
def service(clock, db):
    return BookingService(db, MockPagoPA("http://test"), NoopAgenda(), "segreto-test", now=clock)


@pytest.fixture
def mario():
    return Citizen(tax_code="RSSMRA80A01E038X", name="Mario", last_name="Rossi", email="m@example.org")


@pytest.fixture
def anna():
    return Citizen(tax_code="BNCNNA90B41E038Y", name="Anna", last_name="Bianchi")


@pytest.fixture
def inference_client():
    import server  # inference/server.py
    return TestClient(server.app)


@pytest.fixture
def settings():
    s = Settings(base_url="http://testserver", database_url=TEST_DATABASE_URL, database_schema=new_schema(),
                 secret_key="k" * 32,
                 inference_url="http://inference", office_user="u", office_password="p",
                 keeper_password="c", feed_token="feed", admin_user="admin", admin_password="admin-pw")
    yield s
    # qualunque app creata con queste impostazioni ha usato questo schema: lo si elimina
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{s.database_schema}" CASCADE')


@pytest.fixture
def app_client(settings, clock, inference_client):
    ai = AIAssistant("http://testserver", client=inference_client)
    app = create_app(settings, now=clock, assistant=ai)
    yield TestClient(app)
    app.state.db.close()
