"""Test database: a throwaway `pv_test` database on the dev Postgres server.

Created fresh per test session, migrated to head, loaded with the fixture CSVs,
transformed, and dropped at the end. Tests that need it are skipped if Postgres
is not reachable (start it with `make up`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.config import BACKEND_DIR, get_settings

TEST_DB = "pv_test"


def _url_for(db: str) -> str:
    """SQLAlchemy URL (postgresql+psycopg://...) for another database on the same server."""
    url = make_url(get_settings().database_url).set(database=db)
    return url.render_as_string(hide_password=False)


def _dsn_for(db: str) -> str:
    """Plain libpq URL for psycopg."""
    return _url_for(db).replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def test_dsn() -> Iterator[str]:
    admin = _dsn_for("postgres")
    try:
        conn = psycopg.connect(admin, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable; run `make up`")
    with conn:
        conn.execute(f"drop database if exists {TEST_DB} with (force)")
        conn.execute(f"create database {TEST_DB}")

    _migrate(_url_for(TEST_DB))
    yield _dsn_for(TEST_DB)

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"drop database if exists {TEST_DB} with (force)")


def _migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tests.fixture_data import write_all

    return write_all(tmp_path_factory.mktemp("source"))


@pytest.fixture(scope="session")
def loaded_db(test_dsn: str, fixture_dir: Path) -> str:
    """Fixture CSVs ingested and transformed (core + clean)."""
    from jobs import ingest, transform

    ingest.run(fixture_dir, dsn=test_dsn, force=True)
    transform.run(["core", "clean"], dsn=test_dsn)
    return test_dsn


@pytest.fixture
def db(loaded_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(loaded_db) as conn:
        yield conn
