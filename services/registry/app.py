"""Stdlib HTTP Dataset Registry + results service.

Endpoints:
  GET  /health
  POST /v1/auth/github/device/code
  POST /v1/auth/github/device/poll
  POST /v1/auth/github/web/start
  POST /v1/auth/github/web/callback
  GET  /v1/users/{user_id} | PATCH /v1/users/{user_id} (self, description)
  POST /v1/orgs | GET /v1/orgs | GET /v1/orgs/{id} | DELETE /v1/orgs/{id}
  POST /v1/orgs/join | POST /v1/orgs/{id}/leave
  POST /v1/orgs/{id}/claim | GET|POST /v1/orgs/{id}/members | PATCH .../members/{user}
  POST /v1/orgs/{id}/transfer | DELETE .../members/{user}
  GET|POST /v1/orgs/{id}/invite-keys | DELETE /v1/orgs/{id}/invite-keys/{key_id}
  POST /v1/packages
  GET  /v1/packages
  GET  /v1/packages/{id}
  GET  /v1/packages/{id}/versions/{ver}
  GET  /v1/packages/{id}/by-digest/{dig}
  GET  /v1/packages/{id}/by-digest/{dig}/content
  GET  /v1/packages/{id}/by-digest/{dig}/files
  GET  /v1/packages/{id}/by-digest/{dig}/files/{path}
  GET  /v1/packages/{id}/by-digest/{dig}/tasks[?limit=&offset=]
  DELETE /v1/packages/{id}/versions/{ver}
  PATCH /v1/packages/{id}/versions/{ver}   (visibility)
  POST /v1/results/attempts
  GET  /v1/results/attempts
  GET  /v1/results/attempts/{run_id}
  DELETE /v1/results/attempts/{run_id}
  PATCH /v1/results/attempts/{run_id}     (visibility)
  GET  /v1/results/attempts/{run_id}/content
  GET  /v1/results/attempts/{run_id}/files
  GET  /v1/results/attempts/{run_id}/files/{path}
  GET|POST|DELETE /v1/results/attempts/{run_id}/shares
  POST /v1/results/suites
  GET  /v1/results/suites
  GET  /v1/results/suites/{suite_run_id}
  DELETE /v1/results/suites/{suite_run_id}[?with_attempts=1]
  PATCH /v1/results/suites/{suite_run_id}  (visibility)
  PATCH /v1/results/suites/{suite_run_id}/agent-ref
  GET  /v1/results/suites/{suite_run_id}/content
  GET|POST|DELETE /v1/results/suites/{suite_run_id}/shares
  GET  /v1/requests
  POST /v1/requests
  POST /v1/requests/decide

Scopes: registry:publish | results:upload | admin (read-private legacy ignored for ACL)
Visibility: public | private. Package private → org member; result private → owner/share.
Owner ops: results → uploaded_by (or admin); packages → org owner (or admin).
Unauthorized private → 404 (not 403). Suite results: no suite-level PASS authority.
Blob GC: delete meta first; drop blob only when digest has zero remaining refs.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Allow `python -m services.registry.app` from repo root.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.registry.access import AccessPolicy  # noqa: E402
from services.registry.backend import (  # noqa: E402
    PublicBackendError,
    require_public_backend,
)
from services.registry.envload import load_env_file  # noqa: E402
from services.registry.http_api import RegistryHttpApi, write_http_result  # noqa: E402
from services.registry.store import (  # noqa: E402
    ADMIN_SCOPES,
    FilesystemBlobStore,
    MemoryBlobStore,
    PostgresTokenStore,
    S3BlobStore,
    SqliteTokenStore,
)
from services.registry.store_schema import (  # noqa: E402
    open_sqlite_stores,
    open_stores,
)
from services.registry.upload_slots import (  # noqa: E402
    UploadSlotPool,
    slots_from_env,
)

from ageval.registry.media_types import (  # noqa: E402
    ATTEMPT_RESULT_MEDIA_TYPE as RESULT_MEDIA_TYPE,
)
from ageval.registry.media_types import SUITE_RESULT_MEDIA_TYPE  # noqa: E402

__all__ = [
    "RESULT_MEDIA_TYPE",
    "SUITE_RESULT_MEDIA_TYPE",
]

MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB after whole-object streaming


class RegistryState:
    def __init__(
        self,
        *,
        stores: Any,
        blobs: Any,
        tokens: Any,
        max_upload: int = MAX_UPLOAD_BYTES,
        github_client_id: str | None = None,
        github_client_secret: str | None = None,
        github_login_allowlist: frozenset[str] | None = None,
        upload_slots: int | UploadSlotPool | None = None,
    ) -> None:
        self.stores = stores
        self.blobs = blobs
        self.tokens = tokens
        self.access = AccessPolicy(
            orgs=stores.orgs, packages=stores.packages, results=stores.results
        )
        if isinstance(upload_slots, UploadSlotPool):
            self.upload_slots = upload_slots
        else:
            self.upload_slots = UploadSlotPool(
                slots_from_env() if upload_slots is None else upload_slots
            )
        from services.registry.auth_service import AuthService
        from services.registry.org_service import OrgService
        from services.registry.package_service import PackageService
        from services.registry.request_service import RequestService
        from services.registry.result_service import ResultService
        from services.registry.runtime_service import RuntimeService
        from services.registry.user_service import UserService

        self.auth = AuthService(
            tokens,
            orgs=stores.orgs,
            github_client_id=github_client_id,
            github_client_secret=github_client_secret,
            github_login_allowlist=github_login_allowlist or frozenset(),
        )
        self.packages = PackageService(
            stores.packages, stores.orgs, blobs, self.access, max_upload=max_upload
        )
        self.results = ResultService(
            stores.results,
            stores.packages,
            stores.orgs,
            stores.inbox,
            blobs,
            self.access,
            max_upload=max_upload,
        )
        self.runtimes = RuntimeService(stores.inbox, stores.packages, self.results)
        self.requests = RequestService(
            stores.inbox, stores.orgs, stores.packages, stores.results, self.access, self.results
        )
        self.orgs = OrgService(stores.orgs, self.access)
        self.users = UserService(stores.orgs)
        self.max_upload = max_upload
        self.spool_dir = Path(tempfile.gettempdir()) / "ageval-registry-spool"
        self.spool_dir.mkdir(parents=True, exist_ok=True)


def _parse_multipart(body: bytes, content_type: str) -> dict[str, bytes]:
    """Compatibility alias for tests that import the stdlib parser."""
    from services.registry.http_api import parse_multipart

    return parse_multipart(body, content_type)


def make_handler(state: RegistryState) -> type[BaseHTTPRequestHandler]:
    api = RegistryHttpApi(state)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            # Path-only; never log Authorization or tokens.
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._write_result(
                api.dispatch(
                    method="OPTIONS",
                    path=self.path,
                    headers=self.headers,
                    body=self.rfile,
                )
            )

        def _dispatch(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            result = api.dispatch(
                method=method,
                path=self.path,
                headers=self.headers,
                body=self.rfile,
                content_length=length,
            )
            self._write_result(result)

        def _write_result(self, result: Any) -> None:
            write_http_result(self, result)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch("PATCH")

    return Handler


def build_default_state(
    data_dir: Path,
    *,
    bootstrap_token: str | None = None,
    memory_blob: bool = False,
) -> tuple[RegistryState, str]:
    """Zero-dep path: SQLite meta + filesystem (or memory) blob + SQLite tokens."""
    db_path = data_dir / "meta.sqlite3"
    stores = open_sqlite_stores(db_path)
    tokens: Any = SqliteTokenStore(db_path)
    blobs: Any = MemoryBlobStore() if memory_blob else FilesystemBlobStore(data_dir / "blobs")
    token = bootstrap_token or secrets.token_urlsafe(24)
    tokens.add(token, ADMIN_SCOPES, github_user="bootstrap")
    return (
        RegistryState(
            stores=stores,
            blobs=blobs,
            tokens=tokens,
            github_client_id=os.environ.get("AGEVAL_GITHUB_CLIENT_ID"),
            github_client_secret=os.environ.get("AGEVAL_GITHUB_CLIENT_SECRET"),
            github_login_allowlist=_parse_login_allowlist(),
        ),
        token,
    )


def _parse_login_allowlist() -> frozenset[str]:
    raw = os.environ.get("AGEVAL_GITHUB_LOGIN_ALLOWLIST") or ""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def build_state_from_env(
    *,
    bootstrap_token: str | None = None,
    force_local: bool = False,
    memory_blob: bool = False,
) -> tuple[RegistryState, str]:
    """Public path is Postgres + S3. Local/test path is explicit."""
    load_env_file()
    if force_local:
        data_dir = (
            Path(os.environ.get("AGEVAL_REGISTRY_DATA_DIR") or ".ageval/registry-data")
            .expanduser()
            .resolve()
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        return build_default_state(
            data_dir, bootstrap_token=bootstrap_token, memory_blob=memory_blob
        )

    database_url, s3_endpoint = require_public_backend()
    from services.registry.sql_adapter import PostgresAdapter

    stores = open_stores(adapter=PostgresAdapter(database_url))
    tokens = PostgresTokenStore(database_url)
    blobs = S3BlobStore(
        endpoint=s3_endpoint,
        access_key=os.environ.get("AGEVAL_REGISTRY_S3_ACCESS_KEY") or "ageval",
        secret_key=os.environ.get("AGEVAL_REGISTRY_S3_SECRET_KEY") or "agevalageval",
        bucket=os.environ.get("AGEVAL_REGISTRY_S3_BUCKET") or "ageval",
        region=os.environ.get("AGEVAL_REGISTRY_S3_REGION") or "us-east-1",
    )
    token = bootstrap_token or secrets.token_urlsafe(24)
    tokens.add(token, ADMIN_SCOPES, github_user="bootstrap")
    return (
        RegistryState(
            stores=stores,
            blobs=blobs,
            tokens=tokens,
            github_client_id=os.environ.get("AGEVAL_GITHUB_CLIENT_ID"),
            github_client_secret=os.environ.get("AGEVAL_GITHUB_CLIENT_SECRET"),
            github_login_allowlist=_parse_login_allowlist(),
        ),
        token,
    )


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="ageval Dataset Registry service")
    parser.add_argument(
        "--host",
        default=os.environ.get("AGEVAL_REGISTRY_HOST") or "127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGEVAL_REGISTRY_PORT") or "8700"),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("AGEVAL_REGISTRY_DATA_DIR") or ".ageval/registry-data"),
        help="SQLite + filesystem blob root when not using Postgres/S3",
    )
    parser.add_argument(
        "--bootstrap-token",
        default=os.environ.get("AGEVAL_REGISTRY_BOOTSTRAP_TOKEN"),
        help="API token (default: random, printed once to stderr)",
    )
    parser.add_argument(
        "--memory-blob",
        action="store_true",
        help="Use in-memory blob store (tests only)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force SQLite+filesystem even if Postgres/S3 env is set",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("AGEVAL_REGISTRY_WORKERS") or "0"),
        help="ASGI worker count (uvicorn). 0 = stdlib ThreadingHTTPServer (dev)",
    )
    args = parser.parse_args(argv)

    if args.local or args.memory_blob:
        data_dir = args.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        state, token = build_default_state(
            data_dir,
            bootstrap_token=args.bootstrap_token,
            memory_blob=args.memory_blob,
        )
        backend = "sqlite+memory" if args.memory_blob else "sqlite+filesystem"
    else:
        try:
            state, token = build_state_from_env(
                bootstrap_token=args.bootstrap_token,
                force_local=False,
            )
            backend = "postgres+s3"
        except PublicBackendError as exc:
            sys.stderr.write(f"registry public start refused: {exc}\n")
            return 2
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"registry backend init failed: {exc}\n")
            return 1

    workers = max(0, int(args.workers))
    public = not (args.local or args.memory_blob)
    if public and workers <= 0:
        workers = int(os.environ.get("AGEVAL_REGISTRY_WORKERS") or "2")
    sys.stderr.write(
        f"ageval-registry listening on http://{args.host}:{args.port} "
        f"backend={backend} workers={workers or 1} http="
        f"{'asgi' if workers > 0 else 'stdlib'}\n"
        f"bootstrap token (store in ~/.ageval/credentials; not logged elsewhere): {token}\n"
    )
    if workers > 0:
        from services.registry.asgi import serve_uvicorn

        return serve_uvicorn(
            state,
            host=args.host,
            port=args.port,
            workers=workers,
            token=token,
            local=args.local or args.memory_blob,
            memory_blob=args.memory_blob,
            data_dir=str(args.data_dir),
            bootstrap_token=args.bootstrap_token,
        )
    handler = make_handler(state)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
