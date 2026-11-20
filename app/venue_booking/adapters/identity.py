"""Identità digitale (art. 64 CAD: accesso ai servizi online con SPID/CIE/CNS).

In produzione l'autenticazione va delegata a un gateway già certificato che
espone OpenID Connect verso l'applicazione: l'area personale del portale del
Comune, il proxy SPID/CIE dell'intermediario regionale, un Keycloak/SATOSA con
i plugin SPID e CIE, o il progetto italia/spid-cie-oidc-django.
L'app riceve solo gli attributi minimi: codice fiscale, nome, cognome, email.

`OIDCIdentity` implementa il flusso "authorization code" (OpenID Connect Core
1.0) con PKCE, state e nonce; client id, secret e indirizzo del gateway si
impostano dal back-office /amministrazione/identita.
`MockIdentity` simula il ritorno dall'Identity Provider per demo e test.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

import httpx

log = logging.getLogger("prenota.identita")


@dataclass
class Citizen:
    tax_code: str
    name: str
    last_name: str
    email: str | None = None
    method: str = "SPID"

    def to_session(self) -> dict:
        return asdict(self)


class IdentityError(Exception):
    """Accesso non riuscito: il messaggio si mostra al cittadino."""


def identity_config(settings) -> dict:
    """Configurazione dell'accesso SPID/CIE dal file .env (non modificabile dal back-office)."""
    s = settings
    return {"backend": s.identity_backend, "oidc_issuer": s.oidc_issuer.rstrip("/"), "oidc_client_id": s.oidc_client_id,
            "oidc_client_secret": s.oidc_client_secret or None,
            "redirect_uri": s.oidc_redirect_uri or f"{s.base_url.rstrip('/')}/auth/oidc/callback",
            "oidc_scope": s.oidc_scope, "oidc_acr_values": s.oidc_acr_values, "oidc_auth_metodo": s.oidc_auth_method,
            "claim_cf": s.oidc_claim_tax_code, "claim_nome": s.oidc_claim_name,
            "claim_cognome": s.oidc_claim_family_name, "claim_email": s.oidc_claim_email}


def check_identity_config(cfg: dict) -> None:
    """Errore chiaro all'avvio se IDENTITY_BACKEND=oidc ma le variabili OIDC_* non bastano."""
    backend = cfg.get("backend")
    if backend not in ("mock", "oidc"):
        raise ValueError(f"IDENTITY_BACKEND: usare mock oppure oidc, non {backend!r}")
    if backend != "oidc":
        return
    missing = [name for name, key in (("OIDC_ISSUER", "oidc_issuer"), ("OIDC_CLIENT_ID", "oidc_client_id"),
                                      ("OIDC_CLIENT_SECRET", "oidc_client_secret")) if not cfg.get(key)]
    if missing:
        raise ValueError(f"IDENTITY_BACKEND=oidc: impostare nel file .env {', '.join(missing)}")
    local = ("http://localhost", "http://127.0.0.1")
    for name, key in (("OIDC_ISSUER", "oidc_issuer"), ("OIDC_REDIRECT_URI", "redirect_uri")):
        if not (cfg[key].startswith("https://") or cfg[key].startswith(local)):
            raise ValueError(f"{name}: indirizzo https:// (http è ammesso solo per localhost), non {cfg[key]!r}")
    if "openid" not in cfg.get("oidc_scope", "").split():
        raise ValueError("OIDC_SCOPE: deve contenere openid")
    if cfg.get("oidc_auth_metodo") not in ("client_secret_basic", "client_secret_post"):
        raise ValueError("OIDC_AUTH_METHOD: client_secret_basic oppure client_secret_post")
    if not cfg.get("claim_cf"):
        raise ValueError("OIDC_CLAIM_TAX_CODE: indicare l'attributo con il codice fiscale")


class MockIdentity:
    DEMO_USER = Citizen(tax_code="RSSMRA80A01E038X", name="Mario", last_name="Rossi",
                            email="mario.rossi@example.org", method="SPID (simulato)")

    def login_url(self, return_url: str) -> str:
        return f"/auth/simulato?ritorno={return_url}"

    def complete(self) -> Citizen:
        return self.DEMO_USER


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt_payload(token: str) -> dict:
    """Payload di un JWT, senza verifica della firma.

    Ammesso solo per l'ID token ricevuto direttamente dal token endpoint su TLS
    (OpenID Connect Core 1.0, par. 3.1.3.7, punto 6): il server è autenticato dal
    certificato TLS e dal client secret; issuer, audience, scadenza e nonce si verificano qui.
    """
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        raise IdentityError("Risposta del gestore dell'identità non valida") from None


def normalize_tax_code(value: str) -> str:
    """"TINIT-RSSMRA80A01E038X" (formato SPID) -> "RSSMRA80A01E038X"."""
    tax_code = value.strip().upper()
    return tax_code.split("-", 1)[1] if tax_code.startswith("TINIT-") else tax_code


