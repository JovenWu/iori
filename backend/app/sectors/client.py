"""Sectors API client — thin httpx wrapper.

Billing (docs.sectors.app): 2xx and 404 consume credits; 400/401/403/429/5xx
are free. `get` never raises on HTTP status — it returns (status, body) so the
cache layer can persist the paid-for response. Only transport failures and a
missing API key raise SectorsUnavailable.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "SectorsUnavailable",
    "sectors_enabled",
    "init_client",
    "close_client",
    "get",
]

_client: httpx.AsyncClient | None = None


class SectorsUnavailable(Exception):
    """Transport failure or missing configuration — never an HTTP status."""


def sectors_enabled() -> bool:
    return bool(settings.SECTORS_API_KEY)


def init_client() -> None:
    global _client
    if _client is None and sectors_enabled():
        _client = httpx.AsyncClient(
            base_url=settings.SECTORS_BASE_URL,
            headers={"Authorization": settings.SECTORS_API_KEY},
            timeout=settings.SECTORS_TIMEOUT,
        )


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get(path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    """GET `path` → (status_code, parsed JSON body)."""
    if _client is None:
        raise SectorsUnavailable("SECTORS_API_KEY is not configured")
    try:
        resp = await _client.get(path, params=params or {})
    except httpx.HTTPError as exc:
        raise SectorsUnavailable(str(exc)) from exc
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"raw": resp.text}
