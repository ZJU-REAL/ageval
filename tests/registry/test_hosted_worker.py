"""Hosted worker: profiles rewrite, child env, and queue transitions."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from services.registry.app import build_default_state
from services.registry.auth.tokens import TokenInfo
from services.registry.clock import now
from services.registry.hosted.prepare import HostedRunError, prepare_profiles
from services.registry.hosted.rows import JobRow
from services.registry.hosted.worker import (
    AgevalCliRunner,
    RunResult,
    drain_once,
)
from services.registry.packages.rows import ReleaseRow

from ageval.registry.archive import build_archive
from ageval.registry.media_types import DATASET_MEDIA_TYPE

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
_MASTER = base64.urlsafe_b64encode(b"m" * 32).decode("ascii")


class _Proc:
    def __init__(self, stdout: str, *, code: int = 0) -> None:
        self.returncode: int | None = None
        self._stdout = stdout
        self._code = code

    def poll(self) -> int:
        return self._code

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        del timeout
        self.returncode = self._code
        return self._stdout, ""


def _job(**over: object) -> JobRow:
    base: dict[str, Any] = dict(
        job_id="job1",
        org_id="acme",
        dataset_id="test/publish-min",
        version="0.1.0",
        environment="e2b",
        agent_ref="",
        model="gpt-4.1",
        model_secret_id="model",
        provider_secret_id="provider",
        max_concurrent_tasks=2,
        task_id="hello",
        status="queued",
        error_title="",
        error_message="",
        suite_run_id="",
        created_by="alice",
        created_at=1.0,
        started_at=None,
        finished_at=None,
        worker_id="",
        cancel_requested=False,
    )
    base.update(over)
    return JobRow(**base)  # type: ignore[arg-type]


def _profiles(root: Path) -> None:
    (root / "profiles.yaml").write_text(
        "\n".join(
            [
                "format: ageval.profiles/1",
                "environment: docker",
                "evaluate_host:",
                "  isolated: true",
                "agent_profiles:",
                "  '*':",
                "    executor: acp",
                "    model: {id: old-model}",
                "    api_key: ${OLD_KEY}",
                "    extensions:",
                "      - plugin: acp",
                "      - plugin: docker",
                "        options:",
                "          image: demo",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_prepare_rewrites_environment_and_keeps_secrets_out(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _profiles(dataset)
    job = _job()
    prepared = prepare_profiles(
        job,
        dataset,
        tmp_path / "profiles.yaml",
        model_locator="OPENAI_API_KEY",
        model_value="sk-live",
        provider_locator="E2B_API_KEY",
        provider_value="e2b-secret",
    )
    text = prepared.profiles_path.read_text(encoding="utf-8")
    assert "sk-live" not in text
    assert "e2b-secret" not in text
    loaded = yaml.safe_load(text)
    assert loaded["environment"] == "e2b"
    assert loaded["evaluate_host"]["isolated"] is True
    profile = loaded["agent_profiles"]["*"]
    assert profile["model"] == {"id": "gpt-4.1"}
    assert profile["api_key"] == "${OPENAI_API_KEY}"
    assert profile["extensions"] == [{"plugin": "acp"}, {"plugin": "e2b"}]
    with pytest.raises(HostedRunError) as refused:
        prepare_profiles(
            _job(environment="docker"),
            dataset,
            tmp_path / "nope.yaml",
            model_locator="OPENAI_API_KEY",
            model_value="sk-live",
            provider_locator="E2B_API_KEY",
            provider_value="e2b-secret",
        )
    assert refused.value.code == "hosted_environment_refused"
    assert not (tmp_path / "nope.yaml").exists()


def test_runner_env_has_one_provider_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _profiles(dataset)
    prepared = prepare_profiles(
        _job(task_id=""),
        dataset,
        tmp_path / "profiles.yaml",
        model_locator="OPENAI_API_KEY",
        model_value="sk-live",
        provider_locator="E2B_API_KEY",
        provider_value="e2b-secret",
    )
    monkeypatch.setenv("DAYTONA_API_KEY", "daytona-secret")
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", "reg-token")
    captured: dict[str, object] = {}

    def popen(argv: list[str], **kwargs: object) -> _Proc:
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return _Proc('{"suite_run_id":"from-json"}\n')

    result = AgevalCliRunner(popen=popen).run(prepared, should_cancel=lambda: False)
    argv = captured["argv"]
    env = captured["env"]
    assert isinstance(argv, list)
    assert isinstance(env, dict)
    assert result.suite_run_id == "from-json"
    assert env["E2B_API_KEY"] == "e2b-secret"
    assert env["OPENAI_API_KEY"] == "sk-live"
    assert "DAYTONA_API_KEY" not in env
    assert "AGEVAL_HOSTED_SECRET_KEY" not in env
    assert "AGEVAL_REGISTRY_TOKEN" not in env
    assert "--agent" not in argv
    assert "--model" not in argv
    assert "--json" in argv
    assert captured["cwd"] == str(tmp_path)
    assert "--result-file" in argv

    def noisy(argv: list[str], **kwargs: object) -> _Proc:
        del kwargs
        path = Path(argv[argv.index("--result-file") + 1])
        path.write_text('{"suite_run_id":"from-file"}\n', encoding="utf-8")
        return _Proc("log line\n{not json\n")

    noisy_result = AgevalCliRunner(popen=noisy).run(prepared, should_cancel=lambda: False)
    assert noisy_result.suite_run_id == "from-file"
    popped = False

    def refuse(argv: list[str], **kwargs: object) -> _Proc:
        del argv, kwargs
        nonlocal popped
        popped = True
        return _Proc("")

    with pytest.raises(HostedRunError) as refused:
        AgevalCliRunner(popen=refuse).run(
            replace(prepared, environment="docker"),
            should_cancel=lambda: False,
        )
    assert refused.value.code == "hosted_environment_refused"
    assert popped is False


def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGEVAL_HOSTED_SECRET_KEY", _MASTER)
    state, _token = build_default_state(tmp_path / "reg", memory_blob=True)
    state.stores.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    raw, digest, size = build_archive(FIXTURE)
    state.blobs.put_if_absent(digest, io.BytesIO(raw), prefix="packages")
    state.stores.packages.insert(
        ReleaseRow(
            dataset_id="test/publish-min",
            version="0.1.0",
            visibility="public",
            package_digest="sha256:" + "ab" * 32,
            blob_digest=digest,
            size=size,
            media_type=DATASET_MEDIA_TYPE,
            created_at=now(),
            org_id="acme",
            uploaded_by="alice",
        )
    )
    alice = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    state.hosted.create_secret(
        org_id="acme",
        name="openai",
        kind="model",
        value="sk-live",
        locator="OPENAI_API_KEY",
        provider="",
        auth=alice,
    )
    state.hosted.create_secret(
        org_id="acme",
        name="e2b",
        kind="provider",
        value="e2b-secret",
        locator="",
        provider="e2b",
        auth=alice,
    )
    state.hosted.create_secret(
        org_id="acme",
        name="daytona",
        kind="provider",
        value="daytona-secret",
        locator="",
        provider="daytona",
        auth=alice,
    )
    return state, alice


def _submit(state, alice: TokenInfo, *, environment: str = "e2b") -> str:
    secrets = {
        item["name"]: item for item in state.hosted.list_secrets(org_id="acme", auth=alice)["items"]
    }
    provider_name = environment
    job = state.hosted.create_job(
        org_id="acme",
        dataset_id="test/publish-min",
        version="0.1.0",
        environment=environment,
        model="gpt-4.1",
        model_secret_id=secrets["openai"]["secret_id"],
        provider_secret_id=secrets[provider_name]["secret_id"],
        agent_ref="",
        task_id="",
        max_concurrent_tasks=1,
        auth=alice,
    )
    return str(job["job_id"])


def test_drain_succeeds_and_cancel_and_scrubs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, alice = _state(tmp_path, monkeypatch)
    job_id = _submit(state, alice)
    uploaded: list[str] = []

    class Ok:
        def run(self, prepared, *, should_cancel):
            text = prepared.profiles_path.read_text(encoding="utf-8")
            assert prepared.environment == "e2b"
            assert "sk-live" not in text
            assert "e2b-secret" not in text
            assert "environment: e2b" in text or "environment: 'e2b'" in text
            assert should_cancel() is False
            return RunResult(exit_code=0, suite_run_id="suite-ok")

    assert drain_once(
        state,
        runner=Ok(),
        uploader=lambda job, dataset_root, suite_run_id: uploaded.append(suite_run_id),
    )
    done = state.stores.hosted.get_job(job_id)
    assert done is not None
    assert done.status == "succeeded"
    assert done.suite_run_id == "suite-ok"
    assert uploaded == ["suite-ok"]

    cancel_id = _submit(state, alice)

    class Cancel:
        def run(self, prepared, *, should_cancel):
            del prepared
            running = [
                row
                for row in state.stores.hosted.list_dataset_jobs("test/publish-min")
                if row.status == "running"
            ]
            assert len(running) == 1
            state.stores.hosted.mark_cancel_requested(running[0].job_id)
            assert should_cancel() is True
            return RunResult(exit_code=0, suite_run_id="suite-stop")

    stopped: list[str] = []
    assert drain_once(
        state,
        runner=Cancel(),
        uploader=lambda job, dataset_root, suite_run_id: stopped.append(suite_run_id),
    )
    canceled = state.stores.hosted.get_job(cancel_id)
    assert canceled is not None
    assert canceled.status == "canceled"
    assert canceled.suite_run_id == "suite-stop"
    assert stopped == ["suite-stop"]

    leak_id = _submit(state, alice)

    class Boom:
        def run(self, prepared, *, should_cancel):
            del prepared, should_cancel
            raise RuntimeError("boom sk-live")

    assert drain_once(
        state,
        runner=Boom(),
        uploader=lambda job, dataset_root, suite_run_id: None,
    )
    failed = state.stores.hosted.get_job(leak_id)
    assert failed is not None
    assert failed.status == "failed"
    assert "sk-live" not in failed.error_message
    assert "[redacted]" in failed.error_message


def test_exit_2_stays_failed_and_still_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, alice = _state(tmp_path, monkeypatch)
    job_id = _submit(state, alice, environment="daytona")
    uploaded: list[str] = []

    class Err:
        def run(self, prepared, *, should_cancel):
            del should_cancel
            assert prepared.environment == "daytona"
            text = prepared.profiles_path.read_text(encoding="utf-8")
            assert "daytona-secret" not in text
            return RunResult(exit_code=2, suite_run_id="suite-err", stderr="lock failed")

    assert drain_once(
        state,
        runner=Err(),
        uploader=lambda job, dataset_root, suite_run_id: uploaded.append(suite_run_id),
    )
    row = state.stores.hosted.get_job(job_id)
    assert row is not None
    assert row.status == "failed"
    assert row.suite_run_id == "suite-err"
    assert uploaded == ["suite-err"]


def test_hosted_sources_do_not_import_docker() -> None:
    root = REPO / "services" / "registry"
    for path in (root / "hosted").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import docker" not in text
        assert "import podman" not in text
        assert "docker.sock" not in text
    for rel in ("http/hosted.py", "app.py", "hosted/service.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "hosted.worker" not in text
        assert "ageval.application" not in text


def test_drain_real_uploader_lands_private_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default uploader path (no inject): suite is private and owned by submitter."""
    state, alice = _state(tmp_path, monkeypatch)
    job_id = _submit(state, alice)
    suite_id = "suite-hosted-upload"

    class WriteSuite:
        def run(self, prepared, *, should_cancel):
            del should_cancel
            suite_dir = prepared.dataset_root / ".ageval" / "suite-runs" / suite_id
            suite_dir.mkdir(parents=True, exist_ok=True)
            # No run_id on tasks → with_attempts finds nothing to pack, still hits upload_suite.
            summary = {
                "schema": "ageval.suite.summary/1",
                "suite_run_id": suite_id,
                "dataset_id": "test/publish-min",
                "dataset_version": "0.1.0",
                "exit_code": 0,
                "tasks": [
                    {
                        "task_id": "hello",
                        "status": "PASS",
                        "score": 1.0,
                        "n": 1,
                        "c": 1,
                    }
                ],
                "metrics": {
                    "pass_rate": 1.0,
                    "mean_score": 1.0,
                    "n_tasks": 1,
                    "n_pass": 1,
                    "n_fail": 0,
                    "n_error": 0,
                    "missing_score_as": 0.0,
                },
            }
            (suite_dir / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
            return RunResult(exit_code=0, suite_run_id=suite_id)

    assert drain_once(state, runner=WriteSuite())
    done = state.stores.hosted.get_job(job_id)
    assert done is not None
    assert done.status == "succeeded"
    assert done.suite_run_id == suite_id
    row = state.results.get_suite(suite_id)
    assert row is not None
    assert row.visibility == "private"
    assert row.uploaded_by == "alice"
    assert row.dataset_id == "test/publish-min"
