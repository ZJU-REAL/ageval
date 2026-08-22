"""Reserved first-party plugin ids are not Hub packages."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.plugins.manifest import PluginManifestError
from ageval.plugins.reserved import reject_reserved_plugin_id, reserved_short_id

ROOT = Path(__file__).resolve().parents[2]


def _write_plugin(root: Path, plugin_id: str) -> None:
    root.mkdir()
    (root / "plugin.yaml").write_text(
        "\n".join(
            [
                "format: ageval.plugin/1",
                f"plugin_id: {plugin_id}",
                "version: 0.1.0",
                "slots:",
                "  exclusive:",
                "    - id: executor",
                "      priority: 50",
                '      entry: "sample_echo.factory:build_executor"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("docker", "docker"),
        ("Docker", "docker"),
        ("acme/docker", "docker"),
        ("docker@1.0.0", "docker"),
        ("official/openai-http@sha256:abc", "openai-http"),
        ("sample-echo", None),
        ("acme/nooa", None),
    ],
)
def test_reserved_short_id(raw: str, want: str | None) -> None:
    assert reserved_short_id(raw) == want


def test_reject_reserved_plugin_id() -> None:
    with pytest.raises(PluginManifestError) as ei:
        reject_reserved_plugin_id("org/acp")
    assert ei.value.kind == "plugin_id_reserved"


def test_cli_install_docker_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    env = {**os.environ, "AGEVAL_HOME": str(home)}
    proc = subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "plugin", "install", "docker"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stderr)
    assert data["error"] == "plugin_id_reserved"


def test_cli_install_locator_alias_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    env = {**os.environ, "AGEVAL_HOME": str(home)}
    proc = subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "plugin", "install", "acme/docker@1.0.0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stderr)
    assert data["error"] == "plugin_id_reserved"


def test_publish_reserved_plugin_id(tmp_path: Path) -> None:
    from ageval.application.plugin_ops.plugin_publish import PluginPublishCommand

    root = tmp_path / "plug"
    _write_plugin(root, "docker")
    cmd = PluginPublishCommand(client_factory=lambda **_k: None)
    with pytest.raises(ConfigError) as ei:
        cmd.publish_plugin(root, org="acme")
    assert ei.value.error_code == "plugin_id_reserved"


def test_install_from_local_reserved_manifest(tmp_path: Path) -> None:
    from ageval.plugins.install import install_from_local

    root = tmp_path / "plug"
    _write_plugin(root, "e2b")
    with pytest.raises(PluginManifestError) as ei:
        install_from_local(root)
    assert ei.value.kind == "plugin_id_reserved"
