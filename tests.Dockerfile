# Immagine per la suite di test (unit + integrazione app<->inference in-process)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Europe/Rome
WORKDIR /srv
COPY app/requirements.txt app-req.txt
COPY inference/requirements.txt inf-req.txt
COPY mcp_server/requirements.txt mcp-req.txt
RUN pip install -r app-req.txt -r inf-req.txt -r mcp-req.txt pytest==9.1.1 pyyaml==6.0.3
COPY app/ app/
COPY inference/ inference/
COPY mcp_server/ mcp_server/
COPY pytest.ini .
RUN test -f app/prenota/static/bootstrap-italia/VERSION || python app/scripts/fetch_bootstrap_italia.py
CMD ["pytest", "-q"]
