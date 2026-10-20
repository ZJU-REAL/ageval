# minimal-demo (ageval Dataset)

Smallest end-to-end dataset in the repo: three tasks, one per agent-eval
**case class**. Used by docs, acceptance tests, and the Hub as the canonical
"does a binding work?" package.

| Field | Value |
| --- | --- |
| dataset_id | `official/minimal-demo` |
| Version | `0.1.3` |
| Format | `ageval.dataset/1` |
| Default binding | `profiles.yaml` → docker + ACP (`pi`) |
| Published | `official/minimal-demo@0.1.3` on the configured Registry (public) |

## Tasks

| Task | Case class |
| --- | --- |
| [`terminal-jsonl-agg`](tasks/terminal-jsonl-agg/) | workspace file + clean eval (single session) |
| [`tau2-dialog-min`](tasks/tau2-dialog-min/) | dual-role dialog + tools |
| [`multiagent-env-min`](tasks/multiagent-env-min/) | multi-session + SQL tools |

Provenance is a **reimplementation**: parity claimed at the protocol level only
(upstream: [terminal-bench](https://github.com/laude-institute/terminal-bench);
see each `task.yaml` for per-task detail).

## Layout

```text
ageval.yaml               # dataset manifest (dataset_id / version)
env.example               # copy to .env; locator names only, never real keys
profiles.yaml             # default job: environment=docker, executor=acp
profiles.nooa.yaml        # NVIDIA OO-Agents harness (LiteLLM)
profiles.dsh.yaml         # DeepSeek harness (wildcard role row)
profiles.openhands.yaml   # OpenHands SDK in the attempt environment (LiteLLM)
overlays/                 # per-entry overlay packs (pi / opencode litellm)
tasks/<task_id>/
  task.yaml / run.py / evaluator.py
  data/                   # agent-visible seed
  evaluation/             # gold (evaluator-only, never projected to the agent)
```

## Run

From the repo (no registry needed):

```bash
uv run ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval run  examples/datasets/minimal-demo --task terminal-jsonl-agg
```

From the Registry (any machine with credentials):

```bash
ageval lock official/minimal-demo@0.1.3 --task terminal-jsonl-agg
ageval run  official/minimal-demo@0.1.3 --task terminal-jsonl-agg
```

Other bindings:

```bash
uv run ageval run examples/datasets/minimal-demo --task multiagent-env-min \
  --profiles examples/datasets/minimal-demo/profiles.dsh.yaml
ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.openhands.yaml
```

## Credentials

```bash
cp env.example .env       # fill locally; never commit real keys
```

Locators referenced by the shipped profiles: `ZHIPU_API_KEY` (ACP GLM plan),
`litellm_api_key` / `litellm_base_url` (nooa, openhands), `deepseek_api_key` (dsh),
`AGEVAL_SSH_*` (ssh environment kind). Missing locators fail at `lock` —
before any environment opens.
