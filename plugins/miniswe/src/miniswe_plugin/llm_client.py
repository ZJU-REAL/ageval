"""Ephemeral HTTP clients for miniswe LLM calls.

LiteLLM caches OpenAI / custom httpx clients in ``in_memory_llm_clients_cache``
and reuses keep-alive sockets across turns. Against sticky LiteLLM gateways
that leaves ESTAB connections with a large Send-Q stuck in
``_receive_response_headers``. Direct one-shot httpx POSTs of the same body
succeed; the hung path is the cached keep-alive client.

Chat Completions: **do not** call ``litellm.completion`` for suite runs.
``litellm`` → OpenAI SDK can sit in ``_receive_response_headers`` past the
forced ``timeout=`` / Future watchdog (attempt_1c23ff53: ~4.5 min, no
``upstream_stall``). POST directly to ``{api_base}/chat/completions`` with an
ephemeral httpx client — same pattern as the Responses path.

Responses API: **do not** call ``litellm.responses`` (its ``HTTPHandler`` pool
keep-alives and ``client=`` injection mis-routes). POST directly to
``{api_base}/responses`` with an ephemeral httpx client — same wire shape as
``curl_responses_tools_ok.sh``.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import sys
import threading
from typing import Any, NoReturn

from miniswe_plugin.model import ModelConfigError

# Schema / auth / not-found failures are configuration. 408, 429, and 5xx stay transport.
_CONFIG_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})

# Ephemeral OpenAI/httpx clients live only in the query thread's locals. When the
# stall watchdog fires ``Future.result(timeout=…)``, ``recycle_llm_clients`` only
# clears LiteLLM's cache — it never sees the in-flight ``client=`` — so the hung
# ``_receive_response_headers`` socket stays ESTAB and can wedge the gateway for
# every retry. Track in-flight clients and close them on recycle/timeout.
_IN_FLIGHT_LOCK = threading.Lock()
_IN_FLIGHT_CLIENTS: set[Any] = set()


def _iter_httpx_pools(client: Any) -> list[Any]:
    """Collect httpx/httpcore pool objects under an OpenAI / httpx client."""
    pools: list[Any] = []
    http = (
        client
        if type(client).__name__ == "Client" and getattr(client, "_transport", None) is not None
        else None
    )
    if http is None:
        http = (
            getattr(client, "http_client", None)
            or getattr(client, "_client", None)
            or getattr(client, "client", None)
        )
    if http is None:
        return pools
    transport = getattr(http, "_transport", None)
    if transport is not None:
        pool = getattr(transport, "_pool", None)
        if pool is not None:
            pools.append(pool)
    return pools


def _shutdown_pool_sockets(pool: Any) -> None:
    """``SHUT_RDWR`` every live socket in an httpcore pool.

    ``httpx.Client.close()`` / ``pool.close()`` often returns without waking a
    thread blocked in ``_receive_response_headers`` (ESTAB, Send-Q=0) — both
    chat and responses (``post_responses_api``) hit this. Forcing
    ``socket.shutdown(SHUT_RDWR)`` unblocks that recv immediately so the
    Future watchdog can abandon instead of wedging until SIGTERM / FORCE_CLEAR
    (boa attempt_06c64f5f: kill_in_flight present, plain close did not break
    sticky recv, ≥22min with no TimeoutError reaching the suite log).
    """
    import socket as _socket

    conns = list(getattr(pool, "_connections", None) or [])
    # Public accessor (httpcore 1.x); same objects, but keep if _connections empty.
    try:
        extra = list(getattr(pool, "connections", None) or [])
    except Exception:
        extra = []
    for conn in extra:
        if conn not in conns:
            conns.append(conn)
    for conn in conns:
        inner = getattr(conn, "_connection", None) or conn
        stream = getattr(inner, "_network_stream", None)
        if stream is None:
            continue
        sock = getattr(stream, "_sock", None)
        if sock is None:
            continue
        # A socket already closed by the peer is not a stall failure.
        with contextlib.suppress(Exception):
            sock.shutdown(_socket.SHUT_RDWR)
        with contextlib.suppress(Exception):
            sock.close()


def close_llm_client(client: Any) -> None:
    """Best-effort close of an OpenAI / httpx / LiteLLM HTTPHandler client.

    Prefers ``socket.shutdown(SHUT_RDWR)`` on in-flight httpcore sockets before
    ``close()`` — plain ``close()`` does not reliably unblock
    ``_receive_response_headers``.
    """
    if client is None:
        return
    for pool in _iter_httpx_pools(client):
        _shutdown_pool_sockets(pool)
    targets: list[Any] = [
        client,
        getattr(client, "http_client", None),
        getattr(client, "_client", None),
        # litellm.llms.custom_httpx.http_handler.HTTPHandler wraps ``.client``.
        getattr(client, "client", None),
    ]
    http = (
        getattr(client, "_client", None)
        or getattr(client, "http_client", None)
        or getattr(client, "client", None)
    )
    if http is not None:
        targets.append(getattr(http, "_transport", None))
        transport = getattr(http, "_transport", None)
        if transport is not None:
            targets.append(getattr(transport, "_pool", None))
    seen: set[int] = set()
    for target in targets:
        if target is None:
            continue
        ident = id(target)
        if ident in seen:
            continue
        seen.add(ident)
        closer = getattr(target, "close", None) or getattr(target, "aclose", None)
        if not callable(closer):
            continue
        try:
            result = closer()
        except Exception:
            continue
        if inspect.isawaitable(result):
            with contextlib.suppress(Exception):
                result.close()


def register_in_flight_client(client: Any) -> None:
    """Remember an ephemeral client so a watchdog timeout can close its socket."""
    if client is None:
        return
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT_CLIENTS.add(client)


def unregister_in_flight_client(client: Any) -> None:
    if client is None:
        return
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT_CLIENTS.discard(client)


def kill_in_flight_llm_clients() -> None:
    """Close every registered in-flight ephemeral client (watchdog / recycle).

    Unblocks orphan threads stuck in ``httpcore._receive_response_headers`` by
    closing their httpx transport; safe to call from another thread.
    """
    with _IN_FLIGHT_LOCK:
        clients = list(_IN_FLIGHT_CLIENTS)
        _IN_FLIGHT_CLIENTS.clear()
    for client in clients:
        close_llm_client(client)


def recycle_llm_clients() -> None:
    """Drop cached litellm HTTP clients so the next query opens a fresh connection.

    Gateway hangs often leave a keep-alive socket ESTAB / CLOSE-WAIT with no
    response bytes (large Send-Q). Retrying on the same client reuses that
    sticky connection; closing + flushing forces a new TCP handshake.

    Also closes in-flight ephemeral ``client=`` instances (not in the LiteLLM
    cache) so a stall watchdog timeout actually tears down the hung socket.
    """
    kill_in_flight_llm_clients()
    try:
        import litellm
    except Exception:
        return
    for attr in ("client_session", "aclient_session"):
        session = getattr(litellm, attr, None)
        if session is not None:
            close_llm_client(session)
            with contextlib.suppress(Exception):
                setattr(litellm, attr, None)
    cache = getattr(litellm, "in_memory_llm_clients_cache", None)
    if cache is None:
        return
    cached = getattr(cache, "cache_dict", None)
    if isinstance(cached, dict):
        for client in list(cached.values()):
            close_llm_client(client)
    flush = getattr(cache, "flush_cache", None)
    if callable(flush):
        with contextlib.suppress(Exception):
            flush()
        return
    clear = getattr(cache, "clear", None)
    if callable(clear):
        with contextlib.suppress(Exception):
            clear()
        return


def raise_for_http_status(
    prefix: str,
    status: int | None,
    body: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise a terminal config error for schema 4xx, else a transport RuntimeError."""
    code = status if status is not None else "?"
    message = f"{prefix}_{code}:{body}"
    error: Exception = (
        ModelConfigError(message) if status in _CONFIG_HTTP_STATUS else RuntimeError(message)
    )
    raise error from cause


