"""Server dimostrativo con dati fittizi, per presentazioni e video.

Avvia l'app con un orologio che parte da un istante fisso (DEMO_ORA, di default
lunedì 9 novembre 2026 ore 18:35) e scorre in tempo reale, e popola il database
con prenotazioni di cittadini inventati. Nessun dato reale.

    python app/scripts/demo.py            # http://localhost:8000
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

from prenota.adapters.identity import Cittadino  # noqa: E402
from prenota.booking import TZ, ErrorePrenotazione  # noqa: E402
from prenota.config import Settings  # noqa: E402
from prenota.main import create_app  # noqa: E402

CITTADINI = [  # nomi e codici fiscali inventati
    Cittadino("LRSGNN85C12E038K", "Giovanni", "Lorusso", "g.lorusso@example.org"),
    Cittadino("DGNFNC90H45E038P", "Francesca", "De Giorgio", "f.degiorgio@example.org"),
    Cittadino("CPTMRC78D03E038W", "Marco", "Capotorto", "m.capotorto@example.org"),
    Cittadino("NTRLSN95R51E038T", "Alessandra", "Notarnicola", "a.notarnicola@example.org"),
    Cittadino("PSNDNC88B20E038Q", "Domenico", "Pisani", "d.pisani@example.org"),
    Cittadino("CLMSRA99E62E038N", "Sara", "Colamonico", "s.colamonico@example.org"),
    Cittadino("GNTVTO82L14E038Z", "Vito", "Gentile", "v.gentile@example.org"),
    Cittadino("MNGLRA93P58E038J", "Laura", "Mongelli", "l.mongelli@example.org"),
]
RISERVE = ["ASD Gioiese Calcio a 5 – allenamento", "Scuola media Losapio – torneo d'istituto",
           "Manutenzione impianto luci", "Tennis Club Gioia – lezioni junior"]


def popola(app, ora: datetime, seme: int = 37) -> None:
    servizio = app.state.servizio
    if servizio.elenco():
        return
    rnd = random.Random(seme)
    oggi = ora.date()

    def prenota(inizio: datetime, attivita: str, chi: Cittadino) -> None:
        try:
            p = servizio.prenota("benagiano", attivita, inizio.isoformat(), chi, note=None)
            servizio.conferma_manuale(p["codice"], "RF" + "".join(rnd.choice("0123456789ABCDEF") for _ in range(16)))
        except ErrorePrenotazione:
            pass

    # stasera: il custode ha già qualche ingresso da verificare
    prenota(datetime.combine(oggi, datetime.min.time(), TZ).replace(hour=19), "calcetto", CITTADINI[0])
    prenota(datetime.combine(oggi, datetime.min.time(), TZ).replace(hour=20), "tennis_doppio", CITTADINI[1])
    servizio.blocca("benagiano", datetime.combine(oggi, datetime.min.time(), TZ).replace(hour=21).isoformat(), RISERVE[0])

    # prossimi 14 giorni: circa metà degli slot occupati, venerdì sera alle 20 già preso
    for i in range(1, 15):
        g = oggi + timedelta(days=i)
        if g.weekday() == 6:
            continue
        for h in range(15, 22):
            inizio = datetime(g.year, g.month, g.day, h, tzinfo=TZ)
            if g.weekday() == 4 and h == 20:
                prenota(inizio, "calcetto", CITTADINI[2])
            elif rnd.random() < 0.08:
                servizio.blocca("benagiano", inizio.isoformat(), rnd.choice(RISERVE))
            elif rnd.random() < (0.55 if h >= 18 else 0.3):
                att = rnd.choices(["calcetto", "tennis_singolo", "tennis_doppio"], [6, 2, 2])[0]
                prenota(inizio, att, rnd.choice(CITTADINI))

    # una prenotazione in attesa di pagamento (allo sportello)
    g = oggi + timedelta(days=2)
    for h in range(15, 22):
        try:
            servizio.prenota("benagiano", "tennis_singolo", datetime(g.year, g.month, g.day, h, tzinfo=TZ).isoformat(),
                             CITTADINI[7], note="Paga allo sportello")
            break
        except ErrorePrenotazione:
            continue


def main() -> None:
    partenza = datetime.fromisoformat(os.getenv("DEMO_ORA", "2026-11-09T18:35:00")).replace(tzinfo=TZ)
    t0 = time.monotonic()
    adesso = lambda: partenza + timedelta(seconds=time.monotonic() - t0)  # noqa: E731

    os.environ.setdefault("DB_PATH", str(Path(__file__).resolve().parents[2] / "demo.db"))
    db = Path(os.environ["DB_PATH"])
    for f in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        f.unlink(missing_ok=True)

    app = create_app(Settings(), adesso=adesso)
    popola(app, adesso())
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
