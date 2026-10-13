"""Config Core: merge order, digest stability, immutability, fail-closed errors."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.helpers.lock import CONFIG_MIN, job_document, lock_standalone, lock_task

from ageval.config.digest import digest_payload
from ageval.config.errors import ConfigError
from ageval.config.model import thaw
from ageval.config.overrides import parse_set_override

SOLVER = {
    "executor": "acp",
    "model": {"id": "entry-default"},
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
}
TASK_YAML = (CONFIG_MIN / "tasks" / "minimal" / "task.yaml").read_text(encoding="utf-8")


def _standalone(root: Path, *, task_yaml: str = TASK_YAML, files: tuple[str, ...] = ()) -> Path:
    """A task directory written by the test, with the files it should ship."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.yaml").write_text(task_yaml, encoding="utf-8")
    for name in files:
        (root / name).write_text("#\n", encoding="utf-8")
    return root


def _lock_standalone(root: Path, **kwargs: Any) -> Any:
    return lock_standalone(root, "minimal", job=job_document({"solver": dict(SOLVER)}), **kwargs)


def _expect(root: Path, code: str, **kwargs: Any) -> None:
    with pytest.raises(ConfigError) as caught:
        _lock_standalone(root, **kwargs)
    assert caught.value.error_code == code


# --- digest ----------------------------------------------------------------


def test_lock_is_deterministic() -> None:
    first = lock_task(CONFIG_MIN, "minimal")
    second = lock_task(CONFIG_MIN, "minimal")
    assert first.digest == second.digest
    assert first.canonical_payload() == second.canonical_payload()
    assert first.digest.startswith("sha256:")
    assert len(first.digest) == len("sha256:") + 64
    assert thaw(first.agent_profiles)[0]["executor"] == "acp"
    assert first.job_overlay is not None


def test_override_changes_the_digest() -> None:
    base = lock_task(CONFIG_MIN, "minimal")
    overridden = lock_task(CONFIG_MIN, "minimal", overrides={"/parameters/seed": 7})
    assert overridden.digest != base.digest
    assert thaw(overridden.parameters)["seed"] == 7
    assert "cli-override" in [entry.source for entry in overridden.resolution.entries]


def test_digest_ignores_where_the_checkout_lives(tmp_path: Path) -> None:
    digests = set()
    for name in ("a", "b"):
        root = _standalone(tmp_path / name, files=("run.py", "evaluator.py"))
        digests.add(_lock_standalone(root).digest)
    assert len(digests) == 1


def test_digest_payload_is_key_order_stable() -> None:
    assert digest_payload({"z": 1, "a": [2, 1]}) == digest_payload({"a": [2, 1], "z": 1})


def test_payload_holds_no_secret_and_no_host_path() -> None:
    locked = lock_task(CONFIG_MIN, "minimal")
    blob = str(locked.canonical_payload()) + locked.digest
    assert "sk-" not in blob
    assert str(CONFIG_MIN.resolve()) not in blob


def test_lock_binds_executor_per_profile_mixed_mechanisms(tmp_path: Path) -> None:
    yaml = TASK_YAML.replace(
        "agent_profiles:\n  - id: solver",
        "agent_profiles:\n  - id: solver\n  - id: judge",
    )
    root = _standalone(tmp_path / "pkg", task_yaml=yaml, files=("run.py", "evaluator.py"))
    locked = lock_standalone(
        root,
        "minimal",
        job=job_document(
            {
                "solver": {**SOLVER, "api_key": "${SOLVER_API_KEY}"},
                "judge": {
                    "executor": "openai-http",
                    "model": {"id": "gpt-4.1-mini"},
                    "api_key": "${JUDGE_API_KEY}",
                    "base_url": "http://127.0.0.1:9/v1",
                    "extensions": [{"plugin": "openai-http"}, {"plugin": "local"}],
                },
            }
        ),
    )
    bindings = thaw(locked.extension_bindings)
    assert bindings["solver"]["slots"]["executor"]["plugin"] == "acp"
    assert bindings["judge"]["slots"]["executor"]["plugin"] == "openai-http"
    assert bindings["solver"]["slots"]["environment"]["plugin"] == "local"
    assert bindings["judge"]["slots"]["environment"]["plugin"] == "local"
    overlay = thaw(locked.job_overlay)["agent_profiles"]
    assert overlay["solver"]["api_key"] == "SOLVER_API_KEY"
    assert overlay["judge"]["api_key"] == "JUDGE_API_KEY"
    blob = str(locked.canonical_payload())
    assert "sk-" not in blob


