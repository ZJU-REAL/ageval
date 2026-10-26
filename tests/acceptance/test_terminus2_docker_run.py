"""Named terminus-2 example: lock the agent package. No container, no frontier model."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ageval.registry.agent_package import assert_agent_package

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "examples" / "datasets" / "terminus-2-min"
AGENT = REPO / "examples" / "agents" / "terminus-2-default"


def _env(home: Path, base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["AGEVAL_HOME"] = str(home)
    env["OPENAI_API_KEY"] = "ci-loopback-placeholder"
    env["OPENAI_BASE_URL"] = base_url
    env.pop("AGEVAL_OFFLINE_AGENT", None)
    return env


def _install(home: Path) -> None:
    from ageval.plugins.store import install_from_path

    home.mkdir()
    previous = os.environ.get("AGEVAL_HOME")
    os.environ["AGEVAL_HOME"] = str(home)
    try:
        install_from_path(REPO / "plugins" / "terminus-2")
    finally:
        if previous is None:
            os.environ.pop("AGEVAL_HOME", None)
        else:
            os.environ["AGEVAL_HOME"] = previous


def _ageval(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=1200,
    )


def test_agent_package_and_lock(tmp_path: Path) -> None:
    assert_agent_package(AGENT)
    home = tmp_path / "ageval-home"
    _install(home)
    env = _env(home, "https://example.invalid/v1")
    locked = _ageval(env, "lock", str(DATASET), "--task", "hello")
    assert locked.returncode == 0, locked.stderr or locked.stdout
    data = json.loads(locked.stdout)
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["executor"]["plugin"] == "terminus-2"
    assert "ci-loopback-placeholder" not in json.dumps(data)
