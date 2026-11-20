"""Impostazioni modificabili dal back-office /amministrazione.

Il file .env dà i valori iniziali e i parametri dell'infrastruttura (database,
SECRET_KEY, BASE_URL); tutto ciò che decide il Comune si cambia dal back-office
e vale subito, senza riavvio:

  luogo       nome, indirizzo, Comune, ufficio, prefisso dei numeri
  attivita    attività prenotabili, tariffe e atto che le approva
  orari       fasce orarie per giorno, periodi dell'anno, festivi, chiusure
  pagamenti   intermediario pagoPA e sue credenziali, minuti per pagare
  identita    accesso dei cittadini con SPID/CIE tramite OpenID Connect
  accessi     password di amministratore, ufficio e custode, token del calendario

Una sezione mai salvata dal back-office segue il .env. Ogni salvataggio è
registrato (chi, quando, quali campi: mai i valori dei segreti).

I segreti (password SIL, client secret OIDC, token del calendario) sono cifrati
nel database con una chiave derivata da SECRET_KEY: chi legge un backup del
database non li vede in chiaro. Le password del personale sono salvate solo
come hash scrypt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from datetime import datetime
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .adapters.identity import identity_config
from .catalog import Venue
from .db import Database

log = logging.getLogger("venue_booking.settings")

SECTIONS = ("luogo", "attivita", "orari", "pagamenti", "identita", "accessi")
VENUE_SECTIONS = ("luogo", "attivita", "orari")
# campi cifrati nel database
SECRETS = {"pagamenti": {"mypay_password"}, "identita": {"oidc_client_secret"}, "accessi": {"feed_token"}}
# campi che non si mostrano e non si registrano in chiaro (hash delle password)
PRIVATE_FIELDS = {"accessi": {"admin_hash", "ufficio_hash", "custode_hash"}}

PAYMENT_BACKENDS = {"mock": "Simulazione (solo demo e test)",
                     "mypay": "MyPay SIL – Regione Puglia (intermediario pagoPA)"}
IDENTITY_BACKENDS = {"mock": "Simulazione (utente di prova, solo demo e test)",
                    "oidc": "SPID/CIE tramite gateway OpenID Connect"}


# ------------------------------------------------------------ segreti e password
class SecretBox:
    """Cifratura autenticata (Fernet: AES-128-CBC + HMAC-SHA256) con chiave derivata da SECRET_KEY."""

    PREFIX = "enc:v1:"

    def __init__(self, secret: str):
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"spazio-comune",
                      info=b"impostazioni-back-office-v1").derive(secret.encode())
        self._f = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, text: str) -> str:
        return self.PREFIX + self._f.encrypt(text.encode()).decode()

    def decrypt(self, value: str) -> str | None:
        """None se il valore non è decifrabile (SECRET_KEY cambiata): il segreto va reinserito."""
        if not value.startswith(self.PREFIX):
            return None
        try:
            return self._f.decrypt(value[len(self.PREFIX):].encode()).decode()
        except InvalidToken:
            return None


_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${h.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, h = encoded.split("$")
        if algorithm != "scrypt":
            return False
        computed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32,
                                   n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed.hex(), h)


# ------------------------------------------------------------ archivio
class SettingsArchive:
    """Sezioni salvate in PostgreSQL (tabella impostazioni) e registro delle modifiche."""

    def __init__(self, db: Database, secret_box: SecretBox):
        self.db, self._c = db, secret_box
        self.unreadable: set[tuple[str, str]] = set()

    def _open(self, section: str, values_: dict) -> dict:
        out = dict(values_)
        for field_name in SECRETS.get(section, ()):
            if out.get(field_name):
                plain = self._c.decrypt(out[field_name])
                if plain is None:
                    log.warning("impostazioni: %s.%s non decifrabile (SECRET_KEY cambiata?), va reinserito",
                                section, field_name)
                    self.unreadable.add((section, field_name))
                out[field_name] = plain
        return out

    def load_all(self) -> dict[str, dict]:
        self.unreadable = set()
        rows = self.db.query("SELECT sezione, valori FROM impostazioni")
        return {r["sezione"]: self._open(r["sezione"], r["valori"]) for r in rows}

    def version(self) -> int:
        return self.db.query("SELECT coalesce(max(id), 0) AS v FROM impostazioni_registro")[0]["v"]

    def save(self, section: str, values_: dict, user: str, now: datetime) -> list[str]:
        """Sostituisce la sezione; restituisce i campi cambiati (vuoto = nessuna modifica, niente registro)."""
        if section not in SECTIONS:
            raise ValueError(f"Sezione sconosciuta: {section}")
        current = self.load_all().get(section)
        if current is not None and current == values_:
            return []
        changed = sorted(k for k in set(values_) | set(current or {}) if (current or {}).get(k) != values_.get(k)) \
            if current is not None else ["(prima configurazione)"]
        to_store = dict(values_)
        for field_name in SECRETS.get(section, ()):
            if to_store.get(field_name):
                to_store[field_name] = self._c.encrypt(to_store[field_name])
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO impostazioni (sezione, valori, aggiornata_il, aggiornata_da) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (sezione) DO UPDATE SET valori=excluded.valori, aggiornata_il=excluded.aggiornata_il, "
                "aggiornata_da=excluded.aggiornata_da",
                (section, json.dumps(to_store), now.isoformat(), user))
            conn.execute("INSERT INTO impostazioni_registro (quando, utente, sezione, campi) VALUES (%s, %s, %s, %s)",
                         (now.isoformat(), user, section, changed))
        return changed

    # logo dell'ente (header del sito) ------------------------------------
    def logo(self) -> dict | None:
        r = self.db.query("SELECT tipo, dati, aggiornato_il FROM logo WHERE id=1")
        return r[0] if r else None

    def logo_version(self) -> str | None:
        r = self.db.query("SELECT aggiornato_il FROM logo WHERE id=1")
        return r[0]["aggiornato_il"] if r else None

    def save_logo(self, kind: str | None, data: bytes | None, user: str, now: datetime) -> None:
        """tipo/dati None = elimina il logo."""
        with self.db.tx() as conn:
            if data is None:
                conn.execute("DELETE FROM logo WHERE id=1")
            else:
                conn.execute("INSERT INTO logo (id, tipo, dati, aggiornato_il) VALUES (1, %s, %s, %s) "
                             "ON CONFLICT (id) DO UPDATE SET tipo=excluded.tipo, dati=excluded.dati, "
                             "aggiornato_il=excluded.aggiornato_il", (kind, data, now.isoformat()))
            conn.execute("INSERT INTO impostazioni_registro (quando, utente, sezione, campi) VALUES (%s,%s,%s,%s)",
                         (now.isoformat(), user, "logo", ["(nuovo logo)" if data else "(logo eliminato)"]))

    def restore(self, section: str, user: str, now: datetime) -> bool:
        """Elimina la sezione salvata: torna a valere il .env."""
        with self.db.tx() as conn:
            cur = conn.execute("DELETE FROM impostazioni WHERE sezione=%s", (section,))
            if cur.rowcount:
                conn.execute("INSERT INTO impostazioni_registro (quando, utente, sezione, campi) VALUES (%s,%s,%s,%s)",
                             (now.isoformat(), user, section, ["(ripristino dal .env)"]))
        return bool(cur.rowcount)

    def saved(self) -> dict[str, dict]:
        """Per ogni sezione salvata: quando e da chi."""
        return {r["sezione"]: r for r in self.db.query(
            "SELECT sezione, aggiornata_il, aggiornata_da FROM impostazioni")}

    def audit_log(self, limit: int = 200) -> list[dict]:
        return self.db.query("SELECT quando, utente, sezione, campi FROM impostazioni_registro "
                             "ORDER BY id DESC LIMIT %s", (limit,))


# ------------------------------------------------------------ configurazione in esercizio
class RuntimeConfig:
    """Valori in uso: .env + sezioni salvate. Si ricarica quando un'altra istanza salva."""

    CHECK_INTERVAL = 3.0   # secondi tra due controlli della versione nel database

    def __init__(self, settings, db: Database, env_venue: Venue):
        self.settings, self.env_venue = settings, env_venue
        self.archive = SettingsArchive(db, SecretBox(settings.secret_key))
        self._listeners: list[Callable[["RuntimeConfig"], None]] = []
        self._lock = threading.Lock()
        self._version = -1
        self._last_check = 0.0
        self.errors: list[str] = []
        self.reload()

    # valori predefiniti dal .env --------------------------------------------
    def _payments_env(self) -> dict:
        s = self.settings
        return {"backend": s.payment_backend, "ttl_attesa_min": s.pending_ttl_min,
                "mypay_endpoint": "", "mypay_ipa_ente": "", "mypay_tipo_dovuto": "IMPIANTI_SPORTIVI",
                "mypay_password": None}


    def _access_env(self) -> dict:
        s = self.settings
        return {"admin_user": s.admin_user, "ufficio_user": s.office_user, "feed_token": s.feed_token,
                "admin_hash": None, "ufficio_hash": None, "custode_hash": None}

    # ------------------------------------------------------------------------
    def reload(self) -> None:
        with self._lock:
            version = self.archive.version()
            saved = self.archive.load_all()
            self.errors = []
            data = self.env_venue.to_data()
            data.update({k: v for k, v in saved.items() if k in VENUE_SECTIONS})
            try:
                self.venue = Venue.from_data(data)
            except ValueError as e:   # non dovrebbe accadere: i dati sono validati al salvataggio
                log.error("impostazioni del luogo non valide, uso il .env: %s", e)
                self.errors.append(f"Impostazioni del luogo non valide ({e}): in uso i valori del .env")
                self.venue = self.env_venue
            self.payments = {**self._payments_env(), **saved.get("pagamenti", {})}
            self.identity = identity_config(self.settings)   # SPID/CIE: solo dal file .env
            access = {**self._access_env(), **saved.get("accessi", {})}
            if not access.get("feed_token"):
                access["feed_token"] = self.settings.feed_token
            self.access = access
            self.saved = set(saved)
            v = self.archive.logo_version()
            self.logo_url = f"/logo?v={re.sub(r'[^0-9]', '', v)}" if v else None
            self._version = version
        for f in self._listeners:
            f(self)

    def on_change(self, function: Callable[["RuntimeConfig"], None]) -> None:
        self._listeners.append(function)
        function(self)

    def refresh_if_needed(self) -> None:
        """Ricarica se un altro processo (altro worker, altra VM) ha salvato; al massimo ogni 3 secondi."""
        now = time.monotonic()
        if now - self._last_check < self.CHECK_INTERVAL:
            return
        self._last_check = now
        try:
            if self.archive.version() != self._version:
                self.reload()
        except Exception:   # database momentaneamente irraggiungibile: si continua con i valori in memoria
            log.exception("controllo delle impostazioni non riuscito")

    def save(self, section: str, values_: dict, user: str, now: datetime) -> list[str]:
        changed = self.archive.save(section, values_, user, now)
        self.reload()
        return changed

    # logo dell'ente (header del sito) ------------------------------------
    def save_logo(self, kind: str | None, data: bytes | None, user: str, now: datetime) -> None:
        self.archive.save_logo(kind, data, user, now)
        self.reload()

    def restore(self, section: str, user: str, now: datetime) -> bool:
        done = self.archive.restore(section, user, now)
        self.reload()
        return done

    # accessi del personale --------------------------------------------------
    def verify(self, role: str, user: str, password: str) -> bool:
        """ruolo: admin | ufficio | custode. La password salvata dal back-office prevale su quella del .env."""
        a, s = self.access, self.settings
        expected_user = {"admin": a["admin_user"], "ufficio": a["ufficio_user"], "custode": "custode"}[role]
        user_ok = secrets.compare_digest(user.encode(), expected_user.encode())
        encoded = a.get(f"{role}_hash")
        if encoded:
            password_ok = verify_password(password, encoded)
        else:
            plain = {"admin": s.admin_password, "ufficio": s.office_password, "custode": s.keeper_password}[role]
            password_ok = bool(plain) and secrets.compare_digest(password.encode(), plain.encode())
        return user_ok and password_ok

    @property
    def admin_enabled(self) -> bool:
        return bool(self.access.get("admin_hash") or self.settings.admin_password)
