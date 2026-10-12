"""Suite config fingerprint / homogeneity (#42 + #59 job_overlay axis)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.suite.suite_config_fingerprint import (
    actors_summary_from_profiles,
    compute_suite_config_fields,
    fingerprint_for_actors,
    fingerprint_for_job_overlay,
    job_overlays_compatible,
    plugins_from_extension_bindings,
    plugins_from_job_overlay,
)
from ageval.application.suite.suite_run import execute_suite_run, plan_suite_run

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"
JOURNEYS = REPO / "examples" / "datasets" / "minimal-demo"


def test_actors_summary_sorted_and_secret_free() -> None:
    profiles = [
        {
            "id": "worker",
            "executor": "acp",
            "model": "m2",
            "api_key": "SECRET_LOCATOR",
            "extensions": [
                {"plugin": "acp", "options": {"entry": "pi", "reasoning_effort": "high"}}
            ],
        },
        {
            "id": "planner",
            "executor": "acp",
            "model": "m1",
            "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
        },
    ]
    actors = actors_summary_from_profiles(profiles)
    assert [a["profile_id"] for a in actors] == ["planner", "worker"]
    assert actors[0]["entry"] == "codex"
    assert actors[1]["entry"] == "pi"
    assert "reasoning_effort" in actors[1]["options"]
    blob = str(actors)
    assert "SECRET" not in blob
    assert "api_key" not in blob


def test_nested_model_fingerprint_uses_id() -> None:
    actors = actors_summary_from_profiles(
        [
            {
                "id": "solver",
                "executor": "miniswe",
                "model": {"id": "openai/glm-5.2", "api": "responses", "timeout": 30},
                "extensions": [{"plugin": "miniswe", "options": {"step_limit": 20}}],
            }
        ]
    )
    assert actors[0]["model"] == "openai/glm-5.2"


def test_job_overlay_axis_ignores_role_topology_diff() -> None:
    """Different role ids across tasks still share one profiles.yaml job axis (#59)."""
    suite_overlay = {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": "m",
            },
            "user": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "grok-build"}}],
                "model": "entry-default",
            },
            "service": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "opencode"}}],
                "model": "m2",
            },
        }
    }
    # Task A used only solver; task B used user+service — topology differs.
    per_task_overlays = [
        {"agent_profiles": {"solver": suite_overlay["agent_profiles"]["solver"]}},
        {
            "agent_profiles": {
                "user": suite_overlay["agent_profiles"]["user"],
                "service": suite_overlay["agent_profiles"]["service"],
            }
        },
        None,  # no-agent task
    ]
    fields = compute_suite_config_fields(
        [[], [], []],
        job_overlay=suite_overlay,
        per_task_overlays=per_task_overlays,
    )
    assert fields["config_homogeneous"] is True
    assert fields["config_fingerprint"] == fingerprint_for_job_overlay(suite_overlay)
    assert fields["job_overlay"] == suite_overlay
    assert {a["profile_id"] for a in fields["actors_summary"]} == {
        "service",
        "solver",
        "user",
    }


def test_job_overlay_conflict_not_homogeneous() -> None:
    suite_overlay = {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": "m1",
            }
        }
    }
    conflict = {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
                "model": "m1",
            }
        }
    }
    fields = compute_suite_config_fields(
        [[]],
        job_overlay=suite_overlay,
        per_task_overlays=[conflict],
    )
    assert fields["config_homogeneous"] is False


def test_job_overlays_compatible_helper() -> None:
    suite = {
        "agent_profiles": {
            "a": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": "m",
            },
            "b": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
                "model": "n",
            },
        }
    }
    assert job_overlays_compatible(
        suite, [None, {"agent_profiles": {"a": suite["agent_profiles"]["a"]}}]
    )
    assert not job_overlays_compatible(
        suite,
        [
            {
                "agent_profiles": {
                    "a": {
                        "executor": "acp",
                        "extensions": [{"plugin": "acp", "options": {"entry": "opencode"}}],
                        "model": "m",
                    }
                }
            }
        ],
    )


def test_homogeneous_true_identical_topology() -> None:
    a = actors_summary_from_profiles(
        [
            {
                "id": "solo",
                "executor": "acp",
                "model": "x",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
            }
        ]
    )
    fields = compute_suite_config_fields([a, a, a])
    assert fields["config_homogeneous"] is True
    assert fields["config_fingerprint"].startswith("sha256:")
    assert fields["actors_summary"] == a
    assert fields["agent_label"] == "pi"
    assert fields["model_label"] == "x"


def test_derive_labels_nooa_uses_executor_not_options_agent() -> None:
    a = actors_summary_from_profiles(
        [
            {
                "id": "solver",
                "executor": "nooa",
                "model": "openai/glm-5.2",
                "options": {"agent": "lib.agents:JsonlAggAgent"},
            }
        ]
    )
    fields = compute_suite_config_fields([a])
    assert fields["agent_label"] == "nooa"
    assert fields["model_label"] == "openai/glm-5.2"


