"""Viewer helpers + HTTP surface (Jobs API + SPA; no package-file browser)."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from ageval.viewer import browse
from ageval.viewer.server import make_handler, serve_viewer

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def test_dataset_overview_suite_min() -> None:
    ov = browse.dataset_overview(SUITE)
    assert ov["dataset_id"] == "test/suite-min"
    assert ov["task_count"] >= 3
    assert "alpha" in ov["task_ids"]


def test_commands_include_run_task() -> None:
    cmds = browse.commands_for(SUITE, task_id="alpha")
    assert "ageval run" in cmds["run_task"]
    assert "--task alpha" in cmds["run_task"]
    assert "ageval lock" in cmds["lock_task"]


def test_serve_viewer_bind_in_use_includes_host_port(tmp_path: Path) -> None:
    """Port conflict must name the bind address (OS strerror often omits it)."""
    assets = _minimal_spa(tmp_path)
    holder = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(SUITE, assets))
    host, port = holder.server_address[:2]
    thread = threading.Thread(target=holder.serve_forever, daemon=True)
    thread.start()
    try:
        want_url = f"http://{host}:{port}/"
        with (
            patch("ageval.viewer.server.static_dir", return_value=assets),
            pytest.raises(OSError, match=r"address already in use: http://") as ei,
        ):
            serve_viewer(
                SUITE,
                host=str(host),
                port=int(port),
                open_browser=False,
                block=False,
            )
        msg = str(ei.value)
        assert want_url in msg
        assert "--port" in msg
    finally:
        holder.shutdown()
        holder.server_close()


def _minimal_spa(tmp_path: Path) -> Path:
    """CI-safe SPA shell (no Vite build required)."""
    root = tmp_path / "spa"
    root.mkdir()
    (root / "index.html").write_text(
        "<!doctype html><html><head><title>ageval Viewer</title></head>"
        '<body><div id="root"></div></body></html>\n',
        encoding="utf-8",
    )
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("// test stub\n", encoding="utf-8")
    return root


@pytest.fixture()
def viewer_server(tmp_path: Path):
    assets = _minimal_spa(tmp_path)
    handler = make_handler(SUITE, assets)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as resp:  # noqa: S310 — local test server
        return json.loads(resp.read().decode("utf-8"))


def test_http_health_jobs_and_spa(viewer_server: str) -> None:
    base = viewer_server
    health = _get_json(f"{base}/api/health")
    assert health["ok"] is True
    assert health["service"] == "ageval-viewer"

    jobs_payload = _get_json(f"{base}/api/jobs")
    assert "items" in jobs_payload
    assert jobs_payload["count"] >= 0
    assert "commands" in jobs_payload


def test_serve_viewer_dev_skips_spa_bundle(tmp_path: Path) -> None:
    from ageval.viewer.server import serve_viewer

    info = serve_viewer(
        SUITE,
        host="127.0.0.1",
        port=0,
        open_browser=False,
        block=False,
        dev=True,
        open_path="/jobs/demo",
        ui_port=5173,
    )
    try:
        assert info["dev"] is True
        assert info["open_path"] == "/jobs/demo"
        assert info["ui_url"].endswith("/jobs/demo")
        # Vite was not started (block=False) — do not advertise :5173.
        assert info["ui_started"] is False
        assert info["ui_reason"] == "skipped"
        assert ":5173" not in info["ui_url"]
        with urlopen(f"{info['api_url']}api/health", timeout=5) as resp:  # noqa: S310
            health = json.loads(resp.read().decode("utf-8"))
        assert health["ok"] is True
        with urlopen(info["api_url"], timeout=5) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        assert body.get("dev") is True
    finally:
        info["server"].shutdown()


def test_normalize_open_path_rejects_urls() -> None:
    from ageval.viewer.server import normalize_open_path

    assert normalize_open_path("jobs/x") == "/jobs/x"
    with pytest.raises(Exception, match="invalid open path"):
        normalize_open_path("http://evil.example/")


def test_http_removed_package_browse_404(viewer_server: str) -> None:
    """Old package-file browse endpoints are not part of the product surface."""
    for path in (
        "/api/dataset",
        "/api/commands",
        "/api/tasks/alpha",
        "/api/tasks/alpha/tree",
        "/api/tasks/alpha/file?path=task.yaml",
    ):
        with pytest.raises(HTTPError) as ei:
            urlopen(f"{viewer_server}{path}", timeout=5)  # noqa: S310
        assert ei.value.code == 404
