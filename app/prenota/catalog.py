"""Il luogo prenotabile, le attività e le tariffe.

Ogni installazione gestisce **un solo luogo**: nome, indirizzo, Comune e orari
si leggono dal file .env. Un Comune con più luoghi installa una copia del
repository per ciascuno.

Le tariffe riproducono la D.G.C. n. 37/2025 ("approvazione tariffe impianti
sportivi 2025") del Comune di Gioia del Colle:
  - calcetto: 40 EUR totali a partita
  - tennis singolo: 10 EUR totali; tennis doppio: 20 EUR totali
Un altro luogo sceglie le attività con SPAZIO_ATTIVITA; attività nuove si
aggiungono al dizionario ATTIVITA qui sotto.
"""
from __future__ import annotations

import os
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


ATTIVITA: dict[str, Attivita] = {
    "calcetto": Attivita("calcetto", "Calcetto (calcio a 5)", 4000, "fino a 10", "Montare porte calcetto"),
    "tennis_singolo": Attivita("tennis_singolo", "Tennis – singolo", 1000, "2", "Montare rete tennis"),
    "tennis_doppio": Attivita("tennis_doppio", "Tennis – doppio", 2000, "4", "Montare rete tennis"),
}

FONTE_TARIFFE = os.getenv("FONTE_TARIFFE") or "D.G.C. n. 37/2025 – approvazione tariffe impianti sportivi 2025"
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


@dataclass(frozen=True)
class Spazio:
    nome: str = "Campo comunale coperto di via Benagiano"
    indirizzo: str = "Via Benagiano, 70023 Gioia del Colle (BA)"
    comune: str = "Comune di Gioia del Colle"
    comune_indirizzo: str = "Piazza Margherita di Savoia, 10 – 70023 Gioia del Colle (BA)"
    comune_sito: str = "https://www.comune.gioiadelcolle.ba.it/"
    ufficio: str = "Ufficio Cultura, Istruzione e Sport"
    attivita: tuple[str, ...] = ("calcetto", "tennis_singolo", "tennis_doppio")
    # giorno della settimana (0=lun) -> orari di inizio degli slot
    calendario: dict[int, tuple[time, ...]] = field(
        default_factory=lambda: {d: tuple(time(h) for h in range(15, 22)) for d in range(6)})
    durata_min: int = 60
    preavviso_giorni: int = 14   # finestra di prenotabilità
    prefisso_codice: str = "GDC"  # numeri di prenotazione GDC-XXXX-XXXX

    @classmethod
    def da_env(cls, env: dict[str, str] | None = None) -> "Spazio":
        """Legge il luogo dalle variabili SPAZIO_*, COMUNE_* e UFFICIO_NOME; le assenti restano predefinite."""
        e = {k: v for k, v in (os.environ if env is None else env).items() if v not in (None, "")}
        base = cls()
        durata = int(e.get("SPAZIO_DURATA_MIN", base.durata_min))
        attivita = tuple(a.strip() for a in e["SPAZIO_ATTIVITA"].split(",") if a.strip()) \
            if "SPAZIO_ATTIVITA" in e else base.attivita
        ignote = [a for a in attivita if a not in ATTIVITA]
        if ignote or not attivita:
            raise ValueError(f"SPAZIO_ATTIVITA: attività non previste {ignote}; disponibili: {', '.join(ATTIVITA)}")
        calendario = base.calendario
        if "SPAZIO_GIORNI" in e or "SPAZIO_ORARIO" in e:
            giorni = [g.strip().lower()[:3] for g in e.get("SPAZIO_GIORNI", "lun,mar,mer,gio,ven,sab").split(",")]
            if any(g not in GIORNI for g in giorni):
                raise ValueError(f"SPAZIO_GIORNI: usare {','.join(GIORNI)}")
            apre, chiude = (int(x) for x in e.get("SPAZIO_ORARIO", "15-22").split("-"))
            orari = tuple(time(m // 60, m % 60) for m in range(apre * 60, chiude * 60 - durata + 1, durata))
            calendario = {GIORNI.index(g): orari for g in giorni}
        return cls(
            nome=e.get("SPAZIO_NOME", base.nome),
            indirizzo=e.get("SPAZIO_INDIRIZZO", base.indirizzo),
            comune=e.get("COMUNE_NOME", base.comune),
            comune_indirizzo=e.get("COMUNE_INDIRIZZO", base.comune_indirizzo),
            comune_sito=e.get("COMUNE_SITO", base.comune_sito),
            ufficio=e.get("UFFICIO_NOME", base.ufficio),
            attivita=attivita, calendario=calendario, durata_min=durata,
            preavviso_giorni=int(e.get("SPAZIO_PREAVVISO_GIORNI", base.preavviso_giorni)),
            prefisso_codice=e.get("CODICE_PREFISSO", base.prefisso_codice).upper(),
        )

    @property
    def orario_leggibile(self) -> str:
        giorni = sorted(self.calendario)
        if not giorni:
            return "chiuso"
        orari = self.calendario[giorni[0]]
        return (f"{', '.join(GIORNI[g] for g in giorni)}, slot da {self.durata_min} minuti "
                f"dalle {orari[0].strftime('%H:%M')} alle {orari[-1].strftime('%H:%M')}")
