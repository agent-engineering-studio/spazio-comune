---
title: Video e demo
description: Video dimostrativi di Spazio Comune e come rigenerarli.
---

# Video e demo

Tutti i video usano **dati fittizi**: nomi, codici fiscali e pagamenti sono inventati.

## Orizzontale 16:9 (presentazioni, LinkedIn, YouTube)

<video class="video-demo" controls muted playsinline preload="metadata" poster="../screenshot/01_home.png">
  <source src="../demo/spazio-comune-demo.mp4" type="video/mp4">
</video>

[:material-download: MP4](demo/spazio-comune-demo.mp4){ .md-button }
[:material-download: GIF](demo/spazio-comune-demo.gif){ .md-button }

## Verticale 9:16 (reel, storie, WhatsApp)

<video class="video-verticale" controls muted playsinline preload="metadata" poster="../demo/verticale-poster.jpg">
  <source src="../demo/spazio-comune-demo-verticale.mp4" type="video/mp4">
</video>

[:material-download: MP4 verticale](demo/spazio-comune-demo-verticale.mp4){ .md-button }

## Rigenerare i video

I video vengono registrati da Playwright, che percorre da solo l'istanza demo, e montati con `ffmpeg`.

```bash
pip install playwright && playwright install chromium
docker compose --profile demo up --build -d

python app/scripts/registra_demo.py               # 16:9 → docs/demo/spazio-comune-demo.{mp4,gif}
docker compose restart demo                       # ogni registrazione consuma uno slot e un ingresso
python app/scripts/registra_demo.py --verticale   # 9:16 → docs/demo/spazio-comune-demo-verticale.mp4
```

Le didascalie sono in `app/scripts/registra_demo.py`; i dati fittizi in `app/scripts/demo.py`.
