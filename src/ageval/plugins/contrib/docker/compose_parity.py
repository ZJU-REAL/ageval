"""Attempt-container parity with a compose ``main`` service.

The Attempt stays a separate ``docker run``. Sidecars still come from
``docker compose up``. This module only decides three facts for that run:
``network_mode: service:<name>``, ``main`` environment, and ``cap_add``.

``environment/docker-compose.yaml`` is a declaration when it is not the file
``compose up`` uses. ``services.main`` in that file is not started.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ageval.environments.protocol import EnvironmentFailure

HARBOR_COMPOSE_REL = "environment/docker-compose.yaml"
RUNTIME_COMPOSE_PREFIX = ".ageval-compose-"

_SERVICE_MODE = re.compile(r"^service:([A-Za-z0-9][A-Za-z0-9_.-]{0,62})$")
_CAP_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Same daemon locators DockerHost refuses to project into a container.
_DAEMON_ENV_KEYS = frozenset(
    {
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_API_VERSION",
        "SSL_CERT_FILE",
    }
)


@dataclass(frozen=True, slots=True)
class AttemptParity:
    """What ``docker run`` adds for one Attempt. Empty fields keep today's run."""

    service: str | None = None
    environment: tuple[tuple[str, str], ...] = ()
    cap_add: tuple[str, ...] = ()


def resolve_attempt_parity(
    *,
    task_root: Path,
    compose_file: str | None,
    options: Mapping[str, object],
) -> AttemptParity:
    """Job options win per key. The harbor compose file fills what they omit.

    A ``network_mode`` that is not ``service:<name>`` leaves the network alone.
    ``cap_add`` and ``main_environment`` still apply.
    """
    declared = _harbor_main(task_root, compose_file) if compose_file is not None else _Main()
    network_raw = options.get("network_mode", declared.network_mode)
    env_raw = options.get("main_environment", declared.environment)
    caps_raw = options.get("cap_add", declared.cap_add)
    return AttemptParity(
        service=_service_name(network_raw),
        environment=_environment(env_raw),
        cap_add=_caps(caps_raw),
    )


def prepare_runtime_compose(source: Path, project: str, *, drop_main: bool = False) -> Path:
    """Compose file for ``up``.

    A sidecar ``depends_on`` that names ``main`` is removed in a sibling file.
    When ``drop_main`` is set, ``services.main`` itself is removed so Harbor's
    agent service is not started. The authored file is left as it is. When
    nothing names ``main``, ``source`` itself is returned.
    """
    if not source.is_file():
        return source
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        # compose up reports a file this editor cannot rewrite.
        return source
    if not isinstance(loaded, dict):
        return source
    services = loaded.get("services")
    if not isinstance(services, dict):
        return source
    changed = False
    for spec in services.values():
        if isinstance(spec, dict) and _drop_depends_on_main(spec):
            changed = True
    if drop_main and "main" in services:
        del services["main"]
        changed = True
    if not changed:
        return source
    dest = source.with_name(f"{RUNTIME_COMPOSE_PREFIX}{project}.yaml")
    dest.write_text(
        yaml.safe_dump(loaded, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )
    return dest


def is_runtime_compose(path: Path) -> bool:
    return path.name.startswith(RUNTIME_COMPOSE_PREFIX)


def compose_declares_services(path: Path) -> bool:
    """False only when the file parses and its service map is empty.

    An unreadable file stays True so ``compose up`` can report the real error.
    """
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return True
    if not isinstance(loaded, dict):
        return True
    services = loaded.get("services")
    if not isinstance(services, dict):
        return False
    return bool(services)


@dataclass(frozen=True, slots=True)
class _Main:
    network_mode: str | None = None
    environment: object = None
    cap_add: object = None


def _harbor_main(task_root: Path, compose_file: str) -> _Main:
    """``services.main`` from ``environment/docker-compose.yaml``.

    Read it even when that file is the one ``compose up`` uses. ``compose_file``
    stays in the signature because the caller always has the up path.
    """
    del compose_file
    candidate = (task_root / HARBOR_COMPOSE_REL).resolve()
    if not candidate.is_file():
        return _Main()
    try:
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"{HARBOR_COMPOSE_REL} could not be read as YAML",
        ) from exc
    if not isinstance(loaded, dict):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"{HARBOR_COMPOSE_REL} must be a mapping",
        )
    services = loaded.get("services")
    if not isinstance(services, dict):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"{HARBOR_COMPOSE_REL} must contain a services mapping",
        )
    main = services.get("main")
    if main is None:
        return _Main()
    if not isinstance(main, dict):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"{HARBOR_COMPOSE_REL} services.main must be a mapping",
        )
    return _Main(
        network_mode=_optional_text(main.get("network_mode"), label="main.network_mode"),
        environment=main.get("environment"),
        cap_add=main.get("cap_add"),
    )


