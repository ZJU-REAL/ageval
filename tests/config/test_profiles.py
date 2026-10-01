"""The job document: who binds a role slot, and what may never leak into it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ageval.config.capabilities import DeclarationCapabilityCatalog
from ageval.config.errors import ConfigError
from ageval.config.load_and_lock import ConfigCore
from ageval.config.model import thaw
from ageval.config.package_fs import LocalPackageReader
from ageval.config.profiles import (
    apply_profile_override,
    assert_slots_have_no_inline_binding,
    display_agent_name,
    display_labels_from_overlay,
    job_overlay_to_profiles_document,
    join_display_names,
    load_job_document,
    merge_job_onto_slots,
    parse_job_mapping,
    project_job_overlay,
    write_profiles_yaml,
)

ACP_SOLVER = {
    "executor": "acp",
    "model": "m",
    "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
}


def _job(profiles: dict[str, Any], *, environment: str = "local") -> Any:
    return parse_job_mapping(
        {"format": "ageval.profiles/1", "environment": environment, "agent_profiles": profiles}
    )


def _task(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.yaml").write_text(body, encoding="utf-8")
    (root / "run.py").write_text("async def run(ctx): pass\n", encoding="utf-8")
    (root / "evaluator.py").write_text("def evaluate(i): return {}\n", encoding="utf-8")
    return root


def _lock(task_root: Path, job: Any, **kwargs: Any) -> Any:
    core = ConfigCore(package_reader=LocalPackageReader())
    return core.load_and_lock(
        task_root,
        "t",
        dataset_id="test/db",
        dataset_version="0.1.0",
        job=job,
        capabilities=DeclarationCapabilityCatalog(),
        **kwargs,
    )


# --- role slots vs job binding --------------------------------------------


def test_task_yaml_may_not_bind_a_role_slot(tmp_path: Path) -> None:
    root = _task(
        tmp_path / "t",
        "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n    executor: acp\n",
    )
    with pytest.raises(ConfigError) as caught:
        _lock(root, _job({"solver": dict(ACP_SOLVER)}))
    assert "role slots only" in str(caught.value)


def test_assert_slots_helper_rejects_binding_fields() -> None:
    with pytest.raises(ConfigError):
        assert_slots_have_no_inline_binding([{"id": "x", "executor": "acp"}])
    assert_slots_have_no_inline_binding([{"id": "x"}])


def test_declared_role_without_a_profile_fails_closed(tmp_path: Path) -> None:
    root = _task(
        tmp_path / "t",
        "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n",
    )
    with pytest.raises(ConfigError) as caught:
        _lock(root, _job({"critic": dict(ACP_SOLVER)}))
    assert caught.value.error_code == "missing_binding"


def test_task_without_role_slots_needs_no_profile(tmp_path: Path) -> None:
    root = _task(tmp_path / "t", "format: ageval.task/1\ntask_id: t\n")
    lock = _lock(root, _job({}))
    assert lock.agent_profiles == ()


def test_profile_binds_the_slot_and_cli_override_wins(tmp_path: Path) -> None:
    root = _task(
        tmp_path / "t",
        "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n",
    )
    lock = _lock(
        root,
        _job({"solver": dict(ACP_SOLVER)}),
        overrides={"/agent_profiles/solver/model": "other-model"},
    )
    (row,) = thaw(lock.agent_profiles)
    assert row["id"] == "solver"
    assert row["executor"] == "acp"
    assert row["model"] == "other-model"


def test_merge_helper_binds_every_declared_slot() -> None:
    rows = merge_job_onto_slots([{"id": "solver"}], _job({"solver": dict(ACP_SOLVER)}))
    assert rows[0]["executor"] == "acp"
    assert rows[0]["id"] == "solver"


def test_override_on_an_unnamed_role_inherits_the_rest() -> None:
    job = _job({"*": dict(ACP_SOLVER)})
    apply_profile_override(job, "/agent_profiles/solver/model", "opus")
    (row,) = merge_job_onto_slots([{"id": "solver"}], job)
    assert row["model"] == "opus"
    assert row["extensions"][0]["options"]["entry"] == "pi"


# --- document parsing ------------------------------------------------------


def test_document_round_trips_through_yaml(tmp_path: Path) -> None:
    path = tmp_path / "profiles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "format": "ageval.profiles/1",
                "environment": "local",
                "agent_profiles": {"solver": dict(ACP_SOLVER)},
            }
        ),
        encoding="utf-8",
    )
    job = load_job_document(path)
    assert job.environment == "local"
    assert job.profiles["solver"]["model"] == "m"


def test_unknown_profile_key_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        _job({"solver": {**ACP_SOLVER, "not_a_field": 1}})
    assert "unknown profile keys" in str(caught.value)


def test_upstream_stall_seconds_rejects_a_bad_budget() -> None:
    for bad in (-1, 1.5, True, "60"):
        with pytest.raises(ConfigError):
            _job({"solver": {**ACP_SOLVER, "options": {"upstream_stall_seconds": bad}}})
    with pytest.raises(ConfigError):
        _job(
            {
                "solver": {
                    **ACP_SOLVER,
                    "extensions": [
                        {"plugin": "acp", "options": {"entry": "pi", "upstream_stall_seconds": -3}}
                    ],
                }
            }
        )


def test_upstream_stall_seconds_accepts_zero_and_an_override() -> None:
    job = _job({"solver": {**ACP_SOLVER, "options": {"upstream_stall_seconds": 0}}})
    assert job.profiles["solver"]["options"]["upstream_stall_seconds"] == 0
    apply_profile_override(job, "/agent_profiles/solver/options/upstream_stall_seconds", 120)
    assert job.profiles["solver"]["options"]["upstream_stall_seconds"] == 120
    with pytest.raises(ConfigError):
        apply_profile_override(job, "/agent_profiles/solver/options/upstream_stall_seconds", False)


def test_unknown_top_level_key_fails_closed() -> None:
    with pytest.raises(ConfigError):
        parse_job_mapping(
            {"format": "ageval.profiles/1", "agent_profiles": {}, "not_a_job_key": {"x": {}}}
        )


# --- the secret-free projection --------------------------------------------


def test_overlay_carries_the_locator_name_not_a_value() -> None:
    overlay = project_job_overlay(
        {"solver": {**ACP_SOLVER, "api_key": "MY_KEY_LOCATOR"}},
        environment="local",
    )
    assert overlay["agent_profiles"]["solver"]["api_key"] == "MY_KEY_LOCATOR"
    assert "sk-" not in str(overlay)


def test_overlay_round_trips_into_a_profiles_document(tmp_path: Path) -> None:
    overlay = project_job_overlay(
        {"solver": {**ACP_SOLVER, "api_key": "LOC", "base_url": "LITELLM_BASE"}},
        environment="local",
    )
    path = tmp_path / "profiles.from-suite.yaml"
    write_profiles_yaml(path, job_overlay_to_profiles_document(overlay))
    loaded = load_job_document(path)
    assert loaded.environment == "local"
    assert loaded.profiles["solver"]["extensions"][0]["options"]["entry"] == "pi"
    assert loaded.profiles["solver"]["api_key"] == "${LOC}"
    assert loaded.profiles["solver"]["base_url"] == "${LITELLM_BASE}"


def test_overlay_keeps_plugin_options_but_drops_registry_truth() -> None:
    overlay = project_job_overlay(
        {
            "solver": {
                "executor": "acp",
                "model": "m",
                "extensions": [
                    {
                        "plugin": "acp",
                        "options": {
                            "entry": "pi",
                            "reasoning_effort": "high",
                            "command": ["should-not-ride-the-job-axis"],
                            "acp_version": "9.9.9",
                        },
                    }
                ],
            }
        },
        environment="local",
    )
    options = overlay["agent_profiles"]["solver"]["extensions"][0]["options"]
    assert options == {"entry": "pi", "reasoning_effort": "high"}


def test_overlay_expands_the_wildcard_onto_real_roles() -> None:
    overlay = project_job_overlay(
        {"*": dict(ACP_SOLVER)},
        environment="local",
        role_ids=["solver", "critic"],
    )
    assert set(overlay["agent_profiles"]) == {"solver", "critic"}


# --- display axis ----------------------------------------------------------


def test_agent_name_prefers_label_then_entry() -> None:
    assert display_agent_name({"label": "Pi (glm)", **ACP_SOLVER}) == "Pi (glm)"
    assert display_agent_name(dict(ACP_SOLVER)) == "pi"
    assert display_agent_name({"executor": "openai-http"}) == "openai-http"


def test_labels_collapse_identical_and_join_distinct() -> None:
    assert join_display_names(["pi", "pi"]) == "pi"
    assert join_display_names(["pi", "codex"]) == "pi+codex"
    agent, model = display_labels_from_overlay(
        {"agent_profiles": {"solver": dict(ACP_SOLVER), "critic": dict(ACP_SOLVER)}}
    )
    assert (agent, model) == ("pi", "m")
