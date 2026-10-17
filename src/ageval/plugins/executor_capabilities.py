"""Built-in executor capability matrix.

Spec 19: coding-agent surface is ``acp`` only; ``openai-http`` /
``anthropic-http`` remain api-client.
Private vendor CLI kinds are not first-class.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, get_type_hints

ToolsCap = Literal["native", "adapter-loop", "unsupported"]
StructuredCap = Literal["native", "validated-text", "unsupported"]
SessionCap = Literal["new-only", "resume-within-attempt", "unsupported"]
StreamCap = Literal["native-events", "synthetic-lifecycle"]
# Documented builtins: acp-stdio, api-client, container-worker. Plugins may use others.
ExecutionMode = str


@dataclass(frozen=True, slots=True)
class ExecutorCapabilities:
    kind: str
    tools: ToolsCap
    structured_output: StructuredCap
    session: SessionCap
    stream: StreamCap
    execution_mode: ExecutionMode
    credential_env_names: tuple[str, ...]
    binary: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_CAPABILITIES: Final[dict[str, ExecutorCapabilities]] = {
    "acp": ExecutorCapabilities(
        kind="acp",
        tools="native",
        structured_output="validated-text",
        session="new-only",
        stream="native-events",
        execution_mode="acp-stdio",
        # Entry-specific credential allowlists live on AcpEntryDescriptor.
        credential_env_names=(),
        binary="",
    ),
    "openai-http": ExecutorCapabilities(
        kind="openai-http",
        tools="native",
        structured_output="validated-text",
        session="new-only",
        stream="synthetic-lifecycle",
        execution_mode="api-client",
        credential_env_names=("OPENAI_API_KEY",),
        binary="",
    ),
    "anthropic-http": ExecutorCapabilities(
        kind="anthropic-http",
        tools="native",
        structured_output="validated-text",
        session="new-only",
        stream="synthetic-lifecycle",
        execution_mode="api-client",
        credential_env_names=("ANTHROPIC_API_KEY",),
        binary="",
    ),
}


def get_capabilities(kind: str) -> ExecutorCapabilities | None:
    found = BUILTIN_CAPABILITIES.get(kind)
    if found is not None:
        return found
    return _plugin_published_capabilities(kind)


def _plugin_published_capabilities(kind: str) -> ExecutorCapabilities | None:
    """Capabilities published by an installed plugin's describe() / SPI."""
    try:
        from ageval.plugins.bootstrap import ensure_bootstrapped
        from ageval.plugins.slots import EXECUTOR
    except ImportError:
        return None
    reg = ensure_bootstrapped()
    rec = reg.get_registration(EXECUTOR, kind)
    if rec is None:
        return None
    desc = _describe_from_provider(rec.impl)
    if desc is None:
        return None
    return ExecutorCapabilities(
        kind=kind,
        tools=str(desc.get("tools") or "unsupported"),  # type: ignore[arg-type]
        structured_output=str(desc.get("structured_output") or "unsupported"),  # type: ignore[arg-type]
        session=str(desc.get("session") or "unsupported"),  # type: ignore[arg-type]
        stream=str(desc.get("stream") or "synthetic-lifecycle"),  # type: ignore[arg-type]
        execution_mode=str(desc.get("execution_mode") or "container-worker"),
        credential_env_names=tuple(desc.get("credential_env_names") or ()),
        binary=str(desc.get("binary") or ""),
    )


def _describe_from_provider(impl: Any) -> dict[str, Any] | None:
    if impl is None:
        return None
    found = _call_describe(impl)
    if found is not None:
        return found
    cls = impl if isinstance(impl, type) else type(impl)
    found = _call_describe(cls)
    if found is not None:
        return found
    # Registry holds the factory function; describe() lives on the SPI class.
    ret = _factory_return_type(impl)
    if ret is not None:
        return _call_describe(ret)
    return None


def _call_describe(obj: Any) -> dict[str, Any] | None:
    fn = getattr(obj, "describe", None)
    if not callable(fn):
        return None
    try:
        out = fn()
    except TypeError:
        try:
            out = obj.describe()  # type: ignore[misc]
        except (TypeError, ValueError, AttributeError):
            return None
    except (ValueError, AttributeError):
        return None
    return out if isinstance(out, dict) else None


def _factory_return_type(impl: Any) -> Any | None:
    if impl is None or isinstance(impl, type) or not callable(impl):
        return None
    try:
        hints = get_type_hints(impl)
    except (TypeError, ValueError, NameError, AttributeError):
        hints = getattr(impl, "__annotations__", {}) or {}
    ret = hints.get("return")
    return ret if isinstance(ret, type) else None
