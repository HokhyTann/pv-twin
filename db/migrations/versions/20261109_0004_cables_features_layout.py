"""Cable network, site features (fence, roads, blocks) and layout runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09

Also changes core.asset.parent_id to ON DELETE SET NULL. The layout generator deletes and
recreates generated assets (transformers, combiners, tables, strings); with CASCADE that
would have deleted the source inverters too, and through them all clean.* telemetry.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        alter table core.asset drop constraint asset_parent_id_fkey;
        alter table core.asset add constraint asset_parent_id_fkey
            foreign key (parent_id) references core.asset on delete set null;

        create table core.cable (
            cable_id    bigserial primary key,
            site_id     int not null references core.site on delete cascade,
            from_asset  bigint not null references core.asset on delete cascade,
            to_asset    bigint not null references core.asset on delete cascade,
            kind        text not null check (kind in
                            ('dc_string', 'dc_main', 'ac_lv', 'mv', 'comms')),
            length_m    numeric not null,
            geom        geometry(LineString, 4326) not null
        );
        create index cable_site_kind_ix on core.cable (site_id, kind);
        create index cable_from_ix on core.cable (from_asset);
        create index cable_to_ix on core.cable (to_asset);
        create index cable_geom_gix on core.cable using gist (geom);

        create table core.site_feature (
            feature_id  bigserial primary key,
            site_id     int not null references core.site on delete cascade,
            kind        text not null check (kind in ('fence', 'road', 'block')),
            asset_id    bigint references core.asset on delete cascade,  -- block -> inverter
            geom        geometry(Geometry, 4326) not null
        );
        create index site_feature_site_kind_ix on core.site_feature (site_id, kind);
        create index site_feature_geom_gix on core.site_feature using gist (geom);

        create table core.layout_run (
            site_id      int primary key references core.site on delete cascade,
            version      text not null,          -- hash of params + inputs (use as ETag)
            params       jsonb not null,
            stats        jsonb not null,
            generated_at timestamptz not null default now()
        );
        comment on table core.layout_run is
            'Latest generated layout per site. Geometry is synthetic, built by jobs.layout_gen.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists core.layout_run;
        drop table if exists core.site_feature;
        drop table if exists core.cable;
        alter table core.asset drop constraint asset_parent_id_fkey;
        alter table core.asset add constraint asset_parent_id_fkey
            foreign key (parent_id) references core.asset on delete cascade;
        """
    )
