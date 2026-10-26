---
name: ageval-platform
description: >
  ageval platform map: authority (docs/design vs ARCHITECTURE vs Issues), Core vs
  dataset ownership, red lines (no secrets, mechanism-named adapters), evidence
  grades, which sibling skill to load. Use when entering the
  repo, asking "what is ageval", "who owns PASS", "read order", or "evidence grade".
  Not a substitute for docs/design.
---

# ageval platform

Core owns configuration locking (`lock`), the Attempt phase pipeline, the `EnvironmentProvider` protocol, `limits` enforcement, trajectory archiving, and binding the independent evaluation result. The dataset owns the task interaction loop in `run.py` and grading criteria in `evaluator.py`.

## Read order

1. `docs/design/` — product and mechanism specifications (self-contained)
2. `ARCHITECTURE.md` — module layout and dependency direction
3. GitHub Issues — incremental delivery and acceptance tracking
4. Code / tests / examples — shipped runtime behavior

`website/` is reader-facing documentation. When specifications conflict, `docs/` and `ARCHITECTURE.md` take precedence; update the relevant documentation when wrapping up a phase or PR.

## Ownership

| Owns | Does not own |
| --- | --- |
| **Core:** `lock`, Attempt phases, `EnvironmentProvider` protocol, Agent Service, `limits`, `bind_evaluation` | Task interaction loop, scoring algorithm |
| **`run.py`:** interaction loop, local tools, artifact publishing | `PASS` verdict, host credentials, starting the environment |
| **`evaluator.py`:** grading logic (script or optional `Agent.session` after `gold` upload) | Starting the solver environment; deriving `PASS` from trajectories |

## Red lines

1. No plaintext secrets in `lock.json`, YAML, or evidence archives. Environment variables are locators.
2. Plugins and adapters are named by mechanism (`acp`, `docker`, `e2b`, `ssh`, `openai-http`), never by benchmark name.
3. Environment selection uses `environment: local|docker|e2b|ssh|daytona` in `profiles.yaml`.
4. Unknown schema format fails fast with `invalid_format` at `/format`.
5. Coding agents bind via `executor: acp` + `options.entry`, not `executor: pi`.
6. Plugins implement exclusive or chain slots only. `ageval plugin install` never rewrites `profiles.yaml`.
7. Do not claim `isolated` or `real-benchmark-verified` from a single smoke pass.
8. Logic tests build the input and assert `status`, `error.title`, or the exit code. Fidelity tests run the real CLI on a real filesystem, container, or ACP entry, and record a skip when that boundary is missing.

## Skills

| Task | Load |
| --- | --- |
| CLI operations | `$ageval-cli` |
| `ageval.yaml` / `task.yaml` / `profiles.yaml` | `$ageval-config-package` |
| `run.py` / `AgentSession` / `ageval_sdk` | `$ageval-sdk-harness` |
| `ageval.plugin/1` authoring | `$ageval-plugin` |
| Web UI design tokens & components | `$ageval-design-system` |

Detail: [references/authority.md](references/authority.md), [references/red-lines.md](references/red-lines.md), [references/shipped-surfaces.md](references/shipped-surfaces.md).
