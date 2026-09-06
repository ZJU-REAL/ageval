"""evaluate phase: writers stop, gold arrives, evaluator decides.

Gold isolation here is a cut in *time*, not a mount trick: ``evaluation/`` is
uploaded at the start of this phase, so nothing the Agent could read ever had it
on disk. Isolated evaluate adds a cut in *space*: gold lands only on the second
Host. The verdict enters the Attempt exactly once, via ``bind_evaluation``.
The ``evaluation_runtime`` winner returns raw; it does not bind PASS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.emit import emit
from ageval.config.errors import ConfigError
from ageval.config.model import thaw
from ageval.environments.protocol import (
    ARTIFACTS_PATH,
    EVALUATION_PATH,
    WORKSPACE_PATH,
    BoxSpec,
    EnvironmentProvider,
)
from ageval.evidence.store import EVALUATE_BOX_REL, TASK_ARTIFACTS_REL, evaluate_box_rel
from ageval.plugins.binding import bind_winner
from ageval.plugins.slots import AFTER_EVALUATE, BEFORE_EVALUATE, ENVIRONMENT, EVALUATION_RUNTIME

PHASE = "evaluate"
UNKNOWN_EVALUATE_ENVIRONMENT = "unknown_evaluate_environment"


async def run(ctx: AttemptCtx) -> None:
    ctx.phase = PHASE
    ctx.assert_writers_stopped()  # solver writers; Agent Service may still be up
    await emit(ctx, BEFORE_EVALUATE)
    if named_evaluate_environments(ctx):
        # Named hosts start on first exec / session(environment=), not here.
        pass
    else:
        await _ensure_evaluate_host(ctx)
        await _prepare_evaluate_runtime(ctx)
        await _materialize_on_host(ctx, ctx.scoring_host)
    impl = bind_winner(ctx.registry, ctx.bindings, EVALUATION_RUNTIME)
    plugin_id = ctx.bindings.winners[EVALUATION_RUNTIME].plugin_id
    ctx.services.register(EVALUATION_RUNTIME, impl, plugin_id=plugin_id)
    result = await impl.evaluate(ctx)
    ctx.bind_evaluation(result)
    # Post-processing may annotate metrics; it may not change the verdict.
    status_before = str((result or {}).get("status") or "")
    after = await emit(ctx, AFTER_EVALUATE, result)
    if isinstance(after, dict) and str(after.get("status") or "") != status_before:
        raise RuntimeError("after_evaluate must not change the evaluation status")


def named_evaluate_environments(ctx: AttemptCtx) -> dict[str, dict[str, str]]:
    lock = getattr(ctx, "lock", None)
    refs = thaw(getattr(lock, "resolved_references", None) or {})
    raw = refs.get("evaluation_environments") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for name, recipe in raw.items():
        if isinstance(name, str) and isinstance(recipe, dict):
            out[name] = {str(key): str(value) for key, value in recipe.items()}
    return out


async def ensure_named_host(ctx: AttemptCtx, name: str) -> EnvironmentProvider:
    """Start one named scoring host on first use. Unknown names do not start."""
    recipes = named_evaluate_environments(ctx)
    if name not in recipes:
        raise RuntimeError(UNKNOWN_EVALUATE_ENVIRONMENT)
    host = ctx.evaluate_hosts.get(name)
    if host is None:
        host = _bind_named_scoring_host(ctx, name)
        if host is None:
            raise RuntimeError(UNKNOWN_EVALUATE_ENVIRONMENT)
        ctx.evaluate_hosts[name] = host
    if name in ctx.started_evaluate_names:
        return host
    await host.preflight()
    await host.start(force_build=ctx.lock.force_build)
    ctx.started_evaluate_names.add(name)
    ctx.record_fact(
        "evaluate_host_started",
        {"name": name, "kind": getattr(host, "kind", "")},
    )
    await _materialize_on_host(ctx, host, name=name)
    return host


async def bind_named_environment(
    ctx: AttemptCtx,
    name: str,
    profile_id: str | None = None,
) -> EnvironmentProvider:
    """Point the environment service at a named host for ACP attach_stdio."""
    host = await ensure_named_host(ctx, name)
    winner = ctx.bindings.winners.get(ENVIRONMENT)
    plugin_id = winner.plugin_id if winner is not None else getattr(host, "kind", "environment")
    ctx.services.register(ENVIRONMENT, host, plugin_id=plugin_id)
    await _prepare_named_runtime(ctx, name, profile_id=profile_id)
    return host


async def _ensure_evaluate_host(ctx: AttemptCtx) -> None:
    host = ctx.evaluate_host
    if host is None:
        # The scoring box binds here, not at composition: which profiles belong
        # to the evaluate phase is only known once run has sealed.
        host = _bind_singular_scoring_host(ctx)
        if host is None:
            return
        ctx.evaluate_host = host
    if host is ctx.host:
        return
    await host.preflight()
    await host.start(force_build=ctx.lock.force_build)
    ctx.record_fact("evaluate_host_started", {"kind": getattr(host, "kind", "")})
    winner = ctx.bindings.winners.get(ENVIRONMENT)
    plugin_id = winner.plugin_id if winner is not None else getattr(host, "kind", "environment")
    ctx.services.register(ENVIRONMENT, host, plugin_id=plugin_id)


# --- scoring-box bind (evaluate-phase graphs) -------------------------------


def _evaluate_phase_profile_ids(ctx: AttemptCtx) -> list[str]:
    """Profiles not sealed by run: the roles evaluate may still open."""
    parent = getattr(ctx.agent_service, "service", None) or ctx.agent_service
    sealed = {str(item) for item in (getattr(parent, "_run_profile_ids", None) or ())}
    ids: list[str] = []
    for row in thaw(getattr(ctx.lock, "agent_profiles", None) or ()):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if pid and pid not in sealed:
            ids.append(pid)
    return ids


def _scoring_binder(ctx: AttemptCtx) -> Any:
    parent = getattr(ctx.agent_service, "service", None) or ctx.agent_service
    return getattr(parent, "binder", None)


def _scoring_plugin_layers(ctx: AttemptCtx) -> tuple[tuple[str, str, str, str], ...]:
    """Union image_layers over evaluate-phase profile graphs (solver excluded)."""
    from ageval.plugins.image_layers import layers_for_graphs

    binder = _scoring_binder(ctx)
    if binder is None:
        return ()
    graphs = [binder.graph(pid) for pid in _evaluate_phase_profile_ids(ctx)]
    return layers_for_graphs(graphs)


def _scoring_egress_allowlist(ctx: AttemptCtx, options: dict[str, Any]) -> list[str]:
    """Evaluate-phase profile hosts ∪ this box's ``egress_allow``; never agent extras."""
    from urllib.parse import urlparse

    from ageval.config.env_refs import resolve_locked_base_url
    from ageval.config.profiles import authored_egress_hosts

    sealed = set(_evaluate_phase_profile_ids(ctx))
    hosts: list[str] = []
    for row in thaw(getattr(ctx.lock, "agent_profiles", None) or ()):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if not pid or pid not in sealed:
            continue
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
    hosts.extend(authored_egress_hosts(options))
    return sorted(set(hosts))


