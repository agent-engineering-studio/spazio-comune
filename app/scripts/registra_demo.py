"""Registra il video dimostrativo sul server demo già avviato.

    docker compose --profile demo up -d                # dati fittizi su :8001
    python app/scripts/registra_demo.py                # 16:9 -> docs/demo/spazio-comune-demo.{mp4,gif}
    python app/scripts/registra_demo.py --verticale    # 9:16 -> docs/demo/spazio-comune-demo-verticale.mp4
    python app/scripts/registra_demo.py --screenshot   # docs/screenshot/*.png

Ogni registrazione consuma uno slot e un ingresso: riavviare il demo prima della successiva
(docker compose restart demo).

Richiede playwright (chromium) e ffmpeg.
"""
from __future__ import annotations

import os
import shutil
import re
import subprocess
import sys
import urllib.request
from base64 import b64encode
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.getenv("BASE_URL", "http://localhost:8001")
RADICE = Path(__file__).resolve().parents[2]
USCITA = RADICE / "docs" / "demo"
GREZZI = USCITA / "grezzi"
DESKTOP = {"width": 1280, "height": 720}
TELEFONO = {"width": 390, "height": 720}
VERTICALE = {"width": 405, "height": 720}   # 9:16, portato a 1080x1920 da ffmpeg

STILE = """
#demo-cap{position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:99999;
  background:rgba(0,38,77,.92);color:#fff;font:600 22px/1.3 'Titillium Web',sans-serif;
  padding:14px 26px;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);max-width:88vw;text-align:center;
  animation:demoIn .35s ease-out}
#demo-cap small{display:block;font-weight:400;font-size:16px;opacity:.85;margin-top:2px}
@keyframes demoIn{from{opacity:0;transform:translate(-50%,-12px)}to{opacity:1;transform:translate(-50%,0)}}
.demo-focus{outline:4px solid #ffb400 !important;outline-offset:3px;transition:outline .2s}
"""

