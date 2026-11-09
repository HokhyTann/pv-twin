# PV Digital Twin — Implementation Plan

A personal project: an interactive digital view of a solar PV fleet that O&M can use to monitor
performance, losses, inverter risk and billing. The starting data is the synthetic Cambodian
plant data from the FAI assessment pack. Everything else (layout, cables, transformers) is generated.

---

## 1. Goals and non-goals

**Goals**
- Show each plant as it is laid out on site: panel tables, combiner boxes, inverters, transformers,
  cables, substation and meter. Any asset can be clicked to see its data.
- Colour the plant by a chosen metric (PR, availability, failure risk, expected-vs-actual residual,
  data quality) at a chosen point in time.
- Cover the four monitoring problems as views:
  1. Site performance (PR by site and month, data quality)
  2. Expected vs. actual energy (soiling and hidden losses)
  3. Inverter failure risk (weekly inspection list)
  4. Meter vs. SCADA reconciliation (invoice gap)
- Allow string-level or live telemetry to be added later without a redesign.

**Non-goals (for now)**
- No auth, multi-tenancy or cloud deployment. Everything runs locally with Docker.
- No real-time streaming. Data is loaded in batches from CSV; a simulated "live" feed comes later.
- No 3D in v1. It is an optional phase at the end.

---

## 2. Architecture

```
┌──────────────────────────── Browser ─────────────────────────────┐
│  React + TS (Vite)                                                │
│  deck.gl layout · React Flow SLD · ECharts · TanStack Query       │
└───────────────▲──────────────────────────────────────────────────┘
                │ JSON / GeoJSON (REST)
┌───────────────┴──────────────── API ─────────────────────────────┐
│  FastAPI (Python 3.12, uv)                                        │
│  routers: assets · layout · metrics · alerts · reconciliation     │
│  jobs:    ingest · transform · layout-gen · ml-train · ml-score   │
└───────────────▲──────────────────────────────────────────────────┘
                │ SQLAlchemy 2 / psycopg 3
┌───────────────┴──────────────── DB ──────────────────────────────┐
│  PostgreSQL 17 + PostGIS + TimescaleDB  (one Docker container)    │
│  schemas: raw → clean → mart   + core (assets)   + app (user data)│
└──────────────────────────────────────────────────────────────────┘
```

**Rule:** the frontend only reads `mart` (and `core` for geometry). Python jobs write `clean`,
`mart` and the model outputs. The API holds no business logic that belongs in SQL.

---

## 3. Repository layout

```
PV/
├── PLAN.md
├── docker-compose.yml          # db (+ api, web later)
├── .env.example
├── data/
│   └── source/                 # original CSVs copied from the assessment pack (read-only)
├── db/
│   ├── migrations/             # Alembic (raw SQL in upgrade/downgrade)
│   └── sql/
│       ├── clean/              # one .sql per clean table/view
│       └── mart/               # one .sql per mart view/materialized view
├── backend/
│   ├── pyproject.toml          # uv
│   ├── app/
│   │   ├── main.py             # FastAPI app
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── routers/            # assets, layout, metrics, alerts, recon
│   │   └── schemas/            # Pydantic response models
│   ├── jobs/
│   │   ├── ingest.py           # CSV → raw.*
│   │   ├── transform.py        # runs db/sql/clean then db/sql/mart in order
│   │   ├── layout_gen.py       # builds core.asset + geometry
│   │   ├── train_energy.py     # Problem 2 model
│   │   ├── train_failure.py    # Problem 3 model
│   │   └── score.py            # writes predictions/alerts to mart
│   └── tests/
├── frontend/
│   ├── package.json            # pnpm
│   └── src/
│       ├── app/                # routes, layout shell
│       ├── views/              # FleetMap, SiteLayout, SLD, AssetPanel, Alerts, Recon
│       ├── layers/             # deck.gl layer factories
│       ├── charts/             # ECharts wrappers
│       ├── api/                # typed client + TanStack Query hooks
│       └── state/              # Zustand store
└── Makefile                    # make up / ingest / transform / layout / train / dev
```

---

## 4. Data sources and the site registry

| Source file | Grain | Used for |
|---|---|---|
| `low_site_daily.csv` | site × day (3 sites, Jan–Apr 2026) | PR and availability, data-quality checks |
| `medium_site_daily.csv` | day (one 60 MWp site, Jan 2025–Jun 2026) | Expected-energy model, soiling/cleaning |
| `high_inverter_daily.csv` | inverter × day (4 sites × 10 inv, Jul 2025–Jun 2026) | Failure-risk model |
| `expert_scada_15min.csv` | inverter × 15 min (10 inv, Jan–Mar 2026) | SCADA energy, availability |
| `expert_meter_daily.csv` | day | Billed energy |
| `expert_asset_register.csv` | inverter | Ratings, DC capacity, commissioning date |
| `expert_maintenance_log.csv` | free-text event | Event timeline, explaining gaps |

