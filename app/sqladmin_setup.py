"""SQLAdmin (CRUD по моделям) на /sqladmin — отдельно от SPA /admin."""

from __future__ import annotations

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.config import get_settings
from app.database import engine
from app.models import Click, IpAuthLockout, Link, Profile
from app.security import verify_env_password

_SESSION_KEY = "sqladmin_auth"


class SqlAdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        settings = get_settings()
        expected_user = (settings.sqladmin_username or "sqladmin").strip()
        expected_pass = (settings.sqladmin_password or "").strip() or settings.admin_password
        if username != expected_user:
            return False
        if not verify_env_password(password, expected_pass):
            return False
        request.session.update({_SESSION_KEY: True})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.pop(_SESSION_KEY, None)
        return True

    async def authenticate(self, request: Request) -> bool | RedirectResponse:
        if request.session.get(_SESSION_KEY):
            return True
        return False


class ProfileAdmin(ModelView, model=Profile):
    name = "Профиль"
    name_plural = "Профили"
    icon = "fa-solid fa-user-group"
    column_list = [Profile.id, Profile.name, Profile.color, Profile.created_at, Profile.updated_at]
    column_searchable_list = [Profile.name]
    column_sortable_list = [Profile.name, Profile.created_at]
    form_excluded_columns = [Profile.links]


class LinkAdmin(ModelView, model=Link):
    name = "Ссылка"
    name_plural = "Ссылки"
    icon = "fa-solid fa-link"
    column_list = [
        Link.id,
        Link.slug,
        Link.title,
        Link.label,
        Link.platform,
        Link.destination_url,
        Link.profile_id,
        Link.created_at,
    ]
    column_searchable_list = [Link.slug, Link.title, Link.label, Link.destination_url]
    column_sortable_list = [Link.slug, Link.created_at, Link.platform]
    form_excluded_columns = [Link.clicks]


class ClickAdmin(ModelView, model=Click):
    name = "Клик"
    name_plural = "Клики"
    icon = "fa-solid fa-mouse-pointer"
    column_list = [
        Click.id,
        Click.link_id,
        Click.created_at,
        Click.country_code,
        Click.ip,
        Click.dedupe_key,
        Click.user_agent,
    ]
    column_searchable_list = [Click.ip, Click.dedupe_key, Click.country_code]
    column_sortable_list = [Click.created_at, Click.country_code]
    can_create = False
    page_size = 50


class IpAuthLockoutAdmin(ModelView, model=IpAuthLockout):
    name = "Блокировка IP"
    name_plural = "Блокировки IP"
    icon = "fa-solid fa-ban"
    column_list = [
        IpAuthLockout.ip,
        IpAuthLockout.admin_failures,
        IpAuthLockout.api_failures,
        IpAuthLockout.banned_until,
    ]
    column_sortable_list = [IpAuthLockout.banned_until, IpAuthLockout.admin_failures]


def setup_sqladmin(app) -> Admin:
    settings = get_settings()
    authentication_backend = SqlAdminAuth(secret_key=settings.secret_key)
    admin = Admin(
        app=app,
        engine=engine,
        base_url="/sqladmin",
        title="Bio links DB",
        authentication_backend=authentication_backend,
    )
    admin.add_view(ProfileAdmin)
    admin.add_view(LinkAdmin)
    admin.add_view(ClickAdmin)
    admin.add_view(IpAuthLockoutAdmin)
    return admin
