"""Parent-side model HTTP for terminus-2. Stdlib only; no Harbor and no LiteLLM."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ageval.model import API_CHAT, API_RESPONSES, ModelConfigError, ModelSpec
from ageval.model.wire import chat_body, responses_body
from ageval.runtime.clocks import ClockError, clock_seconds
from ageval.runtime.upstream_stall import current_stall

_CONFIG_STATUS = frozenset({400, 401, 403, 404, 422})
_TOKEN_KEYS = (
    ("prompt_tokens", "input_tokens"),
    ("completion_tokens", "output_tokens"),
    ("cached_tokens", "cached_read_tokens"),
)


class TransportFailure(Exception):
    """Retryable model HTTP failure. The code is the stable name."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StallExhausted(Exception):
    """The parent stall budget ended on a transport failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ModelReply:
    text: str
    usage: dict[str, int]


def transport_clocks(spec: ModelSpec) -> tuple[float, float]:
    """``(http_timeout, watchdog)`` from the shared clock table."""
    try:
        http_timeout = clock_seconds("timeout", spec.timeout)
    except ClockError as exc:
        raise ModelConfigError(f"terminus2_timeout_invalid:{spec.timeout!r}") from exc
    try:
        watchdog = clock_seconds("watchdog", spec.watchdog)
    except ClockError as exc:
        raise ModelConfigError(f"terminus2_watchdog_invalid:{spec.watchdog!r}") from exc
    return http_timeout, watchdog


def complete(
    messages: list[dict[str, Any]],
    *,
    spec: ModelSpec,
    api_key: str | None,
    base_url: str,
    invoke_timeout: float,
) -> ModelReply:
    """POST one turn. Transport failures use the current stall; config errors do not."""
    stall = current_stall()
    if stall is not None:
        stall.claim()
    failed = False
    while True:
        try:
            reply = _once(
                messages,
                spec=spec,
                api_key=api_key,
                base_url=base_url,
                invoke_timeout=invoke_timeout,
            )
        except TransportFailure as exc:
            failed = True
            if stall is None or stall.disabled or not stall.note_failure(exc.code):
                if stall is not None and not stall.disabled:
                    raise StallExhausted(exc.code) from exc
                raise
            stall.wait()
            continue
        if failed and stall is not None:
            stall.end_resumed()
        return reply


def _once(
    messages: list[dict[str, Any]],
    *,
    spec: ModelSpec,
    api_key: str | None,
    base_url: str,
    invoke_timeout: float,
) -> ModelReply:
    http_timeout, watchdog = transport_clocks(spec)
    payload = _payload(messages, spec)
    url = _endpoint(base_url, spec.api)
    raw = _post(
        url,
        payload,
        api_key=api_key,
        http_timeout=http_timeout,
        join_for=_join_for(watchdog, invoke_timeout),
    )
    text = _text(raw, spec.api)
    return ModelReply(text=text, usage=_usage(raw))


def _payload(messages: list[dict[str, Any]], spec: ModelSpec) -> dict[str, Any]:
    if spec.api == API_RESPONSES:
        body: dict[str, Any] = {"model": spec.id, "input": _responses_input(messages)}
        wire = responses_body(spec)
    elif spec.api == API_CHAT:
        body = {"model": spec.id, "messages": messages}
        wire = chat_body(spec)
    else:
        raise ModelConfigError(f"terminus2_api_invalid:{spec.api!r}")
    wire.pop("timeout", None)
    body.update(wire)
    return body


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role not in {"system", "user", "assistant", "developer"}:
            role = "user"
        out.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": str(message.get("content") or "")}],
            }
        )
    return out


def _endpoint(base_url: str, api: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ModelConfigError("terminus2_base_url_missing")
    if api == API_RESPONSES:
        return f"{base}/responses"
    return f"{base}/chat/completions"


def _join_for(watchdog: float, invoke_timeout: float) -> float:
    try:
        cap = float(invoke_timeout)
    except (TypeError, ValueError):
        return watchdog
    if cap > 0 and cap < watchdog:
        return cap
    return watchdog


def _post(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    http_timeout: float,
    join_for: float,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Connection": "close"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            with urllib.request.urlopen(request, timeout=http_timeout) as response:
                box["raw"] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            box["http_code"] = exc.code
            box["http_body"] = detail
        except json.JSONDecodeError:
            box["protocol"] = "bad_json"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            box["transport"] = type(exc).__name__

    worker = threading.Thread(target=run, name="terminus-2-http", daemon=True)
    worker.start()
    deadline = time.monotonic() + join_for
    while worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        worker.join(min(0.05, remaining))
    if worker.is_alive():
        raise TransportFailure("terminus2_watchdog")
    if "http_code" in box:
        code = int(box["http_code"])
        if code in _CONFIG_STATUS:
            raise ModelConfigError(f"terminus2_http_{code}")
        raise TransportFailure(f"terminus2_http_{code}")
    if box.get("protocol"):
        raise TransportFailure("terminus2_bad_json")
    if box.get("transport"):
        raise TransportFailure(f"terminus2_transport:{box['transport']}")
    raw = box.get("raw")
    if not isinstance(raw, dict):
        raise TransportFailure("terminus2_bad_json")
    return raw


def _text(raw: dict[str, Any], api: str) -> str:
    if api == API_RESPONSES:
        output_text = raw.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        parts: list[str] = []
        for item in raw.get("output") or []:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    try:
        message = raw["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        message = {}
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def _usage(raw: dict[str, Any]) -> dict[str, int]:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return {}
    out: dict[str, int] = {}
    for canonical, alias in _TOKEN_KEYS:
        value = usage.get(canonical)
        if not isinstance(value, int) or isinstance(value, bool):
            value = usage.get(alias)
        if isinstance(value, int) and not isinstance(value, bool):
            out[canonical] = value
    return out


__all__ = [
    "ModelReply",
    "StallExhausted",
    "TransportFailure",
    "complete",
    "transport_clocks",
]