def test_lock_does_not_require_undeclared_judge_profile() -> None:
    locked = lock_task(CONFIG_MIN, "minimal")
    ids = [str(row.get("id")) for row in thaw(locked.agent_profiles)]
    assert ids == ["solver"]
    assert "judge" not in (thaw(locked.extension_bindings) or {})


# --- immutability ----------------------------------------------------------


def test_locked_config_cannot_be_mutated() -> None:
    locked = lock_task(CONFIG_MIN, "minimal")
    payload_before = copy.deepcopy(locked.canonical_payload())
    digest_before = locked.digest

    thawed = thaw(locked.parameters)
    thawed["seed"] = 999
    assert locked.digest == digest_before
    assert locked.canonical_payload() == payload_before

    with pytest.raises(TypeError):
        locked.parameters["seed"] = 123  # type: ignore[index]


# --- fail closed -----------------------------------------------------------


def test_active_profile_must_name_a_declared_role() -> None:
    with pytest.raises(ConfigError) as caught:
        lock_task(CONFIG_MIN, "unknown-profile")
    assert caught.value.error_code == "unknown_profile"


def test_unknown_task_format(tmp_path: Path) -> None:
    root = _standalone(
        tmp_path / "pkg",
        task_yaml=TASK_YAML.replace("format: ageval.task/1", "format: ageval.task/999"),
        files=("run.py", "evaluator.py"),
    )
    _expect(root, "invalid_format")


def test_retired_provider_key_is_rejected(tmp_path: Path) -> None:
    root = _standalone(
        tmp_path / "pkg",
        task_yaml=TASK_YAML + "provider:\n  kind: local\n",
        files=("run.py", "evaluator.py"),
    )
    _expect(root, "invalid_schema")


def test_task_without_a_run_module(tmp_path: Path) -> None:
    root = _standalone(tmp_path / "pkg", files=("evaluator.py",))
    _expect(root, "missing_reference")


def test_limits_are_not_overridable() -> None:
    with pytest.raises(ConfigError) as caught:
        lock_task(CONFIG_MIN, "minimal", overrides={"/limits/wall_time_seconds": 1})
    assert caught.value.error_code == "invalid_override"


def test_task_id_must_match_the_selection(tmp_path: Path) -> None:
    root = _standalone(tmp_path / "pkg", files=("run.py", "evaluator.py"))
    with pytest.raises(ConfigError) as caught:
        lock_standalone(root, "wrong-id", job=job_document({"solver": dict(SOLVER)}))
    assert caught.value.error_code == "unknown_task"


def test_unknown_top_level_path(tmp_path: Path) -> None:
    root = _standalone(tmp_path / "pkg", files=("run.py", "evaluator.py"))
    (root / "helpers").mkdir()
    _expect(root, "unknown_package_path")


def test_artifact_path_may_not_escape_the_task(tmp_path: Path) -> None:
    root = _standalone(
        tmp_path / "pkg",
        task_yaml=TASK_YAML.replace("artifacts/result.json", "../escape.json"),
        files=("run.py", "evaluator.py"),
    )
    _expect(root, "path_outside_package")


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    root = _standalone(
        tmp_path / "pkg",
        task_yaml="format: ageval.task/1\nformat: ageval.task/1\ntask_id: minimal\n",
        files=("run.py", "evaluator.py"),
    )
    _expect(root, "invalid_schema")


# --- boundaries ------------------------------------------------------------


def test_locking_never_imports_the_task_module() -> None:
    for key in [k for k in sys.modules if "ageval_task_" in k]:
        del sys.modules[key]
    lock_task(CONFIG_MIN, "minimal")
    assert not any("ageval_task_" in key for key in sys.modules)


def test_set_override_pointer_allowlist() -> None:
    with pytest.raises(ConfigError) as caught:
        parse_set_override('/harness/entrypoint="x:y"')
    assert caught.value.error_code == "invalid_override"

    pointer, value = parse_set_override('/agent_profiles/solver/model/id="gpt-test"')
    assert (pointer, value) == ("/agent_profiles/solver/model/id", "gpt-test")
    whole, body = parse_set_override('/agent_profiles/solver/model={"id":"gpt-test"}')
    assert whole == "/agent_profiles/solver/model"
    assert body == {"id": "gpt-test"}
