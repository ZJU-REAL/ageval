---
name: ageval-cli
description: >
  Operate ageval CLI (lock/run/plugin/view/publish/release/executors/campaign/evidence/status/cancel/jobs/results):
  flags, --set pointers, exit codes, --probe, offline agent path (AGEVAL_OFFLINE_AGENT),
  ACP entry readiness, plugin install, suite upload. Use when running ageval lock/run, PASS/FAIL/ERROR,
  trajectory export, Hub upload. Do not invent flags.
---

# ageval CLI

```bash
uv sync --frozen --all-packages
uv run ageval --help
```

Public commands: `ageval lock` `ageval run` `ageval campaign` `tasks` `jobs` `view` `plugin` `evidence` `ageval status` `ageval cancel` `executors` `publish` `release` `login` `agent` `registry` `cache` `results`. No `submit`. Path arguments are **dataset** roots. `ageval view` also accepts a directory of dataset roots.

```bash
uv run ageval lock examples/core --task config-minimal
uv run ageval run  examples/core --task acp-local-min
uv run ageval run  examples/core --task acp-docker-min --profiles examples/core/profiles.docker.yaml
uv run ageval run  examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval run  official/demo@0.1.0 --dir tmp
uv run ageval view official/demo@0.1.0
uv run ageval run  … --probe          # lock + preflight, no Agent
uv run ageval executors -v
uv run ageval plugin install plugins/nooa
```

`--profiles` replaces the dataset's default `profiles.yaml`. `--agent` and `--profiles` are mutually exclusive. `--agent pi` (and other shipped short ids) needs no `agent install`. `--model` requires `--agent` and overrides this run’s `model.id` (not `ageval results upload-suite --model`). `ageval results analyze` is separate: default analyzer `stats`; `hack` and `review` take `--agent` plus `--model` for an `openai-http` or `anthropic-http` package. Analysis does not change PASS or `evaluation/checks.json`. `--set` allowlist: `/parameters/seed`, `/parameters/active_profile`, `/agent_profiles/<role>/{model,model/id,model/api,model/timeout,model/watchdog,model/reasoning/effort,executor,api_key,base_url,options/<key>}`. `model` is a nested object. Not `limits.*`.

TTY prints a short recap (no digest / sha256). A pipe keeps JSON. `ageval run --json` forces the run document.

Exit: 0 PASS / probe ready; 1 FAIL / probe not ready; 2 ERROR.

Single Attempt evidence: `<dataset>/.ageval/runs/<id>/` (`lock.json`, `result.json`, `trajectory.jsonl`; optional `evaluation/observation.jsonl` for evaluate-phase SDK invoke; optional `evaluation/checks.json` for evaluator `checks`).

`--probe` missing `E2B_API_KEY` or ssh locator → ready false, started false.

Offline: `AGEVAL_OFFLINE_AGENT=1` must not PASS agent tasks.

Hub Leaderboard needs suite upload (`ageval results upload-suite`), not a lone `results upload`.

`ageval results regrade <dataset> --run <attempt_id>` scores a finished Attempt again from `task-artifacts/` and `verifier-collect/` (new Attempt, no agent run, collect commands are not re-run). Default `--resume-suite` skips ERROR; `--retry-errors` re-runs those slots. `--replace-slot` still replaces one named slot.

Flags: `uv run ageval <cmd> --help`. Source: `src/ageval/cli/main.py`.

Detail: [references/commands.md](references/commands.md), [references/failures.md](references/failures.md).
