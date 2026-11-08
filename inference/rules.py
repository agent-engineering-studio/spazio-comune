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

GIORNI = {"lunedi": 0, "martedi": 1, "mercoledi": 2, "giovedi": 3, "venerdi": 4, "sabato": 5, "domenica": 6}
MESI = {m: i + 1 for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"])}
FASCE = {"mattina": (8, 13), "pomeriggio": (13, 18), "sera": (18, 23)}
STOP = set("il lo la i gli le un una di a da in con su per tra fra e o che non si ci mi ti come quanto quanti "
           "quando dove cosa qual quale è e' sono del della dei delle al alla ai alle nel nella posso devo "
           "voglio vorrei serve servono".split())


def normalizza(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def _prossimo(oggi: date, wd: int) -> date:
    return oggi + timedelta(days=(wd - oggi.weekday()) % 7)


def estrai_intento(testo: str, oggi: date) -> dict:
    t = normalizza(testo)
    out: dict = {"attivita": None, "data": None, "fascia": None, "ora": None,
                 "giocatori": None, "confidenza": 0.0}
    segnali = 0

    # --- giocatori
    m = re.search(r"\b(?:in|siamo)\s+(\d{1,2}|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\b", t)
    if m:
        parole = {"due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10}
        g = m.group(1)
        out["giocatori"] = int(g) if g.isdigit() else parole[g]

    # --- attività
    if "tennis" in t:
        doppio = "doppio" in t or (out["giocatori"] or 0) >= 3 or "coppia" in t
        out["attivita"] = "tennis_doppio" if doppio else "tennis_singolo"
        segnali += 1
    elif re.search(r"calcett|calcio|calcio a 5|futsal|pallone|partitella|\bpartita\b", t):
        out["attivita"] = "calcetto"
        segnali += 1

    # --- data
    d: date | None = None
    if re.search(r"\bdopodomani\b", t):
        d = oggi + timedelta(days=2)
    elif re.search(r"\bdomani\b", t):
        d = oggi + timedelta(days=1)
    elif re.search(r"\b(oggi|stasera|stamattina|stamani|oggi pomeriggio)\b", t):
        d = oggi
    else:
        m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", t)
        if m:
            g, mm = int(m.group(1)), int(m.group(2))
            aa = int(m.group(3)) if m.group(3) else oggi.year
            aa = aa + 2000 if aa < 100 else aa
            try:
                d = date(aa, mm, g)
                if not m.group(3) and d < oggi:
                    d = date(aa + 1, mm, g)
            except ValueError:
                d = None
        if d is None:
            m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MESI) + r")\b", t)
            if m:
                try:
                    d = date(oggi.year, MESI[m.group(2)], int(m.group(1)))
                    if d < oggi:
                        d = date(oggi.year + 1, MESI[m.group(2)], int(m.group(1)))
                except ValueError:
                    d = None
        if d is None:
            for nome, wd in GIORNI.items():
                if re.search(rf"\b{nome}\b", t):
                    d = _prossimo(oggi, wd)
                    if re.search(rf"\b(prossimo|prossima)\s+{nome}\b", t) and d == oggi:
                        d += timedelta(days=7)
                    break
        if d is None and re.search(r"\b(weekend|fine settimana)\b", t):
            d = _prossimo(oggi, 5)
    if d:
        out["data"] = d.isoformat()
        segnali += 1

    # --- fascia oraria e ora
    if re.search(r"\bstasera\b|\bsera\b|\bdopo cena\b", t):
        out["fascia"] = "sera"
    elif re.search(r"\bpomeriggio\b|\bdopo pranzo\b", t):
        out["fascia"] = "pomeriggio"
    elif re.search(r"\bmattin[ao]\b|\bstamattina\b|\bstamani\b", t):
        out["fascia"] = "mattina"
    m = re.search(r"\b(?:alle|ore|h|verso le|dalle)\s*(\d{1,2})(?:[:.](\d{2}))?", t)
    if m:
        h = int(m.group(1))
        if out["fascia"] in ("sera", "pomeriggio") and h < 12:
            h += 12
        elif out["fascia"] is None and 1 <= h <= 7:
            h += 12  # "alle 6" in un campo sportivo pomeridiano/serale = 18
        if 0 <= h <= 23:
            out["ora"] = f"{h:02d}:00"
            segnali += 1
            if out["fascia"] is None:
                out["fascia"] = next((f for f, (a, b) in FASCE.items() if a <= h < b), None)
    elif out["fascia"]:
        segnali += 1

    out["confidenza"] = round(min(1.0, segnali / 3), 2)
    return out


# ---------------------------------------------------------------- FAQ / retrieval
def _token(t: str) -> list[str]:
    parole = re.findall(r"[a-z0-9]+", normalizza(t))
    # stemming povero: via la vocale finale, poi max 6 caratteri (costa/costi, tariffa/tariffe…)
    return [(re.sub(r"[aeiou]$", "", p) if len(p) > 4 else p)[:6] for p in parole if p not in STOP and len(p) > 1]


def classifica(domanda: str, documenti: list[dict], k: int = 3) -> list[tuple[float, dict]]:
    """BM25 compatto su titolo+testo."""
    docs = [(_token(d.get("titolo", "") + " " + d.get("titolo", "") + " " + d.get("testo", "")), d) for d in documenti]
    if not docs:
        return []
    N = len(docs)
    avgdl = sum(len(t) for t, _ in docs) / N or 1
    df = Counter(w for t, _ in docs for w in set(t))
    q = _token(domanda)
    k1, b = 1.4, 0.75
    risultati = []
    for toks, d in docs:
        tf = Counter(toks)
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(toks) / avgdl))
        risultati.append((s, d))
    risultati.sort(key=lambda x: x[0], reverse=True)
    return [r for r in risultati[:k] if r[0] > 0]


def rispondi_faq(domanda: str, documenti: list[dict]) -> dict:
    top = classifica(domanda, documenti, k=2)
    if not top:
        return {"risposta": None, "fonti": [], "trovata": False}
    migliore = top[0][1]
    return {"risposta": migliore["testo"], "fonti": [d["id"] for _, d in top[:1]], "trovata": True}
