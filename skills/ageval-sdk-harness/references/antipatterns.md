# run.py antipatterns

| Antipattern | Do instead |
| --- | --- |
| Treat `completed` as PASS | Independent evaluator only |
| Treat judge `invoke` text / `observation.jsonl` as PASS | Return `{status, score, metrics}`; engine binds |
| `if executor == "codex":` / `if entry == "pi":` for Core policy | Switch `agent_profiles` / `active_profile` / `parameters.roles` |
| Write `executor: codex` in package yaml | `executor: acp` + `- plugin: acp` / `options.entry: codex` (etc.) |
| Read `~/.codex/auth.json` or print secrets | Rely on Runtime projection |
| Write training JSON by hand under package | Use Core `trajectory.jsonl` under Result.logs |
| Soft CallLimit as the only hard ceiling | `limits.agent_invocations` in yaml (Runtime, run phase only) |
| Import evaluation gold into `run.py` | Keep gold unmounted; upload after the run stops writing |
| Branch on task_id / benchmark name in Core path | Mechanism-only adapters |
