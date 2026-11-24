# Conversion & multi-task package authoring

Author-facing patterns for porting upstream benchmarks into an ageval **dataset**.
Authority: `docs/design/03-task-sdk-and-evaluation.md`, `docs/design/02-schemas-and-config.md`.

## When to use a generator

| Signal | Action |
| --- | --- |
| ≥ ~5 isomorphic members (same `run.py` / eval shape) | Prefer `scripts/generate_package.py` (or equivalent) |
| Members differ only by scenario id / params / data | Thin `task.yaml` + `data/` / `evaluation/` per task; shared orchestration |
| One-off demo task | Inline `run.py` is fine; still respect gold isolation |

### Generator shape (reference)

1. Read upstream assets (often under `shared/assets/` or an external path).
2. Emit `tasks/<task_id>/task.yaml` with `provenance` filled.
3. Emit thin `run.py` / `evaluator.py` that import **`shared.lib.*`**.
4. Write per-task `data/` (agent-visible) and `evaluation/` (gold) as needed.
5. Stay idempotent: re-run regenerates members without hand-editing fifty files.

Do not write `provider.kind` / `assurance`. Generate `run.py`.

### Import migration

| Old (leaf inject) | New (dataset root on path) |
| --- | --- |
| `from harness_core import run` | `from shared.lib.harness_core import run` |
| `from bridge import make_environment` | `from shared.lib.bridge import make_environment` |
| `from evaluator_core import evaluate` | `from shared.lib.evaluator_core import evaluate` |

Shared glue lives under `shared/lib`; the task entry is `run.py`.

## Upstream → ageval owner map

| Upstream concept | Put under | Consumer | Never |
| --- | --- | --- | --- |
| Instruction / prompt / agent-visible files | `tasks/<id>/data/` | Agent seed / `ctx.params` | Gold under `data/` |
| Hidden tests / labels / expected answers | `tasks/<id>/evaluation/` | Evaluator only | `shared/`, Agent mount |
| Container image / apt / system deps | `tasks/<id>/environment/Dockerfile` | docker / e2b `host.start` | Runtime `apt`/`pip` as parity default |
| Domain tools / bridge / dual-agent loop | `shared/lib/` (multi-task) or `tasks/<id>/lib/` | `run.py` + evaluator import | Gold files |
| Shared policies / DB dumps / static assets | `shared/assets/` | Code paths | Agent default mount of gold |
| Offline known-good workspace files | `tasks/<id>/solution/` | Human / CI / offline flag only | Default Agent seed |
| Job binding (executor / entry / model) | dataset `profiles.yaml` (default job) | Runtime / job overlay | Secrets in yaml; extra `profiles*.yaml` at dataset root also enter `ageval publish` / packageDigest |

## Scenario cut

- One upstream scenario / one stable role topology → one dataset (`ageval.yaml`).
- Vary task business parameters and `data/` / `evaluation/` per member, not role topology.
- Different scenarios → separate datasets.

## Thin multi-task template

```text
shared/
  lib/
    run_core.py          # async run(ctx, *, task_dir)
    evaluator_core.py
    bridge.py
tasks/task-00/
  run.py                 # from shared.lib.run_core import run as _run
  evaluator.py
  data/ … evaluation/
```

## Durable `run-meta` (and other required evaluation inputs)

If a member declares `run-meta` (or any other post-invoke metadata) as a published artifact / `evaluation_inputs` entry, the shared runner (`shared/lib/run_core.py` or equivalent) must still produce that file after a normal return, a raised error, a wall-clock or invocation timeout, and SIGTERM.

Do not write it only after `invoke()` returns. A killed or crashing worker never reaches that line, and evaluate then records `missing_evaluation_input` instead of calling the evaluator.

1. Publish a neutral placeholder **before** `invoke`. The parent may `SIGKILL` the run worker at `limits.wall_time_seconds`; `finally` and signal traps do not run in that case.
2. Refresh the same artifact in `try` / `finally` (or an equivalent `trap` / SIGTERM handler for shell runners) so normal completion, raised errors, cooperative cancellation, and SIGTERM overwrite the placeholder with terminal details.

On interrupt, record at least:

| Field | Meaning |
| --- | --- |
| `exit_reason` | Why the run stopped: `completed`, `error`, `cancelled`, `sigterm`, or `timeout` |
| `timed_out` | `true` when the stop was a wall-clock or invocation timeout |
| `ok` | Whether the invoke itself succeeded |
| `error` | Error string when one is available; otherwise `null` |

Keep any dataset-specific fields already in the placeholder (`seeded`, `upstream_task_id`, …).

```python
meta = {
    "ok": False,
    "error": None,
    "text_len": 0,
    "exit_reason": "running",
    "timed_out": False,
    "upstream_task_id": params.get("upstream_task_id"),
}
ctx.publish_json("run-meta", meta)
try:
    async with agent.session(profile_id, max_turns=max_turns) as session:
        inv = await session.invoke(instruction)
    meta.update({
        "ok": bool(inv.get("ok")),
        "error": inv.get("error"),
        "text_len": len(str(inv.get("text") or "")),
        "exit_reason": "completed",
    })
except asyncio.CancelledError:
    meta["exit_reason"] = "cancelled"
    meta["timed_out"] = True  # set only when this cancel is a timeout
    raise
except Exception as exc:
    meta["exit_reason"] = "error"
    meta["error"] = str(exc)
    raise
finally:
    ctx.publish_json("run-meta", meta)
```

A SIGTERM handler should set `exit_reason` to `sigterm` (and `timed_out` if that signal is the wall-clock stop), publish, then re-raise or exit.

## Conversion checklist

- Required evaluation inputs such as `run-meta` still exist when the worker is killed or the runner raises (placeholder before invoke; final write in `finally` / trap).

## Official base `ageval-attempt:base`

When the port `FROM`s the official tag (historical name, CPython 3.12) instead of the vendor instance image, re-check every migrated `RUN pip` / `apt` against this base. A green `docker build` that never imports the hidden tests still ERROR at collection.

Details: `references/isolation.md`.

## Evidence / claims

- Conversion completeness, Hub package publish, or `ageval lock` success **do not** upgrade evidence grade.
- PASS only from the independent evaluator after barrier.
- Fill `provenance` for ports; known gaps stay honest.
