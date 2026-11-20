"""Server dimostrativo con dati fittizi, per presentazioni e video.

Avvia l'app con un orologio che parte da un istante fisso (DEMO_ORA, di default
lunedì 9 novembre 2026 ore 18:35) e scorre in tempo reale, e popola il database
con prenotazioni di cittadini inventati. Nessun dato reale.

    DATABASE_URL=postgresql://… python app/scripts/demo.py   # http://localhost:8000
    docker compose --profile demo up -d   # http://localhost:8001
"""
from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from venue_booking.adapters.identity import Citizen  # noqa: E402
from venue_booking.booking import TZ, BookingError  # noqa: E402
from venue_booking.config import Settings  # noqa: E402
from venue_booking.db import Database  # noqa: E402
from venue_booking.main import create_app  # noqa: E402

CITIZENS = [  # nomi e codici fiscali inventati
    Citizen("LRSGNN85C12E038K", "Giovanni", "Lorusso", "g.lorusso@example.org"),
    Citizen("DGNFNC90H45E038P", "Francesca", "De Giorgio", "f.degiorgio@example.org"),
    Citizen("CPTMRC78D03E038W", "Marco", "Capotorto", "m.capotorto@example.org"),
    Citizen("NTRLSN95R51E038T", "Alessandra", "Notarnicola", "a.notarnicola@example.org"),
    Citizen("PSNDNC88B20E038Q", "Domenico", "Pisani", "d.pisani@example.org"),
    Citizen("CLMSRA99E62E038N", "Sara", "Colamonico", "s.colamonico@example.org"),
    Citizen("GNTVTO82L14E038Z", "Vito", "Gentile", "v.gentile@example.org"),
    Citizen("MNGLRA93P58E038J", "Laura", "Mongelli", "l.mongelli@example.org"),
]
RESERVATIONS = ["ASD Gioiese Calcio a 5 – allenamento", "Scuola media Losapio – torneo d'istituto",
           "Manutenzione impianto luci", "Tennis Club Gioia – lezioni junior"]


def populate(app, now: datetime, seed: int = 37) -> None:
    service = app.state.service
    if service.items():
        return
    rng = random.Random(seed)
    today = now.date()

    def book(start: datetime, activity: str, person: Citizen) -> None:
        try:
            p = service.book(activity, start.isoformat(), person, note=None)
            service.confirm_manually(p["codice"], "RF" + "".join(rng.choice("0123456789ABCDEF") for _ in range(16)))
        except BookingError:
            pass

    # stasera: il custode ha già qualche ingresso da verificare
    book(datetime.combine(today, datetime.min.time(), TZ).replace(hour=19), "calcetto", CITIZENS[0])
    book(datetime.combine(today, datetime.min.time(), TZ).replace(hour=20), "tennis_doppio", CITIZENS[1])
    service.block(datetime.combine(today, datetime.min.time(), TZ).replace(hour=21).isoformat(), RESERVATIONS[0])

    # prossimi 14 giorni: circa metà degli slot occupati, venerdì sera alle 20 già preso
    for i in range(1, 15):
        g = today + timedelta(days=i)
        if g.weekday() == 6:
            continue
        for h in range(15, 22):
            start = datetime(g.year, g.month, g.day, h, tzinfo=TZ)
            if g.weekday() == 4 and h == 20:
                book(start, "calcetto", CITIZENS[2])
            elif rng.random() < 0.08:
                service.block(start.isoformat(), rng.choice(RESERVATIONS))
            elif rng.random() < (0.55 if h >= 18 else 0.3):
                act = rng.choices(["calcetto", "tennis_singolo", "tennis_doppio"], [6, 2, 2])[0]
                book(start, act, rng.choice(CITIZENS))

    # una prenotazione in attesa di pagamento (allo sportello)
    g = today + timedelta(days=2)
    for h in range(15, 22):
        try:
            service.book("tennis_singolo", datetime(g.year, g.month, g.day, h, tzinfo=TZ).isoformat(),
                             CITIZENS[7], note="Paga allo sportello")
            break
        except BookingError:
            continue


def main() -> None:
    start_time = datetime.fromisoformat(os.getenv("DEMO_ORA", "2026-11-09T18:35:00")).replace(tzinfo=TZ)
    t0 = time.monotonic()
    now = lambda: start_time + timedelta(seconds=time.monotonic() - t0)  # noqa: E731

    # la demo vive in uno schema PostgreSQL a parte ("demo"), ricreato da zero a ogni avvio
    os.environ.setdefault("DATABASE_SCHEMA", "demo")
    settings = Settings()
    if settings.database_schema == "public":
        raise SystemExit("La demo cancella i dati del suo schema: usare DATABASE_SCHEMA diverso da public")
    old = Database(settings.database_url, settings.database_schema)
    old.drop_schema()
    old.close()

    app = create_app(settings, now=now)
    populate(app, now())
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
