"""Harbor layout intake: discovery, task.toml mapping, and the unchanged default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers.lock import job_document, lock_standalone
from typer.testing import CliRunner

from ageval.application.composition import build_lock_command
from ageval.cli.main import app
from ageval.config.errors import ConfigError
from ageval.config.model import thaw

SOLVER = {
    "executor": "acp",
    "model": {"id": "entry-default"},
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
}
PROFILES = """format: ageval.profiles/1
environment: local
agent_profiles:
  solver:
    executor: acp
    model: {id: entry-default}
    options:
      entry: codex
    extensions:
      - plugin: acp
      - plugin: local
"""


def _task(root: Path, toml: str, *, name: str = "demo-task") -> Path:
    task = root / name
    task.mkdir(parents=True)
    (task / "task.toml").write_text(toml, encoding="utf-8")
    (task / "instruction.md").write_text("say hello\n", encoding="utf-8")
    tests = task / "tests"
    tests.mkdir()
    (tests / "test.sh").write_text("echo 1 > /logs/verifier/reward.txt\n", encoding="utf-8")
    env = task / "environment"
    env.mkdir()
    (env / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    return task


def _lock(task: Path, *, environment: str = "local"):
    return lock_standalone(
        task,
        task.name,
        job=job_document({"solver": dict(SOLVER)}, environment=environment),
        layout="harbor",
    )


def test_single_task_locks_without_ageval_scripts(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        """
[verifier]
timeout_sec = 900

[agent]
timeout_sec = 120

[environment]
build_timeout_sec = 30
cpus = 2
memory_mb = 512
allow_internet = false
""",
    )
    locked = _lock(task)
    assert locked.task_id == "demo-task"
    limits = thaw(locked.limits)
    assert limits["wall_time_seconds"] == 120
    assert limits["evaluate_seconds"] == 900
    assert limits["environment_seconds"] == 30
    params = thaw(locked.parameters)
    assert params["harbor_network"] == "no-network"
    assert params["cpus"] == 2
    assert params["memory_mb"] == 512
    refs = thaw(locked.resolved_references)
    assert refs["run_entrypoint"] == "ageval.harbor.run:run"
    assert refs["evaluation_entrypoint"] == "ageval.harbor.evaluate:evaluate"
    assert refs["environment_build_context"] == "environment"
    assert refs["environment_dockerfile"] == "environment/Dockerfile"
    assert not (task / "run.py").exists()
    assert not (task / "evaluator.py").exists()


def test_omitted_agent_timeout_does_not_copy_verifier(tmp_path: Path) -> None:
    task = _task(tmp_path, "[verifier]\ntimeout_sec = 900\n")
    limits = thaw(_lock(task).limits)
    assert limits["wall_time_seconds"] == 300
    assert limits["evaluate_seconds"] == 900


def test_task_name_must_match_directory(tmp_path: Path) -> None:
    task = _task(tmp_path, '[task]\nname = "other"\n')
    with pytest.raises(ConfigError) as exc:
        _lock(task)
    assert exc.value.error_code == "unknown_task"


def test_allowlist_network_fails_closed(tmp_path: Path) -> None:
    task = _task(
        tmp_path, '[environment]\nnetwork_mode = "allowlist"\nallowed_hosts = ["example.com"]\n'
    )
    with pytest.raises(ConfigError) as exc:
        _lock(task)
    assert exc.value.error_code == "harbor_network_unsupported"


def test_phase_network_override_fails_closed(tmp_path: Path) -> None:
    task = _task(tmp_path, '[agent]\nnetwork_mode = "public"\n')
    with pytest.raises(ConfigError) as exc:
        _lock(task)
    assert exc.value.error_code == "harbor_network_unsupported"


def test_username_is_rejected(tmp_path: Path) -> None:
    task = _task(tmp_path, '[environment]\nuser = "agent"\n')
    with pytest.raises(ConfigError) as exc:
        _lock(task)
    assert exc.value.error_code == "harbor_unsupported"


def test_uid_is_kept(tmp_path: Path) -> None:
    task = _task(tmp_path, "[environment]\nuser = 1000\n")
    assert thaw(_lock(task).parameters)["harbor_user"] == "1000"


def test_registry_json_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "registry.json").write_text("{}", encoding="utf-8")
    _task(tmp_path, "")
    with pytest.raises(ConfigError) as exc:
        build_lock_command().lock(tmp_path, "", layout="harbor")
    assert exc.value.error_code == "harbor_registry_rejected"


def test_converted_ageval_member_is_rejected(tmp_path: Path) -> None:
    task = tmp_path / "ported"
    task.mkdir()
    (task / "task.yaml").write_text("format: ageval.task/1\ntask_id: ported\n", encoding="utf-8")
    (task / "data").mkdir()
    (task / "evaluation").mkdir()
    (task / "task.toml").write_text("", encoding="utf-8")
    (task / "instruction.md").write_text("x\n", encoding="utf-8")
    (task / "tests").mkdir()
    (task / "tests" / "test.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        build_lock_command().lock(task, "", layout="harbor")
    assert exc.value.error_code == "harbor_layout_mix"


def test_single_task_lock_uses_the_directory_name(tmp_path: Path) -> None:
    task = _task(tmp_path, "")
    (task / "profiles.yaml").write_text(PROFILES, encoding="utf-8")
    locked = build_lock_command().lock(task, "demo-task", layout="harbor")
    assert locked.lock.task_id == "demo-task"
    with pytest.raises(ConfigError) as exc:
        build_lock_command().lock(task, "other", layout="harbor")
    assert exc.value.error_code == "invalid_override"


def test_task_set_lists_and_filters(tmp_path: Path) -> None:
    suite = tmp_path / "terminal-bench"
    _task(suite, "", name="alpha")
    _task(suite, "", name="beta")
    (suite / "profiles.yaml").write_text(PROFILES, encoding="utf-8")
    listed = build_lock_command().tasks(suite, layout="harbor")
    assert listed == ["alpha", "beta"]
    locked = build_lock_command().lock(suite, "beta", layout="harbor")
    assert locked.lock.task_id == "beta"
    assert locked.manifest.dataset_id == "terminal-bench"
    with pytest.raises(ConfigError) as exc:
        build_lock_command().lock(suite, "", layout="harbor")
    assert exc.value.error_code == "invalid_override"


def test_collect_commands_precede_artifact_paths(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        """
[[verifier.collect]]
command = "pg_dump > /tmp/db.sql"
service = "db"