def test_empty_agent_tasks_do_not_break_fallback_homogeneity() -> None:
    """No-agent tasks + identical agent tasks remain homogeneous (fallback path)."""
    solo = actors_summary_from_profiles(
        [
            {
                "id": "solo",
                "executor": "acp",
                "model": "x",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
            }
        ]
    )
    fields = compute_suite_config_fields([[], solo, solo])
    assert fields["config_homogeneous"] is True
    assert fields["actors_summary"] == solo


def test_fallback_different_models_not_homogeneous() -> None:
    a = actors_summary_from_profiles(
        [
            {
                "id": "solo",
                "executor": "acp",
                "model": "gpt-a",
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
            }
        ]
    )
    b = actors_summary_from_profiles(
        [
            {
                "id": "solo",
                "executor": "acp",
                "model": "gpt-b",
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
            }
        ]
    )
    fields = compute_suite_config_fields([a, b])
    assert fields["config_homogeneous"] is False


def test_fingerprint_stable() -> None:
    actors = actors_summary_from_profiles(
        [
            {"id": "b", "executor": "openai-http", "model": "m"},
            {
                "id": "a",
                "executor": "acp",
                "model": "n",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
            },
        ]
    )
    assert fingerprint_for_actors(actors) == fingerprint_for_actors(list(reversed(actors)))


def test_overlays_do_not_change_config_fingerprint() -> None:
    base = {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "grok-build"}}],
                "model": "m",
            }
        }
    }
    with_overlays = {
        "agent_profiles": {
            "solver": {
                **base["agent_profiles"]["solver"],
                "overlays": ["overlays/AGENTS.md"],
            }
        }
    }
    assert fingerprint_for_job_overlay(base) == fingerprint_for_job_overlay(with_overlays)


def test_model_change_changes_fingerprint() -> None:
    base = {
        "agent_profiles": {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": "entry-default",
            }
        }
    }
    other = {
        "agent_profiles": {
            "solver": {**base["agent_profiles"]["solver"], "model": "glm-4.7"},
        }
    }
    assert fingerprint_for_job_overlay(base) != fingerprint_for_job_overlay(other)


@pytest.mark.asyncio
async def test_suite_summary_includes_homogeneous_config() -> None:
    plan = plan_suite_run(SUITE, max_concurrent_tasks=2)
    plan.task_ids = ["alpha", "beta"]

    async def stub(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        result = SimpleNamespace(status="PASS", score=1.0, evidence_path=None, logs=None)
        return 0, result

    summary = await execute_suite_run(plan, run_fn=stub)
    assert "config_fingerprint" in summary
    assert summary["config_fingerprint"].startswith("sha256:")
    assert summary["config_homogeneous"] is True
    assert isinstance(summary["actors_summary"], list)
    # suite-min has empty agent_profiles → empty actors / no job_overlay
    assert summary["actors_summary"] == []
    assert "no suite-level" in summary["note"]


def test_journeys_profiles_are_suite_homogeneous() -> None:
    """example/minimal-demo multi-topology package shares one profiles.yaml axis."""
    from ageval.application.suite.suite_config_fingerprint import collect_suite_config

    # Fake per-task rows without needing a full run
    fields = collect_suite_config(
        JOURNEYS,
        [
            {"task_id": "env-postgres-min"},
            {"task_id": "terminal-jsonl-agg"},
            {"task_id": "tau2-dialog-min"},
            {"task_id": "multiagent-env-min"},
        ],
        task_ids=[
            "env-postgres-min",
            "terminal-jsonl-agg",
            "tau2-dialog-min",
            "multiagent-env-min",
        ],
    )
    assert fields["config_homogeneous"] is True
    assert fields.get("job_overlay", {}).get("agent_profiles")
    roles = set(fields["job_overlay"]["agent_profiles"])
    assert roles == {"*"} or "solver" in roles
    assert roles == {"*"} or "user" in roles or "specialist" in roles


def test_plugins_from_extension_bindings_skip_defaults() -> None:
    agent_profiles = {
        "solver": {
            "executor": {
                "kind": "provide",
                "plugin": "nooa",
                "version": "0.1.0",
            },
            "before_run": {
                "kind": "on",
                "chain": [
                    {"plugin": "default", "source": "default"},
                    {"plugin": "slot-probe", "version": "1.0.0"},
                ],
            },
        }
    }
    refs = plugins_from_extension_bindings(agent_profiles)
    assert [r["plugin_id"] for r in refs] == ["nooa", "slot-probe"]
    assert refs[0]["version"] == "0.1.0"


def test_plugins_from_job_overlay_skips_builtin_executors() -> None:
    overlay = {
        "agent_profiles": {
            "solver": {"executor": "nooa", "model": "m"},
            "user": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "codex"}}],
            },
            "alt": {"executor": "ACP"},
            "http": {"executor": "OpenAI-HTTP"},
        }
    }
    refs = plugins_from_job_overlay(overlay)
    assert refs == [{"plugin_id": "nooa"}]
