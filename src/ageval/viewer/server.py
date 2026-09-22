"""Stdlib HTTP server for the local Dataset viewer SPA + Jobs JSON API."""

from __future__ import annotations

import errno
import json
import mimetypes
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ageval.config.errors import ConfigError
from ageval.viewer import catalog, jobs, trials
from ageval.viewer.session import ViewSession, open_view

# Default bind: loopback only.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_WRITE_CONFLICT = frozenset({"job_in_progress", "job_claimed_elsewhere", "job_inner_attempt"})


def _job_write_status(exc: ConfigError) -> int:
    if exc.error_code == "unknown_task":
        return 404
    if exc.error_code in _WRITE_CONFLICT:
        return 409
    return 400


def _bind_url(host: str, port: int) -> str:
    """Operator-facing bind URL (clickable in most terminals)."""
    # IPv6 literals need brackets in URLs.
    if ":" in host and not host.startswith("["):
        return f"http://[{host}]:{port}/"
    return f"http://{host}:{port}/"


def _raise_bind_error(host: str, port: int, exc: OSError) -> None:
    """Re-raise bind failures with a concrete URL (OS strerror often omits it)."""
    url = _bind_url(host, port)
    en = getattr(exc, "errno", None)
    if en in {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)}:
        raise OSError(
            en,
            f"address already in use: {url} "
            f"(stop the other process or pass --port <free>; --port 0 = ephemeral)",
        ) from exc
    if en in {errno.EADDRNOTAVAIL, errno.EACCES, getattr(errno, "WSAEACCES", -1)}:
        raise OSError(
            en,
            f"cannot bind {url}: {exc.strerror or exc}",
        ) from exc
    raise OSError(
        en or 0,
        f"cannot bind {url}: {exc.strerror or exc}",
    ) from exc


def static_dir() -> Path:
    """Locate SPA under monorepo ``apps/viewer/dist`` (build artifact, gitignored).

    Package-adjacent ``static/`` is how installed wheels serve the SPA: the
    release build copies ``apps/viewer/dist`` there before ``uv build``.
    Run ``pnpm build`` in ``apps/viewer`` for local ``ageval view``.
    """
    env = Path(__file__).resolve()
    repo_dist = env.parents[3] / "apps" / "viewer" / "dist"
    pkg_data = env.parent / "static"
    for candidate in (repo_dist, pkg_data):
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    raise FileNotFoundError("viewer SPA not found (from apps/viewer: pnpm build → dist/)")


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    cors = getattr(handler, "_cors", None)
    if callable(cors):
        cors()
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    _json(handler, status, {"error": code, "message": message})


def _dataset_query(url: str) -> str | None:
    raw = (parse_qs(urlparse(url).query).get("dataset") or [""])[0].strip()
    return raw or None


def _dataset_query_value(url: str, name: str) -> str:
    return (parse_qs(urlparse(url).query).get(name) or [""])[0].strip()


def _config_status(exc: ConfigError) -> int:
    if "unknown" in exc.error_code:
        return 404
    return 400


def _retag_breadcrumbs(payload: dict[str, Any], dataset_key: str) -> None:
    crumbs = payload.get("breadcrumb")
    if not isinstance(crumbs, list):
        return
    home = f"/jobs/{dataset_key}"
    prefix = "/jobs/"
    for crumb in crumbs:
        if not isinstance(crumb, dict):
            continue
        href = crumb.get("href")
        if href == "/":
            crumb["href"] = home
            continue
        if not isinstance(href, str) or not href.startswith(prefix):
            continue
        rest = href[len(prefix) :]
        if rest == dataset_key or rest.startswith(dataset_key + "/"):
            continue
        crumb["href"] = f"{home}/{rest}"


def normalize_open_path(raw: str | None) -> str:
    """Client route to open after start. Must be a same-origin path."""
    text = (raw or "/").strip() or "/"
    if not text.startswith("/"):
        text = f"/{text}"
    if text.startswith("//") or "://" in text or "\\" in text or "\n" in text:
        raise ConfigError(
            "invalid_package",
            f"invalid open path: {raw!r}",
            location="open",
        )
    return text


