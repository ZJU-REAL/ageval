"""Starlette/uvicorn HTTP pipe for the Registry.

ACL and routing stay in ``Route.access`` + ``RegistryHttpApi``. This module
only terminates HTTP and fans out workers. FastAPI / OpenAPI are out of scope.
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from services.registry.http.dispatch import RegistryHttpApi, json_result


def build_asgi_app(state: Any) -> Any:
    """Return a Starlette app bound to an already-built ``RegistryState``."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response, StreamingResponse
    from starlette.routing import Route

    api = RegistryHttpApi(state)

    async def _spool_multipart(request: Request) -> tuple[Path, int] | Any:
        try:
            declared = int(request.headers.get("content-length") or "0")
        except ValueError:
            declared = 0
        if declared <= 0 or declared > state.max_upload:
            return json_result(
                413,
                {
                    "error": "payload_too_large",
                    "message": f"max {state.max_upload} bytes",
                },
            )
        parent = getattr(state, "spool_dir", None)
        root = (
            parent
            if isinstance(parent, Path)
            else Path(tempfile.gettempdir()) / "ageval-registry-spool"
        )
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="ageval-asgi-", dir=str(root)))
        dest = work / "body.spool"
        written = 0
        try:
            with dest.open("wb") as out:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > state.max_upload:
                        raise OSError("payload_too_large")
                    out.write(chunk)
        except OSError:
            shutil.rmtree(work, ignore_errors=True)
            return json_result(
                413,
                {
                    "error": "payload_too_large",
                    "message": f"max {state.max_upload} bytes",
                },
            )
        return dest, written

    async def endpoint(request: Request) -> Response:
        header_map = {k.decode("latin1"): v.decode("latin1") for k, v in request.scope["headers"]}
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        ctype = header_map.get("content-type", "")
        spool: Path | None = None
        body_fh: Any = None
        try:
            if (
                request.method in {"POST", "PUT", "PATCH"}
                and "multipart/form-data" in ctype.lower()
            ):
                spooled = await _spool_multipart(request)
                if not isinstance(spooled, tuple):
                    result = spooled
                else:
                    spool, written = spooled
                    body_fh = spool.open("rb")
                    result = await asyncio.to_thread(
                        api.dispatch,
                        method=request.method,
                        path=target,
                        headers=header_map,
                        body=body_fh,
                        content_length=written,
                    )
            else:
                raw = await request.body()
                result = await asyncio.to_thread(
                    api.dispatch,
                    method=request.method,
                    path=target,
                    headers=header_map,
                    body=io.BytesIO(raw),
                    content_length=len(raw),
                )
        finally:
            if body_fh is not None:
                body_fh.close()
            if spool is not None:
                shutil.rmtree(spool.parent, ignore_errors=True)
        headers = dict(result.headers)
        stream = result.stream
        if stream is not None:

            def _iter() -> Any:
                try:
                    while True:
                        chunk = stream.read(64 * 1024)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    stream.close()

            return StreamingResponse(
                _iter(),
                status_code=result.status,
                headers=headers,
                media_type=headers.pop("Content-Type", "application/octet-stream"),
            )
        media = headers.pop("Content-Type", "application/json")
        return Response(
            content=result.body,
            status_code=result.status,
            headers=headers,
            media_type=media,
        )

    async def endpoint_any(request: Request) -> Response:
        return await endpoint(request)

    return Starlette(
        routes=[
            Route(
                "/{path:path}",
                endpoint=endpoint_any,
                methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            ),
            Route(
                "/", endpoint=endpoint_any, methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
            ),
        ]
    )


def app_factory() -> Any:
    """Uvicorn ``--factory`` entry: rebuild state per worker from env."""
    from services.registry.app import build_state_from_env
    from services.registry.envload import load_env_file

    load_env_file()
    force_local = (os.environ.get("AGEVAL_REGISTRY_FORCE_LOCAL") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    memory_blob = (os.environ.get("AGEVAL_REGISTRY_MEMORY_BLOB") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    state, token = build_state_from_env(
        bootstrap_token=os.environ.get("AGEVAL_REGISTRY_BOOTSTRAP_TOKEN"),
        force_local=force_local or memory_blob,
        memory_blob=memory_blob,
    )
    # One line per worker so operators can see the token without stdout dumps.
    if token and not os.environ.get("AGEVAL_REGISTRY_BOOTSTRAP_TOKEN"):
        sys.stderr.write(f"worker bootstrap token: {token}\n")
    return build_asgi_app(state)


def serve_uvicorn(
    state: Any,
    *,
    host: str,
    port: int,
    workers: int,
    token: str,
    local: bool,
    memory_blob: bool,
    data_dir: str,
    bootstrap_token: str | None,
) -> int:
    """Run uvicorn. Workers > 1 rebuild state via ``app_factory``."""
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn required for --workers; install with: uv sync --extra registry"
        ) from exc

    if bootstrap_token:
        os.environ["AGEVAL_REGISTRY_BOOTSTRAP_TOKEN"] = bootstrap_token
    elif token:
        os.environ.setdefault("AGEVAL_REGISTRY_BOOTSTRAP_TOKEN", token)
    os.environ["AGEVAL_REGISTRY_DATA_DIR"] = data_dir
    if local:
        os.environ["AGEVAL_REGISTRY_FORCE_LOCAL"] = "1"
    if memory_blob:
        os.environ["AGEVAL_REGISTRY_MEMORY_BLOB"] = "1"

    config_kw: dict[str, Any] = {
        "host": host,
        "port": port,
        "log_level": "warning",
    }
    if workers <= 1:
        app = build_asgi_app(state)
        uvicorn.run(app, **config_kw)
        return 0
    uvicorn.run(
        "services.registry.asgi:app_factory",
        factory=True,
        workers=workers,
        **config_kw,
    )
    return 0
