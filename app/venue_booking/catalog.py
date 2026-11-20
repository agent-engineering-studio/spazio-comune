"""Il luogo prenotabile, le attività, le tariffe e il calendario.

Ogni installazione gestisce **un solo luogo**. Il file .env (SPAZIO_*, COMUNE_*)
dà i valori iniziali; il back-office /admin li sostituisce senza
riavvio (vedi impostazioni.py). Un Comune con più luoghi installa una copia del
repository per ciascuno.

Calendario (regolamento comunale):
  - fasce orarie per ogni giorno della settimana, anche al minuto (09:30-13:00);
  - periodi dell'anno con un proprio orario settimanale (es. estate);
  - giorni festivi nazionali calcolati ogni anno, più festività locali;
  - chiusure straordinarie tra due date (manutenzioni, eventi).

Le tariffe riproducono la D.G.C. n. 37/2025 ("approvazione tariffe impianti
sportivi 2025") del Comune di Gioia del Colle:
  - calcetto: 40 EUR totali a partita
  - tennis singolo: 10 EUR totali; tennis doppio: 20 EUR totali
Un altro luogo sceglie le attività con SPAZIO_ATTIVITA; attività nuove si
aggiungono al dizionario ATTIVITA qui sotto.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class Activity:
    code: str
    name: str
    fee_cents: int          # importo totale per slot, in centesimi
    players: str
    setup_note: str          # nota per il custode

    @property
    def fee_eur(self) -> str:
        return f"{self.fee_cents / 100:.2f}".replace(".", ",")


ACTIVITIES: dict[str, Activity] = {
    "calcetto": Activity("calcetto", "Calcetto (calcio a 5)", 4000, "fino a 10", "Montare porte calcetto"),
    "tennis_singolo": Activity("tennis_singolo", "Tennis – singolo", 1000, "2", "Montare rete tennis"),
    "tennis_doppio": Activity("tennis_doppio", "Tennis – doppio", 2000, "4", "Montare rete tennis"),
}

FEES_SOURCE = os.getenv("FONTE_TARIFFE") or "D.G.C. n. 37/2025 – approvazione tariffe impianti sportivi 2025"
WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

# festività nazionali a data fissa (giorno, mese); Pasqua e Lunedì dell'Angelo si calcolano
FIXED_HOLIDAYS = [(1, 1), (6, 1), (25, 4), (1, 5), (2, 6), (15, 8), (1, 11), (8, 12), (25, 12), (26, 12)]


def easter(year: int) -> date:
    """Domenica di Pasqua nel calendario gregoriano (algoritmo di Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def national_holidays(year: int) -> set[date]:
    """I giorni "rossi" del calendario italiano per l'anno dato."""
    holidays = {date(year, m, g) for g, m in FIXED_HOLIDAYS}
    holidays |= {easter(year), easter(year) + timedelta(days=1)}
    if year >= 2026:
        holidays.add(date(year, 10, 4))   # San Francesco d'Assisi, festa nazionale dal 2026
    return holidays


def _minutes(text: str, field_name: str) -> int:
    """"9", "09", "9:30", "24" -> minuti dalla mezzanotte."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text.strip())
    if not m:
        raise ValueError(f"{field_name}: usare intervalli apertura-chiusura, es. 9-13,14-22 oppure 09:30-13:00")
    hours_, minutes = int(m.group(1)), int(m.group(2) or 0)
    if minutes > 59 or hours_ * 60 + minutes > 24 * 60:
        raise ValueError(f"{field_name}: orario {text.strip()} non valido (da 00:00 a 24:00)")
    return hours_ * 60 + minutes


def bands(text: str, field_name: str) -> list[tuple[int, int]]:
    """Da "9-13,14-22" o "09:30-13:00, 15:00-22:00" agli intervalli in minuti. Vuoto = chiuso."""
    out = []
    for interval in filter(None, (x.strip() for x in text.replace(";", ",").split(","))):
        parts = interval.replace("–", "-").split("-")
        if len(parts) != 2:
            raise ValueError(f"{field_name}: usare intervalli apertura-chiusura, es. 9-13,14-22 oppure 09:30-13:00")
        opens, closes = _minutes(parts[0], field_name), _minutes(parts[1], field_name)
        if not opens < closes:
            raise ValueError(f"{field_name}: intervallo {interval} non valido (l'apertura viene prima della chiusura)")
        out.append((opens, closes))
    return sorted(out)


def _slot_starts(text: str, duration: int, field_name: str) -> tuple[time, ...]:
    """Dalle fasce orarie agli orari di inizio degli slot che vi rientrano per intero."""
    starts: set[int] = set()
    for opens, closes in bands(text, field_name):
        if closes - opens < duration:
            raise ValueError(f"{field_name}: la fascia {opens // 60:02d}:{opens % 60:02d}-{closes // 60:02d}:{closes % 60:02d} "
                             f"è più corta di uno slot ({duration} minuti)")
        starts.update(range(opens, closes - duration + 1, duration))
    return tuple(time(m // 60, m % 60) for m in sorted(starts))


def _day_month(text: str, field_name: str) -> tuple[int, int]:
    try:
        g, m = (int(x) for x in text.strip().split("/"))
        date(2024, m, g)   # anno bisestile: ammette il 29/02
    except ValueError:
        raise ValueError(f"{field_name}: usare date GG/MM, es. 01/06") from None
    return m, g


def _intervals(slot_times: tuple[time, ...], duration: int) -> list[tuple[int, int]]:
    """Orari di inizio degli slot -> intervalli continui in minuti."""
    out: list[list[int]] = []
    for t in slot_times:
        m = t.hour * 60 + t.minute
        if out and out[-1][1] == m:
            out[-1][1] = m + duration
        else:
            out.append([m, m + duration])
    return [(a, b) for a, b in out]


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _readable(slot_times: tuple[time, ...], duration: int) -> str:
    """Orari di inizio degli slot -> "15:00–22:00" (più intervalli separati da virgola)."""
    return ", ".join(f"{_hhmm(a)}–{_hhmm(b)}" for a, b in _intervals(slot_times, duration))


def bands_text(slot_times: tuple[time, ...], duration: int) -> str:
    """Orari di inizio degli slot -> "15:00-22:00", la sintassi dei moduli e del .env."""
    return ", ".join(f"{_hhmm(a)}-{_hhmm(b)}" for a, b in _intervals(slot_times, duration))


def _week_readable(calendar: dict[int, tuple[time, ...]], duration: int) -> str:
    """{0: (15:00, ...), 5: (9:00, ...)} -> "lun, mar, mer 15:00–22:00 · sab 09:00–13:00"."""
    groups: list[tuple[list[int], tuple[time, ...]]] = []
    for g in sorted(k for k, v in calendar.items() if v):
        for days, slot_times in groups:
            if slot_times == calendar[g]:
                days.append(g)
                break
        else:
            groups.append(([g], calendar[g]))
    return " · ".join(f"{', '.join(WEEKDAYS[g] for g in days)} {_readable(slot_times, duration)}" for days, slot_times in groups)


@dataclass(frozen=True)
class Period:
    """Orario settimanale che sostituisce quello normale tra due date, ogni anno (es. estate)."""
    from_: tuple[int, int]       # (mese, giorno)
    to_: tuple[int, int]
    calendar: dict[int, tuple[time, ...]]   # giorno della settimana (0=lun) -> orari di inizio degli slot
    name: str = ""

    def contains(self, day: date) -> bool:
        md = (day.month, day.day)
        if self.from_ <= self.to_:
            return self.from_ <= md <= self.to_
        return md >= self.from_ or md <= self.to_   # periodo a cavallo di Capodanno


@dataclass(frozen=True)
class Closure:
    """Chiusura straordinaria tra due date incluse (manutenzione, evento, ordinanza)."""
    from_: date
    to_: date
    reason: str = ""


_ACTIVITY_CODE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def _integer(value, field_name: str, minimum: int, maximum: int) -> int:
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{field_name}: inserire un numero intero") from None
    if not minimum <= n <= maximum:
        raise ValueError(f"{field_name}: valore tra {minimum} e {maximum}")
    return n


def _week_from_data(week: dict, duration: int, field_name: str) -> dict[int, tuple[time, ...]]:
    cal = {}
    for i, g in enumerate(WEEKDAYS):
        slot_times = _slot_starts(str(week.get(g) or ""), duration, f"{field_name}, {WEEKDAY_NAMES[i]}")
        if slot_times:
            cal[i] = slot_times
    return cal


WEEKDAY_NAMES = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


@dataclass(frozen=True)
class FeeBand:
    """Fascia tariffaria del regolamento (es. tariffa serale con illuminazione).

    Vale per gli slot che iniziano tra start_min e end_min, nei giorni indicati (vuoto = tutti),
    e sostituisce la tariffa base delle attività per cui indica un importo.
    """
    name: str
    start_min: int                  # minuti dalla mezzanotte, incluso
    end_min: int                    # escluso
    weekdays: frozenset[int]        # 0=lun; vuoto = tutti i giorni
    fees: dict[str, int]            # codice attività -> importo in centesimi

    def applies(self, start: datetime) -> bool:
        minute = start.hour * 60 + start.minute
        return (not self.weekdays or start.weekday() in self.weekdays) and self.start_min <= minute < self.end_min

    @property
    def readable(self) -> str:
        days = ", ".join(WEEKDAYS[d] for d in sorted(self.weekdays)) if self.weekdays else ""
        return f"{self.name} ({_hhmm(self.start_min)}–{_hhmm(self.end_min)}{', ' + days if days else ''})"


def _fee_bands_from_data(items: list, catalog: dict) -> tuple[FeeBand, ...]:
    bands_ = []
    for i, b in enumerate(items, 1):
        name = str(b.get("nome") or "").strip()[:60]
        label = f"Fascia tariffaria {name or i}"
        if not name:
            raise ValueError(f"{label}: il nome è obbligatorio, es. Serale con illuminazione")
        start_min = _minutes(str(b.get("dalle") or ""), f"{label}, dalle")
        end_min = _minutes(str(b.get("alle") or ""), f"{label}, alle")
        if start_min >= end_min:
            raise ValueError(f"{label}: l'ora di inizio viene prima di quella di fine")
        days = b.get("giorni") or []
        if any(d not in WEEKDAYS for d in days):
            raise ValueError(f"{label}: giorni non validi, usare {','.join(WEEKDAYS)}")
        fees = {}
        for code, cents in (b.get("tariffe") or {}).items():
            if cents in (None, ""):
                continue
            if code not in catalog:
                raise ValueError(f"{label}: attività sconosciuta {code}")
            fees[code] = _integer(cents, f"{label}, tariffa {catalog[code].name}", 0, 10_000_00)
        if not fees:
            raise ValueError(f"{label}: indicare la tariffa di almeno un'attività")
        bands_.append(FeeBand(name, start_min, end_min, frozenset(WEEKDAYS.index(d) for d in days), fees))
    return tuple(bands_)


@dataclass(frozen=True)
class Venue:
    name: str = "Campo comunale coperto di via Benagiano"
    address: str = "Via Benagiano, 70023 Gioia del Colle (BA)"
    municipality: str = "Comune di Gioia del Colle"
    municipality_address: str = "Piazza Margherita di Savoia, 10 – 70023 Gioia del Colle (BA)"
    municipality_site: str = "https://www.comune.gioiadelcolle.ba.it/"
    office: str = "Ufficio Cultura, Istruzione e Sport"
    # attività prenotabili (codici del catalogo, nell'ordine mostrato)
    activities: tuple[str, ...] = ("calcetto", "tennis_singolo", "tennis_doppio")
    # tutte le attività conosciute, anche quelle non più prenotabili (servono a mostrare le prenotazioni passate)
    catalog: dict[str, Activity] = field(default_factory=lambda: dict(ACTIVITIES))
    fees_source: str = FEES_SOURCE
    # giorno della settimana (0=lun) -> orari di inizio degli slot
    calendar: dict[int, tuple[time, ...]] = field(
        default_factory=lambda: {d: tuple(time(h) for h in range(15, 22)) for d in range(6)})
    # orari diversi in alcuni periodi dell'anno; il primo periodo che comprende il giorno vince
    periods: tuple[Period, ...] = ()
    # orari nei giorni festivi: () = chiuso, None = come un giorno normale
    holidays: tuple[time, ...] | None = ()
    # festività locali oltre a quelle nazionali: (mese, giorno, anno oppure None = ogni anno)
    extra_holidays: tuple[tuple[int, int, int | None], ...] = ()
    # chiusure straordinarie tra due date
    closures: tuple[Closure, ...] = ()
    slot_minutes: int = 60
    advance_days: int = 14   # finestra di prenotabilità
    cancel_hours: int = 24   # annullamento online fino a N ore prima
    code_prefix: str = "GDC"  # numeri di prenotazione GDC-XXXX-XXXX
    # fasce tariffarie: la prima che comprende l'inizio dello slot sostituisce la tariffa base
    fee_bands: tuple[FeeBand, ...] = ()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Venue":
        """Legge il luogo dalle variabili SPAZIO_*, COMUNE_* e UFFICIO_NOME; le assenti restano predefinite."""
        e = {k: v for k, v in (os.environ if env is None else env).items() if v not in (None, "")}
        base = cls()
        duration = int(e.get("SPAZIO_DURATA_MIN", base.slot_minutes))
        activity = tuple(a.strip() for a in e["SPAZIO_ATTIVITA"].split(",") if a.strip()) \
            if "SPAZIO_ATTIVITA" in e else base.activities
        unknown = [a for a in activity if a not in ACTIVITIES]
        if unknown or not activity:
            raise ValueError(f"SPAZIO_ATTIVITA: attività non previste {unknown}; disponibili: {', '.join(ACTIVITIES)}")
        calendar = base.calendar
        if "SPAZIO_GIORNI" in e or "SPAZIO_ORARIO" in e:
            days = [g.strip().lower()[:3] for g in e.get("SPAZIO_GIORNI", "lun,mar,mer,gio,ven,sab").split(",")]
            if any(g not in WEEKDAYS for g in days):
                raise ValueError(f"SPAZIO_GIORNI: usare {','.join(WEEKDAYS)}")
            slot_times = _slot_starts(e.get("SPAZIO_ORARIO", "15-22"), duration, "SPAZIO_ORARIO")
            calendar = {WEEKDAYS.index(g): slot_times for g in days}
        periods = []
        for entry in filter(None, (v.strip() for v in e.get("SPAZIO_ORARIO_PERIODI", "").split(";"))):
            try:
                date_, slot_times_ = entry.split("=")
                from_, to_ = date_.split("-")
            except ValueError:
                raise ValueError("SPAZIO_ORARIO_PERIODI: usare GG/MM-GG/MM=orari, es. 01/06-15/09=9-13,16-24") from None
            period_times = _slot_starts(slot_times_, duration, "SPAZIO_ORARIO_PERIODI")
            periods.append(Period(_day_month(from_, "SPAZIO_ORARIO_PERIODI"), _day_month(to_, "SPAZIO_ORARIO_PERIODI"),
                                   {g: period_times for g in calendar}))
        holidays = e.get("SPAZIO_FESTIVI", "chiuso").strip().lower()
        holidays = () if holidays == "chiuso" else None if holidays == "aperto" else _slot_starts(holidays, duration, "SPAZIO_FESTIVI")
        return cls(
            name=e.get("SPAZIO_NOME", base.name),
            address=e.get("SPAZIO_INDIRIZZO", base.address),
            municipality=e.get("COMUNE_NOME", base.municipality),
            municipality_address=e.get("COMUNE_INDIRIZZO", base.municipality_address),
            municipality_site=e.get("COMUNE_SITO", base.municipality_site),
            office=e.get("UFFICIO_NOME", base.office),
            fees_source=e.get("FONTE_TARIFFE", base.fees_source),
            activities=activity, calendar=calendar, periods=tuple(periods), holidays=holidays,
            extra_holidays=_extra_holidays(e.get("SPAZIO_FESTIVI_EXTRA", ""), "SPAZIO_FESTIVI_EXTRA"), slot_minutes=duration,
            advance_days=int(e.get("SPAZIO_PREAVVISO_GIORNI", base.advance_days)),
            cancel_hours=int(e.get("SPAZIO_ORE_ANNULLAMENTO", base.cancel_hours)),
            code_prefix=e.get("CODICE_PREFISSO", base.code_prefix).upper(),
        )

    # ------------------------------------------------------------ formato del back-office
    def to_data(self) -> dict[str, dict]:
        """Il luogo nelle sezioni del back-office (luogo, attivita, orari), con valori testuali modificabili."""
        d = self.slot_minutes
        holidays = "aperto" if self.holidays is None else (bands_text(self.holidays, d) or "chiuso")
        order = list(self.activities) + [c for c in self.catalog if c not in self.activities]
        return {
            "luogo": {"nome": self.name, "indirizzo": self.address, "comune": self.municipality,
                      "comune_indirizzo": self.municipality_address, "comune_sito": self.municipality_site,
                      "ufficio": self.office, "prefisso_codice": self.code_prefix},
            "attivita": {"fonte_tariffe": self.fees_source, "elenco": [
                {"codice": c, "nome": a.name, "tariffa_cent": a.fee_cents, "giocatori": a.players,
                 "preparazione": a.setup_note, "attiva": c in self.activities}
                for c in order for a in [self.catalog[c]]],
                "fasce_tariffarie": [{"nome": b.name, "dalle": _hhmm(b.start_min), "alle": _hhmm(b.end_min),
                                      "giorni": [WEEKDAYS[d] for d in sorted(b.weekdays)], "tariffe": dict(b.fees)}
                                     for b in self.fee_bands]},
            "orari": {
                "durata_min": d, "preavviso_giorni": self.advance_days, "ore_annullamento": self.cancel_hours,
                "settimana": {g: bands_text(self.calendar.get(i, ()), d) for i, g in enumerate(WEEKDAYS)},
                "periodi": [{"nome": p.name, "dal": f"{p.from_[1]:02d}/{p.from_[0]:02d}", "al": f"{p.to_[1]:02d}/{p.to_[0]:02d}",
                             "settimana": {g: bands_text(p.calendar.get(i, ()), d) for i, g in enumerate(WEEKDAYS)}}
                            for p in self.periods],
                "festivi": holidays,
                "festivi_extra": ",".join(f"{g:02d}/{m:02d}" + (f"/{a}" if a else "") for m, g, a in self.extra_holidays),
                "chiusure": [{"dal": c.from_.isoformat(), "al": c.to_.isoformat(), "motivo": c.reason} for c in self.closures],
            },
        }

    @classmethod
    def from_data(cls, data: dict[str, dict]) -> "Venue":
        """Costruisce e valida il luogo dalle sezioni del back-office. Errori: ValueError con il nome del campo."""
        venue, act, slot_times = data.get("luogo", {}), data.get("attivita", {}), data.get("orari", {})
        for field_name, label in (("nome", "Nome del luogo"), ("indirizzo", "Indirizzo del luogo"),
                                 ("comune", "Nome del Comune"), ("ufficio", "Ufficio competente")):
            if not str(venue.get(field_name) or "").strip():
                raise ValueError(f"{label}: campo obbligatorio")
        prefix = str(venue.get("prefisso_codice") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,5}", prefix):
            raise ValueError("Prefisso dei numeri di prenotazione: da 2 a 5 lettere o cifre, es. GDC")
        site = str(venue.get("comune_sito") or "").strip()
        if site and not site.startswith(("https://", "http://")):
            raise ValueError("Sito del Comune: indirizzo che inizia con https://")

        catalog, active = {}, []
        for i, a in enumerate(act.get("elenco", []), 1):
            code = str(a.get("codice") or "").strip().lower()
            if not _ACTIVITY_CODE.match(code) or code == "blocco":
                raise ValueError(f"Attività {i}: codice non valido (minuscole, cifre e _, es. pallavolo)")
            if code in catalog:
                raise ValueError(f"Attività {i}: il codice {code} è già usato")
            name = str(a.get("nome") or "").strip()
            if not name:
                raise ValueError(f"Attività {code}: il nome è obbligatorio")
            fee = _integer(a.get("tariffa_cent", 0), f"Attività {code}, tariffa", 0, 10_000_00)
            catalog[code] = Activity(code, name[:80], fee, str(a.get("giocatori") or "").strip()[:40],
                                        str(a.get("preparazione") or "").strip()[:120])
            if a.get("attiva"):
                active.append(code)
        if not active:
            raise ValueError("Attività: almeno una deve essere prenotabile")
        for code, a in ACTIVITIES.items():   # le attività predefinite restano note anche se mai usate
            catalog.setdefault(code, a)

        duration = _integer(slot_times.get("durata_min", 60), "Durata dello slot (minuti)", 15, 480)
        calendar = _week_from_data(slot_times.get("settimana", {}), duration, "Orario settimanale")
        periods = []
        for i, p in enumerate(slot_times.get("periodi", []), 1):
            name = str(p.get("nome") or "").strip()[:60]
            field_name = f"Periodo {name or i}"
            periods.append(Period(_day_month(str(p.get("dal") or ""), f"{field_name}, dal"),
                                   _day_month(str(p.get("al") or ""), f"{field_name}, al"),
                                   _week_from_data(p.get("settimana", {}), duration, field_name), name))
        holidays = str(slot_times.get("festivi") or "chiuso").strip().lower()
        holidays = () if holidays == "chiuso" else None if holidays == "aperto" else _slot_starts(holidays, duration, "Giorni festivi")
        closures = []
        for i, c in enumerate(slot_times.get("chiusure", []), 1):
            try:
                from_, to_ = date.fromisoformat(str(c.get("dal"))), date.fromisoformat(str(c.get("al") or c.get("dal")))
            except ValueError:
                raise ValueError(f"Chiusura {i}: date non valide") from None
            if to_ < from_:
                raise ValueError(f"Chiusura {i}: la data di fine viene prima di quella di inizio")
            closures.append(Closure(from_, to_, str(c.get("motivo") or "").strip()[:200]))
        return cls(
            name=str(venue["nome"]).strip(), address=str(venue["indirizzo"]).strip(),
            municipality=str(venue["comune"]).strip(), municipality_address=str(venue.get("comune_indirizzo") or "").strip(),
            municipality_site=site, office=str(venue["ufficio"]).strip(), code_prefix=prefix,
            activities=tuple(active), catalog=catalog,
            fee_bands=_fee_bands_from_data(act.get("fasce_tariffarie") or [], catalog),
            fees_source=str(act.get("fonte_tariffe") or "").strip(),
            calendar=calendar, periods=tuple(periods), holidays=holidays,
            extra_holidays=_extra_holidays(str(slot_times.get("festivi_extra") or ""), "Festività locali"),
            closures=tuple(sorted(closures, key=lambda c: c.from_)), slot_minutes=duration,
            advance_days=_integer(slot_times.get("preavviso_giorni", 14), "Giorni di anticipo", 1, 365),
            cancel_hours=_integer(slot_times.get("ore_annullamento", 24), "Ore minime per annullare online", 0, 720),
        )

    # ------------------------------------------------------------ calendario
    def is_holiday(self, day: date) -> bool:
        """Giorno "rosso": festività nazionale o locale (SPAZIO_FESTIVI_EXTRA)."""
        return day in national_holidays(day.year) or any(
            (m, g) == (day.month, day.day) and a in (None, day.year) for m, g, a in self.extra_holidays)

    def fee_band_for(self, activity: str, start: datetime) -> FeeBand | None:
        return next((b for b in self.fee_bands if activity in b.fees and b.applies(start)), None)

    def fee_for(self, activity: str, start: datetime) -> int:
        """Importo in centesimi per uno slot: tariffa della fascia, oppure tariffa base dell'attività."""
        band = self.fee_band_for(activity, start)
        return band.fees[activity] if band else self.catalog[activity].fee_cents

    def closure_on(self, day: date) -> Closure | None:
        return next((c for c in self.closures if c.from_ <= day <= c.to_), None)

    def slots_on(self, day: date) -> tuple[time, ...]:
        """Orari di inizio degli slot in una data: chiusure, periodi, giorno della settimana e festività."""
        if self.closure_on(day):
            return ()
        period = next((p for p in self.periods if p.contains(day)), None)
        week = period.calendar if period else self.calendar
        if not week.get(day.weekday()):
            return ()
        if self.holidays is not None and self.is_holiday(day):
            return self.holidays
        return week[day.weekday()]

    @property
    def readable_hours(self) -> str:
        if not any(self.calendar.values()):
            text = "chiuso"
        else:
            text = f"{_week_readable(self.calendar, self.slot_minutes)} (slot da {self.slot_minutes} minuti)"
        for p in self.periods:
            slot_times = {v for v in p.calendar.values() if v}
            uniform = len(slot_times) == 1 and set(p.calendar) == set(self.calendar)
            detail = (_readable(slot_times.pop(), self.slot_minutes) if uniform
                         else _week_readable(p.calendar, self.slot_minutes)) or "chiuso"
            text += f"; {p.name + ' ' if p.name else ''}dal {p.from_[1]:02d}/{p.from_[0]:02d} al {p.to_[1]:02d}/{p.to_[0]:02d}: {detail}"
        if self.holidays is not None:
            text += "; nei giorni festivi: " + (_readable(self.holidays, self.slot_minutes) or "chiuso")
        return text


def _extra_holidays(text: str, field_name: str) -> tuple[tuple[int, int, int | None], ...]:
    extra = []
    for entry in filter(None, (v.strip() for v in text.split(","))):
        parts = entry.split("/")
        m, g = _day_month("/".join(parts[:2]), field_name)
        if len(parts) > 3 or (len(parts) == 3 and not (parts[2].isdigit() and len(parts[2]) == 4)):
            raise ValueError(f"{field_name}: usare GG/MM (ogni anno) o GG/MM/AAAA, es. 26/05,14/08/2027")
        extra.append((m, g, int(parts[2]) if len(parts) == 3 else None))
    return tuple(extra)
