"""Harness ModelSpec. Nested ``model:`` is the only profile shape.

``extra`` is copied through. This module does not keep a gateway key list.
An executor ``extra_allowlist`` decides which of those keys may be sent.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Set
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn

from ageval.model.errors import ModelConfigError

API_CHAT = "chat"
API_RESPONSES = "responses"
API_SHORT_NAMES = frozenset({API_CHAT, API_RESPONSES})

# Spec attribute names. YAML ``reasoning.effort`` is ``reasoning_effort``.
MODEL_SPEC_FIELDS = frozenset({"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"})

_MODEL_KEYS = frozenset({"id", "api", "reasoning", "timeout", "watchdog", "extra"})
_REASONING_KEYS = frozenset({"effort"})
# Flat names are rejected. They are not parsed into a spec.
_FLAT_MODEL_KEYS = (
    "api",
    "reasoning_effort",
    "timeout",
    "request_timeout",
    "watchdog",
    "extra_body",
)
# Names that would replace a first-class field. Not a vendor key list.
_EXTRA_RESERVED = frozenset({"id", "api", "timeout", "watchdog", "reasoning_effort"})


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One resolved model.

    ``None`` on ``reasoning_effort`` / ``timeout`` / ``watchdog`` means omit.
    Omitted watchdog stays ``None`` here. The executor applies its own finite
    default. ``extra`` is opaque vendor data.
    """

    id: str
    api: str
    reasoning_effort: str | None
    timeout: float | None
    watchdog: float | None
    extra: Mapping[str, Any]


def resolve_model(model: Any, options: Mapping[str, Any] | None = None) -> ModelSpec:
    """Resolve a nested ``model:`` mapping to one ``ModelSpec``.

    ``model`` must be a mapping. A string id is rejected. Flat model keys in
    ``options`` (including ``extra_body`` and ``request_timeout``) are rejected.
    Other option keys are ignored; they are executor knobs, not model fields.
    """
    if options is None:
        opts: Mapping[str, Any] = {}
    elif isinstance(options, Mapping):
        opts = options
    else:
        _fail(f"model_options_invalid:{options!r}")
    if not isinstance(model, Mapping):
        _fail(f"model_nested_required:{model!r}")
    conflicts = _flat_keys_set(opts)
    if conflicts:
        _fail("model_flat_rejected:" + ",".join(conflicts))
    return _from_nested(model)


def require_model_support(
    spec: ModelSpec,
    *,
    supported_apis: Set[str],
    supported_model_fields: Set[str],
    extra_allowlist: Set[str],
) -> None:
    """Raise ``ModelConfigError`` when ``spec`` does not fit one executor.

    An active first-class field missing from ``supported_model_fields`` fails.
    Omit (``None``, or empty ``extra``) is not active. Every ``extra`` key must
    sit in ``extra_allowlist``. An empty allowlist rejects every extra key.
    """
    if spec.api not in supported_apis:
        _fail(f"model_api_unsupported:{spec.api}")
    missing = sorted(_active_fields(spec) - set(supported_model_fields))
    if missing:
        _fail("model_field_unsupported:" + ",".join(missing))
    rejected = sorted(key for key in spec.extra if key not in extra_allowlist)
    if rejected:
        _fail("model_extra_rejected:" + ",".join(rejected))


def _active_fields(spec: ModelSpec) -> set[str]:
    active = {"id", "api"}
    if spec.reasoning_effort is not None:
        active.add("reasoning_effort")
    if spec.timeout is not None:
        active.add("timeout")
    if spec.watchdog is not None:
        active.add("watchdog")
    if spec.extra:
        active.add("extra")
    return active