CARTELLO = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="{base}/static/bootstrap-italia/dist/css/bootstrap-italia.min.css" rel="stylesheet"></head>
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:linear-gradient(135deg,#0066cc,#00264d);color:#fff;font-family:'Titillium Web',sans-serif;text-align:center">
<div style="max-width:{w}px;padding:24px">{html}</div></body></html>"""


def didascalia(page: Page, titolo: str, sotto: str = "") -> None:
    page.evaluate("""([t, s, css]) => {
        if (!document.getElementById('demo-style')) {
          const st = document.createElement('style'); st.id = 'demo-style'; st.textContent = css;
          document.head.appendChild(st);
        }
        document.getElementById('demo-cap')?.remove();
        const d = document.createElement('div'); d.id = 'demo-cap';
        d.innerHTML = t + (s ? '<small>' + s + '</small>' : '');
        document.body.appendChild(d);
    }""", [titolo, sotto, STILE])


def evidenzia(page: Page, selettore: str, pausa: int = 700):
    el = page.locator(selettore).first
    el.scroll_into_view_if_needed()
    el.evaluate("e => e.classList.add('demo-focus')")
    page.wait_for_timeout(pausa)
    return el


def scorri(page: Page, y: int, passi: int = 20) -> None:
    for _ in range(passi):
        page.mouse.wheel(0, y / passi)
        page.wait_for_timeout(35)


def cartello(page: Page, html: str, durata: int, w: int = 1000) -> None:
    page.set_content(CARTELLO.format(base=BASE, html=html, w=w))
    page.wait_for_timeout(durata)


def codice_stasera() -> str:
    """Primo ingresso di stasera, letto dal back-office (funziona anche contro il container demo)."""
    req = urllib.request.Request(BASE + "/ufficio", headers={
        "Authorization": "Basic " + b64encode(b"ufficio.sport:cambiami").decode()})
    html = urllib.request.urlopen(req).read().decode()
    return re.search(r"GDC-[A-Z0-9]{4}-[A-Z0-9]{4}", html).group(0)


def scena_cittadino(browser) -> Path:
    ctx = browser.new_context(viewport=DESKTOP, record_video_dir=GREZZI / "1", record_video_size=DESKTOP,
                              http_credentials={"username": "ufficio.sport", "password": "cambiami"},
                              locale="it-IT")
    page = ctx.new_page()

    cartello(page, """<p style="font-size:22px;letter-spacing:.08em;text-transform:uppercase;opacity:.8">Comune di Gioia del Colle</p>
      <h1 style="font-size:56px;font-weight:700;color:#fff">Prenotare il campo comunale</h1>
      <p style="font-size:28px;margin-top:24px">Oggi: <b>7 passaggi</b> su 2 portali, e paghi <i>prima</i> di sapere se l'orario è libero.</p>
      <p style="font-size:28px">Con <b>Spazio Comune</b>: <b>4 passaggi</b>, un solo portale, paghi <i>dopo</i> aver scelto.</p>""", 4200)

    page.goto(BASE + "/")
    didascalia(page, "Il calendario mostra subito gli orari liberi", "Calcetto, tennis singolo o doppio · tariffe D.G.C. 37/2025")
    page.wait_for_timeout(1800)
    scorri(page, 420)
    page.wait_for_timeout(1600)
    scorri(page, -420)

    didascalia(page, "Oppure lo chiedi all'assistente, come a un operatore", "L'IA propone, sei tu a scegliere")
    campo = evidenzia(page, "#testo", 500)
    campo.click()
    campo.press_sequentially("calcetto venerdì sera alle 20", delay=70)
    page.wait_for_timeout(500)
    evidenzia(page, "form[action='/assistente'] button", 400).click()
    page.wait_for_load_state()
    didascalia(page, "Le 20 sono già prese? Ti propone gli orari accanto", "Nessun pagamento a vuoto, nessun rimborso")
    page.locator("[aria-live=polite]").first.scroll_into_view_if_needed()
    page.wait_for_timeout(2600)
    evidenzia(page, "[aria-live=polite] a.btn", 600).click()

    page.wait_for_load_state()
    didascalia(page, "1 · Entra con SPID o CIE", "Nome, cognome e codice fiscale si compilano da soli")
    page.wait_for_timeout(1800)
    evidenzia(page, "a:has-text('Entra con SPID')", 600).click()

    page.wait_for_load_state()
    didascalia(page, "2 · Controlla il riepilogo", "L'orario resta tuo per 15 minuti mentre paghi")
    page.wait_for_timeout(2400)
    evidenzia(page, "button:has-text('pagoPA')", 600).click()

    page.wait_for_load_state()
    didascalia(page, "3 · Paga con pagoPA (MyPay Regione Puglia)", "Importo e causale già compilati: niente PDF da caricare")
    page.wait_for_timeout(2400)
    evidenzia(page, "button:has-text('Paga')", 600).click()

    page.wait_for_load_state()
    didascalia(page, "4 · Prenotazione confermata: ecco il QR per il custode", "Conferma automatica, riconciliata con il codice IUV")
    page.wait_for_timeout(1200)
    scorri(page, 260)
    page.wait_for_timeout(3000)

    page.goto(BASE + "/")
    page.locator("#domanda").scroll_into_view_if_needed()
    didascalia(page, "Domande su tariffe, pagamento, annullamento?", "Risposte con la fonte ufficiale del servizio")
    campo = evidenzia(page, "#domanda", 400)
    campo.click()
    campo.press_sequentially("posso annullare la prenotazione?", delay=60)
    evidenzia(page, "form[action='/faq'] button", 400).click()
    page.wait_for_load_state()
    page.locator(".callout").scroll_into_view_if_needed()
    page.wait_for_timeout(3200)

    page.goto(BASE + "/ufficio")
    didascalia(page, "L'Ufficio Sport vede tutto in una pagina", "Incassi pagoPA, riserve per società e scuole, export per la ragioneria")
    page.wait_for_timeout(2600)
    scorri(page, 520, 30)
    page.wait_for_timeout(2600)

    ctx.close()
    return page.video.path()


def scena_custode(browser) -> Path:
    ctx = browser.new_context(viewport=TELEFONO, record_video_dir=GREZZI / "2", record_video_size=TELEFONO,
                              http_credentials={"username": "custode", "password": "custode"},
                              device_scale_factor=2, is_mobile=True, has_touch=True, locale="it-IT")
    page = ctx.new_page()
    page.goto(BASE + "/custode")
    page.add_style_tag(content="#demo-cap{font-size:18px;top:12px;padding:12px 16px;width:90vw}")
    didascalia(page, "Il custode, dal telefono", "Ingressi di stasera e sport da preparare")
    page.wait_for_timeout(2400)
    campo = evidenzia(page, "#codice", 400)
    campo.click()
    campo.press_sequentially(codice_stasera(), delay=80)
    evidenzia(page, "form[action='/custode'] button", 400).click()
    page.wait_for_load_state()
    page.add_style_tag(content="#demo-cap{font-size:18px;top:12px;padding:12px 16px;width:90vw}")
    didascalia(page, "QR o codice valido: ingresso registrato", "Un QR già usato o contraffatto viene segnalato")
    page.wait_for_timeout(3400)
    ctx.close()
    return page.video.path()


def scena_finale(browser) -> Path:
    ctx = browser.new_context(viewport=DESKTOP, record_video_dir=GREZZI / "3", record_video_size=DESKTOP)
    page = ctx.new_page()
    cartello(page, """<h1 style="font-size:60px;font-weight:700;color:#fff">Spazio Comune</h1>
      <p style="font-size:28px;margin-top:20px">SPID/CIE · pagoPA · QR al custode · assistente IA trasparente</p>
      <p style="font-size:22px;opacity:.85;margin-top:28px">Bootstrap Italia · GDPR art. 6.1.e · AI Act art. 50 · open source EUPL-1.2, riusabile da ogni Comune</p>
      <p style="font-size:18px;opacity:.7;margin-top:36px">Demo con dati fittizi</p>""", 4200)
    ctx.close()
    return page.video.path()


CAP_MOBILE = "#demo-cap{font-size:17px;top:10px;padding:10px 14px;width:92vw}#demo-cap small{font-size:13px}"


def mobile(page: Page, titolo: str, sotto: str = "") -> None:
    page.add_style_tag(content=CAP_MOBILE)
    didascalia(page, titolo, sotto)


def scena_verticale(browser) -> Path:
    ctx = browser.new_context(viewport=VERTICALE, device_scale_factor=2, is_mobile=True, has_touch=True,
                              record_video_dir=GREZZI / "v", record_video_size=VERTICALE,
                              http_credentials={"username": "custode", "password": "custode"}, locale="it-IT")
    page = ctx.new_page()
    cartello(page, """<p style="font-size:15px;letter-spacing:.08em;text-transform:uppercase;opacity:.8">Comune di Gioia del Colle</p>
      <h1 style="font-size:38px;font-weight:700;color:#fff;line-height:1.15">Prenotare il campo comunale</h1>
      <p style="font-size:20px;margin-top:22px">Oggi: <b>7 passaggi</b> su 2 portali.<br>Paghi <i>prima</i> di sapere se l'orario è libero.</p>
      <p style="font-size:20px;margin-top:14px">Con <b>Spazio Comune</b>: <b>4 passaggi</b> dal telefono.<br>Paghi <i>dopo</i> aver scelto.</p>""", 3800, w=380)

    page.goto(BASE + "/")
    page.locator("#testo").scroll_into_view_if_needed()
    mobile(page, "Chiedilo all'assistente IA", "come lo diresti a un operatore")
    campo = evidenzia(page, "#testo", 500)
    campo.click()
    campo.press_sequentially("calcetto venerdì sera alle 20", delay=70)
    evidenzia(page, "form[action='/assistente'] button", 400).click()
    page.wait_for_load_state()
    page.locator("[aria-live=polite]").first.scroll_into_view_if_needed()
    scorri(page, -120, 6)
    mobile(page, "Le 20 sono prese? Ti propone le più vicine", "L'IA propone, tu scegli")
    page.wait_for_timeout(2600)
    evidenzia(page, "[aria-live=polite] a.btn", 600).click()

    page.wait_for_load_state()
    mobile(page, "1 · Entra con SPID o CIE", "dati già compilati")
    page.wait_for_timeout(1600)
    evidenzia(page, "a:has-text('Entra con SPID')", 500).click()
    page.wait_for_load_state()
    mobile(page, "2 · Controlla il riepilogo", "l'orario è tuo per 15 minuti")
    page.wait_for_timeout(1800)
    evidenzia(page, "button:has-text('pagoPA')", 600).click()
    page.wait_for_load_state()
    mobile(page, "3 · Paga con pagoPA", "niente ricevuta PDF da caricare")
    page.wait_for_timeout(2000)
    evidenzia(page, "button:has-text('Paga')", 600).click()
    page.wait_for_load_state()
    mobile(page, "4 · Confermata: mostra il QR", "al custode, dal telefono")
    page.wait_for_timeout(1000)
    page.locator(".qr").scroll_into_view_if_needed()
    scorri(page, -60, 5)
    page.wait_for_timeout(2800)

    page.goto(BASE + "/")
    page.locator("#domanda").scroll_into_view_if_needed()
    mobile(page, "Domande? Risponde con la fonte ufficiale", "se non lo sa, ti manda all'ufficio")
    campo = evidenzia(page, "#domanda", 400)
    campo.click()
    campo.press_sequentially("quanto costa il tennis?", delay=60)
    evidenzia(page, "form[action='/faq'] button", 400).click()
    page.wait_for_load_state()
    page.locator(".callout").scroll_into_view_if_needed()
    scorri(page, -80, 5)
    page.wait_for_timeout(3000)

    page.goto(BASE + "/custode")
    mobile(page, "Il custode verifica dal telefono", "porte o rete: sa già cosa montare")
    page.wait_for_timeout(1800)
    campo = evidenzia(page, "#codice", 400)
    campo.click()
    campo.press_sequentially(codice_stasera(), delay=70)
    evidenzia(page, "form[action='/custode'] button", 400).click()
    page.wait_for_load_state()
    mobile(page, "Ingresso registrato ✓", "un QR già usato o falso viene segnalato")
    page.wait_for_timeout(3000)

    cartello(page, """<h1 style="font-size:44px;font-weight:700;color:#fff">Spazio Comune</h1>
      <p style="font-size:20px;margin-top:18px">SPID/CIE · pagoPA · QR<br>assistente IA trasparente</p>
      <p style="font-size:16px;opacity:.85;margin-top:22px">Open source EUPL-1.2<br>riusabile da ogni Comune</p>
      <p style="font-size:14px;opacity:.7;margin-top:28px">Demo con dati fittizi</p>""", 3800, w=380)
    ctx.close()
    return page.video.path()


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def screenshot() -> None:
    cartella = RADICE / "docs" / "screenshot"
    cartella.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1.5, locale="it-IT",
                                  http_credentials={"username": "ufficio.sport", "password": "cambiami"})
        page = ctx.new_page()
        foto = lambda nome: page.screenshot(path=cartella / f"{nome}.png")  # noqa: E731
        page.goto(BASE + "/")
        foto("01_home")
        page.fill("#testo", "calcetto venerdì sera alle 20")
        page.click("form[action='/assistente'] button")
        page.wait_for_load_state()
        page.locator("[aria-live=polite]").first.scroll_into_view_if_needed()
        page.mouse.wheel(0, -150)
        page.wait_for_timeout(300)
        foto("02_assistente")
        page.locator("[aria-live=polite] a.btn").first.click()
        page.click("a:has-text('Entra con SPID')")
        page.wait_for_load_state()
        foto("03_riepilogo")
        page.click("button:has-text('pagoPA')")
        page.wait_for_load_state()
        foto("04_pagopa")
        page.click("button:has-text('Paga')")
        page.wait_for_load_state()
        foto("05_ticket")
        page.goto(BASE + "/")
        page.fill("#domanda", "posso annullare la prenotazione?")
        page.click("form[action='/faq'] button")
        page.wait_for_load_state()
        page.locator(".callout").scroll_into_view_if_needed()
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(300)
        foto("06_faq")
        page.goto(BASE + "/ufficio")
        foto("07_ufficio")
        ctx.close()
        ctx = browser.new_context(viewport={"width": 390, "height": 760}, device_scale_factor=2, is_mobile=True,
                                  has_touch=True, locale="it-IT",
                                  http_credentials={"username": "custode", "password": "custode"})
        page = ctx.new_page()
        page.goto(BASE + "/custode")
        page.fill("#codice", codice_stasera())
        page.click("form[action='/custode'] button")
        page.wait_for_load_state()
        page.screenshot(path=cartella / "08_mobile.png")
        browser.close()
    print(cartella)


def main_verticale() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        clip = scena_verticale(browser)
        browser.close()
    mp4 = USCITA / "spazio-comune-demo-verticale.mp4"
    ffmpeg("-i", str(clip), "-vf", "fps=30,scale=1080:1920:flags=lanczos,setsar=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4))
    shutil.rmtree(GREZZI, ignore_errors=True)
    print(mp4)


def main() -> None:
    shutil.rmtree(GREZZI, ignore_errors=True)
    USCITA.mkdir(parents=True, exist_ok=True)
    if "--verticale" in sys.argv:
        return main_verticale()
    if "--screenshot" in sys.argv:
        return screenshot()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        clip = [scena_cittadino(browser), scena_custode(browser), scena_finale(browser)]
        browser.close()

    # il video del telefono viene centrato su sfondo blu istituzionale
    w, h = DESKTOP["width"], DESKTOP["height"]
    filtro = (f"[0:v]fps=25,scale={w}:{h},setsar=1[a];"
              f"[1:v]fps=25,scale=-2:{h - 40},pad={w}:{h}:(ow-iw)/2:20:color=0x00264d,setsar=1[b];"
              f"[2:v]fps=25,scale={w}:{h},setsar=1[c];"
              "[a][b][c]concat=n=3:v=1:a=0[v]")
    mp4 = USCITA / "spazio-comune-demo.mp4"
    ffmpeg(*sum([["-i", str(c)] for c in clip], []), "-filter_complex", filtro, "-map", "[v]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4))
    gif = USCITA / "spazio-comune-demo.gif"
    ffmpeg("-i", str(mp4), "-vf",
           "fps=12,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4",
           str(gif))
    shutil.rmtree(GREZZI, ignore_errors=True)
    print(mp4, gif, sep="\n")


if __name__ == "__main__":
    main()
