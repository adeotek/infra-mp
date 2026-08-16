"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    Values are read from environment variables prefixed with ``INFRAMP_``
    (e.g. ``INFRAMP_DATA_DIR``) and optionally from a local ``.env`` file.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="INFRAMP_", extra="ignore")

    app_name: str = "InfraMP"
    data_dir: Path = Path("data")
    secret_key: str = "change-me-in-production"
    session_cookie_name: str = "infra_mp_session"
    session_ttl_days: int = 7
    admin_username: str = "admin"
    admin_password: str = ""
    admin_display_name: str = "Administrator"
    debug: bool = False

    @property
    def database_url(self) -> str:
        """SQLite database URL derived from the data directory."""
        return f"sqlite:///{self.data_dir}/infra-mp.db"


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
