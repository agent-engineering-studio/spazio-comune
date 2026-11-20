"""Client verso il server di inferenza + base di conoscenza del servizio.

Se il server di inferenza non risponde, l'interfaccia funziona comunque:
l'assistente sparisce e resta il calendario classico (degrado controllato).
"""
from __future__ import annotations

import logging
from datetime import date

import httpx

from .catalog import Venue

log = logging.getLogger("venue_booking.ai")


def knowledge_base(venue: Venue) -> list[dict]:
    venue_ = venue
    activities = [venue_.catalog[a] for a in venue_.activities]
    fees = "; ".join(f"{a.name}: {a.fee_eur} euro totali a slot da {venue_.slot_minutes} minuti" for a in activities)
    for b in venue_.fee_bands:
        fees += "; tariffa " + b.readable + ": " + ", ".join(
            f"{venue_.catalog[c].name} {cents / 100:.2f} euro".replace(".", ",") for c, cents in b.fees.items())
    return [
        {"id": "tariffe", "titolo": "Tariffe costi prezzi quanto costa pagare",
         "testo": f"Tariffe in vigore ({venue_.fees_source}): {fees}. L'importo è per l'intero gruppo, non a persona."},
        {"id": "pagamento", "titolo": "Come si paga pagoPA carta bonifico ricevuta",
         "testo": "Si paga online con pagoPA subito dopo aver scelto l'orario (carta, conto, app IO o avviso in "
                  "tabaccheria/ufficio postale). Non serve più caricare la ricevuta PDF: la conferma arriva in automatico."},
        {"id": "accesso", "titolo": "Accesso SPID CIE identità login registrazione",
         "testo": "Per prenotare si accede con SPID o CIE. Nome, cognome e codice fiscale vengono compilati in automatico."},
        {"id": "ingresso", "titolo": "Ingresso al campo custode biglietto QR stampa ricevuta",
         "testo": "Al campo basta mostrare il QR code della prenotazione sullo smartphone al custode. Non serve stampare nulla."},
        {"id": "annullamento", "titolo": "Annullare disdire cancellare rimborso spostare",
         "testo": f"Puoi annullare online dall'area 'Le mie prenotazioni' fino a {venue_.cancel_hours} ore prima. Per annullamenti "
                  "successivi o rimborsi contatta l'" + venue_.office + "."},
        {"id": "orari", "titolo": "Orari apertura giorni disponibili quando",
         "testo": f"{venue_.name}: {venue_.readable_hours}, prenotabile fino a {venue_.advance_days} giorni prima. "
                  "Gli orari disponibili sono sempre quelli mostrati nel calendario, che l'ufficio aggiorna per chiusure e manutenzioni."},
        {"id": "dove", "titolo": "Dove si trova indirizzo luogo campo",
         "testo": f"{venue_.name}, {venue_.address}."},
        {"id": "attivita", "titolo": "Sport attività calcetto tennis singolo doppio giocatori",
         "testo": "Si può prenotare: " + ", ".join(f"{a.name} ({a.players} giocatori)" for a in activities) + ". "
                  "Scegliendo l'attività il custode saprà già come preparare il campo."},
        {"id": "privacy", "titolo": "Privacy dati personali trattamento",
         "testo": f"I dati sono trattati dal {venue_.municipality} per gestire la prenotazione e il pagamento "
                  "(art. 6.1.e GDPR, esecuzione di un compito di interesse pubblico). L'assistente IA non riceve i tuoi dati personali."},
    ]


class AIAssistant:
    def __init__(self, base_url: str | None, timeout: float = 8.0, client: httpx.Client | None = None,
                 venue: Venue | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.venue = venue or Venue()
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def interpret(self, text: str, today: date) -> dict | None:
        if not self.enabled:
            return None
        try:
            r = self._client.post(f"{self.base_url}/v1/tasks/intent", json={"testo": text, "oggi": today.isoformat()})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("inference intent non disponibile: %s", e)
            return None

    def faq(self, question: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            r = self._client.post(f"{self.base_url}/v1/tasks/faq",
                                  json={"domanda": question, "documenti": knowledge_base(self.venue)})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("inference faq non disponibile: %s", e)
            return None


TIME_BANDS = {"mattina": (8, 13), "pomeriggio": (13, 18), "sera": (18, 24)}


def filter_slots(days: list[dict], intent: dict, maximum: int = 4) -> list[dict]:
    """Applica l'intento al calendario: slot liberi compatibili, ordinati per vicinanza alla richiesta.

    Se l'ora esatta non è libera propone le alternative più vicine nello stesso giorno;
    se il giorno richiesto è tutto impegnato, quelle dei giorni successivi:
    l'assistente suggerisce, il cittadino sceglie.
    """
    def candidates(same_day: bool) -> list[tuple]:
        found = []
        for g in days:
            if same_day and g["data"] != intent["data"]:
                continue
            for s in g["slot"]:
                if not s["libero"]:
                    continue
                h = int(s["ora"][:2])
                if intent.get("fascia") and not intent.get("ora"):
                    a, b = TIME_BANDS[intent["fascia"]]
                    if not a <= h < b:
                        continue
                distance = abs(h - int(intent["ora"][:2])) if intent.get("ora") else 0
                # negli altri giorni conta prima il giorno più vicino, poi l'ora
                key = (distance, s["inizio"]) if same_day or not intent.get("data") else (g["data"], distance, s["inizio"])
                found.append((key, {**s, "data": g["data"]}))
        return sorted(found, key=lambda c: c[0])

    chosen = candidates(same_day=True) if intent.get("data") else []
    return [c[1] for c in (chosen or candidates(same_day=False))[:maximum]]
