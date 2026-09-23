"""Default ``environment_setup`` handler: run the task's own ``setup.sh``.

This is the last slot of the environment phase. It carries *this task's*
dependencies — never the Agent runtime, which the ACP plugin probes and installs
on ``after_environment_ready``.
"""

from __future__ import annotations

from typing import Any

from ageval.environments.protocol import EnvironmentFailure
from ageval.plugins.protocol import NextFn

SETUP_PRIORITY = 500
BOX_ENVIRONMENT_DIR = "/attempt/environment"
SETUP_FILENAME = "setup.sh"


async def default_environment_setup(ctx: Any, value: Any, nxt: NextFn) -> Any:
    """Upload ``environment/`` and exec ``setup.sh`` when the task ships one."""
    source = getattr(ctx, "environment_src", None)
    if source is None or not source.is_dir() or not (source / SETUP_FILENAME).is_file():
        return await nxt(value)

    host = ctx.host
    await host.upload(source, BOX_ENVIRONMENT_DIR)
    timeout = ctx.remaining_seconds()
    if timeout is not None and timeout <= 0:
        raise EnvironmentFailure("environment_timeout", "environment_timeout")
    # Relative argv against the mapped cwd: in-box absolute paths are literals
    # to the process, and a local box has no ``/attempt`` on disk.
    result = await host.exec(
        ["sh", SETUP_FILENAME],
        cwd=BOX_ENVIRONMENT_DIR,
        timeout_sec=timeout,
    )
    if result.exit_code != 0 and timeout is not None and ctx.phase_budget_exhausted():
        raise EnvironmentFailure("environment_timeout", "environment_timeout")
    ctx.record_fact(
        "environment_setup",
        {"exit_code": result.exit_code, "script": f"environment/{SETUP_FILENAME}"},
    )
    if result.exit_code != 0:
        raise EnvironmentFailure(
            "environment_setup_failed",
            f"environment/{SETUP_FILENAME} exited {result.exit_code}: "
            f"{result.stderr.strip()[-500:]}",
        )
    return await nxt(value)
