---
name: ageval-sdk-harness
description: >
  Write dataset run.py with ageval_sdk (RunContext, Agent/AgentSession, ToolSet,
  RunTerminal, publish). Use for task run.py, sessions, tool guards, optional
  evaluator.py LLM-as-judge. Triggers: AgentSession, RunTerminal,
  ctx.publish_json, write run.py, evaluator.py. SDK never decides PASS or holds
  host credentials.
---

# SDK / run.py

```python
from ageval_sdk import RunContext, RunTerminal

async def run(ctx: RunContext) -> RunTerminal:
    async with ctx.agent.session("solver", max_turns=1) as session:
        reply = await session.invoke(ctx.params["instruction"])
    ctx.publish_json("reply", {"ok": bool(reply.get("ok")), "text": reply.get("text") or ""})
    if not reply.get("ok"):
        return RunTerminal.failed(str(reply.get("error") or "invoke_failed"))
    return RunTerminal.completed("ok")
```

`RunTerminal.completed` is not PASS. Evaluator is a separate process.

Default `evaluator.py` is a script: read artifacts + gold, return `{status, score, metrics}`. Optional extra key `checks` (use `evaluation_check(...)`) — parent writes `evaluation/checks.json`; bind ignores it. Optional LLM-as-judge: after gold is uploaded, `Agent.session(<role>).invoke` on a role declared in the same `profiles.yaml`. Parent injects `inputs["agent"]` when the socket is projected (`environment: local`). Still return `{status, score, metrics}` — judge text, `evaluation/observation.jsonl`, and `checks` rows are not PASS. `invoke` kwargs must not override `profile_id` / executor.

| May | Must not |
| --- | --- |
| Open sessions, tools, publish | Decide PASS |
| Use `ctx.params` | Re-read lock or secrets |
| Return completed/failed | Raise Core ceilings |
| Evaluator `Agent.session` after gold | Bind PASS from judge prose / observation.jsonl |

API: [references/api.md](references/api.md). Antipatterns: [references/antipatterns.md](references/antipatterns.md).