**Site codes clash between files.** For example, `PV-01` is an 80 MWp site in the P1 file and a
fleet site in the P3 file. Fix this with a seeded `core.site` registry that gives every site one
unique code and records where it came from:

| site_code | name | capacity | source dataset | source code |
|---|---|---|---|---|
| KH-A01..A03 | Sites from P1 | 80 / 60 / 40 MWp | low | PV-01..03 |
| KH-B01 | 60 MWp site | 60 MWp | medium | (none) |
| KH-C01..C04 | Inverter fleet | 10 inv each | high | PV-01..04 |
| KH-D06 | PV-06 | 10 × 3 MWp DC | expert | PV-06 |

Each site gets a fictional location in Cambodia. The ingest jobs map source codes to `site_id`
using this table.

---

## 5. Database

### 5.1 Setup
- Image: `timescale/timescaledb-ha:pg17`. It already includes PostGIS and TimescaleDB.
- Extensions: `postgis`, `timescaledb`, `pg_stat_statements`.
- Migrations: Alembic. The SQL is written by hand; no ORM autogenerate for analytics tables.
- Geometry is stored as `geometry(…, 4326)` (WGS84). The layout is generated in UTM 48N
  (EPSG:32648, which covers Cambodia) so it can be measured in metres, then converted to 4326.

### 5.2 Schemas

| Schema | Contents | Written by |
|---|---|---|
| `raw` | Exact CSV copies, all columns as text, plus `_file`, `_row`, `_loaded_at` | `ingest.py` |
| `core` | Site registry, asset tree, asset geometry, cable network | seed + `layout_gen.py` |
| `clean` | Typed, deduplicated, unit-checked data with `dq_flag` columns; telemetry hypertables | `transform.py` |
| `mart` | Read models for the UI (aggregates, KPIs, predictions, alerts) | `transform.py`, `score.py` |
| `app` | User-created data: alert acks, notes, saved views | API |

### 5.3 Core asset model

```sql
core.site (
  site_id       serial PK,
  site_code     text unique,
  name          text,
  capacity_dc_kwp numeric,
  tz            text default 'Asia/Phnom_Penh',
  location      geometry(Point, 4326),
  source_dataset text, source_code text
)

core.asset (
  asset_id      bigserial PK,
  site_id       int FK → core.site,
  parent_id     bigint FK → core.asset,      -- tree
  asset_type    text,   -- substation | meter | transformer | inverter | combiner | string | table
  code          text,   -- e.g. INV-07, CB-07-03, TBL-07-03-12
  attrs         jsonb,  -- model, rated_ac_kw, dc_kwp, commissioned, modules_per_table …
  geom          geometry(Geometry, 4326),    -- point for equipment, polygon for tables/blocks
  unique (site_id, code)
)
create index on core.asset using gist (geom);
create index on core.asset (site_id, asset_type);

core.cable (
  cable_id      bigserial PK,
  site_id       int,
  from_asset    bigint FK, to_asset bigint FK,
  kind          text,    -- dc_string | dc_main | ac_lv | mv | comms
  geom          geometry(LineString, 4326),
  length_m      numeric generated always as (…)  -- or computed at insert time
)
```

The electrical tree is **site → substation → meter → MV transformer → inverter → combiner box →
string → panel table**. The SLD and every drill-down come from `parent_id`. For deep queries use
a recursive CTE, or a `path ltree` column if that turns out easier.

### 5.4 Telemetry (clean schema, Timescale hypertables)

```sql
clean.inverter_15min (ts timestamptz, asset_id bigint, ac_power_kw real, dq_flag smallint)
  -- hypertable on ts, 7-day chunks, compression after 30 days
clean.inverter_daily (day date, asset_id, online, energy_kwh, efficiency_pct, igbt_max_temp_c,
                      fan_speed_rpm, alarm_count, ambient_max_c, ticket_flag, failure_next_7d)
clean.site_daily     (day date, site_id, energy_mwh, irradiation_kwh_m2, ambient_max_c,
                      availability_pct, panel_cleaning, dq_flag)
clean.meter_daily    (day date, asset_id /*meter*/, export_kwh, dq_flag)
clean.event          (ts timestamptz, site_id, asset_id null, category, note)
                      -- from the maintenance log; category from keyword rules
                      -- (cleaning, trip, fault, comms, firmware, meter)
clean.dq_issue       (table_name, row_ref, rule, detail, action)   -- data-quality log
```

