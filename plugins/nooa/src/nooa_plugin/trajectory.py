"""Map NVIDIA nooa event_manager dumps to ``ageval.trajectory.event/1``.

Vendor-native rows stay in ``backend_raw/``. This module never emits ACP
``session_update`` shapes.

``items()`` only returns events the backend *recorded* for the LLM. Runtime
events (``LLMComplete``, ``BeforeTurn``, …) use ``Role.RUNTIME_EVENT`` and
are notify-only — they must be tapped via ``on("*")`` during invoke.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

SCHEMA = "ageval.trajectory.event/1"
_SOURCE = "nooa"
_OPAQUE_CLIP = 8_000
_SKIP_KINDS = frozenset(
    {
        "BeforeTurn",
        "AfterTurn",
        "BeforeAgentCall",
        "AfterAgentCall",
        "LLMCallStart",
        "LLMCallEnd",
        "TuiSessionResumed",
        "TuiSessionCleared",
        "DebugTrace",
        "SystemPrompt",
        "Notification",
        "Summary",
    }
)


class EventTap:
    """Live collector across child managers, runtime events, and middleware."""

    _orig_add: Any = None
    _active: list[EventTap] = []

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._unsubs: list[Callable[[], None]] = []
        self.stats: dict[str, Any] = {"attached": False, "add_calls": 0}

    def attach(self, agent: Any) -> EventTap:
        em = _event_manager(agent)
        if em is not None:
            on = getattr(em, "on", None)
            if callable(on):
                with suppress(Exception):
                    self._unsubs.append(on("*", self._on_event))
            intercept = getattr(em, "intercept", None)
            if callable(intercept):
                with suppress(Exception):
                    self._unsubs.append(intercept("llm_call", self._on_llm))
                with suppress(Exception):
                    self._unsubs.append(intercept("execute_python", self._on_python))
            self.stats["attached"] = True
        self._install_add_patch()
        return self

    def _install_add_patch(self) -> None:
        try:
            from nooa.runtime.event_manager import EventManager
        except ImportError:
            return
        if EventTap._orig_add is None:
            EventTap._orig_add = EventManager.add

            def _patched(em: Any, event: Any, *args: Any, **kwargs: Any) -> Any:
                for tap in list(EventTap._active):
                    tap.stats["add_calls"] = int(tap.stats.get("add_calls") or 0) + 1
                    tap._on_event(event)
                return EventTap._orig_add(em, event, *args, **kwargs)

            EventManager.add = _patched  # type: ignore[method-assign]
        if self not in EventTap._active:
            EventTap._active.append(self)

    def _on_event(self, ev: Any) -> None:
        with suppress(Exception):
            self._ingest(ev, tag=getattr(ev, "tag", None))

    async def _on_llm(self, ctx: Any, nxt: Any) -> Any:
        out = await nxt(ctx)
        with suppress(Exception):
            self._capture_llm(out)
        return out

    async def _on_python(self, ctx: Any, nxt: Any) -> Any:
        started_at = _utc_now_iso()
        t0 = time.monotonic()
        out = await nxt(ctx)
        elapsed_ms = max(0.0, (time.monotonic() - t0) * 1000.0)
        with suppress(Exception):
            self._capture_python(out, started_at=started_at, elapsed_ms=elapsed_ms)
        return out

    def _capture_llm(self, ctx: Any) -> None:
        resp = getattr(ctx, "response", None)
        if resp is None:
            return
        content = getattr(resp, "content", None)
        if content is None:
            content = getattr(resp, "text", None)
        if isinstance(content, str) and content:
            self._ingest(
                {
                    "event_type": "LLMOutput",
                    "id": f"tap_llm_{len(self._rows)}",
                    "content": content,
                }
            )
        tool_calls = getattr(resp, "tool_calls", None) or []
        reasoning = getattr(resp, "reasoning_content", None) or ""
        calls: list[dict[str, Any]] = []
        for call in tool_calls:
            if isinstance(call, dict):
                calls.append(call)
                continue
            calls.append(
                {
                    "tool_call_id": str(
                        getattr(call, "tool_call_id", None) or getattr(call, "id", "") or ""
                    ),
                    "function_name": str(
                        getattr(call, "function_name", None) or getattr(call, "name", "") or "tool"
                    ),
                    "arguments": _as_args(getattr(call, "arguments", None)),
                }
            )
        if reasoning or calls:
            self._ingest(
                {
                    "event_type": "LLMComplete",
                    "id": f"tap_llmcomplete_{len(self._rows)}",
                    "reasoning_content": reasoning if isinstance(reasoning, str) else "",
                    "tool_calls": calls,
                }
            )

    def _capture_python(
        self,
        ctx: Any,
        *,
        started_at: str | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        code = getattr(ctx, "code", None)
        result = getattr(ctx, "result", None)
        call_id = f"tap_py_{len(self._rows) + 1}"
        args = {"code": code} if isinstance(code, str) and code else {}
        start_row: dict[str, Any] = {
            "event_type": "ToolCallEvent",
            "id": call_id,
            "tool_call_id": call_id,
            "name": "execute_python",
            "arguments": args,
        }
        if started_at:
            start_row["started_at"] = started_at
            start_row["at"] = started_at
        self._ingest(start_row)
        stdout = getattr(result, "stdout", "") if result is not None else ""
        stderr = getattr(result, "stderr", "") if result is not None else ""
        error = getattr(result, "error", None) if result is not None else None
        value = getattr(result, "returned_value", None) if result is not None else None
        success = bool(getattr(result, "success", True)) if result is not None else True
        end_row: dict[str, Any] = {
            "event_type": "PythonOutput",
            "id": f"{call_id}_out",
            "tool_call_id": call_id,
            "execution_status": "complete" if success else "error",
            "stdout": stdout or "",
            "stderr": stderr or "",
            "error": "" if error is None else str(error),
            "value": None if value is None else _jsonable(value),
        }
        if started_at:
            end_row["started_at"] = started_at
        if elapsed_ms is not None and math.isfinite(elapsed_ms) and elapsed_ms >= 0:
            end_row["elapsed_ms"] = float(elapsed_ms)
        self._ingest(end_row)

    def _ingest(self, ev: Any, *, tag: Any = None) -> None:
        row = _event_to_dict(ev)
        if row is None:
            return
        if tag is not None and "tag" not in row:
            row["tag"] = str(tag)
        vendor_ts = row.get("timestamp") or row.get("created_at")
        if isinstance(vendor_ts, str) and vendor_ts.strip():
            row.setdefault("at", vendor_ts.strip())
        elif "at" not in row:
            row["at"] = _utc_now_iso()
        key = _row_key(row)
        if key in self._seen:
            # Later ToolCallEvent updates carry the result — replace, keep start.
            for i, existing in enumerate(self._rows):
                if _row_key(existing) == key:
                    first = (
                        existing.get("started_at")
                        or existing.get("timestamp")
                        or existing.get("at")
                    )
                    if isinstance(first, str) and first.strip():
                        row.setdefault("started_at", first.strip())
                    self._rows[i] = row
                    return
            return
        self._seen.add(key)
        self._rows.append(row)

    def finish(self, agent: Any | None = None) -> list[dict[str, Any]]:
        if agent is not None:
            for tag, ev in _iter_recorded(agent):
                self._ingest(ev, tag=tag)
            em = _event_manager(agent)
            if em is not None:
                self.stats["em_items"] = _safe_len(getattr(em, "items", None))
                backend = getattr(em, "_backend", None)
                self.stats["backend_len"] = _safe_len(getattr(backend, "__len__", None), backend)
        for unsub in self._unsubs:
            with suppress(Exception):
                unsub()
        self._unsubs.clear()
        if self in EventTap._active:
            EventTap._active.remove(self)
        if not EventTap._active and EventTap._orig_add is not None:
            with suppress(Exception):
                from nooa.runtime.event_manager import EventManager

                EventManager.add = EventTap._orig_add  # type: ignore[method-assign]
            EventTap._orig_add = None
        self.stats["native_count"] = len(self._rows)
        return list(self._rows)


def attach_event_tap(agent: Any) -> EventTap:
    """Subscribe before invoke so notify-only runtime events are kept."""
    return EventTap().attach(agent)


def dump_native_events(agent: Any) -> list[dict[str, Any]]:
    """Snapshot recorded events (active + archived). Prefer ``EventTap``."""
    tap = EventTap()
    for tag, ev in _iter_recorded(agent):
        tap._ingest(ev, tag=tag)
    return list(tap._rows)


def to_ageval_trajectory_events(
    raw_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    session_id: str = "nooa",
) -> list[dict[str, Any]]:
    """Native nooa dump → Core-owned trajectory events."""
    out: list[dict[str, Any]] = []
    seq = 0
    emitted_tools: set[str] = set()
    pending_code: str | None = None
    started_at: dict[str, str] = {}
    llm_started_at: str | None = None
    pending_llm_elapsed: float | None = None
    last_llm_elapsed: float | None = None
    last_return: dict[str, Any] | None = None
    has_vendor_tools = any(
        isinstance(row, dict)
        and _event_type(row) in {"ToolCallEvent", "ToolCall", "PythonOutput"}
        and not str(row.get("id") or "").startswith("tap_")
        for row in raw_events
    )

    def _next() -> int:
        nonlocal seq
        seq += 1
        return seq

    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        if has_vendor_tools and str(raw.get("id") or "").startswith("tap_"):
            continue
        et = _event_type(raw)
        if et == "LLMCallStart":
            llm_started_at = _coerce_event_at(raw)
            continue
        if et == "LLMCallEnd":
            end_at = _coerce_event_at(raw)
            if llm_started_at and end_at:
                pending_llm_elapsed = _iso_delta_ms(llm_started_at, end_at)
                if pending_llm_elapsed and pending_llm_elapsed > 0:
                    last_llm_elapsed = pending_llm_elapsed
            llm_started_at = None
            continue
        if et in _SKIP_KINDS:
            continue
        if et == "Task":
            text = str(raw.get("prompt") or "")
            if text:
                out.append(_text(_next(), session_id, "thought", text))
        elif et in {"Message", "TextOnlyReply"}:
            text = raw.get("content")
            if not isinstance(text, str):
                text = str(text or "")
            if text:
                row = _text(_next(), session_id, "assistant", text)
                pending_llm_elapsed = _attach_llm_elapsed(row, pending_llm_elapsed)
                out.append(row)
        elif et == "LLMOutput":
            text = raw.get("content")
            if not isinstance(text, str):
                text = str(text or "")
            if text and _looks_like_code(text):
                pending_code = text
                row = _text(_next(), session_id, "thought", text)
                pending_llm_elapsed = _attach_llm_elapsed(row, pending_llm_elapsed)
                out.append(row)
            elif text:
                row = _text(_next(), session_id, "assistant", text)
                pending_llm_elapsed = _attach_llm_elapsed(row, pending_llm_elapsed)
                out.append(row)
        elif et in {"Reasoning", "Error", "Feedback"}:
            text = raw.get("content")
            if text:
                row = _text(_next(), session_id, "thought", str(text))
                pending_llm_elapsed = _attach_llm_elapsed(row, pending_llm_elapsed)
                out.append(row)
        elif et in {"ToolCallEvent", "ToolCall"}:
            seq, pending_code = _emit_tool_pair(
                out,
                seq,
                session_id,
                raw,
                emitted_tools,
                started_at,
                pending_code=pending_code,
            )
            name = str(raw.get("name") or raw.get("tool") or "")
            if name == "return_result":
                last_return = raw
        elif et == "PythonOutput":
            seq, pending_code = _emit_python_output(
                out,
                seq,
                session_id,
                raw,
                emitted_tools,
                started_at,
                pending_code=pending_code,
            )
        elif et == "LLMComplete":
            reason = raw.get("reasoning_content")
            if isinstance(reason, str) and reason.strip():
                row = _text(_next(), session_id, "thought", reason)
                pending_llm_elapsed = _attach_llm_elapsed(row, pending_llm_elapsed)
                out.append(row)
            # Proposed calls on the LLM row are not the execute span.
            # ToolCallEvent + PythonOutput own start/end when present.
            if has_vendor_tools:
                continue
            for call in raw.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("tool_call_id") or call.get("id") or "")
                if call_id and call_id in emitted_tools:
                    continue
                name = str(call.get("function_name") or call.get("name") or "tool")
                args = _as_args(call.get("arguments"))
                fake = {
                    "tool_call_id": call_id or f"nooa_llm_{seq + 1}",
                    "name": name,
                    "arguments": args,
                }
                seq, pending_code = _emit_tool_pair(
                    out,
                    seq,
                    session_id,
                    fake,
                    emitted_tools,
                    started_at,
                    pending_code=pending_code,
                )
                if name == "return_result":
                    last_return = fake
        else:
            seq = _next()
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "opaque",
                    "payload": _clip(raw),
                }
            )
    has_assistant = any(ev.get("channel") == "assistant" for ev in out)
    if last_return is not None and last_llm_elapsed and last_llm_elapsed > 0 and not has_assistant:
        payload = last_return.get("arguments")
        if payload is None:
            payload = last_return.get("result")
        text = _stringify_result(payload) if payload is not None else ""
        if text:
            row = _text(_next(), session_id, "assistant", text)
            row["elapsed_ms"] = float(last_llm_elapsed)
            out.append(row)
    return out


def _emit_tool_pair(
    out: list[dict[str, Any]],
    seq: int,
    session_id: str,
    raw: dict[str, Any],
    emitted_tools: set[str],
    started_at: dict[str, str],
    *,
    pending_code: str | None,
) -> tuple[int, str | None]:
    seq += 1
    call_id = str(raw.get("tool_call_id") or raw.get("id") or f"nooa_tool_{seq}")
    name = str(raw.get("name") or raw.get("tool") or "tool")
    args = _as_args(raw.get("arguments"))
    if pending_code and not args and _tool_kind(name) == "execute":
        args = {"code": pending_code}
        pending_code = None
    if call_id not in emitted_tools:
        start = {
            "schema": SCHEMA,
            "seq": seq,
            "session_id": session_id,
            "source": _SOURCE,
            "kind": "tool",
            "phase": "start",
            "tool_call_id": call_id,
            "title": name,
            "function_name": name,
            "tool_kind": _tool_kind(name),
            "status": "pending",
            "args": args,
        }
        _attach_timing(start, raw)
        _remember_start(started_at, call_id, start)
        out.append(start)
        emitted_tools.add(call_id)
    else:
        _remember_start(started_at, call_id, {"at": _coerce_event_at(raw)})
    if raw.get("result") is not None:
        seq += 1
        result = raw["result"]
        update = {
            "schema": SCHEMA,
            "seq": seq,
            "session_id": session_id,
            "source": _SOURCE,
            "kind": "tool",
            "phase": "update",
            "tool_call_id": call_id,
            "title": name,
            "function_name": name,
            "tool_kind": _tool_kind(name),
            "status": "failed" if _is_error_result(result) else "completed",
            "content": _stringify_result(result),
            "raw_output": result,
        }
        _attach_timing(update, raw)
        # Folded ToolCallEvent.timestamp is the start, not the end.
        if _event_type(raw) in {"ToolCallEvent", "ToolCall"}:
            start_iso = started_at.get(call_id)
            if start_iso:
                update["started_at"] = start_iso
            if "elapsed_ms" not in raw and "ended_at" not in raw:
                update.pop("ended_at", None)
                if update.get("at") == start_iso:
                    update.pop("at", None)
                    update.pop("elapsed_ms", None)
        _apply_span(update, started_at, call_id)
        out.append(update)
    return seq, pending_code


def _emit_python_output(
    out: list[dict[str, Any]],
    seq: int,
    session_id: str,
    raw: dict[str, Any],
    emitted_tools: set[str],
    started_at: dict[str, str],
    *,
    pending_code: str | None,
) -> tuple[int, str | None]:
    seq += 1
    call_id = str(raw.get("tool_call_id") or f"nooa_py_{seq}")
    payload = {
        k: raw.get(k)
        for k in (
            "execution_status",
            "stdout",
            "stderr",
            "error",
            "value",
            "explicit_return",
        )
    }
    status = (
        "completed"
        if str(payload.get("execution_status") or "").lower()
        in {"", "none", "complete", "completed"}
        else "failed"
    )
    args: dict[str, Any] = {}
    if pending_code:
        args = {"code": pending_code}
        pending_code = None
    if call_id not in emitted_tools:
        start = {
            "schema": SCHEMA,
            "seq": seq,
            "session_id": session_id,
            "source": _SOURCE,
            "kind": "tool",
            "phase": "start",
            "tool_call_id": call_id,
            "title": "execute_python",
            "function_name": "execute_python",
            "tool_kind": "execute",
            "status": "pending",
            "args": args,
        }
        _attach_timing(start, raw)
        _remember_start(started_at, call_id, start)
        out.append(start)
        emitted_tools.add(call_id)
        seq += 1
    update = {
        "schema": SCHEMA,
        "seq": seq,
        "session_id": session_id,
        "source": _SOURCE,
        "kind": "tool",
        "phase": "update",
        "tool_call_id": call_id,
        "title": "execute_python",
        "function_name": "execute_python",
        "tool_kind": "execute",
        "status": status,
        "content": _python_obs_text(payload),
        "raw_output": payload,
    }
    _attach_timing(update, raw)
    _apply_span(update, started_at, call_id)
    out.append(update)
    return seq, pending_code


def _text(seq: int, session_id: str, channel: str, text: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "seq": seq,
        "session_id": session_id,
        "source": _SOURCE,
        "kind": "text",
        "channel": channel,
        "text": text,
    }


def _utc_now_iso() -> str:
    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    if now.microsecond:
        stamp = f"{stamp}.{now.microsecond:06d}".rstrip("0")
    return stamp + "Z"


def _attach_timing(ev: dict[str, Any], raw: dict[str, Any]) -> None:
    at = _coerce_event_at(raw)
    if at:
        ev["at"] = at
    for key in ("elapsed_ms", "elapsedMs", "duration_ms", "durationMs"):
        val = raw.get(key)
        if isinstance(val, bool) or not isinstance(val, int | float):
            continue
        if not math.isfinite(val) or val < 0:
            continue
        ev["elapsed_ms"] = float(val)
        break
    started = raw.get("started_at") or raw.get("startedAt")
    if isinstance(started, str) and started.strip():
        ev["started_at"] = started.strip()
    ended = raw.get("ended_at") or raw.get("endedAt")
    if isinstance(ended, str) and ended.strip():
        ev["ended_at"] = ended.strip()


def _coerce_event_at(raw: dict[str, Any]) -> str | None:
    for key in ("timestamp", "created_at", "started_at", "at"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _remember_start(started_at: dict[str, str], call_id: str, ev: dict[str, Any]) -> None:
    at = ev.get("started_at") or ev.get("at")
    if isinstance(at, str) and at and call_id not in started_at:
        started_at[call_id] = at
        ev.setdefault("started_at", at)


def _apply_span(ev: dict[str, Any], started_at: dict[str, str], call_id: str) -> None:
    # Remembered ToolCallEvent start wins. PythonOutput.started_at is often the
    # output timestamp (same as ended_at) and must not zero the span.
    start_iso = started_at.get(call_id)
    if not start_iso and isinstance(ev.get("started_at"), str):
        start_iso = ev["started_at"]
    if start_iso:
        ev["started_at"] = start_iso
        started_at.setdefault(call_id, start_iso)
    end_iso = ev.get("ended_at") if isinstance(ev.get("ended_at"), str) else None
    if not end_iso and isinstance(ev.get("at"), str):
        end_iso = ev["at"]
    if end_iso:
        ev["ended_at"] = end_iso
    if ev.get("elapsed_ms") is None and start_iso and end_iso:
        elapsed = _iso_delta_ms(start_iso, end_iso)
        if elapsed is not None and elapsed > 0:
            ev["elapsed_ms"] = elapsed


def _attach_llm_elapsed(ev: dict[str, Any], elapsed_ms: float | None) -> float | None:
    if elapsed_ms is None or elapsed_ms <= 0:
        return elapsed_ms
    ev["elapsed_ms"] = float(elapsed_ms)
    return None


def _iso_delta_ms(started: str, ended: str) -> float | None:
    a = _parse_iso(started)
    b = _parse_iso(ended)
    if a is None or b is None:
        return None
    delta = (b - a).total_seconds() * 1000.0
    if delta < 0:
        return 0.0
    return round(delta, 3)


def _parse_iso(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _event_manager(agent: Any) -> Any | None:
    return getattr(agent, "event_manager", None)


def _iter_recorded(agent: Any) -> list[tuple[Any, Any]]:
    """Yield (tag, event) from active items, values, and backend.all_events()."""
    em = _event_manager(agent)
    if em is None:
        return []
    out: list[tuple[Any, Any]] = []
    items = getattr(em, "items", None)
    if callable(items):
        try:
            pairs = items()
        except Exception:  # noqa: BLE001
            pairs = ()
        if isinstance(pairs, (list, tuple)):
            for pair in pairs:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    out.append((pair[0], pair[1]))
    values = getattr(em, "values", None)
    if callable(values):
        try:
            for ev in values() or ():
                out.append((getattr(ev, "tag", None), ev))
        except Exception:  # noqa: BLE001
            pass
    backend = getattr(em, "_backend", None)
    all_events = getattr(backend, "all_events", None) if backend is not None else None
    if callable(all_events):
        try:
            for ev in all_events():
                out.append((getattr(ev, "tag", None), ev))
        except Exception:  # noqa: BLE001
            pass
    return out


def _event_type(raw: dict[str, Any]) -> str:
    for key in ("event_type", "type", "kind"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            return val.rsplit(".", 1)[-1]
    return ""


def _safe_len(fn: Any, obj: Any = None) -> int | None:
    try:
        if obj is not None and callable(fn):
            return int(fn())
        if callable(fn):
            val = fn()
            return len(val) if not isinstance(val, int) else int(val)
    except Exception:  # noqa: BLE001
        return None
    return None


def _event_to_dict(ev: Any) -> dict[str, Any] | None:
    try:
        if isinstance(ev, dict):
            row = dict(ev)
        elif hasattr(ev, "model_dump") and callable(ev.model_dump):
            dumped: Any = None
            with suppress(Exception):
                dumped = ev.model_dump(mode="json")
            if not isinstance(dumped, dict):
                with suppress(Exception):
                    dumped = ev.model_dump()
            row = dumped if isinstance(dumped, dict) else None
            if row is not None:
                row = _jsonable(row)
        else:
            row = None
        if row is None:
            row = {
                "event_type": type(ev).__name__,
                "repr": str(ev)[:_OPAQUE_CLIP],
            }
        name = type(ev).__name__ if not isinstance(ev, dict) else _event_type(row)
        if name and "event_type" not in row:
            row["event_type"] = name
        return row
    except Exception:  # noqa: BLE001
        return {"event_type": type(ev).__name__, "repr": str(ev)[:500]}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "value") and not callable(value.value):
        try:
            return _jsonable(value.value)
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _row_key(row: dict[str, Any]) -> str:
    eid = row.get("id")
    if eid:
        return f"id:{eid}"
    et = _event_type(row)
    tid = row.get("tool_call_id")
    if tid:
        return f"{et}:{tid}"
    return f"{et}:{row.get('tag')}:{id(row)}"


def _looks_like_code(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.startswith("```"):
        return True
    needles = ("import ", "from ", "def ", "open(", "Path(", "json.", "print(")
    return any(n in text for n in needles) and "\n" in text


def _as_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        with suppress(Exception):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
    return {}


def _tool_kind(name: str) -> str:
    lowered = name.lower()
    if "python" in lowered or "exec" in lowered or "bash" in lowered or "shell" in lowered:
        return "execute"
    if "read" in lowered or "cat" in lowered:
        return "read"
    if "write" in lowered or "edit" in lowered:
        return "edit"
    return "other"


def _is_error_result(result: Any) -> bool:
    if isinstance(result, dict):
        status = str(result.get("status") or result.get("execution_status") or "").lower()
        if status in {"error", "failed", "fail"}:
            return True
        if result.get("error"):
            return True
    return False


def _stringify_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)


def _python_obs_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    stdout = payload.get("stdout")
    stderr = payload.get("stderr")
    error = payload.get("error")
    value = payload.get("value")
    if isinstance(stdout, str) and stdout:
        parts.append(stdout)
    if isinstance(stderr, str) and stderr:
        parts.append(stderr)
    if error:
        parts.append(str(error))
    if value is not None and not parts:
        parts.append(_stringify_result(value))
    return "\n".join(parts)


def _clip(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        blob = json.dumps(raw, ensure_ascii=False, default=str)
    except TypeError:
        return {"repr": str(raw)[:_OPAQUE_CLIP]}
    if len(blob) <= _OPAQUE_CLIP:
        return raw
    return {"clipped": True, "preview": blob[:_OPAQUE_CLIP]}
