"""Load source CSVs into raw.* exactly as they are.

- Every column is stored as text; typing and validation happen in clean.*.
- `_row` is the 1-based data line number in the source file (header = line 0),
  so any clean/DQ finding can point back to the exact CSV line.
- Idempotent: each table is dropped and recreated per load. A file whose SHA-256
  matches its last successful load is skipped unless --force is given.

Usage:  uv run python -m jobs.ingest [--force] [--data-dir PATH] [name ...]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from app.config import get_settings

log = logging.getLogger("ingest")

# source file -> raw table name
SOURCES: dict[str, str] = {
    "low_site_daily.csv": "low_site_daily",
    "medium_site_daily.csv": "medium_site_daily",
    "high_inverter_daily.csv": "high_inverter_daily",
    "expert_scada_15min.csv": "expert_scada_15min",
    "expert_meter_daily.csv": "expert_meter_daily",
    "expert_asset_register.csv": "expert_asset_register",
    "expert_maintenance_log.csv": "expert_maintenance_log",
}

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass
class LoadResult:
    file_name: str
    table: str
    rows: int
    skipped: bool


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _column_names(header: list[str]) -> list[str]:
    cols = [c.strip().lower() for c in header]
    for c in cols:
        if not _IDENT.match(c) or c.startswith("_"):
            raise ValueError(f"unsupported column name {c!r}")
    if len(set(cols)) != len(cols):
        raise ValueError(f"duplicate column names in header: {cols}")
    return cols


def load_file(conn: psycopg.Connection, path: Path, table: str, force: bool = False) -> LoadResult:
    digest = sha256_of(path)
    if not force:
        last = conn.execute(
            "select sha256 from raw.load_log where table_name = %s order by load_id desc limit 1",
            (table,),
        ).fetchone()
        exists = conn.execute("select to_regclass(%s)", (f"raw.{table}",)).fetchone()[0]
        if last and last[0] == digest and exists:
            return LoadResult(path.name, table, 0, skipped=True)

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        cols = _column_names(next(reader))
        ident = sql.Identifier("raw", table)

        conn.execute(sql.SQL("drop table if exists {}").format(ident))
        conn.execute(
            sql.SQL("create table {} (_row integer primary key, {})").format(
                ident,
                sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in cols),
            )
        )

        copy_stmt = sql.SQL("copy {} ({}) from stdin").format(
            ident, sql.SQL(", ").join(map(sql.Identifier, ["_row", *cols]))
        )
        n = 0
        with conn.cursor().copy(copy_stmt) as cp:
            for n, rec in enumerate(reader, start=1):
                if len(rec) != len(cols):
                    # Keep ragged lines visible to the clean layer instead of failing the load.
                    rec = (rec + [None] * len(cols))[: len(cols)]
                    log.warning("%s line %d: expected %d fields", path.name, n, len(cols))
                cp.write_row([n, *[(v if v != "" else None) for v in rec]])

    conn.execute(
        "insert into raw.load_log (file_name, table_name, sha256, row_count, columns) "
        "values (%s, %s, %s, %s, %s)",
        (path.name, table, digest, n, cols),
    )
    return LoadResult(path.name, table, n, skipped=False)


def run(
    data_dir: Path, names: list[str] | None = None, force: bool = False, dsn: str | None = None
) -> list[LoadResult]:
    dsn = dsn or get_settings().dsn
    selected = {k: v for k, v in SOURCES.items() if not names or k in names or v in names}
    results = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        for file_name, table in selected.items():
            path = data_dir / file_name
            if not path.exists():
                raise FileNotFoundError(path)
            with conn.transaction():
                results.append(load_file(conn, path, table, force=force))
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("names", nargs="*", help="file or table names (default: all)")
    p.add_argument("--force", action="store_true", help="reload even if unchanged")
    p.add_argument("--data-dir", type=Path, default=get_settings().data_path)
    args = p.parse_args()

    for r in run(args.data_dir, args.names, args.force):
        status = "unchanged, skipped" if r.skipped else f"{r.rows:>7,} rows"
        log.info("raw.%-24s %s", r.table, status)


if __name__ == "__main__":
    main()
