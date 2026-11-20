"""Adapter pagoPA.

Il Comune paga già tramite MyPay di Regione Puglia (intermediario tecnologico
pagoPA, ente C_E038). Oggi il cittadino deve: aprire MyPay, compilare a mano
il "pagamento spontaneo", scaricare la ricevuta PDF e caricarla nel modulo
eAgenda. L'ufficio poi controlla a vista ogni PDF.

Con l'integrazione SIL (Sistema Informativo Locale) prevista da MyPay4
(`PagamentiTelematiciDovutiPagati`: paaSILInviaDovuti / paaSILChiediPagati)
il sistema crea il *dovuto* con importo e causale corretti, ottiene l'URL di
pagamento e riceve l'esito: niente PDF, niente verifica manuale.

`MockPagoPA` serve per demo e test; `MyPaySILGateway` è lo scheletro da
completare con il WSDL fornito da Regione Puglia. Endpoint, codice IPA,
password SIL e tipo dovuto si impostano dal back-office /amministrazione/pagamenti
(la password è cifrata nel database).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentDue:
    booking_code: str
    amount_cents: int
    reason: str
    payer_tax_code: str
    payer_name: str
    email: str | None
    due_type: str = "IMPIANTI_SPORTIVI"   # codice tipo dovuto configurato su MyPay


@dataclass
class PaymentCreated:
    iuv: str
    payment_url: str


class PaymentGateway(Protocol):
    def create_payment_due(self, due: PaymentDue, return_url: str) -> PaymentCreated: ...
    def is_paid(self, iuv: str) -> bool: ...


class MockPagoPA:
    """Simula MyPay/pagoPA. Il pagamento si conclude chiamando `segna_pagato`."""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")
        self._paid: set[str] = set()

    def create_payment_due(self, due: PaymentDue, return_url: str) -> PaymentCreated:
        iuv = "RF" + secrets.token_hex(8).upper()
        url = f"{self.base_url}/pagopa-mock/{iuv}?return_url={return_url}"
        return PaymentCreated(iuv=iuv, payment_url=url)

    def mark_paid(self, iuv: str) -> None:
        self._paid.add(iuv)

    def is_paid(self, iuv: str) -> bool:
        return iuv in self._paid


class MyPaySILGateway:  # pragma: no cover - richiede ambiente Regione Puglia
    """Integrazione SOAP con MyPay4 (servizi SIL per enti).

    Da completare con: endpoint, codice IPA ente, password SIL, tipo dovuto.
    Operazioni MyPay4 di riferimento (repo RegioneDelVeneto/mypay):
      - paaSILInviaDovuti  -> restituisce idSession + url di redirect al checkout
      - paaSILChiediPagati -> restituisce l'esito/ricevuta (RT) del pagamento
    """

    def __init__(self, endpoint: str, ipa_code: str, password: str, due_type: str):
        self.endpoint, self.ipa_code = endpoint, ipa_code
        self._password, self.due_type = password, due_type

    def create_payment_due(self, due: PaymentDue, return_url: str) -> PaymentCreated:
        raise NotImplementedError("Configurare l'accesso SIL MyPay con Regione Puglia")

    def is_paid(self, iuv: str) -> bool:
        raise NotImplementedError("Configurare l'accesso SIL MyPay con Regione Puglia")


def create_gateway(cfg: dict, base_url: str) -> PaymentGateway:
    """Il gateway scelto nel back-office (o PAYMENT_BACKEND nel .env)."""
    if cfg.get("backend") == "mypay":
        return MyPaySILGateway(cfg.get("mypay_endpoint") or "", cfg.get("mypay_ipa_ente") or "",
                               cfg.get("mypay_password") or "", cfg.get("mypay_tipo_dovuto") or "IMPIANTI_SPORTIVI")
    if cfg.get("backend", "mock") == "mock":
        return MockPagoPA(base_url)
    raise ValueError(f"Intermediario pagoPA non supportato: {cfg.get('backend')}")