[[artifacts]]
source = "/tmp/db.sql"
service = "db"
exclude = ["*.log"]
""",
    )
    rows = thaw(_lock(task).resolved_references)["evaluation_collect"]
    assert rows[0]["command"] == "pg_dump > /tmp/db.sql"
    assert rows[0]["service"] == "db"
    assert rows[1]["path"] == "/tmp/db.sql"
    assert rows[1]["service"] == "db"
    assert rows[1]["exclude"] == ["*.log"]


def test_separate_tests_dockerfile_is_preinstalled(tmp_path: Path) -> None:
    task = _task(tmp_path, "")
    (task / "tests" / "Dockerfile").write_text(
        "FROM scratch\nCOPY test.sh /tests/test.sh\n", encoding="utf-8"
    )
    locked = _lock(task, environment="docker")
    refs = thaw(locked.resolved_references)
    envs = refs["evaluation_environments"]["verifier"]
    assert envs["dockerfile"] == "tests/Dockerfile"
    assert envs["context"] == "tests"
    assert "package_uploads" not in refs
    assert thaw(locked.parameters)["harbor_verifier_mode"] == "separate"


def test_explicit_separate_without_verifier_image_is_not_shared(tmp_path: Path) -> None:
    task = _task(tmp_path, '[verifier]\nenvironment_mode = "separate"\n')
    locked = _lock(task, environment="docker")
    refs = thaw(locked.resolved_references)
    assert thaw(locked.parameters)["harbor_verifier_mode"] == "separate"
    assert refs["evaluation_environments"]["verifier"]["context"] == "environment"
    assert refs["package_uploads"] == [{"source": "tests", "dest": "/tests"}]


def test_docker_compose_yaml_is_the_up_file(tmp_path: Path) -> None:
    task = _task(tmp_path, "")
    (task / "environment" / "Dockerfile").unlink()
    (task / "environment" / "docker-compose.yaml").write_text(
        "services:\n  main:\n    image: demo\n  db:\n    image: demo\n",
        encoding="utf-8",
    )
    refs = thaw(_lock(task, environment="docker").resolved_references)
    assert refs["environment_compose"] == "environment/docker-compose.yaml"
    assert "environment_dockerfile" not in refs


def test_default_layout_still_requires_task_yaml(tmp_path: Path) -> None:
    task = _task(tmp_path, "")
    with pytest.raises(ConfigError) as exc:
        lock_standalone(task, task.name, job=job_document({"solver": dict(SOLVER)}))
    assert exc.value.error_code == "unknown_package_path"


def test_cli_tasks_and_lock(tmp_path: Path) -> None:
    task = _task(tmp_path, "[agent]\ntimeout_sec = 45\n")
    (task / "profiles.yaml").write_text(PROFILES, encoding="utf-8")
    runner = CliRunner()
    listed = runner.invoke(app, ["tasks", str(task), "--layout", "harbor"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.stdout)
    assert payload["tasks"] == ["demo-task"]
    assert payload["dataset_id"] == "demo-task"
    locked = runner.invoke(app, ["lock", str(task), "--layout", "harbor"])
    assert locked.exit_code == 0, locked.output
    body = json.loads(locked.stdout)
    assert body["task_id"] == "demo-task"
    assert body["dataset_version"] == "1"
    rejected = runner.invoke(app, ["lock", str(task), "--layout", "harbor", "--task", "demo-task"])
    assert rejected.exit_code == 2
    assert "invalid_override" in rejected.output
