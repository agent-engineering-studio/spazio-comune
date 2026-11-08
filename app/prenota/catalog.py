"""Catalogo impianti, attività e tariffe.

Le tariffe riproducono la D.G.C. n. 37/2025 ("approvazione tariffe impianti
sportivi 2025") così come riportate nella scheda del servizio eAgenda del
Comune di Gioia del Colle:
  - calcetto: 40 EUR totali a partita
  - tennis singolo: 10 EUR totali; tennis doppio: 20 EUR totali

Il calendario (giorni/orari) è un valore di esempio: in produzione si legge
dalla configurazione dell'Ufficio Cultura, Istruzione e Sport, che resta
l'unico a decidere aperture, chiusure e manutenzioni.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class Attivita:
    codice: str
    nome: str
    tariffa_cent: int          # importo totale per slot, in centesimi
    giocatori: str
    preparazione: str          # nota per il custode

    @property
    def tariffa_eur(self) -> str:
        return f"{self.tariffa_cent / 100:.2f}".replace(".", ",")


@dataclass(frozen=True)
class Impianto:
    codice: str
    nome: str
    indirizzo: str
    ufficio: str
    attivita: tuple[str, ...]
    # giorno della settimana (0=lun) -> orari di inizio slot da 60 minuti
    calendario: dict[int, tuple[time, ...]] = field(default_factory=dict)
    durata_min: int = 60
    preavviso_giorni: int = 14   # finestra di prenotabilità


ATTIVITA: dict[str, Attivita] = {
    "calcetto": Attivita("calcetto", "Calcetto (calcio a 5)", 4000, "fino a 10", "Montare porte calcetto"),
    "tennis_singolo": Attivita("tennis_singolo", "Tennis – singolo", 1000, "2", "Montare rete tennis"),
    "tennis_doppio": Attivita("tennis_doppio", "Tennis – doppio", 2000, "4", "Montare rete tennis"),
}

_POMERIGGIO_SERA = tuple(time(h) for h in range(15, 22))  # 15:00 … 21:00

IMPIANTI: dict[str, Impianto] = {
    "benagiano": Impianto(
        codice="benagiano",
        nome="Campo comunale coperto di via Benagiano",
        indirizzo="Via Benagiano, 70023 Gioia del Colle (BA)",
        ufficio="Cultura, Istruzione e Sport",
        attivita=("calcetto", "tennis_singolo", "tennis_doppio"),
        calendario={d: _POMERIGGIO_SERA for d in range(0, 6)},  # lun-sab
    ),
}

FONTE_TARIFFE = "D.G.C. n. 37/2025 – approvazione tariffe impianti sportivi 2025"
