"""Attempt / trial evidence API tests for local viewer (#26)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.viewer import jobs, trials

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


def _seed_suite_run(db: Path, job_id: str = "suite_demo_job_001") -> str:
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "agent_label": "codex",
        "model_label": "gpt-test",
        "provider_label": "openai",
        "job_overlay": {"environment": "docker", "agent_profiles": {}},
        "created_at": "2026-07-14T19:46:20Z",
        "tasks": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_alpha_1"},
            {"task_id": "beta", "status": "FAIL", "score": 0.0, "run_id": "run_beta_1"},
        ],
        "task_refs": [
            {"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_alpha_1"},
            {"task_id": "beta", "status": "FAIL", "score": 0.0, "run_id": "run_beta_1"},
        ],
        "metrics": {
            "pass_rate": 0.5,
            "mean_score": 0.5,
            "n_tasks": 2,
            "n_pass": 1,
            "n_fail": 1,
            "n_error": 0,
            "missing_score_as": 0.0,
        },
        "exit_code": 1,
        "note": "per-task evaluator verdicts only; no suite-level PASS",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return job_id


def _write_evidence(db: Path, run_id: str, *, task_id: str = "alpha") -> Path:
    root = db / ".ageval" / "runs" / run_id
    inv = root / "agent" / "invocations" / "0001-inv_test"
    inv.mkdir(parents=True, exist_ok=True)
    (root / "evaluation").mkdir(parents=True, exist_ok=True)
    (root / "harness").mkdir(parents=True, exist_ok=True)

    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "digest": "sha256:deadbeef",
                "environment": "e2b",
                "job_overlay": {"environment": "e2b", "agent_profiles": {}},
                "profiles": [
                    {
                        "id": "main",
                        "executor": "acp",
                        "model": "test-model",
                        "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                        "capabilities": {"execution_mode": "acp-stdio"},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "score": 1.0,
                "kind": "e2b",
                "error": None,
                "agent_invocations": 1,
                "harness_kind": "completed",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps(
            {
                "schema": "ageval.evidence.summary/1",
                "run_id": run_id,
                "status": "PASS",
                "score": 1.0,
                "agent_invocations": 1,
                "phase_timing": {
                    "schema": "ageval.phase_timing/1",
                    "phases": [
                        {"id": "run", "label": "Agent Execution", "duration_ms": 4500.0},
                    ],
                    "total_ms": 4500.0,
                    "started_at": "2026-08-20T10:00:00Z",
                    "finished_at": "2026-08-20T10:00:04Z",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "effects.jsonl").write_text(
        json.dumps({"kind": "effect", "ok": True}) + "\n", encoding="utf-8"
    )
    (root / "cleanup.json").write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
    (root / "evaluation" / "raw.json").write_text(
        json.dumps({"verdict": "PASS", "score": 1.0}) + "\n", encoding="utf-8"
    )
    (inv / "metadata.json").write_text(
        json.dumps(
            {
                "invocation_id": "inv_test",
                "session_id": "sess_test",
                "profile_id": "main",
                "executor_kind": "acp",
                "model": "test-model",
                "status": "completed",
                "latency_ms": 1234.5,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    traj = [
        {
            "type": "turn",
            "role": "user",
            "content": "hello",
            "turn_index": 1,
            "source": "ageval",
            "session_id": "sess_test",
        },
        {
            "type": "turn",
            "role": "assistant",
            "content": "world",
            "turn_index": 1,
            "source": "acp",
            "session_id": "sess_test",
        },
        {
            "type": "terminal",
            "ok": True,
            "stop_reason": "end_turn",
            "source": "ageval",
            "turn_index": 1,
            "session_id": "sess_test",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "cached_read_tokens": 50,
                "cost": {"amount": 0.001, "currency": "USD"},
                "context": {"used": 200, "size": 100000},
                "sources": {"prompt_usage": True, "usage_update": True},
            },
        },
    ]
    (inv.parent.parent.parent / "trajectory.jsonl").write_text(
        "\n".join(json.dumps(x) for x in traj) + "\n", encoding="utf-8"
    )
    (inv / "final-response.json").write_text(
        json.dumps({"content": "world"}) + "\n", encoding="utf-8"
    )
    return root


def _clean_db(tmp_path: Path) -> Path:
    db = tmp_path / "db"
    shutil.copytree(SUITE, db, ignore=shutil.ignore_patterns(".ageval"))
    return db


def test_resolve_and_trial_detail(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_evidence(db, "run_alpha_1", task_id="alpha")

    evidence = trials.resolve_evidence_root(db, "run_alpha_1", task_id="alpha")
    assert evidence.is_dir()
    assert (evidence / "lock.json").is_file()

    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    assert detail["ok"] is True
    assert detail["trial"]["dataset_ref"] == "test/suite-min@0.1.0"
    assert detail["trial"]["dataset_id"] == "test/suite-min"
    assert detail["trial"]["dataset_version"] == "0.1.0"
    assert detail["trial"]["run_id"] == "run_alpha_1"
    assert detail["trial"]["status"] == "PASS"
    tabs = detail["trial"]["available_tabs"]
    assert "trajectory" in tabs
    assert "agent" in tabs
    assert "verifier" in tabs
    assert "lock" in tabs
    assert "runtime" in tabs
    assert detail["trial"].get("framework") == "acp"
    assert detail["trial"].get("environment") == "e2b"
    assert detail["trial"].get("started") == "2026-08-20T10:00:00Z"
    assert detail["trial"].get("duration") == "4.5s"
    actors = detail["trial"].get("actors") or []
    assert len(actors) == 1
    assert actors[0]["role"] == "main"
    assert actors[0]["agent"] == "pi"
    assert actors[0]["model"] == "test-model"
    assert actors[0].get("executor_kind") == "acp"
    assert detail["trial"].get("executor_kind") == "acp"
    assert actors[0]["invokes"] == 1
    assert actors[0]["latency_ms_sum"] == pytest.approx(1234.5)
    assert actors[0]["time_label"]
    assert "1.2s" in actors[0]["time_label"] or "1234ms" in actors[0]["time_label"]
    usage = actors[0].get("usage") or {}
    assert usage.get("input_tokens") == 100
    assert usage.get("output_tokens") == 20
    assert usage.get("cache_hit_rate") == pytest.approx(0.5)
    assert usage.get("cost_amount") == pytest.approx(0.001)
    assert actors[0].get("usage_label")
    assert "in " in actors[0]["usage_label"]
    assert detail["trial"].get("upstream_url") is None


def test_trial_identity_is_lock_not_opened_yaml(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    evidence = _write_evidence(db, "run_alpha_1", task_id="alpha")
    lock_path = evidence / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["dataset_id"] = "official/tau3-airline"
    lock["dataset_version"] = "0.1.0"
    lock_path.write_text(json.dumps(lock) + "\n", encoding="utf-8")
    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    assert detail["trial"]["dataset_ref"] == "official/tau3-airline@0.1.0"


def test_trial_missing_lock_identity_fails_closed(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    evidence = _write_evidence(db, "run_alpha_1", task_id="alpha")
    lock = json.loads((evidence / "lock.json").read_text(encoding="utf-8"))
    del lock["dataset_version"]
    (evidence / "lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing dataset_id@version"):
        trials.get_trial(db, job_id, "alpha", "run_alpha_1")


def test_trajectory_steps(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_evidence(db, "run_alpha_1", task_id="alpha")

    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    assert traj["step_count"] >= 3
    roles = [s.get("role") for s in traj["steps"] if s.get("role")]
    assert "user" in roles
    assert "assistant" in roles
    assert all(s.get("profile_id") == "main" for s in traj["steps"])


def test_evaluation_observation_steps_not_on_trajectory(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = _write_evidence(db, "run_alpha_1", task_id="alpha")
    gold = "secret-gold-token-eval-judge"
    (root / "evaluation" / "observation.jsonl").write_text(
        json.dumps(
            {
                "type": "turn",
                "role": "assistant",
                "content": "score 1",
                "turn_index": 1,
                "profile_id": "judge",
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "terminal",
                "ok": True,
                "turn_index": 1,
                "profile_id": "judge",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    obs = trials.trial_evaluation_observation(db, job_id, "alpha", "run_alpha_1")
    assert obs["step_count"] >= 2
    assert all(s.get("role") != "user" for s in obs["steps"])
    assert any(s.get("profile_id") == "judge" for s in obs["steps"])
    assert gold not in json.dumps(obs)
    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    assert all(s.get("profile_id") != "judge" for s in traj["steps"])
    (root / "evaluation" / "observation.jsonl").unlink()
    gone = trials.trial_evaluation_observation(db, job_id, "alpha", "run_alpha_1")
    assert gone["steps"] == []


def test_evaluation_checks_and_package_script(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = _write_evidence(db, "run_alpha_1", task_id="alpha")
    (root / "evaluation" / "checks.json").write_text(
        json.dumps(
            {
                "schema": "ageval.evaluation.checks/1",
                "checks": [
                    {
                        "id": "audit",
                        "title": "schema audit",
                        "status": "FAIL",
                        "score": 0.0,
                        "script": "evaluator.py",
                        "stdout": "mismatch",
                    },
                    {"id": "files", "status": "PASS", "score": 1.0},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tree = trials.trial_tree(db, job_id, "alpha", "run_alpha_1", scope="verifier")
    paths = {entry["path"] for entry in tree["entries"]}
    assert "result.json" in paths
    assert "evaluation/checks.json" in paths
    doc = trials.trial_evaluation_checks(db, job_id, "alpha", "run_alpha_1")
    assert [row["id"] for row in doc["checks"]] == ["audit", "files"]
    script = trials.trial_package_file(db, job_id, "alpha", "run_alpha_1", relpath="evaluator.py")
    assert script["path"] == "tasks/alpha/evaluator.py"
    assert "evaluate" in (script.get("content") or "")
    (root / "evaluation" / "checks.json").unlink()
    gone = trials.trial_evaluation_checks(db, job_id, "alpha", "run_alpha_1")
    assert gone["checks"] == []
    with pytest.raises(ConfigError, match="script path rejected"):
        trials.trial_package_file(db, job_id, "alpha", "run_alpha_1", relpath="../ageval.yaml")


def test_trajectory_tool_call_and_observation_steps(tmp_path: Path) -> None:
    """Viewer fail-open parses tool_call / observation rows for the panel."""
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = _write_evidence(db, "run_alpha_1", task_id="alpha")
    inv = root / "agent" / "invocations" / "0001-inv_test"
    traj = [
        {"type": "turn", "role": "user", "content": "read cfg", "turn_index": 1},
        {
            "type": "tool_call",
            "tool_call_id": "call_1",
            "title": "read file",
            "function_name": "read",
            "kind": "read",
            "status": "completed",
            "args": {"path": "/w/a.txt"},
            "elapsed_ms": 1420.5,
            "started_at": "2026-08-14T12:00:00Z",
            "ended_at": "2026-08-14T12:00:01.42Z",
            "turn_index": 1,
            "source": "acp",
        },
        {
            "type": "observation",
            "tool_call_id": "call_1",
            "status": "completed",
            "content": "file body",
            "turn_index": 1,
            "source": "acp",
        },
        {"type": "turn", "role": "assistant", "content": "done", "turn_index": 1},
        {"type": "terminal", "ok": True, "turn_index": 1},
    ]
    (inv.parent.parent.parent / "trajectory.jsonl").write_text(
        "\n".join(json.dumps(x) for x in traj) + "\n", encoding="utf-8"
    )

    payload = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    types = [s.get("type") for s in payload["steps"]]
    assert "tool_call" in types
    assert "observation" in types
    tool = next(s for s in payload["steps"] if s.get("type") == "tool_call")
    assert tool.get("tool_call_id") == "call_1"
    assert tool.get("kind") == "read"
    assert tool.get("function_name") == "read"
    assert tool.get("elapsed_ms") == 1420.5
    assert tool.get("started_at") == "2026-08-14T12:00:00Z"
    # args surfaced as content when no content field
    assert tool.get("content") and "a.txt" in tool["content"]
    obs = next(s for s in payload["steps"] if s.get("type") == "observation")
    assert obs.get("content") == "file body"
    assert obs.get("tool_call_id") == "call_1"


def test_tree_and_file_and_traversal(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_evidence(db, "run_alpha_1", task_id="alpha")

    tree = trials.trial_tree(db, job_id, "alpha", "run_alpha_1", scope="agent")
    paths = {e["path"] for e in tree["entries"]}
    # The agent scope holds the per-invocation record; the trajectory itself is
    # one file at the Attempt root.
    assert any("invocations" in p for p in paths)

    file_payload = trials.trial_file(
        db,
        job_id,
        "alpha",
        "run_alpha_1",
        relpath="lock.json",
    )
    assert file_payload["encoding"] == "utf-8"
    assert "task_id" in (file_payload.get("content") or "")

    with pytest.raises(ConfigError):
        trials.trial_file(
            db,
            job_id,
            "alpha",
            "run_alpha_1",
            relpath="../escape.txt",
        )


def test_trial_file_redacts_env_basename(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    evidence = _write_evidence(db, "run_alpha_1", task_id="alpha")
    (evidence / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    payload = trials.trial_file(
        db,
        job_id,
        "alpha",
        "run_alpha_1",
        relpath=".env",
    )
    assert payload["encoding"] == "redacted"
    assert payload["content"] is None
    assert "sk-secret" not in json.dumps(payload)


def test_list_trials_enriches_evidence(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_evidence(db, "run_alpha_1", task_id="alpha")
    # Extra local run for same task (not in suite summary)
    _write_evidence(db, "run_alpha_extra", task_id="alpha")

    listed = trials.list_task_trials(db, job_id, "alpha")
    run_ids = {t["run_id"] for t in listed["trials"]}
    assert run_ids == {"run_alpha_1"}
    assert "run_alpha_extra" not in run_ids
    alpha1 = next(t for t in listed["trials"] if t["run_id"] == "run_alpha_1")
    assert alpha1["has_evidence"] is True
    assert "trajectory" in alpha1["available_tabs"]


def test_missing_run_raises(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed_suite_run(db)
    with pytest.raises(ConfigError):
        trials.resolve_evidence_root(db, "does_not_exist")


def test_get_trial_opens_previous_without_listing_it(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = "suite_amended"
    suite_dir = db / ".ageval" / "suite-runs" / job_id
    suite_dir.mkdir(parents=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": job_id,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "tasks": [{"task_id": "alpha", "status": "PASS", "score": 1.0, "run_id": "run_new"}],
        "attempts": [
            {
                "task_id": "alpha",
                "attempt_index": 0,
                "status": "PASS",
                "run_id": "run_new",
                "previous": [
                    {
                        "run_id": "run_old",
                        "status": "ERROR",
                        "score": None,
                        "attempt_index": 0,
                    }
                ],
            }
        ],
        "task_refs": [
            {
                "task_id": "alpha",
                "status": "PASS",
                "score": 1.0,
                "run_id": "run_new",
                "previous": [
                    {
                        "run_id": "run_old",
                        "status": "ERROR",
                        "score": None,
                        "attempt_index": 0,
                    }
                ],
            }
        ],
        "metrics": {"n_tasks": 1, "n_pass": 1},
    }
    suite_dir.joinpath("summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    _write_evidence(db, "run_new", task_id="alpha")
    _write_evidence(db, "run_old", task_id="alpha")

    listed = trials.list_task_trials(db, job_id, "alpha")
    assert [t["run_id"] for t in listed["trials"]] == ["run_new"]

    old = trials.get_trial(db, job_id, "alpha", "run_old")
    assert old["trial"]["run_id"] == "run_old"
    assert old["slot_current_run_id"] == "run_new"
    assert old["slot_previous"][0]["run_id"] == "run_old"
    assert "run_old" not in old["sibling_run_ids"]


def test_path_ids_reject_traversal(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    with pytest.raises(ConfigError):
        jobs.get_job(db, "../etc")
    with pytest.raises(ConfigError):
        jobs.get_job_task(db, job_id, "../alpha")
    with pytest.raises(ConfigError):
        trials.resolve_evidence_root(db, "run_alpha_1/../x", task_id="alpha")
    with pytest.raises(ConfigError):
        trials.trial_file(
            db,
            job_id,
            "alpha",
            "run_alpha_1",
            relpath="/etc/passwd",
        )


def test_cross_task_evidence_rejected(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    # Evidence locked to alpha, requested under beta
    _write_evidence(db, "run_alpha_1", task_id="alpha")
    with pytest.raises(ConfigError):
        trials.resolve_evidence_root(db, "run_alpha_1", task_id="beta", require_task_match=True)
    with pytest.raises(ConfigError):
        trials.trial_trajectory(db, job_id, "beta", "run_alpha_1")


def test_missing_evidence_suite_row_ok(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    # suite has run_beta_1 but no on-disk evidence
    detail = trials.get_trial(db, job_id, "beta", "run_beta_1")
    assert detail["trial"]["has_evidence"] is False
    assert detail["trial"]["available_tabs"] == []
    assert detail["trial"]["status"] == "FAIL"


def _write_multi_role_evidence(db: Path, run_id: str, *, task_id: str = "alpha") -> Path:
    """Two profiles, multiple invs; last usage per profile wins; old used-only shape."""
    root = db / ".ageval" / "runs" / run_id
    inv_root = root / "agent" / "invocations"
    inv_root.mkdir(parents=True, exist_ok=True)
    (root / "evaluation").mkdir(parents=True, exist_ok=True)

    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "digest": "sha256:multi",
                "provenance": {
                    "kind": "reimplementation",
                    "upstream": {
                        "name": "example-upstream",
                        "url": "https://github.com/example/upstream",
                        "ref": "main",
                    },
                },
                "profiles": [
                    {
                        "id": "user-grok",
                        "executor": "acp",
                        "model": "entry-default",
                        "extensions": [{"plugin": "acp", "options": {"entry": "grok"}}],
                        "capabilities": {"execution_mode": "acp-stdio"},
                    },
                    {
                        "id": "service-opencode",
                        "executor": "acp",
                        "model": "glm-5.2",
                        "extensions": [{"plugin": "acp", "options": {"entry": "opencode"}}],
                        "capabilities": {"execution_mode": "acp-stdio"},
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(
        json.dumps({"status": "PASS", "score": 1.0, "agent_invocations": 3}) + "\n",
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps({"run_id": run_id, "status": "PASS", "score": 1.0}) + "\n",
        encoding="utf-8",
    )

    invs = [
        ("0001-inv_a", "user-grok", "entry-default", 1000.0, None),
        (
            "0002-inv_b",
            "service-opencode",
            "glm-5.2",
            2000.0,
            # legacy UsageUpdate-only shape — must NOT become tokens
            {"used": 9999, "size": 100000, "cost": {"amount": 0.05, "currency": "USD"}},
        ),
        (
            "0003-inv_c",
            "service-opencode",
            "glm-5.2",
            3000.0,
            {
                "input_tokens": 11433,
                "output_tokens": 140,
                "cached_read_tokens": 8576,
                "cost": {"amount": 0.012, "currency": "USD"},
                "context": {"used": 15925, "size": 1000000},
            },
        ),
    ]
    for dirname, profile_id, model, latency_ms, usage in invs:
        inv = inv_root / dirname
        inv.mkdir(parents=True, exist_ok=True)
        (inv / "metadata.json").write_text(
            json.dumps(
                {
                    "invocation_id": dirname.split("-", 1)[-1],
                    "session_id": f"sess_{profile_id}",
                    "profile_id": profile_id,
                    "executor_kind": "acp",
                    "model": model,
                    "status": "completed",
                    "latency_ms": latency_ms,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        terminal: dict = {
            "type": "terminal",
            "ok": True,
            "stop_reason": "end_turn",
            "source": "ageval",
            "turn_index": 1,
            "session_id": f"sess_{profile_id}",
        }
        if usage is not None:
            terminal["usage"] = usage
        session = f"sess_{profile_id}"
        lines = [
            {
                "type": "turn",
                "role": "user",
                "content": "hi",
                "turn_index": 1,
                "session_id": session,
            },
            {
                "type": "turn",
                "role": "assistant",
                "content": "ok",
                "turn_index": 1,
                "session_id": session,
            },
            terminal,
        ]
        attempt_trajectory = inv.parent.parent.parent / "trajectory.jsonl"
        with attempt_trajectory.open("a", encoding="utf-8") as handle:
            for row in lines:
                handle.write(json.dumps(row) + "\n")
    return root


def test_multi_role_actors_time_usage_and_provenance(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    _write_multi_role_evidence(db, "run_alpha_1", task_id="alpha")

    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    trial = detail["trial"]
    assert trial.get("upstream_url") == "https://github.com/example/upstream"
    assert trial.get("upstream_name") == "example-upstream"
    actors = trial.get("actors") or []
    assert len(actors) == 2
    by_pid = {a["profile_id"]: a for a in actors}

    user = by_pid["user-grok"]
    assert user["role"] == "user-grok"
    assert user["agent"] == "grok"
    assert user["invokes"] == 1
    assert user["latency_ms_sum"] == pytest.approx(1000.0)
    # No usage on user inv → fail-open
    assert user.get("usage") is None or user.get("usage_label") is None

    service = by_pid["service-opencode"]
    assert service["role"] == "service-opencode"
    assert service["agent"] == "opencode"
    assert service["invokes"] == 2
    assert service["latency_ms_sum"] == pytest.approx(5000.0)
    # Last invoke wins — normalized tokens, not legacy used=9999
    usage = service.get("usage") or {}
    assert usage.get("input_tokens") == 11433
    assert usage.get("output_tokens") == 140
    # inclusion heuristic: cache ≤ input → hit = cache/input
    assert usage.get("cache_relation") == "inclusion"
    assert usage.get("cache_hit_rate") == pytest.approx(8576 / 11433)
    assert usage.get("cost_amount") == pytest.approx(0.012)
    # disjoint heuristic: cache > input → hit = cache/(input+cache)
    disjoint = (
        trials._usage_summary_for_actor(  # noqa: SLF001
            {"input_tokens": 100, "cached_read_tokens": 500}
        )
        or {}
    )
    assert disjoint.get("cache_relation") == "disjoint"
    assert disjoint.get("cache_hit_rate") == pytest.approx(500 / 600)
    assert disjoint.get("display_input_tokens") == 600
    assert "cache 83%" in (disjoint.get("label") or "")
    assert usage.get("context_used") == 15925
    label = service.get("usage_label") or ""
    assert "in " in label and "out " in label
    assert "cache " in label
    assert "$" in label
    # Never surface bare context used as token total
    assert "9999" not in label

    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    profiles = {s.get("profile_id") for s in traj["steps"]}
    assert "user-grok" in profiles
    assert "service-opencode" in profiles


def test_legacy_usage_cost_only_no_used_as_tokens(tmp_path: Path) -> None:
    """Old evidence with only {used,size,cost}: show cost, never used as tokens."""
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = db / ".ageval" / "runs" / "run_alpha_1"
    inv = root / "agent" / "invocations" / "0001-inv_x"
    inv.mkdir(parents=True, exist_ok=True)
    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "profiles": [
                    {
                        "id": "main-pi",
                        "executor": "acp",
                        "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                        "capabilities": {"execution_mode": "acp-stdio"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(json.dumps({"status": "PASS", "score": 1.0}) + "\n")
    (root / "summary.json").write_text(json.dumps({"status": "PASS"}) + "\n")
    (inv / "metadata.json").write_text(
        json.dumps(
            {
                "profile_id": "main-pi",
                "executor_kind": "acp",
                "model": "m",
                "latency_ms": 500,
            }
        )
        + "\n"
    )
    terminal = {
        "type": "terminal",
        "ok": True,
        "usage": {
            "used": 16899,
            "size": 1000000,
            "cost": {"amount": 0.0, "currency": "USD"},
            "sessionUpdate": "usage_update",
        },
    }
    (inv.parent.parent.parent / "trajectory.jsonl").write_text(
        json.dumps(terminal) + "\n", encoding="utf-8"
    )

    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    actor = (detail["trial"].get("actors") or [])[0]
    usage = actor.get("usage") or {}
    assert usage.get("input_tokens") is None
    assert usage.get("output_tokens") is None
    assert usage.get("context_used") == 16899
    assert usage.get("cost_amount") == 0.0
    label = actor.get("usage_label") or ""
    # Cost-only label; no token line
    assert "in " not in label
    assert "$" in label or "0" in label


def test_first_class_usage_and_jsonl_labels_without_invocation_meta(tmp_path: Path) -> None:
    """Layer C first-class usage/elapsed label actors without metadata.json."""
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = db / ".ageval" / "runs" / "run_alpha_1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "profiles": [
                    {
                        "id": "solver",
                        "executor": "openai-http",
                        "model": "gpt-4.1-mini",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(json.dumps({"status": "PASS", "score": 1.0}) + "\n")
    (root / "summary.json").write_text(json.dumps({"status": "PASS"}) + "\n")
    (root / "trajectory.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "turn",
                        "role": "user",
                        "content": "hi",
                        "turn_index": 1,
                        "metadata": {"profile_id": "solver"},
                    }
                ),
                json.dumps(
                    {
                        "type": "terminal",
                        "ok": True,
                        "elapsed_ms": 142.5,
                        "usage": {
                            "prompt_tokens": 11,
                            "completion_tokens": 4,
                            "cached_tokens": 2,
                            "cost_usd": 0.0012,
                        },
                        "extra": {"reasoning_tokens": 3, "foo": True},
                        "metadata": {
                            "profile_id": "solver",
                            "executor_kind": "openai-http",
                            "latency_ms": 142.5,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    actor = (detail["trial"].get("actors") or [])[0]
    assert actor["profile_id"] == "solver"
    assert actor["latency_ms_sum"] == pytest.approx(142.5)
    usage = actor.get("usage") or {}
    assert usage.get("input_tokens") == 11
    assert usage.get("output_tokens") == 4
    assert usage.get("cached_read_tokens") == 2
    assert usage.get("cost_amount") == pytest.approx(0.0012)
    assert actor.get("usage_label")
    assert "$" in (actor.get("usage_label") or "")
    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    terminal = next(s for s in traj["steps"] if s.get("type") == "terminal")
    assert terminal.get("profile_id") == "solver"
    assert terminal.get("elapsed_ms") == pytest.approx(142.5)
    assert "usage=" not in (terminal.get("content") or "")
    assert terminal.get("extra") == {"reasoning_tokens": 3, "foo": True}


def test_actor_model_from_job_overlay_when_lock_has_no_profiles(
    tmp_path: Path,
) -> None:
    """Sealed lock.json is overlay-only; default runs drop invocation metadata."""
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = db / ".ageval" / "runs" / "run_alpha_1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "job_overlay": {
                    "environment": "docker",
                    "agent_profiles": {
                        "solver": {
                            "executor": "openai-http",
                            "label": "openai-http · qwen",
                            "model": "dashscope/deepseek-v4-flash",
                        }
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(json.dumps({"status": "PASS", "score": 1.0}) + "\n")
    (root / "summary.json").write_text(json.dumps({"status": "PASS"}) + "\n")
    (root / "trajectory.jsonl").write_text(
        json.dumps(
            {
                "type": "terminal",
                "ok": True,
                "elapsed_ms": 10,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "metadata": {"profile_id": "solver"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    actor = (detail["trial"].get("actors") or [])[0]
    assert actor["agent"] == "openai-http · qwen"
    assert actor["model"] == "dashscope/deepseek-v4-flash"
    assert actor.get("executor_kind") == "openai-http"
    assert detail["trial"].get("extra") is None


def test_old_usage_extra_alias_and_summary_extra(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = db / ".ageval" / "runs" / "run_alpha_1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "profiles": [{"id": "solver", "executor": "openai-http"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(json.dumps({"status": "PASS", "score": 1.0}) + "\n")
    (root / "summary.json").write_text(
        json.dumps({"status": "PASS", "extra": {"probe": {"foo": True}}}) + "\n"
    )
    (root / "trajectory.jsonl").write_text(
        json.dumps(
            {
                "type": "terminal",
                "ok": True,
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "extra": {"reasoning_tokens": 9},
                },
                "metadata": {"profile_id": "solver"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    detail = trials.get_trial(db, job_id, "alpha", "run_alpha_1")
    assert detail["trial"]["extra"] == {"probe": {"foo": True}}
    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    terminal = next(s for s in traj["steps"] if s.get("type") == "terminal")
    assert terminal.get("extra") == {"reasoning_tokens": 9}
    assert "extra" in (terminal.get("usage") or {})


def test_trajectory_backfills_profile_id_by_turn_without_regrouping(
    tmp_path: Path,
) -> None:
    """Slim archives only stamp profile_id on terminal.metadata; keep file order."""
    db = _clean_db(tmp_path)
    job_id = _seed_suite_run(db)
    root = db / ".ageval" / "runs" / "run_alpha_1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "lock.json").write_text(
        json.dumps(
            {
                "task_id": "alpha",
                "dataset_id": "test/suite-min",
                "dataset_version": "0.1.0",
                "profiles": [
                    {"id": "user", "executor": "openai-http"},
                    {"id": "service", "executor": "openai-http"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "result.json").write_text(json.dumps({"status": "PASS", "score": 1.0}) + "\n")
    rows = [
        {"type": "turn", "role": "user", "content": "u-prompt", "turn_index": 1},
        {"type": "turn", "role": "assistant", "content": "need help", "turn_index": 1},
        {
            "type": "terminal",
            "ok": True,
            "turn_index": 1,
            "metadata": {"profile_id": "user", "executor_kind": "openai-http"},
        },
        {"type": "turn", "role": "user", "content": "s-prompt", "turn_index": 2},
        {"type": "tool_call", "function_name": "get_user", "turn_index": 2},
        {"type": "observation", "content": "{}", "turn_index": 2},
        {"type": "turn", "role": "assistant", "content": "I can help", "turn_index": 2},
        {
            "type": "terminal",
            "ok": True,
            "turn_index": 2,
            "metadata": {"profile_id": "service", "executor_kind": "openai-http"},
        },
    ]
    (root / "trajectory.jsonl").write_text(
        "\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8"
    )

    traj = trials.trial_trajectory(db, job_id, "alpha", "run_alpha_1")
    steps = traj["steps"]
    assert [s.get("type") for s in steps] == [
        "turn",
        "turn",
        "terminal",
        "turn",
        "tool_call",
        "observation",
        "turn",
        "terminal",
    ]
    assert [s.get("profile_id") for s in steps] == [
        "user",
        "user",
        "user",
        "service",
        "service",
        "service",
        "service",
        "service",
    ]
