"""La scheda publiccode.yml deve restare valida per il Catalogo di Developers Italia."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Sottoinsieme dei valori ammessi dallo standard publiccode.yml (campo categories)
ALLOWED_CATEGORIES = {
    "online-booking", "appointment-scheduling", "digital-citizenship", "payment-gateway",
    "facility-management", "resource-management", "event-management", "other",
}


def test_publiccode_yml_valid():
    pc = yaml.safe_load((ROOT / "publiccode.yml").read_text())
    for key in ("publiccodeYmlVersion", "name", "url", "platforms", "developmentStatus",
                   "softwareType", "description", "legal", "maintenance", "localisation"):
        assert key in pc, key
    assert set(pc["categories"]) <= ALLOWED_CATEGORIES
    it = pc["description"]["it"]
    assert it["shortDescription"] and it["longDescription"] and it["features"]
    assert len(it["shortDescription"]) <= 150
    assert pc["legal"]["license"] == "EUPL-1.2"
    assert pc["maintenance"]["type"] in ("internal", "contract", "community", "none")
    if pc["maintenance"]["type"] in ("internal", "community"):
        assert pc["maintenance"]["contacts"]
    assert "it" not in pc, "la sezione nazionale va scritta IT (maiuscolo)"
    # software open source di terze parti: codiceIPA vuoto (guida Developers Italia, passo 8)
    assert pc["IT"]["riuso"]["codiceIPA"] == ""
    for s in it.get("screenshots", []):
        assert (ROOT / s).exists(), s
