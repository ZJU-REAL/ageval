"""ASGI pipe shares Route.access + *Service; workers do not starve health."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from services.registry.app import build_default_state
from services.registry.asgi import build_asgi_app
from services.registry.http.dispatch import RegistryHttpApi

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.client import RegistryClient
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"


def _asgi_call(
    app: object,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> tuple[int, bytes]:
    header_list = [
        (k.lower().encode("latin1"), v.encode("latin1")) for k, v in (headers or {}).items()
    ]
    if body and not any(k == b"content-length" for k, _ in header_list):
        header_list.append((b"content-length", str(len(body)).encode("latin1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": header_list,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    messages: list[dict[str, object]] = []
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    import asyncio

    asyncio.run(app(scope, receive, send))  # type: ignore[operator]
    start = next(m for m in messages if m["type"] == "http.response.start")
    chunks = [m["body"] for m in messages if m["type"] == "http.response.body"]
    raw = b"".join(c if isinstance(c, bytes) else b"" for c in chunks)
    return int(start["status"]), raw  # type: ignore[arg-type]


def test_asgi_health_and_json(tmp_path: Path) -> None:
    state, token = build_default_state(tmp_path / "data", bootstrap_token="asgi", memory_blob=True)
    app = build_asgi_app(state)
    status, raw = _asgi_call(app, "GET", "/health")
    assert status == 200
    assert json.loads(raw.decode())["ok"] is True
    status, raw = _asgi_call(
        app,
        "GET",
        "/v1/orgs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200
    payload = json.loads(raw.decode())
    assert "items" in payload


def test_asgi_multipart_uses_stream_not_full_body() -> None:
    src = Path(__file__).resolve().parents[2] / "services" / "registry" / "asgi.py"
    text = src.read_text(encoding="utf-8")
    assert "request.stream()" in text
    assert "multipart/form-data" in text


def test_http_api_matches_asgi_health(tmp_path: Path) -> None:
    state, _token = build_default_state(tmp_path / "d", bootstrap_token="t", memory_blob=True)
    api = RegistryHttpApi(state)
    result = api.dispatch(method="GET", path="/health", headers={}, body=io.BytesIO())
    assert result.status == 200
    assert json.loads(result.body.decode())["service"] == "ageval-registry"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_health(url: str, *, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1.0) as resp:  # noqa: S310
                if int(resp.status) == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(0.15)
    raise AssertionError(f"registry did not become healthy: {last}")


@pytest.mark.skipif(
    os.environ.get("AGEVAL_SKIP_UVICORN_WORKERS") == "1",
    reason="operator skipped multi-worker smoke",
)
def test_uvicorn_workers_health_not_starved(tmp_path: Path) -> None:
    pytest.importorskip("uvicorn")
    pytest.importorskip("starlette")
    port = _free_port()
    data = tmp_path / "reg"
    data.mkdir()
    env = os.environ.copy()
    env["AGEVAL_REGISTRY_FORCE_LOCAL"] = "1"
    env["AGEVAL_REGISTRY_DATA_DIR"] = str(data)
    env["AGEVAL_REGISTRY_BOOTSTRAP_TOKEN"] = "worker-token"
    env["AGEVAL_REGISTRY_WORKERS"] = "2"
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "services.registry.app",
            "--local",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--data-dir",
            str(data),
            "--bootstrap-token",
            "worker-token",
            "--workers",
            "2",
        ],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_health(url)
        client = RegistryClient(url, token="worker-token")
        client.create_org(name="test", display_name="Test")
        archive, blob_digest, size = build_archive(FIXTURE)
        digest = compute_package_digest(FIXTURE)
        archive_path = tmp_path / "pkg.tar.gz"
        archive_path.write_bytes(archive)

        def _health() -> int:
            return int(client.health()["ok"] is True)

        def _publish() -> int:
            info = client.publish(
                dataset_id="test/publish-min",
                version="0.1.0",
                package_digest=digest,
                blob_digest=blob_digest,
                size=size,
                media_type=MEDIA_TYPE,
                visibility="private",
                archive=archive_path,
                org_id="test",
            )
            return int(info.dataset_id == "test/publish-min")

        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(_health) for _ in range(8)]
            futs.append(pool.submit(_publish))
            futs.extend(pool.submit(_health) for _ in range(8))
            results = [f.result(timeout=30) for f in as_completed(futs, timeout=40)]
        assert all(results)
        listed = client.list_packages()
        assert any(item.dataset_id == "test/publish-min" for item in listed)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)
