# Spazio Comune: scorciatoie per Docker Compose (vedi docker-compose.yml)
#
#   make build    costruisce le immagini (app, inference, mcp)
#   make up       avvia lo stack in background (app :8000, MCP :8090)
#   make help     tutti i comandi

COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help build up down restart logs ps test demo llm

help: ## Mostra i comandi disponibili
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-10s %s\n", $$1, $$2}'

.env:
	cp .env.example .env
	@echo "Creato .env da .env.example: rivedi SPAZIO_*, COMUNE_* e le password."

build: .env ## Costruisce le immagini
	$(COMPOSE) build

up: .env ## Avvia app + inferenza + server MCP in background (con build)
	$(COMPOSE) up --build -d

down: ## Ferma lo stack (i dati in PostgreSQL restano nel volume)
	$(COMPOSE) --profile demo --profile llm down

restart: ## Ricrea i container dopo una modifica al .env
	$(COMPOSE) up -d --force-recreate

logs: ## Segue i log di tutti i servizi
	$(COMPOSE) logs -f

ps: ## Stato dei container
	$(COMPOSE) ps

test: ## Esegue la suite pytest nel container di test
	$(COMPOSE) --profile test run --build --rm test

demo: .env ## Avvia anche l'istanza demo con dati fittizi su :8001
	$(COMPOSE) --profile demo up --build -d

llm: .env ## Avvia anche l'LLM locale con Ollama
	$(COMPOSE) --profile llm up --build -d
