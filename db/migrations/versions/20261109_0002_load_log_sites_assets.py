"""Raw load log, site registry (seeded) and asset table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One unique code per site. Source files reuse codes (PV-01 means different sites in the
# low and high datasets), so every source row is mapped through (source_dataset, source_code).
# Locations are fictional points in Cambodia, used only to place sites on the fleet map.
# fmt: off
SITES = [
    # code,     name,                       dc_kwp, lat,    lon,     dataset,  source_code
    ("KH-A01", "Kampong Speu Solar A1",    80000, 11.452, 104.518, "low", "PV-01"),
    ("KH-A02", "Svay Rieng Solar A2",      60000, 11.082, 106.121, "low", "PV-02"),
    ("KH-A03", "Kampong Chhnang Solar A3", 40000, 12.203, 104.597, "low", "PV-03"),
    ("KH-B01", "Pursat Solar B1",          60000, 12.498, 103.947, "medium", ""),
    ("KH-C01", "Battambang Solar C1",      None,  13.052, 103.104, "high", "PV-01"),
    ("KH-C02", "Banteay Meanchey Solar C2", None, 13.598, 102.951, "high", "PV-02"),
    ("KH-C03", "Takeo Solar C3",           None,  10.948, 104.801, "high", "PV-03"),
    ("KH-C04", "Kampot Solar C4",          None,  10.703, 104.252, "high", "PV-04"),
    ("KH-D06", "Kandal Solar PV-06",       30000, 11.301, 104.698, "expert", "PV-06"),
]
# fmt: on


def _sql_value(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def upgrade() -> None:
    op.execute(
        """
        create table raw.load_log (
            load_id     bigserial primary key,
            file_name   text not null,
            table_name  text not null,
            sha256      text not null,
            row_count   bigint not null,
            columns     text[] not null,
            loaded_at   timestamptz not null default now()
        );
        comment on table raw.load_log is 'One row per CSV load into raw.*';
        """
    )

    op.execute(
        """
        create table core.site (
            site_id         serial primary key,
            site_code       text not null unique,
            name            text not null,
            capacity_dc_kwp numeric,
            tz              text not null default 'Asia/Phnom_Penh',
            location        geometry(Point, 4326),
            source_dataset  text not null,
            source_code     text not null default '',
            unique (source_dataset, source_code)
        );
        comment on column core.site.source_code is
            'Site code used in the source file ('''' when the file has no site column)';

        create table core.asset (
            asset_id    bigserial primary key,
            site_id     int not null references core.site on delete cascade,
            parent_id   bigint references core.asset on delete cascade,
            asset_type  text not null check (asset_type in (
                            'substation', 'meter', 'transformer', 'inverter',
                            'combiner', 'string', 'table')),
            code        text not null,
            attrs       jsonb not null default '{}',
            geom        geometry(Geometry, 4326),
            unique (site_id, code)
        );
        create index asset_geom_gix on core.asset using gist (geom);
        create index asset_site_type_ix on core.asset (site_id, asset_type);
        create index asset_parent_ix on core.asset (parent_id);
        """
    )

    rows = ",\n".join(
        f"({_sql_value(code)}, {_sql_value(name)}, {_sql_value(kwp)}, "
        f"st_setsrid(st_makepoint({lon}, {lat}), 4326), {_sql_value(ds)}, {_sql_value(src)})"
        for code, name, kwp, lat, lon, ds, src in SITES
    )
    op.execute(
        "insert into core.site "
        "(site_code, name, capacity_dc_kwp, location, source_dataset, source_code) values\n" + rows
    )


def downgrade() -> None:
    op.execute("drop table if exists core.asset")
    op.execute("drop table if exists core.site")
    op.execute("drop table if exists raw.load_log")
