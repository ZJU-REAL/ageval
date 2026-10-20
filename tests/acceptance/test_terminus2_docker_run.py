"""Named terminus-2 example: lock always, docker run when a daemon is up.

The model is a loopback chat server. No Harbor CLI and no frontier model.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ageval.plugins.contrib.docker.images import daemon_available
from ageval.registry.agent_package import assert_agent_package

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "examples" / "datasets" / "terminus-2-min"
AGENT = REPO / "examples" / "agents" / "terminus-2-default"

_BATCH = {
    "analysis": "write hello.txt",
    "plan": "printf",
    "commands": [{"keystrokes": "printf 'hello\\n' > hello.txt\n", "duration": 1.0}],
    "task_complete": True,
}


def _skip_without_docker() -> None:
    if os.environ.get("AGEVAL_SKIP_DOCKER") == "1":
        pytest.skip("AGEVAL_SKIP_DOCKER=1")
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")


def _gateway() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            body = {
                "choices": [{"message": {"role": "assistant", "content": json.dumps(_BATCH)}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 12},
            }
            raw = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name="terminus2-gateway", daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def _env(home: Path, base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    env["OPENAI_BASE_URL"] = base_url
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    return env


def _install(home: Path) -> None:
    from ageval.plugins.store import install_from_path

    home.mkdir()
    previous = os.environ.get("AGEVAL_HOME")
    os.environ["AGEVAL_HOME"] = str(home)
    try:
        install_from_path(REPO / "plugins" / "terminus-2")
    finally:
        if previous is None:
            os.environ.pop("AGEVAL_HOME", None)
        else:
            os.environ["AGEVAL_HOME"] = previous


def _ageval(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=1200,
    )


def test_agent_package_and_lock(tmp_path: Path) -> None:
    assert_agent_package(AGENT)
    home = tmp_path / "ageval-home"
    _install(home)
    env = _env(home, "https://example.invalid/v1")
    locked = _ageval(env, "lock", str(DATASET), "--task", "hello")
    assert locked.returncode == 0, locked.stderr or locked.stdout
    data = json.loads(locked.stdout)
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "terminus-2"
    assert "ci-loopback-placeholder" not in json.dumps(data)


def test_docker_run_writes_hello(tmp_path: Path) -> None:
    _skip_without_docker()
    dataset = Path(
        shutil.copytree(
            DATASET,
            tmp_path / "terminus-2-min",
            ignore=shutil.ignore_patterns(".ageval"),
        )
    )
    home = tmp_path / "ageval-home"
    _install(home)
    server, base = _gateway()
    try:
        env = _env(home, base)
        locked = _ageval(env, "lock", str(dataset), "--task", "hello")
        assert locked.returncode == 0, locked.stderr or locked.stdout
        ran = _ageval(env, "run", str(dataset), "--task", "hello")
    finally:
        server.shutdown()
    assert ran.returncode == 0, ran.stderr or ran.stdout
    result = json.loads(ran.stdout)
    assert result["status"] == "PASS"
    runs = dataset / ".ageval" / "runs"
    trajectories = sorted(runs.rglob("trajectory.jsonl"))
    assert trajectories, f"no trajectory under {runs}"
    text = trajectories[-1].read_text(encoding="utf-8")
    assert "terminus-2" in text
    assert '"type": "tool_call"' in text
    assert "printf" in text
    assert "ci-loopback-placeholder" not in text
