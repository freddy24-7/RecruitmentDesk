"""The visitor's address, for the per-IP limits (PRD section 11)."""

from fastapi import Request

from app.config import Settings


def client_ip(request: Request, settings: Settings) -> str:
    """The address the per-IP limits count.

    Behind a proxy, the connection comes from the proxy, so the address is
    read from the header the proxy sets (`CLIENT_IP_HEADER`). If the header
    holds a list, the last entry is used: it was added by the nearest proxy,
    while earlier entries may come from the visitor. Without the setting, the
    header is ignored, so a visitor cannot choose an address by sending one.
    """
    if settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header, "")
        last = value.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"
