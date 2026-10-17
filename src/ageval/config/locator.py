"""One parse of a profile ``base_url``.

Lock stores either an ``http(s)`` URL or an env locator name. Callers use
this type instead of a second string parser. The secret value stays in the
process environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from ageval.config.env_refs import is_http_url, is_locator_name, parse_env_ref
from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError


@dataclass(frozen=True, slots=True)
class HttpUrl:
    value: str


@dataclass(frozen=True, slots=True)
class EnvLocator:
    name: str


BaseUrl = HttpUrl | EnvLocator


def parse_base_url(raw: str, *, location: str) -> BaseUrl:
    """Parse a profile value: ``${NAME}`` or an ``http(s)`` URL."""
    name = parse_env_ref(raw)
    if name is not None:
        return EnvLocator(name)
    text = raw.strip()
    if is_http_url(text):
        return HttpUrl(text)
    raise ConfigError(
        ERROR_INVALID_SCHEMA,
        "profile.base_url must be ${ENV_NAME} or an http(s) URL",
        location=location,
    )


def parse_locked_base_url(raw: object) -> BaseUrl | None:
    """Parse a value already stored on the lock, or an overlay row.

    Empty input is ``None``. A bare locator name is ``EnvLocator``. An
    ``http(s)`` URL is ``HttpUrl``. ``${NAME}`` unwraps to the name.
    Anything else is ``None`` so an overlay can omit the key.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if is_http_url(text):
        return HttpUrl(text)
    name = parse_env_ref(text)
    if name is not None:
        return EnvLocator(name)
    if is_locator_name(text):
        return EnvLocator(text)
    return None


def locked_base_url(loc: BaseUrl) -> str:
    """String written into the lock: the URL, or the locator name."""
    if isinstance(loc, HttpUrl):
        return loc.value
    return loc.name


def resolve(
    loc: BaseUrl,
    *,
    environ: Mapping[str, str] | None = None,
    location: str = "/agent_profiles/base_url",
) -> str:
    """Return the URL. An unset locator fails."""
    if isinstance(loc, HttpUrl):
        return loc.value
    env = os.environ if environ is None else environ
    val = env.get(loc.name)
    if not val or not str(val).strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            (
                f"profile.base_url ${{{loc.name}}} is unset "
                "(set it in process env or package/repo .env)"
            ),
            location=location,
        )
    return str(val).strip()


def resolve_if_set(
    loc: BaseUrl,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return the URL, or ``None`` when the locator is unset.

    Overlay writers use this so a missing env omits ``base_url`` instead of
    failing the overlay build. Spawn still uses ``resolve``, which fails.
    """
    if isinstance(loc, HttpUrl):
        return loc.value
    env = os.environ if environ is None else environ
    val = env.get(loc.name)
    if not val or not str(val).strip():
        return None
    return str(val).strip()
