"""Simulazione di carico: cittadini virtuali prenotano in parallelo attraverso il sito.

Ogni cittadino percorre il flusso reale (SPID simulato, scelta dello slot,
pagamento pagoPA simulato). Metà dei cittadini punta di proposito agli stessi
orari, per verificare che nessuno slot venga venduto due volte. Alla fine il
risultato si controlla sul database, tramite l'API dell'ufficio:
  - ogni slot occupato porta registrato un solo numero di prenotazione;
  - ogni prenotazione confermata corrisponde allo slot su cui è registrata.

    python app/scripts/simula.py --url http://localhost:8001 --cittadini 30
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


def cittadino(url: str, inizio: str, attivita: str, esiti: list, barriera: threading.Barrier) -> None:
    with httpx.Client(base_url=url, timeout=30, follow_redirects=False) as c:
        c.get("/auth/simulato?ritorno=/")
        r = c.get("/prenota", params={"inizio": inizio, "attivita": attivita})
        token = csrf(r.text)
        barriera.wait()  # tutti inviano insieme
        r = c.post("/prenota", data={"inizio": inizio, "attivita": attivita, "csrf_token": token})
        if r.status_code != 303:
            esiti.append(("rifiutata", inizio, None, r.status_code))
            return
        pagina = r.headers["location"]
        r = c.get(pagina)
        ritorno = parse_qs(urlparse(pagina).query)["ritorno"][0]
        c.post(urlparse(pagina).path, data={"ritorno": ritorno, "csrf_token": csrf(r.text)})
        r = c.get(urlparse(ritorno).path)  # ritorno da pagoPA: l'app verifica il pagamento
        codice = ritorno.rstrip("/").rsplit("/", 1)[-1]
        ok = r.status_code == 303 and r.headers["location"] == f"/prenotazione/{codice}"
        esiti.append(("confermata" if ok else "non_confermata", inizio, codice, r.status_code))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--cittadini", type=int, default=30)
    ap.add_argument("--utente", default="ufficio.sport")
    ap.add_argument("--password", default="cambiami")
    ap.add_argument("--seme", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seme)
    ufficio = (a.utente, a.password)

    info = httpx.get(f"{a.url}/api/v1/spazio").json()
    liberi = [s["inizio"] for g in httpx.get(f"{a.url}/api/v1/disponibilita?giorni=7").json()
              for s in g["slot"] if s["libero"]]
    if len(liberi) < 4:
        print("Troppi pochi slot liberi: riavviare l'istanza (docker compose restart demo)")
        return 1
    contesi = rnd.sample(liberi, 3)                       # orari su cui si scontrano in molti
    richieste = [(rnd.choice(contesi) if i % 2 == 0 else rnd.choice(liberi), rnd.choice(info["attivita"])["codice"])
                 for i in range(a.cittadini)]
    print(f"Luogo: {info['nome']} – {info['comune']}")
    print(f"{a.cittadini} cittadini, {len(liberi)} slot liberi, 3 slot contesi da metà dei cittadini\n")

    esiti, barriera = [], threading.Barrier(a.cittadini)
    fili = [threading.Thread(target=cittadino, args=(a.url, ini, att, esiti, barriera)) for ini, att in richieste]
    for f in fili:
        f.start()
    for f in fili:
        f.join()

    confermate = {e[2]: e[1] for e in esiti if e[0] == "confermata"}
    rifiutate = [e for e in esiti if e[0] == "rifiutata"]
    print(f"Prenotazioni confermate: {len(confermate)}   rifiutate (slot già preso): {len(rifiutate)}")

    # verifica sul database tramite l'API dell'ufficio
    occ = httpx.get(f"{a.url}/api/v1/ufficio/occupazione?giorni=7", auth=ufficio).json()
    sullo_slot = {s["inizio"]: s for g in occ for s in g["slot"]}
    errori = []
    for codice, inizio in confermate.items():
        if sullo_slot[inizio]["codice"] != codice:
            errori.append(f"{codice}: sullo slot {inizio} c'è {sullo_slot[inizio]['codice']}")
    doppie = [i for i, n in Counter(confermate.values()).items() if n > 1]
    errori += [f"slot {i} venduto più volte" for i in doppie]
    vincenti_contesi = Counter(confermate.values())
    print("\nSlot contesi: chi ha vinto")
    print(f"  {'slot':<26} {'richieste':>9}  numero di prenotazione registrato")
    for ini in contesi:
        n = sum(1 for r in richieste if r[0] == ini)
        print(f"  {ini:<26} {n:>9}  {sullo_slot[ini]['codice']}  ({vincenti_contesi[ini]} confermata)")

    print("\nTabella slot (estratto, dal database):")
    print(f"  {'inizio':<26} {'stato':<12} {'numero':<15} intestatario")
    for ini in sorted(set(confermate.values()))[:12]:
        s = sullo_slot[ini]
        print(f"  {ini:<26} {s['stato']:<12} {s['codice']:<15} {s['intestatario']}")

    if errori:
        print("\nERRORI:\n  " + "\n  ".join(errori))
        return 1
    print(f"\nOK: {len(confermate)} prenotazioni, ognuna registrata sul proprio slot; nessuno slot venduto due volte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
