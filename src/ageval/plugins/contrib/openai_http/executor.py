"""Second AgentExecutor: OpenAI-compatible HTTP Chat backend.

Thin executor only — no Run/credential store ownership beyond scoped API key env.
Profile may supply ``base_url`` and ``api_key`` (env locator name).
Native ``tools=`` is first-class; omit the catalog to keep the content path.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from ageval.evidence.redaction import IncrementalTextRedactor
from ageval.model import ModelSpec, require_model_support, spec_from_factory
from ageval.model.errors import (
    ModelConfigError,
    ProtocolError,
    TransportStall,
    http_status_is_config_error,
)
from ageval.model.usage import LOST_ON_TIMEOUT, NOT_REPORTED, adopt_usage
from ageval.model.wire import chat_body, responses_body
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.base import BaseExecutor
from ageval.plugins.contrib.openai_http.options import OpenAIHTTPOptions
from ageval.plugins.contrib.openai_http.parse import (
    chat_text_and_calls,
    responses_text_and_calls,
)
from ageval.plugins.contrib.openai_http.stream import (
    ChatAssembler,
    ResponsesAssembler,
    provider_error_from_body,
)
from ageval.plugins.contrib.openai_http.usage import normalize_openai_http_usage
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.http_activity import (
    ModelTurnDeltaWriter,
    abort_model_turn,
    begin_model_turn,
    finish_model_turn,
    messages_for_turn,
)
from ageval.plugins.http_loopback import is_http_loopback
from ageval.plugins.http_stream import StreamProgressJournal, exchange_sse
from ageval.plugins.options import coerce_options, mapping_for_model
from ageval.runtime.clocks import clock_seconds

_DEFAULT_BASE = "https://api.openai.com/v1"
_DEFAULT_KEY_ENV = "OPENAI_API_KEY"
_DEFAULT_MODEL_ID = "gpt-4.1-mini"


def _chat_messages(
    prompt: str, messages: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, Any]]:
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        out = [dict(item) for item in messages if isinstance(item, Mapping)]
        if out:
            return out
    return [{"role": "user", "content": prompt}]


def _normalize_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        return []
    out: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "function" and isinstance(item.get("function"), Mapping):
            out.append(dict(item))
            continue
        name = str(item.get("name") or "")
        if not name:
            fn = item.get("function")
            if isinstance(fn, Mapping):
                name = str(fn.get("name") or "")
                if name:
                    out.append({"type": "function", "function": dict(fn)})
            continue
        spec: dict[str, Any] = {"name": name}
        if item.get("description"):
            spec["description"] = item["description"]
        if isinstance(item.get("parameters"), Mapping):
            spec["parameters"] = dict(item["parameters"])
        out.append({"type": "function", "function": spec})
    return out


def _responses_tools(catalog: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Chat-shaped tool rows to the flat Responses shape."""
    out: list[dict[str, Any]] = []
    for row in catalog:
        fn = row.get("function")
        if not isinstance(fn, Mapping) or not fn.get("name"):
            continue
        flat: dict[str, Any] = {"type": "function", "name": str(fn["name"])}
        if fn.get("description"):
            flat["description"] = fn["description"]
        if isinstance(fn.get("parameters"), Mapping):
            flat["parameters"] = dict(fn["parameters"])
        out.append(flat)
    return out