The `dq_flag` bitmask records problems instead of deleting rows: duplicate, missing, out of
range, negative, timestamp gap, stuck value, and so on. Every rule also writes a row to
`clean.dq_issue` so the UI can show it.

### 5.5 Marts (what the UI reads)

| Mart | Grain | Notes |
|---|---|---|
| `mart.site_pr_daily` / `_monthly` | site × day/month | Sum energy and irradiation first, then divide |
| `mart.site_kpi_latest` | site | Last-30-day PR, availability, open alerts (for fleet map dots) |
| `mart.inverter_daily_kpi` | inverter × day | Energy, specific yield, availability, data completeness |
| `mart.energy_expected` | site × day | Model prediction, actual, residual %, lost MWh, lost $ |
| `mart.inverter_risk` | inverter × day | Failure score, rank, alert flag, model version |
| `mart.inspection_list` | week | Top-N inverters to inspect, within the weekly limit |
| `mart.recon_daily` | site × day | SCADA kWh, meter kWh, gap, gap broken down by cause |
| `mart.alert` | alert | Unified feed: type, severity, asset, period, $ impact, status |

Continuous aggregates handle the 15-min → hourly → daily rollups. Monthly and KPI marts are
materialized views refreshed at the end of `transform.py`.

### 5.6 Model tables
```sql
mart.model_run (run_id, model_name, version, trained_at, train_period, test_period,
                metrics jsonb, params jsonb, artifact_path)
```
Every prediction row stores its `run_id`, so the UI can always say which model produced a number.

---

## 6. Backend (FastAPI)

### 6.1 Stack
- Python 3.12, **uv** for environments
- FastAPI + Pydantic v2; SQLAlchemy 2 Core (not the ORM) on **psycopg 3**
- pandas / polars for jobs; scikit-learn + LightGBM for models; joblib for model files
- pytest + a throwaway Postgres for tests (testcontainers or a docker-compose test profile)
- ruff for linting and formatting

### 6.2 Jobs (run with `make` / `uv run python -m jobs.X`)
1. **`ingest`**: copies each CSV into `raw.*` with `COPY`. It must be idempotent (truncate and
   reload per file) and record a file hash so an unchanged file is skipped.
2. **`layout_gen`**: builds `core.asset` and `core.cable` for each site (see 6.4).
3. **`transform`**: runs `db/sql/clean/*.sql`, then `db/sql/mart/*.sql`, in filename order inside
   one transaction per layer, then refreshes the materialized views.
4. **`train_energy`** (P2): trains on 2025, tests on 2026 H1, saves the model and a `model_run`
   row. Start with linear regression on irradiation and temperature, then try gradient boosting.
5. **`train_failure`** (P3): splits by time, excludes the leaky columns (`ticket_flag` and the
   rows after a failure), builds rolling features (7/14-day mean, slope and max of IGBT
   temperature, fan speed, alarms and efficiency drop). Trains LightGBM with class weights and
   picks the threshold by expected $ saving under the 3-inspections-per-week limit.
6. **`score`**: applies the latest models and writes `mart.energy_expected`,
   `mart.inverter_risk`, `mart.inspection_list` and `mart.alert`.

Later, a small scheduler (APScheduler, or plain cron) can replay data day by day to imitate
live operation.

### 6.3 API (all under `/api/v1`)

| Method & path | Returns |
|---|---|
| `GET /sites` | Site list with latest KPIs and health (for the fleet map) |
| `GET /sites/{id}/layout?types=table,inverter,cable` | GeoJSON FeatureCollection (or binary, see 6.5) |
| `GET /sites/{id}/tree` | Asset tree for the SLD and tree navigator |
| `GET /sites/{id}/colour?metric=pr&date=…` | `{asset_id: value}` for colouring the layout |
| `GET /assets/{id}` | Asset details, attributes, parent chain |
| `GET /assets/{id}/timeseries?metric=…&from=…&to=…&res=15m\|1h\|1d` | Time series |
| `GET /sites/{id}/pr?grain=day\|month` | PR series |
| `GET /sites/{id}/expected-energy` | Actual vs. expected, residuals, cleaning events |
| `GET /risk?week=…` | Inverter risk ranking and the inspection list |
| `GET /sites/{id}/reconciliation?from=…&to=…` | SCADA vs. meter, gap broken down by cause |
| `GET /events?site_id=…` | Maintenance-log events |
| `GET /dq?site_id=…` | Data-quality issues |
| `GET /alerts?status=open` / `PATCH /alerts/{id}` | Alert feed / acknowledge or close |

