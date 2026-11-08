"""Client verso il server di inferenza + base di conoscenza del servizio.

Se il server di inferenza non risponde, l'interfaccia funziona comunque:
l'assistente sparisce e resta il calendario classico (degrado controllato).
"""
from __future__ import annotations

import logging
from datetime import date

import httpx

from .catalog import ATTIVITA, FONTE_TARIFFE, Spazio

log = logging.getLogger("prenota.ai")


def base_conoscenza(spazio: Spazio) -> list[dict]:
    imp = spazio
    attivita = [ATTIVITA[a] for a in imp.attivita]
    tariffe = "; ".join(f"{a.nome}: {a.tariffa_eur} euro totali a slot da {imp.durata_min} minuti" for a in attivita)
    return [
        {"id": "tariffe", "titolo": "Tariffe costi prezzi quanto costa pagare",
         "testo": f"Tariffe in vigore ({FONTE_TARIFFE}): {tariffe}. L'importo è per l'intero gruppo, non a persona."},
        {"id": "pagamento", "titolo": "Come si paga pagoPA carta bonifico ricevuta",
         "testo": "Si paga online con pagoPA subito dopo aver scelto l'orario (carta, conto, app IO o avviso in "
                  "tabaccheria/ufficio postale). Non serve più caricare la ricevuta PDF: la conferma arriva in automatico."},
        {"id": "accesso", "titolo": "Accesso SPID CIE identità login registrazione",
         "testo": "Per prenotare si accede con SPID o CIE. Nome, cognome e codice fiscale vengono compilati in automatico."},
        {"id": "ingresso", "titolo": "Ingresso al campo custode biglietto QR stampa ricevuta",
         "testo": "Al campo basta mostrare il QR code della prenotazione sullo smartphone al custode. Non serve stampare nulla."},
        {"id": "annullamento", "titolo": "Annullare disdire cancellare rimborso spostare",
         "testo": "Puoi annullare online dall'area 'Le mie prenotazioni' fino a 24 ore prima. Per annullamenti "
                  "successivi o rimborsi contatta l'" + imp.ufficio + "."},
        {"id": "orari", "titolo": "Orari apertura giorni disponibili quando",
         "testo": f"{imp.nome}: {imp.orario_leggibile}, prenotabile fino a {imp.preavviso_giorni} giorni prima. "
                  "Gli orari disponibili sono sempre quelli mostrati nel calendario, che l'ufficio aggiorna per chiusure e manutenzioni."},
        {"id": "dove", "titolo": "Dove si trova indirizzo luogo campo",
         "testo": f"{imp.nome}, {imp.indirizzo}."},
        {"id": "attivita", "titolo": "Sport attività calcetto tennis singolo doppio giocatori",
         "testo": "Si può prenotare: " + ", ".join(f"{a.nome} ({a.giocatori} giocatori)" for a in attivita) + ". "
                  "Scegliendo l'attività il custode saprà già come preparare il campo."},
        {"id": "privacy", "titolo": "Privacy dati personali trattamento",
         "testo": f"I dati sono trattati dal {imp.comune} per gestire la prenotazione e il pagamento "
                  "(art. 6.1.e GDPR, esecuzione di un compito di interesse pubblico). L'assistente IA non riceve i tuoi dati personali."},
    ]


class AssistenteIA:
    def __init__(self, base_url: str | None, timeout: float = 8.0, client: httpx.Client | None = None,
                 spazio: Spazio | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.spazio = spazio or Spazio()
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def attivo(self) -> bool:
        return bool(self.base_url)

    def interpreta(self, testo: str, oggi: date) -> dict | None:
        if not self.attivo:
            return None
        try:
            r = self._client.post(f"{self.base_url}/v1/tasks/intent", json={"testo": testo, "oggi": oggi.isoformat()})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("inference intent non disponibile: %s", e)
            return None

    def faq(self, domanda: str) -> dict | None:
        if not self.attivo:
            return None
        try:
            r = self._client.post(f"{self.base_url}/v1/tasks/faq",
                                  json={"domanda": domanda, "documenti": base_conoscenza(self.spazio)})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("inference faq non disponibile: %s", e)
            return None


FASCE = {"mattina": (8, 13), "pomeriggio": (13, 18), "sera": (18, 23)}


def filtra_slot(giorni: list[dict], intento: dict, massimo: int = 4) -> list[dict]:
    """Applica l'intento al calendario: slot liberi compatibili, ordinati per vicinanza alla richiesta.

    Se l'ora esatta non è libera propone le alternative più vicine nello stesso giorno,
    poi negli altri giorni: l'assistente suggerisce, il cittadino sceglie.
    """
    candidati = []
    for g in giorni:
        if intento.get("data") and g["data"] != intento["data"]:
            continue
        for s in g["slot"]:
            if not s["libero"]:
                continue
            h = int(s["ora"][:2])
            if intento.get("fascia") and not intento.get("ora"):
                a, b = FASCE[intento["fascia"]]
                if not a <= h < b:
                    continue
            distanza = abs(h - int(intento["ora"][:2])) if intento.get("ora") else 0
            candidati.append((distanza, s["inizio"], {**s, "data": g["data"]}))
    candidati.sort(key=lambda c: (c[0], c[1]))
    return [c[2] for c in candidati[:massimo]]
