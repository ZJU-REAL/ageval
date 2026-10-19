<div align="center"><a name="readme-top"></a>

<img src="docs/assets/hero.png" alt="ageval: Configurable and pluggable agent evaluation framework" width="100%">

# ageval

**English** · [简体中文](README.zh-CN.md)

<br/>

<!-- SHIELD GROUP -->

<a href="https://github.com/ZJU-REAL/ageval/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/ZJU-REAL/ageval?style=for-the-badge&logo=github&color=E3B341&labelColor=20242D"></a>
<a href="https://github.com/ZJU-REAL/ageval/releases"><img alt="release" src="https://img.shields.io/github/v/release/ZJU-REAL/ageval?style=for-the-badge&logo=github&color=1B54E8&labelColor=20242D"></a>
<a href="https://github.com/ZJU-REAL/ageval/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/ZJU-REAL/ageval/ci.yml?branch=main&label=CI&logo=githubactions&logoColor=white&style=for-the-badge&labelColor=20242D"></a>
<a href="https://github.com/ZJU-REAL/ageval/blob/main/LICENSE"><img alt="license" src="https://img.shields.io/github/license/ZJU-REAL/ageval?style=for-the-badge&logo=opensourceinitiative&logoColor=white&color=34D399&labelColor=20242D"></a>
<a href="https://zju-real.github.io/ageval/en/docs/"><img alt="docs" src="https://img.shields.io/badge/docs-website-1B54E8?style=for-the-badge&logo=gitbook&logoColor=white&labelColor=20242D"></a>
<a href="#getting-started"><img alt="install uv" src="https://img.shields.io/badge/install-uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white&labelColor=20242D"></a>
<a href="https://youtu.be/MxiM9A9YvLc"><img alt="demo" src="https://img.shields.io/badge/demo-YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white&labelColor=20242D"></a>

</div>

<details>
<summary><kbd>Table of contents</kbd></summary>

#### TOC

