"""Spec 00: ageval lock writes per-profile extension_bindings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _chain_plugins(fragment: dict, slot: str) -> set[str]:
    slots = fragment.get("slots") if isinstance(fragment.get("slots"), dict) else fragment
    row = (slots or {}).get(slot) or {}
    return {str(item.get("plugin")) for item in (row.get("chain") or [])}


def _lock(*args: str, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "lock",
            str(ROOT / "examples/datasets/minimal-demo"),
            "--task",
            "terminal-jsonl-agg",
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def _isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *plugin_ids: str
) -> dict[str, str]:
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    for plugin_id in plugin_ids:
        install_from_path(ROOT / "plugins" / plugin_id)
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["litellm_api_key"] = "sk-lock-must-not-see"
    env["litellm_base_url"] = "https://example.invalid/v1"
    return env


def test_lock_cli_extension_bindings_solver_acp() -> None:
    data = _lock()
    agent_profiles = data["extension_bindings"]
    assert "solver" in agent_profiles
    assert agent_profiles["solver"]["slots"]["executor"]["plugin"] == "acp"
    assert agent_profiles["solver"]["slots"]["executor"]["source"] == "profile_executor_field"
    assert agent_profiles["solver"]["slots"]["executor"]["kind"] == "exclusive"
    runtime = agent_profiles["solver"]["slots"]["evaluation_runtime"]
    assert runtime == {
        "kind": "exclusive",
        "plugin": "default",
        "priority": 1000,
        "source": "default",
    }
    seal = agent_profiles["solver"]["slots"]["trajectory_seal"]
    assert seal == {
        "kind": "exclusive",
        "plugin": "default",
        "priority": 1000,
        "source": "default",
    }
    assert agent_profiles["solver"]["slots"]["trajectory_collect"]["kind"] == "chain"
    assert any(e.get("pointer") == "/extension_bindings" for e in data.get("resolution") or [])
    assert "dsh" not in _chain_plugins(agent_profiles["solver"], "trajectory_collect")
    assert "nooa" not in _chain_plugins(agent_profiles["solver"], "trajectory_collect")


def test_lock_dsh_profile_selects_dsh_not_nooa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _isolated_home(tmp_path, monkeypatch, "dsh", "nooa")
    data = _lock(
        "--profiles", str(ROOT / "examples/datasets/minimal-demo/profiles.dsh.yaml"), env=env
    )
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "dsh"
    collect = _chain_plugins(solver, "trajectory_collect")
    assert "dsh" in collect
    assert "nooa" not in collect
    dsh_inject = (solver.get("inject") or {}).get("dsh") or []
    assert any(row.get("service") == "environment" for row in dsh_inject)
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in dsh_inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec", "upload"}
    assert "sk-lock-must-not-see" not in json.dumps(data)


def test_lock_nooa_profile_records_inject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _isolated_home(tmp_path, monkeypatch, "nooa")
    data = _lock(
        "--profiles", str(ROOT / "examples/datasets/minimal-demo/profiles.nooa.yaml"), env=env
    )
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "nooa"
    nooa_inject = (solver.get("inject") or {}).get("nooa") or []
    assert any(row.get("service") == "environment" for row in nooa_inject)
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in nooa_inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec", "upload"}
    assert "sk-lock-must-not-see" not in json.dumps(data)


def test_lock_openhands_profile_records_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _isolated_home(tmp_path, monkeypatch, "openhands")
    data = _lock(
        "--profiles",
        str(ROOT / "examples/datasets/minimal-demo/profiles.openhands.yaml"),
        env=env,
    )
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "openhands"
    collect = _chain_plugins(solver, "trajectory_collect")
    assert "openhands" in collect
    inject = (solver.get("inject") or {}).get("openhands") or []
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in inject
        if row.get("service") == "environment"
    )
    assert set(caps) == {"exec", "upload", "download"}
    assert "sk-lock-must-not-see" not in json.dumps(data)