**Design rule:** keep geometry (which rarely changes, so cache it hard) separate from metric
values (which change with the date and metric). When the user moves the time slider, the
frontend only re-fetches the small `colour` payload, never the geometry.

### 6.4 Layout generator (`layout_gen.py`)
This is what makes the plant look real. All sizes are parameters.
- **Panel table:** 2 × 28 modules of 600 Wp ≈ 33.6 kWp, about 4.5 m × 33 m footprint, rows
  facing south with a gap between rows chosen to avoid shading (about 1.8 × table depth).
- **Inverter block:** about `dc_kwp / table_kwp` tables (≈ 90 for a 3 MWp block), arranged in a
  rectangle around a central inverter-and-transformer skid.
- **Combiner box:** one per ~16 strings. Each table is assigned to its nearest combiner box.
- **Site:** blocks laid out in a grid, with service roads between them, a substation and meter
  at the edge, and a fence polygon around everything.
- **Cables:** Manhattan-style polylines (straight lines with right-angle turns) for
  table → combiner (DC), combiner → inverter (DC main) and transformer → substation (MV ring
  or radial). `length_m` is computed from the line, which later allows cable-loss estimates.
- **Sites with no inverter data** (P1, P2): blocks are sized from capacity alone with nominal
  3 MWp inverters, and are coloured by site-level metrics.

Use a fixed random seed so the layout is the same on every run.

### 6.5 Performance notes
- An 80 MWp site has about 2,400 tables, which is tiny for deck.gl. GeoJSON is fine for v1.
- If it gets slow, add `ST_AsMVT` vector tiles or a binary columnar endpoint (Arrow or flat
  arrays) for deck.gl's binary attributes.
- Cache `layout` responses with an ETag based on the layout version.

---

## 7. Frontend

### 7.1 Stack
- **Vite + React 19 + TypeScript**, pnpm
- **deck.gl** (`@deck.gl/react`, `layers`, `geo-layers`): the plant layout and fleet map
- **MapLibre GL** via `react-map-gl/maplibre` as the basemap (free OSM-style tiles, or no
  basemap with a plain dark background for the plant view)
- **React Flow (@xyflow/react)**: single-line diagram, auto-laid-out with **elkjs**
- **Apache ECharts** (`echarts-for-react`): all time-series charts
- **TanStack Query**: data fetching and caching. **Zustand**: shared UI state
- **TanStack Router** (or React Router): routing with type-safe search params
- **Tailwind CSS + shadcn/ui**: panels, tables, controls
- API types generated from FastAPI's OpenAPI spec (`openapi-typescript`)

### 7.2 Shared state (Zustand)
`selectedSiteId · selectedAssetId · hoveredAssetId · colourMetric · date / dateRange ·
layerVisibility · viewMode (layout | sld | split)`

The URL search params mirror this state, so any view can be bookmarked and shared.

### 7.3 Screens

1. **Fleet overview** (`/`)
   - Map of Cambodia with one dot per site, sized by MWp and coloured by health (PR band or
     open alerts).
   - Side list: KPIs per site and a sparkline of the last 30 days of PR.
2. **Site twin** (`/sites/:id`), the main screen
   - **Left:** asset tree navigator and layer toggles (tables, strings, combiners, inverters,
     transformers, DC cables, MV cables, comms, roads, fence).
   - **Centre:** deck.gl plant layout.
     - `PolygonLayer` for tables, coloured by the chosen metric through a legend scale
     - `IconLayer` for inverters, transformers, combiners and the meter
     - `PathLayer` for cables, styled by kind, with a "trace path" highlight
     - `TextLayer` for labels that appear once zoomed in
   - **Top bar:** metric picker (PR, availability, risk, residual, data quality), date
     picker/slider, play button to animate across days.
   - **Right drawer:** details of the selected asset (see screen 3).
   - **Toggle:** layout ↔ SLD ↔ split view. Selecting in one highlights in the other.
3. **Asset drawer** (opened by clicking any asset)
   - Attributes (model, rating, commissioned date), and its parent and children.
   - Charts for that asset type: power / energy, efficiency, IGBT temperature, fan speed,
     risk score history.
   - Related events from the maintenance log and open alerts, with an acknowledge action.
   - **"Trace upstream"**: highlights the full path from table to meter on both the layout
     and the SLD.
4. **Performance** (`/sites/:id/performance`): PR heatmap (month × site), daily PR line with
   the 0.75–0.85 healthy band, data-quality issue table.
