"""Profile binding ``${ENV_NAME}`` refs.

``api_key: ${NAME}`` unwraps to locator ``NAME`` (value never enters the lock).
``base_url`` accepts ``${NAME}`` (lock stores the name; spawn reads env) or a
literal ``http(s)`` URL (lock stores the URL). Bare locator names are rejected.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_LOCATOR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


PREPARE_TRUST_ENV = "AGEVAL_PREPARE_TRUST"


def prepare_trust_entries() -> frozenset[str]:
    """Trust list for dataset prepare scripts (dataset_ids or root paths)."""
    import os

    raw = os.environ.get(PREPARE_TRUST_ENV) or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def prepare_script_env(dataset_root: str) -> dict[str, str]:
    """Child environment for a dataset prepare script."""
    import os

    env = dict(os.environ)
    env["AGEVAL_DATASET_ROOT"] = dataset_root
    return env


def parse_env_ref(raw: str) -> str | None:
    text = raw.strip()
    match = _ENV_REF.fullmatch(text)
    return match.group(1) if match else None


def expand_api_key_locator(raw: str, *, location: str) -> str:
    name = parse_env_ref(raw)
    if name is None:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "profile.api_key must be ${ENV_NAME} (env locator; never a bare name or secret)",
            location=location,
        )
    return name


def is_http_url(raw: str) -> bool:
    text = raw.strip()
    return text.startswith(("http://", "https://"))


def is_locator_name(raw: str) -> bool:
    text = raw.strip()
    return bool(_LOCATOR_NAME_RE.fullmatch(text)) and 0 < len(text) <= 64


def expand_base_url_locator(raw: str, *, location: str) -> str:
    """Unwrap ``${NAME}`` to ``NAME``; keep an ``http(s)`` URL as a literal."""
    from ageval.config.locator import locked_base_url, parse_base_url

    return locked_base_url(parse_base_url(raw, location=location))


def resolve_locked_base_url(
    raw: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    location: str = "/agent_profiles/base_url",
) -> str | None:
    """Turn a locked ``base_url`` (locator name or URL) into a URL at spawn."""
    from ageval.config.locator import EnvLocator, HttpUrl, parse_locked_base_url, resolve

    loc = parse_locked_base_url(raw)
    if loc is None:
        if raw is None or not str(raw).strip():
            return None
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "locked base_url must be an env locator name or an http(s) URL",
            location=location,
        )
    if isinstance(loc, HttpUrl):
        return loc.value
    assert isinstance(loc, EnvLocator)
    return resolve(loc, environ=environ, location=location)


def expand_profile_env_refs(
    profile: dict[str, Any],
    *,
    location: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Rewrite api_key / base_url ${} refs in place on one profile."""
    del environ
    api_key = profile.get("api_key")
    if api_key is not None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "profile.api_key must be a non-empty ${ENV_NAME} when set",
                location=f"{location}/api_key",
            )
        profile["api_key"] = expand_api_key_locator(api_key, location=f"{location}/api_key")
    base_url = profile.get("base_url")
    if base_url is not None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                "profile.base_url must be a non-empty string when set",
                location=f"{location}/base_url",
            )
        profile["base_url"] = expand_base_url_locator(
            base_url,
            location=f"{location}/base_url",
        )
