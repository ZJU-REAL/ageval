# ageval Canonical Glossary

This document defines the canonical terminology for **ageval** across both internal specifications and public reader-facing surfaces. All documentation, CLI help text, UI copy, and code comments MUST use the canonical terms below and MUST NOT use terms listed in the **Forbidden / Avoid** column.

Machine verification for public surfaces is enforced by `python3 scripts/check_public_terms.py`.

---

## 1. Surface Classification

| Surface | Covered Paths | Terminology Rule |
| --- | --- | --- |
| **public** | Root `README.md`, `README.zh-CN.md`, [`website/`](../website/), `examples/**/README*`, plugin READMEs | Must use terms marked `public` or `both`. Never expose internal-only class names as user concepts, and never include GitHub Issue numbers. |
| **internal** | `docs/design/*`, `docs/PRD.md`, `docs/RFCs/*`, `AGENTS.md`, `ARCHITECTURE.md`, `skills/*` | May use terms marked `both` or `internal`. |

---

## 2. Core Naming Principles

1. **Preserve protocol and schema identifiers**: Terms that correspond to CLI commands, configuration keys, or schema formats (`dataset`, `task`, `lock`, `PASS`, `FAIL`, `ERROR`, `gold`, `limits`, `Attempt`, `suite`, `ModelSpec`) retain their exact Latin identifiers in both English and Chinese documentation.
2. **Agent = Model + Harness**: A deployable agent consists of a **model** and a **harness** (the agent runtime managing interaction loops and tool execution, such as `pi`, `codex`, `claude-code`, `opencode`, `miniswe`, `terminus-2`, `openhands`, `dsh`, or `nooa`). **ageval** is the evaluation platform, never a harness. An `ageval.agent/1` bundle is called an **Agent package** (Agent 包).
3. **Environment, never "box"**: Execution backends (`local`, `docker`, `e2b`, `daytona`, `ssh`) are always called **environments** (环境) or **scoring containers / scoring hosts** (评分环境 / 评分容器). Never refer to an environment or container in prose as a `box`, `agent box`, `scoring box`, `盒子`, `箱子`, or `打分盒` (except when citing the internal Python class `BoxSpec`).
4. **Standard plugin engineering terms**: The extension system uses **plugin slots** (`slot`), divided into **exclusive slots** (`exclusive slot`) and **chain slots** (`chain slot`), with **dependency injection** (`inject`) and **service exports** (`export`). Never call a bound exclusive-slot implementation a `winner` (`赢家` / `exclusive-slot winner`).
5. **Phases, never "相位"**: The fixed steps `environment → run → evaluate → record` (and `cleanup` in `finally`) are called **phases** (阶段).
6. **Profiles vs. Jobs**: `profiles.yaml` is called the **profiles configuration** (配置文件 / `profiles`). **jobs** refers exclusively to the run list in Hub and Viewer. Never call `profiles.yaml` a `job document` (`job 文档`), and never call a single Attempt a `job`.
7. **Resource limits, never "hard ceilings"**: Pre-effect budgets are called **`limits`** or **resource limits / invocation quotas** (资源上限 / 调用配额), never `hard ceilings` (`硬顶`).
8. **No private metaphors or slang**: Avoid invented metaphors or internal shorthand such as `题包`, `证据包`, `金标`, `观察袋`, `插件袋`, `层 B / 层 C`, `layer-B / layer-C`, `探测管子`, `字段糖`, `硬切`, `机制卡`, or `勾选机`.

---

## 3. Canonical Terminology Table

