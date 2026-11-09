"""Layout tests: the pure planner (no DB) and the DB writer (pv_test)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import replace
from itertools import combinations

import psycopg
import pytest

from jobs import layout_gen, transform
from jobs.layout_plan import InverterSpec, LayoutParams, layout_version, plan_site

P = LayoutParams()
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def rect(wkt: str) -> tuple[float, float, float, float]:
    xs_ys = [float(v) for v in NUM.findall(wkt)]
    xs, ys = xs_ys[0::2], xs_ys[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ---- planner (pure) -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def three() -> object:
    """Three inverters of different size -> one full station + one single-block station."""
    return plan_site(
        [InverterSpec("INV-01", 3000), InverterSpec("INV-02", 2400), InverterSpec("INV-03", 1500)]
    )


def test_table_count_matches_dc_capacity(three) -> None:
    per_inv: dict[str, int] = {}
    parent = {a.code: a.parent_code for a in three.assets}
    for a in three.assets:
        if a.asset_type == "table":
            inv = parent[a.parent_code]
            per_inv[inv] = per_inv.get(inv, 0) + 1
    assert per_inv == {
        "INV-01": round(3000 / P.table_kwp),
        "INV-02": round(2400 / P.table_kwp),
        "INV-03": round(1500 / P.table_kwp),
    }


def test_strings_and_combiner_capacity(three) -> None:
    by_type: dict[str, list] = {}
    for a in three.assets:
        by_type.setdefault(a.asset_type, []).append(a)
    assert len(by_type["string"]) == P.strings_per_table * len(by_type["table"])
    assert sum(c.attrs["n_strings"] for c in by_type["combiner"]) == len(by_type["string"])
    assert max(c.attrs["n_strings"] for c in by_type["combiner"]) <= P.strings_per_combiner


def test_tree_is_complete(three) -> None:
    by_code = {a.code: a for a in three.assets}
    assert len(by_code) == len(three.assets), "asset codes must be unique"
    for a in three.assets:
        node, hops = a, 0
        while node.parent_code is not None:
            node = by_code[node.parent_code]
            hops += 1
            assert hops < 10
        assert node.code == "SUB-01"


def test_no_overlapping_tables_or_equipment_on_tables(three) -> None:
    tables = [rect(a.geom) for a in three.assets if a.asset_type == "table"]
    assert not any(overlaps(a, b) for a, b in combinations(tables, 2))
    for a in three.assets:
        if a.asset_type in ("inverter", "transformer", "combiner"):
            x, y = (float(v) for v in NUM.findall(a.geom))
            assert not any(t[0] < x < t[2] and t[1] < y < t[3] for t in tables), a.code


def test_cables_connect_known_assets(three) -> None:
    codes = {a.code for a in three.assets}
    kinds: dict[str, int] = {}
    for c in three.cables:
        assert c.from_code in codes and c.to_code in codes
        assert len(c.path) >= 2
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    n = {
        t: sum(a.asset_type == t for a in three.assets)
        for t in ("table", "combiner", "inverter", "transformer")
    }
    assert kinds == {
        "dc_string": n["table"],
        "dc_main": n["combiner"],
        "ac_lv": n["inverter"],
        "mv": n["transformer"],
    }


def test_planner_is_deterministic_and_versioned() -> None:
    invs = [InverterSpec(f"INV-{i:02d}", 3000) for i in range(1, 6)]
    a, b = plan_site(invs), plan_site(invs)
    assert [x.geom for x in a.assets] == [x.geom for x in b.assets]
    assert layout_version(invs, P) == layout_version(invs, P)
    assert layout_version(invs, P) != layout_version(invs, replace(P, row_pitch=9.0))


def test_empty_site_rejected() -> None:
    with pytest.raises(ValueError):
        plan_site([])


# ---- DB writer --------------------------------------------------------------------------------


def counts(conn: psycopg.Connection) -> tuple:
    return conn.execute(
        "select (select count(*) from core.asset), (select count(*) from core.cable),"
        " (select count(*) from core.site_feature),"
        " (select count(*) from clean.inverter_daily), (select count(*) from clean.inverter_15min),"
        " (select count(*) from clean.meter_daily), (select count(*) from clean.event"
        "  where asset_id is not null)"
    ).fetchone()


@pytest.fixture(scope="module")
def laid_out(loaded_db: str) -> Iterator[tuple[str, dict, tuple]]:
    with psycopg.connect(loaded_db) as conn:
        source_ids = dict(
            conn.execute("select site_id || '/' || code, asset_id from core.asset").fetchall()
        )
        clean_before = counts(conn)[3:]
    layout_gen.run(dsn=loaded_db)
    yield loaded_db, source_ids, clean_before


def test_source_assets_keep_ids_and_clean_data_survives(laid_out) -> None:
    dsn, source_ids, clean_before = laid_out
    with psycopg.connect(dsn) as conn:
        now = dict(
            conn.execute(
                "select site_id || '/' || code, asset_id from core.asset"
                " where site_id || '/' || code = any(%s)",
                (list(source_ids),),
            ).fetchall()
        )
        assert now == source_ids
        assert counts(conn)[3:] == clean_before


def test_rerun_is_idempotent(laid_out) -> None:
    dsn, _, _ = laid_out
    with psycopg.connect(dsn) as conn:
        before = counts(conn)
        versions = conn.execute(
            "select site_id, version from core.layout_run order by 1"
        ).fetchall()
    layout_gen.run(dsn=dsn)
    transform.run(["core"], dsn=dsn)  # core upserts must not disturb the layout
    with psycopg.connect(dsn) as conn:
        assert counts(conn) == before
        assert (
            conn.execute("select site_id, version from core.layout_run order by 1").fetchall()
            == versions
        )
        assert (
            conn.execute(
                "select count(*) from core.asset where parent_id is null"
                " and asset_type <> 'substation'"
            ).fetchone()[0]
            == 0
        )


def test_inverter_sizes_by_source(laid_out) -> None:
    dsn, _, _ = laid_out
    with psycopg.connect(dsn) as conn:
        rows = dict(
            conn.execute(
                "select s.site_code, array_agg(distinct (a.attrs->>'dc_kwp_source')"
                "  || ' @ ' || (a.attrs->>'dc_kwp')) from core.asset a join core.site s"
                " using (site_id) where a.asset_type = 'inverter' group by 1"
            ).fetchall()
        )
        n_gen = conn.execute(
            "select count(*) from core.asset a join core.site s using (site_id)"
            " where s.site_code = 'KH-A01' and a.asset_type = 'inverter'"
        ).fetchone()[0]
    # D06: nameplate from the register, no estimate needed
    assert rows["KH-D06"] == [None]
    # C01: fixture energy (Jul 2025) does not overlap reference SCADA (Jan 2026) -> default
    assert rows["KH-C01"][0].startswith("default")
    # A01: 80 MWp / 3 MWp -> 27 generated inverters
    assert n_gen == round(80000 / 3000)


def test_geometry_in_db(laid_out) -> None:
    dsn, _, _ = laid_out
    with psycopg.connect(dsn) as conn:
        overlapping = conn.execute(
            "select count(*) from core.asset a join core.asset b on a.site_id = b.site_id"
            " and a.asset_id < b.asset_id and a.geom && b.geom"
            " and st_relate(a.geom, b.geom, '2********')"
            " where a.asset_type = 'table' and b.asset_type = 'table'"
        ).fetchone()[0]
        outside = conn.execute(
            "select count(*) from core.asset a join core.site_feature f"
            " on f.site_id = a.site_id and f.kind = 'fence'"
            " where not st_within(a.geom, f.geom)"
        ).fetchone()[0]
        bad_len = conn.execute("select count(*) from core.cable where length_m <= 0").fetchone()[0]
        srid = conn.execute(
            "select distinct st_srid(geom) from core.asset where geom is not null"
        ).fetchall()
    assert (overlapping, outside, bad_len) == (0, 0, 0)
    assert srid == [(4326,)]
