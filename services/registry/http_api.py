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

from services.registry.errors import RegistryAppError
from services.registry.routes import match_route
from services.registry.spool import extract_multipart_archive, spool_body
from services.registry.store import TokenInfo

from ageval.registry.media_types import (
    ATTEMPT_RESULT_MEDIA_TYPE as RESULT_MEDIA_TYPE,
)
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


class RegistryHttpApi:
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

    def _auth_web_start(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.auth.web_start(
                redirect_uri=str(body.get("redirect_uri") or "").strip()
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _auth_web_callback(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.auth.web_callback(
                code=str(body.get("code") or "").strip(),
                state=str(body.get("state") or "").strip(),
                redirect_uri=str(body.get("redirect_uri") or "").strip(),
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _auth_device_code(self) -> HttpResult:
        try:
            return json_result(200, self.state.auth.device_code())
        except RegistryAppError as exc:
            return _caught(exc)

    def _auth_device_poll(self) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            status, payload = self.state.auth.device_poll(
                device_code=str(body.get("device_code") or "")
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(status, payload)

    def _publish_package(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.packages.publish(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)

    def _release_draft(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.packages.release_draft(
                dataset_id=dataset_id,
                auth=auth,
                visibility=str(body.get("visibility") or "") or None,
                replace=bool(body.get("replace")),
                version=str(body.get("version") or "") or None,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _put_package_favorite(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.packages.set_favorite(
                dataset_id=dataset_id, auth=auth, favorited=True
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_package_favorite(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.packages.set_favorite(
                dataset_id=dataset_id, auth=auth, favorited=False
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_packages(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            mine_raw = (qs.get("mine") or [""])[0]
            fav_raw = (qs.get("favorited") or [""])[0]
            orgs_raw = (qs.get("orgs") or [""])[0]
            payload = self.state.packages.list_packages(
                auth=auth,
                prefix=(qs.get("dataset_id_prefix") or [None])[0],
                visibility=(qs.get("visibility") or [None])[0],
                version=(qs.get("version") or [None])[0],
                package_kind=(qs.get("package_kind") or [None])[0],
                mine=str(mine_raw).strip().lower() in {"1", "true", "yes"},
                favorited=str(fav_raw).strip().lower() in {"1", "true", "yes"},
                orgs=str(orgs_raw).strip().lower() in {"1", "true", "yes"},
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_package_versions(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.packages.list_versions(dataset_id=dataset_id, auth=auth)
            items = payload.get("items") or []
            if any(
                isinstance(item, dict) and item.get("package_kind") == "agent" for item in items
            ):
                payload["appearances"] = self.state.runtimes.appearances_for_agent(dataset_id, auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_meta(
        self,
        *,
        dataset_id: str,
        version: str | None,
        package_digest: str | None,
        auth: TokenInfo,
    ) -> HttpResult:
        try:
            payload = self.state.packages.serve_meta(
                dataset_id=dataset_id,
                version=version,
                package_digest=package_digest,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_content(
        self, *, dataset_id: str, package_digest: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            fh, size, row = self.state.packages.serve_content(
                dataset_id=dataset_id,
                package_digest=package_digest,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {"X-Ageval-Blob-Digest": row.blob_digest},
            stream=fh,
            size=size,
        )

    def _serve_package_files_list(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
    ) -> HttpResult:
        try:
            payload = self.state.packages.list_files(
                dataset_id=dataset_id,
                auth=auth,
                package_digest=package_digest,
                version=version,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_package_file(
        self,
        *,
        dataset_id: str,
        file_path: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
    ) -> HttpResult:
        try:
            payload = self.state.packages.read_file(
                dataset_id=dataset_id,
                file_path=file_path,
                auth=auth,
                package_digest=package_digest,
                version=version,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _upload_attempt(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.results.upload_attempt(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)

    def _list_attempts(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            payload = self.state.results.list_attempts(
                auth=auth,
                dataset_id=(qs.get("dataset_id") or [None])[0],
                task_id=(qs.get("task_id") or [None])[0],
                standalone=(qs.get("standalone") or ["0"])[0] in {"1", "true", "yes"},
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_attempt_meta(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.serve_attempt_meta(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_attempt_content(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            fh, size, row = self.state.results.serve_attempt_content(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {
                "X-Ageval-Blob-Digest": row.blob_digest,
                "X-Ageval-Media-Type": RESULT_MEDIA_TYPE,
            },
            stream=fh,
            size=size,
        )

    def _serve_attempt_files_list(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.list_attempt_files(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_attempt_file(self, *, run_id: str, file_path: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.read_attempt_file(
                run_id=run_id, file_path=file_path, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _upload_suite(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.results.upload_suite(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)

    def _append_suite_slot(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.append_suite_slot(
                suite_run_id=suite_run_id, body=body, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_requests(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        inbox = str((qs.get("inbox") or [""])[0]).strip().lower() in {"1", "true", "yes"}
        suite_run_id = str((qs.get("suite_run_id") or [""])[0]).strip()
        try:
            if inbox:
                payload = self.state.requests.inbox(auth=auth)
            elif suite_run_id:
                payload = self.state.requests.list_for_suite(suite_run_id=suite_run_id, auth=auth)
            else:
                payload = self.state.requests.inbox(auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _apply_request(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"kind", "suite_run_id", "agent"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        kind = str(body.get("kind") or "").strip()
        suite_run_id = str(body.get("suite_run_id") or "").strip()
        agent_raw = body.get("agent")
        agent = str(agent_raw).strip() if isinstance(agent_raw, str) else None
        try:
            payload = self.state.requests.apply(
                kind=kind, suite_run_id=suite_run_id, auth=auth, agent=agent
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _decide_requests(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"ids", "action"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        ids = body.get("ids")
        if not isinstance(ids, list):
            return json_result(400, {"error": "invalid_request", "message": "ids required"})
        action = str(body.get("action") or "").strip()
        try:
            payload = self.state.requests.decide(
                request_ids=[str(i) for i in ids], action=action, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_suites(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            board_raw = (qs.get("board") or [""])[0]
            payload = self.state.results.list_suites(
                auth=auth,
                dataset_id=(qs.get("dataset_id") or [None])[0],
                board=str(board_raw).strip().lower() in {"1", "true", "yes"},
                uploaded_by=(qs.get("uploaded_by") or [None])[0],
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_suite_meta(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.serve_suite_meta(suite_run_id=suite_run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _serve_suite_content(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            fh, size, row = self.state.results.serve_suite_content(
                suite_run_id=suite_run_id, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {
                "X-Ageval-Blob-Digest": row.blob_digest,
                "X-Ageval-Media-Type": SUITE_RESULT_MEDIA_TYPE,
            },
            stream=fh,
            size=size,
        )

    def _get_user(self, *, user_id: str) -> HttpResult:
        try:
            payload = self.state.users.get_public(user_id)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _create_org(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [
            key
            for key in body
            if key not in {"name", "display_name", "is_claimable", "description"}
        ]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        try:
            payload = self.state.orgs.create(
                name=str(body.get("name") or ""),
                display_name=str(body.get("display_name") or ""),
                is_claimable=bool(body.get("is_claimable", False)),
                description=body.get("description", ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _list_orgs(self, *, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_for_user(auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _get_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.get_public(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [key for key in body if key not in {"display_name", "description"}]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        try:
            payload = self.state.orgs.patch(
                org_id=org_id,
                display_name=body["display_name"] if "display_name" in body else None,  # noqa: SIM401
                description=body["description"] if "description" in body else None,  # noqa: SIM401
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_user(self, *, user_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [key for key in body if key not in {"description"}]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        if "description" not in body:
            return json_result(400, {"error": "invalid_request", "message": "description required"})
        try:
            payload = self.state.users.patch(
                user_id=user_id,
                description=body["description"],
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_package_display_name(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [key for key in body if key not in {"display_name", "icon_key", "icon_github"}]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        has_display_name = "display_name" in body
        has_icon_key = "icon_key" in body
        has_icon_github = "icon_github" in body
        if not has_display_name and not has_icon_key and not has_icon_github:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "display_name or icon_key or icon_github required",
                },
            )
        try:
            payload = self.state.packages.patch_marketplace(
                dataset_id=dataset_id,
                display_name=body.get("display_name"),
                icon_key=body.get("icon_key"),
                icon_github=body.get("icon_github"),
                has_display_name=has_display_name,
                has_icon_key=has_icon_key,
                has_icon_github=has_icon_github,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _claim_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.claim(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _create_invite_key(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.create_invite(
                org_id=org_id,
                max_uses=body.get("max_uses"),
                expires_at=body.get("expires_at"),
                expires_in_days=body.get("expires_in_days"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _list_invite_keys(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_invites(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _revoke_invite_key(self, *, org_id: str, key_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.revoke_invite(org_id=org_id, key_id=key_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _join_org_with_invite(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.join(
                invite_key=str(body.get("invite_key") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_org_members(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_members(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _add_org_member(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.add_member(
                org_id=org_id,
                user_id=str(body.get("user_id") or ""),
                role=str(body.get("role") or "member"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _remove_org_member(self, *, org_id: str, user_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.remove_member(org_id=org_id, user_id=user_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_org_member(self, *, org_id: str, user_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.set_member_role(
                org_id=org_id,
                user_id=user_id,
                role=str(body.get("role") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _transfer_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.transfer(
                org_id=org_id,
                user_id=str(body.get("user_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _leave_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.leave(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.delete(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _list_result_shares(
        self, *, result_kind: str, result_id: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            payload = self.state.results.list_shares(
                result_kind=result_kind, result_id=result_id, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _add_result_share(self, *, result_kind: str, result_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.add_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)

    def _remove_result_share(
        self, *, result_kind: str, result_id: str, auth: TokenInfo
    ) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.remove_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_attempt(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.delete_attempt(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_suite(
        self, *, suite_run_id: str, auth: TokenInfo, qs: dict[str, list[str]]
    ) -> HttpResult:
        with_attempts = (qs.get("with_attempts") or ["0"])[0] in {"1", "true", "yes"}
        try:
            payload = self.state.results.delete_suite(
                suite_run_id=suite_run_id,
                with_attempts=with_attempts,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_attempt(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.results.patch_attempt(
                run_id=run_id, visibility=visibility, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _attach_suite_agent(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"agent", "role"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        agent = str(body.get("agent") or "").strip()
        if not agent:
            return json_result(400, {"error": "invalid_request", "message": "agent is required"})
        role_raw = body.get("role")
        role = str(role_raw).strip() if isinstance(role_raw, str) and role_raw.strip() else None
        try:
            payload = self.state.results.attach_agent(
                suite_run_id=suite_run_id, agent=agent, role=role, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_suite(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.results.patch_suite(
                suite_run_id=suite_run_id, visibility=visibility, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _delete_package_release(
        self, *, dataset_id: str, version: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            payload = self.state.packages.delete_release(
                dataset_id=dataset_id, version=version, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)

    def _patch_package_release(
        self, *, dataset_id: str, version: str, auth: TokenInfo
    ) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.packages.patch_visibility(
                dataset_id=dataset_id,
                version=version,
                visibility=visibility,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)


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
