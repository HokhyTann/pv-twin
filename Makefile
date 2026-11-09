SHELL := /bin/bash
ASSESSMENT_DATA ?= $(HOME)/Desktop/FAI_Engineer_Assessment_Candidate_Pack/data

.PHONY: help env install up down reset psql migrate revision api web data health \
	ingest transform layout layout-preview pipeline dq test lint

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

ingest:          ## Load CSVs into raw.* (skips unchanged files; f=--force to reload)
	cd backend && uv run python -m jobs.ingest $(f)

transform:       ## Rebuild core + clean (+ mart) from raw
	cd backend && uv run python -m jobs.transform

layout:          ## Generate synthetic plant layouts (assets, cables, features) for all sites
	cd backend && uv run python -m jobs.layout_gen $(sites)

layout-preview:  ## Render layouts to data/preview/*.html (open index.html in a browser)
	cd backend && uv run python -m jobs.layout_preview $(sites)
	@echo "open data/preview/index.html"

pipeline: migrate ingest transform layout  ## migrate -> ingest -> transform -> layout

dq:              ## Show the data-quality issue log
	@docker compose exec -T db psql -U pv -d pv -c "select source_table, rule, severity, \
	  source_row as line, entity, to_char(period_start at time zone 'Asia/Phnom_Penh', 'YYYY-MM-DD') as start, \
	  n_rows, detail from clean.dq_issue order by source_table, severity, rule, source_row"

test:            ## Run backend tests (needs `make up`; throwaway pv_test DB) + frontend unit tests
	cd backend && uv run pytest -q
	cd frontend && pnpm test

lint:            ## Backend: ruff format + lint. Frontend: oxlint + type check
	cd backend && uv run ruff format . ../db/migrations && uv run ruff check --fix . ../db/migrations
	cd frontend && pnpm lint && pnpm typecheck

api:             ## Run FastAPI on :8000 with reload
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:             ## Run Vite dev server on :5173 (proxies /api -> :8000)
	cd frontend && pnpm dev

health:          ## Call the API health endpoint
	@curl -s localhost:8000/api/v1/health | python3 -m json.tool