def http_timeout_seconds(timeout: float | None) -> float | None:
    """Numeric HTTP clock. ``None`` means omit. It does not become 180.

    Zero and negatives are rejected. This path does not import httpx.
    """
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise ValueError(f"miniswe_timeout_invalid:{timeout!r}")
    return float(timeout)


def client_timeout(timeout: float | None) -> tuple[Any, float | None]:
    """httpx timeout and the numeric value passed alongside it."""
    import httpx

    value = http_timeout_seconds(timeout)
    if value is None:
        return httpx.Timeout(None), None
    return httpx.Timeout(value, connect=min(30.0, value)), value


def make_ephemeral_openai_client(
    *,
    api_key: str | None,
    api_base: str | None,
    timeout: float | None,
) -> Any:
    """OpenAI client whose httpx pool never keeps idle connections.

    Pass this as ``client=`` to ``litellm.completion`` so LiteLLM skips its
    in-memory client cache for that call. Only safe for OpenAI-compatible
    chat providers — never pass into ``litellm.responses`` or Anthropic paths.
    """
    import httpx
    from openai import OpenAI

    http_timeout, timeout_s = client_timeout(timeout)
    http = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=20),
        timeout=http_timeout,
        follow_redirects=True,
        headers={"Connection": "close"},
    )
    return OpenAI(
        api_key=api_key,
        base_url=api_base,
        http_client=http,
        timeout=timeout_s,
        max_retries=0,
        default_headers={"Connection": "close"},
    )


