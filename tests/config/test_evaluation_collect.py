"""Lock stores evaluation.collect only when the list has rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.helpers.lock import job_document, lock_standalone

from ageval.config.errors import ConfigError
from ageval.config.model import locked_to_summary, thaw
from ageval.evidence.store import AttemptEvidenceStore

SOLVER = {
    "executor": "acp",
    "model": {"id": "entry-default"},
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
}

_HEAD = """format: ageval.task/1
task_id: collect
agent_profiles:
  - id: solver
evaluation:
"""


def _lock(root: Path, evaluation_body: str) -> Any:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.yaml").write_text(_HEAD + evaluation_body, encoding="utf-8")
    (root / "run.py").write_text("#\n", encoding="utf-8")
    (root / "evaluator.py").write_text("#\n", encoding="utf-8")
    return lock_standalone(root, "collect", job=job_document({"solver": dict(SOLVER)}))


def test_omit_and_empty_collect_add_no_resolved_key(tmp_path: Path) -> None:
    omitted = _lock(tmp_path / "omit", "  inputs: []\n")
    empty = _lock(tmp_path / "empty", "  collect: []\n")
    assert "evaluation_collect" not in thaw(omitted.resolved_references)
    assert "evaluation_collect" not in thaw(empty.resolved_references)
    assert omitted.digest != empty.digest


def test_collect_rows_keep_command_and_normalize_path(tmp_path: Path) -> None:
    locked = _lock(
        tmp_path / "rows",
        """  collect:
    - path: /tmp/agent.patch/
      service: main
      command: "git diff > /tmp/agent.patch"
      timeout_sec: 60
    - command: "curl -H 'Authorization: Bearer s3cr3t-token' http://localhost/finalize"
    - path: /tmp//pg.dump
      service: postgres-db
      command: "pg_dump -f /tmp/pg.dump"
      timeout_sec: 10.5
      exclude: ["*.log"]
""",
    )
    rows = thaw(locked.resolved_references)["evaluation_collect"]
    assert rows == [
        {
            "path": "/tmp/agent.patch",
            "service": "main",
            "command": "git diff > /tmp/agent.patch",
            "timeout_sec": 60,
        },
        {
            "command": "curl -H 'Authorization: Bearer s3cr3t-token' http://localhost/finalize",
        },
        {
            "path": "/tmp/pg.dump",
            "service": "postgres-db",
            "command": "pg_dump -f /tmp/pg.dump",
            "timeout_sec": 10.5,
            "exclude": ["*.log"],
        },
    ]
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    store.write_lock_summary(locked_to_summary(locked).as_dict())
    text = (store.root / "lock.json").read_text(encoding="utf-8")
    assert "s3cr3t-token" not in text
    assert "Bearer" not in text
    memory = json.dumps(thaw(locked.resolved_references))
    assert "s3cr3t-token" in memory


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("  collect: {}\n", "must be a list"),
        ("  collect:\n    - user: root\n      path: /tmp/x\n", "unknown evaluation.collect keys"),
        ("  collect:\n    - path: tmp/x\n", "absolute path"),
        ("  collect:\n    - path: /tmp/../etc/passwd\n", "without .."),
        ("  collect:\n    - command: '   '\n", "non-empty string"),
        ("  collect:\n    - path: /tmp/x\n      timeout_sec: 0\n", "positive number"),
        ("  collect:\n    - path: /tmp/x\n      timeout_sec: true\n", "positive number"),
        ("  collect:\n    - command: 'true'\n      exclude: ['*.log']\n", "exclude requires path"),
        ("  collect:\n    - path: /tmp/x\n      service: 'bad name'\n", "service must match"),
        ("  collect:\n    - {}\n", "requires path or command"),
    ],
)
def test_collect_schema_rejects_once(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _lock(tmp_path / "bad", body)
