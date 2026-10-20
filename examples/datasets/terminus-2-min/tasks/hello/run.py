"""One terminus-2 invoke. The file on disk is the artifact; the reply is not PASS."""

from __future__ import annotations

from ageval_sdk import RunContext, RunTerminal


async def run(ctx: RunContext) -> RunTerminal:
    instruction_path = ctx.workspace_root / "instruction.md"
    if not instruction_path.is_file():
        return RunTerminal.failed("instruction_missing")
    instruction = instruction_path.read_text(encoding="utf-8")
    async with ctx.agent.session("solver", max_turns=1) as session:
        invoked = await session.invoke(instruction)
    if not invoked.get("ok"):
        return RunTerminal.failed(str(invoked.get("error") or "agent_invoke_failed"))
    target = ctx.workspace_root / "hello.txt"
    if not target.is_file():
        return RunTerminal.failed("hello_missing")
    ctx.publish_file("hello", target)
    return RunTerminal.completed("hello")
