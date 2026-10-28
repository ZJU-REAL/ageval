---
name: eval-ops-pitfalls
description: >
  Pre-run environment checks and suite troubleshooting: dead proxies, invocation
  timeouts, package mirrors, model routing, environment_image_unresolved,
  widespread failures, evaluator dependencies, permissions, and CLI/schema
  mismatches. Use when preparing an evaluation run or diagnosing acp_timeout,
  HTTP_PROXY, AGEVAL_AGENT_INVOKE_TIMEOUT, AGEVAL_APT_MIRROR, PEP668, or test
  collection failures.
---

# Evaluation operations pitfalls

Use this skill when preparing or troubleshooting evaluation runs with ageval.
Check infrastructure and evaluator setup before drawing conclusions about model
performance. Mechanism details are defined in `docs/design/*`. Dataset-specific
scoring commands, dependencies, and file preparation belong to the dataset's
README, configuration, and evaluator implementation.

## Before a run

1. **Proxy reachability:** Inspect `env | grep -i proxy` in the process that launches the run. For loopback proxy addresses, confirm a listener exists and is reachable from the process that uses it. Remove stale proxy settings from the launch environment and its configuration source, then retry the affected operation, such as `docker pull`. A successful model API request verifies that request's network path; image pulls and package installs need their own checks.
2. **Invocation timeout:** Read `limits.wall_time_seconds`, the task's invocation pattern, and the effective invocation timeout (`AGEVAL_AGENT_INVOKE_TIMEOUT` or `parameters.agent_timeout_seconds`). When one ACP invocation spans the whole run, allow it to last at least the run's wall-time budget. For multiple invocations, size the timeout for the expected duration of each call. Diagnose `acp_timeout` against these configured values.
3. **Model routing:** Check the complete model id and any provider prefix required by the configured endpoint or gateway. Smoke-test a request through the same routing path used by the agent. If a routing layer rewrites the id, verify the resulting id at the next hop.
4. **Package sources:** Verify the configured APT and Python package sources from the image-build or scoring environment that uses them. Proxy DNS / fake-ip routing can make a mirror unreachable. For `AGEVAL_APT_MIRROR`, see the Docker plugin README. Confirm a representative image build succeeds before starting a batch.
5. **Executable and schema:** Confirm that `ageval` resolves to the intended installation and supports the keys used by the dataset. With multiple worktrees or virtual environments, check which executable the launch process uses. An unknown key such as `evaluation.collect` requires checking both the dataset schema and the installed CLI version.
6. **Scoring setup:** Read the dataset's scoring contract and trace where its evaluator launches commands. Confirm the interpreter, dependencies, file preparation, and write permissions at that execution location before starting a batch.

## Evaluator setup checks

Apply these checks to the execution path declared by the dataset:

- **Execution location:** Trace the evaluator worker and each subprocess or scoring-environment call. Use the failing command's executable and paths to identify the machine or container to inspect.
- **Python environment:** If the evaluator installs packages, use its designated virtual environment and verify that its interpreter, pip, and test runner agree. For PEP668 errors, inspect the interpreter receiving the install. Check inherited `PYTHONPATH` and `PYTHONHOME`; clear them for package-install subprocesses when they redirect imports away from the intended environment.
- **Test dependencies:** Confirm the dataset's declared test requirements are installed before test collection. Missing imports and collection failures require checking evaluator setup before interpreting a recorded FAIL as task performance.
- **Files and permissions:** If scoring removes submitted files or overlays reference files, follow the dataset's documented order. Confirm that the scoring process can read and write the staged workspace. When container-written files are host-owned by root, use the dataset's supported ownership preparation for the scoring user.
- **Copied files:** Exclude `.DS_Store` and `._*` AppleDouble files when preparing dataset copies or archives; they can be mistaken for test modules or wheels.

## Widespread failures

Inspect representative results and trajectories when nearly all tasks fail,
patches are empty, or agents never start. Establish whether the common cause is
image resolution, gateway routing, dependency installation, or another setup
failure.

Once infrastructure has invalidated a suite, fix the cause and verify a
representative run before starting a fresh suite. With the owner's approval,
delete the invalid suite. Keep affected results out of performance reporting;
repeatedly replacing runs under the same broken configuration wastes quota.
Resolve or explicitly report outstanding ERROR results and record task-solving
FAIL results separately.

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| `environment_image_unresolved` / `compose_build_failed` | Proxy reachability, package sources, and the task Dockerfile or compose build |
| `acp_timeout` while wall time remains | Effective invocation timeout and whether one invocation spans the full run |
| API 400 / no healthy deployments | Model id, required provider prefix, gateway rewrite rules, and deployment health |
| PEP668 / `externally-managed-environment` | The failing install's interpreter, execution location, virtual environment, and inherited Python variables |
| Missing imports or test collection errors recorded as FAIL | Declared test dependencies and the interpreter running collection |
| `PermissionError` writing the workspace or home directory | File ownership and permissions relative to the scoring process's user |
| Unknown evaluation configuration key | Dataset schema and the CLI installation used by the launch process |
| pytest discovers `._*.py` / BadZipFile for `._*.whl` | AppleDouble files introduced during copying or archive creation |

## References

| Topic | Authority |
| --- | --- |
| Limits and ACP timeout mechanisms | `docs/design/01-core-lifecycle.md`, `docs/design/05-executors-and-acp.md` |
| Evaluation execution and isolation | `docs/design/03-task-sdk-and-evaluation.md` |
| Package-source settings | `src/ageval/plugins/contrib/docker/README.md` |
| Scoring commands, dependencies, and file preparation | The dataset's README, configuration, and evaluator implementation |
| Other CLI failures | `$ageval-cli` -> `references/failures.md` |