class OIDCIdentity:
    """Relying Party OpenID Connect verso il gateway SPID/CIE dell'ente."""

    DISCOVERY_TTL = 3600

    def __init__(self, cfg: dict, redirect_uri: str, client: httpx.Client | None = None):
        self.cfg, self.redirect_uri = cfg, redirect_uri
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)
        self._discovery: tuple[float, dict] | None = None

    @property
    def issuer(self) -> str:
        return (self.cfg.get("oidc_issuer") or "").rstrip("/")

    def discovery(self, force: bool = False) -> dict:
        if not force and self._discovery and time.monotonic() - self._discovery[0] < self.DISCOVERY_TTL:
            return self._discovery[1]
        url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            r = self._client.get(url)
            r.raise_for_status()
            meta = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("discovery OIDC non riuscita su %s: %s", url, e)
            raise IdentityError("Il servizio di accesso SPID/CIE non è raggiungibile: riprova tra qualche minuto") from None
        for key in ("issuer", "authorization_endpoint", "token_endpoint"):
            if not meta.get(key):
                raise IdentityError(f"Configurazione OIDC del gateway incompleta: manca {key}")
        self._discovery = (time.monotonic(), meta)
        return meta

    def start(self, session_info: dict, return_url: str) -> str:
        """URL dell'autorizzazione; state, nonce e PKCE restano nella sessione del browser."""
        meta = self.discovery()
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        session_info["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "ritorno": return_url,
                            "creato": int(time.time())}
        params_ = {
            "response_type": "code", "client_id": self.cfg["oidc_client_id"], "redirect_uri": self.redirect_uri,
            "scope": self.cfg.get("oidc_scope") or "openid", "state": state, "nonce": nonce,
            "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
        }
        if self.cfg.get("oidc_acr_values"):
            params_["acr_values"] = self.cfg["oidc_acr_values"]
        return f"{meta['authorization_endpoint']}?{urlencode(params_)}"

    def complete(self, session_info: dict, code: str | None, state: str | None, error: str | None = None) -> tuple[Citizen, str]:
        pending = session_info.pop("oidc", None)
        if error:
            raise IdentityError("Accesso annullato o non autorizzato dal gestore dell'identità")
        if not pending or not state or not secrets.compare_digest(state, pending["state"]):
            raise IdentityError("Sessione di accesso scaduta o non valida: riprova")
        if time.time() - pending.get("creato", 0) > 900:
            raise IdentityError("Sessione di accesso scaduta: riprova")
        if not code:
            raise IdentityError("Risposta del gestore dell'identità incompleta")
        meta = self.discovery()
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                "code_verifier": pending["verifier"]}
        auth = None
        if self.cfg.get("oidc_auth_metodo") == "client_secret_post":
            data.update(client_id=self.cfg["oidc_client_id"], client_secret=self.cfg.get("oidc_client_secret") or "")
        else:
            auth = (self.cfg["oidc_client_id"], self.cfg.get("oidc_client_secret") or "")
        try:
            r = self._client.post(meta["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"})
            r.raise_for_status()
            token = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("token endpoint OIDC: %s", e)
            raise IdentityError("Accesso non riuscito: il gestore dell'identità non ha confermato l'autenticazione") from None

        claims: dict = {}
        if token.get("id_token"):
            claims = _jwt_payload(token["id_token"])
            aud = claims.get("aud")
            aud = aud if isinstance(aud, list) else [aud]
            if claims.get("iss") != meta["issuer"] or self.cfg["oidc_client_id"] not in aud:
                raise IdentityError("Token di identità non destinato a questo servizio")
            if claims.get("nonce") != pending["nonce"]:
                raise IdentityError("Token di identità non valido (nonce)")
            if int(claims.get("exp", 0)) < time.time() - 60:
                raise IdentityError("Token di identità scaduto: riprova")
        if meta.get("userinfo_endpoint") and token.get("access_token"):
            try:
                r = self._client.get(meta["userinfo_endpoint"],
                                     headers={"Authorization": f"Bearer {token['access_token']}", "Accept": "application/json"})
                r.raise_for_status()
                info = r.json() if "json" in r.headers.get("content-type", "") else _jwt_payload(r.text)
                if claims.get("sub") and info.get("sub") not in (None, claims["sub"]):
                    raise IdentityError("Attributi dell'utente non coerenti con il token di identità")
                claims = {**claims, **info}
            except (httpx.HTTPError, ValueError) as e:
                log.warning("userinfo OIDC: %s", e)
                if not claims:
                    raise IdentityError("Attributi dell'utente non disponibili") from None
        return self._citizen(claims), pending.get("ritorno") or "/"

    def _citizen(self, claims: dict) -> Citizen:
        def claim(key: str) -> str:
            name = self.cfg.get(key) or ""
            return str(claims.get(name) or "").strip()

        tax_code = normalize_tax_code(claim("claim_cf"))
        if not tax_code:
            raise IdentityError("Il gestore dell'identità non ha fornito il codice fiscale: "
                                 "verificare gli attributi richiesti (scope/claim) nel back-office")
        acr = str(claims.get("acr") or "").lower()
        method = "CIE" if "cie" in acr else "SPID" if "spid" in acr else "SPID/CIE"
        return Citizen(tax_code=tax_code, name=claim("claim_nome"), last_name=claim("claim_cognome"),
                         email=claim("claim_email") or None, method=method)
