from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from .catalog import Spazio


def _env(nome: str, default: str | None = None) -> str | None:
    v = os.getenv(nome)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    base_url: str = field(default_factory=lambda: _env("BASE_URL", "http://localhost:8000"))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "/data/prenota.db"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY") or secrets.token_hex(32))
    inference_url: str | None = field(default_factory=lambda: _env("INFERENCE_URL"))
    payment_backend: str = field(default_factory=lambda: _env("PAYMENT_BACKEND", "mock"))
    identity_backend: str = field(default_factory=lambda: _env("IDENTITY_BACKEND", "mock"))
    ufficio_user: str = field(default_factory=lambda: _env("UFFICIO_USER", "ufficio.sport"))
    ufficio_password: str = field(default_factory=lambda: _env("UFFICIO_PASSWORD", "cambiami"))
    custode_password: str = field(default_factory=lambda: _env("CUSTODE_PASSWORD", "custode"))
    feed_token: str = field(default_factory=lambda: _env("FEED_TOKEN") or secrets.token_urlsafe(16))
    ttl_attesa_min: int = field(default_factory=lambda: int(_env("TTL_ATTESA_MIN", "15")))
    spazio: Spazio = field(default_factory=Spazio.da_env)
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "false") == "true")
