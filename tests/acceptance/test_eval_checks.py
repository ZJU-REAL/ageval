"""Opt-in evaluator checks.json; bind ignores per-check status."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from ageval.evidence.slim import slim_sealed_attempt
from ageval.registry.results_archive import build_attempt_archive

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "eval-checks-min"
GOLD = "secret-gold-token-eval-checks"


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


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    env["SOLVER_API_KEY"] = "ci-solver-locator"
    env["JUDGE_API_KEY"] = "ci-judge-locator"
    env["SOLVER_BASE_URL"] = "http://127.0.0.1:9/v1"
    env["JUDGE_BASE_URL"] = "http://127.0.0.1:9/v1"
    return env


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


def test_lock_script_score_fixture() -> None:
    proc = _ageval(_base_env(), "lock", str(FIXTURE), "--task", "script-score", cwd=FIXTURE)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_default_evaluator_without_checks_writes_no_file(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "no-checks", ignore=shutil.ignore_patterns(".ageval"))
    )
    (dataset / "tasks" / "script-score" / "evaluator.py").write_text(
        "from pathlib import Path\n"
        "import json\n"
        "def evaluate(inputs):\n"
        "    data = json.loads(Path(inputs['artifacts']['result']).read_text())\n"
        "    ok = data.get('ok') is True\n"
        "    return {'status': 'PASS' if ok else 'FAIL', 'score': 1.0 if ok else 0.0}\n",
        encoding="utf-8",
    )
    ran = _ageval(_base_env(), "run", str(dataset), "--task", "script-score", cwd=dataset)
    assert ran.returncode == 0, ran.stderr or ran.stdout
    result = json.loads(ran.stdout)
    run_dir = _run_dir(dataset, result)
    assert result["status"] == "PASS"
    assert not (run_dir / "evaluation" / "checks.json").exists()
    assert not (run_dir / "evaluation" / "observation.jsonl").exists()
    assert (run_dir / "result.json").is_file()


def test_opt_in_checks_do_not_rewrite_bind(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "checks", ignore=shutil.ignore_patterns(".ageval"))
    )
    ran = _ageval(_base_env(), "run", str(dataset), "--task", "script-score", cwd=dataset)
    assert ran.returncode == 0, ran.stderr or ran.stdout
    result = json.loads(ran.stdout)
    assert result["status"] == "PASS"
    assert result.get("score") == 1.0
    run_dir = _run_dir(dataset, result)
    checks_path = run_dir / "evaluation" / "checks.json"
    assert checks_path.is_file()
    body = json.loads(checks_path.read_text(encoding="utf-8"))
    assert body["schema"] == "ageval.evaluation.checks/1"
    ids = [row["id"] for row in body["checks"]]
    assert ids == ["audit", "files"]
    by_id = {row["id"]: row for row in body["checks"]}
    assert by_id["audit"]["status"] == "FAIL"
    assert by_id["files"]["status"] == "PASS"
    result_doc = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result_doc["status"] == "PASS"
    assert "checks" not in result_doc
    assert not (run_dir / "evaluation" / "evaluator_raw.json").exists()
    gold = (dataset / "tasks" / "script-score" / "evaluation" / "audit.py").read_text(
        encoding="utf-8"
    )
    dumped = checks_path.read_text(encoding="utf-8")
    assert "print(" not in dumped
    assert gold.strip() not in dumped


def test_slim_and_archive_keep_checks_drop_raw(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "slim", ignore=shutil.ignore_patterns(".ageval"))
    )
    ran = _ageval(_base_env(), "run", str(dataset), "--task", "script-score", cwd=dataset)
    assert ran.returncode == 0, ran.stderr or ran.stdout
    run_dir = _run_dir(dataset, json.loads(ran.stdout))
    (run_dir / "evaluation" / "evaluator_raw.json").write_text("{}\n", encoding="utf-8")
    slim_sealed_attempt(run_dir)
    assert (run_dir / "evaluation" / "checks.json").is_file()
    assert not (run_dir / "evaluation" / "evaluator_raw.json").exists()
    archive, _, _ = build_attempt_archive(run_dir, run_id=run_dir.name)
    import gzip
    import io
    import tarfile

    with (
        gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r:") as tar,
    ):
        names = {m.name for m in tar.getmembers() if m.isfile()}
    prefix = f".ageval/runs/{run_dir.name}"
    assert f"{prefix}/evaluation/checks.json" in names
    assert f"{prefix}/evaluation/evaluator_raw.json" not in names


def test_compose_checks_and_observation(tmp_path: Path) -> None:
    dataset = Path(
        shutil.copytree(FIXTURE, tmp_path / "compose", ignore=shutil.ignore_patterns(".ageval"))
    )
    server, base = _serve_judge()
    env = _base_env()
    env["SOLVER_BASE_URL"] = base
    env["JUDGE_BASE_URL"] = base
    try:
        ran = _ageval(env, "run", str(dataset), "--task", "compose-score", cwd=dataset)
        assert ran.returncode == 0, ran.stderr or ran.stdout
        result = json.loads(ran.stdout)
        assert result["status"] == "PASS"
        run_dir = _run_dir(dataset, result)
        checks_path = run_dir / "evaluation" / "checks.json"
        obs = run_dir / "evaluation" / "observation.jsonl"
        assert checks_path.is_file()
        assert obs.is_file()
        assert (run_dir / "result.json").is_file()
        dumped_obs = obs.read_text(encoding="utf-8")
        dumped_checks = checks_path.read_text(encoding="utf-8")
        assert GOLD not in dumped_obs
        assert GOLD not in dumped_checks
        rows = [json.loads(line) for line in dumped_obs.splitlines() if line.strip()]
        assert all(row.get("role") != "user" for row in rows)
        assert any(row.get("profile_id") == "judge" for row in rows)
        body = json.loads(dumped_checks)
        assert [row["id"] for row in body["checks"]] == ["files", "gold-present"]
        assert not (run_dir / "evaluation" / "evaluator_raw.json").exists()
    finally:
        server.shutdown()
