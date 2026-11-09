from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pv:pv@localhost:5432/pv"
    data_dir: Path = REPO_DIR / "data" / "source"
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def data_path(self) -> Path:
        """DATA_DIR may be relative to backend/; resolve it to an absolute path."""
        p = self.data_dir
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
