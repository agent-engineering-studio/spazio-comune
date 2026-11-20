"""Backend deterministico (nessun modello): estrazione intenti in italiano e FAQ per retrieval.

È il backend predefinito: gira ovunque, non invia dati a terzi, rende i test
riproducibili. Gli LLM (locali o cloud) si attivano solo se configurati e
vengono comunque validati/normalizzati da questo modulo.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

WEEKDAYS = {"lunedi": 0, "martedi": 1, "mercoledi": 2, "giovedi": 3, "venerdi": 4, "sabato": 5, "domenica": 6}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"])}
TIME_SLOTS = {"mattina": (8, 13), "pomeriggio": (13, 18), "sera": (18, 24)}
STOP_WORDS = set("il lo la i gli le un una di a da in con su per tra fra e o che non si ci mi ti come quanto quanti "
                 "quando dove cosa qual quale è e' sono del della dei delle al alla ai alle nel nella posso devo "
                 "voglio vorrei serve servono".split())
NUMBER_WORDS = {"due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def _next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def extract_intent(text: str, today: date) -> dict:
    t = normalize(text)
    out: dict = {"attivita": None, "data": None, "fascia": None, "ora": None,
                 "giocatori": None, "confidenza": 0.0}
    signals = 0

    # --- giocatori
    m = re.search(r"\b(?:in|siamo)\s+(\d{1,2}|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\b", t)
    if m:
        players = m.group(1)
        out["giocatori"] = int(players) if players.isdigit() else NUMBER_WORDS[players]

    # --- attività
    if "tennis" in t:
        doubles = "doppio" in t or (out["giocatori"] or 0) >= 3 or "coppia" in t
        out["attivita"] = "tennis_doppio" if doubles else "tennis_singolo"
        signals += 1
    elif re.search(r"calcett|calcio|calcio a 5|futsal|pallone|partitella|\bpartita\b", t):
        out["attivita"] = "calcetto"
        signals += 1

    # --- data
    d: date | None = None
    if re.search(r"\bdopodomani\b", t):
        d = today + timedelta(days=2)
    elif re.search(r"\bdomani\b", t):
        d = today + timedelta(days=1)
    elif re.search(r"\b(oggi|stasera|stamattina|stamani|oggi pomeriggio)\b", t):
        d = today
    else:
        m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", t)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today.year
            year = year + 2000 if year < 100 else year
            try:
                d = date(year, month, day)
                if not m.group(3) and d < today:
                    d = date(year + 1, month, day)
            except ValueError:
                d = None
        if d is None:
            m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", t)
            if m:
                try:
                    d = date(today.year, MONTHS[m.group(2)], int(m.group(1)))
                    if d < today:
                        d = date(today.year + 1, MONTHS[m.group(2)], int(m.group(1)))
                except ValueError:
                    d = None
        if d is None:
            for name, weekday in WEEKDAYS.items():
                if re.search(rf"\b{name}\b", t):
                    d = _next_weekday(today, weekday)
                    if re.search(rf"\b(prossimo|prossima)\s+{name}\b", t) and d == today:
                        d += timedelta(days=7)
                    break
        if d is None and re.search(r"\b(weekend|fine settimana)\b", t):
            d = _next_weekday(today, 5)
    if d:
        out["data"] = d.isoformat()
        signals += 1

    # --- fascia oraria e ora
    if re.search(r"\bstasera\b|\bsera\b|\bdopo cena\b", t):
        out["fascia"] = "sera"
    elif re.search(r"\bpomeriggio\b|\bdopo pranzo\b", t):
        out["fascia"] = "pomeriggio"
    elif re.search(r"\bmattin[ao]\b|\bstamattina\b|\bstamani\b", t):
        out["fascia"] = "mattina"
    m = re.search(r"\b(?:alle|ore|h|verso le|dalle)\s*(\d{1,2})(?:[:.](\d{2}))?", t)
    if m:
        hour = int(m.group(1))
        if out["fascia"] in ("sera", "pomeriggio") and hour < 12:
            hour += 12
        elif out["fascia"] is None and 1 <= hour <= 7:
            hour += 12  # "alle 6" in un campo sportivo pomeridiano/serale = 18
        if 0 <= hour <= 23:
            out["ora"] = f"{hour:02d}:00"
            signals += 1
            if out["fascia"] is None:
                out["fascia"] = next((f for f, (a, b) in TIME_SLOTS.items() if a <= hour < b), None)
    elif out["fascia"]:
        signals += 1

    out["confidenza"] = round(min(1.0, signals / 3), 2)
    return out


# ---------------------------------------------------------------- FAQ / retrieval
def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize(text))
    # stemming povero: via la vocale finale, poi max 6 caratteri (costa/costi, tariffa/tariffe…)
    return [(re.sub(r"[aeiou]$", "", w) if len(w) > 4 else w)[:6] for w in words if w not in STOP_WORDS and len(w) > 1]


def rank(question: str, documents: list[dict], k: int = 3) -> list[tuple[float, dict]]:
    """BM25 compatto su titolo+testo."""
    docs = [(_tokens(d.get("titolo", "") + " " + d.get("titolo", "") + " " + d.get("testo", "")), d) for d in documents]
    if not docs:
        return []
    n_docs = len(docs)
    avgdl = sum(len(t) for t, _ in docs) / n_docs or 1
    df = Counter(w for t, _ in docs for w in set(t))
    query = _tokens(question)
    k1, b = 1.4, 0.75
    results = []
    for toks, d in docs:
        tf = Counter(toks)
        score = 0.0
        for w in query:
            if w not in tf:
                continue
            idf = math.log(1 + (n_docs - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(toks) / avgdl))
        results.append((score, d))
    results.sort(key=lambda x: x[0], reverse=True)
    return [r for r in results[:k] if r[0] > 0]


def answer_faq(question: str, documents: list[dict]) -> dict:
    top = rank(question, documents, k=2)
    if not top:
        return {"risposta": None, "fonti": [], "trovata": False}
    best = top[0][1]
    return {"risposta": best["testo"], "fonti": [d["id"] for _, d in top[:1]], "trovata": True}
