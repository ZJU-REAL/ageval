# CLI failure diagnosis

| Symptom | Check |
| --- | --- |
| exit 2, empty stdout on lock | Config error on stderr (`unknown_profile`, schema, `invalid_format` at `/format`) |
| lock `unsupported_capability` / `unsupported executor` | Kind not in `ageval executors` `.supported` — coding agents need `executor: acp` |
| lock `options.entry required` | ACP profile missing `- plugin: acp` / `options.entry` |
| Agent ERROR offline | Expected under `AGEVAL_OFFLINE_AGENT=1` |
| executor unbound on docker | Plugin did not bind to the environment (`attach_stdio` / in-environment worker). Do not silently fall back to the host |
| `image_contribute_unsatisfied` / missing bake | Bound external executor but `config.image_layers` / `Dockerfile.bake` empty — `$ageval-plugin` |
| `nooa_package_missing` / `No module named 'nooa'` | Host needs `uv sync --extra nooa`; docker writes the package into the image |
| ACP entry not ready | `ageval executors -v` → that `entry_id` `host_ready` / install pin; no invoke-time `npm i` |
| `credential_missing` | Declared credential env names unset and no `api_key` locator. Required ACP entries fail at `--probe` / session-open; keyless (OAuth) warn only. HTTP executors (`openai-http` / `anthropic-http` / `dsh` / `nooa` / `miniswe`) skip this when locked `base_url` host is `127.0.0.1` / `localhost` / `::1` |
| e2b / ssh probe not ready | Missing `E2B_API_KEY` or SSH locator — the check fails and the run does not start; `started: false`. Skip is not a pass |
| PASS without real model | Forbidden — do not use fixtures as public proof |
| Trajectory empty | Non-empty `agent_profiles` + `run.py` `Agent.session`/`invoke` |
| Resume skipped an ERROR | Default `--resume-suite` skips finished PASS / FAIL / ERROR. Use `--replace-slot --task T` |
| Export fails `unsealed_invocation` | Attempt still running or metadata not terminal |
| Export fails `secret_residual` | Fix source evidence; do not strip secrets by hand in export dir |
| Docker ERROR | Docker daemon, image build, network/creds projection; read result / agent meta under `.ageval/runs/` |
| Run-phase limit (`wall_time_seconds`, `agent_invocations`) | Evaluator PASS/FAIL (exit 0 or 1). `result.json` `limit` is that key. Evaluate still runs |
| Environment clock | ERROR, phase `environment`, token `environment_timeout`. Run does not start |
| Evaluate clock | ERROR, phase `evaluate`, token `evaluate_timeout` |
| Evaluator status other than PASS / FAIL | ERROR, phase `evaluate`, token `evaluator_invalid_status` |

Design: `docs/design/05-runtime/evidence.md`, `docs/design/07-budget-evaluation-failure.md`.
