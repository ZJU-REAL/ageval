# ageval

**agent eval** — lock a dataset, bind environment and agent, run the same task.

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">中文</a>
  &nbsp;&nbsp;
  <a href="https://github.com/ZJU-REAL/ageval/releases"><img alt="Release" src="https://img.shields.io/github/v/release/ZJU-REAL/ageval?display_name=tag&sort=semver"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-blue"></a>
</p>

> [!IMPORTANT]
> Most agent evaluation still sits at the **model**: same prompts, same tool contract, different weights or APIs. That split is failing. A shippable agent is a Model plus a Harness: the same weights on a different coding-agent runtime, tool policy, or isolation change behavior and cost. Harness has to be a first-class eval axis, locked with the Model and the environment.

**ageval** decouples the runtime of a bench run. Environment and Agent combine through plugins, so one `run.py` runs under each binding.

## Contents

- [What it is](#what-it-is)
- [How it works](#how-it-works)
- [Features](#features)
- [Getting started](#getting-started)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Docs](#docs)

## What it is

ageval treats **Harness** as a first-class evaluation axis.

- **The unit of delivery is a dataset.** A dataset holds tasks; each task owns the loop (`run.py`), the score (`evaluator.py`), and gold. Environment and Agent bind on the job, not in the task.
- **An Attempt is visible.** Order is environment → run → evaluate → record; cleanup always runs.
- **Environment is injected by name.** The environment winner **exports** the service name `environment`. An agent backend **injects** that name and **requires** the capabilities it needs (`attach_stdio` or `exec`). Missing capability fails at lock. Calls stay on the Protocol. Default is the host and local docker; cloud sandboxes [e2b](https://e2b.dev) and [daytona](https://www.daytona.io) are optional.
- **Coding agents enter through plugins.** Default is [ACP](https://agentclientprotocol.com) ([pi](https://pi.dev), [Codex](https://github.com/openai/codex), [Claude Code](https://github.com/anthropics/claude-code), [OpenCode](https://github.com/sst/opencode)); heterogeneous harnesses such as [nooa](https://github.com/NVIDIA-NeMo/labs-OO-Agents), [dsh](https://github.com/deepseek-ai/deepseek-harness), and [miniswe](https://github.com/SWE-agent/mini-swe-agent) join the same way. Open slots extend the harness set and run on the same Attempt path and leaderboard.

## How it works

```text
            you ── lock / run ──►  ┌─────────────────┐
                                   │     Attempt     │  lock dataset · digest
                                   │   ageval core   │  environment → run
                                   │                 │  evaluate → record
                                   │                 │  finally cleanup
                                   └────────┬────────┘
                                            │ opens one environment
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
        ┌───────────┐                 ┌───────────┐                 ┌───────────┐
        │   local   │                 │  docker   │                 │ e2b/ssh/daytona │
        └─────┬─────┘                 └─────┬─────┘                 └─────┬─────┘
              └──────── Protocol: upload · exec · attach_stdio ───────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │     run.py      │  task loop · Agent invoke
                                   │  ACP / plugin   │  plugin inlet
                                   └────────┬────────┘
                                            ▼
                                   ┌─────────────────┐
                                   │  evaluator.py   │  only source of PASS
                                   └─────────────────┘
```

1. **Lock the experiment.** Dataset, Environment, and Agent are composed into a digest. Secrets remain locators; they are not stored as plaintext in the lock.
2. **Open an environment.** Host, docker, a cloud sandbox, or a remote. Insufficient capability or missing credentials fail before the environment opens.
3. **Execute the task.** `run.py` owns the loop, tools, and Agent invocation. Changing the environment or the Agent does not require rewriting the task.
4. **Score independently.** Gold enters the environment at this point. `evaluator.py` binds PASS / FAIL / ERROR. Cleanup always runs.

## Features

**Evaluation**

- **Lock one experiment.** Dataset, Harness, and environment lock together into a reproducible digest. Scores are not comparable across different bindings.
- **One task, a suite, a matrix, or repeats.** Run a single task, a full dataset, a parameter matrix on one task, or multiple independent Attempts of the same job (pass@k).
- **Scoring is separate from the Agent.** Gold does not enter the Agent view. PASS comes only from `evaluator.py`; trajectories are for inspection.
- **Limits are enforced before invocation.** Wall time, memory, processes, and invocation ceilings are enforced by the runtime before invoke; `run.py` cannot raise them.

**Composition**

- **One `run.py` under each binding.** Environment and Agent combine through plugins. Default is [ACP](https://agentclientprotocol.com); heterogeneous harnesses such as [nooa](https://github.com/NVIDIA-NeMo/labs-OO-Agents), [dsh](https://github.com/deepseek-ai/deepseek-harness), and [miniswe](https://github.com/SWE-agent/mini-swe-agent) join through the same plugin path. Open slots extend or replace a harness and participate in the same Attempt path and leaderboard.
- **Agent packages.** A job's Agent binding is packaged as `ageval.agent/1` and bound after install.
- **Multiple roles and sessions.** The task owns dialog, tools, and handoff; the runtime supplies the environment and the Agent inlet.
- **Validate before invoke.** Capabilities and credentials are checked before the Agent is called; absence fails and invoke does not start.

**Environment**

- **Host, container, cloud sandbox, remote — one Protocol.** local, docker, [e2b](https://e2b.dev), ssh, [daytona](https://www.daytona.io): `upload` / `exec` / `attach_stdio`.
- **Visibility is isolated.** The Agent sees only the projected workspace; gold and host credentials do not enter the task default environment.
- **Official Attempt image.** Docker installs ACP entries at build time; they are not installed at invoke.

**Results**

- **Local Viewer.** Inspect trajectory, environment, and score along Jobs → Tasks → Attempt.
- **Sealed trajectory.** Export a copy without modifying the score.
- **Hub.** Publish datasets, plugins, and Agent packages; upload suites. Organizations manage members, visibility, and versions. The public Leaderboard lists complete, release-bound suites only. Operators can `docker compose -f services/registry/docker-compose.yml up -d` (Postgres, object store, Registry, Hub) and pull `ghcr.io/zju-real/ageval-hub` / `ageval-registry` from a release tag.

**Authoring**

- **The task owns only that task.** Loop, tools, scoring, and gold; orchestration does not belong in the task.
- **SDK is optional.** Sessions, tools, terminals. It does not decide PASS and does not hold host credentials.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and CPython **3.12+**. A live coding-agent run also requires a host ACP entry and credentials. `ageval lock` does not.

```bash
git clone https://github.com/ZJU-REAL/ageval.git
cd ageval
uv sync --frozen --all-packages
uv run ageval -V
```

```bash
uv run ageval tasks examples/journeys
uv run ageval lock examples/journeys --task terminal-jsonl-agg
uv run ageval run  examples/journeys --task terminal-jsonl-agg
uv run ageval run  examples/journeys --task terminal-jsonl-agg \
  --profiles examples/journeys/profiles.e2b-acp.yaml --probe
uv run ageval executors -v
uv run ageval view examples/journeys --no-browser
```

Default `examples/journeys` profiles use `environment: docker`. Install an Agent package with `ageval agent install examples/agents/pi-default`, then bind it with `--agent`.

In-repo examples: [`examples/README.md`](examples/README.md) — journeys, `tau3-airline`, and catalog Agents.

## Architecture

```text
  ageval.yaml + task.yaml + profiles.yaml
                 │
                 ▼
           ageval lock                 digest · extension_bindings
                 │
                 ▼
           ageval run  ── Attempt ── environment → run → evaluate → record
                 │                      finally cleanup
                 ▼
        .ageval/runs/<id>/             lock.json · result.json · trajectory.jsonl
                 │
      ┌──────────┼──────────┐
      ▼                     ▼
 ageval view          Registry / Hub
 local Jobs           publish · upload-suite · Leaderboard
```

- lock is the normative gate: unknown format fails once. Plugins change the binding, not the five Attempt phases.
- Attempt owns identity, deadlines, cleanup, and the score.
- Local Viewer reads files; Hub talks to Registry.

## Project structure

Simplified from [`ARCHITECTURE.md`](ARCHITECTURE.md). Generated trees (`.ageval/`, `.venv/`) are not source.

```text
ageval/
├── src/ageval/
│   ├── cli/                         # argv, help, exit code
│   ├── application/
│   │   ├── composition.py           # sole production wiring; CLI imports build_* here
│   │   ├── lock.py                  # load_and_lock
│   │   ├── run.py                   # mint identity → run_attempt
│   │   ├── campaign.py / suite/     # matrix · suite · Always-k
│   │   └── agent_ops/ / plugin_ops / registry_ops/
│   ├── attempt/                     # visible pipeline
│   │   ├── __init__.py              # run_attempt
│   │   └── phases/                  # environment → run → evaluate → record · cleanup
│   ├── config/                      # dataset + task.yaml + profiles
│   ├── environments/protocol.py     # EnvironmentProvider · caps; no vendor SDK
│   ├── plugins/
│   │   ├── slots.py                 # exclusive / chain
│   │   └── contrib/                 # acp · local · docker · e2b · daytona · ssh
│   ├── runtime/                     # identity, parent Agent Service, task_worker
│   ├── evaluation/                  # barrier + bind PASS
│   └── evidence/                    # trajectory.jsonl layout
├── sdk/python/                      # ageval_sdk for run.py (no PASS, no host credentials)
├── plugins/                         # external ageval.plugin/1 (nooa, dsh, miniswe, …)
├── examples/
│   ├── journeys/                    # terminal-jsonl-agg · tau2-dialog-min · multiagent-env-min
│   ├── tau3-airline/
│   └── agents/                      # ageval.agent/1
├── apps/viewer                      # ageval view SPA
├── apps/hub                         # Hub SPA
├── services/registry/               # package + results HTTP
├── docker/attempt/                  # official image; ACP entries baked in
├── docs/                            # mechanism design
└── website/                         # product docs
```

## Docs

- Usage: [`website/`](website/)
- Design: [`docs/`](docs/README.md)
- Examples: [`examples/README.md`](examples/README.md)
- [`AGENTS.md`](AGENTS.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