def uses_openai_http_client(model_name: str | None) -> bool:
    """True when ``client=`` OpenAI injection is safe for ``litellm.completion``.

    Anthropic / Bedrock / etc. must not receive an OpenAI SDK client — it
    mis-routes. OpenAI-compatible gateway models use an ``openai/`` prefix
    (possibly doubled: ``openai/openai/gpt-6-sol``).

    Call this on the *remapped* chat model from
    ``chat_model_for_openai_compat_gateway`` when ``api=chat``.
    """
    name = (model_name or "").strip().lower()
    if not name:
        return False
    if name.startswith("anthropic/") or name.startswith("bedrock/"):
        return False
    if name.startswith("openai/") or name.startswith("azure/"):
        return True
    # Bare gateway ids served via OpenAI-compatible /v1/chat/completions.
    return "/" not in name


def chat_model_for_openai_compat_gateway(model_name: str | None) -> str:
    """Force LiteLLM onto OpenAI-compat chat for gateway profile model ids.

    This plugin always points ``api_base`` at an OpenAI-compatible ``…/v1``
    gateway. Profile ids such as ``anthropic/claude-opus-5-5`` are the *wire*
    ``model`` string that gateway expects (curl to ``/v1/chat/completions``
    succeeds). LiteLLM, however, treats the ``anthropic/`` prefix as “use the
    Anthropic Messages SDK”, posts to ``{api_base}/messages`` (404) or crashes
    on ``reasoning_effort=none`` (``thinking is None`` AttributeError). The
    stall wrapper then retries forever → miniswe never reaches turn1.

    Remap to ``openai/<original>`` so LiteLLM uses the OpenAI chat provider,
    the wire model stays ``anthropic/…`` (or bare ``claude-…``), and
    ``uses_openai_http_client`` enables the ephemeral ``Connection: close``
    client. Already-``openai/`` / ``azure/`` ids are unchanged (DeepSeek,
    gpt-6-sol). Responses API does not use this helper.
    """
    text = (model_name or "").strip()
    if not text:
        return text
    lower = text.lower()
    if lower.startswith(("openai/", "azure/")):
        return text
    if lower.startswith(("anthropic/", "bedrock/")):
        return f"openai/{text}"
    # LiteLLM auto-routes bare Claude ids to the Anthropic provider.
    if "/" not in text and lower.startswith("claude"):
        return f"openai/{text}"
    return text


def wire_model_name(model_name: str) -> str:
    """Strip one LiteLLM provider prefix for the gateway wire ``model`` field.

    Profile ``openai/openai/gpt-6-sol`` → wire ``openai/gpt-6-sol`` (matches
    ``curl_responses_tools_ok.sh``). ``openai/DeepSeek-V4.1-Flash`` →
    ``DeepSeek-V4.1-Flash``.
    """
    text = (model_name or "").strip()
    if "/" not in text:
        return text
    _provider, rest = text.split("/", 1)
    return rest if rest else text


