"""Public entrypoint: ageval executors lists ACP + openai-http."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run_ageval(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    cmd = [sys.executable, "-m", "ageval.cli.main", *args]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
    )


def test_executors_lists_supported_and_host_probe() -> None:
    result = _run_ageval("executors")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert set(data) >= {
        "supported",
        "host_ready",
        "missing_binary",
        "executors",
        "acp_entries",
    }
    assert "acp" in data["supported"]
    assert "openai-http" in data["supported"]
    assert "anthropic-http" in data["supported"]
    for gone in ("codex", "pi", "opencode", "claude-code"):
        assert gone not in data["supported"]

    by_kind = {r["kind"]: r for r in data["executors"]}
    http = by_kind["openai-http"]
    assert http["execution_mode"] == "api-client"
    assert http["host_ready"] is True
    anthropic = by_kind["anthropic-http"]
    assert anthropic["execution_mode"] == "api-client"
    assert anthropic["host_ready"] is True
    assert "sk-" not in result.stdout.lower()

    entry_ids = {r["entry_id"] for r in data["acp_entries"]}
    assert {"codex", "pi", "opencode", "claude-code", "grok-build"} <= entry_ids


def test_executors_verbose_adds_detail() -> None:
    result = _run_ageval("executors", "-v")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    by_kind = {r["kind"]: r for r in data["executors"]}
    assert by_kind["acp"].get("tools") is not None or data.get("acp_entries")
    acp_rows = {r["entry_id"]: r for r in data["acp_entries"]}
    assert "credential_env_names" in acp_rows["opencode"]
    assert "credential_missing" in acp_rows["pi"]
    assert "keyless_auth" in acp_rows["codex"]
    assert acp_rows["pi"]["source"] == "package"


def test_executors_lists_a_home_entry_and_a_bad_file_exits() -> None:
    home = Path(os.environ["AGEVAL_HOME"])
    (home / "acp-entries.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "kimi",
                        "integration_mode": 2,
                        "execution_mode": "acp-stdio",
                        "engine_detect_commands": ["kimi"],
                        "acp_command": ["kimi", "acp"],
                        "acp_detect_commands": ["kimi"],
                        "acp_package": "@moonshot-ai/kimi-code",
                        "acp_version": "1.2.3",
                        "install_command": "npm install -g @moonshot-ai/kimi-code@1.2.3",
                        "credential_env_names": ["KIMI_API_KEY"],
                        "model_binding": "config-option",
                        "platforms": ["darwin", "linux"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    listed = _run_ageval("executors")
    assert listed.returncode == 0, listed.stderr
    data = json.loads(listed.stdout)
    rows = {row["entry_id"]: row for row in data["acp_entries"]}
    assert rows["kimi"]["source"] == "user"
    assert rows["pi"]["source"] == "package"
    assert "/Users" not in listed.stdout
    (home / "acp-entries.json").write_text("{", encoding="utf-8")
    failed = _run_ageval("executors")
    assert failed.returncode != 0
    assert "Traceback" not in failed.stderr
    assert "acp_user_entries_unreadable" in failed.stderr
    assert "codex" not in failed.stdout
