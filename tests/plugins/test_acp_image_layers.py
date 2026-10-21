"""ACP plugin image_layers: bound entry body, content key, no model."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ageval.plugins.contrib.acp.bake import NODE_GATE_MARKER, node_gate_script, render_bake_body
from ageval.plugins.contrib.acp.hooks import _needed_commands
from ageval.plugins.contrib.acp.registry import get_entry, list_entry_ids
from ageval.plugins.contrib.docker import images
from ageval.plugins.contrib.docker.images import content_digest
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
    assert NODE_GATE_MARKER in text
    assert "command -v npm" not in text


def test_render_opencode_bakes_pinned_detect_commands() -> None:
    desc = get_entry("opencode")
    assert desc is not None
    body = render_bake_body(_template(), "opencode")
    assert "opencode-ai@1.18.12" in body
    assert '"name":"opencode","package":"opencode-ai"' in body
    assert "command -v opencode" not in body
    detect = [line for line in body.splitlines() if "node -e" in line]
    assert len(detect) == 1
    assert detect[0].startswith("RUN node -e ")
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
    assert '"name":"pi","package":"@earendil-works/pi-coding-agent"' in pi
    assert '"name":"pi-acp","package":"pi-acp"' in pi
    assert "command -v pi" not in pi
    assert "command -v pi-acp" not in pi
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
            assert f'"name":"{name}","package":' in body
            assert f"command -v {name}" not in body
        assert "__ACP_ENTRY_PACKAGES__" not in body
        assert "__ACP_DETECT_BINARIES__" not in body
        assert NODE_GATE_MARKER not in body
        assert "command -v npm" not in body
        assert desc.runtime.node_spec().removeprefix(">=") in body
        assert "setup_${install_major}.x" in body
        assert "npm- nodejs-dev- nodejs-doc- nodejs-legacy- libnode-dev-" in body
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


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


_NODE_STUB = """#!/bin/sh
IFS= read -r line < "$NODE_VERSION_FILE"
printf '%s\\n' "$line"
"""

_APT_STUB = """#!/bin/sh
printf '%s\\n' "apt-get $*" >> "$GATE_LOG"
if [ "$1" = "install" ]; then
  shift
  for arg in "$@"; do
    if [ "$arg" = "nodejs" ] && [ -n "${NODE_AFTER:-}" ]; then
      printf '%s\\n' "$NODE_AFTER" > "$NODE_VERSION_FILE"
      if [ ! -e "$NODE_BIN" ]; then
        /bin/cp "$NODE_STUB_SRC" "$NODE_BIN"
        /bin/chmod +x "$NODE_BIN"
      fi
    fi
  done
fi
exit 0
"""


def _run_node_gate(
    tmp_path: Path,
    *,
    entry_id: str,
    floor: tuple[int, int, int],
    node: str | None,
    apt: bool = False,
    after: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the bake gate with PATH limited to stubs.

    ``rm`` is always a stub. The production script's apt-list cleanup must not
    reach the host ``rm``.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    version = tmp_path / "node-version"
    node_bin = bindir / "node"
    stub_src = tmp_path / "node-stub.sh"
    _write_exec(stub_src, _NODE_STUB)
    _write_exec(bindir / "rm", "#!/bin/sh\nprintf 'rm\\n' >> \"$GATE_LOG\"\nexit 0\n")
    _write_exec(bindir / "curl", "#!/bin/sh\nprintf 'curl\\n' >> \"$GATE_LOG\"\nexit 0\n")
    _write_exec(bindir / "bash", "#!/bin/sh\nprintf 'bash\\n' >> \"$GATE_LOG\"\nexit 0\n")
    if node is not None:
        version.write_text(node + "\n", encoding="utf-8")
        _write_exec(node_bin, _NODE_STUB)
    if apt:
        _write_exec(bindir / "apt-get", _APT_STUB)
    env = {
        "PATH": str(bindir),
        "GATE_LOG": str(tmp_path / "gate.log"),
        "NODE_VERSION_FILE": str(version),
        "NODE_BIN": str(node_bin),
        "NODE_STUB_SRC": str(stub_src),
    }
    if after is not None:
        env["NODE_AFTER"] = after
    return subprocess.run(
        ["/bin/sh", "-c", node_gate_script(entry_id, floor)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _gate_log(tmp_path: Path) -> str:
    log = tmp_path / "gate.log"
    if not log.is_file():
        return ""
    return log.read_text(encoding="utf-8")


def test_pi_bake_embeds_the_node_gate_and_a_stable_content_key(tmp_path: Path) -> None:
    first = render_bake_body(_template(), "pi")
    second = render_bake_body(_template(), "pi")
    assert first == second
    gate = node_gate_script("pi", (22, 19, 0))
    assert gate in first
    digest_kwargs = {
        "context_root": tmp_path,
        "platform": "linux/arm64",
        "base_digest": "sha256:base",
    }
    assert content_digest(recipe=first, **digest_kwargs) == content_digest(
        recipe=second, **digest_kwargs
    )
    proc = _run_node_gate(tmp_path, entry_id="pi", floor=(22, 19, 0), node="v22.19.0")
    assert proc.returncode == 0, proc.stderr
    assert "apt-get" not in _gate_log(tmp_path)
    assert "rm" not in _gate_log(tmp_path)


def test_node_already_above_floor_is_left_alone(tmp_path: Path) -> None:
    proc = _run_node_gate(tmp_path, entry_id="opencode", floor=(18, 0, 0), node="v18.19.1")
    assert proc.returncode == 0, proc.stderr
    assert _gate_log(tmp_path) == ""


@pytest.mark.parametrize(
    ("node", "apt", "after", "code", "apt_called", "stderr_has"),
    [
        ("v22.23.4", False, None, 0, False, ""),
        ("v18.19.1", False, None, 1, False, "acp entry pi requires node >=22.19.0; found v18.19.1"),
        ("v18.19.1", True, "v22.23.4", 0, True, ""),
        ("v18.19.1", True, None, 1, True, "found v18.19.1"),
        (None, True, "v22.23.4", 0, True, ""),
    ],
)
def test_pi_node_gate_installs_or_fails_closed(
    tmp_path: Path,
    node: str | None,
    apt: bool,
    after: str | None,
    code: int,
    apt_called: bool,
    stderr_has: str,
) -> None:
    proc = _run_node_gate(
        tmp_path,
        entry_id="pi",
        floor=(22, 19, 0),
        node=node,
        apt=apt,
        after=after,
    )
    assert proc.returncode == code, proc.stderr
    assert ("apt-get" in _gate_log(tmp_path)) is apt_called
    if stderr_has:
        assert stderr_has in proc.stderr
        assert proc.stderr.count("\n") == 1


def test_floor_above_the_installer_fails_before_apt(tmp_path: Path) -> None:
    proc = _run_node_gate(
        tmp_path,
        entry_id="pi",
        floor=(24, 0, 0),
        node="v18.19.1",
        apt=True,
        after="v22.23.4",
    )
    assert proc.returncode == 1
    assert (
        proc.stderr.strip()
        == "acp entry pi requires node >=24.0.0; found v18.19.1; bake installs node 22.x only"
    )
    assert "apt-get" not in _gate_log(tmp_path)
