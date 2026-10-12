"""SPI and graph types for the extension registry.

``ExecutorSPI`` is the ``executor`` exclusive slot winner. It receives its pipe
from ``environment.attach_stdio`` and therefore never learns a container id,
sandbox handle, or ssh target.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ExecutorSPI(Protocol):
    """Exclusive slot ``executor``: one Agent backend for the Attempt."""

    kind: str

    def open(self, **kwargs: Any) -> None:
        """Optional session open (adapters that open lazily may no-op)."""
        ...

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any: ...

    def close(self) -> None:
        """Release process / session resources."""
        ...


@runtime_checkable
class EvaluationRuntimeSPI(Protocol):
    """Exclusive slot ``evaluation_runtime``: launch the evaluator, return raw.

    Must not call ``bind_evaluation``. PASS enters only when the evaluate
    phase binds the returned document.
    """

    async def evaluate(self, ctx: Any) -> dict[str, Any]: ...


@runtime_checkable
class TrajectorySealSPI(Protocol):
    """Exclusive slot ``trajectory_seal``: author layer C ``trajectory.jsonl``."""

    def seal(self, ctx: Any, turns: list[list[dict[str, Any]]]) -> Path: ...


# Chain middleware: async (ctx, value, next) -> value
NextFn = Callable[[Any], Awaitable[Any]]
HookHandler = Callable[[Any, Any, NextFn], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ExplicitBinding:
    """Job intent for one slot (short override, not a full plugin copy)."""

    slot: str
    plugin: str
    priority: int | None = None
    source: str = "explicit"
    options: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ExtensionSelect:
    """One ``extensions`` row before per-slot expansion.

    ``slots is None`` means every slot the plugin registered.
    """

    plugin: str
    slots: tuple[str, ...] | None = None
    priority: int | None = None
    source: str = "explicit"
    options: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InjectRequirement:
    """One ``inject`` row: a service name plus the caps it will actually call."""

    service: str
    capabilities: tuple[str, ...] = ()


@dataclass
class BindingIntent:
    """Per-profile binding intent used at lock time."""

    profile_id: str
    environment: str | None = None  # exclusive slot environment winner (job level)
    environment_options: dict[str, Any] = field(default_factory=dict)
    executor: str | None = None  # exclusive slot executor winner
    options: dict[str, Any] = field(default_factory=dict)
    extensions: list[ExplicitBinding] = field(default_factory=list)
    extension_selects: list[ExtensionSelect] = field(default_factory=list)
    requires: dict[str, tuple[str, ...]] = field(default_factory=dict)
    model: str | Mapping[str, Any] | None = None
    base_url: str | None = None
    api_key: str | None = None


@dataclass(frozen=True, slots=True)
class WinnerRef:
    """Resolved exclusive slot winner (also registered as a service)."""

    plugin_id: str
    impl: Any
    priority: int
    source: str
    version: str | None = None
    digest: str | None = None
    slot: str = ""
    options: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HandlerRef:
    """One link in a chain slot."""

    plugin_id: str
    handler: Any
    priority: int
    source: str
    version: str | None = None
    digest: str | None = None
    slot: str = ""
    options: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BindingRecord:
    """Lock-facing record of one resolved contribution."""

    slot: str
    kind: str  # "exclusive" | "chain"
    plugin: str
    priority: int
    source: str
    version: str | None = None
    digest: str | None = None


@dataclass
class ExtensionGraph:
    """Resolution result for one profile id."""

    profile_id: str
    winners: dict[str, WinnerRef] = field(default_factory=dict)
    chains: dict[str, list[HandlerRef]] = field(default_factory=dict)
    records: list[BindingRecord] = field(default_factory=list)
    services: dict[str, str] = field(default_factory=dict)  # service id → plugin id
    injects: dict[str, tuple[InjectRequirement, ...]] = field(default_factory=dict)

    def winner(self, slot: str) -> WinnerRef | None:
        return self.winners.get(slot)

    def chain(self, slot: str) -> list[HandlerRef]:
        return list(self.chains.get(slot) or [])


def intent_from_profile(
    profile: Mapping[str, Any],
    *,
    environment: str | None = None,
    environment_options: Mapping[str, Any] | None = None,
    requires: Mapping[str, Sequence[str]] | None = None,
) -> BindingIntent:
    """Build BindingIntent from a resolved ``agent_profiles`` row."""
    profile_id = str(profile.get("id") or profile.get("profile_id") or "")
    executor = _optional_str(profile.get("executor"))
    options_raw = profile.get("options")
    options: dict[str, Any] = dict(options_raw) if isinstance(options_raw, Mapping) else {}
    extensions: list[ExplicitBinding] = []
    extension_selects: list[ExtensionSelect] = []
    ext_raw = profile.get("extensions") or []
    if not isinstance(ext_raw, Sequence) or isinstance(ext_raw, (str, bytes)):
        from ageval.plugins.errors import ExtensionRegistryError

        raise ExtensionRegistryError(
            "extensions must be a list of mappings",
            kind="invalid_extension_binding",
        )
    for item in ext_raw:
        parsed_binding, parsed_select = parse_extension_row(item)
        if parsed_binding is not None:
            extensions.append(parsed_binding)
        if parsed_select is not None:
            extension_selects.append(parsed_select)
    return BindingIntent(
        profile_id=profile_id,
        environment=_optional_str(environment),
        environment_options=dict(environment_options or {}),
        executor=executor,
        options=options,
        extensions=extensions,
        extension_selects=extension_selects,
        requires={str(k): tuple(str(v) for v in vals) for k, vals in (requires or {}).items()},
        model=_profile_model(profile.get("model")),
        base_url=_optional_str(profile.get("base_url")),
        api_key=_optional_str(profile.get("api_key")),
    )


def _optional_str(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _profile_model(raw: Any) -> str | dict[str, Any] | None:
    """String id, or a nested ``model:`` mapping. Empty / other types are absent."""
    from ageval.config.profiles import model_argument

    return model_argument(raw)


def row_options(item: Mapping[str, Any]) -> dict[str, Any]:
    """Parse optional ``options`` on one extensions row."""
    raw = item.get("options")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        from ageval.plugins.errors import ExtensionRegistryError

        raise ExtensionRegistryError(
            "extensions.options must be a mapping",
            kind="invalid_extension_binding",
        )
    return dict(raw)


def options_for_plugin(intent: BindingIntent, plugin_id: str) -> dict[str, Any]:
    """Options for *plugin_id*: profile ``options`` then extensions rows (last wins)."""
    found: dict[str, Any] = {}
    if intent.executor == plugin_id and intent.options:
        found = dict(intent.options)
    for sel in intent.extension_selects:
        if sel.plugin == plugin_id and sel.options:
            found = {**found, **dict(sel.options)}
    for binding in intent.extensions:
        if binding.plugin == plugin_id and binding.options:
            found = {**found, **dict(binding.options)}
    return found


def parse_extension_row(item: Any) -> tuple[ExplicitBinding | None, ExtensionSelect | None]:
    """Parse one extensions row. ``{slot, plugin}`` binds a single slot."""
    from ageval.plugins.errors import ExtensionRegistryError

    if not isinstance(item, Mapping):
        raise ExtensionRegistryError(
            "each extensions row must be a mapping",
            kind="invalid_extension_binding",
        )
    plugin = _optional_str(item.get("plugin"))
    if plugin is None:
        raise ExtensionRegistryError(
            "extensions row requires plugin",
            kind="invalid_extension_binding",
        )
    slot_raw = item.get("slot")
    slots_raw = item.get("slots")
    prio = item.get("priority")
    priority = int(prio) if prio is not None else None
    options = row_options(item)
    if slot_raw is not None and slots_raw is not None:
        raise ExtensionRegistryError(
            "extensions row cannot set both slot and slots",
            kind="invalid_extension_binding",
        )
    if slot_raw is not None:
        slot = _optional_str(slot_raw)
        if slot is None:
            raise ExtensionRegistryError(
                "extensions.slot must be a non-empty string",
                kind="invalid_extension_binding",
            )
        return (
            ExplicitBinding(
                slot=slot,
                plugin=plugin,
                priority=priority,
                options=options or None,
            ),
            None,
        )
    if slots_raw is not None:
        if not isinstance(slots_raw, Sequence) or isinstance(slots_raw, (str, bytes)):
            raise ExtensionRegistryError(
                "extensions.slots must be a list of slot ids",
                kind="invalid_extension_binding",
            )
        slots: list[str] = []
        for raw_slot in slots_raw:
            slot = _optional_str(raw_slot)
            if slot is None:
                raise ExtensionRegistryError(
                    "extensions.slots entries must be non-empty strings",
                    kind="invalid_extension_binding",
                )
            slots.append(slot)
        if not slots:
            raise ExtensionRegistryError(
                "extensions.slots must not be empty",
                kind="invalid_extension_binding",
            )
        return (
            None,
            ExtensionSelect(
                plugin=plugin,
                slots=tuple(slots),
                priority=priority,
                options=options or None,
            ),
        )
    return (
        None,
        ExtensionSelect(
            plugin=plugin,
            slots=None,
            priority=priority,
            options=options or None,
        ),
    )
