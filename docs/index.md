---
title: Spazio Comune
description: Prenotazione online degli impianti sportivi comunali con SPID/CIE, pagoPA, QR code e assistente IA.
---

<div class="hero" markdown>

# Spazio Comune

Prenotare il campo comunale in **4 passaggi su un solo portale**, pagando **dopo** aver scelto l'orario,
con un **assistente IA** che trova gli orari partendo da una frase.
Pilota proposto: campo coperto di via Benagiano, Comune di Gioia del Colle.

</div>

<video class="video-demo" controls muted playsinline preload="metadata" poster="screenshot/01_home.png">
  <source src="demo/spazio-comune-demo.mp4" type="video/mp4">
  Il tuo browser non riproduce video: <a href="demo/spazio-comune-demo.mp4">scarica il video</a>.
</video>

*Un minuto di demo con dati fittizi: assistente IA, SPID, pagoPA, QR, ufficio e custode.*

## Scegli da dove partire

<div class="grid cards" markdown>

-   :material-account-group: **Cittadini**

    ---

    Quali vantaggi hai e come si prenota in quattro passi: chiedi all'assistente, entri con SPID o CIE, paghi
    con pagoPA, mostri il QR.

    [:octicons-arrow-right-24: Prenotare in 4 passi](cittadini.md)

-   :material-bank: **Comune**

    ---

    Entrate stimate tra 14.000 e 28.000 € l'anno per il solo campo, incassi riconciliati in automatico,
    ufficio con meno controlli manuali, IA sotto controllo.

    [:octicons-arrow-right-24: Benefici per il Comune](comune.md)

-   :material-server-security: **Sviluppatori e ufficio IT**

    ---

    Installazione con Docker, configurazione, server IA, e checklist per la messa in esercizio secondo le
    norme ICT della PA.

    [:octicons-arrow-right-24: Installazione](installazione.md) ·
    [Installazione conforme PA](normativa-it.md)

</div>

## L'intelligenza artificiale, in breve

<div class="grid" markdown>

!!! tip "Per il cittadino"
    Scrivi *"calcetto venerdì sera alle 20"*: l'assistente propone gli orari liberi più vicini e risponde alle
    domande citando la fonte ufficiale. **Propone, non decide**: scegli e paghi tu.

!!! abstract "Per il Comune e l'IT"
    Motore predefinito **offline, senza GPU**, nessun dato a terzi. LLM locale o cloud opzionale, con
    redazione dei dati personali, trasparenza (AI Act art. 50) e degrado controllato.
    [Approfondisci](intelligenza-artificiale.md).

</div>

## Oggi e domani

| | Oggi | Con Spazio Comune |
|---|---|---|
| Passaggi | 7 su 2 portali | **4 su 1 portale** |
| Pagamento | prima di scegliere, compilato a mano | **dopo** aver scelto, già compilato |
| Ricerca orario | un giorno alla volta | settimana intera o **assistente IA** |
| Identità | dati riscritti a mano | **SPID / CIE** |
| Al campo | ricevuta stampata | **QR** sul telefono |
| Ufficio | controllo a vista dei PDF | conferma automatica con IUV, export, iCal |

!!! warning "Prototipo e proposta indipendente"
    Questo progetto è una **proposta** al Comune di Gioia del Colle, non un servizio ufficiale del Comune.
    SPID/CIE e pagoPA sono **simulati** e tutti i dati della demo sono fittizi.
