"""AcpExecutor: parent-side ACP session over a pipe the box handed us.

The parent is the only ACP JSON-RPC client. It never spawns a process itself and
never learns how the box is implemented: the pipe comes from
``environment.attach_stdio``, so there is no container id, sandbox handle or ssh
target anywhere in this file.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress as contextlib_suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from acp.exceptions import RequestError

from ageval import __version__ as AGEVAL_VERSION
from ageval.environments.protocol import Placement, StdioTransport
from ageval.model import ModelSpec, require_model_support, spec_from_factory
from ageval.model.errors import TransportStall
from ageval.model.usage import adopt_usage
from ageval.plugins.agent_result import (
    AgentResult,
    observational_result_health,
    parse_validated_text_structured,
)
from ageval.plugins.base import BaseExecutor
from ageval.plugins.contrib.acp.child_env import project_credential_env
from ageval.plugins.contrib.acp.client import (
    _AgevalAcpClient,
    _map_stop_reason,
    _offline_result,
)
from ageval.plugins.contrib.acp.config_bind import (
    bind_model,
    bind_reasoning_effort,
    config_options_from,
)
from ageval.plugins.contrib.acp.entry_local import (
    acp_stdio_argv,
    apply_grok_build_bind,
    uses_entry_local_bind,
)
from ageval.plugins.contrib.acp.home import home_env
from ageval.plugins.contrib.acp.hooks import (
    resolve_entry_argv0,
    store_entry_argv0,
    stored_entry_argv0,
)
from ageval.plugins.contrib.acp.options import AcpOptions
from ageval.plugins.contrib.acp.registry import AcpEntryDescriptor, AcpRegistryError, get_entry
from ageval.plugins.contrib.acp.trajectory_map import acp_session_events_to_ageval
from ageval.plugins.contrib.acp.usage import _as_plain_mapping, normalize_acp_usage
from ageval.plugins.contrib.acp.usage_journal import (
    journal_box_dir,
    journal_texts,
    sum_journal_files,
)
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.options import coerce_options, mapping_for_model
from ageval.runtime.clocks import clock_default


class _IdleTimeout(Exception):
    """No ACP session/update or permission for idle_timeout_seconds."""


# ACP tool kinds that do not write the workspace. edit / delete / move /
# execute / other, and a call with no kind, may have changed it.
_READONLY_TOOL_KINDS = frozenset({"read", "search", "think", "fetch"})


_JOURNAL_PARTIAL = frozenset(
    {"acp_idle_timeout", "acp_timeout", "acp_unexpected_eof", "acp_protocol_error"}
)

# Non-ok kinds the parent may stall-retry when the workspace is still unchanged.
_TRANSPORT_STALL_ERRORS = _JOURNAL_PARTIAL


def _acp_transport_stall(error: str | None) -> TransportStall | None:
    """Typed failure so parent stall-retries ACP transport non-ok (like HTTP)."""
    if error is None or error not in _TRANSPORT_STALL_ERRORS:
        return None
    return TransportStall(error, kind=error)


def _usage_source_label(sources: Any) -> str:
    """Which source produced usage on a terminal that did not finish the prompt."""
    prompt = isinstance(sources, Mapping) and sources.get("prompt_usage") is True
    update = isinstance(sources, Mapping) and sources.get("usage_update") is True
    journal = isinstance(sources, Mapping) and sources.get("session_journal") is True
    if prompt and update:
        return "prompt_usage+usage_update"
    if prompt:
        return "prompt_usage"
    if update:
        return "usage_update"
    if journal:
        return "session_journal"
    return "unknown"


def _mark_partial_usage(
    usage: dict[str, Any] | None,
    extra: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mark usage cut off before ``session/prompt`` returned.

    Neither source had data: stay null. A normal return does not call this.
    """
    if usage is None and extra is None:
        return None, None
    bag = dict(extra or {})
    bag["usage_partial"] = True
    bag["usage_source"] = _usage_source_label(bag.get("sources"))
    return usage, bag


