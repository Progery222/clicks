import ipaddress

from fastapi import Request

from app.config import get_settings


def _peer_is_trusted_proxy(peer: str | None) -> bool:
    """Доверять X-Forwarded-For только если соединение пришло с reverse-proxy (LAN/docker)."""
    if not peer:
        return False
    try:
        return not ipaddress.ip_address(peer).is_global
    except ValueError:
        return False


def _should_trust_forwarded_headers(request: Request) -> bool:
    settings = get_settings()
    if settings.trust_forwarded_headers is not None:
        return settings.trust_forwarded_headers
    peer = request.client.host if request.client else None
    return _peer_is_trusted_proxy(peer)


def _first_routable_client_ip(candidates: list[str]) -> str | None:
    """Предпочитаем первый глобальный (публичный) адрес в цепочке прокси."""
    first: str | None = None
    for raw in candidates:
        ip = raw.strip()
        if not ip:
            continue
        if first is None:
            first = ip
        try:
            if ipaddress.ip_address(ip).is_global:
                return ip
        except ValueError:
            continue
    return first


def get_client_ip(request: Request) -> str | None:
    """
    IP клиента за reverse-proxy (Railway, Cloudflare и т.д.).
    Заголовки X-Forwarded-For учитываются только при доверенном peer (docker/LAN).
    """
    if _should_trust_forwarded_headers(request):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            chain = [p for p in (s.strip() for s in xff.split(",")) if p]
            picked = _first_routable_client_ip(chain)
            if picked:
                return picked

        for header in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
            val = request.headers.get(header)
            if not val:
                continue
            ip = val.split(",")[0].strip()
            if not ip:
                continue
            try:
                if ipaddress.ip_address(ip).is_global:
                    return ip
            except ValueError:
                continue
            return ip

    if request.client:
        return request.client.host
    return None
