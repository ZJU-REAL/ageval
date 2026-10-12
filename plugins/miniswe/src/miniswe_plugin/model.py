"""Miniswe Model: one spec resolved from a nested ``model:`` or flat fields.

Field authority is ``plugins/miniswe/README.md``. This module parses. It does
not decide the HTTP body. Callers apply the spec.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from ageval.plugins.errors import ExtensionMaterializeError

DEFAULT_MODEL_ID = "openai/gpt-4o-mini"
DEFAULT_WATCHDOG_SECONDS = 180.0

API_CHAT = "chat"
API_RESPONSES = "responses"
API_SHORT_NAMES = frozenset({API_CHAT, API_RESPONSES})

_MODEL_KEYS = frozenset({"id", "api", "reasoning", "timeout", "watchdog", "extra"})
_REASONING_KEYS = frozenset({"effort"})
# Flat compat keys. Present together with a nested ``model:`` mapping is a conflict.
_FLAT_MODEL_KEYS = (
    "api",
    "reasoning_effort",
    "timeout",
    "request_timeout",
    "watchdog",
    "extra_body",
)
# ``extra`` must not replace these. ``reasoning.effort`` is checked on the leaf.
_EXTRA_RESERVED = frozenset(
    {
        "model",
        "id",
        "api",
        "api_key",
        "api_base",
        "drop_params",
        "timeout",
        "request_timeout",
        "watchdog",
        "reasoning_effort",
    }
)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One resolved model. ``None`` on ``timeout`` / ``reasoning_effort`` means omit.

    ``watchdog is None`` means the caller applies ``DEFAULT_WATCHDOG_SECONDS``.
    It does not mean unlimited.
    """

    id: str
    api: str
    reasoning_effort: str | None
    timeout: float | None
    watchdog: float | None
    extra: Mapping[str, Any]


def transport_clocks(spec: ModelSpec) -> tuple[float | None, float]:
    """``(http_timeout, watchdog)``.

    HTTP timeout ``None`` means the client has no timeout. Watchdog omit uses
    ``DEFAULT_WATCHDOG_SECONDS``. Zero and non-finite watchdog values fail.
    """
    watchdog = DEFAULT_WATCHDOG_SECONDS if spec.watchdog is None else float(spec.watchdog)
    if not math.isfinite(watchdog) or watchdog <= 0:
        _fail(f"miniswe_watchdog_invalid:{watchdog!r}")
    return spec.timeout, watchdog


def wire_body(spec: ModelSpec) -> dict[str, Any]:
    """Body fields taken from the spec. Unset effort and timeout are absent.

    Responses still receives chat-shaped ``reasoning_effort`` until the
    responses map lands. ``extra`` is copied first so a first-class value wins.
    """
    body: dict[str, Any] = copy.deepcopy(dict(spec.extra))
    if spec.reasoning_effort is not None:
        body["reasoning_effort"] = spec.reasoning_effort
    if spec.timeout is not None:
        body["timeout"] = float(spec.timeout)
    return body


def resolve_model(model: Any, options: Mapping[str, Any] | None = None) -> ModelSpec:
    """Resolve nested ``model:`` or flat profile fields to one ``ModelSpec``.

    A nested mapping is authoritative. Flat model keys set beside it conflict.
    A string ``model`` is the id; ``options`` supplies the other fields.
    ``request_timeout`` is the deprecated flat name of ``timeout`` (``0`` omits).
    """
    opts = dict(options or {})
    if isinstance(model, Mapping):
        conflicts = _flat_keys_set(opts)
        if conflicts:
            _fail("miniswe_model_conflict:" + ",".join(conflicts))
        return _from_nested(model)
    if model is not None and not isinstance(model, str):
        _fail(f"miniswe_model_invalid:{model!r}")
    return _from_flat(model, opts)


def _from_nested(raw: Mapping[str, Any]) -> ModelSpec:
    unknown = sorted(str(key) for key in raw if key not in _MODEL_KEYS)
    if unknown:
        _fail("miniswe_model_unknown:" + ",".join(unknown))
    if "id" not in raw:
        _fail("miniswe_model_id_invalid:None")
    return ModelSpec(
        id=_model_id(raw.get("id")),
        api=_api(raw.get("api")),
        reasoning_effort=_reasoning(raw.get("reasoning"), present="reasoning" in raw),
        timeout=_timeout(raw.get("timeout"), present="timeout" in raw),
        watchdog=_watchdog(raw.get("watchdog"), present="watchdog" in raw),
        extra=_extra(raw.get("extra"), present="extra" in raw),
    )


