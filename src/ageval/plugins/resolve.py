"""Resolve BindingIntent + registry → ExtensionGraph (lock source of truth).

Everything fails closed here, at lock time: an unknown slot, two plugins on one
exclusive slot, a missing service, or a capability the winning box cannot
deliver. Nothing probes at invoke time.
"""

from __future__ import annotations

from typing import Any

from ageval.plugins.conflict import Candidate, order_chain, pick_one
from ageval.plugins.errors import (
    ExtensionMaterializeError,
    ExtensionPluginNotFoundError,
    UnknownExtensionSlotError,
)
from ageval.plugins.model_contract import assert_requires_environment
from ageval.plugins.protocol import (
    BindingIntent,
    BindingRecord,
    ExplicitBinding,
    ExtensionGraph,
    ExtensionSelect,
    HandlerRef,
    InjectRequirement,
    WinnerRef,
    options_for_plugin,
)
from ageval.plugins.registry import ExtensionRegistry, Registration
from ageval.plugins.services import assert_inject_satisfied
from ageval.plugins.slots import (
    ALL_SLOTS,
    ENVIRONMENT,
    EXECUTOR,
    REQUIRED_EXCLUSIVE_SLOTS,
    SlotKind,
    get_slot_kind,
    is_slot,
)

# Exclusive slots selected by a job field rather than by an extensions row.
_SUGAR_SLOTS: dict[str, str] = {ENVIRONMENT: "environment", EXECUTOR: "executor"}


def resolve(
    intent: BindingIntent,
    registry: ExtensionRegistry,
    *,
    materialize: bool = True,
) -> ExtensionGraph:
    """Resolve every slot for one profile intent.

    *materialize* builds the chain handlers, which is what an Attempt needs.
    Lock only wants the graph, so it resolves without building anything.
    """
    graph = ExtensionGraph(profile_id=intent.profile_id)
    explicit = list(intent.extensions)
    explicit.extend(expand_extension_selects(intent.extension_selects, registry))
    for binding in explicit:
        if not is_slot(binding.slot):
            raise UnknownExtensionSlotError(
                f"unknown extension slot: {binding.slot!r}",
                kind="unknown_extension_slot",
            )

    # Job fields select exclusive winners; appended last so they beat a bare
    # ``- plugin:`` row that also registered the slot.
    for slot, attr in _SUGAR_SLOTS.items():
        chosen = getattr(intent, attr, None)
        if chosen:
            # The box reads job ``environment_options``; the executor reads the
            # profile's own ``options``. They are different vocabularies.
            options = (
                dict(intent.environment_options)
                if slot == ENVIRONMENT
                else options_for_plugin(intent, str(chosen))
            )
            explicit.append(
                ExplicitBinding(
                    slot=slot,
                    plugin=str(chosen),
                    source=f"profile_{attr}_field",
                    options=options or None,
                )
            )

    for slot in ALL_SLOTS:
        slot_explicit = [e for e in explicit if e.slot == slot]
        candidates = registry.candidates(slot)
        if get_slot_kind(slot) is SlotKind.EXCLUSIVE:
            _resolve_exclusive(
                graph,
                intent,
                slot,
                candidates=candidates,
                explicit=explicit,
                slot_explicit=slot_explicit,
            )
        else:
            _resolve_chain(
                graph,
                intent,
                slot,
                candidates=candidates,
                explicit=explicit,
                slot_explicit=slot_explicit,
                materialize=materialize,
            )

    _collect_services(graph, registry)
    _collect_injects(graph, registry)
    assert_requires_environment(graph, registry)
    assert_inject_satisfied(graph.injects, _declared_services(graph, registry))
    _assert_requires(intent, graph)
    return graph


def _declared_services(graph: ExtensionGraph, registry: ExtensionRegistry) -> dict[str, Any]:
    """Service id → declared implementation, for lock-time capability checks.

    Winners are still classes here, and capabilities are declared on the class,
    so a box that cannot ``attach_stdio`` fails the lock rather than an invoke.
    """
    available: dict[str, Any] = {slot: ref.impl for slot, ref in graph.winners.items()}
    for service_id, plugin_id in graph.services.items():
        if service_id in available:
            continue
        registration = registry.service(service_id)
        if registration is not None and registration.plugin_id == plugin_id:
            available[service_id] = registration.impl
    return available


