"""Parent-owned Agent Service: the only place an Agent invocation is allowed.

The task worker holds an opaque session id and a socket path. Everything that
could be abused stays here: the invocation quota, the wall deadline, the offline
gate, credential-free executor binding, and per-invocation evidence. A ceiling
is enforced *before* the external effect, so a task cannot spend its way past a
limit and apologise afterwards.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ageval.evidence.redaction import RedactionError
from ageval.evidence.store import AttemptEvidenceStore, InvocationHandle
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.slots import (
    AFTER_AGENT_CLOSE,
    AFTER_AGENT_INVOKE,
    AFTER_AGENT_OPEN,
    BEFORE_AGENT_CLOSE,
    BEFORE_AGENT_INVOKE,
    BEFORE_AGENT_OPEN,
    NORMALIZE_AGENT_RESULT,
)
from ageval.runtime.agent_binding import AgentBinder, UnknownProfileError
from ageval.runtime.agent_service_evidence import (
    seal_failure,
    seal_invoke_result,
    write_invoke_request,
)
from ageval.runtime.offline import is_offline_agent

_LOG = logging.getLogger(__name__)
_THREAD_LOOPS = threading.local()

# Per-invoke ceiling when the task declares none.
DEFAULT_INVOKE_TIMEOUT_SECONDS = 300.0
# Parent-egress judges: environment= does not attach. In-box exec (oneshot / dsh)
# still targets the named scoring host.
_PARENT_EGRESS_EXECUTORS = frozenset({"openai-http", "anthropic-http"})


def resolve_invoke_timeout_seconds(
    params: dict[str, Any] | None = None,
    *,
    default: float = DEFAULT_INVOKE_TIMEOUT_SECONDS,
) -> float:
    """Read ``parameters.agent_timeout_seconds``; non-positive falls back."""
    data = params if isinstance(params, dict) else {}
    raw = data.get("agent_timeout_seconds")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


@dataclass
class AgentInvocationQuota:
    """Pre-effect invoke budget for one Attempt. No refund on failure.

    Thread-safe because the socket server answers each worker call on its own
    thread, and the ceiling must hold across all of them.
    """

    limit: int
    _used: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.limit = max(0, int(self.limit))

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.limit - self._used)

    def try_consume(self) -> bool:
        """Reserve one slot. False when the ceiling is already exhausted."""
        with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True


@dataclass
class SessionBinding:
    """One open logical session: a bound executor and its locked graph."""

    session_id: str
    attempt_id: str
    profile_id: str
    model: str
    executor_kind: str
    executor: Any
    graph: ExtensionGraph
    actor_id: str | None = None
    closed: bool = False
    last_handle: InvocationHandle | None = None


@dataclass
class ParentAgentService:
    """Process-local parent authority for one Attempt's Agent invocations."""

    attempt_id: str  # Runtime-owned; never taken from the worker
    binder: AgentBinder
    agent_invocation_limit: int
    invoke_quota: AgentInvocationQuota | None = None
    evidence_store: AttemptEvidenceStore | None = None
    # Current phase clock (monotonic seconds); checked before each external invoke.
    deadline_monotonic: float | None = None
    invoke_timeout_seconds: float = DEFAULT_INVOKE_TIMEOUT_SECONDS
    # First run-phase limit only. Evaluate-phase refusals do not call it.
    on_limit_reached: Any = None
    offline_env: str = "AGEVAL_OFFLINE_AGENT"
    invocations_completed: int = 0
    _sessions: dict[str, SessionBinding] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _run_sealed: bool = field(default=False, repr=False)
    _run_profile_ids: set[str] = field(default_factory=set, repr=False)
    evaluate_environment_names: frozenset[str] | None = None
    evaluate_environment_binder: Any = None

    def __post_init__(self) -> None:
        if self.invoke_quota is None:
            self.invoke_quota = AgentInvocationQuota(limit=self.agent_invocation_limit)
        timeout = float(self.invoke_timeout_seconds)
        self.invoke_timeout_seconds = timeout if timeout > 0 else DEFAULT_INVOKE_TIMEOUT_SECONDS

    # --- sessions ------------------------------------------------------------

    def seal_run(self) -> None:
        """Stop solver writers; keep the socket so evaluate can still invoke.

        Profiles that already opened a session during run may not invoke after
        gold lands. New profiles (e.g. ``judge``) still may.
        """
        with self._lock:
            self._run_sealed = True
            self._run_profile_ids = {binding.profile_id for binding in self._sessions.values()}
            session_ids = [sid for sid, binding in self._sessions.items() if not binding.closed]
        for session_id in session_ids:
            self.close_session(session_id=session_id)

    def open_session(
        self,
        *,
        profile_id: str,
        actor_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if self._wall_expired():
            self._note_run_limit("wall_time_seconds")
            return {"ok": False, "error": "wall_time_exceeded", "profile_id": profile_id}
        with self._lock:
            if self._run_sealed and profile_id in self._run_profile_ids:
                return {
                    "ok": False,
                    "error": "solver_writers_stopped",
                    "profile_id": profile_id,
                }
        actor = str(actor_id).strip() if actor_id and str(actor_id).strip() else None
        targeted = self._target_evaluate_environment(profile_id, environment)
        if targeted is not None:
            return targeted
        try:
            bound = self.binder.bind(profile_id)
        except UnknownProfileError:
            return {"ok": False, "error": "unknown_profile", "profile_id": profile_id}
        except Exception as exc:  # noqa: BLE001 — binding fails closed, once
            kind = getattr(exc, "kind", None) or type(exc).__name__
            return {
                "ok": False,
                "error": str(kind),
                "profile_id": profile_id,
                "detail": str(exc),
            }

        binding = SessionBinding(
            session_id=f"sess_{uuid.uuid4().hex[:16]}",
            attempt_id=self.attempt_id,
            profile_id=profile_id,
            model=bound.model,
            executor_kind=bound.plugin_id,
            executor=bound.executor,
            graph=bound.graph,
            actor_id=actor,
        )
        with self._lock:
            self._sessions[binding.session_id] = binding

        meta: dict[str, Any] = {
            "session_id": binding.session_id,
            "profile_id": profile_id,
            "executor_plugin": binding.executor_kind,
            "actor_id": actor,
        }
        try:
            self._chain(binding, BEFORE_AGENT_OPEN, meta)
            self._chain(binding, AFTER_AGENT_OPEN, meta)
        except Exception as exc:  # noqa: BLE001 — no half-open session
            with self._lock:
                self._sessions.pop(binding.session_id, None)
            kind = getattr(exc, "kind", None) or type(exc).__name__
            return {
                "ok": False,
                "error": "agent_open_hook_failed",
                "profile_id": profile_id,
                "detail": f"{kind}: {exc}",
            }
        return {
            "ok": True,
            "session_id": binding.session_id,
            "profile_id": profile_id,
            "actor_id": actor,
            "attempt_id": self.attempt_id,
            "provider_session_handle": None,
            "executor_plugin": binding.executor_kind,
        }

    def _target_evaluate_environment(
        self,
        profile_id: str,
        environment: str | None,
    ) -> dict[str, Any] | None:
        """Bind ACP attach to a named scoring host. HTTP judges ignore the name."""
        name = str(environment).strip() if environment else ""
        names = self.evaluate_environment_names
        if not name:
            if not names or not self._run_sealed:
                return None
            try:
                omitted = self.binder.profile(profile_id)
            except UnknownProfileError:
                return {"ok": False, "error": "unknown_profile", "profile_id": profile_id}
            if str(omitted.get("executor") or "") in _PARENT_EGRESS_EXECUTORS:
                return None
            return {
                "ok": False,
                "error": "unknown_evaluate_environment",
                "profile_id": profile_id,
            }
        if names is None or name not in names:
            return {
                "ok": False,
                "error": "unknown_evaluate_environment",
                "profile_id": profile_id,
            }
        try:
            row = self.binder.profile(profile_id)
        except UnknownProfileError:
            return {"ok": False, "error": "unknown_profile", "profile_id": profile_id}
        if str(row.get("executor") or "") in _PARENT_EGRESS_EXECUTORS:
            return None
        if not self._run_sealed:
            return {
                "ok": False,
                "error": "unknown_evaluate_environment",
                "profile_id": profile_id,
            }
        binder = self.evaluate_environment_binder
        if binder is None:
            return {
                "ok": False,
                "error": "unknown_evaluate_environment",
                "profile_id": profile_id,
            }
        try:
            _drive(binder(name, profile_id))
        except Exception as exc:  # noqa: BLE001 — open fails closed, once
            message = str(exc)
            error = (
                "unknown_evaluate_environment"
                if "unknown_evaluate_environment" in message
                else (getattr(exc, "kind", None) or type(exc).__name__)
            )
            return {
                "ok": False,
                "error": str(error),
                "profile_id": profile_id,
                "detail": message,
            }
        return None

    def close_session(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            binding = self._sessions.get(session_id)
            if binding is None:
                return {"ok": True, "already": "missing"}
            binding.closed = True

        payload: dict[str, Any] = {
            "session_id": session_id,
            "profile_id": binding.profile_id,
            "executor_plugin": binding.executor_kind,
        }
        # The session is already closed; a reporting hook must not resurrect it.
        try:
            self._chain(binding, BEFORE_AGENT_CLOSE, payload)
        except Exception:
            _LOG.exception("before_agent_close failed (fail-open) session_id=%s", session_id)
        close = getattr(binding.executor, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()
        try:
            self._chain(binding, AFTER_AGENT_CLOSE, payload)
        except Exception:
            _LOG.exception("after_agent_close failed (fail-open) session_id=%s", session_id)
        return {"ok": True}

    def session_graph(self, session_id: str) -> ExtensionGraph | None:
        """The graph pinned to an open session (evidence / inspection)."""
        with self._lock:
            binding = self._sessions.get(session_id)
        return None if binding is None else binding.graph

    def open_session_ids(self) -> list[str]:
        with self._lock:
            return [sid for sid, binding in self._sessions.items() if not binding.closed]

    # --- invoke --------------------------------------------------------------

    def invoke(
        self,
        *,
        session_id: str,
        prompt: str,
        tools: Any = None,
        messages: Any = None,
    ) -> dict[str, Any]:
        refusal = self._refuse_before_effect(session_id)
        if refusal is not None:
            return refusal
        with self._lock:
            binding = self._sessions[session_id]
            assert self.invoke_quota is not None
            if not self._run_sealed and not self.invoke_quota.try_consume():
                self._note_run_limit("agent_invocations")
                return {"ok": False, "error": "agent_invocation_limit"}

        started = time.monotonic()
        handle, refused = self._begin_evidence(binding, prompt, tools=tools, messages=messages)
        if refused is not None:
            return self._failed(binding, handle, error=refused)

        collect_dir = None if handle is None else handle.directory / "backend_raw"
        if collect_dir is not None:
            collect_dir.mkdir(parents=True, exist_ok=True)
        sentinels = tuple(self.evidence_store.sentinels) if self.evidence_store else ()

        try:
            sent = self._chain(binding, BEFORE_AGENT_INVOKE, prompt)
            invoke_kwargs: dict[str, Any] = {
                "timeout": self._invoke_timeout(),
                "collect_dir": collect_dir,
                "redaction_sentinels": sentinels,
            }
            if tools is not None:
                invoke_kwargs["tools"] = tools
            if messages is not None:
                invoke_kwargs["messages"] = messages
            result = binding.executor.invoke(sent, **invoke_kwargs)
            result = self._chain(binding, AFTER_AGENT_INVOKE, result)
            result = self._chain(binding, NORMALIZE_AGENT_RESULT, result)
        except Exception as exc:  # noqa: BLE001 — a crash still leaves evidence
            latency = (time.monotonic() - started) * 1000.0
            kind = str(getattr(exc, "kind", None) or type(exc).__name__)
            detail = str(getattr(exc, "message", None) or exc).strip()[:500]
            if handle is not None:
                event = {
                    "type": "lifecycle",
                    "phase": "crash",
                    "error_type": type(exc).__name__,
                    "kind": kind,
                    "source": "agent_service",
                }
                if detail:
                    event["detail"] = detail
                handle.append_event(event)
                seal_failure(handle, status="crash", error=kind, latency_ms=latency)
            return self._failed(binding, handle, error=kind)

        latency = (time.monotonic() - started) * 1000.0
        if handle is not None:
            redaction_error = seal_invoke_result(handle, result=result, latency_ms=latency)
            if redaction_error is not None:
                return self._failed(binding, handle, error=redaction_error)

        with self._lock:
            self.invocations_completed += 1
            if handle is not None:
                binding.last_handle = handle
        return {
            "ok": bool(result.ok),
            "error": result.error,
            "model": result.model,
            "text": (result.text or "")[-4000:],
            "structured": result.structured if isinstance(result.structured, dict) else None,
            "provider_session_handle": None,
            "remaining_after": self._remaining(),
            "invocation_id": handle.invocation_id if handle else None,
            "evidence_relative": handle.relative_path if handle else None,
            "tool_calls": _public_tool_calls(result),
        }

    def record_observation(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        content: str,
        invocation_id: str | None = None,
        function_name: str | None = None,
        raw_output: Any = None,
        error: bool = False,
    ) -> dict[str, Any]:
        """Attach a domain-tool observation to the last sealed invoke.

        Parent does not execute package tools. run.py calls this after
        Environment.get_response / ToolSet.call. No invoke quota.
        """
        call_id = str(tool_call_id or "").strip()
        if not call_id:
            return {"ok": False, "error": "missing_tool_call_id"}
        with self._lock:
            binding = self._sessions.get(session_id)
            if binding is None:
                return {"ok": False, "error": "unknown_session"}
            if binding.closed:
                return {"ok": False, "error": "session_closed"}
            handle = binding.last_handle
        if handle is None:
            return {"ok": False, "error": "no_invocation"}
        if invocation_id and handle.invocation_id != str(invocation_id):
            return {"ok": False, "error": "invocation_mismatch"}
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        event: dict[str, Any] = {
            "kind": "tool",
            "phase": "update",
            "tool_call_id": call_id,
            "function_name": str(function_name or ""),
            "content": text,
            "status": "failed" if error else "completed",
            "source": "ageval",
        }
        if raw_output is not None:
            event["raw_output"] = raw_output
        handle.append_supplement(event)
        return {
            "ok": True,
            "invocation_id": handle.invocation_id,
            "tool_call_id": call_id,
        }

    # --- guards --------------------------------------------------------------

    def _refuse_before_effect(self, session_id: str) -> dict[str, Any] | None:
        """Every reason to refuse before anything external happens."""
        if self._wall_expired():
            self._note_run_limit("wall_time_seconds")
            return _refusal("wall_time_exceeded")
        if is_offline_agent(env_name=self.offline_env):
            return _refusal("offline_forced")
        with self._lock:
            binding = self._sessions.get(session_id)
        if binding is None:
            return {"ok": False, "error": "unknown_session"}
        if binding.closed:
            return {"ok": False, "error": "session_closed"}
        if binding.attempt_id != self.attempt_id:
            return {"ok": False, "error": "cross_attempt_session"}
        return None

    def _wall_expired(self) -> bool:
        return self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic

    def _note_run_limit(self, name: str) -> None:
        """Tell the Attempt which run-phase limit was enforced. First one wins upstream."""
        if self._run_sealed:
            return
        callback = self.on_limit_reached
        if callable(callback):
            callback(name)

    def _remaining(self) -> int:
        assert self.invoke_quota is not None
        return self.invoke_quota.remaining

    def _invoke_timeout(self) -> float:
        """Task ceiling, operator override, then whatever wall time is left."""
        timeout = float(self.invoke_timeout_seconds)
        override = os.environ.get("AGEVAL_AGENT_INVOKE_TIMEOUT", "").strip()
        if override:
            with contextlib.suppress(ValueError):
                parsed = float(override)
                if parsed > 0:
                    timeout = parsed
        timeout = max(1.0, timeout)
        if self.deadline_monotonic is None:
            return timeout
        remaining = self.deadline_monotonic - time.monotonic()
        return 0.1 if remaining <= 0 else min(timeout, remaining)

    # --- evidence ------------------------------------------------------------

    def _begin_evidence(
        self,
        binding: SessionBinding,
        prompt: str,
        *,
        tools: Any = None,
        messages: Any = None,
    ) -> tuple[InvocationHandle | None, str | None]:
        """Open the invocation record. A redaction failure refuses the invoke."""
        if self.evidence_store is None:
            return None, None
        handle = self.evidence_store.begin_invocation(
            profile_id=binding.profile_id,
            executor_kind=binding.executor_kind,
            model=binding.model,
            surface="evaluate" if self._run_sealed else "agent",
        )
        try:
            write_invoke_request(
                handle,
                prompt=prompt,
                profile_id=binding.profile_id,
                kind=binding.executor_kind,
                model=binding.model,
                actor_id=binding.actor_id,
                tools=tools,
                messages=messages,
            )
        except RedactionError:
            # The store already sealed this invocation as redaction_failed.
            return handle, "redaction_failed"
        return handle, None

    def _failed(
        self, binding: SessionBinding, handle: InvocationHandle | None, *, error: str
    ) -> dict[str, Any]:
        with self._lock:
            self.invocations_completed += 1
            if handle is not None:
                binding.last_handle = handle
        return {
            "ok": False,
            "error": error,
            "model": binding.model,
            "text": "",
            "structured": None,
            "provider_session_handle": None,
            "remaining_after": self._remaining(),
            "invocation_id": handle.invocation_id if handle else None,
            "evidence_relative": handle.relative_path if handle else None,
            "tool_calls": [],
        }

    # --- chains --------------------------------------------------------------

    def _chain(self, binding: SessionBinding, slot: str, value: Any) -> Any:
        """Run one locked chain slot on this synchronous invoke path."""
        from ageval.attempt.emit import run_handlers

        handlers = binding.graph.chain(slot) if binding.graph is not None else []
        if not handlers:
            return value
        return _drive(run_handlers(handlers, value, ctx=binding))


def _public_tool_calls(result: Any) -> list[dict[str, Any]]:
    raw = getattr(result, "tool_calls", None) or ()
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("name") or ""):
            out.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "arguments": item.get("arguments")
                    if isinstance(item.get("arguments"), dict)
                    else {},
                }
            )
    return out


def _refusal(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "text": "",
        "structured": None,
        "provider_session_handle": None,
        "tool_calls": [],
    }


def _drive(coro: Any) -> Any:
    """Run an async chain from this sync path without dropping it."""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = getattr(_THREAD_LOOPS, "loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            _THREAD_LOOPS.loop = loop
        return loop.run_until_complete(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
