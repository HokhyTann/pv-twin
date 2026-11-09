"""Extensions and layered schemas (raw, core, clean, mart, app)

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = {
    "raw": "Exact CSV copies (text columns + load metadata). Written by jobs.ingest.",
    "core": "Site registry, asset tree, geometry and cable network.",
    "clean": "Typed, deduplicated, quality-flagged data and telemetry hypertables.",
    "mart": "Read models for the UI: KPIs, predictions, alerts.",
    "app": "User-created data: alert acknowledgements, notes, saved views.",
}


def upgrade() -> None:
    op.execute("create extension if not exists postgis")
    op.execute("create extension if not exists timescaledb")
    for name, comment in SCHEMAS.items():
        op.execute(f"create schema if not exists {name}")
        op.execute(f"comment on schema {name} is '{comment}'")


def downgrade() -> None:
    for name in reversed(SCHEMAS):
        op.execute(f"drop schema if exists {name} cascade")
    # Extensions are left installed on purpose; dropping them is rarely wanted.
