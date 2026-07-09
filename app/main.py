from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.jobs import cleanup_old_clicks
from app.middleware.csrf import CsrfMiddleware
from app.middleware.ip_ban import IpAuthBanMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.database import get_db
from app.routers import admin, api_v1, health, redirect
from app.routers.admin import render_indicators_page
from app.services.dbip_country_download import ensure_dbip_country_db
from app.services.geolite_download import ensure_geolite_city_db
from app.services.geoip import (
    reset_geoip_reader,
    resolved_city_mmdb_path,
    resolved_country_mmdb_path,
)

scheduler = AsyncIOScheduler()


class NoCacheAdminHtmlMiddleware(BaseHTTPMiddleware):
    """Не кэшировать HTML админки (иначе список ссылок «застывает» после создания)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/admin") or path.startswith("/api") or path in ("/privacy", "/indicators"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Vary"] = "Cookie"
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.validate_security()
    boot_log = logging.getLogger("uvicorn.error")
    boot_log.info(
        "Security: APP_ENV=%s openapi=%s csrf=%s",
        settings.app_env,
        not settings.openapi_disabled(),
        settings.csrf_enabled,
    )
    geolite_downloaded = False
    try:
        geolite_downloaded = await asyncio.to_thread(
            ensure_geolite_city_db,
            settings.maxmind_license_key,
            geoip_city_db_path=settings.geoip_city_db_path,
        )
    except Exception:
        boot_log.exception("GeoLite bootstrap failed")

    dbip_downloaded = False
    try:
        if resolved_city_mmdb_path() is None:
            dbip_downloaded = await asyncio.to_thread(
                ensure_dbip_country_db,
                geoip_country_db_path=settings.geoip_country_db_path,
                auto_download=settings.geoip_country_auto_download,
                download_url=settings.geoip_country_db_url,
            )
    except Exception:
        boot_log.exception("DB-IP Country bootstrap failed")

    if geolite_downloaded or dbip_downloaded:
        reset_geoip_reader()

    boot_log.info(
        "GeoIP после старта: city_db=%s country_db=%s",
        resolved_city_mmdb_path(),
        resolved_country_mmdb_path(),
    )

    scheduler.add_job(cleanup_old_clicks, "cron", hour=3, minute=5)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Bio links",
        lifespan=lifespan,
        docs_url=None if settings.openapi_disabled() else "/docs",
        redoc_url=None if settings.openapi_disabled() else "/redoc",
        openapi_url=None if settings.openapi_disabled() else "/openapi.json",
    )
    app.add_middleware(IpAuthBanMiddleware)
    app.add_middleware(NoCacheAdminHtmlMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.session_cookie_https_only,
    )
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy_page(request: Request):
        return templates.TemplateResponse("privacy.html", {"request": request})

    @app.get("/indicators", response_class=HTMLResponse, include_in_schema=False)
    async def indicators_page(
        request: Request,
        db=Depends(get_db),
        profile: str = Query("all"),
        platform: str = Query("all"),
        date_from: str | None = Query(None, alias="from"),
        date_to: str | None = Query(None, alias="to"),
        preset: str | None = Query(None),
    ):
        return await render_indicators_page(
            request,
            db,
            profile=profile,
            platform=platform,
            date_from=date_from,
            date_to=date_to,
            preset=preset,
        )

    app.include_router(health.router)
    app.include_router(api_v1.router)
    app.include_router(admin.router)
    app.include_router(redirect.router)
    return app


app = create_app()
