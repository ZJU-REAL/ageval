"""egress: llm proxy allowlists bound hosts and refuses the rest."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ageval.plugins.contrib.docker.egress import AllowlistProxy


def test_proxy_allows_listed_host_and_forbids_others() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=origin.serve_forever, daemon=True).start()
    origin_port = int(origin.server_address[1])
    proxy = AllowlistProxy(["127.0.0.1"])
    try:
        proxy.start()
        proxy_url = f"http://127.0.0.1:{proxy.port}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
        with opener.open(f"http://127.0.0.1:{origin_port}/", timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == b"ok"
        with pytest.raises(urllib.error.HTTPError) as forbidden:
            opener.open("http://example.com/", timeout=5)
        assert forbidden.value.code == 403
    finally:
        proxy.stop()
        origin.shutdown()


def test_empty_allowlist_refuses_to_start() -> None:
    proxy = AllowlistProxy([])
    with pytest.raises(RuntimeError, match="base_url"):
        proxy.start()


def test_docker_host_llm_egress_without_hosts_fails_closed(tmp_path: Path) -> None:
    from ageval.environments.protocol import BoxSpec, EnvironmentFailure
    from ageval.plugins.contrib.docker.host import DockerHost

    host = DockerHost(
        spec=BoxSpec(attempt_root=tmp_path / "box", task_root=tmp_path, repo_root=tmp_path),
        options={"egress": "llm", "egress_allowlist": []},
    )
    with pytest.raises(EnvironmentFailure, match="base_url"):
        host._start_egress_proxy()
