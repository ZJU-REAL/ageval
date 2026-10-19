# tau3-airline-5 (ageval Dataset)

Port of **τ³-bench / tau2-bench** `airline` domain onto ageval outer lifecycle.

In-repo this is an **abbreviated** dataset: **five** members (`airline-00` … `airline-04`).
The upstream domain has 50 tasks; that full cut is not checked into this repository; it ships via Hub as `official/tau3-airline`.

| Field | Value |
| --- | --- |
| Upstream | https://github.com/sierra-research/tau2-bench @ `v1.0.1` |
| Domain | airline (in-repo: 5 tasks, `airline-00`…`airline-04`) |
| Agents | `user` + `service` via `profiles.yaml` → `openai-http` GLM Coding Plan (`glm-5.3`) |
| Bridge | ageval Agent ACP ↔ tau2 `Environment` tools + `evaluate_simulation` |
| Shared | Dataset-level `shared/lib` + `shared/assets` (`from shared.lib…`) |

## Layout

```text
ageval.yaml / profiles.yaml
shared/                 # real package (shared/__init__.py)
  lib/                  # shared.lib.harness_core / bridge / evaluator_core
  assets/               # db.json, policy.md, tasks.json (in packageDigest)
tasks/airline-NN/
  task.yaml / run.py / evaluator.py       # thin; import shared.lib.*
  data/                 # agent-visible scenario + policy copy
  evaluation/           # gold / full task JSON (evaluator-only)
```

No per-task `lib/` copies — modules live once under `shared/lib` and are imported
as `shared.lib.*` (Runtime puts the dataset root on `sys.path`, not the `lib/` leaf).

## Run

```bash
uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00
uv run ageval run  examples/datasets/tau3-airline-5 --task airline-00
uv run ageval run  examples/datasets/tau3-airline-5   # five in-repo members
uv run python scripts/check_shared_lib_collisions.py examples/datasets/tau3-airline-5
```

Host needs `tau2==1.0.1` (see `requirements.txt`) for tools/DB scoring.

## Evidence notes

- Attempt PASS only from independent evaluator (tau2 ENV+COMMUNICATE product).
- Gold lives under each task's `evaluation/` (not under `shared/`).
- Presence of this package / Hub Shared UI does not make the evaluation results more credible.

## Generate members

The in-repo cut is `--ids 0,1,2,3,4`. `--all` expands locally from `shared/assets/tasks.json`;
do not commit the full 50-task tree here.

```bash
python examples/datasets/tau3-airline-5/scripts/generate_package.py --ids 0,1,2,3,4
```