| Canonical English | Canonical Chinese (Bilingual Surfaces) | Surface | Definition | Forbidden / Avoid |
| --- | --- | --- | --- | --- |
| **ageval** | ageval | both | Product, Python package, and CLI name (`ageval-cli` on PyPI). | `AgEval` as product name, `agent-eval` as CLI |
| **dataset** | dataset / 评测数据集 | both | Benchmark delivery unit: root `ageval.yaml` (`ageval.dataset/1`) + `tasks/<id>/`. | `Database`, `database_id`, `task package`, `题包` |
| **task** | task / 任务 | both | Single dataset member: `tasks/<id>/task.yaml` + `run.py` + `evaluator.py`. | `题包` |
| **task script** | 任务脚本 | both | `run.py` and `evaluator.py` inside a task directory. | Calling `run.py` `harness.py` |
| **profiles** (`profiles.yaml`) | 配置文件 / `profiles.yaml` | both | Environment, role executor, and `ModelSpec` binding configuration (`ageval.profiles/1`). | `job document`, `job 文档` |
| **jobs** | jobs | both | Run history table in Hub and Viewer. | Calling `profiles.yaml` or an Attempt a `job` |
| **Agent package** | Agent 包 | both | `ageval.agent/1` configuration bundle (executor, entry, model defaults, overlays). | Calling the package format itself a `harness` |
| **harness / agent runtime** | harness / Agent 运行时 | both | The evaluated runtime driving model turns and tool calls (`pi`, `codex`, `claude-code`, `miniswe`, `terminus-2`, `openhands`, `dsh`, `nooa`). | Calling `ageval` a harness; `first-class eval axis`; `一等评测维度`; `harness beneath` |
| **Attempt** | Attempt / 单次运行 | both | Single execution of one task, archived under `.ageval/runs/<attempt_id>/`. Retries and regrades mint a new Attempt. | `可见 Attempt`, calling an Attempt a `job` |
| **Trial** | Trial | internal | Sequence of Attempts sampling `(task_id, locked_config_digest)`. | Mixing Trial and Attempt in introductory guides |
| **`ageval run`** | `ageval run` | both | CLI execution entrypoint (not a synonym for an Attempt directory). | Using `run` to mean `.ageval/runs/<id>/` |
| **suite** | suite / 整份 dataset 运行 | both | Dataset-wide execution (`ageval run <dataset>` without `--task`), archived under `.ageval/suite-runs/<suite_run_id>/`. | `suite PASS` |
| **Campaign** | Campaign | both | Parameter-matrix execution via `ageval campaign`. | — |
| **Core** | Core | both | The runtime engine managing locking and the four fixed execution phases. | `内核` |
| **environment** | 环境 | both | Execution backend (`local`, `docker`, `e2b`, `daytona`, `ssh`). | `box`, `agent box`, `Attempt box`, `in-box`, `in-image`, `盒子`, `箱子` |
| **scoring host / scoring container** | 评分环境 / 评分容器 | both | Environment instance running `evaluator.py` commands or judge sessions during `evaluate`. | `scoring box`, `打分盒` |
| **executor** | executor / 执行器 | both | Per-profile plugin bound to the `executor` exclusive slot (`acp`, `openai-http`, `anthropic-http`, `miniswe`, `terminus-2`, `openhands`, `dsh`, `nooa`, `acp-oneshot`). | `oneshot` (alone without `acp-oneshot`), `host-loop` (on public copy) |
| **plugin slot** (`slot`) | 插件槽 | both | Extension point defined in `src/ageval/plugins/slots.py`. | `机制卡` |
| **exclusive slot** | 独占槽 | both | Slot binding a single implementation per resolution graph and exporting it as a same-named service (`environment`, `executor`, `evaluation_runtime`, `trajectory_seal`). | `winner`, `exclusive winner`, `exclusive-slot winner`, `赢家` |
| **chain slot** | 链槽 | both | Priority-ordered hook chain `(ctx, value, nxt)` emitted during lifecycle phases. | — |
| **plugin dependency graph** (`ExtensionGraph`) | 插件依赖图 / `ExtensionGraph` | both | Resolved slot bindings and service dependency graph produced by `ageval lock`. | — |
| **dependency injection / service export** (`inject` / `export`) | 依赖注入 / 服务导出 | both | Declarative service and capability dependencies verified during `ageval lock`. | `按名注入` |
| **configuration locking** (`lock` / `digest`) | 配置锁定 / `ageval lock` | both | Pre-execution validation producing `LockedTaskConfig` and its canonical SHA-256 `digest`. | `一并锁定`, `锁定评测维度` |
| **limits** | `limits` / 资源上限 | both | Pre-effect phase timeouts, invocation quotas, and concurrency caps. | `hard ceiling`, `hard ceilings`, `硬顶` |
| **reference materials** (`gold`) | 参考材料 / 参考答案 / `gold` | both | Grading assets under `tasks/<id>/evaluation/`, uploaded only during `evaluate`. | `金标` |
| **evidence** | 执行证据 / evidence | both | Secret-redacted Attempt archive under `.ageval/runs/<attempt_id>/`. | `证据包`, `存证` |
| **trajectory** | 轨迹 (`trajectory.jsonl`) | both | Normalized interaction event log sealed during `record`; observational only, never decides `PASS`. | `密封轨迹`, `layer-B`, `layer-C`, `层 B`, `层 C` |
| **`extra` field** | 扩展字段 / `extra` | both | Structured extension object on `terminal.extra` or `summary.extra`. | `观察袋`, `插件袋`, `袋子` |
| **analyzer** | 分析器 / analyzer | both | Post-run read-only diagnostics (`stats`, `hack`, `review`) over sealed evidence. | — |
| **checks** (`evaluation/checks.json`) | 检查项 / `checks` | both | Optional step-level grading breakdown returned by `evaluator.py` (`ageval.evaluation.checks/1`). | `勾选机` |
| **projected workspace** | 工作区可见文件 | both | Files uploaded to `/attempt/workspace` and visible to the evaluated agent during `run`. | — |
| **snapshot share** | 快照分享 | both | Read-only share link `/s/{token}` (`static` or `--live` mode). | — |
| **phase** | 阶段 | both | Top-level Attempt lifecycle stage (`environment`, `run`, `evaluate`, `record`, `cleanup`). | `相位` |
| **`attach_stdio`** | `attach_stdio` | both | `EnvironmentProvider` method spawning a foreground process inside the environment and returning bidirectional `stdin`/`stdout` streams. | `探测管子`, `attach 管子` |
| **ACP entry** | ACP entry | both | `options.entry` under `executor: acp` (`pi`, `codex`, `claude-code`, `opencode`, `grok-build`, plus `$AGEVAL_HOME/acp-entries.json`). | `内置卡` |
| **capabilities** | 能力标记 | both | Boolean capability flags declared on `EnvironmentCapabilities` (`exec`, `upload`, `download`, `attach_stdio`, `uid_gid`, `path_views`, `compose`). | — |
| **BYOK / BYOA** | BYOK / BYOA | internal | Environment-variable API key projection vs. allowlisted host subscription auth file copy into `/attempt/home`. | — |
| **hosted job** | 托管评测 / 托管运行 | both | Hub-submitted evaluation job executed by a background worker on E2B or Daytona. | — |
| **org secret** | 组织密钥 | both | Encrypted organization-scoped model or cloud-provider secret stored in Registry. | `vault` |
| **composition root** | 组合根 | internal | `src/ageval/application/composition.py`, the sole production wiring module (`build_*`). | — |
| **Control Plane** | 控制面 | internal | Host parent process orchestrating child workers and environment providers. | — |
| **fail fast before execution** | 校验失败即终止 | both | Rejecting invalid configurations or missing credentials during `lock` or `preflight` before starting execution. | `fail-closed`, `fail closed`, `fail-open` (on public copy) |
| **image bake** | 构建期写入镜像 | both | Installing base runtimes and plugin `image_layers` at image build time rather than during `invoke`. | `烘焙` |
| **isolated scoring container** (`evaluate_host.isolated`) | 独立评分容器 (`evaluate_host.isolated`) | both | Dedicated Docker container started during `evaluate` so `gold` never enters the solver environment. | Bare `isolated` without context |
| **evidence grade** | 内部验收分级 | internal | Internal repository delivery verification tier (`design-only`, `runnable-mvp`, `isolated`, `real-benchmark-verified`). | Using `evidence grade` / `证据等级` on public copy |
| **`ModelSpec`** | `ModelSpec` | both | Immutable model contract resolved from nested `model:` (`id`, `api`, `reasoning_effort`, `timeout`, `watchdog`, `extra`). | `字段糖` |
| **`BaseEnvironment`** | `BaseEnvironment` | internal | Abstract base class for `@environment_plugin` implementations. | — |
| **`BaseExecutor`** | `BaseExecutor` | internal | Abstract base class for `@executor_plugin` implementations (`supports_model`, `bind_model`). | `consumes_model` |
| **`extra_allowlist`** | `extra_allowlist` | internal | Explicit `frozenset` on `BaseExecutor` subclasses naming permitted top-level keys in `model.extra`. | — |

