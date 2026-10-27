# 03 — Task SDK (`ageval_sdk`), Isolated Evaluation, and Conversion Rules

This specification defines the task-script process boundary (`run.py` and `evaluator.py`), the public API of **`ageval_sdk`**, solver sealing and reference material (`gold`) isolation, artifact harvesting (`file`, `tree`, and `evaluation.collect`), grading strategies (`evaluator.py`, Agent-as-Judge, `checks.json`, Harbor rewards), and benchmark conversion conventions.

Implementation modules live in `src/ageval_sdk/`, `src/ageval/attempt/phases/evaluate.py`, `src/ageval/attempt/artifact_harvest.py`, and `src/ageval/evaluation/`.

---

## 1. Scope and Process Isolation Invariants

1. **Subprocess isolation**: The parent control plane executes `tasks/<id>/run.py` (`async def run(ctx: RunContext) -> RunTerminal`) and `tasks/<id>/evaluator.py` inside isolated worker subprocesses (`src/ageval/runtime/task_worker.py` and `eval_worker.py`) rather than importing task modules in-process.
2. **One-way SDK dependency**: `ageval_sdk` imports only public DTOs and protocol shapes and NEVER imports `ageval` control-plane internals, never mints Attempt identity, never reads host credentials, never starts/stops environments, and never binds `PASS` or `FAIL`.
3. **Evaluation barrier and gold isolation**: Reference materials under `tasks/<id>/evaluation/` (`gold`) remain unmounted during `environment` and `run`. They are uploaded to the scoring host only after `seal_run` drains all solver sessions and `AttemptCtx.assert_writers_stopped()` succeeds at the entry of `evaluate`. A terminal-action replay does not run `run.py`. Gold stays unmounted through that run phase. `--evaluate` enters `evaluate` and uses `evaluator.py`. Without `--evaluate`, the evaluate phase does not run.
4. **Verdict exclusivity**: `PASS` and `FAIL` enter `Result` exclusively through `AttemptCtx.bind_evaluation` during `evaluate`. `RunTerminal.completed`, trajectory completion, ACP `end_turn`, raw judge text, individual `checks` exit codes, and replay completion never set `Result.status` to PASS or FAIL.

| `run.py` Owns | `run.py` Must Never Do |
| --- | --- |
| Orchestrating single-turn or multi-turn interaction loops, multi-role routing, domain tool execution, and publishing workspace artifacts via `ctx.publish_json` / `ctx.publish_tree`. | Issue `PASS` or `FAIL` verdicts, read `evaluation/` reference materials, read host credential files, or invoke `host.start` / `host.stop`. |

---

## 2. Public `ageval_sdk` API Surface

```python
from ageval_sdk import (
    Agent,
    AgentSession,
    RunContext,
    RunParameterView,
    RunScope,
    RunTerminal,
    ScriptError,
    Tool,
    ToolSet,
    AllowList,
    CallLimit,
    bounded_gather,
    first_success,
    evaluation_check,
)
```

| Exported Symbol | Contract and Responsibility |
| --- | --- |
| `RunContext` | Passed to `async def run(ctx: RunContext) -> RunTerminal`. Exposes `ctx.params` (`RunParameterView` supporting dotted lookup), `ctx.workspace_root` (`Path`), `ctx.artifact_dir` (`Path`), `ctx.scope` (`RunScope`), `ctx.agent` (`Agent`), `ctx.publish_json(id, data)`, and `ctx.publish_tree(id, path)`. |
| `RunTerminal` | Return type of `run.py`: `RunTerminal.completed(summary_str)` or `RunTerminal.failed(reason_str)`. Does not set `Result.status` to `PASS`. |
| `ScriptError(title, message)` | Raised by `run.py` or `evaluator.py` to abort the current phase with a deterministic `Result.error` `{phase, title, message}` (`status: "ERROR"`). |
| `Agent` / `AgentSession` | Opens logical sessions bound to a role `profile_id` via `ctx.agent.session(profile_id, *, max_turns=8, actor_id=None, environment=None)`. |
| `Tool` / `ToolSet` / `AllowList` / `CallLimit` | In-process domain tool registry and soft call-count guardrails for `run.py` (supplementing, never replacing, Core `limits`). |
| `bounded_gather` / `first_success` | Structured async concurrency primitives bounded by `limits.agent_concurrency`. |
| `evaluation_check` | Helper for constructing validated step items in `evaluator.py`'s optional `checks` return list. |