def _scoring_environment_options(
    ctx: AttemptCtx, recipe: dict[str, str] | None = None
) -> dict[str, Any]:
    """Two boxes, two option maps.

    Declared ``evaluate_host.environment_options`` wins whole. Omitted, the
    scoring box keeps today's non-inheritance: only ``platform`` / ``user`` /
    ``python_version`` from the job map, never the agent ``egress`` /
    ``egress_allow`` / ``network`` or image.
    """
    overlay = thaw(getattr(ctx.lock, "job_overlay", None) or {})
    host = overlay.get("evaluate_host") if isinstance(overlay.get("evaluate_host"), dict) else {}
    nested = host.get("environment_options")
    if isinstance(nested, dict) and nested:
        options: dict[str, Any] = dict(nested)
    else:
        job_options = overlay.get("environment_options")
        options = {
            key: value
            for key, value in (job_options.items() if isinstance(job_options, dict) else [])
            if key in {"platform", "user", "python_version"}
        }
    image = (recipe or {}).get("docker_image")
    if not (isinstance(image, str) and image.strip()):
        refs = thaw(getattr(ctx.lock, "resolved_references", None) or {})
        image = refs.get("evaluation_docker_image")
    if isinstance(image, str) and image.strip():
        options["image"] = image.strip()
    if str(options.get("egress") or "") == "llm":
        options["egress_allowlist"] = _scoring_egress_allowlist(ctx, options)
    return options


def _bind_singular_scoring_host(ctx: AttemptCtx) -> EnvironmentProvider | None:
    """The one isolated scoring box: evaluate recipe + evaluate-phase layers."""
    refs = thaw(getattr(ctx.lock, "resolved_references", None) or {})
    has_recipe = bool(refs.get("environment_evaluate_dockerfile")) or bool(
        refs.get("evaluation_docker_image")
    )
    if not has_recipe:
        return None
    return bind_winner(
        ctx.registry,
        ctx.bindings,
        ENVIRONMENT,
        spec=BoxSpec(
            attempt_root=ctx.evidence.path(EVALUATE_BOX_REL),
            task_root=ctx.task_root,
            repo_root=Path.cwd(),
            dockerfile=refs.get("environment_evaluate_dockerfile"),
            compose_file=None,
        ),
        plugin_layers=_scoring_plugin_layers(ctx),
        options=_scoring_environment_options(ctx),
    )


