SHELL := /bin/bash
ASSESSMENT_DATA ?= $(HOME)/Desktop/FAI_Engineer_Assessment_Candidate_Pack/data

.PHONY: help env install up down reset psql migrate revision api web data health

help:            ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

env:             ## Create .env from .env.example if missing
	@test -f .env || cp .env.example .env

install: env     ## Install backend + frontend dependencies
	cd backend && uv sync
	cd frontend && pnpm install

up: env          ## Start Postgres and wait until healthy
	docker compose up -d --wait db

down:            ## Stop containers (keeps data)
	docker compose down

reset:           ## Stop containers AND delete the database volume
	docker compose down -v

psql:            ## Open psql in the db container
	docker compose exec db psql -U pv -d pv

migrate:         ## Apply all Alembic migrations
	cd backend && uv run alembic upgrade head

revision:        ## New migration: make revision m="message"
	cd backend && uv run alembic revision -m "$(m)"

data:            ## Copy assessment CSVs into data/source (source folder untouched)
	cp -n $(ASSESSMENT_DATA)/*.csv data/source/ || true
	@ls -1 data/source

api:             ## Run FastAPI on :8000 with reload
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:             ## Run Vite dev server on :5173 (proxies /api -> :8000)
	cd frontend && pnpm dev

health:          ## Call the API health endpoint
	@curl -s localhost:8000/api/v1/health | python3 -m json.tool
