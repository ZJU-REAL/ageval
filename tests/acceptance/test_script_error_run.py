"""ScriptError and engine ERROR titles through real ageval run on environment: local."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROFILES = """\
format: ageval.profiles/1
environment: local
agent_profiles:
  solver:
    executor: openai-http
    model: mock
    api_key: ${SOLVER_API_KEY}
    base_url: ${SOLVER_BASE_URL}
    extensions:
      - plugin: openai-http
      - plugin: local
"""

_DATASET = """\
format: ageval.dataset/1
dataset_id: test/script-error
version: "0.1.0"
description: Script and engine ERROR titles.
tasks:
  root: tasks
"""

_TASK = """\
format: ageval.task/1
task_id: {task_id}
parameters:
  seed: 1
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 30
  environment_seconds: 30
  evaluate_seconds: 30
  agent_invocations: 1
"""

_PASS_EVAL = """\
def evaluate(inputs):
    del inputs
    return {"status": "PASS", "score": 1.0, "metrics": {}}
"""

_FAIL_EVAL = """\
def evaluate(inputs):
    del inputs
    return {"status": "FAIL", "score": 0.0, "metrics": {}}
"""

_COMPLETED = """\
from ageval_sdk import RunContext, RunTerminal

async def run(ctx: RunContext) -> RunTerminal:
    del ctx
    return RunTerminal.completed("ok")
"""


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-solver-locator"
    env["SOLVER_BASE_URL"] = "http://127.0.0.1:9/v1"
    env.setdefault("ZHIPU_API_KEY", "ci-offline-placeholder")
    env.setdefault("glm_coding_api_key", "ci-offline-placeholder")
    return env


def _write(
    root: Path, task_id: str, run_py: str, evaluator_py: str, setup: str | None = None
) -> None:
    task = root / "tasks" / task_id
    task.mkdir(parents=True)
    (task / "task.yaml").write_text(_TASK.format(task_id=task_id), encoding="utf-8")
    (task / "run.py").write_text(run_py, encoding="utf-8")
    (task / "evaluator.py").write_text(evaluator_py, encoding="utf-8")
    if setup is not None:
        env_dir = task / "environment"
        env_dir.mkdir()
        (env_dir / "setup.sh").write_text(setup, encoding="utf-8")


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "script-error"
    root.mkdir()
    (root / "ageval.yaml").write_text(_DATASET, encoding="utf-8")
    (root / "profiles.yaml").write_text(_PROFILES, encoding="utf-8")
    _write(
        root,
        "run-script-error",
        "from ageval_sdk import ScriptError\n"
        "async def run(ctx):\n"
        "    del ctx\n"
        '    raise ScriptError(title="Workspace seed missing", message="seed.txt is not a file")\n',
        _PASS_EVAL,
    )
    _write(
        root,
        "eval-script-error",
        _COMPLETED,
        "from ageval_sdk import ScriptError\n"
        "def evaluate(inputs):\n"
        "    del inputs\n"
        '    raise ScriptError(title="Judge response empty", message="judge returned no text")\n',
    )
    _write(
        root,
        "run-value-error",
        'async def run(ctx):\n    del ctx\n    raise ValueError("seed.txt is not a file")\n',
        _PASS_EVAL,
    )
    _write(
        root,
        "setup-failed",
        _COMPLETED,
        _PASS_EVAL,
        setup="echo seed missing >&2\nexit 1\n",
    )
    _write(root, "judged-pass", _COMPLETED, _PASS_EVAL)
    _write(
        root,
        "invalid-terminal",
        "from ageval_sdk import RunContext, RunTerminal\n"
        "async def run(ctx: RunContext) -> RunTerminal:\n"
        "    del ctx\n"
        '    return RunTerminal.failed("invalid_terminal")\n',
        _FAIL_EVAL,
    )
    return root


def _run(dataset: Path, task: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    proc = subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "run", str(dataset), "--task", task],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(dataset),
        env=_env(),
        timeout=60,
    )
    assert proc.stdout.strip(), proc.stderr
    document = json.loads(proc.stdout)
    assert isinstance(document, dict)
    return proc, document


def _result(dataset: Path, document: dict[str, object]) -> dict[str, object]:
    path = dataset / str(document["logs"]) / "result.json"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _facts(dataset: Path, document: dict[str, object]) -> list[dict[str, object]]:
    summary = json.loads(
        (dataset / str(document["logs"]) / "summary.json").read_text(encoding="utf-8")
    )
    facts = summary.get("facts")
    assert isinstance(facts, list)
    return [fact for fact in facts if isinstance(fact, dict)]


def test_script_error_in_run_py(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    proc, document = _run(dataset, "run-script-error")
    assert proc.returncode == 2, proc.stderr
    result = _result(dataset, document)
    assert result["status"] == "ERROR"
    assert result["score"] is None
    assert result["limit"] is None
    assert result["error"] == {
        "phase": "run",
        "title": "Workspace seed missing",
        "message": "seed.txt is not a file",
    }
    assert document["error"] == result["error"]


def test_script_error_in_evaluator_py(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    proc, document = _run(dataset, "eval-script-error")
    assert proc.returncode == 2, proc.stderr
    result = _result(dataset, document)
    assert result["status"] == "ERROR"
    assert result["score"] is None
    assert result["limit"] is None
    assert result["error"] == {
        "phase": "evaluate",
        "title": "Judge response empty",
        "message": "judge returned no text",
    }


def test_value_error_uses_the_class_name(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    proc, document = _run(dataset, "run-value-error")
    assert proc.returncode == 2, proc.stderr
    result = _result(dataset, document)
    assert result["error"] == {
        "phase": "run",
        "title": "ValueError",
        "message": "seed.txt is not a file",
    }


def test_setup_failure_uses_the_environment_token(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    proc, document = _run(dataset, "setup-failed")
    assert proc.returncode == 2, proc.stderr
    result = _result(dataset, document)
    assert result["status"] == "ERROR"
    assert result["score"] is None
    assert result["limit"] is None
    error = result["error"]
    assert isinstance(error, dict)
    assert error["phase"] == "environment"
    assert error["title"] == "environment_setup_failed"
    assert "exited 1" in str(error["message"])
    assert not any(fact.get("phase") == "run" for fact in _facts(dataset, document))


def test_pass_and_failed_terminal_leave_error_null(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    passed, pass_doc = _run(dataset, "judged-pass")
    assert passed.returncode == 0, passed.stderr
    pass_result = _result(dataset, pass_doc)
    assert pass_result["status"] == "PASS"
    assert pass_result["error"] is None
    assert pass_result["limit"] is None

    failed, fail_doc = _run(dataset, "invalid-terminal")
    assert failed.returncode == 1, failed.stderr
    fail_result = _result(dataset, fail_doc)
    assert fail_result["status"] == "FAIL"
    assert fail_result["score"] == 0.0
    assert fail_result["error"] is None
    assert any(fact.get("phase") == "evaluate" for fact in _facts(dataset, fail_doc))