def _workspace_unchanged(events: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    """True when this prompt's tool events did not change the workspace.

    Kinds are collected per tool call. An update that omits ``tool_kind`` does
    not erase a kind already seen on that call. A call with no kind at all is
    treated as a change.
    """
    seen: dict[str, set[str]] = {}
    anon = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("kind") != "tool":
            continue
        raw_kind = ev.get("tool_kind")
        name = raw_kind.strip().lower() if isinstance(raw_kind, str) else ""
        call_id = ev.get("tool_call_id")
        if isinstance(call_id, str) and call_id:
            key = call_id
        else:
            key = f"#{anon}"
            anon += 1
        bucket = seen.setdefault(key, set())
        if name:
            bucket.add(name)
    return all(kinds and kinds <= _READONLY_TOOL_KINDS for kinds in seen.values())


@executor_plugin(priority=100, source="first-party")
class AcpExecutor(BaseExecutor):
    """Descriptor-driven ACP executor; one entry process per ageval session."""

    kind = "acp"
    concurrent_sessions = True
    requires_environment = True
    supported_apis = frozenset({"chat"})
    supported_model_fields = frozenset({"id", "api", "reasoning_effort"})
    extra_allowlist = frozenset()
    Options = AcpOptions

    def __init__(
        self,
        *,
        entry_id: str | None = None,
        host: Any = None,
        placement: Placement | None = None,
        model: Any = "entry-default",
        reasoning_effort: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        api_key: str | None = None,
        descriptor: AcpEntryDescriptor | None = None,
        idle_timeout_seconds: float | None = None,
        options: Mapping[str, Any] | None = None,
        profile_id: str | None = None,
        **_kwargs: Any,
    ) -> None:
        del profile_id
        raw = mapping_for_model(options)
        parsed: AcpOptions | None
        if isinstance(options, AcpOptions):
            parsed = options
        elif raw or entry_id is None:
            parsed = coerce_options(AcpOptions, raw, enforce_required=entry_id is None)
        else:
            parsed = None
        if entry_id is None:
            assert parsed is not None
            entry_id = parsed.entry
            spec = spec_from_factory(model, raw, default_id="entry-default")
            self.supports_model(spec)
            self.bind_model(spec)
        elif isinstance(model, Mapping):
            spec = spec_from_factory(model, raw, default_id="entry-default")
            self.supports_model(spec)
            self.bind_model(spec)
        else:
            self.model = model if isinstance(model, str) and model.strip() else "entry-default"
            effort = reasoning_effort.strip() if isinstance(reasoning_effort, str) else None
            self.reasoning_effort = effort or None
        if idle_timeout_seconds is None and parsed is not None:
            idle_timeout_seconds = parsed.idle_timeout_seconds
        self.options = parsed if parsed is not None else AcpOptions(entry=entry_id)
        if api_key_env is None and isinstance(api_key, str) and api_key.strip():
            api_key_env = api_key.strip()
        self.entry_id = entry_id
        self.base_url = base_url
        self.api_key_env = api_key_env
        idle = float(idle_timeout_seconds) if idle_timeout_seconds is not None else None
        self.idle_timeout_seconds = idle if idle is not None and idle > 0 else None
        try:
            resolved = descriptor if descriptor is not None else get_entry(entry_id)
        except AcpRegistryError as exc:
            from ageval.plugins.errors import ExtensionMaterializeError

            raise ExtensionMaterializeError(
                str(exc),
                kind="extension_materialize_failed",
            ) from exc
        if resolved is None:
            raise KeyError(f"unknown_acp_entry:{entry_id}")
        if placement is None:
            from ageval.plugins.errors import ExtensionMaterializeError

            raise ExtensionMaterializeError(
                "acp_placement_required",
                kind="extension_materialize_failed",
            )
        self.descriptor: AcpEntryDescriptor = resolved
        self._host = host
        self._placement: Placement = placement

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._conn: Any = None
        self._pipe: StdioTransport | None = None
        self._client: _AgevalAcpClient | None = None
        self._acp_session_id: str | None = None
        self._resumed_native = False
        self._agent_info: dict[str, Any] | None = None
        self._protocol_version: int | None = None
        self._actual_model: str | None = None
        self._actual_reasoning_effort: str | None = None
        self._last_error_detail: str | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._inflight: Any = None

    @classmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        require_model_support(
            spec,
            supported_apis=cls.supported_apis,
            supported_model_fields=cls.supported_model_fields,
            extra_allowlist=cls.extra_allowlist,
        )

    def bind_model(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.model = spec.id
        self.reasoning_effort = spec.reasoning_effort

    def _child_env(self) -> dict[str, str]:
        """Entry env: this Attempt's HOME plus an allowlisted credential set."""
        env = home_env(self.descriptor, self._host.visible_path(self._placement.home))
        env.update(
            project_credential_env(
                self.entry_id,
                credential_env_names=self.descriptor.credential_env_names,
                api_key_env=self.api_key_env,
                base_url=self.base_url,
                model=self.model,
            )
        )
        for key, value in self.descriptor.fixed_env.items():
            if value:
                env[str(key)] = str(value)
        return env

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, name=f"acp-loop-{self.entry_id}", daemon=True)
        t.start()
        self._loop = loop
        self._thread = t
        return loop

    def _run(self, coro: Any, *, timeout: float) -> Any:
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        self._inflight = fut
        try:
            return fut.result(timeout=timeout)
        finally:
            if self._inflight is fut:
                self._inflight = None

    async def _attach_and_init(self) -> None:
        """Attach the entry inside the box and bring the ACP session up."""
        import acp
        from acp.client.connection import ClientSideConnection
        from acp.schema import Implementation

        from ageval.environments.streams import open_streams

        argv0 = stored_entry_argv0(self._host, self.entry_id or "")
        if argv0 is None and self.entry_id:
            argv0 = await resolve_entry_argv0(self._host, self.descriptor)
            if argv0:
                store_entry_argv0(self._host, self.entry_id, argv0)
        if not argv0:
            from ageval.environments.protocol import EnvironmentFailure

            raise EnvironmentFailure(
                "acp_runtime_missing",
                f"acp entry {self.entry_id!r} has no pinned binary",
            )
        argv = self.stdio_argv()
        client = _AgevalAcpClient()
        client.activity = getattr(self, "activity", None)
        self._client = client
        scope = getattr(self, "activity", None)
        request_id = getattr(scope, "invoke_request_id", None)
        pipe = await self._host.attach_stdio(
            argv,
            placement=self._placement,
            env=self._child_env(),
            request_id=request_id if isinstance(request_id, str) and request_id else None,
        )
        self._pipe = pipe
        reader, writer = await open_streams(pipe)
        self._conn = ClientSideConnection(client, writer, reader)

        # No IDE filesystem/terminal proxy capabilities (tools run in entry process).
        init = await self._conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=None,
            client_info=Implementation(name="ageval", version=AGEVAL_VERSION),
        )
        if init is None:
            raise RuntimeError("acp_protocol_error")

        self._protocol_version = getattr(init, "protocol_version", None) or 1
        agent_info = getattr(init, "agent_info", None)
        if agent_info is not None:
            if hasattr(agent_info, "model_dump"):
                self._agent_info = agent_info.model_dump(by_alias=True, exclude_none=True)
            else:
                self._agent_info = {
                    "name": getattr(agent_info, "name", None),
                    "version": getattr(agent_info, "version", None),
                }

        # The entry reads this path itself, so it must be its own view of the box.
        cwd = self._host.visible_path(self._placement.workdir)
        opened, resumed = await self._open_acp_session(cwd)
        self._resumed_native = resumed
        self._acp_session_id = getattr(opened, "session_id", None)
        if not self._acp_session_id:
            raise RuntimeError("acp_protocol_error")
        if not resumed:
            from ageval.plugins.contrib.acp.activity_stream import note_native_session

            note_native_session(getattr(self, "activity", None), str(self._acp_session_id))

        await self._bind_entry(init, opened)

    def stdio_argv(self) -> list[str]:
        """ACP stdio argv. argv[0] is the pinned absolute path, never a PATH name."""
        from ageval.environments.protocol import EnvironmentFailure

        argv0 = stored_entry_argv0(self._host, self.entry_id or "")
        if not argv0:
            raise EnvironmentFailure(
                "acp_runtime_missing",
                f"acp entry {self.entry_id!r} has no pinned binary",
            )
        command = [argv0, *self.descriptor.acp_command[1:]]
        return acp_stdio_argv(
            self.entry_id,
            command,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )

    async def _open_acp_session(self, cwd: str) -> tuple[Any, bool]:
        """Resume the native ACP session, or open a new one."""
        from ageval.plugins.contrib.acp.activity_stream import native_session_id, prime_stream_state

        scope = getattr(self, "activity", None)
        client = getattr(self, "_client", None)
        if client is not None:
            prime_stream_state(client, scope)
        native = native_session_id(scope)
        load = getattr(self._conn, "load_session", None)
        if native and callable(load):
            if client is not None:
                client.suppress_activity = True
            try:
                loaded = await load(cwd=cwd, session_id=native, mcp_servers=[])
            except Exception:  # noqa: BLE001 — fall back to a new session and the transcript
                loaded = None
            finally:
                if client is not None:
                    client.suppress_activity = False
            # LoadSessionResponse has no session id. A returned object means the entry accepted it.
            if loaded is not None:
                from types import SimpleNamespace

                sid = getattr(loaded, "session_id", None) or native
                return SimpleNamespace(session_id=str(sid)), True
        assert self._conn is not None
        opened = await self._conn.new_session(cwd=cwd, mcp_servers=[])
        return opened, False

    async def _bind_entry(self, initialize: Any, new_session_resp: Any) -> None:
        if uses_entry_local_bind(self.entry_id):
            actual_model, actual_effort = apply_grok_build_bind(
                initialize=initialize,
                session=new_session_resp,
                model=self.model,
                reasoning_effort=self.reasoning_effort,
            )
            self._actual_model = actual_model
            self._actual_reasoning_effort = actual_effort
            return
        latest = await self._bind_model(new_session_resp)
        await self._bind_reasoning_effort(latest)

    async def _bind_model(self, new_session_resp: Any) -> Any:
        """Bind model. Returns the latest ``configOptions`` (refreshed after set)."""
        try:
            actual, latest = await bind_model(
                self._conn,
                session_id=self._acp_session_id,
                desired=self.model,
                model_binding=self.descriptor.model_binding,
                new_session_resp=new_session_resp,
            )
        except RuntimeError as exc:
            if (
                str(exc) == "acp_model_unavailable"
                and self.entry_id in {"claude-code", "codex"}
                and self.model.strip() not in ("", "entry-default")
            ):
                # Claude: attach env ANTHROPIC_MODEL. Codex: HOME .codex/config.toml.
                self._actual_model = self.model
                return config_options_from(new_session_resp)
            raise
        self._actual_model = actual
        return latest

    async def _bind_reasoning_effort(self, config_options: Any) -> None:
        """Apply ``model.reasoning.effort`` to the advertised selector."""
        self._actual_reasoning_effort = await bind_reasoning_effort(
            self._conn,
            session_id=self._acp_session_id,
            desired=self.reasoning_effort,
            config_options=config_options,
        )

    @staticmethod
    def _exc_detail(exc: BaseException) -> str | None:
        """Human-actionable detail from an ACP failure (RequestError.data first).

        Adapters put the underlying cause in ``error.data.details`` (e.g. the
        engine's stderr); losing it leaves operators with a bare error kind.
        """
        data = getattr(exc, "data", None)
        if isinstance(data, dict):
            for key in ("details", "detail", "message"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()[:300]
        text = str(exc).strip()
        return text[:300] if text else None

    async def _prompt_once(self, prompt: str) -> AgentResult:
        assert self._conn is not None and self._client is not None
        assert self._acp_session_id is not None
        from ageval.plugins.contrib.acp.activity_stream import prompt_for_resume, seal_open_turn

        prompt = prompt_for_resume(
            getattr(self, "activity", None),
            prompt,
            resumed_native=self._resumed_native,
        )
        # Per-prompt isolation: chunks + event buffer reset each invoke so
        # turn-level trajectory merge does not pull prior turns' stream.
        self._client.text_chunks.clear()
        self._client.events.clear()
        self._client.permission_decisions.clear()
        self._client.latest_usage_update = None
        self._client.prompt_usage = None
        self._client.mark_activity()
        started = time.monotonic()

        try:
            resp = await self._await_prompt(prompt)
        except _IdleTimeout:
            return self._timeout_agent_result(started, error="acp_idle_timeout")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "auth" in msg:
                err = "acp_auth_required"
            elif "eof" in msg or "closed" in msg:
                err = "acp_unexpected_eof"
            else:
                err = "acp_protocol_error"
            detail = self._exc_detail(exc)
            if detail:
                self._client.record(
                    {"type": "lifecycle", "phase": "error", "reason": err, "detail": detail}
                )
            return self._result(
                text="".join(self._client.text_chunks),
                ok=False,
                error=err,
                stop=None,
                error_detail=detail,
                usage_partial=True,
            )

        # Token authority: PromptResponse.usage (may be absent on older agents).
        prompt_usage_raw = getattr(resp, "usage", None)
        self._client.prompt_usage = _as_plain_mapping(prompt_usage_raw)
        if self._client.prompt_usage is not None:
            event_prompt_usage: dict[str, Any] = self._client.prompt_usage
            if prompt_usage_raw is not None and hasattr(prompt_usage_raw, "model_dump"):
                with contextlib_suppress(TypeError, ValueError, AttributeError):
                    dumped_prompt = prompt_usage_raw.model_dump(by_alias=True, exclude_none=True)
                    if isinstance(dumped_prompt, dict):
                        event_prompt_usage = dumped_prompt
            self._client.record(
                {
                    "type": "prompt_usage",
                    "session_id": self._acp_session_id,
                    "source": "acp",
                    # Wire-ish camelCase when available for protocol cross-check.
                    "prompt_usage": event_prompt_usage,
                }
            )

        stop = getattr(resp, "stop_reason", None) or getattr(resp, "stopReason", None)
        seal_open_turn(getattr(self, "activity", None), self._client)
        text = "".join(self._client.text_chunks)
        ok, err = _map_stop_reason(str(stop) if stop is not None else "end_turn")
        # Elicitation decline may have been recorded
        elicited = any(e.get("type") == "elicitation" for e in self._client.events[-5:])
        if elicited and not text:
            return self._result(text=text, ok=False, error="acp_elicitation_required", stop=stop)
        return self._result(text=text, ok=ok, error=err, stop=stop)

    async def _await_prompt(self, prompt: str) -> Any:
        """Wait for ``session/prompt``. Optional idle stall is ACP-local."""
        import acp

        assert self._conn is not None
        prompt_coro = self._conn.prompt(
            session_id=self._acp_session_id,
            prompt=[acp.text_block(prompt)],
        )
        idle = self.idle_timeout_seconds
        if idle is None:
            return await prompt_coro
        prompt_task = asyncio.create_task(prompt_coro)
        try:
            while True:
                if prompt_task.done():
                    return prompt_task.result()
                assert self._client is not None
                remaining = idle - (time.monotonic() - self._client.last_activity_monotonic)
                if remaining <= 0:
                    with contextlib_suppress(OSError, RuntimeError, ValueError, TypeError):
                        await self._cancel()
                    raise _IdleTimeout()
                await asyncio.wait({prompt_task}, timeout=min(0.2, remaining))
        finally:
            if not prompt_task.done():
                prompt_task.cancel()
                with contextlib_suppress(
                    asyncio.CancelledError,
                    RequestError,
                    OSError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                ):
                    await prompt_task

    def _normalized_usage(
        self, *, partial: bool
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Map this attempt's prompt usage and latest usage_update.

        ``partial`` marks a timeout or protocol failure. A finished prompt
        leaves the normalized bag unchanged.
        """
        if self._client is None:
            return None, None
        usage, extra = normalize_acp_usage(
            prompt_usage=self._client.prompt_usage,
            usage_update=self._client.latest_usage_update,
        )
        if partial:
            return _mark_partial_usage(usage, extra)
        return usage, extra

    def _timeout_agent_result(self, started: float, *, error: str) -> AgentResult:
        """Keep in-flight ACP updates, including usage already received."""
        timeout_ev: dict[str, Any] = {
            "type": "lifecycle",
            "phase": "timeout",
            "source": "acp_adapter",
            "reason": error,
            "elapsed_ms": (time.monotonic() - started) * 1000.0,
        }
        meta: dict[str, Any] = {
            "executor_kind": "acp",
            "acp_entry_id": self.entry_id,
        }
        if self.idle_timeout_seconds is not None:
            meta["idle_timeout_seconds"] = self.idle_timeout_seconds
        text = ""
        if error == "acp_idle_timeout" and self._client is not None:
            text = "".join(self._client.text_chunks)
        mapped = self._with_prior(self._mapped_events())
        usage, extra = self._normalized_usage(partial=True)
        return AgentResult(
            model=self.model,
            text=text,
            structured=None,
            ok=False,
            error=error,
            events=(*mapped, timeout_ev),
            usage=adopt_usage(usage, timeout=True),
            extra=extra,
            metadata=meta,
            repeatable=_workspace_unchanged(mapped),
            failure=_acp_transport_stall(error),
        )

    def _result(
        self,
        *,
        text: str,
        ok: bool,
        error: str | None,
        stop: Any,
        error_detail: str | None = None,
        usage_partial: bool = False,
    ) -> AgentResult:
        structured = parse_validated_text_structured(text) if ok else None
        meta: dict[str, Any] = {
            "executor_kind": "acp",
            "acp_entry_id": self.entry_id,
            "acp_version": self.descriptor.acp_version,
            "descriptor_digest": self.descriptor.descriptor_digest,
            "protocol_version": self._protocol_version,
            "agent_info": self._agent_info,
            "locked_model": self.model,
            "actual_model": self._actual_model,
            "locked_reasoning_effort": self.reasoning_effort,
            "actual_reasoning_effort": self._actual_reasoning_effort,
            "stop_reason": str(stop) if stop is not None else None,
            "integration_mode": self.descriptor.integration_mode,
        }
        if error_detail:
            meta["error_detail"] = error_detail
        mapped = self._with_prior(self._mapped_events())
        # Dual-source normalize: tokens from PromptResponse.usage; cost/context
        # from latest UsageUpdate. Never maps context.used → prompt_tokens.
        usage, extra = self._normalized_usage(partial=usage_partial)
        adopted = adopt_usage(usage, partial=usage_partial)
        health = observational_result_health(
            ok=ok,
            usage=adopted,
            extra=extra,
            actual_model=self._actual_model,
            events=mapped,
        )
        if health:
            meta["result_health"] = health
        return AgentResult(
            model=str(self._actual_model or self.model),
            text=text,
            structured=structured,
            ok=ok,
            error=error,
            events=mapped,
            usage=adopted,
            extra=extra,
            metadata=meta,
            repeatable=_workspace_unchanged(mapped),
            failure=_acp_transport_stall(error),
        )

    def _ensure_session(self, *, timeout: float) -> str | None:
        """Attach the entry if needed. Returns an error kind or None.

        Entry presence and credentials were settled during the environment phase
        (``after_environment_ready``), so nothing probes the host here.
        """
        with self._lock:
            if self._closed:
                return "session_closed"
            if self._conn is not None and self._acp_session_id is not None:
                return None
        try:
            self._run(
                self._attach_and_init(),
                timeout=min(timeout, clock_default("acp_home_cap")),
            )
        except RuntimeError as exc:
            # Bare kind raised by _attach_and_init; no extra detail to carry.
            self._last_error_detail = None
            return str(exc) or "acp_protocol_error"
        except Exception as exc:  # noqa: BLE001
            self._last_error_detail = self._exc_detail(exc)
            msg = str(exc).lower()
            if "auth" in msg:
                return "acp_auth_required"
            return "acp_protocol_error"
        return None

    def _mapped_events(self) -> tuple[dict[str, Any], ...]:
        if self._client is None:
            return ()
        return tuple(acp_session_events_to_ageval(self._client.snapshot_events()))

    def _with_prior(self, fresh: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        from ageval.plugins.activity_events import prior_activity_events

        return tuple(prior_activity_events(getattr(self, "activity", None), fresh))

    def _write_vendor(self, collect_dir: str | None) -> None:
        if not collect_dir or self._client is None:
            return
        dump = self._client.snapshot_events()
        if not dump:
            return
        root = Path(collect_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "acp_events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in dump) + "\n",
            encoding="utf-8",
        )

    def _timeout_result(self, started: float, collect_dir: str | None) -> AgentResult:
        """Keep in-flight ACP updates; do not replace them with a lone timeout row."""
        with contextlib_suppress(OSError, RuntimeError, concurrent.futures.CancelledError):
            self._run(self._cancel(), timeout=5.0)
        self._write_vendor(collect_dir)
        return self._timeout_agent_result(started, error="acp_timeout")

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> AgentResult:
        from ageval.runtime.offline import is_offline_agent

        del redaction_sentinels, tools, messages
        if is_offline_agent():
            return _offline_result(self.model)

        err = self._ensure_session(timeout=timeout)
        if err is not None:
            detail = self._last_error_detail
            event: dict[str, Any] = {
                "type": "lifecycle",
                "phase": "failed",
                "reason": err,
                "source": "acp_adapter",
            }
            meta: dict[str, Any] = {
                "executor_kind": "acp",
                "acp_entry_id": self.entry_id,
                "descriptor_digest": self.descriptor.descriptor_digest,
            }
            if detail:
                event["detail"] = detail
                meta["error_detail"] = detail
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=err,
                events=(event,),
                metadata=meta,
                failure=_acp_transport_stall(err),
            )

        started = time.monotonic()
        # This attempt only. A timeout before the prompt coroutine starts must
        # not reuse the previous turn's usage.
        if self._client is not None:
            self._client.latest_usage_update = None
            self._client.prompt_usage = None
        try:
            result = self._run(self._prompt_once(prompt), timeout=timeout)
        except TimeoutError:
            result = self._timeout_result(started, collect_dir)
        except Exception as exc:  # noqa: BLE001
            mapped = self._mapped_events()
            usage, extra = self._normalized_usage(partial=True)
            result = AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="acp_protocol_error",
                stderr=str(exc)[:500],
                events=(
                    *mapped,
                    {
                        "type": "lifecycle",
                        "phase": "failed",
                        "error_type": type(exc).__name__,
                        "source": "acp_adapter",
                    },
                ),
                usage=adopt_usage(usage, partial=True),
                extra=extra,
                metadata={
                    "executor_kind": "acp",
                    "acp_entry_id": self.entry_id,
                },
                repeatable=_workspace_unchanged(mapped),
                failure=_acp_transport_stall("acp_protocol_error"),
            )
        else:
            self._write_vendor(collect_dir)
        return self._apply_usage_journal(result)

    def _apply_usage_journal(self, result: AgentResult) -> AgentResult:
        """Fill first-class usage from the entry journal when ACP sent none."""
        if result.usage:
            return result
        journal = self.descriptor.usage_journal
        if journal is None or self._host is None or self._placement is None:
            return result
        host_path = getattr(self._host, "host_path", None)
        if not callable(host_path):
            return result
        located = host_path(journal_box_dir(self._placement.home, journal))
        if isinstance(located, Path):
            root = located
        elif isinstance(located, str):
            root = Path(located)
        else:
            return result
        usage, extra = sum_journal_files(journal_texts(root, journal.suffix), journal)
        if usage is None and extra is None:
            return result
        merged = dict(result.extra or {})
        if extra:
            sources = dict(merged.get("sources") or {})
            for key, value in dict(extra.get("sources") or {}).items():
                if sources.get(key) is not True:
                    sources[key] = value
            sources["session_journal"] = True
            merged.update({key: value for key, value in extra.items() if key != "sources"})
            merged["sources"] = sources
        if result.error in _JOURNAL_PARTIAL:
            usage, merged_out = _mark_partial_usage(usage, merged)
            adopted = adopt_usage(
                usage, timeout=result.error in {"acp_timeout", "acp_idle_timeout"}, partial=True
            )
        else:
            merged_out = merged or None
            adopted = adopt_usage(usage)
        return replace(result, usage=adopted, extra=merged_out)

    async def _cancel(self) -> None:
        if self._conn is not None and self._acp_session_id is not None:
            with contextlib_suppress(OSError, RuntimeError, ValueError, TypeError):
                await self._conn.cancel(session_id=self._acp_session_id)

    def prepare_invoke(self) -> None:
        return None

    def cancel_invoke(self) -> None:
        """Cancel the prompt and drop the in-flight wait. Close still owns the process."""
        loop = self._loop
        fut = self._inflight
        if loop is not None and self._conn is not None and self._acp_session_id is not None:
            asyncio.run_coroutine_threadsafe(self._cancel(), loop)
        if fut is not None:
            fut.cancel()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self._loop is not None:
                with contextlib_suppress(OSError, RuntimeError, concurrent.futures.CancelledError):
                    self._run(self._shutdown(), timeout=10.0)
                self._stop_loop()
        finally:
            # The box owns the process; dropping the pipe is our whole part.
            if self._pipe is not None:
                with contextlib_suppress(OSError, RuntimeError, ValueError, TypeError):
                    self._pipe.terminate()
            self._conn = None
            self._pipe = None
            self._acp_session_id = None

    async def _shutdown(self) -> None:
        """End the ACP session and leave no task behind on the private loop."""
        if self._conn is not None and self._acp_session_id is not None:
            with contextlib_suppress(RequestError, OSError, RuntimeError, ValueError, TypeError):
                await self._conn.close_session(session_id=self._acp_session_id)
            with contextlib_suppress(RequestError, OSError, RuntimeError, ValueError, TypeError):
                await self._conn.close()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _stop_loop(self) -> None:
        loop, thread = self._loop, self._thread
        self._loop, self._thread = None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5.0)
        with contextlib_suppress(OSError, RuntimeError):
            loop.close()