### 2.1 Structured tool calling (`tools` and `messages`) and `record_observation`

`AgentSession.invoke(prompt, *, tools=None, messages=None, request_id=None)` supports both plain-text instruction turns and multi-turn structured tool-calling loops. Session ids are `sess_{profile}_{actor|default}_{environment|main}_{ordinal}` and request ids are `req_{session_id}_turn_{n}` unless the caller passes `request_id`. A restarted `run.py` therefore hits the same ids; a completed invoke returns the logged result, and a conflicting prompt for that id fails the Attempt as `session_alignment_mismatch`.

```python
reply = await session.invoke(instruction, tools=OPENAI_TOOLS, messages=history)
for call in reply.get("tool_calls") or ():
    obs = await tools.call(call["name"], call["arguments"])
    await session.record_observation(
        str(call.get("id") or ""),
        content=str(obs),
        raw_output=obs,
        function_name=str(call.get("name") or ""),
        invocation_id=reply.get("invocation_id"),
    )
```

- **HTTP executors (`openai-http`, `anthropic-http`)**: Encode `tools` and `messages` into the bound API format and return structured calls in `reply["tool_calls"]` (`[{id, name, arguments}]`). `session.record_observation(...)` appends the domain tool observation to the invocation's trajectory without consuming `limits.agent_invocations`.
- **ACP executor (`executor: acp`)**: Ignores `tools` and `messages` kwargs because the in-environment coding agent manages its own native tool loop from the text `prompt`.

### 2.2 Multi-session concurrency (`bounded_gather` and `first_success`)

`AgentSession` socket operations are fully asynchronous. A single Attempt may open multiple concurrent sessions (including multiple independent sessions bound to the same `profile_id`, each maintaining isolated history). Calls within a single `session_id` execute serially in arrival order; calls across distinct sessions overlap up to `limits.agent_concurrency` on executors declaring `concurrent_sessions = True`.

- **`bounded_gather(aws, *, limit, timeout=None)`**: Runs an iterable of awaitables with at most `limit` in flight and returns results in input order. An exception raised by one branch is returned at that index without cancelling sibling branches. If `timeout` (seconds) expires, unfinished slots receive `TimeoutError` and remaining in-flight tasks are cancelled and drained (`op: cancel`).
- **`first_success(aws, *, limit=None, accept=None)`**: Runs awaitables up to `limit` concurrency and returns the first result that does not raise and satisfies `accept(result)` (default: truthy), then immediately cancels and drains all remaining branches. If no branch succeeds, raises `RuntimeError("no acceptable result")`.

---

## 3. Isolated Evaluation and Reference Material (`gold`) Isolation

```text
run phase end
  → seal_run: cancel queued solver calls, drain in-flight solver calls, close solver sessions
  → mark_writers_stopped (ParentAgentService stays open for evaluate-phase judge profiles)
  → harvest artifacts.publishable into evidence/task-artifacts/ (file or filtered directory tree)

evaluate phase
  before_evaluate
  evaluation.collect            # Optional: run collect commands & copy absolute paths into evidence/verifier-collect/
  [isolated, no named map] start isolated Docker scoring container (evaluate.Dockerfile or evaluation.docker_image)
  [no named map] upload task-artifacts/, verifier-collect/, and evaluation/ (gold) to scoring host
  [isolated, no named map] emit after_environment_ready for evaluate-phase ACP profiles
  evaluation_runtime.evaluate   # Exclusive slot (default: subprocess evaluator.py)
                                # Named evaluation.environments: lazy start on first scoring.exec or session(environment=)
                                # Optional: evaluator.py invokes Agent.session("<judge>")
  bind_evaluation               # Sole entry point for Result.status (PASS or FAIL)
  after_evaluate                # May attach supplementary metrics; cannot alter Result.status

cleanup phase (finally)
  stop all started isolated/named scoring containers + stop run environment
```

