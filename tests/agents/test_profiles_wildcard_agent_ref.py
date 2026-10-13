"""Wildcard "*" default binding + agent_ref passthrough in profiles (design/14)."""

from __future__ import annotations

import pytest

from ageval.config.errors import ConfigError
from ageval.config.profiles import (
    job_overlay_to_profiles_document,
    merge_job_onto_slots,
    parse_job_mapping,
    project_job_overlay,
)

WILDCARD_DOC = {
    "format": "ageval.profiles/1",
    "agent_profiles": {
        "*": {
            "executor": "openai-http",
            "model": {"id": "none"},
            "agent_ref": "local/m@0.1.0+sha256:abc",
        },
        "critic": {"executor": "openai-http", "model": {"id": "other"}},
    },
}


def test_parse_accepts_wildcard_key() -> None:
    job = parse_job_mapping(WILDCARD_DOC)
    assert set(job.profiles) == {"*", "critic"}


def test_parse_still_rejects_bad_role_ids() -> None:
    doc = {
        "format": "ageval.profiles/1",
        "agent_profiles": {"**": {"executor": "openai-http", "model": {"id": "x"}}},
    }
    with pytest.raises(ConfigError):
        parse_job_mapping(doc)


def test_merge_exact_wins_wildcard_falls_back() -> None:
    job = parse_job_mapping(WILDCARD_DOC)
    merged = merge_job_onto_slots([{"id": "solver"}, {"id": "critic"}], job)
    by_id = {row["id"]: row for row in merged}
    assert by_id["solver"]["model"] == {"id": "none"}  # wildcard fallback
    assert by_id["solver"]["agent_ref"] == "local/m@0.1.0+sha256:abc"
    assert by_id["critic"]["model"] == {"id": "other"}  # exact wins
    assert "agent_ref" not in by_id["critic"]


def test_merge_without_wildcard_still_fails_closed() -> None:
    job = parse_job_mapping(
        {
            "format": "ageval.profiles/1",
            "agent_profiles": {"critic": {"executor": "openai-http", "model": {"id": "x"}}},
        }
    )
    with pytest.raises(ConfigError):
        merge_job_onto_slots([{"id": "solver"}], job)


def test_project_expands_wildcard_to_real_roles() -> None:
    job = parse_job_mapping(WILDCARD_DOC)
    overlay = project_job_overlay(
        job.profiles, environment=job.environment, role_ids=["solver", "critic"]
    )
    rows = overlay["agent_profiles"]
    assert set(rows) == {"solver", "critic"}
    assert rows["solver"]["agent_ref"] == "local/m@0.1.0+sha256:abc"
    assert rows["critic"]["model"] == {"id": "other"}
    assert "*" not in rows


def test_agent_ref_round_trips_via_profiles_document() -> None:
    job = parse_job_mapping(WILDCARD_DOC)
    overlay = project_job_overlay(job.profiles, environment=job.environment, role_ids=["solver"])
    doc = job_overlay_to_profiles_document(overlay)
    assert doc["agent_profiles"]["solver"]["agent_ref"] == "local/m@0.1.0+sha256:abc"


def test_task_yaml_slots_reject_agent_ref_inline() -> None:
    from ageval.config.profiles import assert_slots_have_no_inline_binding

    with pytest.raises(ConfigError):
        assert_slots_have_no_inline_binding([{"id": "solver", "agent_ref": "x@1"}])


def test_suite_compat_and_labels_with_wildcard_binding() -> None:
    """Found via live eval: '*' suite binding blanked labels / homogeneity."""
    from ageval.application.suite.suite_config_fingerprint import (
        compute_suite_config_fields,
        job_overlays_compatible,
    )

    binding = {
        "executor": "acp",
        "model": {"id": "entry-default"},
        "label": "Claude Code (entry default)",
        "extensions": [{"plugin": "acp", "options": {"entry": "claude-code"}}],
    }
    suite_overlay = {"agent_profiles": {"*": binding}}
    per_task = [{"agent_profiles": {"solver": dict(binding)}}]

    assert job_overlays_compatible(suite_overlay, per_task) is True
    # A conflicting model for the same role still breaks compatibility.
    conflicting = [{"agent_profiles": {"solver": {**binding, "model": "other"}}}]
    assert job_overlays_compatible(suite_overlay, conflicting) is False

    fields = compute_suite_config_fields([], job_overlay=suite_overlay, per_task_overlays=per_task)
    assert fields["config_homogeneous"] is True
    assert fields["agent_label"] == "Claude Code (entry default)"


