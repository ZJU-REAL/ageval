# design/ — System Specifications Index

This directory contains the nine **self-contained normative specifications** (`01` through `09`) for **ageval** mechanisms, schemas, protocols, and architectural invariants.
Implementation source layout, module ownership, and Python import directions live in **[ARCHITECTURE.md](../../ARCHITECTURE.md)**; product requirements, user stories US1-US12, and architectural red lines live in **[PRD.md](../PRD.md)**; contributor workflow and verification gates live in **[AGENTS.md](../../AGENTS.md)**.

```text
PRD            Product positioning, user stories US1-US12, and architectural red lines
01-03          Core lifecycle & quotas, dataset/task/profiles/ModelSpec schemas, ageval_sdk & isolated evaluation
04-06          Execution environments, agent executors & ACP, extension plugins & slots
07-09          Evidence archive & post-run analyzers, Hub/Registry/Agents/Hosted jobs, Web UI design system
```

| Specification | Normative Scope |
| --- | --- |
| [01-core-lifecycle.md](01-core-lifecycle.md) | Configuration locking (`lock`), Attempt identity and phase state machine, `limits` enforcement, `upstream_stall`, suite resumption, `regrade`, and `Result.error` failure taxonomy |
| [02-schemas-and-config.md](02-schemas-and-config.md) | `ageval.yaml` (`ageval.dataset/1`), `task.yaml` (`ageval.task/1`), `profiles.yaml` (`ageval.profiles/1`), `ModelSpec`, dataset assets/prepare, git sources, and `--layout harbor` |
| [03-task-sdk-and-evaluation.md](03-task-sdk-and-evaluation.md) | Task script `run.py`, `ageval_sdk` API, multi-session concurrency (`bounded_gather`, `first_success`), isolated evaluation (`evaluator.py`), `gold` isolation, and benchmark conversion rules |
| [04-environments.md](04-environments.md) | `EnvironmentProvider` protocol, `BaseEnvironment`, capability matrix (`local`, `docker`, `e2b`, `ssh`, `daytona`), official base image baking, CPU/memory/GPU limits, and Compose sidecars |
| [05-executors-and-acp.md](05-executors-and-acp.md) | `BaseExecutor`, `ParentAgentService`, `executor: acp` (`attach_stdio`) vs. `acp-oneshot`, executor placement (`miniswe`, `terminus-2`, `openhands`), BYOK/BYOA, and generated executor option tables |
| [06-plugins-and-extensions.md](06-plugins-and-extensions.md) | `ageval.plugin/1`, exclusive slots, chain slots, service `export` / `inject`, `ExtensionGraph` resolution, and two-stage static contract validation |
| [07-evidence-and-analysis.md](07-evidence-and-analysis.md) | `.ageval/runs/<attempt_id>/` layout, `trajectory.jsonl` sealing, `terminal.usage`, `summary.extra`, Suites and Campaigns, and post-run read-only analyzers (`stats`, `hack`, `review`) |
| [08-hub-registry-and-agents.md](08-hub-registry-and-agents.md) | Hub, Registry HTTP API, git source registration (`eval_digest`), Leaderboard Plaza (`/leaderboard`), `ageval.agent/1` packages, models catalog, snapshot shares, and cloud-hosted jobs |
| [09-web-ui-design-system.md](09-web-ui-design-system.md) | Web UI design tokens, typography, motion curves, component vocabulary, and ten visual invariants |
