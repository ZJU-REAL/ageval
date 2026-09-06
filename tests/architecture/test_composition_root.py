"""CLI must assemble run/campaign through the production composition root."""

from __future__ import annotations

import inspect
from pathlib import Path

from ageval.application import composition
from ageval.cli import main as cli_main


def test_build_lock_command_is_wired() -> None:
    assert callable(composition.build_lock_command().lock)


def test_build_dataset_checkout_is_wired() -> None:
    assert callable(composition.build_dataset_checkout())


def test_build_run_attempt_returns_the_use_case() -> None:
    run_attempt = composition.build_run_attempt()
    assert inspect.iscoroutinefunction(run_attempt)


def test_cli_reaches_run_only_through_composition() -> None:
    cli_dir = Path(cli_main.__file__).resolve().parent
    sources = "\n".join(p.read_text(encoding="utf-8") for p in cli_dir.glob("*.py"))
    assert "build_run_attempt" in sources
    assert "build_dataset_checkout" in sources
    assert "from ageval.application.run import" not in sources
    assert "from ageval.registry.resolve import" not in sources
    assert "from ageval.viewer.jobs import" not in sources


def test_cli_campaign_uses_composition() -> None:
    cli_dir = Path(cli_main.__file__).resolve().parent
    sources = "\n".join(p.read_text(encoding="utf-8") for p in cli_dir.glob("*.py"))
    assert "build_campaign_runner" in sources
    assert "from ageval.application.campaign import run_campaign" not in sources


def test_build_agent_commands_installs_from_path_and_registry() -> None:
    cmds = composition.build_agent_commands()
    assert callable(cmds.install_agent_from_path)
    assert callable(cmds.install_agent_from_registry)


def test_cli_imports_composition_only() -> None:
    cli_dir = Path(cli_main.__file__).resolve().parent
    offenders: list[str] = []
    for path in cli_dir.glob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "ageval.application." not in stripped:
                continue
            if "ageval.application.composition" in stripped:
                continue
            offenders.append(f"{path.name}:{i}:{stripped}")
    assert offenders == []
