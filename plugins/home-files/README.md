# home-files

`ageval.plugin/1` that copies overlay files into Attempt
`$HOME` or workspace. Chain `after_environment_ready` only. No bake.

## Capabilities

| | Value |
| --- | --- |
| export | — |
| inject | — (copies through the Attempt host `upload` after the environment is ready) |
| chain | `after_environment_ready` |
| bake | — |

## Install

```bash
ageval plugin install plugins/home-files
```

Install writes `$AGEVAL_HOME/plugins` only. It never rewrites profiles.

## Bind

```yaml
executor: acp
extensions:
  - plugin: acp
    options:
      entry: opencode
  - plugin: home-files
    options:
      files:
        - src: overlays/opencode.litellm.json
          dest: .config/opencode/opencode.json
          dest_root: home
```

## Parameters

| Name | Default | Purpose |
| --- | --- | --- |
| `options.files` | unset (no-op) | List of overlay rows. Omit / empty → copy nothing. Must be a list. |
| `options.files[].src` | *(required per row)* | Relative to the overlay root: the installed Agent package when the binding has `agent_ref`, otherwise the Dataset root. No `..`, no absolute path. |
| `options.files[].dest` | *(required per row)* | Relative to `dest_root`. No `..`. Not under `evaluation/`. |
| `options.files[].dest_root` | *(required per row)* | `home` or `workspace`. Any other value is rejected. |

Secrets stay locators. Overlay JSON must not embed tokens or upstream URLs.
Use `${NAME}` (same as profiles) or `{env:NAME}`. Copy expands those from the
same `.env` chain as lock (process env, then dataset `.env`, cwd `.env`, repo
`.env`). Unset names are rejected. Bare `$NAME` is left for the engine (Pi
`apiKey`). No JSON deep-merge.

To show the same files on Hub Agent Performance, list them on this role as
`overlays:` (paths under `overlays/`, resolved from the Agent package when
`agent_ref` is set). That field is the
published set; this plugin still copies only its own `files[].src`.

## Run

```bash
ageval plugin install plugins/home-files
ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/acp-profiles/profiles.acp.opencode.glm-5.2.yaml
ageval run examples/datasets/minimal-demo --task terminal-jsonl-agg \
  --profiles examples/datasets/minimal-demo/acp-profiles/profiles.acp.opencode.glm-5.2.yaml
```
