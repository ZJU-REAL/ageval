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
    """Upload ``environment/`` and exec ``setup.sh`` when the task ships one.

    ``--oracle`` on a Harbor task also runs ``solution/solve.sh`` here, before
    the built-in run skips the agent.
    """
    await _run_setup_script(ctx)
    await _run_oracle(ctx)
    return await nxt(value)


async def _run_setup_script(ctx: Any) -> None:
    source = getattr(ctx, "environment_src", None)
    if source is None or not source.is_dir() or not (source / SETUP_FILENAME).is_file():
        return

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


async def _run_oracle(ctx: Any) -> None:
    """Run ``solution/solve.sh`` only when the lock asked for the oracle."""
    from ageval.config.model import thaw
    from ageval.environments.protocol import WORKSPACE_PATH

    params = thaw(getattr(getattr(ctx, "lock", None), "parameters", None) or {})
    if params.get("harbor_oracle") is not True:
        return
    task_root = getattr(ctx, "task_root", None)
    if task_root is None:
        raise EnvironmentFailure("harbor_oracle_missing", "solution/solve.sh not found")
    source = task_root / "solution"
    script = source / "solve.sh"
    if not script.is_file():
        raise EnvironmentFailure("harbor_oracle_missing", "solution/solve.sh not found")
    host = ctx.host
    await host.upload(source, "/attempt/solution")
    timeout = ctx.remaining_seconds()
    if timeout is not None and timeout <= 0:
        raise EnvironmentFailure("environment_timeout", "environment_timeout")
    visible = host.visible_path("/attempt/solution/solve.sh")
    result = await host.exec(["sh", visible], cwd=WORKSPACE_PATH, timeout_sec=timeout)
    if result.exit_code != 0:
        raise EnvironmentFailure(
            "harbor_oracle_failed",
            f"solution/solve.sh exited {result.exit_code}: {result.stderr.strip()[-500:]}",
        )
    ctx.record_fact("harbor_oracle", {"exit_code": result.exit_code})
