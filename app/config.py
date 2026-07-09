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
    # Если пусто — эндпоинты /api/v1/* отвечают 503 (см. app/routers/api_v1.py).
    api_token: str | None = None

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

    # 0 = без лимита; иначе макс. переходов /r/ с одного IP в минуту
    redirect_rate_limit_per_minute: int = 120
    # 0 = без лимита; иначе макс. запросов /api/v1 с одного IP в минуту
    api_rate_limit_per_minute: int = 300

    # БД accountstats / social-dashboard (accounts.profile_pic), опционально
    accountstats_database_url: str | None = None

    # production | development — влияет на openapi и проверку секретов
    app_env: str = "development"
    # None = доверять X-Forwarded-For только если peer не глобальный (docker/LAN)
    trust_forwarded_headers: bool | None = None
    csrf_enabled: bool = True
    security_headers_enabled: bool = True
    disable_openapi_docs: bool | None = None
    allow_private_destination_urls: bool = False
    content_security_policy: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://cloudflareinsights.com; "
        "frame-ancestors 'none'"
    )

    def openapi_disabled(self) -> bool:
        if self.disable_openapi_docs is not None:
            return self.disable_openapi_docs
        return self.app_env.strip().lower() == "production"

    def validate_security(self) -> None:
        if self.app_env.strip().lower() != "production":
            return
        if self.secret_key.strip() in ("", "change-me-in-production"):
            raise RuntimeError("SECRET_KEY must be set in production (APP_ENV=production)")
        if self.admin_password.strip() in ("", "admin"):
            raise RuntimeError("ADMIN_PASSWORD must be changed in production")
        if not (self.api_token or "").strip():
            raise RuntimeError("API_TOKEN must be set in production (APP_ENV=production)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