def _responses_function_calls(raw: Any) -> list[dict[str, Any]]:
    """Chat ``tool_calls`` on an assistant turn to Responses ``function_call`` items."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for call in raw:
        if not isinstance(call, Mapping):
            continue
        fn = call.get("function") if isinstance(call.get("function"), Mapping) else call
        assert isinstance(fn, Mapping)
        name = str(fn.get("name") or "")
        if not name:
            continue
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)
        out.append(
            {
                "type": "function_call",
                "call_id": str(call.get("id") or call.get("call_id") or ""),
                "name": name,
                "arguments": args,
            }
        )
    return out


def _responses_input(
    prompt: str, messages: Sequence[Mapping[str, Any]] | None
) -> str | list[dict[str, Any]]:
    """Responses ``input``. A bare prompt stays a string. History becomes items."""
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        return prompt
    rows = [dict(item) for item in messages if isinstance(item, Mapping)]
    if not rows:
        return prompt
    items: list[dict[str, Any]] = []
    for item in rows:
        role = str(item.get("role") or "user")
        content = item.get("content")
        if content is None:
            text = ""
        elif isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, ensure_ascii=False)
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(item.get("tool_call_id") or ""),
                    "output": text,
                }
            )
            continue
        calls = _responses_function_calls(item.get("tool_calls")) if role == "assistant" else []
        if text or not calls:
            items.append(
                {
                    "type": "message",
                    "role": "assistant" if role == "assistant" else "user",
                    "content": text,
                }
            )
        items.extend(calls)
    return items


@executor_plugin(priority=120, source="first-party")
class OpenAIHTTPExecutor(BaseExecutor):
    """HTTP executor for Chat Completions and Responses. No box."""

    kind = "openai-http"
    requires_environment = False
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist = frozenset({"provider"})
    concurrent_sessions = True
    Options = OpenAIHTTPOptions

    def __init__(
        self,
        *,
        options: Mapping[str, Any] | None = None,
        profile_id: str | None = None,
        model: Any = None,
        base_url: str | None = None,
        api_key: str | None = None,
        **_kwargs: Any,
    ) -> None:
        del profile_id
        self.base_url = base_url.strip() if isinstance(base_url, str) and base_url.strip() else None
        self.api_key_env = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        raw = mapping_for_model(options)
        spec = spec_from_factory(model, raw, default_id=_DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)
        self.options = (
            options
            if isinstance(options, OpenAIHTTPOptions)
            else coerce_options(OpenAIHTTPOptions, raw)
        )
        self._stream_meta: dict[str, object] = {}
        self._delta_writer: ModelTurnDeltaWriter | None = None

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
        self.api = spec.api
        self.reasoning_effort = spec.reasoning_effort
        self.http_timeout = clock_seconds("timeout", spec.timeout)
        self.watchdog = clock_seconds("watchdog", spec.watchdog)
        self.extra = dict(spec.extra)
        self._invoke_cancel = threading.Event()

    def close(self) -> None:
        self.cancel_invoke()

    def prepare_invoke(self) -> None:
        self._invoke_cancel.clear()

    def cancel_invoke(self) -> None:
        """Stop waiting on this process. Does not abort the remote provider."""
        self._invoke_cancel.set()

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
        self._stream_sentinels = tuple(redaction_sentinels or ())
        messages = messages_for_turn(self, prompt, messages)
        self._stream_meta = {}
        self._delta_writer = None
        if self._invoke_cancel.is_set():
            return self._result(ok=False, error="invoke_cancelled", effort=self.reasoning_effort)
        key_env = self.api_key_env or _DEFAULT_KEY_ENV
        key = os.environ.get(key_env, "")
        base = self.base_url or os.environ.get("AGEVAL_OPENAI_BASE_URL") or _DEFAULT_BASE
        loopback = is_http_loopback(base)
        effort = self.reasoning_effort
        if not key and not loopback:
            return self._result(ok=False, error="missing_credential", effort=effort)
        from ageval.runtime.offline import is_offline_agent

        if is_offline_agent() and not loopback:
            return self._result(ok=False, error="offline_forced", effort=effort)
        responses = self.api == "responses"
        suffix = "/responses" if responses else "/chat/completions"
        url = f"{base.rstrip('/')}{suffix}"
        payload = self._payload(prompt, messages, tools, responses=responses, effort=effort)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        streamed = self.options.stream
        self._activity_step = begin_model_turn(self, prompt, messages)
        outcome = None
        try:
            if streamed:
                outcome = self._stream_exchange(
                    req,
                    responses=responses,
                    timeout=timeout,
                    collect_dir=collect_dir,
                )
                kind, found = outcome.kind, outcome.detail
                self._stream_meta = dict(outcome.metrics)
            else:
                kind, found = self._exchange(req, timeout=timeout)
        except Exception:  # noqa: BLE001 — a transport crash still closes the model turn
            abort_model_turn(self, self._activity_step, reason="process_interrupted")
            self._activity_step = None
            raise
        snapshot = outcome.snapshot if outcome is not None else None
        if kind == "cancelled":
            return self._result(
                ok=False,
                error="invoke_cancelled",
                effort=effort,
                repeatable=False,
                text=snapshot.text if snapshot is not None else "",
                events=_stream_error_events(snapshot) if snapshot is not None else (),
                thought=snapshot.thought if snapshot is not None else None,
                stop_reason=snapshot.stop_reason if snapshot is not None else None,
                usage=_partial_usage(snapshot, timeout=False) if snapshot is not None else None,
                metadata=_stream_error_metadata(snapshot, fallback="cancelled")
                if streamed
                else None,
            )
        if kind == "watchdog":
            message = f"TimeoutError:openai_http_watchdog:{self.watchdog:g}"
            return self._result(
                ok=False,
                error=message,
                effort=effort,
                failure=TransportStall(message, kind="watchdog"),
                text=snapshot.text if snapshot is not None else "",
                events=_stream_error_events(snapshot) if snapshot is not None else (),
                thought=snapshot.thought if snapshot is not None else None,
                stop_reason=snapshot.stop_reason if snapshot is not None else None,
                usage=_partial_usage(snapshot, timeout=True) if snapshot is not None else None,
                metadata=_stream_error_metadata(snapshot, fallback="timeout") if streamed else None,
            )
        if kind == "protocol":
            message = f"ProtocolError:{found}"
            return self._result(
                ok=False,
                error=message,
                effort=effort,
                failure=ProtocolError(message, kind=str(found or "bad_json")),
                repeatable=False,
                text=snapshot.text if snapshot is not None else "",
                events=_stream_error_events(snapshot) if snapshot is not None else (),
                thought=snapshot.thought if snapshot is not None else None,
                stop_reason=snapshot.stop_reason if snapshot is not None else None,
                usage=_partial_usage(snapshot, timeout=False) if snapshot is not None else None,
                metadata=_stream_error_metadata(snapshot, fallback="parse") if streamed else None,
            )
        if kind == "http":
            assert isinstance(found, dict)
            code = int(found["http_code"])
            http_error = provider_error_from_body(found.get("http_body"), status_code=code)
            meta: dict[str, Any] = {
                "http_error": http_error,
                "error_origin": "http",
            }
            if streamed:
                meta["answer_complete"] = False
            if http_status_is_config_error(code):
                # The gateway rejected the request itself; resending cannot help.
                meta["error_kind"] = ModelConfigError.kind
                message = f"ModelConfigError:HTTPError:{code}"
                return self._result(
                    ok=False,
                    error=message,
                    effort=effort,
                    metadata=meta,
                    repeatable=False,
                    failure=ModelConfigError(message),
                )
            message = f"HTTPError:{code}"
            return self._result(
                ok=False,
                error=message,
                effort=effort,
                metadata=meta,
                failure=TransportStall(message, kind="http"),
            )
        if kind == "transport":
            message = str(found)
            timeout_kind = (
                str(found)
                if str(found) in {"stream_first_event_timeout", "stream_idle_timeout"}
                else "transport"
            )
            return self._result(
                ok=False,
                error=message,
                effort=effort,
                failure=TransportStall(message, kind=timeout_kind),
                text=snapshot.text if snapshot is not None else "",
                events=_stream_error_events(snapshot) if snapshot is not None else (),
                thought=snapshot.thought if snapshot is not None else None,
                stop_reason=snapshot.stop_reason if snapshot is not None else None,
                usage=_partial_usage(snapshot, timeout=True) if snapshot is not None else None,
                metadata=_stream_error_metadata(
                    snapshot,
                    fallback="timeout"
                    if timeout_kind in {"stream_first_event_timeout", "stream_idle_timeout"}
                    else "transport",
                )
                if streamed
                else None,
            )
        raw = found if isinstance(found, dict) else {}
        if responses:
            text, thought, tool_calls = responses_text_and_calls(raw)
        else:
            text, thought, tool_calls = chat_text_and_calls(raw)
        stop_reason = _stream_stop_reason(raw, responses) if streamed else None
        if streamed and not (text or "").strip() and not tool_calls:
            return self._result(
                ok=False,
                error="ProtocolError:stream_empty_answer",
                effort=effort,
                failure=ProtocolError(
                    "ProtocolError:stream_empty_answer", kind="stream_empty_answer"
                ),
                repeatable=False,
                text=snapshot.text if snapshot is not None else "",
                events=_stream_error_events(snapshot) if snapshot is not None else (),
                thought=snapshot.thought if snapshot is not None else None,
                stop_reason=stop_reason,
                usage=_partial_usage(snapshot, timeout=False) if snapshot is not None else None,
                metadata=_stream_error_metadata(snapshot, fallback="parse") if streamed else None,
            )
        structured = _json_object(text)
        if streamed:
            events = list(snapshot.events) if snapshot is not None else []
            events.extend(_events("", tool_calls))
        else:
            events = _events(thought, tool_calls)
        if collect_dir:
            _write_exchange(collect_dir, payload, raw)
        usage, usage_extra = normalize_openai_http_usage(
            raw.get("usage") if isinstance(raw, dict) else None,
            response_id=raw.get("id") if isinstance(raw, dict) else None,
        )
        meta_extra: dict[str, object] | None = None
        if streamed:
            meta_extra = {"stop_reason": stop_reason, "answer_complete": True}
        return self._seal_activity(
            AgentResult(
                model=self.model,
                text=(text or "")[-8000:],
                structured=structured,
                ok=True,
                error=None,
                events=tuple(events),
                tool_calls=tool_calls,
                usage=adopt_usage(usage),
                extra=usage_extra,
                metadata=self._meta(effort, actual=effort, extra=meta_extra),
            ),
            thought=thought or None,
            stop_reason=stop_reason,
        )

    def _payload(
        self,
        prompt: str,
        messages: Sequence[Mapping[str, Any]] | None,
        tools: Sequence[Mapping[str, Any]] | None,
        *,
        responses: bool,
        effort: str | None,
    ) -> dict[str, Any]:
        catalog = _normalize_tools(tools)
        if responses:
            payload: dict[str, Any] = {
                "model": self.model,
                "input": _responses_input(prompt, messages),
            }
        else:
            payload = {
                "model": self.model,
                "messages": _chat_messages(prompt, messages),
                "temperature": 0,
            }
        if catalog:
            payload["tools"] = _responses_tools(catalog) if responses else catalog
        wire = responses_body(self.spec) if responses else chat_body(self.spec)
        # The HTTP clock is ``http_timeout``. The JSON body does not repeat it.
        wire.pop("timeout", None)
        payload.update(wire)
        if self.options.stream:
            payload["stream"] = True
            if not responses:
                # Chat Completions reports final usage on the stream.
                payload["stream_options"] = {"include_usage": True}
        del effort
        return payload

    def _ceiling(self, timeout: float) -> tuple[float, bool]:
        """Total exchange ceiling and whether the watchdog owns it."""
        join_for = self.watchdog
        try:
            invoke_cap = float(timeout)
        except (TypeError, ValueError):
            invoke_cap = self.watchdog
        watchdog_ceiling = True
        if invoke_cap > 0 and invoke_cap < self.watchdog:
            join_for = invoke_cap
            watchdog_ceiling = False
        return join_for, watchdog_ceiling

    def _exchange(self, req: urllib.request.Request, *, timeout: float) -> tuple[str, Any]:
        """POST under the HTTP clock and the watchdog.

        The watchdog is the abort ceiling unless this invoke's timeout is
        shorter. Expiry is a repeatable transport error. HTTP and decode
        failures stay on this thread's result, not a second stall path.
        """
        http_timeout = self.http_timeout
        join_for, watchdog_ceiling = self._ceiling(timeout)
        box: dict[str, Any] = {}

        def _post() -> None:
            try:
                with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                    box["raw"] = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                box["http_code"] = exc.code
                box["http_body"] = exc.read().decode("utf-8", errors="replace")[:800]
            except json.JSONDecodeError:
                box["protocol"] = "bad_json"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                box["transport"] = type(exc).__name__

        worker = threading.Thread(target=_post, name="openai-http", daemon=True)
        worker.start()
        deadline = time.monotonic() + join_for
        while worker.is_alive():
            if self._invoke_cancel.is_set():
                return "cancelled", None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(min(0.05, remaining))
        if self._invoke_cancel.is_set():
            return "cancelled", None
        if worker.is_alive():
            return ("watchdog" if watchdog_ceiling else "transport"), (
                None if watchdog_ceiling else "TimeoutError"
            )
        if "http_code" in box:
            return "http", box
        if "protocol" in box:
            return "protocol", box["protocol"]
        if "transport" in box:
            return "transport", box["transport"]
        return "ok", box.get("raw")

    def _stream_exchange(
        self,
        req: urllib.request.Request,
        *,
        responses: bool,
        timeout: float,
        collect_dir: str | None,
    ) -> Any:
        """Consume one SSE turn under the outer clock. No reconnect or replay."""
        total_timeout, watchdog_ceiling = self._ceiling(timeout)
        writer = ModelTurnDeltaWriter(self, getattr(self, "_activity_step", None))
        self._delta_writer = writer
        consumer = ResponsesAssembler(writer) if responses else ChatAssembler(writer)
        journal = StreamProgressJournal(collect_dir)
        try:
            return exchange_sse(
                req,
                consumer=consumer,
                http_timeout=self.http_timeout,
                total_timeout=total_timeout,
                watchdog_ceiling=watchdog_ceiling,
                cancel=self._invoke_cancel,
                first_event_timeout=self.options.stream_first_event_timeout_seconds,
                idle_timeout=self.options.stream_idle_timeout_seconds,
                on_event=journal,
                exchange_id=journal.exchange_id,
            )
        finally:
            writer.close()
            journal.close()
            self._delta_writer = None

    def _result(
        self,
        *,
        ok: bool,
        error: str,
        effort: str | None,
        metadata: dict[str, Any] | None = None,
        repeatable: bool = True,
        failure: BaseException | None = None,
        text: str = "",
        events: Sequence[Mapping[str, Any]] = (),
        thought: str | None = None,
        stop_reason: str | None = None,
        usage: Any = None,
    ) -> AgentResult:
        if usage is None:
            usage = LOST_ON_TIMEOUT if isinstance(failure, TransportStall) else NOT_REPORTED
        extra = dict(metadata) if metadata else {}
        if stop_reason is not None:
            extra["stop_reason"] = stop_reason
        return self._seal_activity(
            AgentResult(
                model=self.model,
                text=text,
                structured=None,
                ok=ok,
                error=error,
                events=tuple(dict(item) for item in events),
                metadata=self._meta(effort, actual=None, extra=extra or None),
                repeatable=repeatable,
                failure=failure,
                usage=usage,
            ),
            thought=thought,
            stop_reason=stop_reason,
        )

    def _seal_activity(
        self,
        result: AgentResult,
        *,
        thought: str | None = None,
        stop_reason: str | None = None,
    ) -> AgentResult:
        if self.options.stream:
            result = replace(
                result, events=_redact_stream_events(result.events, self._stream_sentinels)
            )
        step = getattr(self, "_activity_step", None)
        self._activity_step = None
        return finish_model_turn(
            self,
            step if isinstance(step, int) else None,
            result,
            thought=thought,
            stop_reason=stop_reason,
        )

    def _meta(
        self,
        effort: str | None,
        *,
        actual: str | None,
        extra: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "executor_kind": "openai-http",
            "api": self.api,
            "locked_reasoning_effort": effort,
            "actual_reasoning_effort": actual,
        }
        if self._stream_meta:
            meta.update(self._stream_meta)
            correlation = {
                key: meta.pop(key)
                for key in (
                    "exchange_id",
                    "x_client_request_id",
                    "x_litellm_call_id",
                    "x_request_id",
                )
                if isinstance(meta.get(key), str) and meta.get(key)
            }
            if correlation:
                meta["stream_correlation"] = correlation
        if extra:
            meta.update(extra)
        return meta


def _redact_stream_events(
    events: Sequence[dict[str, Any]], sentinels: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    """Keep fragment context when invocation events are sealed after transport."""
    redactors: dict[str, IncrementalTextRedactor] = {}
    last: dict[str, int] = {}
    output: list[dict[str, Any]] = []
    for event in events:
        if event.get("kind") != "text" or not isinstance(event.get("text"), str):
            output.append(dict(event))
            continue
        channel = str(event.get("channel") or "assistant")
        last[channel] = len(output)
        redactor = redactors.setdefault(channel, IncrementalTextRedactor(extra_sentinels=sentinels))
        text = redactor.feed(event["text"])
        output.append({**event, "text": text})
    for channel, redactor in redactors.items():
        text = redactor.feed("", final=True)
        if text:
            output[last[channel]]["text"] += text
    return tuple(output)


def _stream_error_metadata(snapshot: Any, *, fallback: str) -> dict[str, object]:
    details = (
        dict(snapshot.error_details) if snapshot is not None and snapshot.error_details else None
    )
    origin = fallback
    if details is not None:
        raw_origin = details.get("origin")
        if isinstance(raw_origin, str) and raw_origin:
            origin = raw_origin
    meta: dict[str, object] = {"answer_complete": False, "error_origin": origin}
    if details is not None:
        meta["stream_error"] = details
    return meta


def _stream_error_events(snapshot: Any) -> tuple[Mapping[str, Any], ...]:
    events = [dict(item) for item in snapshot.events]
    events.extend(_events("", snapshot.tool_calls))
    return tuple(events)


def _partial_usage(snapshot: Any, *, timeout: bool) -> Any:
    usage, _extra = normalize_openai_http_usage(snapshot.usage)
    return adopt_usage(usage, timeout=timeout, partial=not timeout and usage is not None)


def _stream_stop_reason(raw: Mapping[str, Any], responses: bool) -> str:
    if responses:
        status = raw.get("status")
        return status if isinstance(status, str) and status else "completed"
    choices = raw.get("choices")
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            reason = first.get("finish_reason")
            if isinstance(reason, str) and reason:
                return reason
    return "stop"


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        structured = json.loads(text) if text else None
    except json.JSONDecodeError:
        return None
    return structured if isinstance(structured, dict) else None


def _events(thought: str, tool_calls: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if thought:
        events.append(
            {
                "kind": "text",
                "channel": "thought",
                "text": thought[-8000:],
                "source": "openai-http",
            }
        )
    events.extend(
        {
            "kind": "tool",
            "phase": "start",
            "tool_call_id": call["id"],
            "function_name": call["name"],
            "title": call["name"],
            "args": call["arguments"],
            "status": "pending",
            "source": "openai-http",
        }
        for call in tool_calls
    )
    return events


def _write_exchange(collect_dir: str, payload: Mapping[str, Any], raw: Any) -> None:
    from pathlib import Path

    out = Path(collect_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "request.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "response.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
