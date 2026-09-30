"""AcpExecutor: parent-side ACP session over a pipe the box handed us.

The parent is the only ACP JSON-RPC client. It never spawns a process itself and
never learns how the box is implemented: the pipe comes from
``environment.attach_stdio``, so there is no container id, sandbox handle or ssh
target anywhere in this file.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import suppress as contextlib_suppress
from pathlib import Path
from typing import Any

from ageval import __version__ as AGEVAL_VERSION
from ageval.environments.protocol import Placement, StdioTransport
from ageval.plugins.agent_result import (
    AgentExecutor,
    AgentResult,
    observational_result_health,
    parse_validated_text_structured,
)
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
from ageval.plugins.contrib.acp.registry import AcpEntryDescriptor, get_entry
from ageval.plugins.contrib.acp.trajectory_map import acp_session_events_to_ageval
from ageval.plugins.contrib.acp.usage import _as_plain_mapping, normalize_acp_usage


class _IdleTimeout(Exception):
    """No ACP session/update or permission for idle_timeout_seconds."""


# ACP tool kinds that do not write the workspace. edit / delete / move /
# execute / other, and a call with no kind, may have changed it.
_READONLY_TOOL_KINDS = frozenset({"read", "search", "think", "fetch"})


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


class AcpExecutor(AgentExecutor):
    """Descriptor-driven ACP executor; one entry process per ageval session."""

    kind: str = "acp"

    def __init__(
        self,
        *,
        entry_id: str,
        host: Any,
        placement: Placement,
        model: str = "entry-default",
        reasoning_effort: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        descriptor: AcpEntryDescriptor | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.model = model
        self.reasoning_effort = reasoning_effort.strip() if reasoning_effort else None
        if self.reasoning_effort == "":
            self.reasoning_effort = None
        self.base_url = base_url
        self.api_key_env = api_key_env
        idle = float(idle_timeout_seconds) if idle_timeout_seconds is not None else None
        self.idle_timeout_seconds = idle if idle is not None and idle > 0 else None
        resolved = descriptor if descriptor is not None else get_entry(entry_id)
        if resolved is None:
            raise KeyError(f"unknown_acp_entry:{entry_id}")
        self.descriptor: AcpEntryDescriptor = resolved
        self._host = host
        self._placement = placement

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._conn: Any = None
        self._pipe: StdioTransport | None = None
        self._client: _AgevalAcpClient | None = None
        self._acp_session_id: str | None = None
        self._agent_info: dict[str, Any] | None = None
        self._protocol_version: int | None = None
        self._actual_model: str | None = None
        self._actual_reasoning_effort: str | None = None
        self._last_error_detail: str | None = None
        self._lock = threading.Lock()
        self._closed = False

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
        return fut.result(timeout=timeout)

    async def _attach_and_init(self) -> None:
        """Attach the entry inside the box and bring the ACP session up."""
        import acp
        from acp.client.connection import ClientSideConnection
        from acp.schema import Implementation

        from ageval.environments.streams import open_streams

        argv = self.stdio_argv()
        if not argv:
            raise RuntimeError("acp_entry_missing")
        client = _AgevalAcpClient()
        self._client = client
        pipe = await self._host.attach_stdio(
            argv,
            placement=self._placement,
            env=self._child_env(),
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
        new = await self._conn.new_session(
            cwd=self._host.visible_path(self._placement.workdir),
            mcp_servers=[],
        )
        self._acp_session_id = getattr(new, "session_id", None)
        if not self._acp_session_id:
            raise RuntimeError("acp_protocol_error")

        await self._bind_entry(init, new)

    def stdio_argv(self) -> list[str]:
        """ACP stdio argv for this entry, as run inside the box."""
        return acp_stdio_argv(
            self.entry_id,
            list(self.descriptor.acp_command),
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )

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
        """Apply profile ``options.reasoning_effort`` to the advertised selector."""
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
            )

        # Token authority: PromptResponse.usage (may be absent on older agents).
        prompt_usage_raw = getattr(resp, "usage", None)
        self._client.prompt_usage = _as_plain_mapping(prompt_usage_raw)
        if self._client.prompt_usage is not None:
            event_prompt_usage: dict[str, Any] = self._client.prompt_usage
            if prompt_usage_raw is not None and hasattr(prompt_usage_raw, "model_dump"):
                with contextlib_suppress(Exception):
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
                    with contextlib_suppress(Exception):
                        await self._cancel()
                    raise _IdleTimeout()
                await asyncio.wait({prompt_task}, timeout=min(0.2, remaining))
        finally:
            if not prompt_task.done():
                prompt_task.cancel()
                with contextlib_suppress(asyncio.CancelledError, Exception):
                    await prompt_task

    def _timeout_agent_result(self, started: float, *, error: str) -> AgentResult:
        """Keep in-flight ACP updates; append one timeout lifecycle row."""
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
        mapped = self._mapped_events()
        return AgentResult(
            model=self.model,
            text=text,
            structured=None,
            ok=False,
            error=error,
            events=(*mapped, timeout_ev),
            metadata=meta,
            repeatable=_workspace_unchanged(mapped),
        )

    def _result(
        self,
        *,
        text: str,
        ok: bool,
        error: str | None,
        stop: Any,
        error_detail: str | None = None,
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
        mapped = self._mapped_events()
        # Dual-source normalize: tokens from PromptResponse.usage; cost/context
        # from latest UsageUpdate. Never maps context.used → prompt_tokens.
        usage = extra = None
        if self._client is not None:
            usage, extra = normalize_acp_usage(
                prompt_usage=self._client.prompt_usage,
                usage_update=self._client.latest_usage_update,
            )
        health = observational_result_health(
            ok=ok,
            usage=usage,
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
            usage=usage,
            extra=extra,
            metadata=meta,
            repeatable=_workspace_unchanged(mapped),
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
            self._run(self._attach_and_init(), timeout=min(timeout, 120.0))
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
        with contextlib_suppress(Exception):
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
        tools: Any = None,
        messages: Any = None,
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
            )

        started = time.monotonic()
        try:
            result = self._run(self._prompt_once(prompt), timeout=timeout)
        except TimeoutError:
            return self._timeout_result(started, collect_dir)
        except Exception as exc:  # noqa: BLE001
            mapped = self._mapped_events()
            return AgentResult(
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
                metadata={
                    "executor_kind": "acp",
                    "acp_entry_id": self.entry_id,
                },
                repeatable=_workspace_unchanged(mapped),
            )
        self._write_vendor(collect_dir)
        return result

    async def _cancel(self) -> None:
        if self._conn is not None and self._acp_session_id is not None:
            with contextlib_suppress(Exception):
                await self._conn.cancel(session_id=self._acp_session_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self._loop is not None:
                with contextlib_suppress(Exception):
                    self._run(self._shutdown(), timeout=10.0)
                self._stop_loop()
        finally:
            # The box owns the process; dropping the pipe is our whole part.
            if self._pipe is not None:
                with contextlib_suppress(Exception):
                    self._pipe.terminate()
            self._conn = None
            self._pipe = None
            self._acp_session_id = None

    async def _shutdown(self) -> None:
        """End the ACP session and leave no task behind on the private loop."""
        if self._conn is not None and self._acp_session_id is not None:
            with contextlib_suppress(Exception):
                await self._conn.close_session(session_id=self._acp_session_id)
            with contextlib_suppress(Exception):
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
        with contextlib_suppress(Exception):
            loop.close()