### 3.1 Three scoring host isolation modes
1. **Phase-boundary isolation (default when `evaluate_host` is omitted)**: Reuses the `run` environment after solver sessions are sealed, uploads `evaluation/` to `/attempt/evaluation`, and runs `evaluator.py`.
2. **Single isolated scoring container (`evaluate_host.isolated: true`)**: Starts a dedicated Docker container from `environment/evaluate.Dockerfile` (or `evaluation.docker_image`). Harvested `task-artifacts/`, `verifier-collect/`, and `evaluation/` are uploaded only to this scoring container; the solver environment never receives `evaluation/` at any point in its lifetime.
3. **Multiple named scoring containers (`evaluation.environments`)**: Declared in `task.yaml` when different grading checks require distinct container images (requires `evaluate_host.isolated: true` and `environment: docker`). Each named container is started lazily on the first `await scoring.exec("<name>", argv)` or `ctx.agent.session("<judge>", environment="<name>")` call from `evaluator.py`, receiving its own copy of harvested artifacts and `evaluation/`. Unused named containers are never built or started.

### 3.2 Artifact harvesting (`artifacts.publishable`) and `evaluation.collect`
- **`artifacts.publishable`**: Snapshots each declared artifact into `evidence/task-artifacts/` at the end of `run`. `kind: file` (default) copies a single file; `kind: tree` snapshots a directory (such as `path: workspace`) applying optional `exclude` globs (`["target", "*.so", ".git"]`) and preserving symlinks without dereferencing host paths. When `evaluation.inputs[].target` is `"workspace"`, the tree snapshot is restored into `/attempt/workspace` on the scoring host.
- **`evaluation.collect`**: Runs at the start of `evaluate` to extract absolute paths (`path`, optional `service` defaulting to `"main"`, optional `command` with `timeout_sec` defaulting to `60`, and optional `exclude`) into `evidence/verifier-collect/`. Execution order is fixed: (1) all `command` entries on `main` → (2) all `path` copies from `main` → (3) all `command` entries on Compose sidecars → (4) all `path` copies from Compose sidecars. Any non-zero command exit code or missing path terminates `evaluate` as `ERROR` (`environment_collect_failed` or `environment_collect_missing`).

---

## 4. Grading Strategies: Agent-as-Judge, Step `checks`, and Harbor Rewards

1. **Agent-as-Judge (`Agent.session("<judge>")`)**: Tasks may declare a separate judge role in `task.yaml` and `profiles.yaml`. Judge invocations execute serially during `evaluate`, do not consume `limits.agent_invocations` or `limits.agent_concurrency`, and write their trajectory to `evaluation/observation.jsonl` with `user` prompt rows omitted so reference material (`gold`) embedded in judge prompts is never exposed in public trajectory archives.
2. **Structured step checks (`evaluation/checks.json` — `ageval.evaluation.checks/1`)**: `evaluator.py` may return an optional `checks` list constructed via `evaluation_check(id, *, status, score=..., script=..., environment=..., exec_result=...)`. Individual check statuses are observational in Viewer and Hub (`Verifier` tab) and never override the top-level `status` and `score` passed to `bind_evaluation`.
3. **Built-in Harbor reward grading (`--layout harbor`)**: Executes `tests/test.sh` after sealing the solver and reads `/logs/verifier/reward.json` (or fallback `/logs/verifier/reward.txt`). Primary key `"reward"` (or single key) with value `1`, `1.0`, or `true` binds `PASS`; `0`, `0.0`, or `false` binds `FAIL`; missing or unparseable reward files produce `ERROR` (`title: "harbor_reward_missing"`), never `FAIL`.

---

## 5. Benchmark Conversion and Verification Standards

1. **Thin task scripts + `<dataset_root>/shared/lib`**: Extract reusable interaction loops, domain tool bridges, and common grading helpers into `<dataset_root>/shared/lib/` (`from shared.lib... import ...`). Record upstream `provenance` (repository URL, commit/version, adaptation notes) in `ageval.yaml` or `task.yaml`.
2. **Explicit `shared/` copy for in-container scripts**: Docker image builds do not implicitly copy `<dataset_root>/shared/`. If an in-container helper script needs `shared.lib.*`, the task's `Dockerfile` must `COPY` it explicitly and set `PYTHONPATH`.
3. **Fidelity checks**: `ageval lock` and `ageval run` on a real `local` or `docker` environment. The product has no `executor: mock`. No credential, or `AGEVAL_SKIP_REAL_ACP=1`: record **skipped**. Parser, lock, and phase tests use fixtures.
