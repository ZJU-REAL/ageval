# openhands — in-environment Software Agent SDK

External `ageval.plugin/1` package. **Not** first-party ageval core (only ACP is first-party).

This plugin runs the [OpenHands Software Agent SDK](https://docs.openhands.dev/sdk)
inside the Attempt environment. The parent does not import the SDK. It injects
the `environment` service (`exec`, `upload`, `download`), uploads a worker,
and runs that worker with `host.exec`.

The workspace is the Attempt directory. The runner builds a local workspace
only, so the SDK does not start a second sandbox. Task text is uploaded as a
file and passed by path, which keeps a long instruction off argv.

Profile `base_url` + `api_key` (env locator) project into the exec env as
`OPENAI_BASE_URL` / `LLM_BASE_URL` and `OPENAI_API_KEY` / `LLM_API_KEY`.
Values never enter the lock. The trajectory file is a structured step list
(`openhands.trajectory/1`), mapped to `ageval.trajectory.event/1` at record
time. Stdout is not the transcript. Thinking stored on an action
(`thought`, `reasoning_content`, thinking blocks, and visible Responses
reasoning) is a `thought` step before that tool call. Record writes it as
an assistant turn with `part: thought`. The final reply stays a normal
assistant turn.

A missing SDK at setup is installed at the pinned version. If that install
fails, invoke returns `openhands_sdk_install_failed` and does not scrape a
partial log into the trajectory.

## Capabilities

| | Value |
| --- | --- |
| export | exclusive `executor` |
| inject | `environment`: `exec`, `upload`, `download` |
| chain | `trajectory_collect` |
| bake | `docker/Dockerfile.bake` |

A kind that cannot `exec` / `upload` / `download` fails at `ageval lock`, not mid-invoke.

## Parameters

`options` merge: profile `options` then this plugin's `extensions` row (last wins).

<!-- ageval:param-table executor=openhands -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.version` | 1.56.0 | Exact openhands-sdk and openhands-tools version (X.Y.Z). Omit uses the packaged pin. Ranges, blanks, and non-pins are rejected. |
| `options.max_iterations` | 40 | Cap on SDK iterations for one invoke. A non-positive value, bool, or non-integer is rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

| Name | Default | Purpose |
| --- | --- | --- |
| `model` | `openai/gpt-4.1-mini` | Nested `model.id`, passed through to the SDK. |
| `model.api` | `chat` | Accepted `chat` or `responses`. The SDK selects the wire format. |
| `model.reasoning.effort` | omit | Sent as the SDK `reasoning_effort` when set, including `none`. |
| `api_key` | `OPENAI_API_KEY` / `litellm_api_key` | Env **locator name**. Value never enters the lock. Omit on loopback `base_url` (`127.0.0.1` / `localhost` / `::1`). |
| `base_url` | `OPENAI_BASE_URL` / `litellm_base_url` / `AGEVAL_OPENAI_BASE_URL` | OpenAI-compatible base projected into the worker. |

## Install

```bash
ageval plugin install plugins/openhands
```

Install updates `~/.ageval/plugins` (or `$AGEVAL_HOME/plugins`) only — **never** edits
`profiles.yaml` / `ageval.yaml` / `task.yaml`. The parent process does not need
the SDK installed. `docker/Dockerfile.bake` pins `openhands-sdk` and
`openhands-tools`. A box that does not already have that pin gets the same
versions from `pip` at setup, or fails closed.

## Bind

```yaml
format: ageval.profiles/1
environment: docker
agent_profiles:
  solver:
    executor: openhands
    extensions:
      - plugin: openhands
      - plugin: docker
    model:
      id: openai/glm-5.2
      reasoning:
        effort: max
    api_key: ${litellm_api_key}
    base_url: ${litellm_base_url}
```

## minimal-demo smoke

```bash
ageval plugin install plugins/openhands
unset AGEVAL_OFFLINE_AGENT
ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/profiles.openhands.yaml
```

Evidence for a successful invoke includes `execution_location: attempt-container`
and `backend_raw/openhands_trajectory.json`. A kind that cannot `exec` fails at
`ageval lock`, not mid-invoke.

## Recognition ≠ this host can run ≠ image baked

- **install** → Recognition only (`plugin list` / executor visible)
- **profiles `executor: openhands`** → exclusive-slot implementation (+ model / base_url / api_key)
- **`extensions: [{plugin: openhands}]`** → opt-in bake / trajectory collect
- **`--probe`** → binding-aware feasibility; no Agent, no bake
- **image baked** → `Dockerfile.bake` installs the pinned SDK into the environment Python. The worker is uploaded at invoke
