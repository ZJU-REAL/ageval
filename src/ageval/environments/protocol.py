"""Environment (box) transport protocol — no vendor SDK, no kind branching.

The ``environment`` exclusive slot winner is the only object that knows how a
box is started, how files move in and out, and how a foreground process is
attached. Everything above it (``attempt``, ACP executor, task ``run.py``)
talks to this Protocol and never sees a container id, sandbox handle, or ssh
target.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

# Capability names a kind may claim. ``requires.environment`` must be a subset.
CAPABILITY_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "upload",
        "download",
        "attach_stdio",
        "uid_gid",
        "path_views",
        "compose",
    }
)

# In-box path contract. Every kind maps these to its own storage.
WORKSPACE_PATH = "/attempt/workspace"
HOME_PATH = "/attempt/home"
ARTIFACTS_PATH = "/attempt/artifacts"
EVALUATION_PATH = "/attempt/evaluation"


@dataclass(frozen=True, slots=True)
class EnvironmentCapabilities:
    """What a kind can actually deliver. Declaring one it cannot is a bug."""

    exec: bool = False
    upload: bool = False
    download: bool = False
    attach_stdio: bool = False
    uid_gid: bool = False
    path_views: bool = False
    compose: bool = False

    def names(self) -> frozenset[str]:
        return frozenset(name for name in CAPABILITY_NAMES if getattr(self, name))

    def missing(self, required: Sequence[str]) -> list[str]:
        have = self.names()
        return sorted({str(name) for name in required} - have)


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a foreground process attaches. Issued by the kind, opaque above it.

    Paths are in the in-box contract form, like every other path a caller hands
    to a box. Use ``visible_path`` when a path must be handed *to* a process
    (an argv element, an env value) instead of to the box.
    """

    target_id: str
    user: str | None = None
    workdir: str = WORKSPACE_PATH
    home: str = HOME_PATH


@dataclass(frozen=True, slots=True)
class BoxSpec:
    """What the engine hands a kind when it binds the ``environment`` slot.

    The kind decides what it needs: a local box uses only the work root, a
    docker box also reads the recipe the task shipped. Job ``options`` stay
    separate — this is engine-owned context, not user configuration.
    """

    attempt_root: Path
    task_root: Path
    repo_root: Path
    # Task-relative recipes, present only when the task actually ships them.
    dockerfile: str | None = None
    compose_file: str | None = None
    # Directory inside task_root used as the docker build context. None keeps task_root.
    build_context: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeStatus:
    """Whether a previously started box can be reused."""

    status: Literal["absent", "idle", "busy"]
    nonce: str | None = None
    cursor_seq: int | None = None
    cursor_request_id: str | None = None
    inflight_request_id: str | None = None
    last_exit: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Result of a completed in-box command."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@runtime_checkable
class StdioTransport(Protocol):
    """Live bidirectional pipe to a foreground process inside an open box."""

    stdin: object
    stdout: object
    stderr: object

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...


@runtime_checkable
class EnvironmentProvider(Protocol):
    """Exclusive slot ``environment``: the box for one Attempt."""

    kind: str
    capabilities: EnvironmentCapabilities
    # argv prefix that runs a Python module inside this box, e.g. ``("python3",)``.
    python_command: tuple[str, ...]

    async def preflight(self) -> None:
        """Fail closed at lock time when this box cannot be opened here."""
        ...

    async def start(self, *, force_build: bool = False) -> None: ...

    def runtime_handle(self) -> dict[str, Any]:
        """JSON handle for a started box. Opaque above the kind."""
        ...

    async def probe(self, handle: Mapping[str, Any]) -> ProbeStatus:
        """Inspect a previous handle without mutating the workspace."""
        ...

    async def attach(self, handle: Mapping[str, Any]) -> None:
        """Bind this instance to a live box identified by ``handle``."""
        ...

    async def discard(self, handle: Mapping[str, Any]) -> None:
        """Stop a box recorded on ``handle``. The attempt directory stays.

        Kinds that own an external machine override this. ``local`` does nothing.
        """
        ...

    def placement(self) -> Placement:
        """Engine-issued attach facts for the open box (no vendor handle)."""
        ...

    def visible_path(self, box_path: str) -> str:
        """An in-box path as the processes inside this box see it.

        Identical to *box_path* for kinds that really own ``/attempt``; a local
        box maps it onto its work root. Callers use this only when a path must
        travel *into* a process (argv, env), never to talk to the box itself.
        """
        ...

    async def exec(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        user: str | None = None,
        service: str | None = None,
    ) -> ExecResult: ...

    async def upload(
        self,
        source: Path,
        dest: str,
        *,
        service: str | None = None,
    ) -> None: ...

    async def download(
        self,
        source: str,
        dest: Path,
        *,
        service: str | None = None,
    ) -> None: ...

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> StdioTransport: ...

    async def stop(self, *, delete: bool) -> None: ...


class EnvironmentFailure(Exception):
    """Box failure with a stable kind for evidence and exit mapping."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def reject_foreign_service(service: str | None, *, kind: str, verb: str) -> None:
    """Kinds without compose cannot copy from a named service."""
    if service is None:
        return
    raise EnvironmentFailure(
        "environment_capability_missing",
        f"{kind} does not provide compose; {verb}(service=…) is unavailable",
    )
