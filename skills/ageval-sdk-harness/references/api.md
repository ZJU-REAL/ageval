# ageval_sdk public surface (shipped)

Package: `ageval_sdk` (see `src/ageval_sdk/`, same distribution as `ageval`).

## Types

| Symbol | Role |
| --- | --- |
| `RunContext` | params, workspace, artifact_dir, agent, publish |
| `RunScope` | attempt/trial/run identity (parent-owned) |
| `Agent` | factory for sessions bound to attempt |
| `AgentSession` | `open` / `invoke` / `close` via parent socket |
| `Tool` / `ToolSet` | local tools |
| `AllowList` / `CallLimit` | soft local guards |
| `RunTerminal` | completed / failed — not PASS |
| `bounded_gather` / `collect_results` / `first_success` | workflow helpers |
| `evaluation_check` | optional `checks` row for the evaluator return; not PASS |

## AgentSession.invoke return keys (parent path)

Includes `ok`, `error`, `text`, `structured`, `provider_session_handle`, `invocation_id`, `evidence_relative`, and `tool_calls` (list of `{id, name, arguments}`; empty when the turn is text-only).

Optional invoke kwargs: `tools` (OpenAI-style catalog) and `messages` (chat history). Omit both for prompt-only invoke. Profile / workspace / executor overrides stay rejected. ACP ignores the catalog.

## Offline

When `AGEVAL_OFFLINE_AGENT=1`, invoke fails closed (`offline_forced`) — never stub PASS on public paths.

## Evaluator (optional)

`evaluator.py` may construct `Agent(attempt_id=…)` or use injected `inputs["agent"]` when `AGEVAL_AGENT_SERVICE_SOCK` is set. Same `Agent.session(profile_id).invoke` as `run.py`. Evaluate-phase turns fold to `evaluation/observation.jsonl` (omit `user`). Optional `checks` on the return (helper `evaluation_check`) persist as `evaluation/checks.json`. Neither file is PASS.

Design: `docs/design/03-task-run-and-sdk.md`.
