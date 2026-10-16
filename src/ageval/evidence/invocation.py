"""Read one sealed invocation back as a trajectory payload.

The Agent Service seals each invocation as it happens; the record phase reads
those files back, lets plugins shape them, and the engine writes the Attempt
trajectory. Keeping the reader here means the record phase never learns the
per-invocation file names.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.evidence.store import parse_jsonl_recover


def read_invocation_payload(directory: Path) -> dict[str, Any]:
    """Payload for one invocation: what was asked, what streamed, how it ended."""
    metadata = _read_json(directory / "metadata.json")
    final = _read_json(directory / "final-response.json")
    request = _read_json(directory / "request.json")
    status = str(metadata.get("status") or "")
    turn_meta: dict[str, Any] = {
        "turn_index": metadata.get("seq") or 1,
        "executor_kind": metadata.get("executor_kind"),
        "model": metadata.get("model"),
        "profile_id": metadata.get("profile_id"),
        "invocation_id": metadata.get("invocation_id"),
        "latency_ms": metadata.get("latency_ms"),
        "status": status,
    }
    executor_meta = metadata.get("executor_metadata")
    if isinstance(executor_meta, dict):
        turn_meta.update(executor_meta)
    return {
        "prompt": _prompt_of(request),
        "events": tuple(parse_jsonl_recover(directory / "events.jsonl")),
        "final_text": str(final.get("content") or ""),
        "structured": final.get("structured_output"),
        "usage": _usage_of(final, metadata),
        "extra": _extra_of(final, metadata),
        "ok": status == "completed",
        "error": metadata.get("error"),
        "metadata": turn_meta,
    }


def _usage_of(final: dict[str, Any], metadata: dict[str, Any]) -> Any:
    """Completed invokes keep usage on final-response. Others keep it on metadata."""
    found = final.get("usage")
    if found is not None:
        return found
    fallback = metadata.get("usage")
    return fallback if isinstance(fallback, dict) else None


def _extra_of(final: dict[str, Any], metadata: dict[str, Any]) -> Any:
    found = final.get("extra")
    if found is not None:
        return found
    fallback = metadata.get("extra")
    return fallback if isinstance(fallback, dict) else None


def _prompt_of(request: dict[str, Any]) -> str:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return ""
    return "".join(
        str(m.get("content") or "")
        for m in messages
        if isinstance(m, dict)  # user turn only
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return found if isinstance(found, dict) else {}
