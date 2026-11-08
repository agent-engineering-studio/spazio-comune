"""Scarica Bootstrap Italia dal registry npm, verifica l'integrità (SRI sha512) ed
estrae `dist/` in prenota/static/bootstrap-italia/dist.

Gli asset vengono ospitati in locale: nessuna CDN di terzi (GDPR, disponibilità).
Uso: python scripts/fetch_bootstrap_italia.py [versione]
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSIONE = sys.argv[1] if len(sys.argv) > 1 else "2.18.3"
DEST = Path(__file__).resolve().parents[1] / "prenota" / "static" / "bootstrap-italia"


def main() -> None:
    meta = json.load(urllib.request.urlopen(f"https://registry.npmjs.org/bootstrap-italia/{VERSIONE}", timeout=60))
    tgz = urllib.request.urlopen(meta["dist"]["tarball"], timeout=120).read()
    algo, atteso = meta["dist"]["integrity"].split("-", 1)
    calcolato = base64.b64encode(hashlib.new(algo, tgz).digest()).decode()
    if calcolato != atteso:
        sys.exit(f"Integrità NON verificata per bootstrap-italia@{VERSIONE}")
    DEST.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tgz)) as tar:
        membri = [m for m in tar.getmembers()
                  if m.name.startswith("package/dist/") and (m.isfile() or m.isdir()) and ".." not in m.name]
        for m in membri:
            m.name = m.name[len("package/"):]
        tar.extractall(DEST, members=membri, filter="data")
    (DEST / "VERSION").write_text(VERSIONE + "\n")
    print(f"bootstrap-italia@{VERSIONE} verificato ({algo}) ed estratto in {DEST}")


if __name__ == "__main__":
    main()
