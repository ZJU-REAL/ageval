---
name: verify-ageval
description: >
  Verify ageval by driving the public CLI: doctor, a lock that rejects a bad
  profile, and one minimal-demo task on local plus openai-http against the
  in-repo loopback gateway. Use when checking lock/run, seal invariants, or
  whether a credential skip was reported honestly. Triggers: verify ageval,
  loopback gateway, AGEVAL_SKIP_REAL_ACP, not run.
---

# Verify ageval

Drive `uv run ageval`. A missing credential or `AGEVAL_SKIP_REAL_ACP=1` is **not run**, never passed. Report format: [references/report.md](references/report.md).

Work in a copy of the dataset and a temporary `AGEVAL_HOME`. Leave the run evidence. Stop only the gateway and viewer processes this procedure started.

## Doctor

```bash
uv run ageval --version
uv run ageval run examples/datasets/minimal-demo --task tau2-dialog-min --probe
```

`--probe` is a flag on `ageval run`: lock plus preflight, and it does not start an Attempt. The shipped minimal-demo profiles use docker and ACP. Without a docker daemon or an ACP entry, record that probe **not run** (or failed, if the tool was present and the probe itself failed). Do not treat it as a pass of the loopback path.

## Lock rejects a bad profile

Copy `examples/datasets/minimal-demo` aside. Point a profile at `executor: acp` with `options.entry: pi` and `options.idle_timeout_secnds: 30`. `uv run ageval lock` must exit non-zero and name `idle_timeout_secnds`.

## Loopback run

Start [references/loopback_gateway.py](references/loopback_gateway.py). It prints `http://127.0.0.1:<port>/v1`.

Write a profiles file on the dataset copy: `environment: local`, roles `user` and `service`, `executor: openai-http`, `model.id: mock`, `base_url` set to that URL, `api_key: ${OPENAI_API_KEY}`, extensions `openai-http` and `local`.

```bash
export AGEVAL_HOME=/tmp/ageval-verify-home
export OPENAI_API_KEY=ci-loopback-placeholder
unset AGEVAL_OFFLINE_AGENT
uv run ageval lock <copy> --task tau2-dialog-min --profiles <profiles>
uv run ageval run  <copy> --task tau2-dialog-min --profiles <profiles>
```

Then:

- stdout status is `PASS`
- `lock.json` does not contain `ci-loopback-placeholder`
- `trajectory.jsonl` has a terminal row whose `usage` is a non-empty object
- `uv run python -c` with `assert_sealed_invariants` on that run directory

This pass is the loopback path only.

## Checks this procedure does not fake

| Check | What to do |
| --- | --- |
| Real ACP | **not run** when `AGEVAL_SKIP_REAL_ACP=1` or the entry binary / key is missing |
| Timeout-path usage | **not run** on the scripted gateway (it returns 200). A timeout run must still show a non-empty terminal `usage` after slim |
| Hosted worker | `uv run python -m services.registry.hosted.worker --once --local` with the temporary `AGEVAL_HOME`. Exit 0 and no suite started is a dry run. A missing registry env is **not run** |
| Viewer | If `apps/viewer/dist` is missing, `pnpm --dir apps/viewer install --frozen-lockfile && pnpm --dir apps/viewer build`. Then `uv run ageval view <copy> --no-browser --port 8766`. `curl` `/api/health` and `/api/jobs`. Stop the process. Do not open a browser. If the server does not start, **not run** |
