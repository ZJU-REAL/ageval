# ageval System Specifications

## Purpose and Authority Hierarchy

This directory (`docs/`) is the **self-contained normative specification** for **ageval** product semantics, execution mechanisms, schemas, protocols, and safety boundaries. All implementation modules, GitHub Issues, tests, and reader-facing guides derive from the contracts defined here.

The unit of benchmark delivery is a **dataset** (`ageval.dataset/1`), distinct from a relational database. Canonical terminology is defined in [glossary.md](glossary.md).

```text
docs/ (PRD + design/* + glossary)  ← Normative product & mechanism specifications (Living Truth)
  → ARCHITECTURE.md                ← Implementation source layout, module ownership & import graph
  → docs/RFCs/                     ← Point-in-time mechanism proposals (merged into design/ on acceptance)
  → GitHub Issues                  ← Incremental delivery & acceptance tracking
  → Code / Tests / Public Smoke    ← Verified runtime implementation
```

| Concern | Authoritative Document |
| --- | --- |
| Product positioning, success criteria, non-goals, user stories US1-US12, and red lines | [PRD.md](PRD.md) |
| Normative mechanism, schema, and protocol specifications (`01`-`09`) | [`design/`](design/README.md) |
| Canonical terminology and forbidden terms | [glossary.md](glossary.md) |
| Architectural proposals prior to specification merge | [`RFCs/`](RFCs/AGENTS.md) |
| Current source tree, composition root, and dependency direction | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Contributor workflow, construction rules, and CI gates | [../AGENTS.md](../AGENTS.md) |
| Reader-facing bilingual documentation | [../website/](../website/) |

`docs/reference/` contains archived historical background notes and is not an active specification.

---

## Specification Index (`docs/design/`)

Recommended reading order is summarized in [design/README.md](design/README.md).

| Specification | Normative Scope |
| --- | --- |
| [design/01-core-lifecycle.md](design/01-core-lifecycle.md) | Core locking (`load_and_lock`), Attempt identity and phase state machine, `limits` enforcement, `upstream_stall`, suite resumption, `regrade`, and `Result.error` failure taxonomy |
| [design/02-schemas-and-config.md](design/02-schemas-and-config.md) | `ageval.dataset/1`, `ageval.task/1`, `ageval.profiles/1`, `ModelSpec`, asset/prepare hooks, git sources, `--set` allowlist, and `--layout harbor` |
| [design/03-task-sdk-and-evaluation.md](design/03-task-sdk-and-evaluation.md) | Task script `run.py`, `ageval_sdk` API, multi-session concurrency (`bounded_gather`, `first_success`), isolated evaluation (`evaluator.py`), `gold` isolation, and conversion rules |
| [design/04-environments.md](design/04-environments.md) | `EnvironmentProvider` protocol, `BaseEnvironment`, capability enforcement (`requires ⊆ capabilities`), `local` / `docker` / `e2b` / `ssh` / `daytona`, image baking, and Compose sidecars |
| [design/05-executors-and-acp.md](design/05-executors-and-acp.md) | `BaseExecutor`, `ParentAgentService`, `executor: acp` (`attach_stdio`) vs. `acp-oneshot`, executor placement (`miniswe`, `terminus-2`, `openhands`), BYOK/BYOA, and generated option tables |
| [design/06-plugins-and-extensions.md](design/06-plugins-and-extensions.md) | `ageval.plugin/1`, exclusive slots, chain slots, declarative `export` / `inject`, `ExtensionGraph` resolution, and two-stage static contract validation |
| [design/07-evidence-and-analysis.md](design/07-evidence-and-analysis.md) | `.ageval/runs/<attempt_id>/` layout, `trajectory.jsonl` sealing, `terminal.usage` and `summary.extra`, Suites and Campaigns, and read-only analyzers (`stats`, `hack`, `review`) |
| [design/08-hub-registry-and-agents.md](design/08-hub-registry-and-agents.md) | Hub, Registry HTTP service, git-backed datasets (`eval_digest`), Leaderboard Plaza (`/leaderboard`), `ageval.agent/1` packages, models catalog, snapshot shares, and cloud-hosted jobs |
| [design/09-web-ui-design-system.md](design/09-web-ui-design-system.md) | Web UI design system tokens, typography, motion curves, component vocabulary, and ten visual invariants |

---

## Architectural Proposals (`docs/RFCs/`)

[`RFCs/`](RFCs/AGENTS.md) holds mechanism proposals prior to acceptance into `design/`. A `Draft` RFC does not describe shipped behavior. Authoring rules live in [`RFCs/AGENTS.md`](RFCs/AGENTS.md).

| RFC | Status | Summary |
| --- | --- | --- |
| [RFCs/0001-attempt-activity-recovery.md](RFCs/0001-attempt-activity-recovery.md) | Accepted | Unified `activity.jsonl` (`ageval.activity/1`) and incremental `/attempt/{workspace,home}` checkpoints (`ageval.checkpoint/1`) for recovering unsealed Attempts across all executors (including `acp`) and environment kinds. Normative rules are folded into design 01, 04, 05, and 07. |

---

## Synchronization Policy

1. **Phase-completion sync**: When a change modifies product semantics, schemas, or module boundaries, update the corresponding `docs/design/*` pages (plus `PRD.md`, `glossary.md`, `ARCHITECTURE.md`, `website/`, and `skills/` when affected) when wrapping up the implementation phase or pull request.
2. **Reader-facing separation**: `website/` summarizes usage for operators and dataset authors; normative mechanism specifications remain in `docs/design/`.
3. **No Issue numbers in outward docs**: Outward-facing documentation (`README.md`, `README.zh-CN.md`, `website/`, `examples/**/README*`, and plugin READMEs) MUST NOT contain GitHub Issue numbers.
