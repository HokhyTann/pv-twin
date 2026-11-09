from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_engine

router = APIRouter(tags=["health"])

EXPECTED_SCHEMAS = ["raw", "core", "clean", "mart", "app"]


class Health(BaseModel):
    api: str
    db: str
    postgres: str | None = None
    extensions: dict[str, str] = {}
    schemas: list[str] = []
    migration: str | None = None


@router.get("/health", response_model=Health)
def health() -> Health:
    """Liveness of API + DB. Never raises: DB problems are reported in the body."""
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("show server_version")).scalar_one()
            exts = dict(
                conn.execute(
                    text(
                        "select extname, extversion from pg_extension "
                        "where extname in ('postgis', 'timescaledb')"
                    )
                ).all()
            )
            schemas = list(
                conn.execute(
                    text(
                        "select schema_name from information_schema.schemata "
                        "where schema_name = any(:names) order by schema_name"
                    ),
                    {"names": EXPECTED_SCHEMAS},
                ).scalars()
            )
            migration = None
            if conn.execute(text("select to_regclass('public.alembic_version')")).scalar():
                migration = conn.execute(text("select version_num from alembic_version")).scalar()
    except SQLAlchemyError as e:
        return Health(api="ok", db=f"error: {e.__class__.__name__}")
    return Health(
        api="ok",
        db="ok",
        postgres=version,
        extensions=exts,
        schemas=schemas,
        migration=migration,
    )
