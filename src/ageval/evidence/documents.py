"""Sealed evidence documents: summary, result, and the trajectory terminal row.

These dataclasses are the wire contract. ``scripts/gen_evidence_ts.py`` exports
JSON Schema and the TypeScript in ``apps/shared``. Writers keep today's JSON:
a required key is present even when null; an omit-none key is absent.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field, fields
from typing import Any, Literal, get_args, get_origin, get_type_hints

from ageval.evidence.schema import SUMMARY_SCHEMA_VERSION

UsageReason = Literal["not_reported", "lost_on_timeout", "parse_failed", "partial"]
ResultStatus = Literal["PASS", "FAIL", "ERROR"]

_SCHEMA_ID = "ageval.evidence.documents"
_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _omit() -> Any:
    """JSON key is absent when the value is None."""
    return field(default=None, metadata={"presence": "omit"})


def _null() -> Any:
    """JSON key is present and may be null."""
    return field(default=None, metadata={"presence": "null"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultError:
    """``result.error`` / ``summary.result.error``."""

    phase: str | None = _null()
    title: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ForkChange:
    """One solver-model field that differs between the source lock and the child."""

    role: str
    path: str
    # JSON names match the fork contract. Python cannot bind the keyword ``from``.
    before: str = field(metadata={"json_name": "from"})
    after: str = field(metadata={"json_name": "to"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ForkProvenance:
    """``result.fork`` and ``summary.fork``. Absent when the Attempt is not a fork."""

    format: Literal["ageval.fork/1"]
    parent_attempt_id: str
    checkpoint_seq: int
    source_locked_config_digest: str
    child_locked_config_digest: str
    source_model: str
    continuation_model: str
    continuation_model_verified: bool
    context_conversion: str
    executor_kind: str
    changes: list[ForkChange]
    shared_prefix_usage: MeasuredUsage | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayDivergence:
    """First meaningful difference between a recorded action and the new observation."""

    ordinal: int | None = _null()
    tool_call_id: str
    field: Literal["exit_code", "output", "artifact"]
    recorded_exit_code: int | None = _null()
    observed_exit_code: int | None = _null()
    artifact_id: str | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayProvenance:
    """``result.replay`` and ``summary.replay``. Absent when the Attempt is not a replay."""

    format: Literal["ageval.replay/1"]
    parent_attempt_id: str
    source_locked_config_digest: str
    child_locked_config_digest: str
    tool_semantics: str
    tool_semantics_version: str
    status: Literal["matched", "diverged", "error"]
    comparator: str
    actions_executed: int
    actions_planned: int
    evaluated: bool
    reproduced_failure: bool
    first_divergence: ReplayDivergence | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptResultDocument:
    """``result.json`` and ``summary.result``. ``facts`` is not on this object."""

    agent_invocations: int
    capabilities_used: list[str]
    cleanup_warning: str | None = _null()
    error: ResultError | None = _null()
    evidence_path: str
    gold_materialized_at: str
    kind: str
    limit: str | None = _null()
    logs: str
    metrics: dict[str, Any]
    score: float | None = _null()
    status: ResultStatus
    fork: ForkProvenance | None = _omit()
    replay: ReplayProvenance | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class PhaseTimingPhase:
    id: str
    label: str
    duration_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PhaseTimingDocument:
    """``summary.phase_timing``. ``started_at`` / ``finished_at`` are omitted when absent."""

    schema: Literal["ageval.phase_timing/1"]
    phases: list[PhaseTimingPhase]
    total_ms: float
    started_at: str | None = _omit()
    finished_at: str | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class FactDocument:
    """One ``summary.facts`` item. Empty ``detail`` is omitted, not null."""

    phase: str
    name: str
    detail: dict[str, Any] | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryDocument:
    """``summary.json``."""

    schema: Literal["ageval.evidence.summary/1"]
    attempt_id: str
    run_id: str
    evidence_root: str
    result: AttemptResultDocument
    facts: list[FactDocument]
    phase_timing: PhaseTimingDocument
    keep_vendor_raw: bool
    extra: dict[str, Any] | None = _omit()
    fork: ForkProvenance | None = _omit()
    replay: ReplayProvenance | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasuredUsage:
    """First-class counts. Each field is omitted until the backend reports it."""

    prompt_tokens: int | None = _omit()
    completion_tokens: int | None = _omit()
    cached_tokens: int | None = _omit()
    cost_usd: float | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableUsage:
    """A sealed reason. ``partial`` may carry numbers; those numbers are not a bill."""

    unavailable: UsageReason
    prompt_tokens: int | None = _omit()
    completion_tokens: int | None = _omit()
    cached_tokens: int | None = _omit()
    cost_usd: float | None = _omit()


@dataclass(frozen=True, slots=True, kw_only=True)
class TerminalRow:
    """One sealed ``type: terminal`` row. ``usage`` is an object, never JSON null."""

    type: Literal["terminal"]
    ok: bool
    error: str | None = _null()
    turn_index: int
    session_id: str | None = _null()
    structured: dict[str, Any] | None = _null()
    usage: MeasuredUsage | UnavailableUsage = field(metadata={"union_name": "TerminalUsage"})
    stop_reason: str | None = _null()
    metadata: dict[str, Any]
    source: Literal["ageval"]
    extra: dict[str, Any] | None = _omit()
    elapsed_ms: float | None = _omit()
    profile_id: str | None = _omit()


ROOT_DOCUMENTS: tuple[type, ...] = (
    SummaryDocument,
    AttemptResultDocument,
    TerminalRow,
)


def _union_args(tp: Any) -> tuple[Any, ...] | None:
    origin = get_origin(tp)
    if origin is types.UnionType:
        return get_args(tp)
    return None


def _split_none(tp: Any) -> tuple[Any, bool]:
    args = _union_args(tp)
    if not args:
        return tp, False
    rest = tuple(arg for arg in args if arg is not type(None))
    has_none = len(rest) != len(args)
    if not has_none:
        return tp, False
    if len(rest) == 1:
        return rest[0], True
    raise TypeError("evidence_union")


def _dataclass_union(tp: Any) -> tuple[type, ...] | None:
    args = _union_args(tp)
    if not args:
        return None
    members = tuple(arg for arg in args if arg is not type(None))
    if len(members) < 2:
        return None
    if all(
        isinstance(member, type) and hasattr(member, "__dataclass_fields__") for member in members
    ):
        return members
    return None


def _scalar_schema(tp: Any) -> dict[str, Any] | None:
    if tp is str:
        return {"type": "string"}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    origin = get_origin(tp)
    if origin is Literal:
        values = get_args(tp)
        if len(values) == 1:
            return {"const": values[0]}
        return {"enum": list(values)}
    if origin is list:
        (item,) = get_args(tp)
        item_schema, _refs, _unions = _type_schema(item, {})
        return {"type": "array", "items": item_schema}
    if origin is dict:
        key_t, _value_t = get_args(tp)
        if key_t is not str:
            raise TypeError("evidence_dict_key")
        return {"type": "object", "additionalProperties": True}
    return None


def _type_schema(
    tp: Any, meta: dict[str, Any]
) -> tuple[dict[str, Any], list[type], list[tuple[str, tuple[type, ...]]]]:
    """Return a schema node, dataclass refs, and named unions to define."""
    core, has_none = _split_none(tp)
    presence = meta.get("presence")
    if presence == "null" and not has_none:
        raise TypeError("evidence_nullable")
    if presence == "omit" and not has_none:
        raise TypeError("evidence_omit")
    if presence is None and has_none:
        raise TypeError("evidence_presence")
    body_tp = core if has_none else tp

    members = _dataclass_union(body_tp)
    if members is not None:
        name = meta.get("union_name")
        if not isinstance(name, str) or not name:
            raise TypeError("evidence_union_name")
        node: dict[str, Any] = {"$ref": f"#/$defs/{name}"}
        unions = [(name, members)]
        refs = list(members)
    elif isinstance(body_tp, type) and hasattr(body_tp, "__dataclass_fields__"):
        node = {"$ref": f"#/$defs/{body_tp.__name__}"}
        unions = []
        refs = [body_tp]
    else:
        scalar = _scalar_schema(body_tp)
        if scalar is None:
            raise TypeError("evidence_type")
        node = scalar
        unions = []
        refs = _nested_refs(body_tp)

    if presence == "null":
        node = {"anyOf": [node, {"type": "null"}]}
    return node, refs, unions


def _nested_refs(tp: Any) -> list[type]:
    origin = get_origin(tp)
    if origin is list:
        (item,) = get_args(tp)
        if isinstance(item, type) and hasattr(item, "__dataclass_fields__"):
            return [item]
    return []


def _object_schema(
    cls: type,
) -> tuple[dict[str, Any], list[type], list[tuple[str, tuple[type, ...]]]]:
    hints = get_type_hints(cls)
    properties: dict[str, Any] = {}
    required: list[str] = []
    refs: list[type] = []
    unions: list[tuple[str, tuple[type, ...]]] = []
    for spec in fields(cls):
        if spec.metadata.get("presence") == "omit":
            pass
        node, node_refs, node_unions = _type_schema(hints[spec.name], dict(spec.metadata))
        name = str(spec.metadata.get("json_name") or spec.name)
        properties[name] = node
        refs.extend(node_refs)
        unions.extend(node_unions)
        if spec.metadata.get("presence") != "omit":
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }
    if cls is MeasuredUsage:
        schema["minProperties"] = 1
    return schema, refs, unions


def json_schema() -> dict[str, Any]:
    """Draft 2020-12 schema for the three sealed documents and their nested objects."""
    if SUMMARY_SCHEMA_VERSION != "ageval.evidence.summary/1":
        raise RuntimeError("summary_schema_version")
    defs: dict[str, Any] = {}
    pending: list[type] = list(ROOT_DOCUMENTS)
    seen: set[type] = set()
    named: set[str] = set()
    while pending:
        cls = pending.pop(0)
        if cls in seen:
            continue
        seen.add(cls)
        schema, refs, unions = _object_schema(cls)
        defs[cls.__name__] = schema
        for ref in refs:
            if ref not in seen:
                pending.append(ref)
        for name, members in unions:
            if name in named:
                continue
            named.add(name)
            defs[name] = {"oneOf": [{"$ref": f"#/$defs/{member.__name__}"} for member in members]}
            for member in members:
                if member not in seen:
                    pending.append(member)
    ordered = {name: defs[name] for name in sorted(defs)}
    return {
        "$schema": _JSON_SCHEMA_DIALECT,
        "$id": _SCHEMA_ID,
        "$defs": ordered,
        "oneOf": [{"$ref": f"#/$defs/{cls.__name__}"} for cls in ROOT_DOCUMENTS],
    }
