"""Run the SQL transforms: db/sql/<layer>/*.sql in filename order.

Each layer runs in a single transaction, so a failure leaves that layer exactly as it was.
Layers run in LAYERS order; `mart` is skipped until it has files.

Usage:  uv run python -m jobs.transform [layer ...]
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import psycopg

from app.config import REPO_DIR, get_settings

log = logging.getLogger("transform")

SQL_DIR = REPO_DIR / "db" / "sql"
LAYERS = ["core", "clean", "mart"]


def layer_files(layer: str, sql_dir: Path = SQL_DIR) -> list[Path]:
    return sorted((sql_dir / layer).glob("*.sql"))


def run(
    layers: list[str] | None = None, dsn: str | None = None, sql_dir: Path = SQL_DIR
) -> dict[str, int]:
    """Run the given layers (default: all). Returns {layer: files_run}."""
    dsn = dsn or get_settings().dsn
    selected = [layer for layer in LAYERS if not layers or layer in layers]
    done: dict[str, int] = {}
    with psycopg.connect(dsn) as conn:
        for layer in selected:
            files = layer_files(layer, sql_dir)
            if not files:
                continue
            with conn.transaction():
                for f in files:
                    t0 = time.perf_counter()
                    try:
                        # No parameters -> simple query protocol, so a file may hold
                        # several statements.
                        conn.execute(f.read_text())
                    except psycopg.Error as e:
                        raise RuntimeError(f"{layer}/{f.name} failed: {e}") from e
                    log.info("%-6s %-32s %6.2fs", layer, f.name, time.perf_counter() - t0)
            done[layer] = len(files)
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("layers", nargs="*", help=f"any of {LAYERS} (default: all)")
    args = p.parse_args()
    unknown = set(args.layers) - set(LAYERS)
    if unknown:
        p.error(f"unknown layer(s): {sorted(unknown)}")
    run(args.layers or None)


if __name__ == "__main__":
    main()