def _from_flat(model: str | None, options: Mapping[str, Any]) -> ModelSpec:
    if "timeout" in options and "request_timeout" in options:
        _fail("miniswe_model_conflict:request_timeout,timeout")
    timeout_key = "timeout" if "timeout" in options else "request_timeout"
    timeout_present = timeout_key in options
    text = model.strip() if isinstance(model, str) else ""
    return ModelSpec(
        id=text or DEFAULT_MODEL_ID,
        api=_api(options.get("api")),
        reasoning_effort=_effort(options.get("reasoning_effort")),
        timeout=_timeout(
            options.get(timeout_key) if timeout_present else None,
            present=timeout_present,
            name=timeout_key if timeout_present else "timeout",
        ),
        watchdog=_watchdog(options.get("watchdog"), present="watchdog" in options),
        extra=_extra(options.get("extra_body"), present="extra_body" in options),
    )


def _flat_keys_set(options: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key in _FLAT_MODEL_KEYS:
        if key not in options:
            continue
        raw = options.get(key)
        if raw is None or raw == "":
            continue
        if key == "extra_body" and raw == {}:
            continue
        found.append(key)
    return sorted(found)


def _model_id(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        _fail(f"miniswe_model_id_invalid:{raw!r}")
    return raw.strip()


def _api(raw: Any) -> str:
    if raw is None or raw == "":
        return API_CHAT
    if not isinstance(raw, str):
        _fail(f"miniswe_api_invalid:{raw!r}")
    name = raw.strip().lower()
    if name not in API_SHORT_NAMES:
        _fail(f"miniswe_api_invalid:{raw!r}")
    return name


def _reasoning(raw: Any, *, present: bool) -> str | None:
    if not present or raw is None or raw == "":
        return None
    if not isinstance(raw, Mapping):
        _fail(f"miniswe_model_reasoning_invalid:{raw!r}")
    unknown = sorted(str(key) for key in raw if key not in _REASONING_KEYS)
    if unknown:
        _fail("miniswe_model_reasoning_unknown:" + ",".join(unknown))
    if "effort" not in raw:
        return None
    return _effort(raw.get("effort"))


def _effort(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not raw.strip():
        _fail(f"miniswe_reasoning_effort_invalid:{raw!r}")
    return raw.strip()


def _timeout(raw: Any, *, present: bool, name: str = "timeout") -> float | None:
    """``0`` and omit are both ``None`` (do not send). Negatives are rejected."""
    if not present or raw is None or raw == "":
        return None
    value = _finite_number(raw, name=name)
    if value < 0:
        _fail(f"miniswe_{name}_invalid:{raw!r}")
    if value == 0:
        return None
    return value


def _watchdog(raw: Any, *, present: bool) -> float | None:
    """Omit is ``None`` (caller applies the default cap). ``0`` and non-finite fail."""
    if not present or raw is None or raw == "":
        return None
    if isinstance(raw, str) and raw.strip().lower() in {"inf", "infinity", "+inf", "unlimited"}:
        _fail(f"miniswe_watchdog_invalid:{raw!r}")
    value = _finite_number(raw, name="watchdog")
    if value <= 0 or not math.isfinite(value):
        _fail(f"miniswe_watchdog_invalid:{raw!r}")
    return value


def _finite_number(raw: Any, *, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        _fail(f"miniswe_{name}_invalid:{raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _fail(f"miniswe_{name}_invalid:{raw!r}")
    if not math.isfinite(value):
        _fail(f"miniswe_{name}_invalid:{raw!r}")
    return value


def _extra(raw: Any, *, present: bool) -> dict[str, Any]:
    if not present or raw is None or raw == "":
        return {}
    if raw == {}:
        return {}
    if not isinstance(raw, Mapping):
        _fail(f"miniswe_extra_body_invalid:{raw!r}")
    out: dict[str, Any] = {}
    reserved: list[str] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            _fail(f"miniswe_extra_body_invalid:{raw!r}")
        name = key.strip()
        if name in _EXTRA_RESERVED:
            reserved.append(name)
            continue
        if name == "reasoning":
            _reject_extra_reasoning_effort(value)
        out[name] = copy.deepcopy(value)
    if reserved:
        _fail("miniswe_extra_body_reserved:" + ",".join(sorted(reserved)))
    return out


def _reject_extra_reasoning_effort(value: Any) -> None:
    if not isinstance(value, Mapping):
        _fail(f"miniswe_extra_body_invalid:{value!r}")
    if "effort" in value:
        _fail("miniswe_extra_overrides:reasoning.effort")


def _fail(message: str) -> NoReturn:
    raise ExtensionMaterializeError(message, kind="extension_materialize_failed")
