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
    # Signs CSRF tokens (HMAC key). Sessions themselves are opaque random
    # tokens stored server-side, so this key is a pepper, not a session key.
    secret_key: str = "change-me-in-production"
    session_cookie_name: str = "infra_mp_session"
    session_ttl_days: int = 7
    # When unset (None), the Secure cookie flag follows base_url (HTTPS -> on).
    cookie_secure: bool | None = None
    # Comma-separated Host header allowlist for TrustedHostMiddleware.
    # "*" (default) disables the check — set explicitly behind a proxy.
    allowed_hosts: str = "*"
    # Send HSTS headers. Only enable behind a TLS-terminating proxy.
    hsts_enabled: bool = False
    admin_username: str = "admin"
    admin_password: str = ""
    admin_display_name: str = "Administrator"
    debug: bool = False
    mcp_enabled: bool = True
    base_url: str = "http://localhost:8000"
    # Login brute-force protection: after max_attempts failures within
    # window_seconds, further attempts are rejected for cooldown_seconds.
    login_max_attempts: int = 5
    login_window_seconds: int = 600
    login_cooldown_seconds: int = 600
    # Backup restore limits (zip-bomb protection).
    max_backup_upload_bytes: int = 50 * 1024 * 1024
    max_backup_db_bytes: int = 250 * 1024 * 1024

    @property
    def database_url(self) -> str:
        """SQLite database URL derived from the data directory."""
        return f"sqlite:///{self.data_dir}/infra-mp.db"

    @property
    def cookie_secure_resolved(self) -> bool:
        """The Secure cookie flag: explicit setting wins, else HTTPS base_url."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.base_url.startswith("https://")

    @property
    def allowed_hosts_list(self) -> list[str]:
        hosts = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        return hosts or ["*"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