def test_wildcard_and_explicit_spellings_share_fingerprint() -> None:
    """Identity must not depend on '*'-vs-explicit spelling (design/14)."""
    from ageval.application.suite.suite_config_fingerprint import compute_suite_config_fields

    binding = {
        "executor": "acp",
        "model": {"id": "entry-default"},
        "extensions": [{"plugin": "acp", "options": {"entry": "claude-code"}}],
    }
    per_task = [{"agent_profiles": {"solver": dict(binding)}}]
    via_wildcard = compute_suite_config_fields(
        [], job_overlay={"agent_profiles": {"*": binding}}, per_task_overlays=per_task
    )
    via_explicit = compute_suite_config_fields(
        [], job_overlay={"agent_profiles": {"solver": dict(binding)}}, per_task_overlays=per_task
    )
    assert via_wildcard["config_fingerprint"] == via_explicit["config_fingerprint"]
    assert [a["profile_id"] for a in via_wildcard["actors_summary"]] == ["solver"]


def test_overlays_do_not_inherit_onto_exact_row() -> None:
    """``--agent xx --agent user=yy`` must not copy xx's overlay tree onto user."""
    job = parse_job_mapping(
        {
            "format": "ageval.profiles/1",
            "agent_profiles": {
                "*": {
                    "executor": "openai-http",
                    "model": {"id": "none"},
                    "overlays": ["overlays/skills/demo"],
                    "agent_ref": "official/xx@0.1.0+sha256:aaaaaaaaaaaa",
                },
                "user": {
                    "executor": "openai-http",
                    "model": {"id": "other"},
                    "agent_ref": "official/yy@0.1.0+sha256:bbbbbbbbbbbb",
                },
            },
        }
    )
    overlay = project_job_overlay(
        job.profiles, environment=job.environment, role_ids=["solver", "user"]
    )
    rows = overlay["agent_profiles"]
    assert rows["solver"]["overlays"] == ["overlays/skills/demo"]
    assert rows["solver"]["agent_ref"].startswith("official/xx@")
    assert "overlays" not in rows["user"]
    assert rows["user"]["agent_ref"].startswith("official/yy@")


def test_exact_row_overrides_wildcard_field_wise() -> None:
    """--set on one field of a wildcard-bound agent must not drop the rest."""
    from ageval.config.profiles import apply_profile_override, effective_profile

    job = parse_job_mapping(
        {
            "format": "ageval.profiles/1",
            "agent_profiles": {
                "*": {
                    "executor": "acp",
                    "model": {"id": "entry-default"},
                    "extensions": [{"plugin": "acp", "options": {"entry": "claude-code"}}],
                }
            },
        }
    )
    apply_profile_override(job, "/agent_profiles/solver/model/id", "claude-opus-5")
    merged = merge_job_onto_slots([{"id": "solver"}, {"id": "critic"}], job)
    by_id = {row["id"]: row for row in merged}
    assert by_id["solver"]["model"]["id"] == "claude-opus-5"  # override wins
    assert by_id["solver"]["executor"] == "acp"  # inherited from wildcard
    assert by_id["solver"]["extensions"][0]["options"]["entry"] == "claude-code"
    assert by_id["critic"]["model"] == {"id": "entry-default"}  # untouched fallback

    eff = effective_profile(job.profiles, "solver")
    assert eff is not None and eff["model"]["id"] == "claude-opus-5" and eff["executor"] == "acp"
