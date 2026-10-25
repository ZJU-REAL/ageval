"""Kill a parent-loop episode and resume it without repeating finished steps."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from ageval.plugins.contrib.docker.images import daemon_available

REPO = Path(__file__).resolve().parents[2]
TERMINUS = REPO / "examples" / "datasets" / "terminus-2-min"

_HELLO = json.dumps(
    {
        "analysis": "write",
        "plan": "printf",
        "commands": [{"keystrokes": "printf 'hello\\n' > hello.txt\n", "duration": 0.5}],
        "task_complete": False,
    }
)
_DONE = json.dumps(
    {"analysis": "done", "plan": "stop", "commands": [], "task_complete": True}
)


class _Gateway:
    def __init__(self, bodies: list[dict[str, Any]], *, block_after: int) -> None:
        self.bodies = bodies
        self.block_after = block_after
        self.prompts: list[str] = []
        self._release = Event()
        self.holding = Event()
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
                if len(owner.prompts) >= owner.block_after and not owner._release.is_set():
                    owner.holding.set()
                    owner._release.wait(timeout=120)
                    return
                owner.prompts.append(
                    json.dumps(body.get("messages"), ensure_ascii=False, default=str)
                )
                payload = owner.bodies[min(len(owner.prompts) - 1, len(owner.bodies) - 1)]
                raw = json.dumps(payload).encode("utf-8")
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


def _chat(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _bash(command: str, call_id: str) -> dict[str, Any]:
    return _chat(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "bash", "arguments": json.dumps({"command": command})},
                }
            ],
        }
    )


def _text(content: str) -> dict[str, Any]:
    body = _chat({"role": "assistant", "content": content})
    body["choices"][0]["finish_reason"] = "stop"
    return body


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["AGEVAL_HOME"] = str(home)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _install(home: Path, *plugin_ids: str) -> None:
    from ageval.plugins.store import install_from_path

    os.environ["AGEVAL_HOME"] = str(home)
    for plugin_id in plugin_ids:
        install_from_path(REPO / "plugins" / plugin_id)


def _ageval(env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def _kill_when_holding(
    gateway: _Gateway,
    dataset: Path,
    profiles: Path,
    env: dict[str, str],
    task: str,
    log_path: Path,
) -> Path:
    with log_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ageval.cli.main",
                "run",
                str(dataset),
                "--task",
                task,
                "--profiles",
                str(profiles),
            ],
            cwd=str(dataset),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err,
            start_new_session=True,
        )
        try:
            held = gateway.holding.wait(timeout=180)
            if not held:
                if proc.poll() is not None:
                    proc.wait(timeout=5)
                preview = log_path.read_text(encoding="utf-8")[-2000:]
                pytest.fail(f"run never reached the blocked model call\n{preview}")
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
        except Exception:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            raise
    attempt = _unsealed(dataset)
    if attempt is None:
        pytest.fail("killed run left no unsealed attempt")
    return attempt


def _unsealed(dataset: Path) -> Path | None:
    runs = dataset / ".ageval" / "runs"
    if not runs.is_dir():
        return None
    found = [
        path
        for path in runs.iterdir()
        if path.is_dir()
        and (path / "activity.jsonl").is_file()
        and not (path / "result.json").is_file()
    ]
    if not found:
        return None
    found.sort(key=lambda path: path.stat().st_mtime)
    return found[-1]


def _header_handle(attempt: Path) -> dict[str, Any]:
    first = (attempt / "activity.jsonl").read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(first)
    handle = row["payload"].get("environment_handle")
    return handle if isinstance(handle, dict) else {}


def test_miniswe_resume_does_not_requery_finished_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    _install(home, "miniswe")
    dataset = tmp_path / "ds"
    task = dataset / "tasks" / "write"
    task.mkdir(parents=True)
    (dataset / "ageval.yaml").write_text(
        "format: ageval.dataset/1\ndataset_id: examples/miniswe-resume\n"
        "version: '0.1.0'\ntasks:\n  root: tasks\n",
        encoding="utf-8",
    )
    (task / "task.yaml").write_text(
        "\n".join(
            [
                "format: ageval.task/1",
                "task_id: write",
                "parameters:",
                "  active_profile: solver",
                "agent_profiles:",
                "  - id: solver",
                "limits:",
                "  wall_time_seconds: 180",
                "  agent_invocations: 1",
                "evaluation:",
                "  inputs: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (task / "run.py").write_text(
        "\n".join(
            [
                "from ageval_sdk import RunContext, RunTerminal",
                "async def run(ctx: RunContext) -> RunTerminal:",
                "    async with ctx.agent.session('solver', max_turns=1) as session:",
                "        invoked = await session.invoke('Use the bash tool to finish.')",
                "    if not invoked.get('ok'):",
                "        return RunTerminal.failed(str(invoked.get('error') or 'failed'))",
                "    return RunTerminal.completed('done')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (task / "evaluator.py").write_text(
        "def evaluate(inputs):\n"
        "    del inputs\n"
        "    return {'status': 'PASS', 'score': 1.0, 'metrics': {}}\n",
        encoding="utf-8",
    )
    gateway = _Gateway(
        [
            _bash("printf 'step-one\\n' > marker.txt", "call_1"),
            _bash("printf 'step-two\\n' >> marker.txt", "call_2"),
            _bash("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT", "call_3"),
        ],
        block_after=2,
    )
    profiles = dataset / "profiles.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: local",
                "agent_profiles:",
                "  solver:",
                "    executor: miniswe",
                "    model: {id: mock, api: chat}",
                f"    base_url: {gateway.base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: miniswe",
                "        options: {stream: false, step_limit: 4}",
                "      - plugin: local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = _env(home)
    try:
        attempt = _kill_when_holding(
            gateway, dataset, profiles, env, "write", tmp_path / "miniswe.err"
        )
        gateway._release.set()
        assert len(gateway.prompts) == 2
        resumed = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            "write",
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
            cwd=dataset,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        assert len(gateway.prompts) == 3
        assert "call_2" not in gateway.prompts[0]
        assert "call_2" in gateway.prompts[2]
        result = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
        assert result["status"] == "PASS"
        assert (attempt / "trajectory.jsonl").is_file()
    finally:
        gateway.close()


@pytest.mark.skipif(not daemon_available(), reason="docker daemon is not available")
def test_terminus_resume_reuses_the_live_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    _install(home, "terminus-2")
    dataset = Path(shutil.copytree(TERMINUS, tmp_path / "terminus-2-min"))
    gateway = _Gateway([_text(_HELLO), _text(_DONE)], block_after=1)
    profiles = dataset / "profiles.resume.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: docker",
                "agent_profiles:",
                "  solver:",
                "    executor: terminus-2",
                "    model: {id: mock, api: chat}",
                f"    base_url: {gateway.base}",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: terminus-2",
                "        options: {parser: json, step_limit: 4, cmd_timeout: 90}",
                "      - plugin: docker",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = _env(home)
    try:
        attempt = _kill_when_holding(
            gateway, dataset, profiles, env, "hello", tmp_path / "terminus.err"
        )
        before = _header_handle(attempt).get("container_id")
        gateway._release.set()
        assert len(gateway.prompts) == 1
        resumed = _ageval(
            env,
            "run",
            str(dataset),
            "--task",
            "hello",
            "--profiles",
            str(profiles),
            "--resume",
            attempt.name,
            cwd=dataset,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr, gateway.prompts)
        assert len(gateway.prompts) == 2
        assert "printf" not in gateway.prompts[0]
        assert "printf" in gateway.prompts[1]
        after = _header_handle(attempt).get("container_id")
        assert before and before == after
        result = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
        assert result["status"] == "PASS"
        assert (attempt / "trajectory.jsonl").is_file()
    finally:
        gateway.close()
