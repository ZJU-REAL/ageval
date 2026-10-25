"""Project completed activity rows into trajectory events.

A resumed invoke only observes the steps that happen after the process
starts. Viewer trajectory is the whole invoke, so earlier completed steps
from the activity log are placed in front of that fresh stream.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

SCHEMA = "ageval.trajectory.event/1"


def prior_activity_events(scope: Any, fresh: Sequence[Any]) -> list[dict[str, Any]]:
    """Whole invoke: fresh events, with completed activity steps filling every gap.

    A resumed buffer is often only the suffix, and a worker trajectory can also
    skip steps that ``activity.jsonl`` already marked completed. Those missing
    steps stay in ``seq`` order instead of being dropped.
    """
    log = getattr(scope, "log", None) if scope is not None else None
    invoke = getattr(scope, "invoke_request_id", None) if scope is not None else None
    fresh_events = [event for event in fresh if isinstance(event, dict)]
    if log is None or not isinstance(invoke, str):
        return _reseq(fresh_events)
    session_id = getattr(scope, "session_id", None)
    session = session_id if isinstance(session_id, str) else ""
    completed = [
        record
        for record in log.records
        if record.status == "completed" and record.payload.get("invoke_request_id") == invoke
    ]
    order, buckets, tail = _segments(fresh_events)
    fresh_ids = set(order)
    activity_ids = {_call_id(record) for record in completed if _call_id(record)}
    if fresh_ids and activity_ids and fresh_ids.isdisjoint(activity_ids):
        return _reseq(fresh_events)
    if not fresh_ids:
        projected = _project(completed, log.records, session_id=session)
        return _reseq(projected + fresh_events)
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for record in completed:
        if record.kind == "model_turn":
            if not _already_in_fresh(record, fresh_events):
                out.extend(_project([record], log.records, session_id=session))
            continue
        if record.kind != "tool_call":
            continue
        call_id = _call_id(record)
        if not call_id or call_id in used:
            continue
        if call_id in buckets:
            out.extend(buckets[call_id])
            used.add(call_id)
            continue
        out.extend(_project([record], log.records, session_id=session))
        used.add(call_id)
    for call_id in order:
        if call_id not in used:
            out.extend(buckets[call_id])
            used.add(call_id)
    out.extend(tail)
    return _reseq(out)


def _segments(
    events: Sequence[dict[str, Any]],
) -> tuple[list[str], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Group fresh events so text before a tool stays with that tool."""
    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    pending: list[dict[str, Any]] = []
    for event in events:
        found = _tool_ids((event,))
        call_id = next(iter(found), "")
        if not call_id:
            pending.append(event)
            continue
        if call_id not in buckets:
            buckets[call_id] = pending
            pending = []
            order.append(call_id)
        buckets[call_id].append(event)
    return order, buckets, pending


def _reseq(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seq, event in enumerate(events, start=1):
        row = dict(event)
        row["seq"] = seq
        out.append(row)
    return out


def _already_in_fresh(record: Any, fresh: Sequence[Any]) -> bool:
    """A resumed buffer already carries this model turn when its text is there."""
    if record.kind != "model_turn":
        return False
    pieces = (
        str(record.payload.get("assistant_text") or "").strip(),
        str(record.payload.get("thought") or "").strip(),
    )
    blobs = _fresh_blobs(fresh)
    for piece in pieces:
        if len(piece) < 16:
            continue
        if any(piece in blob for blob in blobs):
            return True
    return False


def _fresh_blobs(events: Sequence[Any]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "text":
            continue
        text = event.get("text")
        if not isinstance(text, str) or not text:
            continue
        grouped.setdefault(str(event.get("channel") or ""), []).append(text)
    blobs: list[str] = []
    for parts in grouped.values():
        blobs.append("".join(parts))
        blobs.append("\n".join(parts))
    return blobs


def _call_id(record: Any) -> str:
    raw = record.payload.get("tool_call_id")
    return raw if isinstance(raw, str) else ""


def _tool_ids(events: Sequence[Any]) -> set[str]:
    found: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in ("tool_call_id", "toolCallId"):
            raw = event.get(key)
            if isinstance(raw, str) and raw:
                found.add(raw)
        update = event.get("update")
        if isinstance(update, dict):
            for key in ("tool_call_id", "toolCallId"):
                raw = update.get(key)
                if isinstance(raw, str) and raw:
                    found.add(raw)
    return found


def _project(
    records: Sequence[Any],
    all_records: Sequence[Any],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seq = 0
    inflight: dict[str, Any] = {}
    for record in all_records:
        if record.kind == "tool_call" and record.status == "in_flight":
            inflight[record.request_id] = record
    for record in records:
        if record.kind == "model_turn" and record.status == "completed":
            thought = str(record.payload.get("thought") or "").strip()
            text = str(record.payload.get("assistant_text") or "")
            if thought:
                seq += 1
                out.append(_text(seq, session_id, thought, channel="thought"))
            if text:
                seq += 1
                out.append(_text(seq, session_id, text, channel="assistant"))
            continue
        if record.kind != "tool_call" or record.status != "completed":
            continue
        call_id = _call_id(record)
        if not call_id:
            continue
        started = inflight.get(record.request_id)
        name = "tool"
        arguments: dict[str, Any] = {}
        if started is not None:
            name = str(started.payload.get("tool_name") or "tool")
            raw_args = started.payload.get("arguments")
            if isinstance(raw_args, dict):
                arguments = raw_args
        seq += 1
        out.append(
            {
                "schema": SCHEMA,
                "seq": seq,
                "session_id": session_id,
                "source": "activity",
                "kind": "tool",
                "phase": "start",
                "tool_call_id": call_id,
                "function_name": name,
                "title": name,
                "args": arguments,
                "status": "pending",
            }
        )
        seq += 1
        out.append(
            {
                "schema": SCHEMA,
                "seq": seq,
                "session_id": session_id,
                "source": "activity",
                "kind": "tool",
                "phase": "update",
                "tool_call_id": call_id,
                "function_name": name,
                "title": name,
                "content": str(record.payload.get("content") or "")[:8000],
                "status": "completed" if record.payload.get("outcome") != "error" else "failed",
            }
        )
    return out


def _text(seq: int, session_id: str, text: str, *, channel: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "seq": seq,
        "session_id": session_id,
        "source": "activity",
        "kind": "text",
        "channel": channel,
        "text": text[:8000],
    }
