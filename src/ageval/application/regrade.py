"""Regrade a finished Attempt from its harvested ``task-artifacts/``.

Mints a new Attempt, skips the agent run, and evaluates with the dataset's
current gold and evaluator. The source directory, including ``result.json``,
is only read.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ageval.application.phase_timing import timing_from_facts
from ageval.application.run import (
    _agent_environment_options,
    _agent_service,
    _bind_evaluate_session_target,
    _box_spec,
    _environment_options,
    _error_fact,
    _exit_code,
    _fact_detail,
    _open_evidence,
    _optional_dir,
    _selected_profile_id,
    _write_result,
)
from ageval.attempt import run_regrade
from ageval.attempt.artifact_harvest import regrade_harvest_gap
from ageval.attempt.ctx import AttemptCtx
from ageval.config.constants import ENVIRONMENT_DIR, EVALUATION_DIR, SEED_DIR
from ageval.config.errors import ConfigError
from ageval.config.model import locked_to_summary, thaw
from ageval.evaluation.bind import bind_result
from ageval.evaluation.error_record import error_record
from ageval.evidence.locators import resolve_attempt_run_dir
from ageval.evidence.store import AGENT_BOX_REL, TASK_ARTIFACTS_REL
from ageval.plugins.binding import bind_winner
from ageval.plugins.bootstrap import ensure_bootstrapped
from ageval.plugins.image_layers import layers_for_graph
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import ENVIRONMENT
from ageval.registry.resolve import resolve_dataset_root
from ageval.runtime.agent_binding import AgentBinder
from ageval.runtime.cancellation import CancellationSignal
from ageval.runtime.identity import IdentityFactory

_HARVEST_TITLE = "regrade_harvest_missing"


async def regrade_attempts(
    dataset: Path | str,
    run_ids: list[str],
    *,
    profiles_path: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
    keep_workspace: bool = False,
    keep_vendor_raw: bool = False,
    identity_factory: IdentityFactory | None = None,
) -> tuple[int, dict[str, Any]]:
    """Regrade each source attempt. One new Attempt per id. Exit follows the worst status."""
    ids = _dedupe_run_ids(run_ids)
    root = resolve_dataset_root(dataset)
    factory = identity_factory or IdentityFactory()
    rows: list[dict[str, Any]] = []
    for source_run_id in ids:
        rows.append(
            await _regrade_one(
                root,
                source_run_id,
                profiles_path=profiles_path,
                overrides=overrides,
                keep_workspace=keep_workspace,
                keep_vendor_raw=keep_vendor_raw,
                identity_factory=factory,
            )
        )
    return _batch_exit(rows), {"results": rows}


def _dedupe_run_ids(run_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in run_ids:
        text = str(raw).strip()
        if text and text not in seen:
            seen.append(text)
    if not seen:
        raise ConfigError(
            "regrade_run_required",
            "--run requires at least one attempt id",
            location="--run",
        )
    return seen


async def _regrade_one(
    dataset_root: Path,
    source_run_id: str,
    *,
    profiles_path: Path | str | None,
    overrides: dict[str, Any] | None,
    keep_workspace: bool,
    keep_vendor_raw: bool,
    identity_factory: IdentityFactory,
) -> dict[str, Any]:
    source = resolve_attempt_run_dir(dataset_root, source_run_id)
    task_id = _source_task_id(source)
    from ageval.application.composition import build_lock_command

    locked = build_lock_command().lock(
        dataset_root,
        task_id,
        profiles_path=profiles_path,
        overrides=overrides,
    )
    lock = locked.lock
    gap = regrade_harvest_gap(lock, source / TASK_ARTIFACTS_REL)
    if gap is not None:
        return _record_harvest_error(
            dataset_root=locked.resolved.dataset_root,
            lock=lock,
            source_run_id=source.name,
            task_id=task_id,
            reason=gap[0],
            missing=gap[1],
            identity_factory=identity_factory,
        )

    dataset_root = locked.resolved.dataset_root
    task_root = locked.resolved.task_dir
    run_ident = identity_factory.new_run()
    trial_ident = identity_factory.new_trial(run_ident, lock.digest)
    attempt_ident = identity_factory.new_attempt(trial_ident)
    evidence = _open_evidence(
        dataset_root=dataset_root,
        lock=lock,
        run_id=run_ident.value,
        attempt_id=attempt_ident.value,
    )
    evidence.write_lock_summary(locked.summary())
    _copy_task_artifacts(source, evidence.path(TASK_ARTIFACTS_REL))

    registry = ensure_bootstrapped()
    profile_id = _selected_profile_id(lock)
    services = ServiceTable()
    binder = AgentBinder(
        profiles=tuple(lock.agent_profiles),
        services=services,
        registry=registry,
        environment=lock.environment,
        environment_options=_environment_options(lock),
        requires=thaw(lock.requires),
        task_root=task_root,
    )
    graph = binder.graph(profile_id)
    agent_service = _agent_service(
        attempt_id=attempt_ident.value,
        binder=binder,
        lock=lock,
        evidence=evidence,
    )
    host = bind_winner(
        registry,
        graph,
        ENVIRONMENT,
        spec=_box_spec(
            lock,
            task_root=task_root,
            attempt_root=evidence.path(AGENT_BOX_REL),
        ),
        plugin_layers=layers_for_graph(graph),
        options=_agent_environment_options(lock, graph),
    )
    services.register(ENVIRONMENT, host, plugin_id=graph.winners[ENVIRONMENT].plugin_id)
    ctx = AttemptCtx(
        run_id=run_ident.value,
        trial_id=trial_ident.value,
        attempt_id=attempt_ident.value,
        lock=lock,
        profile_id=profile_id,
        bindings=graph,
        registry=registry,
        services=services,
        host=host,
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=task_root,
        dataset_root=dataset_root,
        seed_dir=_optional_dir(task_root, lock, "seed_dir", SEED_DIR),
        environment_src=_optional_dir(task_root, lock, "environment_dir", ENVIRONMENT_DIR),
        evaluation_src=_optional_dir(task_root, lock, "evaluation_dir", EVALUATION_DIR),
        agent_service=agent_service,
        keep_workspace=keep_workspace,
        keep_vendor_raw=keep_vendor_raw,
    )
    _bind_evaluate_session_target(ctx, agent_service)
    parent = agent_service.service
    parent.on_limit_reached = ctx.note_limit_reached
    parent.on_phase_clock = lambda frozen: (
        ctx.freeze_phase_clock() if frozen else ctx.thaw_phase_clock()
    )
    parent.record_stall_fact = ctx.record_fact
    parent.task_id = lock.task_id
    ctx.record_fact("regrade", {"source_run_id": source.name})

    try:
        await run_regrade(ctx)
    finally:
        agent_service.stop()

    result = bind_result(
        evaluator_raw=ctx.evaluation_result,
        kind=host.kind,
        capabilities_used=sorted(host.capabilities.names()),
        agent_invocations=len(evidence.list_invocations()),
        evidence_path=evidence.locator,
        cleanup_warning=_fact_detail(ctx, "cleanup_warning", "error"),
        error=_error_fact(ctx),
        limit=_fact_detail(ctx, "limit_reached", "name"),
        facts=tuple(ctx.facts_as_list()),
    )
    facts = ctx.facts_as_list()
    evidence.write_summary(
        {
            "result": result.as_dict(),
            "facts": facts,
            "phase_timing": timing_from_facts(facts),
            "keep_vendor_raw": ctx.keep_vendor_raw,
        }
    )
    _write_result(evidence, result)
    return _row(
        source_run_id=source.name,
        task_id=task_id,
        run_id=attempt_ident.value,
        status=result.status,
        score=result.score,
        evidence_path=result.evidence_path,
        logs=result.logs,
        error=dict(result.error) if result.error else None,
        exit_code=_exit_code(result),
    )


def _record_harvest_error(
    *,
    dataset_root: Path,
    lock: Any,
    source_run_id: str,
    task_id: str,
    reason: str,
    missing: tuple[str, ...],
    identity_factory: IdentityFactory,
) -> dict[str, Any]:
    """New Attempt, status ERROR. The evaluator does not run."""
    run_ident = identity_factory.new_run()
    trial_ident = identity_factory.new_trial(run_ident, lock.digest)
    attempt_ident = identity_factory.new_attempt(trial_ident)
    evidence = _open_evidence(
        dataset_root=dataset_root,
        lock=lock,
        run_id=run_ident.value,
        attempt_id=attempt_ident.value,
    )
    evidence.write_lock_summary(locked_to_summary(lock).as_dict())
    message = _harvest_message(reason, missing)
    recorded = error_record(phase="regrade", title=_HARVEST_TITLE, message=message)
    result = bind_result(
        evaluator_raw=None,
        kind=str(getattr(lock, "environment", "") or ""),
        evidence_path=evidence.locator,
        error=recorded,
        agent_invocations=0,
    )
    facts = [
        {
            "phase": "regrade",
            "name": _HARVEST_TITLE,
            "detail": {
                "source_run_id": source_run_id,
                "reason": reason,
                "missing": list(missing),
            },
        }
    ]
    evidence.write_summary({"result": result.as_dict(), "facts": facts, "phase_timing": {}})
    _write_result(evidence, result)
    return _row(
        source_run_id=source_run_id,
        task_id=task_id,
        run_id=attempt_ident.value,
        status=result.status,
        score=result.score,
        evidence_path=result.evidence_path,
        logs=result.logs,
        error=dict(result.error) if result.error else None,
        exit_code=_exit_code(result),
    )


def _harvest_message(reason: str, missing: tuple[str, ...]) -> str:
    if reason == "undeclared":
        return "task declares no artifacts.publishable; regrade scores the harvested snapshot only"
    listed = ", ".join(missing) if missing else "task-artifacts"
    return f"harvested task-artifacts are missing or insufficient: {listed}"


def _copy_task_artifacts(source_run: Path, dest: Path) -> None:
    src = source_run / TASK_ARTIFACTS_REL
    shutil.copytree(src, dest, symlinks=True)


def _source_task_id(run_dir: Path) -> str:
    lock_path = run_dir / "lock.json"
    if not lock_path.is_file():
        raise ConfigError(
            "regrade_source_invalid",
            "source attempt has no lock.json",
            location=str(lock_path),
        )
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(
            "regrade_source_invalid",
            "source lock.json is not JSON",
            location=str(lock_path),
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            "regrade_source_invalid",
            "source lock.json is not a JSON object",
            location=str(lock_path),
        )
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ConfigError(
            "regrade_source_invalid",
            "source lock.json has no task_id",
            location=str(lock_path),
        )
    return task_id.strip()


def _row(
    *,
    source_run_id: str,
    task_id: str,
    run_id: str,
    status: str,
    score: float | None,
    evidence_path: str,
    logs: str | None,
    error: dict[str, Any] | None,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "source_run_id": source_run_id,
        "task_id": task_id,
        "run_id": run_id,
        "status": status,
        "score": score,
        "evidence_path": evidence_path,
        "logs": logs or evidence_path,
        "error": error,
        "exit_code": exit_code,
    }


def _batch_exit(rows: list[dict[str, Any]]) -> int:
    statuses = [str(row.get("status") or "") for row in rows]
    if any(status == "ERROR" for status in statuses):
        return 2
    if any(status == "FAIL" for status in statuses):
        return 1
    return 0
