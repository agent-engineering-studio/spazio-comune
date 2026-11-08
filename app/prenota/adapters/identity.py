"""Identità digitale (art. 64 CAD: accesso ai servizi online con SPID/CIE/CNS).

In produzione l'autenticazione va delegata a un gateway già certificato:
l'area personale del portale eCOMUNE (se espone OIDC/SAML verso terzi) oppure
un proxy SPID/CIE OpenID Connect (es. progetto italia/spid-cie-oidc-django).
L'app riceve solo gli attributi minimi: codice fiscale, nome, cognome, email.

`MockIdentity` simula il ritorno dall'Identity Provider per demo e test.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Cittadino:
    cf: str
    nome: str
    cognome: str
    email: str | None = None
    metodo: str = "SPID"

    def to_session(self) -> dict:
        return asdict(self)


class MockIdentity:
    UTENTE_DEMO = Cittadino(cf="RSSMRA80A01E038X", nome="Mario", cognome="Rossi",
                            email="mario.rossi@example.org", metodo="SPID (simulato)")

    def login_url(self, ritorno: str) -> str:
        return f"/auth/simulato?ritorno={ritorno}"

    def completa(self) -> Cittadino:
        return self.UTENTE_DEMO
