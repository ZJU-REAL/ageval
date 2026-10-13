"""Binding overlays: path rules, lock existence, secret-free files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.helpers.lock import lock_with_profiles

from ageval.config.errors import ConfigError
from ageval.config.model import thaw
from ageval.config.overlay_files import (
    normalize_overlay_path,
    overlay_secret_hits,
    parse_overlay_paths,
)
from ageval.config.profiles import load_job_document


def _write_dataset(
    tmp: Path,
    *,
    agent_profiles: dict[str, Any],
    overlay_files: dict[str, str] | None = None,
) -> Path:
    db = tmp / "db"
    (db / "tasks" / "t").mkdir(parents=True)
    (db / "ageval.yaml").write_text(
        "format: ageval.dataset/1\ndataset_id: example/overlays\nversion: '0.1.0'\n"
        "tasks:\n  root: tasks\n",
        encoding="utf-8",
    )
    (db / "profiles.yaml").write_text(
        yaml.safe_dump({"format": "ageval.profiles/1", "agent_profiles": agent_profiles}),
        encoding="utf-8",
    )
    task = db / "tasks" / "t"
    (task / "run.py").write_text("async def run(ctx):\n    pass\n", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(i):\n    return {}\n", encoding="utf-8")
    (task / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "format": "ageval.task/1",
                "task_id": "t",
                "parameters": {"models": {"default": "solver"}},
                "agent_profiles": [{"id": "solver"}],
                "limits": {
                    "wall_time_seconds": 60,
                    "agent_invocations": 1,
                },
                "artifacts": {"publishable": []},
                "evaluation": {
                    "entrypoint": "evaluator:evaluate",
                    "inputs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    for rel, text in (overlay_files or {}).items():
        path = db / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return db


def _lock(db: Path, agent_profiles: dict[str, dict[str, Any]]):
    return lock_with_profiles(
        db / "tasks" / "t",
        "t",
        agent_profiles,
    )


def test_normalize_overlay_path_accepts_relative() -> None:
    assert normalize_overlay_path("overlays/AGENTS.md", location="t") == "overlays/AGENTS.md"
    assert parse_overlay_paths(
        ["overlays/skills/jsonl-agg", "overlays/skills/jsonl-agg"],
        location="t",
    ) == ["overlays/skills/jsonl-agg"]


@pytest.mark.parametrize(
    "raw",
    [
        "AGENTS.md",
        "overlays",
        "overlays/",
        "../overlays/x",
        "overlays/../secret",
        "/tmp/overlays/x",
        "~/overlays/x",
        "overlays//x",
        "",
    ],
)
def test_normalize_overlay_path_rejects_bad_shape(raw: str) -> None:
    with pytest.raises(ConfigError):
        normalize_overlay_path(raw, location="t")


def test_locator_forms_are_not_secrets() -> None:
    text = (
        '{"apiKey": "{env:litellm_api_key}", "other": "$litellm_api_key",'
        ' "baseUrl": "${litellm_base_url}", "baseURL": "{env:litellm_base_url}"}'
    )
    assert overlay_secret_hits(text) == []
    assert overlay_secret_hits("API key: see README") == []


def test_journeys_litellm_overlays_base_url_are_locators() -> None:
    root = (
        Path(__file__).resolve().parents[2] / "examples" / "datasets" / "minimal-demo" / "overlays"
    )
    pi = (root / "pi.litellm.json").read_text(encoding="utf-8")
    opencode = (root / "opencode.litellm.json").read_text(encoding="utf-8")
    assert "${litellm_base_url}" in pi
    assert "{env:litellm_base_url}" in opencode
    assert "http://" not in pi
    assert "http://" not in opencode


def test_pem_and_token_are_secrets() -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"
    assert "pem" in overlay_secret_hits(pem)
    assert "token" in overlay_secret_hits('token: "sk-abcdefghijklmnop"')
    entropy = "api_token = " + ("A7kQ9mN2pX4vB8wC1dE3fG5hJ6" * 2)
    assert overlay_secret_hits(entropy)


def test_omit_overlays_lock_unchanged(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        agent_profiles={
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": {"id": "m"},
            }
        },
    )
    locked = _lock(
        db,
        {
            "solver": {
                "executor": "acp",
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
                "model": {"id": "m"},
            }
        },
    )
    overlay = thaw(locked.job_overlay)
    assert "overlays" not in overlay["agent_profiles"]["solver"]


def test_lock_requires_existing_overlay_path(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        agent_profiles={"solver": {"executor": "openai-http", "model": {"id": "none"}}},
    )
    with pytest.raises(ConfigError) as ei:
        _lock(
            db,
            {
                "solver": {
                    "executor": "openai-http",
                    "model": {"id": "none"},
                    "overlays": ["overlays/missing.md"],
                }
            },
        )
    assert ei.value.error_code == "missing_reference"


def test_lock_accepts_file_and_directory(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        agent_profiles={"solver": {"executor": "openai-http", "model": {"id": "none"}}},
        overlay_files={
            "overlays/AGENTS.md": "# hello\n",
            "overlays/skills/jsonl-agg/SKILL.md": "# skill\n",
        },
    )
    agent_profiles = {
        "solver": {
            "executor": "openai-http",
            "model": {"id": "none"},
            "overlays": ["overlays/skills/jsonl-agg", "overlays/AGENTS.md"],
        }
    }
    locked = _lock(db, agent_profiles)
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["solver"]["overlays"] == [
        "overlays/skills/jsonl-agg",
        "overlays/AGENTS.md",
    ]


def test_lock_rejects_secret_in_overlay_file(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        agent_profiles={"solver": {"executor": "openai-http", "model": {"id": "none"}}},
        overlay_files={"overlays/secret.md": "-----BEGIN PRIVATE KEY-----\nabc\n"},
    )
    with pytest.raises(ConfigError) as ei:
        _lock(
            db,
            {
                "solver": {
                    "executor": "openai-http",
                    "model": {"id": "none"},
                    "overlays": ["overlays/secret.md"],
                }
            },
        )
    assert ei.value.error_code == "invalid_package"
    assert "secret" in str(ei.value).lower()


def test_lock_allows_env_locator_in_overlay_json(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        agent_profiles={"solver": {"executor": "openai-http", "model": {"id": "none"}}},
        overlay_files={
            "overlays/cfg.json": '{"apiKey": "{env:litellm_api_key}"}\n',
        },
    )
    locked = _lock(
        db,
        {
            "solver": {
                "executor": "openai-http",
                "model": {"id": "none"},
                "overlays": ["overlays/cfg.json"],
            }
        },
    )
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["solver"]["overlays"] == ["overlays/cfg.json"]


def test_standalone_task_cannot_declare_overlays(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "run.py").write_text("async def run(ctx):\n    pass\n", encoding="utf-8")
    (pkg / "evaluator.py").write_text("def evaluate(i):\n    return {}\n", encoding="utf-8")
    (pkg / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "format": "ageval.task/1",
                "task_id": "t",
                "parameters": {"models": {"default": "solver"}},
                "agent_profiles": [{"id": "solver"}],
                "limits": {
                    "wall_time_seconds": 60,
                    "agent_invocations": 1,
                },
                "artifacts": {"publishable": []},
                "evaluation": {
                    "entrypoint": "evaluator:evaluate",
                    "inputs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as ei:
        lock_with_profiles(
            pkg,
            "t",
            {
                "solver": {
                    "executor": "openai-http",
                    "model": {"id": "none"},
                    "overlays": ["overlays/AGENTS.md"],
                }
            },
        )
    assert ei.value.error_code == "invalid_package"


def test_profiles_document_normalizes_overlays(tmp_path: Path) -> None:
    path = tmp_path / "profiles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "format": "ageval.profiles/1",
                "agent_profiles": {
                    "solver": {
                        "executor": "openai-http",
                        "overlays": ["overlays/AGENTS.md"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    agent_profiles = load_job_document(path)
    assert agent_profiles.profiles["solver"]["overlays"] == ["overlays/AGENTS.md"]
