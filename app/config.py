from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/links"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_asyncpg_url(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    secret_key: str = "change-me-in-production"
    admin_password: str = "admin"

    # bcrypt truncates at 72 bytes; passlib handles str
    geoip_city_db_path: str | None = None
    maxmind_license_key: str | None = None

    # DB-IP Country MMDB (без регистрации), см. app/services/dbip_country_download.py
    geoip_country_db_path: str | None = None
    geoip_country_auto_download: bool = True
    geoip_country_db_url: str | None = None
    # Только для локальной отладки: если реальный IP клиента не глобальный (127.0.0.1, 192.168.x.x),
    # страна берётся по этому публичному адресу. В проде не задавать.
    geoip_debug_fallback_ip: str | None = None

    # Click retention in days (GDPR-style cleanup)
    click_retention_days: int = 180

    cookie_max_age_seconds: int = 365 * 24 * 60 * 60
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    session_cookie_https_only: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
