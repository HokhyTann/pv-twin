"""Tiny source CSVs with planted problems and known answers.

Every planted problem is listed in EXPECTED so tests can assert exact findings.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from pathlib import Path


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_low(d: Path) -> None:
    rows = [
        # PV-01, 80 MWp: line 1-5
        ["2026-01-01", "PV-01", 80.0, 360.0, 5.6, 99.9],
        ["2026-01-02", "PV-01", 80.0, 370.0, 5.8, 99.8],
        ["2026-01-02", "PV-01", 80.0, 370.0, 5.8, 99.8],  # line 3: duplicate of 2
        ["2026-01-03", "PV-01", 80.0, -5.0, 5.7, 99.0],  # line 4: negative energy
        ["2026-01-04", "PV-01", 80.0, "", 5.5, 99.5],  # line 5: missing energy
        # PV-02, file says 50 MWp but registry says 60: line 6-9
        ["2026-01-01", "PV-02", 50.0, 250.0, 0.0, 99.0],  # line 6: irradiation zero
        ["2026-01-02", "PV-02", 50.0, 400.0, 5.0, 99.0],  # line 7: PR = 400/(60*5) > 1
        ["2026-01-03", "PV-02", 50.0, 260.0, 5.5, 101.0],  # line 8: availability > 100
        # 2026-01-04 missing for PV-02 (calendar gap is only inside min..max, so add 01-05)
        ["2026-01-05", "PV-02", 50.0, 255.0, 5.4, 99.0],  # line 9
    ]
    _write(
        d / "low_site_daily.csv",
        ["date", "site", "capacity_mwp", "energy_mwh", "irradiation_kwh_m2", "availability_pct"],
        rows,
    )


def write_medium(d: Path) -> None:
    rows = [
        ["2025-01-01", 280.0, 5.8, 31.0, 0],
        ["2025-01-02", 290.0, 6.0, 32.0, 1],
        ["2025-01-03", 275.0, 5.7, 30.5, 0],
    ]
    _write(
        d / "medium_site_daily.csv",
        ["date", "energy_mwh", "irradiation_kwh_m2", "ambient_max_c", "panel_cleaning"],
        rows,
    )


def write_high(d: Path) -> None:
    """One inverter, 14 days. Outage on day 10-11; label 1 on days 3-9.
    Day 2 is wrongly labelled 1 (label_inconsistent). Ticket on day 9."""
    start = datetime(2025, 7, 1)
    rows = []
    for i in range(14):
        day = (start + timedelta(days=i)).date().isoformat()
        online = 0 if i in (9, 10) else 1
        label = 1 if 2 <= i <= 8 else 0
        if i == 1:
            label = 1  # wrong label
        ticket = 1 if i == 8 else 0
        if online:
            rows.append(
                [
                    day,
                    "PV-01",
                    "INV-01",
                    1,
                    9000,
                    98.1,
                    55.0,
                    3000,
                    0,
                    33.0 + (i % 2),
                    ticket,
                    label,
                ]
            )
        else:
            rows.append([day, "PV-01", "INV-01", 0, 0, "", "", "", "", 33.0, ticket, label])
    # second inverter on the same site so ambient varies within a site-day
    for i in range(14):
        day = (start + timedelta(days=i)).date().isoformat()
        rows.append([day, "PV-01", "INV-02", 1, 9100, 98.2, 54.0, 3010, 0, 35.5, 0, 0])
    _write(
        d / "high_inverter_daily.csv",
        [
            "date",
            "site",
            "inverter_id",
            "online",
            "energy_kwh",
            "efficiency_pct",
            "igbt_max_temp_c",
            "fan_speed_rpm",
            "alarm_count",
            "ambient_max_c",
            "ticket_flag",
            "failure_next_7d",
        ],
        rows,
    )


SCADA_DAYS = 4
SCALED_INVERTER = "INV-03"  # reads 1.25x on local days 2-4 (3 days -> scaling_suspect)


def write_expert(d: Path) -> None:
    invs = ["INV-01", "INV-02", "INV-03"]
    _write(
        d / "expert_asset_register.csv",
        ["inverter_id", "model", "rated_ac_kw", "dc_capacity_kwp", "commissioned"],
        [[i, "CI-2500", 2500, 3000, "2022-11-15"] for i in invs],
    )

    # Local days 2026-01-01..04 = UTC 2025-12-31 17:00 .. 2026-01-04 16:45.
    t0 = datetime(2025, 12, 31, 17, 0)
    rows = []
    daily_local_kwh = [0.0] * SCADA_DAYS
    for k in range(SCADA_DAYS * 96):
        ts = t0 + timedelta(minutes=15 * k)
        local = ts + timedelta(hours=7)
        h = local.hour + local.minute / 60
        base = 2000 * math.sin(math.pi * (h - 6) / 12) if 6 <= h <= 18 else 0.0
        day_idx = k // 96
        for inv in invs:
            p = base
            if inv == SCALED_INVERTER and day_idx >= 1:
                p = base * 1.25
            if inv == "INV-02" and k == 50:
                p = -10.0  # negative power
            if inv == "INV-01" and k == 60:
                continue  # missing interval
            rows.append([ts.strftime("%Y-%m-%d %H:%M"), inv, round(p, 1)])
            if inv == "INV-01":
                daily_local_kwh[day_idx] += max(base, 0) * 0.25
    _write(d / "expert_scada_15min.csv", ["timestamp", "inverter_id", "ac_power_kw"], rows)

    meter = []
    for i in range(SCADA_DAYS):
        day = (datetime(2026, 1, 1) + timedelta(days=i)).date().isoformat()
        kwh = 0 if i == 2 else round(daily_local_kwh[i] * 3 * 0.98)  # day 3: meter zero
        meter.append([day, kwh])
    _write(d / "expert_meter_daily.csv", ["date", "export_kwh"], meter)

    _write(
        d / "expert_maintenance_log.csv",
        ["date", "asset", "note"],
        [
            ["2026-01-02", "ALL", "Panel cleaning, blocks 1-5"],
            ["2026-01-03", "INV-03", "Firmware update v2.3 -> v2.4"],
            ["2026-01-03", "METER", "Annual meter test, no fault"],
            ["2026-01-04", "INV-02", "DC isolator tripped, reset next morning"],
        ],
    )


def write_all(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    write_low(d)
    write_medium(d)
    write_high(d)
    write_expert(d)
    return d
