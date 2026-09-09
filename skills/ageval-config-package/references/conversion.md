# Conversion & multi-task package authoring

Author-facing patterns for porting upstream benchmarks into an ageval **dataset**.
Authority: `docs/design/08-conversion-security-testing.md`, `docs/design/02-task-package-and-config.md`.

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

## Official base `ageval-attempt:base`

When the port `FROM`s the official tag (historical name, CPython 3.12) instead of the vendor instance image, re-check every migrated `RUN pip` / `apt` against this base. A green `docker build` that never imports the hidden tests still ERROR at collection.

Details: `references/isolation.md`.

## Evidence / claims

- Conversion completeness, Hub package publish, or `ageval lock` success **do not** upgrade evidence grade.
- PASS only from the independent evaluator after barrier.
- Fill `provenance` for ports; known gaps stay honest.
