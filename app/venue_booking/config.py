from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

# .env: valori iniziali. Luogo, attività e tariffe, orari, pagamenti e password si cambiano poi
# dal back-office /admin (settings_store.py); qui restano database, segreti, indirizzi
# e il gateway SPID/CIE (OIDC_*), che si configura solo qui.

from .catalog import Venue


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    base_url: str = field(default_factory=lambda: _env("BASE_URL", "http://localhost:8000"))
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql://spazio:spazio@localhost:5432/spazio_comune"))
    database_schema: str = field(default_factory=lambda: _env("DATABASE_SCHEMA", "public"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY") or secrets.token_hex(32))
    inference_url: str | None = field(default_factory=lambda: _env("INFERENCE_URL"))
    payment_backend: str = field(default_factory=lambda: _env("PAYMENT_BACKEND", "mock"))
    identity_backend: str = field(default_factory=lambda: _env("IDENTITY_BACKEND", "mock"))
    office_user: str = field(default_factory=lambda: _env("UFFICIO_USER", "ufficio.sport"))
    office_password: str = field(default_factory=lambda: _env("UFFICIO_PASSWORD", "cambiami"))
    keeper_password: str = field(default_factory=lambda: _env("CUSTODE_PASSWORD", "custode"))
    # amministratore del back-office /admin (impostazioni, credenziali SPID e pagoPA);
    # senza ADMIN_PASSWORD il back-office delle impostazioni resta chiuso
    admin_user: str = field(default_factory=lambda: _env("ADMIN_USER", "amministratore"))
    admin_password: str | None = field(default_factory=lambda: _env("ADMIN_PASSWORD"))
    feed_token: str = field(default_factory=lambda: _env("FEED_TOKEN") or secrets.token_urlsafe(16))
    pending_ttl_min: int = field(default_factory=lambda: int(_env("TTL_ATTESA_MIN", "15")))
    venue: Venue = field(default_factory=Venue.from_env)
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "false") == "true")
    # gateway SPID/CIE OpenID Connect (IDENTITY_BACKEND=oidc)
    oidc_issuer: str = field(default_factory=lambda: _env("OIDC_ISSUER", ""))
    oidc_client_id: str = field(default_factory=lambda: _env("OIDC_CLIENT_ID", ""))
    oidc_client_secret: str = field(default_factory=lambda: _env("OIDC_CLIENT_SECRET", ""))
    oidc_redirect_uri: str = field(default_factory=lambda: _env("OIDC_REDIRECT_URI", ""))   # vuoto = BASE_URL/auth/oidc/callback
    oidc_scope: str = field(default_factory=lambda: _env("OIDC_SCOPE", "openid profile email"))
    oidc_acr_values: str = field(default_factory=lambda: _env("OIDC_ACR_VALUES", ""))
    oidc_auth_method: str = field(default_factory=lambda: _env("OIDC_AUTH_METHOD", "client_secret_basic"))
    oidc_claim_tax_code: str = field(default_factory=lambda: _env(
        "OIDC_CLAIM_TAX_CODE", "https://attributes.eid.gov.it/fiscal_number"))
    oidc_claim_name: str = field(default_factory=lambda: _env("OIDC_CLAIM_NAME", "given_name"))
    oidc_claim_family_name: str = field(default_factory=lambda: _env("OIDC_CLAIM_FAMILY_NAME", "family_name"))
    oidc_claim_email: str = field(default_factory=lambda: _env("OIDC_CLAIM_EMAIL", "email"))
