"""Simulazione di carico: cittadini virtuali prenotano in parallelo attraverso il sito.

Ogni cittadino percorre il flusso reale (SPID simulato, scelta dello slot,
pagamento pagoPA simulato). Metà dei cittadini punta di proposito agli stessi
orari, per verificare che nessuno slot venga venduto due volte. Alla fine il
risultato si controlla sul database, tramite l'API dell'ufficio:
  - ogni slot occupato porta registrato un solo numero di prenotazione;
  - ogni prenotazione confermata corrisponde allo slot su cui è registrata.

    python app/scripts/simulate.py --url http://localhost:8001 --cittadini 30
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import threading
from collections import Counter
from urllib.parse import parse_qs, urlparse

import httpx


def csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def citizen(url: str, start: str, activity: str, results: list, barrier: threading.Barrier) -> None:
    with httpx.Client(base_url=url, timeout=30, follow_redirects=False) as c:
        c.get("/auth/simulato?ritorno=/")
        r = c.get("/prenota", params={"inizio": start, "attivita": activity})
        token = csrf(r.text)
        barrier.wait()  # tutti inviano insieme
        r = c.post("/prenota", data={"inizio": start, "attivita": activity, "csrf_token": token})
        if r.status_code != 303:
            results.append(("rifiutata", start, None, r.status_code))
            return
        page_html = r.headers["location"]
        r = c.get(page_html)
        return_url = parse_qs(urlparse(page_html).query)["ritorno"][0]
        c.post(urlparse(page_html).path, data={"ritorno": return_url, "csrf_token": csrf(r.text)})
        r = c.get(urlparse(return_url).path)  # ritorno da pagoPA: l'app verifica il pagamento
        code = return_url.rstrip("/").rsplit("/", 1)[-1]
        ok = r.status_code == 303 and r.headers["location"] == f"/prenotazione/{code}"
        results.append(("confermata" if ok else "non_confermata", start, code, r.status_code))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--cittadini", type=int, default=30)
    ap.add_argument("--utente", default="ufficio.sport")
    ap.add_argument("--password", default="cambiami")
    ap.add_argument("--seme", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    office = (a.user, a.password)

    info = httpx.get(f"{a.url}/api/v1/spazio").json()
    free = [s["inizio"] for g in httpx.get(f"{a.url}/api/v1/disponibilita?giorni=7").json()
              for s in g["slot"] if s["libero"]]
    if len(free) < 4:
        print("Troppi pochi slot liberi: riavviare l'istanza (docker compose restart demo)")
        return 1
    contested = rng.sample(free, 3)                       # orari su cui si scontrano in molti
    requests = [(rng.choice(contested) if i % 2 == 0 else rng.choice(free), rng.choice(info["attivita"])["codice"])
                 for i in range(a.citizens)]
    print(f"Luogo: {info['nome']} – {info['comune']}")
    print(f"{a.citizens} cittadini, {len(free)} slot liberi, 3 slot contesi da metà dei cittadini\n")

    results, barrier = [], threading.Barrier(a.citizens)
    threads = [threading.Thread(target=citizen, args=(a.url, start, act, results, barrier)) for start, act in requests]
    for f in threads:
        f.start()
    for f in threads:
        f.join()

    confirmed = {e[2]: e[1] for e in results if e[0] == "confermata"}
    rejected = [e for e in results if e[0] == "rifiutata"]
    print(f"Prenotazioni confermate: {len(confirmed)}   rifiutate (slot già preso): {len(rejected)}")

    # verifica sul database tramite l'API dell'ufficio
    occ = httpx.get(f"{a.url}/api/v1/ufficio/occupazione?giorni=7", auth=office).json()
    on_slot = {s["inizio"]: s for g in occ for s in g["slot"]}
    errors = []
    for code, start in confirmed.items():
        if on_slot[start]["codice"] != code:
            errors.append(f"{code}: sullo slot {start} c'è {on_slot[start]['codice']}")
    duplicates = [i for i, n in Counter(confirmed.values()).items() if n > 1]
    errors += [f"slot {i} venduto più volte" for i in duplicates]
    contested_winners = Counter(confirmed.values())
    print("\nSlot contesi: chi ha vinto")
    print(f"  {'slot':<26} {'richieste':>9}  numero di prenotazione registrato")
    for start in contested:
        n = sum(1 for r in requests if r[0] == start)
        print(f"  {start:<26} {n:>9}  {on_slot[start]['codice']}  ({contested_winners[start]} confermata)")

    print("\nTabella slot (estratto, dal database):")
    print(f"  {'inizio':<26} {'stato':<12} {'numero':<15} intestatario")
    for start in sorted(set(confirmed.values()))[:12]:
        s = on_slot[start]
        print(f"  {start:<26} {s['stato']:<12} {s['codice']:<15} {s['intestatario']}")

    if errors:
        print("\nERRORI:\n  " + "\n  ".join(errors))
        return 1
    print(f"\nOK: {len(confirmed)} prenotazioni, ognuna registrata sul proprio slot; nessuno slot venduto due volte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
