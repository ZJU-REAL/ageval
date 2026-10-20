"""Host-only loopback check for OpenAI-compatible HTTP executors.

stdlib only so in-box workers can import it when ageval is on PYTHONPATH.
RFC1918 and lookalike hostnames are not loopback.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

HTTP_EXECUTORS = frozenset({"openai-http", "anthropic-http", "dsh", "nooa", "miniswe", "openhands"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_http_loopback(url: str | None) -> bool:
    """True when *url*'s host is loopback. Empty / non-HTTP / LAN is false."""
    if url is None:
        return False
    text = str(url).strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else f"http://{text}")
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def http_key_present(
    names: tuple[str, ...] | list[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """True when any locator name has a non-empty value. Values are not returned."""
    import os

    host = os.environ if environ is None else environ
    return any(str(host.get(name) or "").strip() for name in names if name)
