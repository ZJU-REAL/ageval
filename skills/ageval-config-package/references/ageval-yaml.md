# Field catalog

Formats: `ageval.dataset/1`, `ageval.task/1`, `ageval.profiles/1`. Unknown format → `invalid_format` at `/format`.

Dataset root keys: `format`, `dataset_id`, `version`, `description`, `tasks`. No `database_id`.

Task: `format`, `task_id`, `parameters`, `agent_profiles` (role ids only), `limits`, `artifacts`, `evaluation`, `provenance`, `requires`. Files present (`run.py`, `evaluator.py`, Dockerfile, `setup.sh`) are recognized. No `harness:` block, no `provider.kind`, no `assurance`.

`limits`: `wall_time_seconds` (run only, default 300), `environment_seconds` (default 600), `evaluate_seconds` (default 600), `agent_invocations` (run-phase invokes only, default 1). An unknown key is rejected once. `limits.*` is not overridable with `--set`.

Profiles: `format`, `environment`, `environment_options`, `agent_profiles`. Role rows may have `executor`, `model`, `api_key` (locator), `options.entry`, `extensions`.

Plugin knobs (`environment_options.*`, `extensions[].options`, role `model` / `api_key` / `base_url`) live in **that plugin's README** Parameters table (name, default, purpose). Capabilities (export / inject) are the other required table. Do not copy keys from a sibling plugin.

`api_key: ${ENV}` is a locator name. Value never enters lock.

`--set` allowlist lives in Config Core, not here.
