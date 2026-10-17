"""Anthropic Messages HTTP executor.

Thin executor only. SDK ``tools=`` / ``messages=`` stay OpenAI-shaped;
this module translates at the executor boundary. Core does not.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from ageval.model import ModelSpec, require_model_support, spec_from_factory
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.base import BaseExecutor
from ageval.plugins.contrib.anthropic_http.usage import normalize_anthropic_http_usage
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.http_loopback import is_http_loopback
from ageval.runtime.clocks import clock_seconds

_DEFAULT_BASE = "https://api.anthropic.com/v1"
_DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"
_DEFAULT_MODEL_ID = "claude-sonnet-4-6"
_DEFAULT_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096
_SOURCE = "anthropic-http"


def _normalize_openai_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
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


def anthropic_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """OpenAI ``tools=`` catalog → Anthropic ``tools[].input_schema``."""
    out: list[dict[str, Any]] = []
    for item in _normalize_openai_tools(tools):
        fn = item.get("function") if isinstance(item.get("function"), Mapping) else item
        if not isinstance(fn, Mapping):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        schema = fn.get("parameters") if isinstance(fn.get("parameters"), Mapping) else None
        row: dict[str, Any] = {
            "name": name,
            "input_schema": dict(schema) if schema else {"type": "object", "properties": {}},
        }
        desc = fn.get("description")
        if isinstance(desc, str) and desc.strip():
            row["description"] = desc
        out.append(row)
    return out


def _text_content(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, Mapping) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _tool_call_blocks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        fn = item.get("function") if isinstance(item.get("function"), Mapping) else item
        if not isinstance(fn, Mapping):
            continue
        name = str(fn.get("name") or item.get("name") or "").strip()
        if not name:
            continue
        args: Any = fn.get("arguments") if "arguments" in fn else item.get("arguments")
        if "input" in item and args is None:
            args = item.get("input")
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
            call_id = f"toolu_{len(out) + 1}"
        out.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
    return out


def anthropic_messages(
    prompt: str, messages: Sequence[Mapping[str, Any]] | None
) -> tuple[str | None, list[dict[str, Any]]]:
    """OpenAI-shaped history → Anthropic ``system`` + ``messages``."""
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        return None, [{"role": "user", "content": prompt}]
    rows = [dict(item) for item in messages if isinstance(item, Mapping)]
    if not rows:
        return None, [{"role": "user", "content": prompt}]

    system_parts: list[str] = []
    body: list[Mapping[str, Any]] = []
    for item in rows:
        role = str(item.get("role") or "")
        if role in {"system", "developer"}:
            text = _text_content(item.get("content")).strip()
            if text:
                system_parts.append(text)
            continue
        body.append(item)

    out: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def _flush_results() -> None:
        nonlocal pending_results
        if pending_results:
            out.append({"role": "user", "content": pending_results})
            pending_results = []

    for item in body:
        role = str(item.get("role") or "")
        if role in {"tool", "function"}:
            content = item.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(item.get("tool_call_id") or item.get("id") or ""),
                    "content": content,
                }
            )
            continue
        _flush_results()
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _text_content(item.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            blocks.extend(_tool_call_blocks(item.get("tool_calls")))
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue
        text = _text_content(item.get("content"))
        out.append({"role": "user", "content": text if text else prompt})

    _flush_results()
    if not out:
        out = [{"role": "user", "content": prompt}]
    system = "\n".join(system_parts) if system_parts else None
    return system, out


def _parse_tool_use(blocks: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(blocks, list):
        return ()
    out: list[dict[str, Any]] = []
    for item in blocks:
        if not isinstance(item, Mapping) or item.get("type") != "tool_use":
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        args = item.get("input") if isinstance(item.get("input"), dict) else {}
        call_id = str(item.get("id") or "")
        if not call_id:
            call_id = f"toolu_{len(out) + 1}"
        out.append({"id": call_id, "name": name, "arguments": args})
    return tuple(out)


def _parse_text(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for item in blocks:
        if not isinstance(item, Mapping) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "".join(parts)


def _parse_thought(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for item in blocks:
        if not isinstance(item, Mapping) or item.get("type") != "thinking":
            continue
        text = item.get("thinking")
        if not isinstance(text, str) or not text.strip():
            alt = item.get("text")
            text = alt if isinstance(alt, str) else ""
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def _as_max_tokens(raw: Any) -> int:
    if raw is None or raw == "":
        return _DEFAULT_MAX_TOKENS
    if isinstance(raw, bool) or not isinstance(raw, int):
        from ageval.plugins.errors import ExtensionMaterializeError

        raise ExtensionMaterializeError(
            "anthropic_max_tokens_invalid",
            kind="extension_materialize_failed",
        )
    if raw < 1:
        from ageval.plugins.errors import ExtensionMaterializeError

        raise ExtensionMaterializeError(
            "anthropic_max_tokens_invalid",
            kind="extension_materialize_failed",
        )
    return raw


def _as_version(raw: Any) -> str:
    if raw is None or raw == "":
        return _DEFAULT_VERSION
    if not isinstance(raw, str) or not raw.strip():
        from ageval.plugins.errors import ExtensionMaterializeError

        raise ExtensionMaterializeError(
            "anthropic_version_invalid",
            kind="extension_materialize_failed",
        )
    return raw.strip()


@executor_plugin(priority=120, source="first-party")
class AnthropicHTTPExecutor(BaseExecutor):
    """Messages API executor. No box. Thinking travels in ``extra.thinking``."""

    kind = "anthropic-http"
    requires_environment = False
    supported_apis = frozenset({"chat"})
    supported_model_fields = frozenset({"id", "api", "timeout", "watchdog", "extra"})
    extra_allowlist = frozenset({"thinking"})

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
        opts = options if isinstance(options, Mapping) else {}
        spec = spec_from_factory(model, opts, default_id=_DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)
        self.max_tokens = _as_max_tokens(opts.get("max_tokens"))
        self.anthropic_version = _as_version(opts.get("anthropic_version"))

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
        self.http_timeout = spec.timeout
        self.watchdog = clock_seconds("watchdog", spec.watchdog)
        self.extra = dict(spec.extra)

    def close(self) -> None:
        return None

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
        key_env = self.api_key_env or _DEFAULT_KEY_ENV
        key = os.environ.get(key_env, "")
        base = self.base_url or os.environ.get("AGEVAL_ANTHROPIC_BASE_URL") or _DEFAULT_BASE
        loopback = is_http_loopback(base)
        if not key and not loopback:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="missing_credential",
            )
        from ageval.runtime.offline import is_offline_agent

        if is_offline_agent() and not loopback:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="offline_forced",
            )
        url = f"{base.rstrip('/')}/messages"
        system, chat = anthropic_messages(prompt, messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": chat,
            "temperature": 0,
        }
        if system:
            payload["system"] = system
        catalog = anthropic_tools(tools)
        if catalog:
            payload["tools"] = catalog
        if self.extra:
            payload.update(copy.deepcopy(self.extra))
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        if key:
            headers["x-api-key"] = key
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        kind, found = _exchange(
            req,
            http_timeout=self.http_timeout if self.http_timeout is not None else timeout,
            watchdog=self.watchdog,
            invoke_timeout=timeout,
        )
        if kind == "watchdog":
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=f"TimeoutError:anthropic_http_watchdog:{self.watchdog:g}",
                metadata={"executor_kind": "anthropic-http"},
            )
        if kind == "http":
            assert isinstance(found, dict)
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=f"HTTPError:{found['http_code']}",
                metadata={
                    "executor_kind": "anthropic-http",
                    "http_error_body": found.get("http_body"),
                },
            )
        if kind == "transport":
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=str(found),
                metadata={"executor_kind": "anthropic-http"},
            )
        raw = found if isinstance(found, dict) else {}
        blocks = raw.get("content") if isinstance(raw, dict) else None
        text = _parse_text(blocks)
        thought = _parse_thought(blocks)
        tool_calls = _parse_tool_use(blocks)
        if not text and not tool_calls and isinstance(raw, dict):
            text = json.dumps(raw)[:4000]
        structured = None
        try:
            structured = json.loads(text) if text else None
            if not isinstance(structured, dict):
                structured = None
        except json.JSONDecodeError:
            structured = None
        events: list[dict[str, Any]] = []
        if thought:
            events.append(
                {
                    "kind": "text",
                    "channel": "thought",
                    "text": thought[-8000:],
                    "source": _SOURCE,
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
                "source": _SOURCE,
            }
            for call in tool_calls
        )
        if collect_dir:
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
        usage, extra = normalize_anthropic_http_usage(
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
            extra=extra,
            metadata={"executor_kind": "anthropic-http"},
        )


def _exchange(
    req: urllib.request.Request,
    *,
    http_timeout: float,
    watchdog: float,
    invoke_timeout: float,
) -> tuple[str, Any]:
    """POST under the HTTP clock and the watchdog. Expiry is transport, not config."""
    if http_timeout is None or http_timeout <= 0:
        http_timeout = watchdog
    join_for = watchdog
    watchdog_ceiling = True
    try:
        invoke_cap = float(invoke_timeout)
    except (TypeError, ValueError):
        invoke_cap = watchdog
    if invoke_cap > 0 and invoke_cap < watchdog:
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

    worker = threading.Thread(target=_post, name="anthropic-http", daemon=True)
    worker.start()
    worker.join(join_for)
    if worker.is_alive():
        return ("watchdog" if watchdog_ceiling else "transport"), (
            None if watchdog_ceiling else "TimeoutError"
        )
    if "http_code" in box:
        return "http", box
    if "transport" in box:
        return "transport", box["transport"]
    return "ok", box.get("raw")
