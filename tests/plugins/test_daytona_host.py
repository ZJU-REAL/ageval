"""daytona kind: fail-closed preflight, frozen attach_stdio, no vendor leak."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ageval.environments.protocol import BoxSpec, EnvironmentFailure
from ageval.plugins.contrib.daytona.host import (
    API_KEY_ENV,
    ATTACH_STDIO,
    DaytonaHost,
    _assert_image_tag,
    _auto_stop_minutes,
)

ROOT = Path(__file__).resolve().parents[2]


def _spec(tmp_path: Path) -> BoxSpec:
    return BoxSpec(attempt_root=tmp_path, task_root=tmp_path, repo_root=tmp_path)


def test_attach_stdio_is_a_kind_constant() -> None:
    assert DaytonaHost.capabilities.attach_stdio is ATTACH_STDIO
    assert DaytonaHost.capabilities.exec is True
    assert DaytonaHost.capabilities.upload is True
    assert DaytonaHost.capabilities.download is True
    assert DaytonaHost.capabilities.uid_gid is False
    assert DaytonaHost.capabilities.compose is False


@pytest.mark.asyncio
async def test_preflight_fails_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (API_KEY_ENV, "daytona_api_key"):
        monkeypatch.delenv(name, raising=False)
    host = DaytonaHost(spec=_spec(tmp_path))
    with pytest.raises(EnvironmentFailure) as ei:
        await host.preflight()
    assert ei.value.kind == "environment_preflight_failed"


def test_timeout_seconds_map_to_auto_stop_minutes() -> None:
    assert _auto_stop_minutes(900) == 15
    assert _auto_stop_minutes(60) == 1
    assert _auto_stop_minutes(1) == 1
    assert _auto_stop_minutes(3600) == 60


def test_child_env_drops_host_path_keeps_box_path(tmp_path: Path) -> None:
    host = DaytonaHost(spec=_spec(tmp_path))
    leaked = host._child_env({"PATH": "/Users/me/bin", "ZHIPU_API_KEY": "sk-not-for-lock"})
    assert "PATH" not in leaked
    assert leaked["ZHIPU_API_KEY"] == "sk-not-for-lock"
    native = host._child_env({"AGEVAL_WORKSPACE": "/attempt/workspace"})
    assert "PATH" not in native
    assert native["AGEVAL_ARTIFACTS"] == "/attempt/artifacts"


def test_rejects_floating_image_tags() -> None:
    with pytest.raises(EnvironmentFailure) as latest:
        _assert_image_tag("python:latest")
    assert latest.value.kind == "environment_image_unresolved"
    with pytest.raises(EnvironmentFailure) as bare:
        _assert_image_tag("python")
    assert bare.value.kind == "environment_image_unresolved"
    with pytest.raises(EnvironmentFailure) as lts:
        _assert_image_tag("ubuntu:lts")
    assert lts.value.kind == "environment_image_unresolved"
    _assert_image_tag("python:3.12.7")
    _assert_image_tag("python@sha256:abc")


def test_acp_and_attempt_do_not_import_daytona() -> None:
    roots = (
        ROOT / "src" / "ageval" / "plugins" / "contrib" / "acp",
        ROOT / "src" / "ageval" / "attempt",
        ROOT / "examples",
    )
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if (
                "if kind == daytona" in text
                or "if kind == 'daytona'" in text
                or 'if kind == "daytona"' in text
            ):
                offenders.append(str(path.relative_to(ROOT)))
            if "import daytona" in text and "contrib/daytona" not in str(path):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_probe_without_key_is_not_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (API_KEY_ENV, "daytona_api_key"):
        monkeypatch.delenv(name, raising=False)
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: daytona",
                "environment_options:",
                "  image: python:3.12.7",
                "agent_profiles:",
                '  "*":',
                "    executor: acp",
                "    model: {id: entry-default}",
                "    options:",
                "      entry: pi",
                "    extensions:",
                "      - plugin: acp",
                "      - plugin: daytona",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop(API_KEY_ENV, None)
    env.pop("daytona_api_key", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "run",
            str(ROOT / "examples/datasets/minimal-demo"),
            "--task",
            "terminal-jsonl-agg",
            "--profiles",
            str(profiles),
            "--probe",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert data.get("ready") is False
    assert data.get("started") is False
    assert "stdio" not in str(data.get("error") or "").lower()


def test_lock_acp_plus_daytona_succeeds_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (API_KEY_ENV, "daytona_api_key"):
        monkeypatch.delenv(name, raising=False)
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: daytona",
                "environment_options:",
                "  image: python:3.12.7",
                "agent_profiles:",
                '  "*":',
                "    executor: acp",
                "    model: {id: entry-default}",
                "    options:",
                "      entry: pi",
                "    extensions:",
                "      - plugin: acp",
                "      - plugin: daytona",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop(API_KEY_ENV, None)
    env.pop("daytona_api_key", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "lock",
            str(ROOT / "examples/datasets/minimal-demo"),
            "--task",
            "terminal-jsonl-agg",
            "--profiles",
            str(profiles),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert data.get("environment") == "daytona"
    solver = data["extension_bindings"]["solver"]
    assert solver["slots"]["environment"]["plugin"] == "daytona"
    assert solver["slots"]["executor"]["plugin"] == "acp"
    inject = (solver.get("inject") or {}).get("acp") or []
    caps = next(
        tuple(row.get("capabilities") or ())
        for row in inject
        if row.get("service") == "environment"
    )
    assert "attach_stdio" in caps
