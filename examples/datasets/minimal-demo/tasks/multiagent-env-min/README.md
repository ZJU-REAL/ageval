# multiagent-env-min

v1 **multiagentbench / database-52** case class on ageval v2 Core surfaces.

| v1 oracle                            | v2 mapping                                                    |
| ------------------------------------ | ------------------------------------------------------------- |
| Multi specialist + planner + reducer | Independent `AgentSession`s (roles via prompts + profile ids) |
| Environment diagnostic tools         | `lib` `ToolSet.db_query` → Attempt-local PostgreSQL           |
| Sealed reducer labels                | Independent evaluator vs `evaluation/expected.json`           |
| Heterogeneous agent backends         | Mixed ACP entries in one Attempt                              |

**Not** a `MultiAgentBenchAdapter`. Gold labels are **not** in agent prompts; they
must be discovered from seeded DB rows via tools.

## ACP mix (default)

`profiles.yaml` binds all three roles to the `pi` entry by default; point
`parameters.roles` at other profile ids for a heterogeneous mix.

| Role                    | profile id  | ACP `entry` |
| ----------------------- | ----------- | ----------- |
| specialists (×5 probes) | `specialist` | `pi`       |
| planner                 | `planner`    | `pi`       |
| reducer                 | `reducer`    | `pi`       |

`run.py` reads profile ids from `parameters.roles` — it never branches on entry name.

## In-environment PostgreSQL

`environment/Dockerfile` adds PostgreSQL to the Attempt image; `environment/setup.sh`
starts it, loads `environment/seed.sql`, and writes `.ageval_env_result.json` into
the workspace so `lib/db_tools.py` can reach the seeded database via `docker exec`.

## Package layout

| Path                   | Role                                                |
| ---------------------- | --------------------------------------------------- |
| `run.py`               | Orchestration only (specialist → planner → reducer) |
| `evaluator.py`         | Independent PASS vs gold labels                     |
| `lib/db_tools.py`      | `db_query` ToolSet + env handoff load               |
| `lib/diagnostics.py`   | Specialist SQL probes + allowed label set           |
| `lib/agent_json.py`    | Invoke → JSON parse helpers                         |
| `environment/seed.sql` | Generic package seed (Core runs as SQL statements)  |
| `data/instruction.md`  | Optional agent-visible brief                        |
| `evaluation/`          | Evaluator-only gold                                 |

```bash
uv run ageval lock examples/datasets/minimal-demo --task multiagent-env-min
uv run ageval run  examples/datasets/minimal-demo --task multiagent-env-min
```

Requires host ACP readiness for `pi`, `opencode`, and `grok-build` (`uv run ageval executors -v`),
plus Docker for the Attempt-local PostgreSQL environment.