def responses_url(api_base: str | None) -> str:
    """``{api_base}/responses`` with a single slash join."""
    base = (api_base or "").rstrip("/")
    if not base:
        raise ValueError("responses_url requires api_base")
    return f"{base}/responses"


def chat_completions_url(api_base: str | None) -> str:
    """``{api_base}/chat/completions`` with a single slash join."""
    base = (api_base or "").rstrip("/")
    if not base:
        raise ValueError("chat_completions_url requires api_base")
    return f"{base}/chat/completions"


class DirectResponsesResult:
    """Minimal Responses object for ``LitellmResponseModel.query`` parsers."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.output = data.get("output") if isinstance(data.get("output"), list) else []
        for key, value in data.items():
            if key == "output":
                continue
            setattr(self, key, value)

    def model_dump(self, mode: str = "python", **_kwargs: Any) -> dict[str, Any]:
        del mode
        return dict(self._data)

    def model_dump_json(self, **_kwargs: Any) -> str:
        return json.dumps(self._data)


def sanitize_responses_input(input_items: Any) -> Any:
    """Strip fields that make this LiteLLM gateway hang on turn2+.

    Replaying Responses ``output`` items as ``input`` with their original ``id``
    values causes a silent upstream hang (0 bytes; curl reproduces). Drop ``id``
    on reasoning/message/function_call items, drop null ``namespace``, and drop
    non-essential ``phase`` / ``status``. Keep ``call_id`` (required to pair
    function_call_output).
    """
    if isinstance(input_items, str):
        return input_items
    if not isinstance(input_items, list):
        return input_items
    drop_keys = frozenset({"id", "phase", "status"})
    out: list[Any] = []
    for item in input_items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        cleaned = {
            key: value for key, value in item.items() if key not in drop_keys and value is not None
        }
        out.append(cleaned)
    return out


def post_responses_api(
    *,
    api_base: str | None,
    api_key: str | None,
    model: str,
    input: Any,
    tools: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> DirectResponsesResult:
    """POST ``/v1/responses`` with an ephemeral no-keepalive httpx client.

    Wire shape matches ``curl_responses_tools_ok.sh``: ``model``, ``input``,
    ``tools`` (flat Responses function schema). No ``stream``, no LiteLLM
    client cache, ``Connection: close``.
    """
    url = responses_url(api_base)
    wire_model = wire_model_name(model)
    payload: dict[str, Any] = {
        "model": wire_model,
        "input": sanitize_responses_input(input),
    }
    if tools is not None:
        payload["tools"] = tools
    if extra_body:
        for key, value in extra_body.items():
            if key in {"model", "input", "tools", "api_key", "api_base", "timeout", "drop_params"}:
                continue
            payload[key] = value

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Connection": "close",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        for key, value in extra_headers.items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value
        headers.setdefault("Connection", "close")

    # Optional wire dump for debugging suite-vs-curl hangs.
    dump_dir = __import__("os").environ.get("AGEVAL_MINISWE_DUMP_RESPONSES")
    if dump_dir:
        import time as _time
        from pathlib import Path as _P

        root = _P(dump_dir)
        root.mkdir(parents=True, exist_ok=True)
        stamp = f"{_time.time():.3f}"
        dump_path = root / f"req_{stamp}.json"
        dump_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "headers": {
                        k: ("***" if k.lower() == "authorization" else v)
                        for k, v in headers.items()
                    },
                    "body": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    import httpx

    http_timeout, _timeout_s = client_timeout(timeout)
    client = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
        timeout=http_timeout,
        follow_redirects=True,
        headers={"Connection": "close"},
    )
    register_in_flight_client(client)
    try:
        response = client.post(url, headers=headers, content=json.dumps(payload).encode("utf-8"))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text if exc.response is not None else "")[:800]
            status = exc.response.status_code if exc.response is not None else None
            raise_for_http_status("responses_http", status, body, cause=exc)
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"responses_http_bad_json:{response.text[:400]}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"responses_http_not_object:{type(data).__name__}")
        return DirectResponsesResult(data)
    finally:
        unregister_in_flight_client(client)
        close_llm_client(client)


def _chat_stream_enabled(explicit: bool | None) -> bool:
    """Default chat streaming on; env ``AGEVAL_MINISWE_CHAT_STREAM=0`` disables.

    Explicit ``stream=`` on ``post_chat_completions`` wins over the env.
    """
    if explicit is not None:
        return bool(explicit)
    import os

    raw = (os.environ.get("AGEVAL_MINISWE_CHAT_STREAM") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _merge_thinking_blocks(dst: list[dict[str, Any]], src: Any) -> None:
    """Append streamed ``thinking`` text into blocks by index."""
    if not isinstance(src, list):
        return
    for i, block in enumerate(src):
        if not isinstance(block, dict):
            continue
        while len(dst) <= i:
            dst.append({"type": "thinking", "thinking": ""})
        cur = dst[i]
        if not isinstance(cur, dict):
            cur = {"type": "thinking", "thinking": ""}
            dst[i] = cur
        if block.get("type"):
            cur["type"] = block["type"]
        piece = block.get("thinking")
        if isinstance(piece, str) and piece:
            cur["thinking"] = str(cur.get("thinking") or "") + piece
        # Preserve other non-empty fields from the first sighting.
        for key, value in block.items():
            if key in {"type", "thinking"}:
                continue
            if key not in cur and value is not None:
                cur[key] = value


def _merge_tool_call_delta(tool_calls: dict[int, dict[str, Any]], deltas: Any) -> None:
    """Accumulate OpenAI-style streamed ``tool_calls`` deltas by ``index``."""
    if not isinstance(deltas, list):
        return
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        try:
            index = int(delta.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        slot = tool_calls.setdefault(
            index,
            {
                "id": None,
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if delta.get("id"):
            slot["id"] = delta["id"]
        if delta.get("type"):
            slot["type"] = delta["type"]
        if "caller" in delta and delta["caller"] is not None and "caller" not in slot:
            slot["caller"] = delta["caller"]
        fn = delta.get("function")
        if isinstance(fn, dict):
            target = slot.setdefault("function", {"name": "", "arguments": ""})
            if fn.get("name"):
                target["name"] = str(target.get("name") or "") + str(fn["name"])
            args = fn.get("arguments")
            if isinstance(args, str) and args:
                target["arguments"] = str(target.get("arguments") or "") + args


def assemble_chat_completion_from_stream(
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fold SSE ``chat.completion.chunk`` objects into one chat.completion dict.

    Preserves ``tool_calls``, ``reasoning_content``, ``thinking_blocks``, and
    ``provider_specific_fields`` the non-stream path already kept via
    ``ChatCompletion.model_validate``.
    """
    if not chunks:
        raise RuntimeError("chat_http_stream_empty")

    meta: dict[str, Any] = {}
    role = "assistant"
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    thinking_blocks: list[dict[str, Any]] = []
    provider_thinking: list[dict[str, Any]] = []
    provider_extra: dict[str, Any] = {}
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        for key in ("id", "created", "model", "system_fingerprint", "service_tier"):
            if key in chunk and chunk[key] is not None and key not in meta:
                meta[key] = chunk[key]
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue
            if delta.get("role"):
                role = str(delta["role"])
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content_parts.append(piece)
            rpiece = delta.get("reasoning_content")
            if isinstance(rpiece, str) and rpiece:
                reasoning_parts.append(rpiece)
            if "thinking_blocks" in delta:
                _merge_thinking_blocks(thinking_blocks, delta.get("thinking_blocks"))
            _merge_tool_call_delta(tool_calls, delta.get("tool_calls"))
            psf = delta.get("provider_specific_fields")
            if isinstance(psf, dict):
                if "thinking_blocks" in psf:
                    _merge_thinking_blocks(provider_thinking, psf.get("thinking_blocks"))
                for key, value in psf.items():
                    if key == "thinking_blocks":
                        continue
                    if key not in provider_extra and value is not None:
                        provider_extra[key] = value

    message: dict[str, Any] = {
        "role": role,
        "content": "".join(content_parts) if content_parts else "",
    }
    saw_reasoning = False
    for c in chunks:
        if not isinstance(c, dict):
            continue
        for ch in c.get("choices") or []:
            if (
                isinstance(ch, dict)
                and isinstance(ch.get("delta"), dict)
                and "reasoning_content" in ch["delta"]
            ):
                saw_reasoning = True
                break
        if saw_reasoning:
            break
    if reasoning_parts or saw_reasoning:
        message["reasoning_content"] = "".join(reasoning_parts)
    if thinking_blocks:
        message["thinking_blocks"] = thinking_blocks
    if provider_thinking or provider_extra:
        psf_out = dict(provider_extra)
        if provider_thinking:
            psf_out["thinking_blocks"] = provider_thinking
        message["provider_specific_fields"] = psf_out
    if tool_calls:
        ordered = [tool_calls[i] for i in sorted(tool_calls)]
        # Normalize required OpenAI fields.
        cleaned: list[dict[str, Any]] = []
        for tc in ordered:
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            item: dict[str, Any] = {
                "id": tc.get("id") or "",
                "type": tc.get("type") or "function",
                "function": {
                    "name": str(fn.get("name") or ""),
                    "arguments": str(fn.get("arguments") or ""),
                },
            }
            if "caller" in tc:
                item["caller"] = tc["caller"]
            cleaned.append(item)
        message["tool_calls"] = cleaned

    data: dict[str, Any] = {
        "id": meta.get("id") or "chatcmpl-stream",
        "created": meta.get("created") or 0,
        "model": meta.get("model") or "",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
                "message": message,
            }
        ],
    }
    for key in ("system_fingerprint", "service_tier"):
        if key in meta:
            data[key] = meta[key]
    if usage is not None:
        data["usage"] = usage
    return data