def _resolve_exclusive(
    graph: ExtensionGraph,
    intent: BindingIntent,
    slot: str,
    *,
    candidates: list[Candidate],
    explicit: list[ExplicitBinding],
    slot_explicit: list[ExplicitBinding],
) -> None:
    if not slot_explicit:
        # No job field and no explicit row: only a registered default may win.
        candidates = [c for c in candidates if c.is_default]
        if not candidates:
            if slot in REQUIRED_EXCLUSIVE_SLOTS:
                raise ExtensionPluginNotFoundError(
                    f"no plugin fills exclusive slot {slot!r}",
                    kind="extension_plugin_not_found",
                )
            return
    winner = pick_one(candidates, explicit, slot=slot)
    reg = winner.impl
    if not isinstance(reg, Registration):
        raise ExtensionMaterializeError(
            f"invalid registration object for {slot}",
            kind="extension_materialize_failed",
        )
    options = _options_for(intent, explicit, slot, winner.plugin_id)
    # Winners stay declared, not constructed: see ``plugins/binding.py``.
    graph.winners[slot] = WinnerRef(
        plugin_id=winner.plugin_id,
        impl=reg.impl,
        priority=winner.priority,
        source=winner.source,
        version=winner.version,
        digest=winner.digest,
        slot=slot,
        options=options or None,
    )
    graph.services[slot] = winner.plugin_id
    graph.records.append(
        BindingRecord(
            slot=slot,
            kind="exclusive",
            plugin=winner.plugin_id,
            priority=winner.priority,
            source=winner.source,
            version=winner.version,
            digest=winner.digest,
        )
    )


def _resolve_chain(
    graph: ExtensionGraph,
    intent: BindingIntent,
    slot: str,
    *,
    candidates: list[Candidate],
    explicit: list[ExplicitBinding],
    slot_explicit: list[ExplicitBinding],
    materialize: bool,
) -> None:
    # Opt-in: a plugin only joins a chain when the job listed it. Engine
    # defaults are the exception — that is what makes them defaults.
    named = {row.plugin for row in slot_explicit}
    candidates = [c for c in candidates if c.is_default or c.plugin_id in named]
    if not candidates:
        return
    chain = order_chain(candidates, explicit, slot=slot)
    if not chain:
        return
    refs: list[HandlerRef] = []
    for item in chain:
        reg = item.impl
        if not isinstance(reg, Registration):
            raise ExtensionMaterializeError(
                f"invalid registration object for {slot}",
                kind="extension_materialize_failed",
            )
        options = _options_for(intent, explicit, slot, item.plugin_id)
        handler = _build_handler(reg, intent, options) if materialize else reg.impl
        refs.append(
            HandlerRef(
                plugin_id=item.plugin_id,
                handler=handler,
                priority=item.priority,
                source=item.source,
                version=item.version,
                digest=item.digest,
                slot=slot,
                options=options or None,
            )
        )
        graph.records.append(
            BindingRecord(
                slot=slot,
                kind="chain",
                plugin=item.plugin_id,
                priority=item.priority,
                source=item.source,
                version=item.version,
                digest=item.digest,
            )
        )
    graph.chains[slot] = refs


def _collect_services(graph: ExtensionGraph, registry: ExtensionRegistry) -> None:
    """Add ``exports.services`` of every bound plugin to the graph."""
    bound = {ref.plugin_id for ref in graph.winners.values()}
    for chain in graph.chains.values():
        bound.update(h.plugin_id for h in chain)
    for plugin_id in sorted(bound):
        for service_id in registry.services_for_plugin(plugin_id):
            graph.services[service_id] = plugin_id


