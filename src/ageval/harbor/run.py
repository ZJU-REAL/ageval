"""Built-in Harbor run: one instruction, or the explicit oracle switch.

``solution/solve.sh`` is executed by the environment phase when ``--oracle``
is set. This entry only skips the agent in that case. It does not score.
"""

from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    """Hand ``instruction.md`` to the bound solver, once."""
    if ctx.params.get("harbor_oracle") is True:
        return RunTerminal.completed("oracle")
    task_root = ctx.task_root
    if task_root is None:
        return RunTerminal.failed("instruction_missing")
    path = task_root / "instruction.md"
    if not path.is_file():
        return RunTerminal.failed("instruction_missing")
    instruction = path.read_text(encoding="utf-8")
    async with ctx.agent.session("solver", max_turns=1) as session:
        invoked = await session.invoke(instruction)
    if not invoked.get("ok"):
        return RunTerminal.failed(str(invoked.get("error") or "agent_invoke_failed"))
    return RunTerminal.completed()
