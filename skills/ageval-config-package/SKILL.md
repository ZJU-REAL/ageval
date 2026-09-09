---
name: ageval-config-package
description: >
  Author ageval datasets (ageval.yaml + tasks/*/task.yaml, run.py/evaluator.py,
  profiles.yaml, environment kinds local|docker|e2b|ssh|daytona, limits, gold isolation,
  script vs LLM-as-judge scoring). Dataset README Run commands start with `ageval`
  (CLI already installed). Never `uv run ageval` or `.venv/bin/ageval`. Triggers:
  ageval.yaml, task.yaml, profiles.yaml, dataset, environment kind, evaluator.py.
  Never secrets in yaml. Never provider.kind.
---

# Config / dataset + task

Config Core is the only normative reader. Delivery unit is a **dataset** root.

```text
my-dataset/                 # CLI path (ageval.dataset/1)
├── ageval.yaml
├── profiles.yaml           # THE job (lock/run default). ageval publish also packs every root profiles*.yaml
├── env.example
├── shared/lib/             # optional; import shared.lib.*
└── tasks/<task_id>/
    ├── task.yaml           # ageval.task/1 — roles + intent
    ├── run.py              # async def run(ctx)
    ├── evaluator.py
    ├── environment/        # Dockerfile, setup.sh, compose
    ├── evaluation/         # gold — not for Agent
    └── data/               # seed
```

CLI: `ageval lock|run <dataset-root> --task <id>`.

**Reader-facing README / docs:** commands start with `ageval`. The reader already has the CLI. Do not write `uv run ageval`, `uv run ageval lock`, `.venv/bin/ageval`, or `AGEVAL=/path/to/...` wrappers. Agent-internal notes (this skill, AGENTS.md) may name a venv binary; dataset README may not.

Dataset README introduces **this dataset** (identity, `profiles.yaml`, layout, `ageval lock|run`, conversion, known gaps). It does **not** document local `.ageval/suite-runs` ids, P/F/E counts, or leaderboard rows. Those are `upload-suite` later, not package copy.

Files present are recognized. Do not re-declare `run.py` entrypoints in yaml. Do not put `executor` / `api_key` on the member task. Do not write `provider.kind` or `assurance`.

```yaml
# ageval.yaml
format: ageval.dataset/1
dataset_id: org/my-suite
version: "0.1.0"
tasks:
  root: tasks
```

```yaml
# profiles.yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: acp
    api_key: ${ZHIPU_API_KEY}
    options: { entry: pi }
    extensions:
      - plugin: acp
      - plugin: docker
```

Gold lives in `evaluation/` and is uploaded at evaluate, not before. `setup.sh` is the last environment slot.

Two scoring styles in `evaluator.py` (same barrier; PASS still the return value):

| Style | When | Evidence |
| --- | --- | --- |
| Deterministic script | Default. Compare artifacts to gold. No `Agent.session`. | `result.json`. No `evaluation/observation.jsonl`. |
| LLM-as-judge | Extra role on the **same** `profiles.yaml` (e.g. `judge`). After gold lands, `Agent.session("judge").invoke`. | `evaluation/observation.jsonl` (no `user` rows). Not merged into Agent `trajectory.jsonl`. |

Judge binding stays in `profiles.yaml` (not on the member task). Budget `limits.agent_invocations` for solver **and** judge. SDK session into the evaluator process is projected on `environment: local`. No `Agent.session` = script path.

`--profiles` swaps the job for **this** lock/run. `--agent` is mutually exclusive with `--profiles`. `--model` requires `--agent`.

### `profiles.yaml` vs extra `profiles*.yaml`

| | Default job (`ageval run <root>`) | `ageval publish` / packageDigest |
| --- | --- | --- |
| `profiles.yaml` | **this file only** | included |
| sibling `profiles*.yaml` at dataset root | ignored unless `--profiles` | **included** (`member_paths_for_digest` / tarball). Overlays those docs declare also enter. |

Hub consumers who `ageval run official/…@ver` without `--profiles` get **`profiles.yaml`**. Extra `profiles.acp.*.yaml` at the root still **ship in the package** and change digest. Experiment jobs that must not be on Hub do not live as `profiles*.yaml` under the dataset root.

Hub comparability still uses suite fingerprint / `upload-suite`. Do not add `n_attempts` to yaml.

Field catalog: [references/ageval-yaml.md](references/ageval-yaml.md). Isolation: [references/isolation.md](references/isolation.md). Conversion: [references/conversion.md](references/conversion.md).