def _optional_text(raw: object, *, label: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"{label} must be a string",
        )
    text = raw.strip()
    return text or None


def _service_name(raw: object) -> str | None:
    text = _optional_text(raw, label="network_mode")
    if text is None or not text.startswith("service:"):
        return None
    match = _SERVICE_MODE.fullmatch(text)
    if match is None:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "network_mode service:<name> needs a compose service name",
        )
    return match.group(1)


def _caps(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        items: list[object] = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        items = list(raw)
    else:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "cap_add must be a list of capability names",
        )
    found: list[str] = []
    for item in items:
        if not isinstance(item, str) or _CAP_NAME.fullmatch(item.strip()) is None:
            raise EnvironmentFailure(
                "environment_options_invalid",
                "cap_add entries must be capability names such as SYS_PTRACE",
            )
        name = item.strip().upper()
        if name not in found:
            found.append(name)
    return tuple(found)


def _environment(raw: object) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            pairs.append((_env_key(key), _env_value(value)))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            pairs.extend(_env_item(item))
    else:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "main_environment must be a mapping or a list of KEY=VALUE entries",
        )
    kept = [(key, value) for key, value in pairs if key not in _DAEMON_ENV_KEYS]
    return tuple(kept)


def _env_item(item: object) -> list[tuple[str, str]]:
    if isinstance(item, str):
        if "=" not in item:
            raise EnvironmentFailure(
                "environment_options_invalid",
                "main environment entries must be KEY=VALUE",
            )
        key, value = item.split("=", 1)
        return [(_env_key(key), _env_value(value))]
    if isinstance(item, Mapping):
        return [(_env_key(key), _env_value(value)) for key, value in item.items()]
    raise EnvironmentFailure(
        "environment_options_invalid",
        "main environment entries must be KEY=VALUE",
    )


def _env_key(raw: object) -> str:
    if not isinstance(raw, str) or _ENV_KEY.fullmatch(raw.strip()) is None:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "main environment keys must be names",
        )
    return raw.strip()


def _env_value(raw: object) -> str:
    if isinstance(raw, bool) or raw is None:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "main environment values must be strings or numbers",
        )
    if isinstance(raw, str):
        if "\n" in raw or "\x00" in raw:
            raise EnvironmentFailure(
                "environment_options_invalid",
                "main environment values must be a single line",
            )
        return raw
    if isinstance(raw, int | float):
        return str(raw)
    raise EnvironmentFailure(
        "environment_options_invalid",
        "main environment values must be strings or numbers",
    )


def _drop_depends_on_main(spec: dict[str, object]) -> bool:
    depends = spec.get("depends_on")
    if isinstance(depends, list):
        kept = [item for item in depends if str(item) != "main"]
        if len(kept) == len(depends):
            return False
        if kept:
            spec["depends_on"] = kept
        else:
            spec.pop("depends_on", None)
        return True
    if isinstance(depends, dict) and "main" in depends:
        depends.pop("main")
        if not depends:
            spec.pop("depends_on", None)
        return True
    return False


__all__ = [
    "HARBOR_COMPOSE_REL",
    "RUNTIME_COMPOSE_PREFIX",
    "AttemptParity",
    "is_runtime_compose",
    "prepare_runtime_compose",
    "resolve_attempt_parity",
]
