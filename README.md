# PV Digital Twin

Interactive digital view of a solar PV fleet for O&M monitoring. See [PLAN.md](PLAN.md) for the full design.

## Prerequisites
Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node + pnpm.

## Quickstart
```bash
make install   # backend (uv) + frontend (pnpm) deps, creates .env
make data      # copy source CSVs into data/source
make up        # start Postgres (TimescaleDB + PostGIS)
make migrate   # apply migrations
make api       # FastAPI on http://localhost:8000  (docs at /docs)
make web       # Vite on http://localhost:5173
```

`make help` lists every target. `make reset` deletes the database volume.

## Layout
```
backend/   FastAPI app (app/) and data jobs (jobs/), managed with uv
frontend/  Vite + React + TypeScript
db/        Alembic migrations and SQL transforms (clean/, mart/)
data/      source CSVs (not committed)
```
