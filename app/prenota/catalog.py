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
from datetime import date, time, timedelta


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

# festività nazionali a data fissa (giorno, mese); Pasqua e Lunedì dell'Angelo si calcolano
FESTE_FISSE = [(1, 1), (6, 1), (25, 4), (1, 5), (2, 6), (15, 8), (1, 11), (8, 12), (25, 12), (26, 12)]


def pasqua(anno: int) -> date:
    """Domenica di Pasqua nel calendario gregoriano (algoritmo di Meeus/Jones/Butcher)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese, giorno = divmod(h + l - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


def festivita_nazionali(anno: int) -> set[date]:
    """I giorni "rossi" del calendario italiano per l'anno dato."""
    feste = {date(anno, m, g) for g, m in FESTE_FISSE}
    feste |= {pasqua(anno), pasqua(anno) + timedelta(days=1)}
    if anno >= 2026:
        feste.add(date(anno, 10, 4))   # San Francesco d'Assisi, festa nazionale dal 2026
    return feste


def _orari(testo: str, durata: int, campo: str) -> tuple[time, ...]:
    """Da "9-13,14-22" (ore intere, chiusura fino a 24) agli orari di inizio degli slot."""
    inizi: set[int] = set()
    for intervallo in testo.split(","):
        try:
            apre, chiude = (int(x) for x in intervallo.strip().split("-"))
        except ValueError:
            raise ValueError(f"{campo}: usare intervalli apertura-chiusura in ore intere, es. 9-13,14-22") from None
        if not 0 <= apre < chiude <= 24:
            raise ValueError(f"{campo}: intervallo {intervallo.strip()} non valido (ore da 0 a 24, apertura prima della chiusura)")
        inizi.update(range(apre * 60, chiude * 60 - durata + 1, durata))
    return tuple(time(m // 60, m % 60) for m in sorted(inizi))


def _giorno_mese(testo: str, campo: str) -> tuple[int, int]:
    try:
        g, m = (int(x) for x in testo.strip().split("/"))
        date(2024, m, g)   # anno bisestile: ammette il 29/02
    except ValueError:
        raise ValueError(f"{campo}: usare date GG/MM, es. 01/06") from None
    return m, g


def _leggibile(orari: tuple[time, ...], durata: int) -> str:
    """Orari di inizio degli slot -> "15:00–22:00" (più intervalli separati da virgola)."""
    intervalli: list[list[int]] = []
    for t in orari:
        m = t.hour * 60 + t.minute
        if intervalli and intervalli[-1][1] == m:
            intervalli[-1][1] = m + durata
        else:
            intervalli.append([m, m + durata])
    return ", ".join(f"{a // 60:02d}:{a % 60:02d}–{b // 60:02d}:{b % 60:02d}" for a, b in intervalli)


@dataclass(frozen=True)
class Periodo:
    """Orario che sostituisce quello normale tra due date, ogni anno (es. estate)."""
    dal: tuple[int, int]       # (mese, giorno)
    al: tuple[int, int]
    orari: tuple[time, ...]

    def comprende(self, giorno: date) -> bool:
        md = (giorno.month, giorno.day)
        if self.dal <= self.al:
            return self.dal <= md <= self.al
        return md >= self.dal or md <= self.al   # periodo a cavallo di Capodanno


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
    # orari diversi in alcuni periodi dell'anno; il primo periodo che comprende il giorno vince
    periodi: tuple[Periodo, ...] = ()
    # orari nei giorni festivi: () = chiuso, None = come un giorno normale
    festivi: tuple[time, ...] | None = ()
    # festività locali oltre a quelle nazionali: (mese, giorno, anno oppure None = ogni anno)
    festivi_extra: tuple[tuple[int, int, int | None], ...] = ()
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
            orari = _orari(e.get("SPAZIO_ORARIO", "15-22"), durata, "SPAZIO_ORARIO")
            calendario = {GIORNI.index(g): orari for g in giorni}
        periodi = []
        for voce in filter(None, (v.strip() for v in e.get("SPAZIO_ORARIO_PERIODI", "").split(";"))):
            try:
                date_, orari_ = voce.split("=")
                dal, al = date_.split("-")
            except ValueError:
                raise ValueError("SPAZIO_ORARIO_PERIODI: usare GG/MM-GG/MM=orari, es. 01/06-15/09=9-13,16-24") from None
            periodi.append(Periodo(_giorno_mese(dal, "SPAZIO_ORARIO_PERIODI"), _giorno_mese(al, "SPAZIO_ORARIO_PERIODI"),
                                   _orari(orari_, durata, "SPAZIO_ORARIO_PERIODI")))
        festivi = e.get("SPAZIO_FESTIVI", "chiuso").strip().lower()
        festivi = () if festivi == "chiuso" else None if festivi == "aperto" else _orari(festivi, durata, "SPAZIO_FESTIVI")
        extra = []
        for voce in filter(None, (v.strip() for v in e.get("SPAZIO_FESTIVI_EXTRA", "").split(","))):
            parti = voce.split("/")
            m, g = _giorno_mese("/".join(parti[:2]), "SPAZIO_FESTIVI_EXTRA")
            if len(parti) > 3 or (len(parti) == 3 and not (parti[2].isdigit() and len(parti[2]) == 4)):
                raise ValueError("SPAZIO_FESTIVI_EXTRA: usare GG/MM (ogni anno) o GG/MM/AAAA, es. 26/05,14/08/2027")
            extra.append((m, g, int(parti[2]) if len(parti) == 3 else None))
        return cls(
            nome=e.get("SPAZIO_NOME", base.nome),
            indirizzo=e.get("SPAZIO_INDIRIZZO", base.indirizzo),
            comune=e.get("COMUNE_NOME", base.comune),
            comune_indirizzo=e.get("COMUNE_INDIRIZZO", base.comune_indirizzo),
            comune_sito=e.get("COMUNE_SITO", base.comune_sito),
            ufficio=e.get("UFFICIO_NOME", base.ufficio),
            attivita=attivita, calendario=calendario, periodi=tuple(periodi), festivi=festivi,
            festivi_extra=tuple(extra), durata_min=durata,
            preavviso_giorni=int(e.get("SPAZIO_PREAVVISO_GIORNI", base.preavviso_giorni)),
            prefisso_codice=e.get("CODICE_PREFISSO", base.prefisso_codice).upper(),
        )

    def festivo(self, giorno: date) -> bool:
        """Giorno "rosso": festività nazionale o locale (SPAZIO_FESTIVI_EXTRA)."""
        return giorno in festivita_nazionali(giorno.year) or any(
            (m, g) == (giorno.month, giorno.day) and a in (None, giorno.year) for m, g, a in self.festivi_extra)

    def orari_del(self, giorno: date) -> tuple[time, ...]:
        """Orari di inizio degli slot in una data: giorno della settimana, festività e periodi."""
        if giorno.weekday() not in self.calendario:
            return ()
        if self.festivi is not None and self.festivo(giorno):
            return self.festivi
        periodo = next((p for p in self.periodi if p.comprende(giorno)), None)
        return periodo.orari if periodo else self.calendario[giorno.weekday()]

    @property
    def orario_leggibile(self) -> str:
        giorni = sorted(self.calendario)
        if not giorni:
            return "chiuso"
        testo = (f"{', '.join(GIORNI[g] for g in giorni)}, {_leggibile(self.calendario[giorni[0]], self.durata_min)} "
                 f"(slot da {self.durata_min} minuti)")
        for p in self.periodi:
            testo += (f"; dal {p.dal[1]:02d}/{p.dal[0]:02d} al {p.al[1]:02d}/{p.al[0]:02d}: "
                      f"{_leggibile(p.orari, self.durata_min) or 'chiuso'}")
        if self.festivi is not None:
            testo += "; nei giorni festivi: " + (_leggibile(self.festivi, self.durata_min) or "chiuso")
        return testo
