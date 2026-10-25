"""Kill an in-flight tau2 dialog and resume it without repeating finished turns."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from ageval.plugins.contrib.docker.images import daemon_available

REPO = Path(__file__).resolve().parents[2]
JOURNEYS = REPO / "examples" / "datasets" / "minimal-demo"
TASK = "tau2-dialog-min"
_SERVICE_STEPS = 5

_SERVICE_SCRIPT: list[tuple[str, dict[str, Any]]] = [
    ("find_customer", {"email": "alex@example.com"}),
    ("get_order", {"order_id": "#W1001"}),
    ("get_product", {"item_id": "item_headphones"}),
    (
        "request_exchange",
        {
            "order_id": "#W1001",
            "from_item_ids": ["item_headphones"],
            "to_item_ids": ["item_headphones_black"],
        },
    ),
    ("done", {"note": "exchange requested"}),
]


class _Gateway:
    def __init__(self, *, block_after: int | None = None) -> None:
        self.service_calls = 0
        self.block_after = block_after
        self._release = Event()
        self._server, self.base = self._serve()

    def close(self) -> None:
        self._release.set()
        self._server.shutdown()

    def _serve(self) -> tuple[ThreadingHTTPServer, str]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                tools = body.get("tools") if isinstance(body.get("tools"), list) else []
                if tools:
                    held = (
                        owner.block_after is not None
                        and owner.service_calls >= owner.block_after
                        and not owner._release.is_set()
                    )
                    if held:
                        owner._release.wait(timeout=120)
                        return
                    idx = min(owner.service_calls, len(_SERVICE_SCRIPT) - 1)
                    owner.service_calls += 1
                    name, arguments = _SERVICE_SCRIPT[idx]
                    message: dict[str, Any] = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_{idx + 1}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    }
                else:
                    message = {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "message": (
                                    "Hi, I'm Alex. My email is alex@example.com and "
                                    "order #W1001 arrived with the wrong color headphones; "
                                    "I want the black variant instead."
                                )
                            }
                        ),
                    }
                raw = json.dumps({"choices": [{"message": message}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address[:2]
        return server, f"http://{host}:{port}/v1"


def test_resume_after_kill_does_not_repeat_finished_turns(tmp_path: Path) -> None:
    dataset, profiles, env, gateway = _prepare(tmp_path, environment="local")
    try:
        attempt = _kill_after_completed_invokes(dataset, profiles, env, minimum=2)
        gateway._release.set()
        completed = _completed_invokes(attempt / "activity.jsonl")
        seen = gateway.service_calls
        assert completed >= 2
        assert seen >= 1
        attempt_id = attempt.name
        resumed = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            "--resume",
            attempt_id,
            cwd=dataset,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        result = json.loads(resumed.stdout)
        assert result["status"] == "PASS"
        assert attempt_id in result["evidence_path"]
        # Finished turns are not sent again. An in-flight turn may be.
        assert gateway.service_calls <= seen + (_SERVICE_STEPS - (completed - 1))
        assert gateway.service_calls >= _SERVICE_STEPS
        assert (attempt / "result.json").is_file()
        assert (attempt / "trajectory.jsonl").is_file()
    finally:
        gateway.close()


def test_resume_rebuilds_removed_docker_container(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    dataset, profiles, env, gateway = _prepare(tmp_path, environment="docker")
    try:
        attempt = _kill_after_completed_invokes(dataset, profiles, env, minimum=2)
        gateway._release.set()
        header = _header(attempt / "activity.jsonl")
        handle = header["payload"]["environment_handle"]
        container_id = str(handle["container_id"])
        removed = subprocess.run(
            ["docker", "rm", "-f", container_id],
            check=False,
            capture_output=True,
            text=True,
        )
        assert removed.returncode == 0, removed.stderr
        resumed = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
            cwd=dataset,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        result = json.loads(resumed.stdout)
        assert result["status"] == "PASS"
        assert (attempt / "trajectory.jsonl").is_file()
    finally:
        gateway.close()


def test_corrupt_activity_seals_error(tmp_path: Path) -> None:
    dataset, profiles, env, gateway = _prepare(tmp_path, environment="local")
    try:
        attempt = _kill_after_completed_invokes(dataset, profiles, env, minimum=2)
        gateway._release.set()
        log_path = attempt / "activity.jsonl"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 3
        lines[1] = "{not-json"
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        resumed = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
            cwd=dataset,
        )
        assert resumed.returncode == 2, (resumed.stdout, resumed.stderr)
        result = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
        assert result["status"] == "ERROR"
        assert result["error"]["title"] == "activity_log_corrupt"
        before = (attempt / "result.json").read_bytes()
        again = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
            cwd=dataset,
        )
        assert again.returncode == 2
        assert (attempt / "result.json").read_bytes() == before
    finally:
        gateway.close()


def _prepare(
    tmp_path: Path, *, environment: str, block_after: int | None = 1
) -> tuple[Path, Path, dict[str, str], _Gateway]:
    dataset = Path(
        shutil.copytree(
            JOURNEYS, tmp_path / "minimal-demo", ignore=shutil.ignore_patterns(".ageval", ".env")
        )
    )
    gateway = _Gateway(block_after=block_after)
    profiles = dataset / "profiles.openai-http.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                f"environment: {environment}",
                "agent_profiles:",
                "  user:",
                "    executor: openai-http",
                "    model: {id: mock}",
                f"    base_url: {gateway.base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                f"      - plugin: {environment}",
                "  service:",
                "    executor: openai-http",
                "    model: {id: mock}",
                f"    base_url: {gateway.base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                f"      - plugin: {environment}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return dataset, profiles, env, gateway


def _kill_after_completed_invokes(
    dataset: Path, profiles: Path, env: dict[str, str], *, minimum: int
) -> Path:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "run",
            str(dataset),
            "--task",
            TASK,
            "--profiles",
            str(profiles),
        ],
        cwd=str(dataset),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 180
    attempt: Path | None = None
    try:
        while time.monotonic() < deadline:
            attempt = _unsealed_attempt(dataset, minimum=minimum)
            if attempt is not None:
                break
            if proc.poll() is not None:
                pytest.fail(f"run finished before the kill point (exit {proc.returncode})")
            time.sleep(0.2)
        if attempt is None:
            os.killpg(proc.pid, signal.SIGKILL)
            runs = dataset / ".ageval" / "runs"
            log = next(runs.rglob("activity.jsonl"), None) if runs.is_dir() else None
            preview = "no activity.jsonl"
            if log is not None:
                preview = log.read_text(encoding="utf-8")[:500]
            pytest.fail(f"timed out waiting for a completed invoke\n{preview}")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
    except Exception:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        raise
    return attempt


def _unsealed_attempt(dataset: Path, *, minimum: int) -> Path | None:
    runs = dataset / ".ageval" / "runs"
    if not runs.is_dir():
        return None
    for path in runs.iterdir():
        log = path / "activity.jsonl"
        if not path.is_dir() or not log.is_file() or (path / "result.json").is_file():
            continue
        if _completed_invokes(log) >= minimum:
            return path
    return None


def _completed_invokes(path: Path) -> int:
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") == "invoke" and row.get("status") == "completed":
            count += 1
    return count


def _header(path: Path) -> dict[str, Any]:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(first)
    assert row["kind"] == "attempt"
    return row


def _ageval(env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=180,
    )
