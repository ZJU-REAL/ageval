"""Pull hosted jobs and run them on e2b or daytona.

``python -m services.registry.hosted.worker``

The API process does not import this module. Sandbox credentials stay in this
process. The child ``ageval run`` receives one provider key and the model locator.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from services.registry.clock import now
from services.registry.errors import RegistryAppError
from services.registry.hosted import crypto
from services.registry.hosted.prepare import HostedRunError, PreparedRun, prepare_profiles
from services.registry.hosted.rows import HOSTED_ENVIRONMENTS, JobRow
from services.registry.hosted.upload import upload_hosted_suite

_DENY_ENV = frozenset(
    {
        "AGEVAL_HOSTED_SECRET_KEY",
        "AGEVAL_REGISTRY_TOKEN",
        "AGEVAL_REGISTRY_BOOTSTRAP_TOKEN",
        "AGEVAL_REGISTRY_S3_SECRET_KEY",
        "AGEVAL_GITHUB_CLIENT_SECRET",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "E2B_API_KEY",
        "e2b_api_key",
        "DAYTONA_API_KEY",
        "daytona_api_key",
    }
)


class RunResult:
    """One ``ageval run`` outcome. ``suite_run_id`` may be empty."""

    def __init__(
        self,
        *,
        exit_code: int,
        suite_run_id: str = "",
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.suite_run_id = suite_run_id
        self.stdout = stdout
        self.stderr = stderr


class SuiteRunner(Protocol):
    def run(self, prepared: PreparedRun, *, should_cancel: Callable[[], bool]) -> RunResult: ...


class SuiteUploader(Protocol):
    def __call__(self, job: JobRow, dataset_root: Path, suite_run_id: str) -> None: ...


def child_environ(
    *,
    provider_locator: str,
    provider_value: str,
    model_locator: str,
    model_value: str,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Parent env for ``ageval run``. One provider key, one model locator."""
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if key not in _DENY_ENV}
    env[provider_locator] = provider_value
    env[model_locator] = model_value
    return env


def suite_id_from_result_file(path: Path) -> str:
    """Read ``suite_run_id`` from the JSON document ``--result-file`` writes."""
    if not path.is_file():
        return ""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if isinstance(obj, dict) and isinstance(obj.get("suite_run_id"), str):
        return obj["suite_run_id"]
    return ""


def parse_suite_run_id(stdout: str) -> str:
    """Last JSON object in stdout that carries ``suite_run_id``."""
    text = stdout or ""
    found = ""
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("suite_run_id"), str):
            found = obj["suite_run_id"]
        index = start + max(end, 1)


def discover_suite_run_id(dataset_root: Path) -> str:
    root = dataset_root / ".ageval" / "suite-runs"
    if not root.is_dir():
        return ""
    best = ""
    best_mtime = -1.0
    for child in root.iterdir():
        summary = child / "summary.json"
        if not summary.is_file():
            continue
        mtime = summary.stat().st_mtime
        if mtime >= best_mtime:
            best_mtime = mtime
            best = child.name
    return best


def signal_suite_cancel(dataset_root: Path) -> None:
    from ageval.application.suite.suite_run import request_suite_cancel

    root = dataset_root / ".ageval" / "suite-runs"
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            request_suite_cancel(dataset_root, child.name)


