"""Public ``ageval run`` use case: mint identity, build the ctx, run the Attempt.

This module assembles one Attempt and maps its outcome to an exit code. It owns
no orchestration: the phase order lives in ``ageval.attempt``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.application.phase_timing import timing_from_facts
from ageval.attempt import run_attempt as run_attempt_pipeline
from ageval.attempt.ctx import AttemptCtx, PhaseObserver
from ageval.attempt.recover import (
    bind_sentinels,
    capture_box,
    classify_environment,
    find_unsealed_attempt,
    load_activity,
    new_nonce,
    partial_output,
    write_attempt_header,
)
from ageval.config.constants import (
    ENVIRONMENT_DIR,
    EVALUATION_DIR,
    SEED_DIR,
)
from ageval.config.model import LockedTaskConfig, thaw
from ageval.config.resources import resource_options
from ageval.environments.protocol import BoxSpec
from ageval.evaluation.bind import AttemptResult, bind_result
from ageval.evidence.checkpoints import prune_recovery_bundle, prune_recovery_state
from ageval.evidence.locators import default_runs_root
from ageval.evidence.store import (
    ACTIVITY_LOG_REL,
    AGENT_BOX_REL,
    AttemptEvidenceStore,
)
from ageval.evidence.trajectory import TRAJECTORY_FILENAME
from ageval.plugins.binding import bind_winner
from ageval.plugins.bootstrap import ensure_bootstrapped
from ageval.plugins.image_layers import layers_for_graph
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import ENVIRONMENT
from ageval.runtime.agent_binding import AgentBinder
from ageval.runtime.agent_service_protocol import AgentServiceServer
from ageval.runtime.cancellation import CancellationSignal
from ageval.runtime.identity import IdentityFactory
from ageval.runtime.parent_agent import ParentAgentService, resolve_invoke_timeout_seconds

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


async def probe_attempt(
    dataset: Path | str,
    task: str,
    *,
    profile: str | None = None,
    profiles_path: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
    layout: str = "ageval",
) -> dict[str, Any]:
    """Lock and preflight without opening a box or invoking an Agent.

    Answers "would this run here?" — the lock resolves, the winning box says
    whether it could open, and nothing is started either way.
    """
    from ageval.application.composition import build_lock_command

    locked = build_lock_command().lock(
        dataset,
        task,
        profile=profile,
        profiles_path=profiles_path,
        overrides=overrides,
        layout=layout,
    )
    lock = locked.lock
    registry = ensure_bootstrapped()
    binder = AgentBinder(
        profiles=tuple(lock.agent_profiles),
        services=ServiceTable(),
        registry=registry,
        environment=lock.environment,
        environment_options=_environment_options(lock),
        requires=thaw(lock.requires),
        task_root=locked.resolved.task_dir,
    )
    graph = binder.graph(_selected_profile_id(lock))
    host = bind_winner(
        registry,
        graph,
        ENVIRONMENT,
        spec=_box_spec(
            lock,
            task_root=locked.resolved.task_dir,
            attempt_root=Path(tempfile.mkdtemp(prefix="ageval-probe-")),
        ),
        plugin_layers=layers_for_graph(graph),
    )
    probe: dict[str, Any] = {
        "task_id": lock.task_id,
        "digest": lock.digest,
        "environment": lock.environment,
        "capabilities": sorted(host.capabilities.names()),
        "started": False,
    }
    try:
        await host.preflight()
    except Exception as exc:  # noqa: BLE001 — the reason is the answer
        probe["ready"] = False
        probe["error"] = f"{type(exc).__name__}: {exc}"
        return probe
    if _http_credentials_missing(lock):
        probe["ready"] = False
        probe["error"] = "credential_missing"
        return probe
    probe["ready"] = True
    return probe


async def run_attempt(
    dataset: Path | str,
    task: str,
    *,
    profile: str | None = None,
    profiles_path: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
    keep_workspace: bool = False,
    keep_recovery_state: bool = False,
    keep_vendor_raw: bool = False,
    force_build: bool = False,
    identity_factory: IdentityFactory | None = None,
    on_phase: PhaseObserver | None = None,
    on_progress: Any = None,
    attempt_index: int = 0,
    allow_prepare: bool = False,
    layout: str = "ageval",
    resume_attempt_id: str | None = None,
    suite_run_id: str | None = None,
    recover_unsealed: bool = False,
    fork: Any = None,
) -> tuple[int, AttemptResult]:
    """Run one foreground Attempt and return its exit code and result."""
    from ageval.application.composition import build_lock_command
    from ageval.application.fork import (
        ForkRejection,
        model_override,
        prepare_fork,
        solver_role_from_source,
    )

    if fork is not None and (resume_attempt_id or recover_unsealed or suite_run_id):
        return _refused_plain(
            kind="",
            evidence_path="",
            title="fork_resume_exclusive",
            message="--fork cannot be combined with --resume",
        )
    fork_overrides = dict(overrides or {})
    if fork is not None:
        try:
            role = solver_role_from_source(
                Path(dataset),
                fork.source_attempt_id,
                fork.checkpoint_seq,
            )
        except ForkRejection as exc:
            return _refused_plain(
                kind="",
                evidence_path="",
                title=exc.error_code,
                message=exc.message,
            )
        fork_overrides.update(model_override(role, fork.model))

    # Lock and preflight run before AttemptCtx exists; notify the observer
    # directly so the live label covers the whole Attempt, not just the phases.
    if on_phase is not None:
        on_phase("started", "lock")
    locked = build_lock_command().lock(
        dataset,
        task,
        profile=profile,
        profiles_path=profiles_path,
        overrides=fork_overrides or None,
        force_build=force_build,
        allow_prepare=allow_prepare,
        layout=layout,
    )
    if on_phase is not None:
        on_phase("finished", "lock")
    lock = locked.lock
    dataset_root = locked.resolved.dataset_root
    task_root = locked.resolved.task_dir
    fork_plan = None
    if fork is not None:
        try:
            fork_plan = prepare_fork(dataset_root, fork, child_lock=locked.summary())
        except ForkRejection as exc:
            return _refused_plain(
                kind=str(lock.environment),
                evidence_path="",
                title=exc.error_code,
                message=exc.message,
            )

    factory = identity_factory or IdentityFactory()
    resumed = _locate_resume(
        dataset_root,
        lock_digest=lock.digest,
        task_id=lock.task_id,
        attempt_index=attempt_index,
        resume_attempt_id=resume_attempt_id,
        suite_run_id=suite_run_id,
        recover_unsealed=recover_unsealed,
    )
    if resumed.refused is not None:
        return resumed.refused
    if resumed.header is not None:
        payload = resumed.header.payload
        run_id = str(payload["run_id"])
        trial_id = str(payload["trial_id"])
        attempt_id = str(payload["attempt_id"])
    elif resumed.attempt_id:
        run_id = resumed.attempt_id
        trial_id = resumed.attempt_id
        attempt_id = resumed.attempt_id
    else:
        run_ident = factory.new_run()
        trial_ident = factory.new_trial(run_ident, lock.digest)
        attempt_ident = factory.new_attempt(trial_ident)
        run_id = run_ident.value
        trial_id = trial_ident.value
        attempt_id = attempt_ident.value

    evidence = _open_evidence(
        dataset_root=dataset_root,
        lock=lock,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    if resumed.activity is not None:
        evidence.sync_invocation_counters()
    if not (evidence.root / "lock.json").is_file():
        evidence.write_lock_summary(locked.summary())
    if fork_plan is not None:
        from ageval.application.fork import copy_fork_prefix

        activity = copy_fork_prefix(
            fork_plan.source_dir,
            evidence.root,
            seq=fork_plan.checkpoint_seq,
            run_id=run_id,
            trial_id=trial_id,
            attempt_id=attempt_id,
            digest=lock.digest,
        )
    else:
        activity = resumed.activity or _open_fresh_activity(
            evidence,
            lock=lock,
            run_id=run_id,
            trial_id=trial_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            suite_run_id=suite_run_id,
        )
    if resumed.activity is not None:
        bind_sentinels(activity, evidence.sentinels)
    if activity.corrupt:
        return _seal_recovery_error(
            evidence,
            kind=str(lock.environment),
            phase="run",
            title="activity_log_corrupt",
            message=activity.corrupt,
        )

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
    # The service comes up first so the box can carry its socket in.
    # Each phase arms its own clock; nothing is charged before environment.
    agent_service = _agent_service(
        attempt_id=attempt_id,
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
    if on_phase is not None:
        on_phase("started", "preflight")
    await host.preflight()
    if on_phase is not None:
        on_phase("finished", "preflight")

    ctx = AttemptCtx(
        run_id=run_id,
        trial_id=trial_id,
        attempt_id=attempt_id,
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
        on_phase=on_phase,
        activity=activity,
        fork_checkpoint_seq=None if fork_plan is None else fork_plan.checkpoint_seq,
        fork_provenance=None
        if fork_plan is None
        else fork_plan.provenance(child_digest=lock.digest, verified=True),
    )
    _bind_evaluate_session_target(ctx, agent_service)
    parent = agent_service.service
    parent.activity = activity
    parent.elapsed_ms_provider = ctx.active_elapsed_ms
    parent.checkpoint_capture = lambda seq: capture_box(ctx, seq)
    parent.read_partial = lambda: partial_output(ctx)
    if fork_plan is None and parent.invoke_quota is not None and resumed.activity is not None:
        parent.invoke_quota.restore_used(activity.admitted_run_invoke_count())
    if fork_plan is None and resumed.activity is not None:
        decision = await classify_environment(ctx)
        parent.environment_reattached = bool(ctx.recovery_attached)
        if decision == "busy":
            agent_service.stop()
            return _refused_result(
                evidence,
                kind=str(lock.environment),
                title="attempt_still_busy",
                message="the environment is still running this Attempt",
            )
    parent.on_limit_reached = ctx.note_limit_reached
    parent.on_phase_clock = lambda frozen: (
        ctx.freeze_phase_clock() if frozen else ctx.thaw_phase_clock()
    )
    parent.record_stall_fact = ctx.record_fact
    parent.on_phase = on_phase
    parent.on_progress = on_progress
    parent.task_id = lock.task_id
    parent.attempt_index = attempt_index

    try:
        await run_attempt_pipeline(ctx)
    finally:
        # The run phase stops it too; this is the guarantee for earlier failures.
        agent_service.stop()

    fork_doc = ctx.fork_provenance if isinstance(ctx.fork_provenance, dict) else None
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
        fork=fork_doc,
    )
    facts = ctx.facts_as_list()
    summary: dict[str, Any] = {
        "result": result.as_dict(),
        "facts": facts,
        "phase_timing": timing_from_facts(facts),
        "keep_vendor_raw": ctx.keep_vendor_raw,
    }
    extra = ctx.summary_extra
    if extra:
        summary["extra"] = extra
    if fork_doc:
        summary["fork"] = fork_doc
    evidence.write_summary(summary)
    _write_result(evidence, result)
    _prune_settled_recovery(
        evidence.root,
        keep_workspace=keep_workspace,
        keep_recovery_state=keep_recovery_state,
    )
    return _exit_code(result), result


def _prune_settled_recovery(
    attempt_dir: Path,
    *,
    keep_workspace: bool,
    keep_recovery_state: bool,
) -> None:
    """Drop recovery files only after the display archive is sealed.

    Interrupted Attempts keep ``activity.jsonl`` and ``checkpoints/`` so
    ``--resume`` works without ``--keep-recovery-state``. ``state/`` is
    environment probe state and follows ``--keep-workspace``.
    """
    settled = (attempt_dir / TRAJECTORY_FILENAME).is_file() and (
        attempt_dir / "result.json"
    ).is_file()
    if not settled:
        return
    if not keep_recovery_state:
        prune_recovery_bundle(attempt_dir)
    if not keep_workspace:
        prune_recovery_state(attempt_dir)


@dataclass
class _ResumePlan:
    activity: Any = None
    header: Any = None
    attempt_id: str | None = None
    refused: tuple[int, AttemptResult] | None = None


def _locate_resume(
    dataset_root: Path,
    *,
    lock_digest: str,
    task_id: str,
    attempt_index: int,
    resume_attempt_id: str | None,
    suite_run_id: str | None,
    recover_unsealed: bool,
) -> _ResumePlan:
    if resume_attempt_id:
        attempt_dir = default_runs_root(dataset_root) / resume_attempt_id
        if not attempt_dir.is_dir():
            return _ResumePlan(
                refused=_refused_plain(
                    kind="local",
                    evidence_path=f".ageval/runs/{resume_attempt_id}",
                    title="activity_log_missing",
                    message=f"no Attempt directory {resume_attempt_id}",
                )
            )
        if (attempt_dir / "result.json").is_file():
            return _ResumePlan(
                refused=_refused_plain(
                    kind="local",
                    evidence_path=f".ageval/runs/{resume_attempt_id}",
                    title="attempt_already_settled",
                    message="result.json already exists",
                )
            )
        activity = load_activity(attempt_dir)
        header = activity.header()
        if header is None and not activity.corrupt:
            return _ResumePlan(
                refused=_refused_plain(
                    kind="local",
                    evidence_path=f".ageval/runs/{resume_attempt_id}",
                    title="activity_log_missing",
                    message="activity.jsonl has no attempt header",
                )
            )
        if header is not None and header.payload.get("locked_config_digest") != lock_digest:
            return _ResumePlan(
                refused=_refused_plain(
                    kind=str(header.payload.get("environment_kind") or "local"),
                    evidence_path=f".ageval/runs/{resume_attempt_id}",
                    title="locked_config_mismatch",
                    message="locked_config_digest does not match this resume",
                )
            )
        if header is not None and header.payload.get("task_id") not in {None, task_id}:
            return _ResumePlan(
                refused=_refused_plain(
                    kind=str(header.payload.get("environment_kind") or "local"),
                    evidence_path=f".ageval/runs/{resume_attempt_id}",
                    title="activity_log_missing",
                    message="Attempt task_id does not match --task",
                )
            )
        return _ResumePlan(activity=activity, header=header, attempt_id=resume_attempt_id)
    if recover_unsealed and suite_run_id:
        found = find_unsealed_attempt(
            dataset_root,
            suite_run_id=suite_run_id,
            task_id=task_id,
            attempt_index=attempt_index,
            digest=lock_digest,
        )
        if found is None:
            return _ResumePlan()
        activity = load_activity(found)
        return _ResumePlan(activity=activity, header=activity.header(), attempt_id=found.name)
    return _ResumePlan()


def _open_fresh_activity(
    evidence: AttemptEvidenceStore,
    *,
    lock: LockedTaskConfig,
    run_id: str,
    trial_id: str,
    attempt_id: str,
    attempt_index: int,
    suite_run_id: str | None,
) -> Any:
    from ageval.evidence.activity import ActivityLog

    log = ActivityLog.open(evidence.root / ACTIVITY_LOG_REL, sentinels=tuple(evidence.sentinels))
    if log.header() is None and not log.corrupt:
        write_attempt_header(
            log,
            run_id=run_id,
            trial_id=trial_id,
            attempt_id=attempt_id,
            task_id=lock.task_id,
            attempt_index=attempt_index,
            suite_run_id=suite_run_id,
            digest=lock.digest,
            environment_kind=str(lock.environment),
            nonce=new_nonce(),
        )
    return log


def _refused_plain(
    *,
    kind: str,
    evidence_path: str,
    title: str,
    message: str,
) -> tuple[int, AttemptResult]:
    from ageval.evaluation.error_record import error_record

    result = bind_result(
        evaluator_raw=None,
        kind=kind,
        evidence_path=evidence_path,
        error=error_record(phase="run", title=title, message=message),
    )
    return EXIT_ERROR, result


def _refused_result(
    evidence: AttemptEvidenceStore,
    *,
    kind: str,
    title: str,
    message: str,
) -> tuple[int, AttemptResult]:
    return _refused_plain(
        kind=kind,
        evidence_path=evidence.locator,
        title=title,
        message=message,
    )


def _seal_recovery_error(
    evidence: AttemptEvidenceStore,
    *,
    kind: str,
    phase: str,
    title: str,
    message: str,
) -> tuple[int, AttemptResult]:
    from ageval.evaluation.error_record import error_record

    result = bind_result(
        evaluator_raw=None,
        kind=kind,
        evidence_path=evidence.locator,
        error=error_record(phase=phase, title=title, message=message),
    )
    evidence.write_summary({"result": result.as_dict(), "facts": []})
    _write_result(evidence, result)
    return EXIT_ERROR, result


def _open_evidence(
    *,
    dataset_root: Path,
    lock: LockedTaskConfig,
    run_id: str,
    attempt_id: str,
) -> AttemptEvidenceStore:
    runs_root = default_runs_root(dataset_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    return AttemptEvidenceStore(
        root=runs_root / attempt_id,
        attempt_id=attempt_id,
        run_id=run_id,
        dataset_root=dataset_root,
    )


def _http_credentials_missing(lock: LockedTaskConfig) -> bool:
    """True when an HTTP executor needs a key and the locked base_url is not loopback."""
    from ageval.config.env_refs import resolve_locked_base_url
    from ageval.config.errors import ConfigError
    from ageval.plugins.executor_capabilities import get_capabilities
    from ageval.plugins.http_loopback import HTTP_EXECUTORS, http_key_present, is_http_loopback

    for row in lock.agent_profiles:
        executor = str(row.get("executor") or "").strip()
        if executor not in HTTP_EXECUTORS:
            continue
        raw = row.get("base_url")
        try:
            base = resolve_locked_base_url(raw if isinstance(raw, str) else None)
        except ConfigError:
            base = None
        if is_http_loopback(base):
            continue
        names: list[str] = []
        locator = row.get("api_key")
        if isinstance(locator, str) and locator.strip():
            names.append(locator.strip())
        caps = get_capabilities(executor)
        if caps is not None:
            for name in caps.credential_env_names:
                if name not in names:
                    names.append(name)
        if names and not http_key_present(names):
            return True
    return False


def _selected_profile_id(lock: LockedTaskConfig) -> str:
    """The role slot this Attempt runs, or "" for a task with no Agent at all.

    Extra roles open on demand, per session.
    """
    rows = list(lock.agent_profiles)
    if not rows:
        return ""
    active = thaw(lock.parameters).get("active_profile")
    if isinstance(active, str) and active.strip():
        return active.strip()
    return str(rows[0].get("id"))


def _environment_options(lock: LockedTaskConfig) -> dict[str, Any]:
    """Job options the box kind reads (never the executor's own options)."""
    overlay = thaw(lock.job_overlay) if lock.job_overlay is not None else {}
    options = overlay.get("environment_options")
    return dict(options) if isinstance(options, dict) else {}


def _agent_environment_options(lock: LockedTaskConfig, graph: ExtensionGraph) -> dict[str, Any]:
    """Winner options plus derived egress allowlist (hostnames only)."""
    winner = graph.winners.get(ENVIRONMENT)
    options = dict(winner.options or {}) if winner is not None else _environment_options(lock)
    if str(options.get("egress") or "") == "llm":
        options["egress_allowlist"] = _egress_allowlist(lock)
    if lock.environment == "docker":
        options.update(resource_options(thaw(lock.parameters), scoring=False))
    _merge_attempt_declarations(options, thaw(lock.parameters))
    return options


def _merge_attempt_declarations(
    options: MutableMapping[str, Any], parameters: Mapping[str, Any]
) -> None:
    """Copy task network, caps, and main env onto the agent box options.

    A key already set on the job ``environment_options`` wins. ``options`` is
    the in-memory start dict. It is not written back onto the lock.
    """
    mode = parameters.get("network_mode")
    if "network_mode" not in options and isinstance(mode, str) and mode.strip():
        options["network_mode"] = mode.strip()
    caps = parameters.get("cap_add")
    if "cap_add" not in options and isinstance(caps, str) and caps.strip():
        options["cap_add"] = [caps.strip()]
    elif "cap_add" not in options and isinstance(caps, list | tuple) and caps:
        options["cap_add"] = list(caps)
    env = parameters.get("main_environment")
    if "main_environment" not in options and isinstance(env, dict) and env:
        options["main_environment"] = dict(env)
    elif "main_environment" not in options and isinstance(env, list | tuple) and env:
        options["main_environment"] = list(env)
    if parameters.get("package_layout") == "harbor":
        _apply_harbor_box_options(options, parameters)


def _apply_harbor_box_options(
    options: MutableMapping[str, Any], parameters: Mapping[str, Any]
) -> None:
    """Harbor policy knobs the docker kind already understands. Job options win."""
    if parameters.get("harbor_network") == "no-network" and "network" not in options:
        options["network"] = "none"
    user = parameters.get("harbor_user")
    if "user" not in options and isinstance(user, str) and user.strip():
        options["user"] = user.strip()
    image = parameters.get("docker_image")
    if "docker_image" not in options and isinstance(image, str) and image.strip():
        options["docker_image"] = image.strip()
    if parameters.get("align_app") is True:
        options["align_app"] = True
    if parameters.get("drop_compose_main") is True:
        options["drop_compose_main"] = True
    workdir = parameters.get("harbor_workdir")
    if (
        "workdir" not in options
        and isinstance(workdir, str)
        and workdir.strip()
        and workdir.strip() != "/app"
    ):
        options["workdir"] = workdir.strip()
    env = options.get("main_environment")
    if isinstance(env, dict) and env:
        from ageval.config.harbor_layout import expand_harbor_env

        options["main_environment"] = expand_harbor_env({str(k): str(v) for k, v in env.items()})


def _egress_allowlist(lock: LockedTaskConfig) -> list[str]:
    from urllib.parse import urlparse

    from ageval.config.env_refs import resolve_locked_base_url
    from ageval.config.errors import ConfigError
    from ageval.config.profiles import authored_egress_hosts

    hosts: list[str] = []
    for row in lock.agent_profiles:
        raw = row.get("base_url")
        try:
            url = resolve_locked_base_url(raw if isinstance(raw, str) else None)
        except ConfigError:
            continue
        if not url:
            continue
        host = urlparse(str(url)).hostname
        if host:
            hosts.append(host)
    hosts.extend(authored_egress_hosts(_environment_options(lock)))
    return sorted(set(hosts))


def _box_spec(
    lock: LockedTaskConfig,
    *,
    task_root: Path,
    attempt_root: Path,
) -> BoxSpec:
    """Engine context for the box: the work root plus whatever recipe shipped."""
    references = thaw(lock.resolved_references)
    context = references.get("environment_build_context")
    return BoxSpec(
        attempt_root=attempt_root,
        task_root=task_root,
        repo_root=Path.cwd(),
        dockerfile=references.get("environment_dockerfile"),
        compose_file=references.get("environment_compose"),
        build_context=context if isinstance(context, str) and context.strip() else None,
    )


def _bind_evaluate_session_target(ctx: AttemptCtx, agent_service: AgentServiceServer) -> None:
    """Let evaluate-phase session(environment=) rebind ACP onto a named host."""
    parent = getattr(agent_service, "service", None)
    if parent is None:
        return
    from ageval.attempt.phases.evaluate import bind_named_environment, named_evaluate_environments

    names = frozenset(named_evaluate_environments(ctx))
    parent.evaluate_environment_names = names if names else None
    if not names:
        return
    parent.evaluate_environment_binder = lambda name, profile_id=None: bind_named_environment(
        ctx, name, profile_id=profile_id
    )


def _agent_service(
    *,
    attempt_id: str,
    binder: AgentBinder,
    lock: LockedTaskConfig,
    evidence: AttemptEvidenceStore,
) -> AgentServiceServer:
    """Start the parent Agent Service the worker will call back into."""
    limits = thaw(lock.limits)
    parameters = thaw(lock.parameters)
    service = ParentAgentService(
        attempt_id=attempt_id,
        binder=binder,
        agent_invocation_limit=int(limits["agent_invocations"]),
        agent_concurrency=int(limits["agent_concurrency"]),
        evidence_store=evidence,
        invoke_timeout_seconds=resolve_invoke_timeout_seconds(parameters),
    )
    # Short path: a Unix socket name has ~100 usable bytes, evidence roots do not.
    socket_dir = Path(tempfile.mkdtemp(prefix="ageval-"))
    server = AgentServiceServer(service, socket_dir / "agent.sock")
    server.start()
    return server


def _optional_dir(task_root: Path, lock: LockedTaskConfig, ref: str, fallback: str) -> Path | None:
    refs = thaw(lock.resolved_references)
    rel = refs.get(ref) or fallback
    candidate = task_root / str(rel)
    return candidate if candidate.is_dir() else None


def _error_fact(ctx: AttemptCtx) -> dict[str, Any] | None:
    """The phase_failed object, or None when the Attempt was judged."""
    for fact in reversed(ctx.phase_facts):
        if fact.name != "phase_failed":
            continue
        detail = fact.detail
        title = detail.get("title")
        if not isinstance(title, str) or not title:
            return None
        phase = detail.get("phase")
        message = detail.get("message")
        return {
            "phase": phase if isinstance(phase, str) else None,
            "title": title,
            "message": message if isinstance(message, str) else "",
        }
    return None


def _fact_detail(ctx: AttemptCtx, name: str, key: str) -> str | None:
    """Last recorded value of one fact detail, for the result document."""
    for fact in reversed(ctx.phase_facts):
        if fact.name == name:
            value = fact.detail.get(key)
            return str(value) if value else None
    return None


def _write_result(evidence: AttemptEvidenceStore, result: AttemptResult) -> None:
    from ageval.evidence.attempt_record import write_attempt_result

    write_attempt_result(evidence.root, result.as_dict())


def _exit_code(result: AttemptResult) -> int:
    if result.status == "PASS":
        return EXIT_PASS
    if result.status == "FAIL":
        return EXIT_FAIL
    return EXIT_ERROR
