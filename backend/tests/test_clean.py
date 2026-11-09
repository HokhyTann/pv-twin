"""Clean-layer tests against the planted problems in tests/fixture_data.py."""

from __future__ import annotations

from pathlib import Path

import psycopg

from jobs import ingest, transform


def issues(db: psycopg.Connection, table: str) -> set[tuple[str, int | None]]:
    rows = db.execute(
        "select rule, source_row from clean.dq_issue where source_table = %s", (table,)
    ).fetchall()
    return set(rows)


def scalar(db: psycopg.Connection, q: str, *params: object) -> object:
    return db.execute(q, params).fetchone()[0]


# ---- site daily (low + medium) ------------------------------------------------------------


def test_low_site_issues_found_exactly(db: psycopg.Connection) -> None:
    found = {(r, n) for r, n in issues(db, "low_site_daily") if r != "missing_day"}
    assert found == {
        ("duplicate_row", 3),
        ("negative_value", 4),
        ("missing_value", 5),
        ("irradiation_zero", 6),
        ("pr_impossible", 7),
        ("out_of_range", 8),
        # file capacity 50 MWp vs registry 60 MWp on every PV-02 line
        ("capacity_mismatch", 6),
        ("capacity_mismatch", 7),
        ("capacity_mismatch", 8),
        ("capacity_mismatch", 9),
    }


def test_low_site_calendar_gap(db: psycopg.Connection) -> None:
    rows = db.execute(
        "select entity, (period_start at time zone 'Asia/Phnom_Penh')::date::text "
        "from clean.dq_issue where source_table = 'low_site_daily' and rule = 'missing_day'"
    ).fetchall()
    assert rows == [("KH-A02", "2026-01-04")]


def test_impossible_values_nulled_but_flagged(db: psycopg.Connection) -> None:
    neg = db.execute(
        "select energy_mwh, dq_flags from clean.site_daily where source_table = 'low_site_daily'"
        " and source_row = 4"
    ).fetchone()
    assert neg == (None, 2)
    irr = db.execute(
        "select irradiation_kwh_m2, energy_mwh, clean.dq_rules_of(dq_flags) from clean.site_daily"
        " where source_table = 'low_site_daily' and source_row = 6"
    ).fetchone()
    assert irr[0] is None and irr[1] == 250
    assert set(irr[2]) == {"irradiation_zero", "capacity_mismatch"}


def test_site_daily_row_counts(db: psycopg.Connection) -> None:
    # 9 low lines - 1 duplicate + 3 medium lines
    assert scalar(db, "select count(*) from clean.site_daily") == 11
    assert scalar(db, "select count(*) from clean.site_daily where panel_cleaning") == 1


# ---- inverter daily (high) ------------------------------------------------------------------


def test_label_check_finds_only_the_planted_error(db: psycopg.Connection) -> None:
    rows = db.execute(
        "select entity, period_start::date::text from clean.dq_issue"
        " where rule = 'label_inconsistent'"
    ).fetchall()
    assert rows == [("KH-C01/INV-01", "2025-07-02")]


def test_offline_days_are_not_missing_values(db: psycopg.Connection) -> None:
    assert scalar(db, "select count(*) from clean.inverter_daily where not online") == 2
    assert ("missing_value", None) not in issues(db, "high_inverter_daily")
    assert not any(r == "missing_value" for r, _ in issues(db, "high_inverter_daily"))


def test_dataset_notes_for_high(db: psycopg.Connection) -> None:
    rules = {r for r, _ in issues(db, "high_inverter_daily")}
    assert {"label_leakage", "ambient_not_site_level"} <= rules


# ---- SCADA, meter, events (expert) ----------------------------------------------------------


def test_scada_stored_in_utc_and_notes(db: psycopg.Connection) -> None:
    first = scalar(db, "select min(ts) at time zone 'Asia/Phnom_Penh' from clean.inverter_15min")
    assert str(first) == "2026-01-01 00:00:00"
    assert ("timestamps_utc", None) in issues(db, "expert_scada_15min")


def test_scaling_flags_exactly_the_scaled_days(db: psycopg.Connection) -> None:
    row = db.execute(
        "select entity, n_rows, (period_start at time zone 'Asia/Phnom_Penh')::date::text"
        " from clean.dq_issue where rule = 'scaling_suspect'"
    ).fetchall()
    assert row == [("INV-03", 288, "2026-01-02")]
    flagged = db.execute(
        "select a.code, count(*) from clean.inverter_15min c join core.asset a using (asset_id)"
        " where c.dq_flags & 32 <> 0 group by 1"
    ).fetchall()
    assert flagged == [("INV-03", 288)]


def test_scada_point_issues(db: psycopg.Connection) -> None:
    by_rule = dict(
        db.execute(
            "select rule || ':' || entity, n_rows from clean.dq_issue"
            " where source_table = 'expert_scada_15min' and severity <> 'info'"
            "   and rule <> 'scaling_suspect'"
        ).fetchall()
    )
    assert by_rule == {"negative_value:INV-02": 1, "missing_interval:INV-01": 1}
    assert scalar(db, "select count(*) from clean.inverter_15min where ac_power_kw < 0") == 0


def test_meter_zero_is_missing_not_zero(db: psycopg.Connection) -> None:
    row = db.execute(
        "select export_kwh, dq_flags from clean.meter_daily where day = '2026-01-03'"
    ).fetchone()
    assert row == (None, 64)
    assert scalar(db, "select count(*) from clean.meter_daily where export_kwh is not null") == 3


def test_event_categories(db: psycopg.Connection) -> None:
    rows = db.execute("select scope, category from clean.event order by source_row").fetchall()
    assert rows == [
        ("ALL", "cleaning"),
        ("INV-03", "firmware"),
        ("METER", "meter"),
        ("INV-02", "trip"),
    ]
    meter_asset = scalar(
        db,
        "select a.code from clean.event e join core.asset a using (asset_id)"
        " where e.scope = 'METER'",
    )
    assert meter_asset == "MTR-01"


# ---- pipeline behaviour -------------------------------------------------------------------


def test_transform_is_idempotent(loaded_db: str) -> None:
    q = (
        "select (select count(*) from clean.site_daily), (select count(*) from clean.dq_issue),"
        " (select count(*) from clean.inverter_15min), (select count(*) from core.asset)"
    )
    with psycopg.connect(loaded_db) as conn:
        before = conn.execute(q).fetchone()
    transform.run(["core", "clean"], dsn=loaded_db)
    with psycopg.connect(loaded_db) as conn:
        assert conn.execute(q).fetchone() == before


def test_ingest_skips_unchanged_files(loaded_db: str, fixture_dir: Path) -> None:
    results = ingest.run(fixture_dir, dsn=loaded_db)
    assert all(r.skipped for r in results)
