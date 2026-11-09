from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_conn() -> Iterator[Connection]:
    """FastAPI dependency: one connection per request (SQLAlchemy Core, no ORM)."""
    with get_engine().connect() as conn:
        yield conn
