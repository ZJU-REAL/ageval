"""Second AgentExecutor: OpenAI-compatible HTTP Chat backend.

Thin executor only — no Run/credential store ownership beyond scoped API key env.
Profile may supply ``base_url`` and ``api_key`` (env locator name).
Native ``tools=`` is first-class; omit the catalog to keep the content path.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from ageval.model import ModelSpec, require_model_support, spec_from_factory
from ageval.model.errors import ModelConfigError, http_status_is_config_error
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.base import BaseExecutor
from ageval.plugins.contrib.openai_http.usage import normalize_openai_http_usage
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.http_loopback import is_http_loopback
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


def _parse_tool_calls(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        fn = item.get("function") if isinstance(item.get("function"), Mapping) else item
        if not isinstance(fn, Mapping):
            continue
        name = str(fn.get("name") or item.get("name") or "")
        if not name:
            continue
        args: Any = fn.get("arguments") if "arguments" in fn else item.get("arguments")
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                parsed = {}
            args = parsed if isinstance(parsed, dict) else {}
        elif not isinstance(args, dict):
            args = {}
        call_id = str(item.get("id") or "")
        if not call_id:
            call_id = f"call_{len(out) + 1}"
        out.append(
            {
                "id": call_id,
                "name": name,
                "arguments": args,
            }
        )
    return tuple(out)


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


def _responses_text_and_calls(
    raw: Mapping[str, Any],
) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    """Read Responses ``output`` text, reasoning summary, and function calls."""
    texts: list[str] = []
    thoughts: list[str] = []
    calls: list[dict[str, Any]] = []
    output = raw.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("type") or "")
            if kind == "reasoning":
                summary = item.get("summary")
                if isinstance(summary, list):
                    for part in summary:
                        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                            thoughts.append(part["text"])
                elif isinstance(item.get("content"), str):
                    thoughts.append(item["content"])
                continue
            if kind == "function_call":
                name = str(item.get("name") or "")
                if not name:
                    continue
                args: Any = item.get("arguments")
                if isinstance(args, str):
                    try:
                        parsed = json.loads(args)
                    except json.JSONDecodeError:
                        parsed = {}
                    args = parsed if isinstance(parsed, dict) else {}
                elif not isinstance(args, dict):
                    args = {}
                call_id = (
                    str(item.get("call_id") or item.get("id") or "") or f"call_{len(calls) + 1}"
                )
                calls.append({"id": call_id, "name": name, "arguments": args})
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if part.get("type") in {"output_text", "text"} and isinstance(
                        part.get("text"), str
                    ):
                        texts.append(part["text"])
            elif isinstance(content, str):
                texts.append(content)
    if not texts and isinstance(raw.get("output_text"), str):
        texts.append(raw["output_text"])
    return "".join(texts), "\n".join(thoughts), tuple(calls)


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
        spec = spec_from_factory(model, options, default_id=_DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)

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
        return None

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
        del redaction_sentinels
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
        kind, found = self._exchange(req, timeout=timeout)
        if kind == "cancelled":
            return self._result(
                ok=False,
                error="invoke_cancelled",
                effort=effort,
                repeatable=False,
            )
        if kind == "watchdog":
            return self._result(
                ok=False,
                error=f"TimeoutError:openai_http_watchdog:{self.watchdog:g}",
                effort=effort,
            )
        if kind == "http":
            assert isinstance(found, dict)
            code = int(found["http_code"])
            meta: dict[str, Any] = {"http_error_body": found.get("http_body")}
            if http_status_is_config_error(code):
                # The gateway rejected the request itself; resending cannot help.
                meta["error_kind"] = ModelConfigError.kind
                return self._result(
                    ok=False,
                    error=f"ModelConfigError:HTTPError:{code}",
                    effort=effort,
                    metadata=meta,
                    repeatable=False,
                )
            return self._result(
                ok=False,
                error=f"HTTPError:{code}",
                effort=effort,
                metadata=meta,
            )
        if kind == "transport":
            return self._result(ok=False, error=str(found), effort=effort)
        raw = found if isinstance(found, dict) else {}
        if responses:
            text, thought, tool_calls = _responses_text_and_calls(raw)
        else:
            text, thought, tool_calls = _chat_text_and_calls(raw)
        structured = _json_object(text)
        events = _events(thought, tool_calls)
        if collect_dir:
            _write_exchange(collect_dir, payload, raw)
        usage, usage_extra = normalize_openai_http_usage(
            raw.get("usage") if isinstance(raw, dict) else None,
            response_id=raw.get("id") if isinstance(raw, dict) else None,
        )
        return AgentResult(
            model=self.model,
            text=(text or "")[-8000:],
            structured=structured,
            ok=True,
            error=None,
            events=tuple(events),
            tool_calls=tool_calls,
            usage=usage,
            extra=usage_extra,
            metadata=self._meta(effort, actual=effort),
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
        if self.extra:
            payload.update(copy.deepcopy(self.extra))
        if effort:
            if responses:
                payload["reasoning"] = {"effort": effort}
            else:
                payload["reasoning_effort"] = effort
        return payload

    def _exchange(self, req: urllib.request.Request, *, timeout: float) -> tuple[str, Any]:
        """POST under the HTTP clock and the watchdog.

        The watchdog is the abort ceiling unless this invoke's timeout is
        shorter. Expiry is a repeatable transport error. HTTP and decode
        failures stay on this thread's result, not a second stall path.
        """
        http_timeout = self.http_timeout
        join_for = self.watchdog
        try:
            invoke_cap = float(timeout)
        except (TypeError, ValueError):
            invoke_cap = self.watchdog
        watchdog_ceiling = True
        if invoke_cap > 0 and invoke_cap < self.watchdog:
            join_for = invoke_cap
            watchdog_ceiling = False
        box: dict[str, Any] = {}

        def _post() -> None:
            try:
                with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                    box["raw"] = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                box["http_code"] = exc.code
                box["http_body"] = exc.read().decode("utf-8", errors="replace")[:800]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
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
        if "transport" in box:
            return "transport", box["transport"]
        return "ok", box.get("raw")

    def _result(
        self,
        *,
        ok: bool,
        error: str,
        effort: str | None,
        metadata: dict[str, Any] | None = None,
        repeatable: bool = True,
    ) -> AgentResult:
        return AgentResult(
            model=self.model,
            text="",
            structured=None,
            ok=ok,
            error=error,
            metadata=self._meta(effort, actual=None, extra=metadata),
            repeatable=repeatable,
        )

    def _meta(
        self,
        effort: str | None,
        *,
        actual: str | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "executor_kind": "openai-http",
            "api": self.api,
            "locked_reasoning_effort": effort,
            "actual_reasoning_effort": actual,
        }
        if extra:
            meta.update(extra)
        return meta


def _chat_text_and_calls(
    raw: Mapping[str, Any],
) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    message: Mapping[str, Any] = {}
    try:
        choice0 = raw["choices"][0]
        found = choice0["message"]
        if isinstance(found, Mapping):
            message = found
    except (KeyError, IndexError, TypeError):
        message = {}
    text = message.get("content") if isinstance(message.get("content"), str) else ""
    if not text and not message:
        text = json.dumps(raw)[:4000]
    thought = ""
    for key in ("reasoning_content", "reasoning"):
        raw_thought = message.get(key)
        if isinstance(raw_thought, str) and raw_thought.strip():
            thought = raw_thought
            break
    return text or "", thought, _parse_tool_calls(message.get("tool_calls"))


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
