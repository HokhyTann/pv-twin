"""Clean layer: typed tables, data-quality rules and issue log

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09

Conventions
- Clean tables are fully rebuilt by db/sql/clean/*.sql (jobs.transform).
- Bad values are never silently dropped. A value that is physically impossible is set to
  NULL and the matching bit is set in `dq_flags`; the original stays in raw.* (`source_row`).
- Duplicates are removed (first line kept) and logged in clean.dq_issue.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
# bit, rule, severity, description, action taken in clean.*
DQ_RULES = [
    (1,   "missing_value",      "warn",  "A required measurement is empty",
          "kept as NULL; excluded from sums that need it"),
    (2,   "negative_value",     "error", "Energy or power below zero",
          "value set to NULL"),
    (4,   "irradiation_zero",   "error", "Irradiation is 0 while the site exported energy",
          "irradiation set to NULL; day excluded from PR"),
    (8,   "pr_impossible",      "error", "Performance ratio above 1.0 (more energy than the "
                                         "sunlight allows)",
          "energy set to NULL"),
    (16,  "out_of_range",       "warn",  "Value outside its physical range (power above rated "
                                         "AC, efficiency or availability outside 0-100 %)",
          "value kept and flagged"),
    (32,  "scaling_suspect",    "warn",  "Inverter reads a steady multiple of its peers for 3 or "
                                         "more days: likely a scaling or configuration error",
          "value kept and flagged; correct it in analysis, not in clean"),
    (64,  "meter_zero_missing", "error", "Meter reads 0 while SCADA shows normal production",
          "treated as a missing reading: set to NULL"),
    (128, "capacity_mismatch",  "warn",  "Capacity in the file differs from the site registry",
          "registry capacity used for PR"),
]
# fmt: on


def upgrade() -> None:
    op.execute(
        """
        create table clean.dq_rule (
            bit         int primary key check (bit > 0 and (bit & (bit - 1)) = 0),
            rule        text not null unique,
            severity    text not null check (severity in ('info', 'warn', 'error')),
            description text not null,
            action      text not null
        );

        create table clean.dq_issue (
            issue_id     bigserial primary key,
            source_table text not null,          -- raw table the issue was found in
            rule         text not null,          -- dq_rule.rule, or a dataset-level note
            severity     text not null check (severity in ('info', 'warn', 'error')),
            source_row   int,                    -- raw._row (NULL for dataset-level issues)
            entity       text,                   -- site_code or asset code
            period_start timestamptz,
            period_end   timestamptz,
            n_rows       int not null default 1,
            detail       text not null,
            action       text not null
        );
        create index dq_issue_table_ix on clean.dq_issue (source_table, rule);

        -- Site-level daily data (low + medium datasets)
        create table clean.site_daily (
            site_id             int not null references core.site,
            day                 date not null,
            capacity_dc_kwp     numeric,         -- as reported by the file (may differ)
            energy_mwh          numeric,
            irradiation_kwh_m2  numeric,
            ambient_max_c       numeric,
            availability_pct    numeric,
            panel_cleaning      boolean,
            dq_flags            int not null default 0,
            source_table        text not null,
            source_row          int not null,
            primary key (site_id, day)
        );

        -- Inverter-level daily data (high dataset)
        create table clean.inverter_daily (
            asset_id         bigint not null references core.asset on delete cascade,
            day              date not null,
            online           boolean not null,
            energy_kwh       numeric,
            efficiency_pct   numeric,
            igbt_max_temp_c  numeric,
            fan_speed_rpm    numeric,
            alarm_count      int,
            ambient_max_c    numeric,
            ticket_flag      boolean,
            failure_next_7d  boolean,
            dq_flags         int not null default 0,
            source_row       int not null,
            primary key (asset_id, day)
        );
        comment on column clean.inverter_daily.ticket_flag is
            'LEAKAGE: tickets are entered after the repair visit. Never use as a model feature.';
        comment on column clean.inverter_daily.failure_next_7d is
            'Label: inverter fails within the next 1-7 days.';

        -- Inverter 15-minute SCADA (expert dataset). ts is the interval start in UTC.
        create table clean.inverter_15min (
            asset_id    bigint not null references core.asset on delete cascade,
            ts          timestamptz not null,
            ac_power_kw real,
            dq_flags    int not null default 0,
            primary key (asset_id, ts)
        );
        select create_hypertable('clean.inverter_15min', by_range('ts', interval '7 days'));

        -- Revenue meter daily export (expert dataset). day is the local (Asia/Phnom_Penh) date.
        create table clean.meter_daily (
            asset_id    bigint not null references core.asset on delete cascade,
            day         date not null,
            export_kwh  numeric,
            dq_flags    int not null default 0,
            source_row  int not null,
            primary key (asset_id, day)
        );

        -- Maintenance log events (expert dataset)
        create table clean.event (
            event_id    bigserial primary key,
            site_id     int not null references core.site,
            asset_id    bigint references core.asset on delete set null,
            scope       text not null,           -- asset code, or ALL / COMMS / METER
            day         date not null,
            category    text not null,
            note        text not null,
            source_row  int not null
        );
        create index event_site_day_ix on clean.event (site_id, day);
        """
    )

    def q(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"

    values = ",\n".join(
        f"({bit}, {q(rule)}, {q(sev)}, {q(desc)}, {q(action)})"
        for bit, rule, sev, desc, action in DQ_RULES
    )
    op.execute(
        "insert into clean.dq_rule (bit, rule, severity, description, action) values\n" + values
    )


def downgrade() -> None:
    for t in [
        "event",
        "meter_daily",
        "inverter_15min",
        "inverter_daily",
        "site_daily",
        "dq_issue",
        "dq_rule",
    ]:
        op.execute(f"drop table if exists clean.{t} cascade")
