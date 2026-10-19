# Red lines (worked examples)

## Evaluation result

- **OK:** Agent invocation fails; `Result` status is `ERROR` or `FAIL`; trajectory files remain archived for inspection.
- **Forbidden:** Infer `PASS` because `final-response.json` exists or `run.py` returned `RunTerminal.completed`.

## Secrets

- **OK:** Dataset bindings with `executor` / ACP `- plugin: acp` / `options.entry` / `model.id` only; credentials referenced via host environment variable locators.
- **Forbidden:** API keys, DSN passwords, or Bearer tokens committed in `ageval.yaml`, `lock.json`, evidence files, skill text, or examples.

## Adapter naming

- **OK:** YAML `executor: acp` + `- plugin: acp` / `options.entry: codex|pi|opencode|…`; `openai-http`; `anthropic-http`; `docker` environment plugin.
- **Forbidden:** `executor: codex|pi|opencode|claude-code` as standalone executor IDs; `TerminalBenchAdapter`; task-ID branches in Core.

## Plugins

- **OK:** `ageval plugin install plugins/nooa` then bind `executor: nooa` in `profiles.yaml`; Docker is ready after plugin `image_layers` build into the image.
- **Forbidden:** Treat `plugin install` as Docker-ready; rewrite `profiles.yaml` during install; branch on `if kind == "nooa"` in Core; add a product `executor: mock`.

## Evidence grade honesty

- **OK:** Report the actual verified `execution_location` and environment kind.
- **Forbidden:** Claim full `isolated` or `real-benchmark-verified` from a single local/Docker smoke pass, or treat skipped CI checks (`AGEVAL_SKIP_REAL_ACP=1`) as passed.

## Environment kind

- **OK:** `environment: local|docker|e2b|ssh|daytona` in `profiles.yaml`.
- **Forbidden:** Legacy `provider.kind` or `assurance: l0/l1` fields.
