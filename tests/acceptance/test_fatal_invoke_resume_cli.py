"""Public suite run: a fatal invoke resumes in place and reaches the evaluator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

_DATASET = """\
format: ageval.dataset/1
dataset_id: test/fatal-invoke-resume
version: "0.1.0"
description: Fatal invoke recovery.
tasks:
  root: tasks
"""

_PROFILES = """\
format: ageval.profiles/1
environment: local
agent_profiles:
  solver:
    executor: openai-http
    model: {id: mock}
    api_key: ${SOLVER_API_KEY}
    base_url: ${SOLVER_BASE_URL}
    extensions:
      - plugin: openai-http
      - plugin: local
"""

_TASK = """\
format: ageval.task/1
task_id: invoke
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 30
  environment_seconds: 30
  evaluate_seconds: 30
  agent_invocations: 2
artifacts:
  publishable:
    - id: result
      path: artifacts/result.json
evaluation:
  inputs:
    - artifact: result
      target: artifacts/result.json
"""

_RUN = """\
from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    async with ctx.agent.session("solver") as session:
        first = await session.invoke("first turn")
        second = await session.invoke("second turn")
    ctx.publish_json("result", {"first": first["ok"], "second": second["ok"]})
    return RunTerminal.completed()
"""

_EVALUATOR = """\
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    Path({marker!r}).write_text("evaluated\\n", encoding="utf-8")
    raw = json.loads(Path(inputs["artifacts"]["result"]).read_text(encoding="utf-8"))
    status = "PASS" if raw == {{"first": True, "second": True}} else "FAIL"
    return {{"status": status, "score": 1.0 if status == "PASS" else 0.0, "metrics": {{}}}}
"""


def _serve() -> tuple[ThreadingHTTPServer, str, dict[str, Any]]:
    state: dict[str, Any] = {"requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            state["requests"] += 1
            if state["requests"] == 2:
                raw = json.dumps(
                    {
                        "error": {
                            "message": "insufficient balance",
                            "type": "billing_error",
                        }
                    }
                ).encode("utf-8")
                self.send_response(403)
            else:
                raw = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "ok",
                                }
                            }
                        ]
                    }
                ).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1", state


def _dataset(root: Path, base_url: str) -> tuple[Path, Path]:
    dataset = root / "dataset"
    task = dataset / "tasks" / "invoke"
    task.mkdir(parents=True)
    marker = dataset / "evaluated.txt"
    (dataset / "ageval.yaml").write_text(_DATASET, encoding="utf-8")
    (dataset / "profiles.yaml").write_text(_PROFILES, encoding="utf-8")
    (task / "task.yaml").write_text(_TASK, encoding="utf-8")
    (task / "run.py").write_text(_RUN, encoding="utf-8")
    (task / "evaluator.py").write_text(
        _EVALUATOR.format(marker=str(marker)),
        encoding="utf-8",
    )
    return dataset, marker


def _run_cli(dataset: Path, base_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-fatal-invoke-placeholder"
    env["SOLVER_BASE_URL"] = base_url
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "run", str(dataset), "--json", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=env,
        timeout=90,
    )


def _document(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.stdout.strip(), result.stderr
    document = json.loads(result.stdout.strip().splitlines()[-1])
    assert isinstance(document, dict)
    return document


@pytest.mark.parametrize("retry_args", [(), ("--retry-errors",)], ids=["resume", "retry-errors"])
def test_fatal_invoke_keeps_recovery_and_resumes_in_place(
    tmp_path: Path,
    retry_args: tuple[str, ...],
) -> None:
    server, base_url, state = _serve()
    try:
        dataset, marker = _dataset(tmp_path, base_url)
        first_proc = _run_cli(dataset, base_url)
        assert first_proc.returncode == 2, (first_proc.stdout, first_proc.stderr)
        first = _document(first_proc)
        assert first["counts"] == {"pass": 0, "fail": 0, "error": 1, "skipped": 0}
        assert len(first["attempts"]) == 1
        failed_row = first["attempts"][0]
        assert failed_row["status"] == "ERROR"
        assert failed_row["error"]["phase"] == "run"
        assert failed_row["error"]["title"] == "agent_invoke_failed"
        assert str(failed_row["error"]["message"]).startswith("ModelConfigError")
        assert not marker.exists()

        attempt = dataset / ".ageval" / "runs" / str(failed_row["run_id"])
        sealed = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
        assert sealed["status"] == "ERROR"
        assert sealed["error"]["title"] == "agent_invoke_failed"
        assert (attempt / "activity.jsonl").is_file()
        assert (attempt / "checkpoints").is_dir()
        assert (attempt / "replay-input.json").is_file()
        assert state["requests"] == 2

        second_proc = _run_cli(
            dataset,
            base_url,
            "--resume-suite",
            str(first["suite_run_id"]),
            *retry_args,
        )
        assert second_proc.returncode == 0, (second_proc.stdout, second_proc.stderr)
        second = _document(second_proc)
        assert second["config_fingerprint"] == first["config_fingerprint"]
        assert second["new_attempts"] == 1
        assert second["skipped_attempts"] == 0
        assert second.get("retried_attempts", 0) == 0
        assert len(second["attempts"]) == 1
        resumed = second["attempts"][0]
        assert resumed["run_id"] == failed_row["run_id"]
        assert resumed["status"] == "PASS"
        assert "previous" not in resumed
        assert marker.read_text(encoding="utf-8") == "evaluated\n"
        assert state["requests"] == 3

        rewritten = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
        assert rewritten["status"] == "PASS"
        assert rewritten["error"] is None
    finally:
        server.shutdown()
        server.server_close()
