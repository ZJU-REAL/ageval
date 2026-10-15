"""TTY recap shapes hide digest/sha and keep a short table."""

from __future__ import annotations

from ageval.cli.present import humanize


def test_tasks_recap_lists_ids() -> None:
    text = humanize(
        {
            "dataset_id": "official/demo",
            "version": "0.1.0",
            "tasks": ["tau2-dialog-min", "terminal-jsonl-agg"],
            "count": 2,
        }
    )
    assert "official/demo@0.1.0" in text
    assert "tau2-dialog-min" in text
    assert "sha256" not in text
    assert "{" not in text


def test_lock_recap_omits_digest() -> None:
    text = humanize(
        {
            "dataset_id": "example/minimal-demo",
            "dataset_version": "0.1.3",
            "task_id": "terminal-jsonl-agg",
            "environment": "docker",
            "digest": "sha256:deadbeef",
            "format": "ageval.task/1",
            "job_overlay": {
                "agent_profiles": {
                    "solver": {
                        "executor": "acp",
                        "model": "zai-coding-cn/glm-5.2",
                        "options": {"entry": "pi"},
                    }
                }
            },
        }
    )
    assert "lock" in text
    assert "terminal-jsonl-agg" in text
    assert "docker" in text
    assert "pi" in text
    assert "sha256" not in text
    assert "deadbeef" not in text


def test_plugin_list_omits_digest() -> None:
    text = humanize(
        {
            "ok": True,
            "plugins": [
                {
                    "plugin_id": "official/dsh",
                    "version": "0.1.0",
                    "digest": "sha256:aaa",
                    "path": "official/dsh/0.1.0",
                    "description": "DeepSeek Harness in the box.",
                }
            ],
        }
    )
    assert "official/dsh" in text
    assert "0.1.0" in text
    assert "DeepSeek Harness in the box." in text
    assert "sha256" not in text


def test_plugin_description_ellipsis_fits_width() -> None:
    long_desc = "Run NVIDIA OO Agents inside the box via environment exec and upload. Not ACP."
    text = humanize(
        {
            "ok": True,
            "plugins": [
                {
                    "plugin_id": "official/nooa",
                    "version": "0.1.0",
                    "description": long_desc,
                }
            ],
        },
        width=42,
    )
    row = next(ln for ln in text.splitlines() if "official/nooa" in ln)
    assert len(row) <= 42
    assert row.endswith("...")
    assert long_desc not in text


def test_executors_ready_table() -> None:
    text = humanize(
        {
            "supported": ["acp", "openai-http"],
            "host_ready": ["openai-http"],
            "missing_binary": [],
            "executors": [
                {"kind": "acp", "host_ready": True},
                {"kind": "openai-http", "host_ready": True},
            ],
            "acp_entries": [
                {"entry_id": "pi", "host_ready": True},
                {"entry_id": "codex", "host_ready": False},
            ],
        }
    )
    assert "executors" in text
    assert "pi" in text
    assert "ready" in text
    assert "missing" in text
    assert "sha256" not in text


def test_executors_human_marks_user_entries() -> None:
    text = humanize(
        {
            "supported": ["acp"],
            "host_ready": [],
            "missing_binary": [],
            "executors": [{"kind": "acp", "host_ready": False}],
            "acp_entries": [
                {"entry_id": "kimi", "host_ready": False, "source": "user"},
                {"entry_id": "pi", "host_ready": True, "source": "package"},
            ],
        }
    )
    for line in text.splitlines():
        if "kimi" in line:
            assert "user" in line
        if line.strip().startswith("pi"):
            assert "user" not in line


def test_publish_and_suite_upload_skip_blob_digest() -> None:
    pub = humanize(
        {
            "ok": True,
            "dataset_id": "official/demo",
            "version": "0.1.0",
            "visibility": "public",
            "ref": "official/demo@0.1.0",
            "package_digest": "sha256:abc",
            "blob_digest": "sha256:def",
            "digest_ref": "official/demo@sha256:abc",
            "org_id": "official",
        }
    )
    assert "official/demo@0.1.0" in pub
    assert "public" in pub
    assert "sha256" not in pub
    up = humanize(
        {
            "ok": True,
            "suite_run_id": "ca096a6f",
            "dataset_id": "official/demo",
            "dataset_version": "0.1.0",
            "pass_rate": 1.0,
            "visibility": "public",
            "blob_digest": "sha256:zzz",
            "attempts_total": 2,
            "attempts_uploaded": 2,
        }
    )
    assert "uploaded" in up
    assert "ca096a6f" in up
    assert "sha256" not in up
