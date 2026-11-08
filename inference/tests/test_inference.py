import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rules  # noqa: E402
import server  # noqa: E402

LUNEDI = date(2026, 11, 9)


@pytest.mark.parametrize("testo, atteso", [
    ("calcetto venerdì sera alle 20", {"attivita": "calcetto", "data": "2026-11-13", "fascia": "sera", "ora": "20:00"}),
    ("Vorrei giocare a tennis domani pomeriggio", {"attivita": "tennis_singolo", "data": "2026-11-10", "fascia": "pomeriggio"}),
    ("tennis in 4 sabato alle 6", {"attivita": "tennis_doppio", "data": "2026-11-14", "ora": "18:00", "giocatori": 4}),
    ("una partita stasera", {"attivita": "calcetto", "data": "2026-11-09", "fascia": "sera"}),
    ("doppio di tennis il 20/11 ore 17", {"attivita": "tennis_doppio", "data": "2026-11-20", "ora": "17:00"}),
    ("calcio a 5 il 3 dicembre", {"attivita": "calcetto", "data": "2026-12-03"}),
    ("calcetto il 2/1", {"data": "2027-01-02"}),
    ("CALCETTO LUNEDÌ", {"attivita": "calcetto", "data": "2026-11-09"}),
    ("calcetto il prossimo lunedì", {"data": "2026-11-16"}),
    ("tennis nel weekend", {"data": "2026-11-14"}),
    ("dopodomani alle 21", {"data": "2026-11-11", "ora": "21:00", "fascia": "sera"}),
])
def test_estrazione_intenti(testo, atteso):
    out = rules.estrai_intento(testo, LUNEDI)
    for k, v in atteso.items():
        assert out[k] == v, (k, out)


def test_confidenza():
    assert rules.estrai_intento("calcetto venerdì alle 20", LUNEDI)["confidenza"] == 1.0
    assert rules.estrai_intento("buongiorno", LUNEDI)["confidenza"] == 0.0


def test_data_impossibile_ignorata():
    assert rules.estrai_intento("calcetto il 31/02", LUNEDI)["data"] is None


DOCS = [
    {"id": "tariffe", "titolo": "Tariffe costi prezzi", "testo": "Calcetto 40 euro, tennis singolo 10 euro, doppio 20 euro."},
    {"id": "annullamento", "titolo": "Annullare disdire rimborso", "testo": "Si può annullare fino a 24 ore prima."},
    {"id": "ingresso", "titolo": "Ingresso custode QR", "testo": "Mostra il QR al custode."},
]


@pytest.mark.parametrize("domanda, fonte", [
    ("quanto costa il calcetto?", "tariffe"),
    ("posso disdire la prenotazione?", "annullamento"),
    ("cosa devo mostrare al custode", "ingresso"),
])
def test_faq_retrieval(domanda, fonte):
    out = rules.rispondi_faq(domanda, DOCS)
    assert out["trovata"] and out["fonti"] == [fonte]


def test_faq_senza_risposta():
    assert rules.rispondi_faq("chi ha vinto lo scudetto", DOCS)["trovata"] is False


@pytest.fixture
def client():
    return TestClient(server.app)


def test_health_e_models(client):
    assert client.get("/health").json()["backend"] == "rules"
    assert client.get("/v1/models").json()["data"][0]["id"] == "rules-it-v1"


def test_endpoint_intent(client):
    r = client.post("/v1/tasks/intent", json={"testo": "tennis doppio domani alle 18", "oggi": "2026-11-09"})
    j = r.json()
    assert r.status_code == 200 and j["attivita"] == "tennis_doppio" and j["data"] == "2026-11-10"
    assert j["backend"] == "rules" and j["generato_da_ia"] is False


def test_endpoint_intent_validazione(client):
    assert client.post("/v1/tasks/intent", json={"testo": ""}).status_code == 422
    assert client.post("/v1/tasks/intent", json={"testo": "x" * 501}).status_code == 422


def test_endpoint_faq(client):
    r = client.post("/v1/tasks/faq", json={"domanda": "quanto costa il tennis", "documenti": DOCS})
    assert r.json()["fonti"] == ["tariffe"]


def test_chat_completions_formato_openai(client):
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "calcetto domani"}]})
    j = r.json()
    assert j["object"] == "chat.completion" and j["choices"][0]["message"]["role"] == "assistant"
    assert json.loads(j["choices"][0]["message"]["content"])["attivita"] == "calcetto"


def test_redazione_pii():
    t = server.redigi("sono RSSMRA80A01E038X, mail mario.rossi@example.org, cell 333 1234567")
    assert "RSSMRA" not in t and "@" not in t and "1234567" not in t
    assert "[CODICE_FISCALE]" in t and "[EMAIL]" in t and "[TELEFONO]" in t


def test_backend_llm_completa_e_valida(monkeypatch, client):
    """L'LLM integra solo i campi mancanti e i valori non ammessi vengono scartati."""
    inviati = []

    def finto_llm(messaggi, json_mode=False, max_tokens=400):
        inviati.append(messaggi)
        return json.dumps({"attivita": "calcetto", "giorno": "venerdì", "fascia": "notte", "ora": "25:00"})

    monkeypatch.setattr(server, "BACKEND", "openai")
    monkeypatch.setattr(server, "_llm", finto_llm)
    j = client.post("/v1/tasks/intent", json={"testo": "una cosa col pallone fra amici, chiamami al 333 1234567",
                                              "oggi": "2026-11-09"}).json()
    assert j["attivita"] == "calcetto" and j["data"] == "2026-11-13"
    assert j["fascia"] is None and j["ora"] is None
    assert j["generato_da_ia"] is True
    assert "1234567" not in inviati[0][1]["content"]  # PII rimossi prima dell'invio


def test_backend_llm_non_disponibile_degrada(monkeypatch, client):
    def guasto(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(server, "BACKEND", "openai")
    monkeypatch.setattr(server, "_llm", guasto)
    j = client.post("/v1/tasks/intent", json={"testo": "boh", "oggi": "2026-11-09"}).json()
    assert j["backend"] == "rules"
    f = client.post("/v1/tasks/faq", json={"domanda": "quanto costa", "documenti": DOCS}).json()
    assert f["backend"] == "rules" and f["trovata"]
    assert client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 503


def test_backend_llm_faq_non_presente(monkeypatch, client):
    monkeypatch.setattr(server, "BACKEND", "openai")
    monkeypatch.setattr(server, "_llm", lambda *a, **k: "NON_PRESENTE")
    f = client.post("/v1/tasks/faq", json={"domanda": "orari piscina", "documenti": DOCS}).json()
    assert f["trovata"] is False and f["generato_da_ia"] is True
