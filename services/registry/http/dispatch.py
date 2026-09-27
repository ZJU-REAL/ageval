"""HTTP-library-neutral Registry adapter.

Reads a request, runs Route.access + *Service, returns an HttpResult.
Stdlib Handler and the Starlette pipe both call this. ACL stays on
``Route.access`` / ``AccessPolicy``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import parse_qs, unquote, urlparse

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.routes import match_route
from services.registry.paging import parse_limit, parse_offset
from services.registry.spool import extract_multipart_archive, spool_body

from ageval.registry.media_types import ATTEMPT_RESULT_MEDIA_TYPE as RESULT_MEDIA_TYPE
from ageval.registry.media_types import SUITE_RESULT_MEDIA_TYPE

_ctx: ContextVar[RequestCtx] = ContextVar("registry_http_ctx")


@dataclass(slots=True)
class RequestCtx:
    headers: Mapping[str, str]
    body: BinaryIO
    content_length: int


@dataclass(slots=True)
class HttpResult:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    stream: BinaryIO | None = None


def cors_headers() -> dict[str, str]:
    origin = (os.environ.get("AGEVAL_REGISTRY_CORS_ORIGIN") or "*").strip() or "*"
    out = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
        "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    }
    if origin != "*":
        out["Vary"] = "Origin"
    return out


def json_result(status: int, payload: dict[str, Any]) -> HttpResult:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        **cors_headers(),
    }
    return HttpResult(status, headers, body=body)


def empty_result(status: int) -> HttpResult:
    headers = {"Content-Length": "0", **cors_headers()}
    return HttpResult(status, headers, body=b"")


def octet_result(
    data: bytes | None,
    extra: Mapping[str, str],
    *,
    stream: BinaryIO | None = None,
    size: int | None = None,
) -> HttpResult:
    length = size if size is not None else (len(data) if data is not None else 0)
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(length),
        **dict(extra),
        **cors_headers(),
    }
    return HttpResult(200, headers, body=data or b"", stream=stream)


def parse_multipart(body: bytes, content_type: str) -> dict[str, bytes]:
    """Parse multipart/form-data without corrupting binary parts.

    Only strip framing CRLF at the part boundary — never rstrip the payload
    (gzip archives may legitimately end in 0x0d / 0x0a).
    """
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        raise ValueError("missing multipart boundary")
    boundary = m.group(1).strip().encode()
    parts = body.split(b"--" + boundary)
    out: dict[str, bytes] = {}
    for part in parts:
        if part in (b"", b"--\r\n", b"--", b"\r\n"):
            continue
        if part.startswith(b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", errors="replace")
        name_m = re.search(r'name="([^"]+)"', headers)
        if not name_m:
            continue
        out[name_m.group(1)] = data
    return out


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def _bearer(headers: Mapping[str, str]) -> str | None:
    auth = _header(headers, "Authorization")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _caught(exc: RegistryAppError) -> HttpResult:
    return json_result(exc.http_status, exc.payload())


# After the helpers above: http.orgs imports those helpers from this module.
from services.registry.http.auth import AuthHandlers
from services.registry.http.orgs import OrgHandlers
from services.registry.http.packages import PackageHandlers
from services.registry.http.results import ResultHandlers
from services.registry.http.shares import ShareHandlers
from services.registry.http.inbox import InboxHandlers
from services.registry.http.runtimes import RuntimeHandlers


class RegistryHttpApi(
    AuthHandlers,
    OrgHandlers,
    PackageHandlers,
    ResultHandlers,
    ShareHandlers,
    InboxHandlers,
    RuntimeHandlers,
):
    def __init__(self, state: Any) -> None:
        self.state = state

    def dispatch(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: BinaryIO,
        content_length: int | None = None,
    ) -> HttpResult:
        if method == "OPTIONS":
            return empty_result(204)
        parsed = urlparse(path)
        route_path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        matched = match_route(method, route_path)
        if matched is None:
            return json_result(404, {"error": "not_found", "message": "unknown path"})
        route, kwargs = matched
        token = _bearer(headers)
        auth = self.state.auth.auth_for(token)
        denied = self.state.access.enforce_route_access(route.access, auth, kwargs=kwargs)
        if denied is not None:
            status, payload = denied
            return json_result(status, payload)
        if route.access != "none":
            kwargs["auth"] = auth
        if route.pass_qs:
            kwargs["qs"] = qs
        length = content_length
        if length is None:
            raw_len = _header(headers, "Content-Length") or "0"
            try:
                length = int(raw_len)
            except ValueError:
                length = 0
        token_ctx = _ctx.set(RequestCtx(headers=headers, body=body, content_length=length))
        try:
            handler = getattr(self, f"_{route.name}")
            return handler(**kwargs)
        finally:
            _ctx.reset(token_ctx)

    def _read_json_body(self) -> dict[str, Any] | HttpResult:
        ctx = _ctx.get()
        raw = ctx.body.read(ctx.content_length) if ctx.content_length > 0 else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return json_result(400, {"error": "invalid_request", "message": "bad JSON"})
        if not isinstance(parsed, dict):
            return json_result(400, {"error": "invalid_request", "message": "bad JSON"})
        return parsed

    def _spool_dir(self) -> Path:
        raw = getattr(self.state, "spool_dir", None)
        if isinstance(raw, Path):
            return raw
        return Path(tempfile.gettempdir()) / "ageval-registry-spool"

    def _read_multipart_archive(self) -> tuple[dict[str, Any], Path, Path] | HttpResult:
        """Return metadata, archive path, and the parent spool dir to delete later."""
        ctx = _ctx.get()
        length = ctx.content_length
        if length <= 0 or length > self.state.max_upload:
            return json_result(
                413,
                {
                    "error": "payload_too_large",
                    "message": f"max {self.state.max_upload} bytes",
                },
            )
        parent = self._spool_dir()
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="ageval-up-", dir=str(parent)))
        try:
            spool = spool_body(
                ctx.body,
                length=length,
                max_bytes=self.state.max_upload,
                dest_dir=work,
            )
            ctype = _header(ctx.headers, "Content-Type")
            meta, archive = extract_multipart_archive(spool, ctype, work)
            spool.unlink(missing_ok=True)
            return meta, archive, work
        except RegistryAppError as exc:
            shutil.rmtree(work, ignore_errors=True)
            return _caught(exc)
        except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
            shutil.rmtree(work, ignore_errors=True)
            return json_result(
                400,
                {"error": "invalid_request", "message": f"bad multipart: {exc}"},
            )

    def _visibility_body(self) -> str | HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        visibility = str(body.get("visibility") or "").strip()
        if visibility not in {"public", "private"}:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "visibility must be public or private",
                },
            )
        return visibility

    def _health(self) -> HttpResult:
        return json_result(200, {"ok": True, "service": "ageval-registry"})


def write_http_result(handler: Any, result: HttpResult) -> None:
    """Write ``HttpResult`` onto a ``BaseHTTPRequestHandler``."""
    handler.send_response(result.status)
    for key, value in result.headers.items():
        handler.send_header(key, value)
    handler.end_headers()
    if result.stream is not None:
        try:
            shutil.copyfileobj(result.stream, handler.wfile)
        finally:
            result.stream.close()
        return
    if result.body:
        handler.wfile.write(result.body)
