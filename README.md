# PV Digital Twin

Interactive digital view of a solar PV fleet for O&M monitoring. See [PLAN.md](PLAN.md) for the full design.

## Prerequisites
Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node + pnpm.

## Quickstart
```bash
make install   # backend (uv) + frontend (pnpm) deps, creates .env
make data      # copy source CSVs into data/source
make up        # start Postgres (TimescaleDB + PostGIS)
make pipeline  # migrate -> ingest CSVs (raw) -> transform (core, clean) -> layout
make dq        # print the data-quality issue log
make layout-preview  # render each site's layout to data/preview/*.html
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
| `core` | Site registry (unique codes like `KH-A01`), asset tree, cables, fence/roads/blocks | migration seed + `db/sql/core` + `jobs.layout_gen` |
| `clean` | Typed tables with `dq_flags`; impossible values set to NULL, never silently dropped | `db/sql/clean` |
| `mart` | Read models for the UI | `db/sql/mart` (from Phase 4) |

Every data problem is logged in `clean.dq_issue` with the source line, rule and the action
taken. Rule definitions are in `clean.dq_rule`; `clean.dq_rules_of(dq_flags)` decodes a flag.

## Synthetic layout
The source data stops at inverter level, so the plant below it is generated
(`backend/jobs/layout_plan.py`, all sizes in `LayoutParams`):

```
substation -> meter -> transformer -> inverter -> combiner -> table -> string
```

- Table = 2 x 28 modules of 600 Wp (33.6 kWp), one string per module row; rows face south.
- Two inverter blocks share a station; inverters, transformer and combiners sit in the
  corridor between them. Each column of stations is one MV feeder to the substation.
- Inverter DC size: asset register (KH-D06); otherwise estimated from energy against
  KH-D06's specific yield (KH-C0x, marked `dc_kwp_source` in `attrs`); otherwise
  site capacity / 3 MWp generated inverters (KH-A0x, KH-B01, `generated: true`).
- Re-running keeps source inverter/meter `asset_id`s, so clean telemetry stays linked.
  `core.layout_run.version` changes only when inputs or parameters change.