def _bind_named_scoring_host(ctx: AttemptCtx, name: str) -> EnvironmentProvider | None:
    """One named scoring box from its member recipe, with evaluate-phase layers."""
    recipe = named_evaluate_environments(ctx)[name]
    dockerfile = recipe.get("dockerfile")
    return bind_winner(
        ctx.registry,
        ctx.bindings,
        ENVIRONMENT,
        spec=BoxSpec(
            attempt_root=ctx.evidence.path(evaluate_box_rel(name)),
            task_root=ctx.task_root,
            repo_root=Path.cwd(),
            dockerfile=dockerfile if isinstance(dockerfile, str) and dockerfile.strip() else None,
            compose_file=None,
        ),
        plugin_layers=_scoring_plugin_layers(ctx),
        options=_scoring_environment_options(ctx, recipe),
    )


async def _prepare_evaluate_runtime(ctx: AttemptCtx) -> None:
    """Probe/install runtime entries on the scoring host for profiles not used during run."""
    if ctx.evaluate_host is None or ctx.evaluate_host is ctx.host:
        return
    await _prepare_evaluate_profiles(ctx)


async def _prepare_named_runtime(ctx: AttemptCtx, name: str, profile_id: str | None = None) -> None:
    if not profile_id:
        return
    await _prepare_evaluate_profiles(ctx, name=name, profile_id=profile_id)


async def _prepare_evaluate_profiles(
    ctx: AttemptCtx,
    name: str | None = None,
    profile_id: str | None = None,
) -> None:
    parent = getattr(ctx.agent_service, "service", None) or ctx.agent_service
    binder = getattr(parent, "binder", None)
    if binder is None:
        return
    sealed = {str(item) for item in (getattr(parent, "_run_profile_ids", None) or ())}
    from ageval.attempt.emit import run_chain
    from ageval.plugins.slots import AFTER_ENVIRONMENT_READY

    already = {
        (str(fact.detail.get("name") or ""), str(fact.detail.get("profile_id") or ""))
        for fact in ctx.phase_facts
        if fact.name == "evaluate_runtime_prepared"
    }
    for row in thaw(getattr(ctx.lock, "agent_profiles", None) or ()):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if not pid or pid in sealed:
            continue
        if profile_id is not None and pid != profile_id:
            continue
        if (name or "", pid) in already:
            continue
        # Empty chains no-op: the slot runs whatever the profile's graph binds.
        await run_chain(binder.graph(pid), AFTER_ENVIRONMENT_READY, None, ctx=ctx)
        detail: dict[str, str] = {"profile_id": pid}
        if name:
            detail["name"] = name
        ctx.record_fact("evaluate_runtime_prepared", detail)
        already.add((name or "", pid))


async def _materialize_on_host(
    ctx: AttemptCtx,
    host: EnvironmentProvider,
    *,
    name: str | None = None,
) -> None:
    """Copy harvested artifacts, workspace trees, and gold onto one scoring host."""
    staged = ctx.evidence.path(TASK_ARTIFACTS_REL)
    extra = {"name": name} if name else {}
    if staged.is_dir() and any(staged.iterdir()):
        await host.upload(staged, ARTIFACTS_PATH)
        ctx.record_fact("artifacts_materialized", {"at": PHASE, **extra})
    for snapshot in _workspace_tree_snapshots(ctx, staged):
        await host.upload(snapshot, WORKSPACE_PATH)
        ctx.record_fact(
            "workspace_materialized",
            {"at": PHASE, "artifact": snapshot.name, **extra},
        )
    if ctx.evaluation_src is not None and ctx.evaluation_src.is_dir():
        await host.upload(ctx.evaluation_src, EVALUATION_PATH)
        ctx.record_fact("gold_materialized", {"at": PHASE, **extra})


def _workspace_tree_snapshots(ctx: AttemptCtx, staged: Path) -> list[Path]:
    lock = getattr(ctx, "lock", None)
    if lock is None:
        return []
    refs = thaw(getattr(lock, "resolved_references", None) or {})
    artifacts = {
        str(row.get("id")): row
        for row in (refs.get("artifacts") or [])
        if isinstance(row, dict) and row.get("id")
    }
    out: list[Path] = []
    for inp in refs.get("evaluation_inputs") or []:
        if not isinstance(inp, dict):
            continue
        if str(inp.get("target") or "") != "workspace":
            continue
        aid = str(inp.get("artifact") or "")
        row = artifacts.get(aid) or {}
        if str(row.get("kind") or "") != "tree":
            continue
        snapshot = staged / aid
        if snapshot.is_dir():
            out.append(snapshot)
    return out
