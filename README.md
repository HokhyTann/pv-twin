# PV Digital Twin

Interactive digital view of a solar PV fleet for O&M monitoring. See [PLAN.md](PLAN.md) for the full design.

## Prerequisites
Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node + pnpm.

## Quickstart
```bash
make install   # backend (uv) + frontend (pnpm) deps, creates .env
make data      # copy source CSVs into data/source
make up        # start Postgres (TimescaleDB + PostGIS)
make pipeline  # migrate -> ingest CSVs (raw) -> transform (core, clean)
make dq        # print the data-quality issue log
make api       # FastAPI on http://localhost:8000  (docs at /docs)
make web       # Vite on http://localhost:5173
```

`make test` runs the backend tests against a throwaway `pv_test` database.
`make help` lists every target. `make reset` deletes the database volume.

## Layout
```
backend/   FastAPI app (app/) and data jobs (jobs/), managed with uv
frontend/  Vite + React + TypeScript
db/        Alembic migrations and SQL transforms (core/, clean/, mart/)
data/      source CSVs (not committed)
```

## Data layers
| Schema | What | Built by |
|---|---|---|
| `raw` | CSVs as text, one column per field plus `_row` (source line) | `jobs.ingest` |
| `core` | Site registry (unique codes like `KH-A01`) and asset tree | migration seed + `db/sql/core` |
| `clean` | Typed tables with `dq_flags`; impossible values set to NULL, never silently dropped | `db/sql/clean` |
| `mart` | Read models for the UI | `db/sql/mart` (from Phase 4) |

Every data problem is logged in `clean.dq_issue` with the source line, rule and the action
taken. Rule definitions are in `clean.dq_rule`; `clean.dq_rules_of(dq_flags)` decodes a flag.