def post_chat_completions(
    *,
    api_base: str | None,
    api_key: str | None,
    model: str,
    messages: Any,
    tools: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    extra_body: dict[str, Any] | None = None,
    stream: bool | None = None,
) -> Any:
    """POST ``/v1/chat/completions`` with an ephemeral no-keepalive httpx client.

    Bypasses ``litellm.completion`` / OpenAI SDK entirely so a sticky gateway
    hang cannot ignore ``timeout=`` or leave the Future watchdog unable to
    abandon (see attempt_1c23ff53). Returns an OpenAI ``ChatCompletion`` so
    ``LitellmModel.query`` parsers keep working.

    Chat Completions default to **SSE streaming** (``stream=True``): first
    tokens arrive in seconds even when non-stream TTFB is minutes under
    ``reasoning_effort=max``. Chunks are assembled into one final assistant
    message including ``tool_calls`` and reasoning fields the non-stream path
    already preserved. ``timeout`` is applied as httpx read idle-between-chunks
    (and connect), not as a total-generation wall alone — long generations stay
    healthy as long as chunks keep arriving. Set ``stream=False`` or
    ``AGEVAL_MINISWE_CHAT_STREAM=0`` to force the legacy non-stream POST.
    Responses API is untouched (``post_responses_api`` stays non-stream).
    """
    import time

    import httpx
    from openai.types.chat import ChatCompletion

    url = chat_completions_url(api_base)
    wire_model = wire_model_name(model)
    use_stream = _chat_stream_enabled(stream)
    # Allow extra_body to force stream on/off only when caller left stream=None
    # and did not set the env-driven default path via explicit False/True.
    if stream is None and isinstance(extra_body, dict) and "stream" in extra_body:
        use_stream = bool(extra_body.get("stream"))

    payload: dict[str, Any] = {
        "model": wire_model,
        "messages": messages,
    }
    if tools is not None:
        payload["tools"] = tools
    if extra_body:
        for key, value in extra_body.items():
            if key in {
                "model",
                "messages",
                "tools",
                "api_key",
                "api_base",
                "timeout",
                "drop_params",
                "client",
                "stream",  # owned by this function / flag
            }:
                continue
            payload[key] = value

    if use_stream:
        payload["stream"] = True
        # Ask the gateway for a final usage object on the stream (OpenAI shape).
        so = payload.get("stream_options")
        if not isinstance(so, dict):
            payload["stream_options"] = {"include_usage": True}
        else:
            so = dict(so)
            so.setdefault("include_usage", True)
            payload["stream_options"] = so

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Connection": "close",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        for key, value in extra_headers.items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value
        headers.setdefault("Connection", "close")

    # read= timeout → idle gap between streamed chunks (or full-body wait when
    # non-stream). connect stays capped so DNS/TCP failures fail fast.
    # Preserve canary client_timeout (None = no HTTP clock).
    http_timeout, _timeout_s = client_timeout(timeout)
    client = httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
        timeout=http_timeout,
        follow_redirects=True,
        headers={"Connection": "close"},
    )
    register_in_flight_client(client)
    try:
        body_bytes = json.dumps(payload).encode("utf-8")
        if not use_stream:
            response = client.post(url, headers=headers, content=body_bytes)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = (exc.response.text if exc.response is not None else "")[:800]
                status = exc.response.status_code if exc.response is not None else None
                raise_for_http_status("chat_http", status, body, cause=exc)
            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(f"chat_http_bad_json:{response.text[:400]}") from exc
            if not isinstance(data, dict):
                raise RuntimeError(f"chat_http_not_object:{type(data).__name__}")
            return ChatCompletion.model_validate(data)

        t0 = time.perf_counter()
        ttfb: float | None = None
        chunks: list[dict[str, Any]] = []
        with client.stream("POST", url, headers=headers, content=body_bytes) as response:
            if response.status_code >= 400:
                err_body = (response.read() or b"").decode("utf-8", "replace")[:800]
                raise_for_http_status("chat_http", response.status_code, err_body)
            for line in response.iter_lines():
                if not line:
                    continue
                if ttfb is None:
                    ttfb = time.perf_counter() - t0
                    # Suite logs read stderr. stdout is the run result document.
                    print(
                        f"miniswe_chat_stream_ttfb:{ttfb:.3f}",
                        file=sys.stderr,
                        flush=True,
                    )
                if not line.startswith("data:"):
                    continue
                data_s = line[5:].strip()
                if not data_s:
                    continue
                if data_s == "[DONE]":
                    break
                try:
                    obj = json.loads(data_s)
                except Exception as exc:
                    raise RuntimeError(f"chat_http_bad_json:{data_s[:400]}") from exc
                if not isinstance(obj, dict):
                    raise RuntimeError(f"chat_http_stream_not_object:{type(obj).__name__}")
                chunks.append(obj)

        if not chunks:
            raise RuntimeError("chat_http_stream_empty")
        data = assemble_chat_completion_from_stream(chunks)
        return ChatCompletion.model_validate(data)
    finally:
        unregister_in_flight_client(client)
        close_llm_client(client)


