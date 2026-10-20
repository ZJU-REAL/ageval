"""dsh / nooa talk only to the environment Protocol; Core has no second bind path."""

from __future__ import annotations

import re
from pathlib import Path

# Parent modules may name the SDK in a probe command string. They must not import it.
_OPENHANDS_SDK_IMPORT = re.compile(r"^\s*(?:import|from)\s+openhands(?:\.|\s)", re.MULTILINE)

REPO = Path(__file__).resolve().parents[2]
_PARENT_PY = (
    REPO / "plugins" / "dsh" / "src" / "dsh_plugin" / "factory.py",
    REPO / "plugins" / "dsh" / "src" / "dsh_plugin" / "container.py",
    REPO / "plugins" / "nooa" / "src" / "nooa_plugin" / "factory.py",
    REPO / "plugins" / "nooa" / "src" / "nooa_plugin" / "container.py",
    REPO / "plugins" / "acp-oneshot" / "src" / "acp_oneshot_plugin" / "factory.py",
    REPO / "plugins" / "acp-oneshot" / "src" / "acp_oneshot_plugin" / "container.py",
    REPO / "plugins" / "openhands" / "src" / "openhands_plugin" / "factory.py",
    REPO / "plugins" / "openhands" / "src" / "openhands_plugin" / "container.py",
)


def test_bind_to_target_absent_from_core_and_dsh_nooa() -> None:
    roots = (
        REPO / "src" / "ageval",
        REPO / "plugins" / "dsh",
        REPO / "plugins" / "nooa",
        REPO / "plugins" / "acp-oneshot",
        REPO / "plugins" / "openhands",
    )
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".yaml", ".yml", ".md"}:
                continue
            text = path.read_text(encoding="utf-8")
            if "bind_to_target" in text:
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_agent_binding_does_not_borrow_host_path() -> None:
    text = (REPO / "src" / "ageval" / "runtime" / "agent_binding.py").read_text(encoding="utf-8")
    assert "host_path" not in text


def test_dsh_nooa_parent_does_not_import_vendor_sdk() -> None:
    for path in _PARENT_PY:
        text = path.read_text(encoding="utf-8")
        assert "from deepseek_harness" not in text, path
        assert "import deepseek_harness" not in text, path
        assert "from nooa.unifiedllm" not in text, path
        assert "get_llm_client" not in text, path
        assert _OPENHANDS_SDK_IMPORT.search(text) is None, path
        assert "container_id" not in text, path
