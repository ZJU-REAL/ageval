"""The lock names a credential locator; it never carries a value or a host path."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.config.capabilities import DeclarationCapabilityCatalog
from ageval.config.load_and_lock import ConfigCore
from ageval.config.model import thaw
from ageval.config.package_fs import LocalPackageReader
from ageval.config.profiles import parse_job_mapping

TASK_YAML = """format: ageval.task/1
task_id: t
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 10
  agent_invocations: 1
"""


def test_acp_lock_snapshot_is_safe(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-the-lock")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://10.0.0.1:8010/v1")
    task = tmp_path / "pkg"
    task.mkdir()
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (task / "run.py").write_text("async def run(ctx): pass\n", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(i): return {}\n", encoding="utf-8")

    lock = ConfigCore(package_reader=LocalPackageReader()).load_and_lock(
        task,
        "t",
        dataset_id="test/db",
        dataset_version="0.1.0",
        capabilities=DeclarationCapabilityCatalog(),
        job=parse_job_mapping(
            {
                "format": "ageval.profiles/1",
                "environment": "local",
                "agent_profiles": {
                    "solver": {
                        "executor": "acp",
                        "model": {"id": "entry-default"},
                        "api_key": "${OPENAI_API_KEY}",
                        "base_url": "${OPENAI_BASE_URL}",
                        "extensions": [
                            {"plugin": "acp", "options": {"entry": "codex"}},
                            {"plugin": "local"},
                        ],
                    }
                },
            }
        ),
    )

    (profile,) = thaw(lock.agent_profiles)
    assert profile["api_key"] == "OPENAI_API_KEY", "the locator name, not the value"
    assert profile["base_url"] == "OPENAI_BASE_URL", "the locator name, not the URL"
    payload = json.dumps({"profiles": thaw(lock.agent_profiles), "overlay": thaw(lock.job_overlay)})
    assert "sk-" not in payload
    assert "10.0.0.1" not in payload
    assert "/Users/" not in payload
    assert str(tmp_path) not in payload