def bind_direct_completion_client(
    model: Any,
    *,
    api_key: str | None,
    api_base: str | None,
    timeout: float | None,
    stream: bool | None = None,
) -> None:
    """Replace ``LitellmModel._query`` with curl-equivalent httpx chat POST.

    Same rationale as ``bind_direct_responses_client``: no LiteLLM client cache,
    no OpenAI SDK ``client=`` injection, hard httpx timeout, in-flight socket
    tracked for ``kill_in_flight`` / ``SHUT_RDWR``.
    """
    if not hasattr(model, "_query"):
        return
    try:
        from minisweagent.models.utils.actions_toolcall import BASH_TOOL
    except ImportError:  # pragma: no cover
        return

    model_name = getattr(getattr(model, "config", None), "model_name", None) or ""
    model_kwargs = dict(getattr(getattr(model, "config", None), "model_kwargs", None) or {})

    def _query(messages: Any, **kwargs: Any) -> Any:
        del kwargs  # LitellmModel may forward client=; ignore — we own the HTTP path.
        recycle_llm_clients()
        extra_headers = model_kwargs.get("extra_headers")
        headers = dict(extra_headers) if isinstance(extra_headers, dict) else None
        reserved = {
            "api_key",
            "api_base",
            "drop_params",
            "timeout",
            "request_timeout",
            "extra_headers",
            "client",
        }
        extra_body = {k: v for k, v in model_kwargs.items() if k not in reserved}
        try:
            return post_chat_completions(
                api_base=api_base or model_kwargs.get("api_base"),
                api_key=api_key or model_kwargs.get("api_key"),
                model=str(model_name),
                messages=messages,
                tools=[BASH_TOOL],
                timeout=timeout,
                extra_headers=headers,
                extra_body=extra_body or None,
                stream=stream,
            )
        finally:
            recycle_llm_clients()

    model._query = _query  # type: ignore[method-assign]