def make_handler(
    dataset_root: Path,
    assets: Path | None,
    *,
    session: ViewSession | None = None,
    cors_origin: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    bound = session if session is not None else open_view(dataset_root)
    assets_dir = assets.resolve(strict=False) if assets is not None else None

    class ViewerHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Quiet by default; still useful on stderr for debugging.
            sys.stderr.write(f"{self.address_string()} - {format % args}\n")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if self.command == "OPTIONS":
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if path == "/api/health":
                _json(self, 200, {"ok": True, "service": "ageval-viewer"})
                return
            if path == "/api/session":
                _json(self, 200, bound.as_dict())
                return
            if path == "/api/datasets":
                _json(self, 200, {"ok": True, "items": [item.as_dict() for item in bound.datasets]})
                return
            if path.startswith("/api/datasets/"):
                self._api_dataset(path)
                return
            if path == "/api/plugins":
                _json(self, 200, catalog.list_plugins())
                return
            if path == "/api/plugins/package":
                self._api_plugin_package()
                return
            if path == "/api/plugins/tree":
                self._api_plugin_tree()
                return
            if path == "/api/plugins/file":
                self._api_plugin_file()
                return
            if path == "/api/agents":
                _json(self, 200, catalog.list_agents())
                return
            if path == "/api/agents/package":
                self._api_agent_package()
                return
            if path == "/api/agents/tree":
                self._api_agent_tree()
                return
            if path == "/api/agents/file":
                self._api_agent_file()
                return
            if path == "/api/jobs":
                self._api_jobs_list()
                return
            if path.startswith("/api/jobs/"):
                self._api_jobs(path)
                return
            if path.startswith("/api/"):
                _error(self, 404, "not_found", "unknown API path")
                return

            if assets_dir is None:
                _json(
                    self,
                    200,
                    {
                        "ok": True,
                        "service": "ageval-viewer",
                        "dev": True,
                        "message": "API only; open the Vite UI origin for the SPA",
                    },
                )
                return

            # Static SPA (client-side routes fall through to index.html)
            rel = path.lstrip("/")
            if rel and ".." not in Path(rel).parts:
                candidate = (assets_dir / rel).resolve(strict=False)
                try:
                    candidate.relative_to(assets_dir)
                    if candidate.is_file():
                        mime, _ = mimetypes.guess_type(str(candidate))
                        self._serve_file(candidate, mime or "application/octet-stream")
                        return
                except ValueError:
                    pass
            self._serve_file(assets_dir / "index.html", "text/html; charset=utf-8")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.do_GET()

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if not path.startswith("/api/jobs/"):
                _error(self, 404, "not_found", "unknown API path")
                return
            parts = [p for p in path[len("/api/jobs/") :].split("/") if p]
            if len(parts) != 1:
                _error(self, 404, "not_found", "unknown jobs API path")
                return
            qs = parse_qs(parsed.query)
            confirm = (qs.get("confirm") or [""])[0]
            self._api_job_delete(parts[0], confirm)

        def _opened(self):
            return bound.by_key(_dataset_query(self.path))

        def _api_dataset(self, path: str) -> None:
            rest = [part for part in path[len("/api/datasets/") :].split("/") if part]
            if not rest:
                _error(self, 404, "not_found", "dataset key required")
                return
            key, tail = rest[0], rest[1:]
            try:
                opened = bound.by_key(key)
                if not tail:
                    _json(self, 200, catalog.dataset_package(opened))
                    return
                if tail == ["tree"]:
                    _json(self, 200, catalog.dataset_tree(opened))
                    return
                if tail == ["file"]:
                    rel = _dataset_query_value(self.path, "path")
                    if not rel:
                        _error(self, 400, "invalid_package", "path query required")
                        return
                    _json(self, 200, catalog.dataset_file(opened, rel))
                    return
            except ConfigError as exc:
                _error(self, _config_status(exc), exc.error_code, str(exc))
                return
            _error(self, 404, "not_found", "unknown dataset API path")

        def _api_plugin_package(self) -> None:
            self._catalog_call("plugin", "package")

        def _api_plugin_tree(self) -> None:
            self._catalog_call("plugin", "tree")

        def _api_plugin_file(self) -> None:
            self._catalog_call("plugin", "file")

        def _api_agent_package(self) -> None:
            self._catalog_call("agent", "package")

        def _api_agent_tree(self) -> None:
            self._catalog_call("agent", "tree")

        def _api_agent_file(self) -> None:
            self._catalog_call("agent", "file")

        def _catalog_call(self, kind: str, action: str) -> None:
            source = _dataset_query_value(self.path, "source")
            package_id = _dataset_query_value(self.path, "id")
            version = _dataset_query_value(self.path, "version")
            if not source or not package_id or not version:
                _error(self, 400, "invalid_package", "source, id, and version are required")
                return
            try:
                if kind == "plugin" and action == "package":
                    payload = catalog.plugin_package(source, package_id, version)
                elif kind == "plugin" and action == "tree":
                    payload = catalog.plugin_tree(source, package_id, version)
                elif kind == "plugin" and action == "file":
                    rel = _dataset_query_value(self.path, "path")
                    if not rel:
                        _error(self, 400, "invalid_package", "path query required")
                        return
                    payload = catalog.plugin_file(source, package_id, version, rel)
                elif kind == "agent" and action == "package":
                    payload = catalog.agent_package(source, package_id, version)
                elif kind == "agent" and action == "tree":
                    payload = catalog.agent_tree(source, package_id, version)
                elif kind == "agent" and action == "file":
                    rel = _dataset_query_value(self.path, "path")
                    if not rel:
                        _error(self, 400, "invalid_package", "path query required")
                        return
                    payload = catalog.agent_file(source, package_id, version, rel)
                else:
                    _error(self, 404, "not_found", "unknown catalog API path")
                    return
            except ConfigError as exc:
                _error(self, _config_status(exc), exc.error_code, str(exc))
                return
            _json(self, 200, payload)

        def _api_job_delete(self, job_id: str, confirm: str) -> None:
            from ageval.application.composition import build_local_jobs_commands

            try:
                opened = self._opened()
            except ConfigError as exc:
                _error(self, _config_status(exc), exc.error_code, str(exc))
                return
            try:
                payload = build_local_jobs_commands().delete_job(
                    opened.root,
                    job_id=job_id,
                    confirm_token=confirm or None,
                )
            except ConfigError as exc:
                _error(self, _job_write_status(exc), exc.error_code, str(exc))
                return
            _json(self, 200, payload)

        def _cors(self) -> None:
            if not cors_origin:
                return
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _serve_file(self, path: Path, content_type: str) -> None:
            try:
                data = path.read_bytes()
            except OSError:
                _error(self, 404, "not_found", "static asset missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _api_jobs_list(self) -> None:
            try:
                if _dataset_query(self.path) is None and not bound.datasets:
                    _json(self, 200, {"ok": True, "items": [], "count": 0, "commands": {}})
                    return
                opened = self._opened()
                payload = jobs.list_jobs(opened.root)
                payload["dataset_key"] = opened.key
                _json(self, 200, payload)
            except ConfigError as exc:
                _error(self, _config_status(exc), exc.error_code, str(exc))

        def _api_jobs(self, path: str) -> None:
            # /api/jobs/{job_id}
            # /api/jobs/{job_id}/tasks/{task_id}
            # /api/jobs/{job_id}/tasks/{task_id}/trials
            # /api/jobs/{job_id}/tasks/{task_id}/trials/{run_id}
            # /api/jobs/{job_id}/tasks/{task_id}/trials/{run_id}/tree|file|trajectory
            # …/observation|checks|package-file
            rest = path[len("/api/jobs/") :]
            parts = [p for p in rest.split("/") if p]
            if not parts:
                _error(self, 404, "not_found", "job id required")
                return
            job_id = parts[0]
            query = urlparse(self.path).query
            q = trials.parse_query(query)
            try:
                opened = self._opened()
                root = opened.root
                dataset_key = opened.key
                if len(parts) == 2 and parts[1] == "delete-preview":
                    from ageval.application.composition import build_local_jobs_commands

                    _json(
                        self,
                        200,
                        build_local_jobs_commands().preview_delete_job(root, job_id=job_id),
                    )
                    return
                if len(parts) == 1:
                    _json(self, 200, jobs.get_job(root, job_id))
                    return
                if len(parts) >= 2 and parts[1] == "overlays":
                    from ageval.viewer.overlays import (
                        declared_overlay_paths,
                        list_overlay_files,
                        read_overlay_file,
                    )

                    overlay = jobs.job_overlay_mapping(root, job_id)
                    prefixes = declared_overlay_paths(root, overlay)
                    if len(parts) == 2:
                        _json(self, 200, list_overlay_files(root, prefixes))
                        return
                    if len(parts) == 3 and parts[2] == "file":
                        rel = q.get("path") or ""
                        if not rel:
                            _error(self, 400, "invalid_package", "path query required")
                            return
                        _json(self, 200, read_overlay_file(root, rel, prefixes))
                        return
                if len(parts) == 3 and parts[1] == "tasks":
                    # Trial-enriched listing (suite summary + local evidence)
                    task_id = parts[2]
                    payload = trials.list_task_trials(root, job_id, task_id)
                    _json(
                        self,
                        200,
                        {
                            "ok": True,
                            "job": payload["job"],
                            "task": payload["task"],
                            "trials": payload["trials"],
                            "agent_label": payload["task"].get("agent_label")
                            or payload["job"].get("agent_label"),
                            "model_label": payload["task"].get("model_label")
                            or payload["job"].get("model_label"),
                            "reasoning_effort": payload["task"].get("reasoning_effort")
                            or payload["job"].get("reasoning_effort"),
                            "provider_label": payload["task"].get("provider_label")
                            or payload["job"].get("provider_label"),
                            "dataset": payload["task"].get("dataset")
                            or payload["job"].get("source"),
                            "commands": payload.get("commands"),
                            "run_command": payload.get("run_command"),
                            "breadcrumb": [
                                {"label": "Jobs", "href": f"/jobs/{dataset_key}"},
                                {"label": job_id, "href": f"/jobs/{dataset_key}/{job_id}"},
                                {"label": task_id, "href": None},
                            ],
                            "note": payload.get("note"),
                        },
                    )
                    return
                if len(parts) >= 4 and parts[1] == "tasks" and parts[3] == "trials":
                    task_id = parts[2]
                    if len(parts) == 4:
                        payload = trials.list_task_trials(root, job_id, task_id)
                        _retag_breadcrumbs(payload, dataset_key)
                        _json(self, 200, payload)
                        return
                    run_id = parts[4]
                    if len(parts) == 5:
                        payload = trials.get_trial(root, job_id, task_id, run_id)
                        _retag_breadcrumbs(payload, dataset_key)
                        _json(self, 200, payload)
                        return
                    if len(parts) == 6 and parts[5] == "tree":
                        _json(
                            self,
                            200,
                            trials.trial_tree(
                                root,
                                job_id,
                                task_id,
                                run_id,
                                scope=q.get("scope", "root"),
                            ),
                        )
                        return
                    if len(parts) == 6 and parts[5] == "file":
                        rel = q.get("path") or ""
                        if not rel:
                            _error(self, 400, "invalid_package", "path query required")
                            return
                        _json(
                            self,
                            200,
                            trials.trial_file(root, job_id, task_id, run_id, relpath=rel),
                        )
                        return
                    if len(parts) == 6 and parts[5] == "trajectory":
                        _json(
                            self,
                            200,
                            trials.trial_trajectory(root, job_id, task_id, run_id),
                        )
                        return
                    if len(parts) == 6 and parts[5] == "observation":
                        _json(
                            self,
                            200,
                            trials.trial_evaluation_observation(root, job_id, task_id, run_id),
                        )
                        return
                    if len(parts) == 6 and parts[5] == "checks":
                        _json(
                            self,
                            200,
                            trials.trial_evaluation_checks(root, job_id, task_id, run_id),
                        )
                        return
                    if len(parts) == 6 and parts[5] == "package-file":
                        rel = q.get("path") or ""
                        if not rel:
                            _error(self, 400, "invalid_package", "path query required")
                            return
                        _json(
                            self,
                            200,
                            trials.trial_package_file(root, job_id, task_id, run_id, relpath=rel),
                        )
                        return
            except ConfigError as exc:
                status = 404 if "unknown" in exc.error_code else 400
                _error(self, status, exc.error_code, str(exc))
                return
            _error(self, 404, "not_found", "unknown jobs API path")

    return ViewerHandler


def serve_viewer(
    dataset_ref: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    block: bool = True,
    dev: bool = False,
    open_path: str = "/",
    ui_port: int = 5173,
) -> dict[str, Any]:
    """Start the local viewer. Returns connection info.

    When *block* is True (CLI default), serve forever until KeyboardInterrupt.
    ``dev=True`` serves the JSON API only (no SPA bundle). Vite is the UI.
    The CLI tries to start ``pnpm --dir apps/viewer dev``; if that cannot run,
    it prints the two-process fallback instead of failing.
    """
    from ageval.viewer.dev_ui import (
        DEFAULT_UI_PORT,
        fallback_commands,
        stop_dev_ui,
        try_start_dev_ui,
    )

    session = open_view(dataset_ref)
    if len(session.datasets) == 1:
        only = session.datasets[0]
        dataset_id: str | None = only.dataset_id
        shown_root = str(only.root)
    else:
        dataset_id = None
        shown_root = str(session.parent) if session.parent is not None else ""
    route = normalize_open_path(open_path)
    ui_port_n = int(ui_port) if ui_port else DEFAULT_UI_PORT
    ui_origin = f"http://127.0.0.1:{ui_port_n}"
    assets = None if dev else static_dir()
    cors_origin = ui_origin if dev else None
    handler = make_handler(
        Path(shown_root or "."),
        assets,
        session=session,
        cors_origin=cors_origin,
    )
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        _raise_bind_error(host, port, exc)
        raise  # pragma: no cover — _raise_bind_error always raises
    # If port 0, OS assigns.
    actual_host, actual_port = server.server_address[:2]
    api_url = f"http://{actual_host}:{actual_port}/"
    api_origin = f"http://{actual_host}:{actual_port}"
    start_vite = bool(dev and block)
    ui = try_start_dev_ui(
        api_origin=api_origin,
        ui_port=ui_port_n,
        start=start_vite,
    )
    page_url = (
        f"{ui_origin}{route}"
        if dev and ui.started
        else f"http://{actual_host}:{actual_port}{route}"
    )
    info = {
        "ok": True,
        "url": page_url,
        "api_url": api_url,
        "ui_url": page_url,
        "host": actual_host,
        "port": actual_port,
        "ui_port": ui_port_n if dev else actual_port,
        "dev": dev,
        "ui_started": ui.started,
        "ui_reason": ui.reason,
        "open_path": route,
        "dataset_id": dataset_id,
        "dataset_count": len(session.datasets),
        "landing": session.landing,
        "root": shown_root,
    }

    if open_browser and (not dev or ui.started):
        threading.Timer(0.4, lambda: webbrowser.open(page_url)).start()

    if block:
        if dev and ui.started:
            message = (
                "API + Vite listening; Ctrl+C stops both"
                if not ui.reused
                else "API listening; reused Vite already on ui_port"
            )
        elif dev:
            cmd_a, cmd_b = fallback_commands(api_origin=api_origin, ui_port=ui_port_n)
            message = f"API listening; Vite not started ({ui.reason})"
            sys.stderr.write(f"viewer: {message}\n  {cmd_a}\n  {cmd_b}\n")
            sys.stderr.flush()
            info["ui_commands"] = [cmd_a, cmd_b]
        else:
            message = "viewer listening; Ctrl+C to stop"
        payload = {
            "ok": True,
            "url": page_url,
            "api_url": api_url,
            "ui_url": page_url,
            "dev": dev,
            "ui_started": ui.started,
            "dataset_id": info["dataset_id"],
            "root": info["root"],
            "message": message,
        }
        if info.get("ui_commands"):
            payload["ui_commands"] = info["ui_commands"]
        print(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop_dev_ui(ui.proc)
            server.shutdown()
            server.server_close()
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        info["server"] = server
        info["thread"] = thread

    return info
