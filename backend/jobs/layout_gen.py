"""Generate the synthetic plant layout for each site and store it in core.*.

For every site:
1. Decide its inverters:
   - inverters already in core.asset (from source data) are kept, with their asset_id;
   - their DC size comes from the asset register, or is *estimated* from energy
     (see estimate_dc_kwp) when the source has none (fleet sites KH-C0x);
   - sites without inverter data (KH-A0x, KH-B01) get generated 3 MWp inverters.
2. Plan the layout in metres (jobs.layout_plan).
3. Replace the site's generated assets, cables and features; place the geometry at the
   site's location (UTM 48N -> WGS84).

Source inverters and meters are only ever updated, never deleted, because clean.*
telemetry references them.

Usage:  uv run python -m jobs.layout_gen [SITE_CODE ...]
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

import psycopg

from app.config import get_settings
from jobs.layout_plan import (
    InverterSpec,
    LayoutParams,
    SiteLayout,
    layout_version,
    plan_site,
    wkt_line,
)

log = logging.getLogger("layout_gen")

UTM = 32648  # WGS 84 / UTM zone 48N (covers Cambodia)
GENERATED_TYPES = ("substation", "transformer", "combiner", "table", "string")

ESTIMATE_SQL = """
-- Specific yield (kWh per kWp per day) of a reference site whose inverter DC size is known,
-- from clean 15-minute SCADA (scaling-suspect intervals excluded, local days).
with ref_daily as (
  select c.asset_id, (c.ts at time zone 'Asia/Phnom_Penh')::date as day,
         sum(c.ac_power_kw) * 0.25 / (a.attrs ->> 'dc_kwp')::numeric as yield
  from clean.inverter_15min c
  join core.asset a using (asset_id)
  where a.attrs ? 'dc_kwp' and c.dq_flags & 32 = 0
  group by 1, 2, a.attrs
),
ref as (
  select percentile_cont(0.5) within group (order by yield) as yield,
         min(day) as d0, max(day) as d1
  from ref_daily where yield > 0
)
-- Median daily energy of each target site's inverters over the same days / reference yield.
select (percentile_cont(0.5) within group (order by d.energy_kwh) / ref.yield)::numeric,
       ref.d0, ref.d1, count(*)