def bind_ephemeral_completion_client(
    model: Any,
    *,
    api_key: str | None,
    api_base: str | None,
    timeout: float | None,
    pass_client: bool = True,
) -> None:
    """Patch ``model._query`` so each chat completion avoids sticky keep-alive.

    ``pass_client=True``: inject ephemeral OpenAI ``client=`` (OpenAI-compatible
    chat only).

    ``pass_client=False``: only flush LiteLLM's client cache (legacy; prefer
    ``bind_direct_responses_client`` for Responses API).
    """
    if not hasattr(model, "_query"):
        return
    orig = model._query

    def _query(messages: Any, **kwargs: Any) -> Any:
        recycle_llm_clients()
        # Force a finite timeout into litellm.completion. LiteLLM's OpenAI path
        # passes ``timeout=`` through to ``chat.completions.create``; without it
        # the SDK can land on ``Timeout(None)`` / read=600 and ignore the
        # ephemeral client's httpx timeout — hang past the stall watchdog's
        # ability to free the gateway socket (watchdog abandons the Future but
        # the orphan keeps ESTAB until we kill_in_flight).
        call_kwargs = dict(kwargs)
        timeout_s = http_timeout_seconds(timeout)
        if timeout_s is not None:
            call_kwargs["timeout"] = timeout_s
        if not pass_client:
            try:
                return orig(messages, **call_kwargs)
            finally:
                recycle_llm_clients()
        client = make_ephemeral_openai_client(api_key=api_key, api_base=api_base, timeout=timeout)
        register_in_flight_client(client)
        try:
            return orig(messages, client=client, **call_kwargs)
        finally:
            unregister_in_flight_client(client)
            close_llm_client(client)
            recycle_llm_clients()

    model._query = _query  # type: ignore[method-assign]


