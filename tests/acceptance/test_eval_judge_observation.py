"""Opt-in evaluator SDK invoke writes evaluation/observation.jsonl."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "eval-judge-min"
GOLD = "secret-gold-token-eval-judge"


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


def _serve_judge() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            raw = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ignored-verdict"}}]}
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
    return server, f"http://{host}:{port}/v1"


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


def test_lock_mixed_acp_and_openai_http_on_judge_fixture() -> None:
    env = os.environ.copy()
    proc = _ageval(
        env,
        "lock",
        str(FIXTURE),
        "--task",
        "judge-score",
        "--profiles",
        str(FIXTURE / "profiles.mixed.yaml"),
        cwd=FIXTURE,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    bindings = data["extension_bindings"]
    assert bindings["solver"]["slots"]["executor"]["plugin"] == "acp"
    assert bindings["judge"]["slots"]["executor"]["plugin"] == "openai-http"
    overlay = data["job_overlay"]["agent_profiles"]
    assert overlay["solver"]["api_key"] != overlay["judge"]["api_key"]
    assert "sk-" not in json.dumps(data)


def test_no_sdk_evaluator_has_no_observation_jsonl(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "no-sdk", ignore=shutil.ignore_patterns(".ageval"))
    )
    (dataset / "tasks" / "judge-score" / "evaluator.py").write_text(
        "from pathlib import Path\n"
        "import json\n"
        "def evaluate(inputs):\n"
        "    data = json.loads(Path(inputs['artifacts']['result']).read_text())\n"
        "    ok = data.get('ok') is True\n"
        "    return {'status': 'PASS' if ok else 'FAIL', 'score': 1.0 if ok else 0.0}\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-solver-locator"
    env["JUDGE_API_KEY"] = "ci-judge-locator"
    env["SOLVER_BASE_URL"] = "http://127.0.0.1:9/v1"
    env["JUDGE_BASE_URL"] = "http://127.0.0.1:9/v1"
    ran = _ageval(env, "run", str(dataset), "--task", "judge-score", cwd=dataset)
    assert ran.returncode == 0, ran.stderr or ran.stdout
    result = json.loads(ran.stdout)
    run_dir = _run_dir(dataset, result)
    assert result["status"] == "PASS"
    assert not (run_dir / "evaluation" / "observation.jsonl").exists()
    assert not (run_dir / "evaluation" / "checks.json").exists()
    assert (run_dir / "result.json").is_file()


def test_opt_in_judge_writes_observation_not_trajectory(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "eval-judge", ignore=shutil.ignore_patterns(".ageval"))
    )
    server, base = _serve_judge()
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-solver-locator"
    env["JUDGE_API_KEY"] = "ci-judge-locator"
    env["SOLVER_BASE_URL"] = base
    env["JUDGE_BASE_URL"] = base
    try:
        ran = _ageval(env, "run", str(dataset), "--task", "judge-score", cwd=dataset)
        assert ran.returncode == 0, ran.stderr or ran.stdout
        result = json.loads(ran.stdout)
        assert result["status"] == "PASS"
        assert result.get("metrics", {}).get("exact") == 1
        run_dir = _run_dir(dataset, result)
        obs = run_dir / "evaluation" / "observation.jsonl"
        traj = run_dir / "trajectory.jsonl"
        assert obs.is_file()
        dumped_obs = obs.read_text(encoding="utf-8")
        dumped_traj = traj.read_text(encoding="utf-8") if traj.is_file() else ""
        assert GOLD not in dumped_obs
        assert GOLD not in dumped_traj
        rows = [json.loads(line) for line in dumped_obs.splitlines() if line.strip()]
        assert rows
        assert all(row.get("role") != "user" for row in rows)
        assert any(row.get("profile_id") == "judge" for row in rows)
        assert any(row.get("type") == "terminal" for row in rows)
        assert "ignored-verdict" in dumped_obs
        traj_rows = [json.loads(line) for line in dumped_traj.splitlines() if line.strip()]
        assert all(row.get("profile_id") != "judge" for row in traj_rows)
        assert "ignored-verdict" not in dumped_traj
        assert not (run_dir / "evaluation" / "evaluator_raw.json").exists()
        result_doc = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        assert result_doc["status"] == "PASS"
        assert "ignored-verdict" not in json.dumps(result_doc)
    finally:
        server.shutdown()
