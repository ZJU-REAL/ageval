"""Resume reads a fixture activity log. No live process is killed."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ageval.application.composition import build_lock_command
from ageval.application.run import run_attempt
from ageval.attempt.recover import write_attempt_header
from ageval.evidence.activity import ActivityLog
from ageval.evidence.locators import default_runs_root

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "examples" / "datasets" / "minimal-demo"
TASK = "tau2-dialog-min"
ATTEMPT_ID = "attempt_fixture"


def _dataset(tmp_path: Path) -> tuple[Path, Path]:
    dataset = Path(
        shutil.copytree(DEMO, tmp_path / "minimal-demo", ignore=shutil.ignore_patterns(".ageval"))
    )
    profiles = dataset / "profiles.local.yaml"
    profiles.write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: local",
                "agent_profiles:",
                "  user:",
                "    executor: openai-http",
                "    model: {id: mock}",
                "    base_url: http://127.0.0.1:9/v1",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                "      - plugin: local",
                "  service:",
                "    executor: openai-http",
                "    model: {id: mock}",
                "    base_url: http://127.0.0.1:9/v1",
                "    api_key: ${OPENAI_API_KEY}",
                "    extensions:",
                "      - plugin: openai-http",
                "      - plugin: local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return dataset, profiles


def _corrupt_activity(dataset: Path, digest: str) -> Path:
    attempt = default_runs_root(dataset) / ATTEMPT_ID
    attempt.mkdir(parents=True)
    log = ActivityLog.open(attempt / "activity.jsonl")
    write_attempt_header(
        log,
        run_id="run_fixture",
        trial_id="trial_fixture",
        attempt_id=ATTEMPT_ID,
        task_id=TASK,
        attempt_index=0,
        suite_run_id=None,
        digest=digest,
        environment_kind="local",
        nonce="nce_fixture",
    )
    log.append(
        request_id="phase_environment",
        kind="phase",
        status="in_flight",
        payload={"phase": "environment"},
    )
    log.append(
        request_id="phase_environment",
        kind="phase",
        status="completed",
        payload={
            "phase": "environment",
            "elapsed_ms": 1.0,
            "limit_reached": None,
            "checkpoint_seq": None,
        },
    )
    lines = (attempt / "activity.jsonl").read_text(encoding="utf-8").splitlines()
    lines[1] = "{not-json"
    (attempt / "activity.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return attempt


def test_corrupt_activity_seals_once(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "ci-loopback-placeholder")
    dataset, profiles = _dataset(tmp_path)
    locked = build_lock_command().lock(dataset, TASK, profiles_path=profiles)
    attempt = _corrupt_activity(dataset, locked.lock.digest)

    code, result = asyncio.run(
        run_attempt(dataset, TASK, profiles_path=profiles, resume_attempt_id=ATTEMPT_ID)
    )
    assert code == 2
    assert result.error is not None
    assert result.error["title"] == "activity_log_corrupt"
    sealed = (attempt / "result.json").read_bytes()

    again, settled = asyncio.run(
        run_attempt(dataset, TASK, profiles_path=profiles, resume_attempt_id=ATTEMPT_ID)
    )
    assert again == 2
    assert settled.error is not None
    assert settled.error["title"] == "attempt_already_settled"
    assert (attempt / "result.json").read_bytes() == sealed
