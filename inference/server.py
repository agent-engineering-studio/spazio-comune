"""Server di inferenza minimale, OpenAI-compatibile.

Endpoint:
  GET  /health                 stato e backend attivo
  GET  /v1/models              elenco modelli (formato OpenAI)
  POST /v1/chat/completions    chat (formato OpenAI) – proxy verso LLM o risposta FAQ deterministica
  POST /v1/tasks/intent        testo libero -> {attivita, data, fascia, ora, giocatori}
  POST /v1/tasks/faq           domanda + documenti -> risposta fondata solo sui documenti

Backend (variabile INFERENCE_BACKEND):
  rules   (default) deterministico, offline, nessun dato esce dal container
  openai  qualsiasi endpoint OpenAI-compatibile: Ollama, vLLM, llama.cpp server,
          Azure OpenAI (via LLM_BASE_URL, LLM_MODEL, LLM_API_KEY)

Garanzie (AI Act art. 50, L. 132/2025, Linee guida AgID IA nella PA):
  - l'IA propone, la persona decide: nessun endpoint prenota o paga;
  - le risposte FAQ citano la fonte e, se la fonte non c'è, lo dicono;
  - i dati personali vengono rimossi prima dell'invio a un LLM (redazione PII);
  - ogni risposta riporta `generato_da_ia` e il backend usato (tracciabilità).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import date

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import rules

log = logging.getLogger("inference")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")

BACKEND = os.getenv("INFERENCE_BACKEND", "rules").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://ollama:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))

app = FastAPI(title="Spazio Comune – inference server", version="0.1.0")

# ------------------------------------------------------------------ PII
_PII_PATTERNS = [
    (re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I), "[CODICE_FISCALE]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?:\+39\s?)?\b3\d{2}[\s.]?\d{6,7}\b|\b0\d{1,3}[\s.]?\d{5,8}\b"), "[TELEFONO]"),
    (re.compile(r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b", re.I), "[IBAN]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------------ modelli I/O
# I nomi dei campi JSON restano in italiano (contratto HTTP): alias sui campi.
class IntentIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., alias="testo", min_length=1, max_length=500)
    today: date | None = Field(None, alias="oggi")


class Document(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str = Field(..., alias="titolo")
    text: str = Field(..., alias="testo")


class FaqIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(..., alias="domanda", min_length=2, max_length=500)
    documents: list[Document] = Field(..., alias="documenti", min_length=1, max_length=50)


class Message(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    model: str | None = None
    messages: list[Message]
    temperature: float | None = 0.0
    max_tokens: int | None = 400


# ------------------------------------------------------------------ LLM client
def _llm(messages: list[dict], json_mode: bool = False, max_tokens: int = 400) -> str:
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{LLM_BASE_URL}/chat/completions", json=payload, timeout=LLM_TIMEOUT,
                   headers={"Authorization": f"Bearer {LLM_API_KEY}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


INTENT_PROMPT = (
    "Estrai dalla richiesta di prenotazione di un campo sportivo comunale un JSON con chiavi: "
    "attivita (calcetto|tennis_singolo|tennis_doppio|null), giorno (testo del giorno così come scritto, o null), "
    "fascia (mattina|pomeriggio|sera|null), ora (HH:00 o null), giocatori (intero o null). "
    "Rispondi solo con JSON valido."
)

FAQ_PROMPT = (
    "Sei l'assistente del servizio prenotazione impianti sportivi del Comune di Gioia del Colle. "
    "Rispondi in italiano semplice, massimo 3 frasi, usando SOLO le informazioni nei documenti forniti. "
    "Se la risposta non è nei documenti, rispondi esattamente: NON_PRESENTE. "
    "Non inventare tariffe, orari o norme."
)


# ------------------------------------------------------------------ endpoint
@app.get("/health")
def health():
    return {"stato": "ok", "backend": BACKEND, "modello": LLM_MODEL if BACKEND == "openai" else "rules-it-v1"}


@app.get("/v1/models")
def models():
    name = LLM_MODEL if BACKEND == "openai" else "rules-it-v1"
    return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": "comune"}]}


@app.post("/v1/tasks/intent")
def intent(body: IntentIn):
    today = body.today or date.today()
    base = rules.extract_intent(body.text, today)
    used = "rules"
    if BACKEND == "openai" and base["confidenza"] < 0.67:
        try:
            raw = _llm([{"role": "system", "content": INTENT_PROMPT},
                        {"role": "user", "content": redact(body.text)}], json_mode=True, max_tokens=120)
            llm = json.loads(raw)
            # l'LLM estrae, il codice risolve e valida (le date relative restano deterministiche)
            if llm.get("attivita") in ("calcetto", "tennis_singolo", "tennis_doppio") and not base["attivita"]:
                base["attivita"] = llm["attivita"]
            if llm.get("giorno") and not base["data"]:
                base["data"] = rules.extract_intent(str(llm["giorno"]), today)["data"]
            if llm.get("fascia") in rules.TIME_SLOTS and not base["fascia"]:
                base["fascia"] = llm["fascia"]
            if isinstance(llm.get("ora"), str) and re.fullmatch(r"([01]\d|2[0-3]):00", llm["ora"]) and not base["ora"]:
                base["ora"] = llm["ora"]
            used = f"openai:{LLM_MODEL}"
        except Exception as e:  # degrado controllato: resta il risultato deterministico
            log.warning("LLM intent non disponibile: %s", e)
    return {**base, "backend": used, "generato_da_ia": used != "rules"}


@app.post("/v1/tasks/faq")
def faq(body: FaqIn):
    docs = [d.model_dump(by_alias=True) for d in body.documents]
    base = rules.answer_faq(body.question, docs)
    if BACKEND != "openai":
        return {**base, "backend": "rules", "generato_da_ia": False}
    top = [d for _, d in rules.rank(body.question, docs, k=3)] or docs[:3]
    context = "\n\n".join(f"[{d['id']}] {d['titolo']}\n{d['testo']}" for d in top)
    try:
        text = _llm([{"role": "system", "content": FAQ_PROMPT},
                     {"role": "user", "content": f"Documenti:\n{context}\n\nDomanda: {redact(body.question)}"}])
        if "NON_PRESENTE" in text:
            return {"risposta": None, "fonti": [], "trovata": False, "backend": f"openai:{LLM_MODEL}", "generato_da_ia": True}
        return {"risposta": text.strip(), "fonti": [d["id"] for d in top], "trovata": True,
                "backend": f"openai:{LLM_MODEL}", "generato_da_ia": True}
    except Exception as e:
        log.warning("LLM faq non disponibile: %s", e)
        return {**base, "backend": "rules", "generato_da_ia": False}


@app.post("/v1/chat/completions")
def chat(body: ChatIn):
    messages = [{"role": m.role, "content": redact(m.content)} for m in body.messages]
    if BACKEND == "openai":
        try:
            content = _llm(messages, max_tokens=body.max_tokens or 400)
        except Exception as e:
            raise HTTPException(503, f"LLM non disponibile: {e}") from e
        model = LLM_MODEL
    else:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        content = json.dumps(rules.extract_intent(last, date.today()), ensure_ascii=False)
        model = "rules-it-v1"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
