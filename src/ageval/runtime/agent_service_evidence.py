"""Evidence helpers for ParentAgentService invokes.

Trajectory is observational only — never PASS authority.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ageval.evidence.redaction import RedactionError


def map_error_status(error: str | None) -> str:
    """Terminal status for a failed invoke; everything unclassified is failed."""
    if error in {"TimeoutExpired", "timeout"}:
        return "timeout"
    if error in {"CancelledError", "cancelled", "KeyboardInterrupt"}:
        return "cancelled"
    return "failed"


def seal_failure(
    handle: Any,
    *,
    status: str,
    error: str,
    latency_ms: float,
) -> None:
    if handle is None:
        return
    with contextlib.suppress(RedactionError):
        handle.seal(
            status=status,
            final_response=None,
            error=error,
            latency_ms=latency_ms,
        )


def write_invoke_request(
    handle: Any,
    *,
    prompt: str,
    profile_id: str,
    kind: str,
    model: str,
    actor_id: str | None = None,
    tools: Any = None,
    messages: Any = None,
) -> None:
    """Write request.json + invoke_start lifecycle event. Raises RedactionError."""
    chat = messages if isinstance(messages, list) and messages else None
    request: dict[str, Any] = {
        "messages": chat if chat is not None else [{"role": "user", "content": prompt}],
        "profile_id": profile_id,
        "executor_kind": kind,
        "model": model,
    }
    if actor_id:
        request["actor_id"] = actor_id
    if isinstance(tools, list) and tools:
        request["tools"] = tools
    handle.write_request(request)
    handle.append_event(
        {
            "type": "lifecycle",
            "phase": "invoke_start",
            "source": "agent_service",
            **({"actor_id": actor_id} if actor_id else {}),
        }
    )


def seal_invoke_result(
    handle: Any,
    *,
    result: Any,
    latency_ms: float,
) -> str | None:
    """Stream the executor's events, then seal this invocation.

    The Attempt trajectory is written later, by the record phase, from what is
    sealed here. Returns ``"redaction_failed"`` on RedactionError, else None.
    """
    # Stream backend events into invocation events.jsonl.
    events = getattr(result, "events", ()) or ()
    for ev in events:
        if isinstance(ev, dict):
            handle.append_event(ev)
    stderr = getattr(result, "stderr", "") or ""
    if stderr:
        handle.write_stderr(stderr)
    # Source refs as events (digests only — paths are under evidence root).
    for ref in getattr(result, "source_refs", ()) or ():
        if isinstance(ref, dict):
            handle.append_event(
                {
                    "type": "source_ref",
                    "kind": ref.get("kind"),
                    "digest": ref.get("digest"),
                    "source": "executor",
                }
            )

    executor_meta = getattr(result, "metadata", None)
    executor_meta = dict(executor_meta) if isinstance(executor_meta, dict) else {}
    try:
        if result.ok:
            handle.seal(
                status="completed",
                final_response={
                    "content": (result.text or "")[-8000:],
                    "structured_output": (
                        result.structured if isinstance(result.structured, dict) else None
                    ),
                    "usage": getattr(result, "usage", None),
                    "extra": getattr(result, "extra", None),
                    "session": {
                        "reusable": False,
                        "handle": None,
                        "note": "ephemeral; no reusable session secret",
                    },
                },
                latency_ms=latency_ms,
                executor_metadata=executor_meta,
            )
        else:
            detail = executor_meta.get("error_detail")
            usage = getattr(result, "usage", None)
            extra = getattr(result, "extra", None)
            handle.seal(
                status=map_error_status(result.error),
                final_response=None,
                error=result.error,
                latency_ms=latency_ms,
                error_detail=str(detail).strip() if isinstance(detail, str) and detail else None,
                executor_metadata=executor_meta,
                usage=usage if isinstance(usage, dict) else None,
                extra=extra if isinstance(extra, dict) else None,
            )
    except RedactionError:
        return "redaction_failed"
    return None
