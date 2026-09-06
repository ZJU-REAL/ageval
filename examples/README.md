# ageval examples

Tracked **datasets** for public smokes, case-class demos, catalog Agents, and
one abbreviated popular-bench conversion.

```text
examples/
├── agents/           # ageval.agent/1 (cc/pi/codex/opencode/dsh/nooa/miniswe)
└── datasets/
    ├── minimal-demo/   # dataset official/minimal-demo — case-class fidelity
    └── tau3-airline-5/   # dataset official/tau3-airline-5 — 5-task airline cut
```

There is no product `executor: mock`. Offline lock uses the real kinds; a missing
credential fails closed. Bind a real Agent with `--agent` or `--profiles`.

CLI path is always the dataset root (`ageval.yaml`):

```bash
uv run ageval lock  examples/datasets/<dataset> --task <task_id>
uv run ageval run   examples/datasets/<dataset> --task <task_id>
uv run ageval tasks examples/datasets/<dataset>
```

## Suite

```bash
# Full dataset (omit --task); concurrency from CLI or dataset defaults
uv run ageval run examples/datasets/minimal-demo --max-concurrent-tasks 2
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg
```

## Smoke

Default `minimal-demo` profiles use `environment: docker`. `--probe` is lock +
preflight only.

```bash
uv run ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00   # conversion; tau2 pin for run
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval tasks examples/datasets/minimal-demo

# Expected failures
uv run ageval lock examples/datasets/minimal-demo --task does-not-exist   # exit ≠ 0
```

## `datasets/minimal-demo/` (`dataset_id: official/minimal-demo`)

| Task                                                                         | Case class                  |
| ---------------------------------------------------------------------------- | --------------------------- |
| [`multiagent-env-min`](datasets/minimal-demo/tasks/multiagent-env-min/)     | Multi-session + SQL tools   |
| [`tau2-dialog-min`](datasets/minimal-demo/tasks/tau2-dialog-min/)           | Dual-role dialog + tools    |
| [`terminal-jsonl-agg`](datasets/minimal-demo/tasks/terminal-jsonl-agg/)     | workspace file + clean eval |

### External nooa plugin (optional profiles)

NVIDIA [OO Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents) path: real LiteLLM
calls via profile `model` / `base_url` / `api_key` (env locator). Install never
rewrites dataset profiles — bind with a separate profiles file:

```bash
uv sync --extra nooa
uv run ageval plugin install plugins/nooa
# repo/.env: litellm_api_key (+ litellm_base_url) or set profile base_url
unset AGEVAL_OFFLINE_AGENT
uv run ageval run examples/datasets/minimal-demo --profiles examples/datasets/minimal-demo/profiles.nooa.yaml
```

Package agents under each task’s `lib/agents.py` are `nooa.Agent` subclasses
(generation methods). Invoke runs the in-environment worker through `host.exec` and
projects locators into that exec env. Docker bake installs `nooa` so the
environment Python can import it.

### External dsh plugin (optional profiles)

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) path: official
JSON-RPC SDK (`deepseek-harness-sdk`), not ACP. Same `minimal-demo` `run.py`; bind
`executor: dsh` + `extensions: [{plugin: dsh}]` + `model` + locator
`deepseek_api_key`. Invoke runs the in-environment worker through `host.exec`. Docker
bake installs the wheels in the Attempt image — `--extra dsh` is for the local
kind's interpreter. `executor:` alone does not bake.

```bash
uv run ageval plugin install plugins/dsh
# repo/.env: deepseek_api_key (projected as DEEPSEEK_API_KEY)
unset AGEVAL_OFFLINE_AGENT
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.dsh.yaml
```

This task writes `aggregates.json`, so omit `options.permission` or use
`workspace-write`. `read-only` fences DSH file-tool writes only; bash can still
write on the bundled jsonrpc runtime. That is not ageval isolation.

### Probing without invoking

```bash
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg --probe
# missing extras or keys: --probe reports ready: false / started: false
# live ACP stdio over ssh A is unsupported
```

## `datasets/tau3-airline-5/` (`dataset_id: official/tau3-airline-5`)

Popular-bench **port** of [tau2-bench](https://github.com/sierra-research/tau2-bench)
`airline` (τ³-bench) as **one domain = one dataset**. Dual-role dialog
(`user` + `service` via `profiles.yaml` → `openai-http` GLM Coding Plan) with package-local tools/DB
bridge and independent evaluator (tau2 ENV+COMMUNICATE). Default environment is `local`.

In-repo this is a **five-task cut** (`airline-00` … `airline-04`). The upstream domain
has 50 tasks; that full suite is not checked in.

| Item         | Notes                                                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Upstream pin | `tau2-bench` @ `v1.0.1` (`fc0055dc…`); paper [2506.07982](https://arxiv.org/abs/2506.07982)                                                            |
| Members      | **5** tasks: `airline-00` … `airline-04` (upstream ids `0`…`4`)                                                                                       |
| Layout       | Dataset-level [`shared/lib`](datasets/tau3-airline-5/shared/lib/) + [`shared/assets`](datasets/tau3-airline-5/shared/assets/); **no** per-task `lib/` copies |
| Gold         | Under each `tasks/airline-NN/evaluation/` only — not under `shared/`                                                                                   |
| Host deps    | `tau2==1.0.1` (see [`datasets/tau3-airline-5/requirements.txt`](datasets/tau3-airline-5/requirements.txt)) for run/eval                                    |
| Evidence     | **Not** a public smoke upgrade path; package / Hub publish **≠** `real-benchmark-verified`                                                             |

```bash
uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00
uv run ageval tasks examples/datasets/tau3-airline-5
uv run python scripts/check_shared_lib_collisions.py examples/datasets/tau3-airline-5
# Five-task in-repo suite (needs agent credentials + tau2):
# uv run ageval run examples/datasets/tau3-airline-5
```

Package-local detail: [`datasets/tau3-airline-5/README.md`](datasets/tau3-airline-5/README.md).
Regenerate the in-repo cut:
`python examples/datasets/tau3-airline-5/scripts/generate_package.py --ids 0,1,2,3,4`.

## `agents/` (`ageval.agent/1`)

Catalog Agent **harness** packages (`binding.model` is the default, not identity).
Built-in Agent packages (`pi`, `opencode`, …) ship with ageval. These trees are custom
overlay examples: install, then bind with `--agent` (mutually exclusive with
`--profiles`). Optional `--model` overrides this run:

```bash
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg --agent pi --model glm-4.7
uv run ageval agent install examples/agents/pi-default
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg --agent local/pi-default@0.1.0
```

## Hub-only conversions

This monorepo keeps **minimal-demo** plus a **five-task** `tau3-airline-5` cut under
`examples/datasets/`. Larger popular-bench ports (including the full 50-task airline
domain) stay **out of `examples/`** and ship as **Hub packages** (publish + suite
upload), so clone size and CI paths stay bounded:

| Upstream           | Hub package id (org `my-lab`)                    | Notes                                 |
| ------------------ | ------------------------------------------------ | ------------------------------------- |
| Terminal-Bench 2.0 | `terminal-bench-2` / light `terminal-bench-2-10` | Docker + Harbor pytest-style verifier |
| MARBLE coding      | `marble-coding` / light `marble-coding-10`       | shared-container multi-agent coding   |

Package presence, Hub publish, or a suite job on the board does not make the evaluation results more credible.

## Suggested first runs

```bash
uv run ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval lock examples/datasets/tau3-airline-5 --task airline-00
```
