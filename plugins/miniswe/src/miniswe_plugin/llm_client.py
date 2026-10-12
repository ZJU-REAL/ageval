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

import inspect
import json
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
        try:
            sock.shutdown(_socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


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
            try:
                result.close()
            except Exception:
                pass


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
            try:
                setattr(litellm, attr, None)
            except Exception:
                pass
    cache = getattr(litellm, "in_memory_llm_clients_cache", None)
    if cache is None:
        return
    cached = getattr(cache, "cache_dict", None)
    if isinstance(cached, dict):
        for client in list(cached.values()):
            close_llm_client(client)
    flush = getattr(cache, "flush_cache", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass
        return
    clear = getattr(cache, "clear", None)
    if callable(clear):
        try:
            clear()
        except Exception:
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
    error: Exception
    if status in _CONFIG_HTTP_STATUS:
        error = ModelConfigError(message)
    else:
        error = RuntimeError(message)
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
        from pathlib import Path as _P
        import time as _time

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
) -> Any:
    """POST ``/v1/chat/completions`` with an ephemeral no-keepalive httpx client.

    Bypasses ``litellm.completion`` / OpenAI SDK entirely so a sticky gateway
    hang cannot ignore ``timeout=`` or leave the Future watchdog unable to
    abandon (see attempt_1c23ff53). Returns an OpenAI ``ChatCompletion`` so
    ``LitellmModel.query`` parsers keep working.
    """
    import httpx
    from openai.types.chat import ChatCompletion

    url = chat_completions_url(api_base)
    wire_model = wire_model_name(model)
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
            }:
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
            raise_for_http_status("chat_http", status, body, cause=exc)
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"chat_http_bad_json:{response.text[:400]}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"chat_http_not_object:{type(data).__name__}")
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