- [⚡ Getting started](#getting-started)
  - [Install skills](#install-skills)
  - [Develop from source](#develop-from-source)
- [✨ Features](#features)
  - [Screenshots](#screenshots)
- [⚙️ How it works](#how-it-works)
  - [End-to-end flow](#end-to-end-flow)
  - [Core base](#core-base)
  - [Plugins](#plugins)
- [📁 Project structure](#project-structure)
- [📖 Docs](#docs)

<br/>

</details>

To decouple benchmark task logic from execution backends across heterogeneous agent harnesses, models, and environments, **ageval** combines programmable task scripts with declarative plugin composition. Install the CLI and skills so a coding agent can author or convert a benchmark and run evaluations end to end; publish datasets, plugins, Agent packages, and evaluation results to the Hub for reproducible comparison and reuse.

<p align="center">
  <video src="https://github.com/user-attachments/assets/79f54d94-999f-44c1-b2a4-72d79d3ce1f4" controls width="100%" title="ageval highlights"></video>
</p>

## Getting started

```bash
uv tool install ageval-cli
# install everything, or only what you need
uv tool install 'ageval-cli[all]' # every CLI extra (not the Hub service)
uv tool install 'ageval-cli[e2b]' # one extra at a time

ageval -V
```

Run a dataset directly from the Hub ([ageval.zjureal.com](https://ageval.zjureal.com), the CLI default) or from any local dataset directory:

```bash
ageval registry list                        # datasets visible on the Hub
ageval run official/minimal-demo@0.1.3 --task terminal-jsonl-agg
ageval run <org>/<name>@<version> --task <task-id>
ageval executors -v
ageval view <org>/<name>@<version> --no-browser
```

### Install skills

Install skills for your local coding agent (CLI usage, plugin authoring, dataset conversion, and SDK usage):

```bash
# install all
npx skills add ZJU-REAL/ageval
# install specific ones
npx skills add ZJU-REAL/ageval --skill ageval-cli
```

### Develop from source

To run the in-repo dataset examples and Agent packages, or to build from source, clone the repository:

```bash
git clone https://github.com/ZJU-REAL/ageval.git
cd ageval
uv sync --frozen --all-packages
uv run ageval -V
```

Run the minimal example and inspect the results in the local Viewer:

```bash
uv run ageval tasks examples/datasets/minimal-demo
uv run ageval run  examples/datasets/minimal-demo --task terminal-jsonl-agg
uv run ageval view examples/datasets/minimal-demo --no-browser
```

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## Features

**Swap the evaluated agent and environment via plugins**

Environments and agent executors both connect through plugin slots. Coding agents connect by default over [ACP](https://agentclientprotocol.com) (`pi`, `codex`, `claude-code`, `opencode`), while [nooa](https://github.com/NVIDIA-NeMo/labs-OO-Agents), [dsh](https://github.com/deepseek-ai/deepseek-harness), and [miniswe](https://github.com/SWE-agent/mini-swe-agent) use the same plugin mechanism. Update `profiles.yaml` or pass `--agent` (and optional `--model`) to switch configurations without modifying task scripts.

**Automated benchmark conversion and inspection**

With the CLI and skills installed, a coding agent can author or convert a dataset and execute evaluations end to end. Afterwards, `ageval view` opens the dataset (or a directory of datasets) to inspect phase timings, tool-call trajectories, and reproduction commands locally, while `ageval results regrade` re-runs grading on archived artifact snapshots without repeating model inference.

**Isolated phase boundary and flexible grading**

Only the independent `evaluator.py` in the `evaluate` phase can return `PASS` or `FAIL`, after solver sessions are sealed and reference materials (`gold`) are uploaded:

- **Deterministic scripts:** compare candidate artifacts or environment states against reference materials, optionally returning structured `checks`.
- **Agent-as-judge / LLM-as-judge:** bind an independent `judge` profile in `profiles.yaml` to inspect artifacts across single or multiple steps.

**Share and compare on Hub**

Publish datasets, plugins, Agent packages, and suite results to [ageval Hub](https://ageval.zjureal.com), or share a read-only snapshot link `/s/{token}` (frozen or `--live`) directly from a local run. Leaderboard entries record the bound harness, model, and environment and link directly to per-Attempt configurations and trajectories.

### Screenshots

<p align="center"><img src="docs/assets/demo/leaderboard.png" alt="Hub leaderboard: scores by Agent and model" width="100%"></p>
<p align="center">Leaderboard: scores by Agent and model</p>

<p align="center"><img src="docs/assets/demo/viewer-trajectory.png" alt="Local viewer: replay tool calls in a trajectory" width="100%"></p>
<p align="center">Trajectory: replay tool calls in the local viewer</p>

<details>
<summary>More screenshots</summary>
<br/>

<p align="center"><img src="docs/assets/demo/agents.png" alt="Agents: packages you can pull from Hub" width="90%"></p>
<p align="center">Agents: packages you can pull from Hub</p>

<p align="center"><img src="docs/assets/demo/plugins-marketplace.png" alt="Plugin marketplace: environment and agent runtime plugins" width="90%"></p>
<p align="center">Plugin marketplace: environment and agent runtime plugins</p>

<p align="center"><img src="docs/assets/demo/leaderboard-pareto.png" alt="Pareto: pass rate vs time" width="90%"></p>
<p align="center">Pareto: pass rate vs time</p>

<p align="center"><img src="docs/assets/demo/viewer-checks.png" alt="Verifier: deterministic script checks" width="90%"></p>
<p align="center">Verifier: deterministic script checks</p>

</details>

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## How it works

### End-to-end flow

1. **`ageval lock`** resolves the plugin dependency graph (`ExtensionGraph`), validates capability dependencies and `ModelSpec` contracts, and writes `lock.json` (storing credentials only as environment variable locators).
2. **`ageval run`** provisions the selected environment (`local`, `docker`, `e2b`, `ssh`, or `daytona`) and uploads task input data.
3. **`run.py`** drives the task interaction loop inside the `run` phase; switching environments or harnesses requires no changes to task code.
4. **`evaluator.py`** runs in the `evaluate` phase after solver sessions are sealed and reference materials (`gold`) are uploaded, producing the sole `PASS` or `FAIL` verdict while `cleanup` always executes in `finally`.

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#eaf1ff","actorBorder":"#5B7BFF","actorTextColor":"#10233f","actorLineColor":"rgba(45,49,66,0.2)","signalColor":"#4f5d75","signalTextColor":"#2d3142","labelBoxBkgColor":"#eaf1ff","labelBoxBorderColor":"#5B7BFF","labelTextColor":"#10233f","noteBkgColor":"#f1f5f9","noteBorderColor":"#64748b","noteTextColor":"#1e293b"}}}%%
sequenceDiagram
    autonumber
    actor u as you
    participant r as run entry
    participant e as Environment<br/>local / docker / e2b…
    participant t as run.py + Agent
    participant v as evaluator.py

    u->>r: ageval lock<br/>dataset + profiles → lock.json
    Note over r: contract or capability mismatch fails fast before execution
    u->>r: ageval run
    r->>r: mint run identity
    r->>e: open environment
    r->>e: upload task data
    e->>t: execute run.py
    loop task loop
        t->>t: ACP invoke · attach_stdio
    end
    t-->>r: trajectory.jsonl
    Note over r,v: solver sealed → upload reference materials (gold), then evaluate
    r->>v: run evaluator.py
    v-->>r: PASS / FAIL / ERROR
    r->>r: record · finally cleanup<br/>lock.json · result.json · trajectory.jsonl
```

### Core base

ageval Core coordinates a fixed pipeline: `lock → environment → run → evaluate → record`, with resource `cleanup` in `finally`. During `ageval lock`, Core binds the environment plugin and per-role executor plugins and validates their contracts. At runtime, Core enforces `limits` (wall-clock timeouts, invocation quotas, and concurrency caps) prior to execution and archives structured evidence (`lock.json`, `result.json`, `trajectory.jsonl`, `summary.json`, and `task-artifacts/`).

<p align="center">
  <img src="docs/assets/core-base.png" alt="ageval Core base overview" width="100%">
</p>

### Plugins

Core decouples runtime responsibilities through **exclusive slots**, **chain slots**, and declarative **dependency injection** (`inject`). Plugins declare the slots they implement and the service capabilities they require; `ageval lock` resolves and verifies the dependency graph (`ExtensionGraph`) before execution.

```yaml
# Agent executor plugin (e.g. dsh)
plugin_id: dsh
slots:
  exclusive:
    - id: executor
inject:
  - service: environment
    capabilities: [exec, upload]

# Environment plugin (e.g. docker)
plugin_id: docker
slots:
  exclusive:
    - id: environment
```

<p align="center">
  <img src="docs/assets/ageval-plugin-graph.png" alt="Plugin mechanism: dependency graph drives Core dispatch" width="100%">
</p>

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## Project structure

```text
ageval/
├── src/ageval/
│   ├── cli/                         # argv, help, exit code
│   ├── application/
│   │   ├── composition.py           # sole production wiring; CLI imports build_* here
│   │   ├── lock.py                  # load_and_lock
│   │   ├── run.py                   # mint identity → run_attempt
│   │   ├── regrade.py               # artifact-based regrading (skips run phase)
│   │   ├── campaign.py / suite/     # matrix · suite · Always-k
│   │   └── agent_ops/ / plugin_ops / registry_ops/ / analysis/
│   ├── attempt/                     # Attempt pipeline
│   │   ├── __init__.py              # run_attempt & run_regrade
│   │   └── phases/                  # environment → run → evaluate → record · cleanup
│   ├── config/                      # dataset + task.yaml + profiles
│   ├── model/                       # ModelSpec · resolve_model
│   ├── environments/protocol.py     # EnvironmentProvider · capabilities
│   ├── plugins/
│   │   ├── base.py / decorators.py  # BaseEnvironment · BaseExecutor
│   │   ├── slots.py                 # exclusive / chain slots
│   │   └── contrib/                 # acp · local · docker/attempt · e2b · daytona · ssh · openai_http · anthropic_http
│   ├── runtime/                     # identity, parent Agent Service, task_worker
│   ├── evaluation/                  # bind_evaluation
│   └── evidence/                    # .ageval/runs layout & trajectory sealing
├── src/ageval_sdk/                  # ageval_sdk for run.py and evaluator.py
├── plugins/                         # external ageval.plugin/1 (nooa, dsh, miniswe, acp-oneshot, …)
├── examples/
│   ├── datasets/
│   │   ├── minimal-demo/            # terminal-jsonl-agg · tau2-dialog-min · multiagent-env-min
│   │   ├── concurrent-research/     # concurrent-session fanout example
│   │   └── tau3-airline-5/          # airline-00 … airline-04
│   └── agents/                      # ageval.agent/1 packages
├── apps/shared                      # shared Hub + Viewer UI components
├── apps/viewer                      # ageval view SPA
├── apps/hub                         # Hub SPA
├── services/registry/               # package + results HTTP service & hosted worker
├── docs/                            # mechanism design specifications
└── website/                         # bilingual product documentation
```

<div align="right">

[![][back-to-top]](#readme-top)

</div>

## Docs

- Usage: [docs site](https://zju-real.github.io/ageval/en/docs/) ([source](website/))
- Design: [`docs/`](docs/README.md)
- Examples: [`examples/README.md`](examples/README.md)
- [`AGENTS.md`](AGENTS.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)

<div align="right">

[![][back-to-top]](#readme-top)

</div>

<!-- LINK GROUP -->

[back-to-top]: https://img.shields.io/badge/-↑_BACK_TO_TOP-1B54E8?style=flat-square