from clean.inverter_daily d
join core.asset a using (asset_id)
cross join ref
where a.site_id = %s and d.online and d.energy_kwh > 0 and d.day between ref.d0 and ref.d1
group by ref.yield, ref.d0, ref.d1
"""


def estimate_dc_kwp(conn: psycopg.Connection, site_id: int) -> tuple[float, str] | None:
    """Per-inverter DC size for a site with energy data but no nameplate.

    Assumes the site sees similar sunlight to the reference site over the overlapping
    days, so it is approximate (rounded to 100 kWp)."""
    row = conn.execute(ESTIMATE_SQL, (site_id,)).fetchone()
    if not row or row[0] is None or row[3] < 30:
        return None
    kwp = round(float(row[0]) / 100) * 100
    return kwp, (
        f"estimated from median daily energy vs reference specific yield, "
        f"{row[1]}..{row[2]} ({row[3]} inverter-days)"
    )


def resolve_inverters(
    conn: psycopg.Connection, site_id: int, site_kwp: float | None, p: LayoutParams
) -> tuple[list[InverterSpec], dict[str, dict]]:
    """Inverters for a site plus extra attrs to store for each one."""
    rows = conn.execute(
        "select code, attrs from core.asset where site_id = %s and asset_type = 'inverter'"
        " and not coalesce((attrs ->> 'generated')::boolean, false) order by code",
        (site_id,),
    ).fetchall()
    extra: dict[str, dict] = {}

    if rows:
        missing = [c for c, a in rows if "dc_kwp" not in a]
        est = estimate_dc_kwp(conn, site_id) if missing else None
        specs = []
        for code, attrs in rows:
            if "dc_kwp" in attrs:
                kwp = float(attrs["dc_kwp"])
            elif est:
                kwp = est[0]
                extra[code] = {
                    "dc_kwp_source": est[1],
                    "rated_ac_kw": round(kwp / p.dc_ac_ratio / 10) * 10,
                }
            else:
                kwp = p.default_inverter_dc_kwp
                extra[code] = {
                    "dc_kwp_source": "default (no nameplate, no reference data)",
                    "rated_ac_kw": round(kwp / p.dc_ac_ratio / 10) * 10,
                }
            specs.append(InverterSpec(code, kwp))
        return specs, extra

    cap = float(site_kwp or p.default_inverter_dc_kwp)
    n = max(1, round(cap / p.default_inverter_dc_kwp))
    kwp = cap / n
    specs = [InverterSpec(f"INV-{i:02d}", kwp) for i in range(1, n + 1)]
    for s in specs:
        extra[s.code] = {
            "generated": True,
            "model": "CI-2500",
            "rated_ac_kw": round(kwp / p.dc_ac_ratio / 10) * 10,
            "dc_kwp_source": f"site capacity {cap:.0f} kWp / {n} inverters",
        }
    return specs, extra


def write_site(
    conn: psycopg.Connection, site_id: int, layout: SiteLayout, extra: dict[str, dict]
) -> None:
    ox, oy = conn.execute(
        "select st_x(g), st_y(g) from (select st_transform(location, %s) g"
        " from core.site where site_id = %s) x",
        (UTM, site_id),
    ).fetchone()

    def geo(col: str) -> str:
        # local metres -> UTM (shift to site origin) -> WGS84
        return f"st_transform(st_translate(st_geomfromtext({col}, {UTM}), %(ox)s, %(oy)s), 4326)"

    args = {"site": site_id, "ox": ox, "oy": oy}
    codes = [a.code for a in layout.assets if a.asset_type == "inverter"]

    # 1. Clear previous generated layout (source inverters/meters are kept).
    conn.execute("update core.asset set parent_id = null where site_id = %s", (site_id,))
    conn.execute("delete from core.cable where site_id = %s", (site_id,))
    conn.execute("delete from core.site_feature where site_id = %s", (site_id,))
    conn.execute(
        "delete from core.asset where site_id = %s and (asset_type = any(%s)"
        " or (asset_type = 'inverter' and coalesce((attrs->>'generated')::boolean, false)"
        "     and code <> all(%s)))",
        (site_id, list(GENERATED_TYPES), codes),
    )

    # 2. Stage and upsert assets.
    conn.execute(
        "create temp table stg_asset (code text, asset_type text, parent_code text,"
        " attrs jsonb, wkt text) on commit drop"
    )
    with conn.cursor().copy("copy stg_asset from stdin") as cp:
        for a in layout.assets:
            attrs = {**a.attrs, **extra.get(a.code, {})}
            cp.write_row([a.code, a.asset_type, a.parent_code, json.dumps(attrs), a.geom])
    conn.execute(
        f"""
        insert into core.asset (site_id, asset_type, code, attrs, geom)
        select %(site)s, asset_type, code, attrs, {geo("wkt")} from stg_asset
        on conflict (site_id, code) do update
          set geom = excluded.geom, attrs = core.asset.attrs || excluded.attrs
        """,
        args,
    )
    conn.execute(
        """
        update core.asset a set parent_id = p.asset_id
        from stg_asset s
        join core.asset p on p.site_id = %(site)s and p.code = s.parent_code
        where a.site_id = %(site)s and a.code = s.code
        """,
        args,
    )

    # 3. Cables.
    conn.execute(
        "create temp table stg_cable (from_code text, to_code text, kind text,"
        " wkt text) on commit drop"
    )
    with conn.cursor().copy("copy stg_cable from stdin") as cp:
        for c in layout.cables:
            cp.write_row([c.from_code, c.to_code, c.kind, wkt_line(c.path)])
    conn.execute(
        f"""
        insert into core.cable (site_id, from_asset, to_asset, kind, length_m, geom)
        select %(site)s, f.asset_id, t.asset_id, s.kind,
               round(st_length(st_geomfromtext(s.wkt, {UTM}))::numeric, 1), {geo("s.wkt")}
        from stg_cable s
        join core.asset f on f.site_id = %(site)s and f.code = s.from_code
        join core.asset t on t.site_id = %(site)s and t.code = s.to_code
        """,
        args,
    )

    # 4. Site features (fence, roads, blocks).
    conn.execute(
        "create temp table stg_feature (kind text, asset_code text, wkt text) on commit drop"
    )
    with conn.cursor().copy("copy stg_feature from stdin") as cp:
        for f in layout.features:
            cp.write_row([f.kind, f.asset_code, f.geom])
    conn.execute(
        f"""
        insert into core.site_feature (site_id, kind, asset_id, geom)
        select %(site)s, s.kind, a.asset_id, {geo("s.wkt")}
        from stg_feature s
        left join core.asset a on a.site_id = %(site)s and a.code = s.asset_code
        """,
        args,
    )


def run(
    site_codes: list[str] | None = None, dsn: str | None = None, params: LayoutParams | None = None
) -> dict[str, dict]:
    p = params or LayoutParams()
    dsn = dsn or get_settings().dsn
    out: dict[str, dict] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        sites = conn.execute(
            "select site_id, site_code, capacity_dc_kwp from core.site"
            " where %s::text[] is null or site_code = any(%s) order by site_code",
            (site_codes, site_codes),
        ).fetchall()
        for site_id, code, kwp in sites:
            with conn.transaction():
                specs, extra = resolve_inverters(conn, site_id, kwp, p)
                has_meter = conn.execute(
                    "select exists (select 1 from core.asset where site_id = %s"
                    " and code = 'MTR-01')",
                    (site_id,),
                ).fetchone()[0]
                if not has_meter:  # no meter in the source data: synthetic one
                    extra["MTR-01"] = {"generated": True}
                layout = plan_site(specs, p)
                write_site(conn, site_id, layout, extra)
                total_kwp = round(sum(s.dc_kwp for s in specs), 1)
                if kwp is None:
                    conn.execute(
                        "update core.site set capacity_dc_kwp = %s where site_id = %s",
                        (total_kwp, site_id),
                    )
                stats = {**layout.stats(), "dc_kwp": total_kwp}
                conn.execute(
                    """
                    insert into core.layout_run (site_id, version, params, stats)
                    values (%s, %s, %s, %s)
                    on conflict (site_id) do update set version = excluded.version,
                      params = excluded.params, stats = excluded.stats, generated_at = now()
                    """,
                    (site_id, layout_version(specs, p), json.dumps(asdict(p)), json.dumps(stats)),
                )
                out[code] = stats
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sites", nargs="*", help="site codes (default: all)")
    args = ap.parse_args()
    for code, s in run(args.sites or None).items():
        log.info(
            "%s  %5.1f MWp  %2d inv  %4d tables  %5d strings  %3d combiners  %4.0f x %4.0f m",
            code,
            s["dc_kwp"] / 1000,
            s.get("inverter", 0),
            s.get("table", 0),
            s.get("string", 0),
            s.get("combiner", 0),
            s["width_m"],
            s["height_m"],
        )


if __name__ == "__main__":
    main()