5. **Expected energy** (`/sites/:id/expected`): actual vs. expected, residual % timeline with
   cleaning-day markers, running total of lost MWh and $.
6. **Inverter risk** (`/risk`): ranked table, this week's inspection list (max 3), score
   history per inverter, caught/missed backtest.
7. **Reconciliation** (`/sites/:id/recon`): daily SCADA vs. meter, a waterfall from SCADA total
   to billed total split by cause, event overlay, per-inverter availability ranking.
8. **Alerts** (`/alerts`): one feed for all alert types, filterable. Clicking an alert jumps to
   the asset on the twin.

### 7.4 Visual conventions
- One colour scale per metric with a fixed domain (for example PR 0.6–0.9, with the healthy
  band highlighted), so colours mean the same thing on every screen.
- Grey with hatching means **no data**. Never let missing data look like a zero value.
- Each table polygon shows its own metric value if one exists; otherwise it shows the parent
  inverter's value with a "via INV-07" note in the tooltip.
- Every chart axis shows its unit (MWh, kWh/m², °C, %).

---

## 8. Dev environment

```
make up         # docker compose up -d db
make migrate    # alembic upgrade head
make seed       # core.site registry
make ingest     # CSV → raw
make layout     # generate assets + geometry
make transform  # raw → clean → mart
make train      # train both models
make score      # predictions + alerts
make api        # uvicorn --reload on :8000
make web        # vite dev server on :5173 (proxies /api → :8000)
make all        # everything above in order, from an empty DB
```

`.env` holds the DB URL and data path. All the CSVs are copied into `data/source/`; the
assessment folder is never modified.

---

## 9. Phases

Each phase ends with something visible and working.

| # | Phase | Done when |
|---|---|---|
| 0 | **Scaffold**: repo, docker-compose, Alembic, uv, Vite, Makefile | `make up migrate` works; the web app shows "API ok" from `/health` |
| 1 | **Ingest + clean + DQ** | All 7 CSVs in `raw` and `clean`; `clean.dq_issue` lists the problems; SQL tests pass |
| 2 | **Asset model + layout generator** | `core.asset` and `core.cable` filled for all sites; the layout checks out in QGIS or the browser |
| 3 | **Site twin v1**: deck.gl layout, layer toggles, click → asset drawer with attributes | Can pan, zoom, select, and trace upstream on KH-D06 |
| 4 | **Metrics + colour-by**: PR/availability marts, colour endpoint, date slider | Changing the date recolours the layout without re-fetching geometry |
| 5 | **SLD view** (React Flow + elkjs), synced selection with the layout | Split view; selecting in one highlights in the other |
| 6 | **Expected-energy model** (P2) + screen | Residual chart shows the soiling event; loss in $ shown |
| 7 | **Failure-risk model** (P3) + risk screen + alerts | Weekly inspection list; backtest caught/missed/net saving |
| 8 | **Reconciliation** (P4) + waterfall + event overlay | Gap explained by cause, real loss vs. data problems separated |
| 9 | **Fleet overview + unified alerts** | Every site on one map; alert → jump to asset |
| 10 | *(optional)* **Simulated live mode**: replay data day by day, alerts appear as they would have | "Play" the year and watch alerts trigger |
| 11 | *(optional)* **3D view**: React Three Fiber with instanced meshes for tables, same asset API | 3D toggle on the site twin |

Phases 0–4 are the core and give a usable twin. Phases 6–8 can be done in any order after that.

---

## 10. Testing

- **SQL:** small fixture CSVs with known answers (PR for a hand-calculated month, known
  duplicates) loaded into a test DB; assert on the mart results.
- **Jobs:** pytest for the layout generator (table count ≈ DC kWp / table kWp, no overlapping
  polygons, every table linked to an inverter), and for leakage (no training row uses features
  dated after its prediction date).
- **API:** pytest with httpx against the test DB.
- **Frontend:** Vitest for utilities and colour scales; Playwright smoke test for select → drawer →
  trace path.

---

## 11. Open decisions (decide when we reach that phase)

1. **Basemap:** none (abstract dark canvas) vs. MapLibre with OSM tiles vs. satellite imagery
   (needs a key). Default: no basemap for the site view, OSM tiles for the fleet map.
2. **Transforms:** plain SQL files (default) vs. dbt-postgres once there are more than ~20 marts.
3. **Model serving:** batch scoring into `mart` (default) vs. an on-demand predict endpoint.
4. **Strings/modules:** keep as generated geometry only, or simulate string currents so the
   twin can show string-level faults.
