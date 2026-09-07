"""limit/offset for Hub list endpoints.

Omit limit on suite lists to return the full visible set (existing clients).
"""

from __future__ import annotations

from services.registry.errors import RegistryAppError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _parse_int(raw: str | None, *, name: str, default: int, minimum: int) -> int:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        n = int(text)
    except ValueError as exc:
        raise RegistryAppError(
            "invalid_request", f"{name} must be an integer", http_status=400
        ) from exc
    if n < minimum:
        raise RegistryAppError("invalid_request", f"{name} must be >= {minimum}", http_status=400)
    return n


def parse_limit(raw: str | None, *, default: int | None = DEFAULT_LIMIT) -> int | None:
    text = (raw or "").strip()
    if not text:
        return default
    return min(_parse_int(raw, name="limit", default=1, minimum=1), MAX_LIMIT)


def parse_offset(raw: str | None) -> int:
    return _parse_int(raw, name="offset", default=0, minimum=0)


def page_slice[T](items: list[T], *, limit: int | None, offset: int) -> tuple[list[T], int]:
    total = len(items)
    if limit is None:
        return items, total
    return items[offset : offset + limit], total
