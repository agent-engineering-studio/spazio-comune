import sys
from datetime import datetime
from pathlib import Path

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
def servizio(orologio):
    return ServizioPrenotazioni(Database(":memory:"), MockPagoPA("http://test"), NoopAgenda(),
                                "segreto-test", adesso=orologio)


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
def settings(tmp_path):
    return Settings(base_url="http://testserver", db_path=str(tmp_path / "t.db"), secret_key="k" * 32,
                    inference_url="http://inference", ufficio_user="u", ufficio_password="p",
                    custode_password="c", feed_token="feed")


@pytest.fixture
def app_client(settings, orologio, inference_client):
    ia = AssistenteIA("http://testserver", client=inference_client)
    app = create_app(settings, adesso=orologio, assistente=ia)
    return TestClient(app)