class AgevalCliRunner:
    """Spawn ``python -m ageval.cli.main run``. Tests inject ``popen``."""

    def __init__(self, popen: Any = subprocess.Popen) -> None:
        self._popen = popen

    def run(self, prepared: PreparedRun, *, should_cancel: Callable[[], bool]) -> RunResult:
        if prepared.environment not in HOSTED_ENVIRONMENTS:
            raise HostedRunError(
                "hosted_environment_refused",
                "hosted jobs accept only e2b or daytona",
            )
        text = prepared.profiles_path.read_text(encoding="utf-8")
        for secret in (prepared.model_value, prepared.provider_value):
            if secret and secret in text:
                raise HostedRunError(
                    "hosted_secret_leak",
                    "profiles file contains a secret value",
                )
        argv = [
            sys.executable,
            "-m",
            "ageval.cli.main",
            "run",
            str(prepared.dataset_root),
            "--profiles",
            str(prepared.profiles_path),
            "--max-concurrent-tasks",
            str(prepared.max_concurrent_tasks),
            "--json",
            "--result-file",
            str(prepared.work_dir / "ageval-result.json"),
        ]
        if prepared.task_id:
            argv.extend(["--task", prepared.task_id])
        env = child_environ(
            provider_locator=prepared.provider_locator,
            provider_value=prepared.provider_value,
            model_locator=prepared.model_locator,
            model_value=prepared.model_value,
        )
        proc = self._popen(
            argv,
            cwd=str(prepared.work_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                if should_cancel():
                    signal_suite_cancel(prepared.dataset_root)
                stop.wait(0.25)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        try:
            stdout, stderr = proc.communicate()
        finally:
            stop.set()
            thread.join(timeout=1)
        exit_code = int(proc.returncode if proc.returncode is not None else 2)
        suite_run_id = (
            suite_id_from_result_file(prepared.work_dir / "ageval-result.json")
            or parse_suite_run_id(stdout or "")
            or discover_suite_run_id(prepared.dataset_root)
        )
        return RunResult(
            exit_code=exit_code,
            suite_run_id=suite_run_id,
            stdout=stdout or "",
            stderr=stderr or "",
        )


def drain_once(
    state: Any,
    *,
    runner: SuiteRunner,
    uploader: SuiteUploader | None = None,
    stale_seconds: int = 0,
) -> bool:
    """Claim and finish at most one job. Return whether a job was claimed."""
    _reclaim_stale(state, stale_seconds)
    worker_id = secrets.token_hex(16)
    job = state.stores.hosted.claim_next(worker_id=worker_id)
    if job is None:
        return False
    secrets_seen: list[str] = []
    try:
        _execute(state, job, runner=runner, uploader=uploader, secrets_seen=secrets_seen)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        _mark_failed(state, job, exc, secrets_seen)
    return True


def _reclaim_stale(state: Any, stale_seconds: int) -> None:
    if stale_seconds <= 0:
        return
    before = now() - stale_seconds
    state.stores.hosted.cancel_stale(before, finished_at=now())
    state.stores.hosted.requeue_stale(before)


def _execute(
    state: Any,
    job: JobRow,
    *,
    runner: SuiteRunner,
    uploader: SuiteUploader | None,
    secrets_seen: list[str],
) -> None:
    work = Path(tempfile.mkdtemp(prefix="ageval-hosted-"))
    keep = os.environ.get("AGEVAL_HOSTED_KEEP_WORK") == "1"
    try:
        dataset_root = work / "dataset"
        _materialize(state, job, dataset_root)
        model_locator, model_value, provider_locator, provider_value = _open_secrets(
            state, job, secrets_seen
        )
        prepared = prepare_profiles(
            job,
            dataset_root,
            work / "profiles.yaml",
            model_locator=model_locator,
            model_value=model_value,
            provider_locator=provider_locator,
            provider_value=provider_value,
        )
        result = runner.run(
            prepared,
            should_cancel=lambda: _cancel_requested(state, job.job_id),
        )
        _settle(state, job, dataset_root, result, uploader, secrets_seen)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _settle(
    state: Any,
    job: JobRow,
    dataset_root: Path,
    result: RunResult,
    uploader: SuiteUploader | None,
    secrets_seen: list[str],
) -> None:
    canceled = _cancel_requested(state, job.job_id)
    suite_run_id = result.suite_run_id
    upload_error = ""
    if suite_run_id:
        try:
            if uploader is None:
                upload_hosted_suite(state, job, dataset_root, suite_run_id)
            else:
                uploader(job, dataset_root, suite_run_id)
        except Exception as exc:
            upload_error = crypto.scrub(str(exc), secrets_seen)
    if canceled:
        status = "canceled"
        title = "hosted_upload_failed" if upload_error else ""
        message = upload_error
    elif result.exit_code in {0, 1} and suite_run_id and not upload_error:
        status = "succeeded"
        title = ""
        message = ""
    else:
        status = "failed"
        if not suite_run_id:
            title = "hosted_suite_missing"
            message = crypto.scrub(_run_text(result), secrets_seen)
        elif upload_error and result.exit_code in {0, 1}:
            title = "hosted_upload_failed"
            message = upload_error
        else:
            title = "hosted_run_failed"
            message = crypto.scrub(_run_text(result), secrets_seen)
            if upload_error:
                message = crypto.scrub(f"{message}\n{upload_error}", secrets_seen)
    state.stores.hosted.finish_job(
        job.job_id,
        status=status,
        error_title=title,
        error_message=message,
        suite_run_id=suite_run_id,
        finished_at=now(),
    )


def _run_text(result: RunResult) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text or f"exit {result.exit_code}"


def _mark_failed(state: Any, job: JobRow, exc: BaseException, secrets_seen: list[str]) -> None:
    if isinstance(exc, HostedRunError):
        title = exc.code
        message = exc.message
    elif isinstance(exc, RegistryAppError):
        title = exc.error
        message = exc.message
    else:
        title = "hosted_run_failed"
        message = str(exc)
    state.stores.hosted.finish_job(
        job.job_id,
        status="failed",
        error_title=title,
        error_message=crypto.scrub(message, secrets_seen),
        suite_run_id="",
        finished_at=now(),
    )


def _cancel_requested(state: Any, job_id: str) -> bool:
    fresh = state.stores.hosted.get_job(job_id)
    return bool(fresh and fresh.cancel_requested)


def _materialize(state: Any, job: JobRow, dest: Path) -> None:
    from services.registry.content.blob_io import read_blob

    from ageval.registry.archive import extract_archive

    if job.version == "draft":
        draft = state.stores.packages.get_draft(job.dataset_id)
        if draft is None:
            raise HostedRunError("not_found", "dataset draft missing")
        blob_digest = draft.blob_digest
    else:
        release = state.stores.packages.get_by_version(job.dataset_id, job.version)
        if release is None:
            raise HostedRunError("not_found", "dataset release missing")
        blob_digest = release.blob_digest
    payload = read_blob(state.blobs, blob_digest, prefix="packages")
    if payload is None:
        raise HostedRunError("not_found", "dataset blob missing")
    extract_archive(payload, dest)


def _open_secrets(state: Any, job: JobRow, secrets_seen: list[str]) -> tuple[str, str, str, str]:
    model = state.stores.hosted.get_secret(job.model_secret_id)
    provider = state.stores.hosted.get_secret(job.provider_secret_id)
    if model is None or model.org_id != job.org_id or model.kind != "model":
        raise HostedRunError("not_found", "model secret missing")
    if (
        provider is None
        or provider.org_id != job.org_id
        or provider.kind != "provider"
        or provider.provider != job.environment
    ):
        raise HostedRunError("not_found", "provider secret missing")
    try:
        model_value = crypto.decrypt(model.ciphertext)
        provider_value = crypto.decrypt(provider.ciphertext)
    except RegistryAppError as exc:
        raise HostedRunError(exc.error, exc.message) from exc
    secrets_seen.extend([model_value, provider_value])
    return model.locator, model_value, provider.locator, provider_value


def _poll_seconds() -> float:
    raw = os.environ.get("AGEVAL_HOSTED_POLL_SECONDS", "2").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"AGEVAL_HOSTED_POLL_SECONDS is not a number: {raw}") from exc
    if value < 0:
        raise SystemExit("AGEVAL_HOSTED_POLL_SECONDS must be >= 0")
    return value


def _stale_seconds() -> int:
    raw = os.environ.get("AGEVAL_HOSTED_STALE_SECONDS", "0").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"AGEVAL_HOSTED_STALE_SECONDS is not an integer: {raw}") from exc
    if value < 0:
        raise SystemExit("AGEVAL_HOSTED_STALE_SECONDS must be >= 0")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ageval hosted job worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job, then exit")
    parser.add_argument(
        "--local",
        action="store_true",
        help="SQLite + filesystem blobs (dev). Does not mint a bootstrap token.",
    )
    args = parser.parse_args(argv)
    from services.registry.app import build_state_from_env

    state, _token = build_state_from_env(force_local=args.local, mint_bootstrap=False)
    runner = AgevalCliRunner()
    stale = _stale_seconds()
    pause = _poll_seconds()
    while True:
        claimed = drain_once(state, runner=runner, stale_seconds=stale)
        if args.once:
            return 0
        if not claimed:
            time.sleep(pause)


if __name__ == "__main__":
    raise SystemExit(main())
