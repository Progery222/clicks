import ipaddress

from fastapi import Request


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
    Сначала X-Forwarded-For (левый = исходный клиент по RFC), затем типичные заголовки CDN.
    """
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
