# terminal-jsonl-agg

v1 **terminal-bench / jsonl-aggregator** case class:

- Agent works in Attempt workspace (JSONL files + instruction only)
- Must write `aggregates.json` by **aggregating real records\_\*.jsonl** (not prompt-fed gold)
- `run.py` **explicitly** `Agent.session` → `invoke` → read workspace file → `publish_json`
- Gold lives under `evaluation/`; it is not mounted. The evaluator compares after upload
- No `TerminalBenchAdapter`

## ACP (default)

Default `minimal-demo` `profiles.yaml` uses `environment: docker` and ACP `entry: pi`
on role `solver`.

```bash
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg
# switch ACP entry via allowlisted override
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --set '/agent_profiles/solver/options/entry="codex"'
```

Needs a host ACP entry, credentials for that entry, and Docker (default environment).
`--probe` checks readiness without invoking the Agent.

## dsh plugin (optional)

Same `run.py`; bind DeepSeek Harness via an alternate profiles file (not ACP):

```bash
uv run ageval plugin install plugins/dsh
uv run ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.dsh.yaml
```

This task writes `aggregates.json`, so omit `options.permission` or use
`workspace-write`. `read-only` fences DSH file-tool writes only; bash can
still write on the bundled jsonrpc runtime. It is not ageval isolation.

Needs locator `deepseek_api_key` in repo `.env`. Docker bake installs
`deepseek-harness-sdk` in the Attempt image.
