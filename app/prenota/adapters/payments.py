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
completare con le credenziali e il WSDL forniti da Regione Puglia.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Dovuto:
    codice_prenotazione: str
    importo_cent: int
    causale: str
    cf_debitore: str
    nome_debitore: str
    email: str | None
    tipo_dovuto: str = "IMPIANTI_SPORTIVI"   # codice tipo dovuto configurato su MyPay


@dataclass
class EsitoCreazione:
    iuv: str
    url_pagamento: str


class PaymentGateway(Protocol):
    def crea_dovuto(self, dovuto: Dovuto, url_ritorno: str) -> EsitoCreazione: ...
    def verifica_pagato(self, iuv: str) -> bool: ...


class MockPagoPA:
    """Simula MyPay/pagoPA. Il pagamento si conclude chiamando `segna_pagato`."""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")
        self._pagati: set[str] = set()

    def crea_dovuto(self, dovuto: Dovuto, url_ritorno: str) -> EsitoCreazione:
        iuv = "RF" + secrets.token_hex(8).upper()
        url = f"{self.base_url}/pagopa-simulato/{iuv}?ritorno={url_ritorno}"
        return EsitoCreazione(iuv=iuv, url_pagamento=url)

    def segna_pagato(self, iuv: str) -> None:
        self._pagati.add(iuv)

    def verifica_pagato(self, iuv: str) -> bool:
        return iuv in self._pagati


class MyPaySILGateway:  # pragma: no cover - richiede ambiente Regione Puglia
    """Integrazione SOAP con MyPay4 (servizi SIL per enti).

    Da completare con: endpoint, codice IPA ente, password SIL, tipo dovuto.
    Operazioni MyPay4 di riferimento (repo RegioneDelVeneto/mypay):
      - paaSILInviaDovuti  -> restituisce idSession + url di redirect al checkout
      - paaSILChiediPagati -> restituisce l'esito/ricevuta (RT) del pagamento
    """

    def __init__(self, endpoint: str, ipa_ente: str, password: str, tipo_dovuto: str):
        self.endpoint, self.ipa_ente = endpoint, ipa_ente
        self._password, self.tipo_dovuto = password, tipo_dovuto

    def crea_dovuto(self, dovuto: Dovuto, url_ritorno: str) -> EsitoCreazione:
        raise NotImplementedError("Configurare l'accesso SIL MyPay con Regione Puglia")

    def verifica_pagato(self, iuv: str) -> bool:
        raise NotImplementedError("Configurare l'accesso SIL MyPay con Regione Puglia")
