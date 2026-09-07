"""Architecture gate: one ACP client package; private vendor modules deleted."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADAPTERS = REPO / "src" / "ageval" / "adapters"
ACP_PKG = REPO / "src" / "ageval" / "plugins" / "contrib" / "acp"


def _acp_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(ACP_PKG.glob("*.py")))


def test_single_acp_executor_package() -> None:
    assert ACP_PKG.is_dir()
    assert (ACP_PKG / "executor.py").is_file()
    assert not (ADAPTERS / "acp").exists()
    assert not (ADAPTERS / "acp_registry.py").is_file()
    assert not (ADAPTERS / "acp_entries.json").is_file()
    # No legacy monolith next to the package.
    assert not (ADAPTERS / "agent_acp.py").is_file()
    # No extra top-level agent_acp* modules.
    assert list(ADAPTERS.glob("agent_acp*.py")) == []


def test_private_vendor_modules_deleted() -> None:
    for name in (
        "agent_codex.py",
        "agent_pi.py",
        "agent_opencode.py",
        "agent_claude_code.py",
    ):
        assert not (ADAPTERS / name).is_file(), f"{name} must be deleted"


def test_acp_module_has_no_regex_json_scrape() -> None:
    src = _acp_sources()
    assert "_try_parse_structured" not in src
    assert "_extract_json_object" not in src
    assert "re.findall" not in src
    assert "re.search" not in src


def test_agent_acp_imports_typed_sdk() -> None:
    src = _acp_sources()
    assert "import acp" in src or "from acp" in src
    # At least one package module parses cleanly with imports present.
    for path in sorted(ACP_PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in tree.body):
            return
    raise AssertionError("ACP package has no import statements")


def test_acp_never_learns_how_the_box_is_built() -> None:
    """The pipe comes from attach_stdio, so no vendor handle can appear here.

    ``_PROBE_SOURCE`` is host.exec'd in-box (same family as acp-oneshot's
    worker). Parent ACP modules still must not spawn processes.
    """
    from ageval.plugins.contrib.acp.hooks import _PROBE_SOURCE

    src = _acp_sources()
    for forbidden in (
        "import docker",
        "import daytona",
        "container_id",
        "wrap_docker_exec",
    ):
        assert forbidden not in src, forbidden
    parent = src.replace(_PROBE_SOURCE, "")
    assert "subprocess.Popen" not in parent
    assert "subprocess.Popen" in _PROBE_SOURCE
    assert "attach_stdio" in src


def test_docker_image_does_not_install_python_acp_sdk() -> None:
    install = (REPO / "src/ageval/plugins/contrib/docker/attempt/install-executors.sh").read_text(
        encoding="utf-8"
    )
    assert "agent-client-protocol" not in install
    assert "pip install" not in install
