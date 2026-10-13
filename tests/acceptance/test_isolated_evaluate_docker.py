"""Real docker: isolated evaluate starts a second container for published trees."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from ageval.plugins.contrib.docker.images import daemon_available

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "eval-isolated-min"


def _skip_without_docker() -> None:
    if os.environ.get("AGEVAL_SKIP_DOCKER") == "1":
        pytest.skip("AGEVAL_SKIP_DOCKER=1")
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")


def _ageval(env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=900,
    )


def _run_dir(dataset: Path, result: dict[str, object]) -> Path:
    logs = str(result.get("logs") or result.get("evidence_path") or "")
    root = dataset / logs if logs else dataset / ".ageval" / "runs"
    if root.is_file():
        return root.parent
    if (root / "result.json").is_file():
        return root
    runs = dataset / ".ageval" / "runs"
    found = sorted(p for p in runs.rglob("result.json"))
    assert found, f"no result.json under {runs}"
    return found[-1].parent


def test_isolated_evaluate_scores_published_tree_in_new_container(tmp_path: Path) -> None:
    _skip_without_docker()
    dataset = Path(
        shutil.copytree(
            FIXTURE,
            tmp_path / "eval-isolated",
            ignore=shutil.ignore_patterns(".ageval"),
        )
    )
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    ran = _ageval(env, "run", str(dataset), "--task", "publish-tree", cwd=dataset)
    assert ran.returncode == 0, ran.stderr or ran.stdout
    result = json.loads(ran.stdout)
    assert result["status"] == "PASS"
    metrics = result.get("metrics") or {}
    assert metrics.get("answer") == "42"
    assert metrics.get("leaked") is False

    run_dir = _run_dir(dataset, result)
    snap = run_dir / "task-artifacts" / "repo"
    assert (snap / "answer.txt").read_text(encoding="utf-8").strip() == "42"
    assert not (snap / "target").exists()
    assert not (snap / "target" / "leak.so").exists()

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    facts = summary.get("facts") or result.get("facts") or []
    names = {str(item.get("name")) for item in facts if isinstance(item, dict)}
    assert "evaluate_host_started" in names
    assert "evaluate_host_stopped" in names
    assert "environment_stopped" in names
    assert "workspace_materialized" in names
    assert not (run_dir / "evaluation" / "observation.jsonl").exists()


def _serve_judge() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            raw = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "score-ok"}}]}
            ).encode("utf-8")
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


def test_isolated_evaluate_llm_judge_on_published_tree(tmp_path: Path) -> None:
    """New eval container + parent JSON-RPC judge over harvested run artifacts."""
    _skip_without_docker()
    dataset = Path(
        shutil.copytree(
            FIXTURE,
            tmp_path / "eval-judge",
            ignore=shutil.ignore_patterns(".ageval"),
        )
    )
    (dataset / "profiles.yaml").write_text(
        "format: ageval.profiles/1\n"
        "environment: docker\n"
        "evaluate_host:\n"
        "  isolated: true\n"
        "agent_profiles:\n"
        "  judge:\n"
        "    executor: openai-http\n"
        "    model: {id: mock}\n"
        "    api_key: ${JUDGE_API_KEY}\n"
        "    base_url: ${JUDGE_BASE_URL}\n"
        "    extensions:\n"
        "      - plugin: openai-http\n"
        "      - plugin: docker\n",
        encoding="utf-8",
    )
    task = dataset / "tasks" / "publish-tree" / "task.yaml"
    text = task.read_text(encoding="utf-8")
    text = text.replace("agent_invocations: 0", "agent_invocations: 1")
    text = text.replace(
        "task_id: publish-tree\n",
        "task_id: publish-tree\nagent_profiles:\n  - id: judge\n",
    )
    task.write_text(text, encoding="utf-8")
    (dataset / "tasks" / "publish-tree" / "evaluator.py").write_text(
        "from __future__ import annotations\n"
        "import asyncio\n"
        "from pathlib import Path\n"
        "from typing import Any\n"
        "def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:\n"
        "    workspace = Path(str(inputs.get('workspace_dir') or ''))\n"
        "    answer_path = workspace / 'answer.txt'\n"
        "    answer = ''\n"
        "    if answer_path.is_file():\n"
        "        answer = answer_path.read_text(encoding='utf-8').strip()\n"
        "    leaked = (workspace / 'target' / 'leak.so').exists()\n"
        "    agent = inputs.get('agent')\n"
        "    judge_ok = False\n"
        "    err = 'agent_missing'\n"
        "    if agent is not None:\n"
        "        async def _invoke() -> Any:\n"
        "            async with agent.session('judge') as session:\n"
        "                return await session.invoke(f'score answer={answer}')\n"
        "        reply = asyncio.run(_invoke())\n"
        "        judge_ok = bool(reply.get('ok'))\n"
        "        err = str(reply.get('error') or '')\n"
        "    ok = answer == '42' and not leaked and judge_ok\n"
        "    return {'status': 'PASS' if ok else 'FAIL', 'score': 1.0 if ok else 0.0,\n"
        "            'metrics': {'answer': answer, 'leaked': leaked,\n"
        "                        'judge_ok': judge_ok, 'judge_error': err}}\n",
        encoding="utf-8",
    )
    server, base = _serve_judge()
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env.pop("AGEVAL_SKIP_DOCKER", None)
    env["JUDGE_API_KEY"] = "ci-judge-locator"
    env["JUDGE_BASE_URL"] = base
    try:
        ran = _ageval(env, "run", str(dataset), "--task", "publish-tree", cwd=dataset)
        assert ran.returncode == 0, ran.stderr or ran.stdout
        result = json.loads(ran.stdout)
        assert result["status"] == "PASS"
        metrics = result.get("metrics") or {}
        assert metrics.get("answer") == "42"
        assert metrics.get("leaked") is False
        assert metrics.get("judge_ok") is True
        run_dir = _run_dir(dataset, result)
        obs = run_dir / "evaluation" / "observation.jsonl"
        assert obs.is_file()
        rows = [
            json.loads(line)
            for line in obs.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(row.get("profile_id") == "judge" for row in rows)
        assert all(row.get("role") != "user" for row in rows)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        facts = summary.get("facts") or []
        names = {str(item.get("name")) for item in facts if isinstance(item, dict)}
        assert "evaluate_host_started" in names
        assert "workspace_materialized" in names
    finally:
        server.shutdown()
