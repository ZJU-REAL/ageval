"""ACP plugin image_layers: bound entry body, content key, no model."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ageval.plugins.contrib.acp.bake import render_bake_body
from ageval.plugins.contrib.acp.hooks import _needed_commands
from ageval.plugins.contrib.acp.registry import get_entry, list_entry_ids
from ageval.plugins.contrib.docker import images
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.image_layers import (
    layers_for_graph,
    layers_for_plugins,
)
from ageval.plugins.protocol import ExtensionGraph, HandlerRef, WinnerRef
from ageval.plugins.slots import AFTER_ENVIRONMENT_READY, EXECUTOR

_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "src/ageval/plugins/contrib/acp/docker/Dockerfile.bake"
)


def _template() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def _graph(entry: str, extra_options: dict[str, str] | None = None) -> ExtensionGraph:
    options = {"entry": entry, **(extra_options or {})}
    return ExtensionGraph(
        profile_id="solver",
        winners={
            EXECUTOR: WinnerRef(
                plugin_id="acp",
                impl=object(),
                priority=100,
                source="test",
                slot=EXECUTOR,
                options=options,
            ),
        },
        chains={
            AFTER_ENVIRONMENT_READY: [
                HandlerRef(
                    plugin_id="acp",
                    handler=object(),
                    priority=100,
                    source="test",
                    slot=AFTER_ENVIRONMENT_READY,
                    options=options,
                )
            ],
        },
    )


class _FakeDaemon:
    def __init__(self) -> None:
        self.images: set[str] = set()
        self.builds: list[tuple[str, str]] = []

    def __call__(self, *args: str, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
        del timeout
        if args[:2] == ("image", "inspect"):
            tag = args[2]
            if tag in self.images:
                return subprocess.CompletedProcess(
                    list(args), 0, stdout=f"sha256:{tag}\n", stderr=""
                )
            return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="missing")
        if args[:2] == ("buildx", "build"):
            tag = args[args.index("-t") + 1]
            source = Path(args[args.index("-f") + 1])
            self.builds.append((tag, source.read_text(encoding="utf-8")))
            self.images.add(tag)
            return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")
        if args[0] == "tag":
            src, dest = args[1], args[2]
            if src in self.images:
                self.images.add(dest)
                return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")
            return subprocess.CompletedProcess(list(args), 1, stdout="", stderr="missing src")
        return subprocess.CompletedProcess(list(args), 1, stdout="", stderr=f"unexpected {args}")


def test_bake_template_uses_base_image_arg() -> None:
    text = _template()
    assert "ARG BASE_IMAGE" in text
    assert "FROM ${BASE_IMAGE}" in text
    assert all(
        "npx" not in line.split()
        for line in text.splitlines()
        if line and not line.lstrip().startswith("#")
    )
    assert "__ACP_ENTRY_PACKAGES__" in text


def test_render_opencode_bakes_pinned_detect_commands() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    body = render_bake_body(_template(), "opencode")
    assert "opencode-ai@1.18.12" in body
    assert "command -v opencode" in body
    assert "__ACP_ENTRY_PACKAGES__" not in body
    assert all(
        "npx" not in line.split()
        for line in body.splitlines()
        if line and not line.lstrip().startswith("#")
    )
    assert "pi-acp@" not in body


def test_render_pi_vs_opencode_bodies_differ() -> None:
    pi = render_bake_body(_template(), "pi")
    opencode = render_bake_body(_template(), "opencode")
    assert pi != opencode
    assert "pi-acp@0.0.33" in pi
    assert "@earendil-works/pi-coding-agent@0.83.0" in pi
    assert "command -v pi" in pi
    assert "command -v pi-acp" in pi
    assert "opencode-ai@" not in pi


def test_render_unknown_entry_fails_closed() -> None:
    with pytest.raises(ExtensionMaterializeError, match="unknown acp entry"):
        render_bake_body(_template(), "not-an-entry")


def test_render_every_registered_entry() -> None:
    template = _template()
    ids = list_entry_ids()
    assert ids
    bodies: dict[str, str] = {}
    for entry_id in ids:
        desc = get_entry(entry_id)
        assert desc is not None
        body = render_bake_body(template, entry_id)
        bodies[entry_id] = body
        prefix = "npm install -g "
        assert desc.install_command.startswith(prefix)
        for token in desc.install_command[len(prefix) :].split():
            assert token in body
        for name in _needed_commands(desc):
            assert f"command -v {name}" in body
        assert "__ACP_ENTRY_PACKAGES__" not in body
        assert "__ACP_DETECT_BINARIES__" not in body
        assert all(
            "npx" not in line.split()
            for line in body.splitlines()
            if line and not line.lstrip().startswith("#")
        )
    assert "codex" in bodies
    _assert_codex_native_run_uses_bash(bodies["codex"])
    for entry_id, body in bodies.items():
        if entry_id == "codex":
            continue
        assert "< <(" not in body
        assert "read -r -d" not in body
        assert 'SHELL ["/bin/bash", "-c"]' not in body


def _assert_codex_native_run_uses_bash(body: str) -> None:
    shell = 'SHELL ["/bin/bash", "-c"]'
    assert shell in body
    proc = body.find("< <(")
    assert proc != -1
    assert body.find(shell) < proc
    assert "read -r -d ''" in body[body.find(shell) :]


def test_bundled_acp_declares_image_layers() -> None:
    layers = layers_for_plugins(frozenset({"acp"}))
    assert len(layers) == 1
    layer = layers[0]
    assert layer.plugin_id == "acp"
    assert layer.dockerfile.name == "Dockerfile.bake"
    assert "__ACP_ENTRY_PACKAGES__" in layer.body


def test_layers_for_graph_fills_bound_entry() -> None:
    rows = layers_for_graph(_graph("opencode"))
    assert len(rows) == 1
    plugin_id, _dockerfile, _root, body = rows[0]
    assert plugin_id == "acp"
    assert "opencode-ai@1.18.12" in body
    assert "__ACP_ENTRY_PACKAGES__" not in body


def test_model_option_does_not_change_layer_body() -> None:
    plain = layers_for_graph(_graph("opencode"))
    with_model = layers_for_graph(_graph("opencode", {"model": "gpt-5.4-mini"}))
    assert plain[0][3] == with_model[0][3]
    assert "gpt-5.4-mini" not in with_model[0][3]


def test_layers_for_graph_requires_entry() -> None:
    graph = ExtensionGraph(
        profile_id="solver",
        winners={
            EXECUTOR: WinnerRef(
                plugin_id="acp",
                impl=object(),
                priority=100,
                source="test",
                slot=EXECUTOR,
            ),
        },
    )
    with pytest.raises(ExtensionMaterializeError, match="acp_entry_required"):
        layers_for_graph(graph)


def test_same_recipe_different_entry_two_content_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_PIP_INDEX", raising=False)
    fake = _FakeDaemon()
    monkeypatch.setattr(images, "docker", fake)
    task = tmp_path / "task"
    task.mkdir()
    (task / "Dockerfile").write_text("FROM ubuntu:24.04\n", encoding="utf-8")
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    kwargs = {
        "task_root": task,
        "dockerfile_rel": "Dockerfile",
        "platform": "linux/arm64",
        "base_digest": "sha256:base",
        "force_build": True,
    }
    open_body = render_bake_body(_template(), "opencode")
    pi_body = render_bake_body(_template(), "pi")
    bake = plugin / "Dockerfile.bake"
    bake.write_text(open_body, encoding="utf-8")

    tag_open, _ = images.build_task_image(
        plugin_layers=(("acp", str(bake), str(plugin), open_body),),
        **kwargs,
    )
    tag_pi, _ = images.build_task_image(
        plugin_layers=(("acp", str(bake), str(plugin), pi_body),),
        **kwargs,
    )
    tag_open_again, _ = images.build_task_image(
        plugin_layers=(("acp", str(bake), str(plugin), open_body),),
        **kwargs,
    )

    assert tag_open != tag_pi
    assert tag_open == tag_open_again
    plugin_bodies = [text for tag, text in fake.builds if tag.endswith("-acp")]
    assert any("opencode-ai@1.18.12" in text for text in plugin_bodies)
    assert any("pi-acp@0.0.33" in text for text in plugin_bodies)