---

## 4. Verdict Status Definitions (`PASS` / `FAIL` / `ERROR`)

| Status | Normative Meaning |
| --- | --- |
| **`PASS`** | Bound exclusively by `bind_evaluation` when `evaluator.py` returns `status: "PASS"`. `RunTerminal.completed`, trajectory sealing, ACP `end_turn`, or staying within `limits` never produce `PASS`. |
| **`FAIL`** | Bound exclusively by `bind_evaluation` when `evaluator.py` returns `status: "FAIL"`. When `run` reaches a quota limit (`wall_time_seconds` or `agent_invocations`), `evaluate` still runs `evaluator.py` to grade harvested artifacts as `PASS` or `FAIL`. |
| **`ERROR`** | Produced by environment startup failure, `environment` or `evaluate` phase timeout, `evaluation.collect` failure, or `evaluator.py` crashing or returning a status other than `PASS` / `FAIL`. `result.json` records `error: {phase, title, message}`; on `PASS` and `FAIL`, `error` is `null`. |

---

## 5. Registered Schema Formats

```text
ageval.dataset/1 · ageval.task/1 · ageval.plugin/1 · ageval.profiles/1 · ageval.agent/1 · ageval.trajectory.event/1 · ageval.evaluation.checks/1 · ageval.analysis.report/1 · ageval.analysis.summary/1
```

Any unrecognized `format` value fails immediately with `invalid_format` at `/format` without legacy alias fallback.