def _collect_injects(graph: ExtensionGraph, registry: ExtensionRegistry) -> None:
    bound = {ref.plugin_id for ref in graph.winners.values()}
    for chain in graph.chains.values():
        bound.update(h.plugin_id for h in chain)
    for plugin_id in sorted(bound):
        rows = tuple(
            row
            for row in registry.injects_for_plugin(plugin_id)
            if isinstance(row, InjectRequirement)
        )
        if rows:
            graph.injects[plugin_id] = rows


def _assert_requires(intent: BindingIntent, graph: ExtensionGraph) -> None:
    """Task ``requires.environment`` must be a subset of the winner's caps."""
    wanted = intent.requires.get(ENVIRONMENT) or ()
    if not wanted:
        return
    winner = graph.winners.get(ENVIRONMENT)
    if winner is None:
        raise ExtensionPluginNotFoundError(
            "task requires environment capabilities but no environment winner is bound",
            kind="extension_plugin_not_found",
        )
    caps = getattr(winner.impl, "capabilities", None)
    if caps is None:
        raise ExtensionPluginNotFoundError(
            f"environment kind {winner.plugin_id!r} declares no capabilities",
            kind="extension_plugin_not_found",
        )
    missing = list(caps.missing(wanted))
    if missing:
        from ageval.plugins.errors import InjectUnsatisfiedError

        raise InjectUnsatisfiedError(
            f"environment kind {winner.plugin_id!r} cannot deliver required capabilities {missing}"
        )


def _build_handler(
    reg: Registration,
    intent: BindingIntent,
    options: dict[str, Any] | None = None,
) -> Any:
    """Turn a chain registration into the handler that will run in the onion."""
    impl = reg.impl
    if not reg.is_factory:
        return impl
    if not callable(impl):
        raise ExtensionMaterializeError(
            f"factory for plugin {reg.plugin_id!r} slot {reg.slot!r} is not callable",
            kind="extension_materialize_failed",
        )
    try:
        return impl(
            options=dict(options or {}),
            profile_id=intent.profile_id,
            model=intent.model,
            base_url=intent.base_url,
            api_key=intent.api_key,
        )
    except ExtensionMaterializeError:
        raise
    except Exception as exc:  # noqa: BLE001 — one lock-time failure, no retry
        raise ExtensionMaterializeError(
            f"materialize failed for plugin {reg.plugin_id!r} slot {reg.slot!r}: {exc}",
            kind="extension_materialize_failed",
        ) from exc


def _options_for(
    intent: BindingIntent,
    explicit: list[ExplicitBinding],
    slot: str,
    plugin_id: str,
) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for binding in explicit:
        if binding.slot == slot and binding.plugin == plugin_id and binding.options:
            found = dict(binding.options)
    if found:
        return found
    return options_for_plugin(intent, plugin_id)


def expand_extension_selects(
    selects: list[ExtensionSelect],
    registry: ExtensionRegistry,
) -> list[ExplicitBinding]:
    """Turn ``- plugin:`` / ``slots:`` rows into per-slot explicit bindings."""
    out: list[ExplicitBinding] = []
    for sel in selects:
        registered = registry.slots_for_plugin(sel.plugin)
        if not registered:
            raise ExtensionPluginNotFoundError(
                f"plugin {sel.plugin!r} is not registered",
                kind="extension_plugin_not_found",
            )
        if sel.slots is None:
            wanted = list(registered)
        else:
            wanted = []
            for slot in sel.slots:
                if not is_slot(slot):
                    raise UnknownExtensionSlotError(
                        f"unknown extension slot: {slot!r}",
                        kind="unknown_extension_slot",
                    )
                if slot not in registered:
                    raise ExtensionPluginNotFoundError(
                        f"plugin {sel.plugin!r} did not register slot {slot!r}",
                        kind="extension_slot_unregistered",
                    )
                wanted.append(slot)
        for slot in wanted:
            out.append(
                ExplicitBinding(
                    slot=slot,
                    plugin=sel.plugin,
                    priority=sel.priority,
                    source=sel.source,
                    options=dict(sel.options) if sel.options else None,
                )
            )
    return out