def bind_direct_responses_client(
    model: Any,
    *,
    api_key: str | None,
    api_base: str | None,
    timeout: float | None,
) -> None:
    """Replace ``LitellmResponseModel._query`` with curl-equivalent httpx POST.

    Bypasses ``litellm.responses`` entirely: no cached ``HTTPHandler`` pool,
    no OpenAI ``client=`` injection. Body matches the working direct probe
    (flat Responses tools, wire model without the LiteLLM provider prefix).
    """
    if not hasattr(model, "_query"):
        return
    try:
        from minisweagent.models.utils.actions_toolcall_response import (
            BASH_TOOL_RESPONSE_API,
        )
    except ImportError:  # pragma: no cover
        return

    model_name = getattr(getattr(model, "config", None), "model_name", None) or ""
    model_kwargs = dict(getattr(getattr(model, "config", None), "model_kwargs", None) or {})

    def _query(messages: Any, **kwargs: Any) -> Any:
        del kwargs  # LitellmResponseModel may forward client=; ignore.
        recycle_llm_clients()
        extra_headers = model_kwargs.get("extra_headers")
        headers = dict(extra_headers) if isinstance(extra_headers, dict) else None
        # Optional body knobs from profile extra_body (already merged into model_kwargs).
        reserved = {
            "api_key",
            "api_base",
            "drop_params",
            "timeout",
            "request_timeout",
            "extra_headers",
        }
        extra_body = {k: v for k, v in model_kwargs.items() if k not in reserved}
        try:
            return post_responses_api(
                api_base=api_base or model_kwargs.get("api_base"),
                api_key=api_key or model_kwargs.get("api_key"),
                model=str(model_name),
                input=messages,
                tools=[BASH_TOOL_RESPONSE_API],
                timeout=timeout,
                extra_headers=headers,
                extra_body=extra_body or None,
            )
        finally:
            recycle_llm_clients()

    model._query = _query  # type: ignore[method-assign]