def _from_nested(raw: Mapping[str, Any]) -> ModelSpec:
    unknown = sorted(str(key) for key in raw if key not in _MODEL_KEYS)
    if unknown:
        _fail("model_unknown:" + ",".join(unknown))
    if "id" not in raw:
        _fail("model_id_invalid:None")
    return ModelSpec(
        id=_model_id(raw.get("id")),
        api=_api(raw.get("api")),
        reasoning_effort=_reasoning(raw.get("reasoning"), present="reasoning" in raw),
        timeout=_timeout(raw.get("timeout"), present="timeout" in raw),
        watchdog=_watchdog(raw.get("watchdog"), present="watchdog" in raw),
        extra=_extra(raw.get("extra"), present="extra" in raw),
    )


def _flat_keys_set(options: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key in _FLAT_MODEL_KEYS:
        if key not in options:
            continue
        if key == "extra_body":
            found.append(key)
            continue
        raw = options.get(key)
        if raw is None or raw == "":
            continue
        found.append(key)
    return sorted(found)


def _model_id(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        _fail(f"model_id_invalid:{raw!r}")
    return raw.strip()


def _api(raw: Any) -> str:
    if raw is None or raw == "":
        return API_CHAT
    if not isinstance(raw, str):
        _fail(f"model_api_invalid:{raw!r}")
    name = raw.strip().lower()
    if name not in API_SHORT_NAMES:
        _fail(f"model_api_invalid:{raw!r}")
    return name


def _reasoning(raw: Any, *, present: bool) -> str | None:
    if not present or raw is None or raw == "":
        return None
    if not isinstance(raw, Mapping):
        _fail(f"model_reasoning_invalid:{raw!r}")
    unknown = sorted(str(key) for key in raw if key not in _REASONING_KEYS)
    if unknown:
        _fail("model_reasoning_unknown:" + ",".join(unknown))
    if "effort" not in raw:
        return None
    return _effort(raw.get("effort"))


def _effort(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not raw.strip():
        _fail(f"reasoning_effort_invalid:{raw!r}")
    return raw.strip()


def _timeout(raw: Any, *, present: bool) -> float | None:
    """``0`` and omit are both ``None`` (do not send). Negatives are rejected."""
    if not present or raw is None or raw == "":
        return None
    value = _finite_number(raw, name="timeout")
    if value < 0:
        _fail(f"model_timeout_invalid:{raw!r}")
    if value == 0:
        return None
    return value


def _watchdog(raw: Any, *, present: bool) -> float | None:
    """Omit is ``None``. ``0`` and non-finite values fail. There is no unlimited."""
    if not present or raw is None or raw == "":
        return None
    if isinstance(raw, str) and raw.strip().lower() in {"inf", "infinity", "+inf", "unlimited"}:
        _fail(f"model_watchdog_invalid:{raw!r}")
    value = _finite_number(raw, name="watchdog")
    if value <= 0 or not math.isfinite(value):
        _fail(f"model_watchdog_invalid:{raw!r}")
    return value


def _finite_number(raw: Any, *, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        _fail(f"model_{name}_invalid:{raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _fail(f"model_{name}_invalid:{raw!r}")
    if not math.isfinite(value):
        _fail(f"model_{name}_invalid:{raw!r}")
    return value


def _extra(raw: Any, *, present: bool) -> Mapping[str, Any]:
    if not present or raw is None or raw == "":
        return MappingProxyType({})
    if raw == {}:
        return MappingProxyType({})
    if not isinstance(raw, Mapping):
        _fail(f"model_extra_invalid:{raw!r}")
    out: dict[str, Any] = {}
    reserved: list[str] = []
    effort_override = False
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            _fail(f"model_extra_invalid:{raw!r}")
        name = key.strip()
        if name in _EXTRA_RESERVED:
            reserved.append(name)
            continue
        if name == "reasoning":
            if not isinstance(value, Mapping):
                _fail(f"model_extra_invalid:{value!r}")
            if "effort" in value:
                effort_override = True
                continue
        out[name] = copy.deepcopy(value)
    if reserved:
        _fail("model_extra_reserved:" + ",".join(sorted(reserved)))
    if effort_override:
        _fail("model_extra_overrides:reasoning.effort")
    return MappingProxyType(out)


def _fail(message: str) -> NoReturn:
    raise ModelConfigError(message)
