# Shipped public surfaces (orientation)

Prefer mechanism packages under `examples/core/`. Full list: `examples/README.md`.
Evidence grade is **limited `runnable-mvp`**. Do not claim `isolated` from one happy path.

| Package | Demonstrates |
| --- | --- |
| `examples/core --task config-minimal` | `ageval lock` success (`dataset_id`, no `database_id`) |
| `examples/core --task acp-local-min` | local ACP public run |
| `examples/core --task acp-docker-min` | docker ACP public run (`--profiles examples/core/profiles.docker.yaml`) |
| `examples/core --task sdk-agent-session` | Host multi-invoke + independent PASS |
| `examples/core --task plugin-agent-executor` | Second executor mechanism (`openai-http`) |
| `examples/datasets/minimal-demo --task terminal-jsonl-agg` | Named demo task |
| `examples/datasets/minimal-demo --task env-postgres-min` | Sidecar / compose path |
| docker topology `sdk-session-single-actor` | lock 有 topology 即可 |

e2b / ssh / daytona: code exists; missing key → `--probe` `ready: false`. Skip is not a pass.

## Install (repo root)

```bash
uv sync --frozen --all-packages
uv run ageval --help
uv run ageval executors -v
```

Design: `docs/PRD.md`, `docs/design/01-core-lifecycle.md`, `ARCHITECTURE.md`.
