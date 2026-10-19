# Evidence

证据目录的路径常量统一维护在 `src/ageval/evidence/` 中。整体数据流见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)。

单次 Attempt 的证据归档目录位于 `<dataset>/.ageval/runs/<attempt_id>/`：

| 文件 / 目录 | 含义 |
| --- | --- |
| `lock.json` | 脱敏后的锁定配置摘要（仅保留凭据环境变量名引用） |
| `result.json` | 结构化评测结果（`status` / `score` / `kind` / `error` / `limit` / `logs`） |
| `trajectory.jsonl` | `run` 阶段的标准化交互轨迹，由 `trajectory_seal` 独占槽实现写出 |
| `evaluation/observation.jsonl` | `evaluate` 阶段 `judge` 会话的标准化轨迹（可选，自动省略 `user` 提示行） |
| `evaluation/checks.json` | `evaluator.py` 返回的分步检查项明细（可选，`ageval.evaluation.checks/1`） |
| `summary.json` | 各阶段耗时（`phase_timing`）、运行事实（`facts`）及可选扩展字段 `extra` |
| `task-artifacts/` | `run` 阶段结束时收集的任务产物快照（文件或目录树） |
| `verifier-collect/` | `evaluation.collect` 收集的容器路径快照（可选） |

`summary.json`、`result.json` 与轨迹 `terminal` 行的 Schema 定义在 `src/ageval/evidence/documents.py` 中，并由 `scripts/gen_evidence_ts.py` 自动导出生成 `apps/shared/lib/evidence.gen.ts`（`--check` 校验同步）。

`Result.logs` / `evidence_path` 指向该 Attempt 目录；`ageval evidence <logs> --out …` 支持在二次脱敏校验后导出已封存的证据目录。

## 轨迹事件处理与展示表面

运行时调用期间的轨迹数据经过三步处理后落盘：
1. **原始响应（`backend_raw`）：** 执行器原始请求与响应载荷；
2. **标准化事件（`ageval.trajectory.event/1`）：** 执行器或 `trajectory_collect` 映射的统一事件行（`thought` / `assistant` / `tool_call` / `observation` / `permission` / `terminal`）；
3. **封存轨迹文件（`trajectory.jsonl`）：** `record` 阶段由 `trajectory_seal` 按调用顺序（`seq` / `turn_index`）合并写出的最终轨迹文件。

每条轨迹事件均带有顶层 `profile_id` 字段以标识对应的角色（如 `solver`、`planner` 等），Viewer 与 Hub 按文件顺序展示并按 `profile_id` 区分多角色交互。

| 展示区域 | 归档文件 | 数据来源 | Web 界面位置 |
| --- | --- | --- | --- |
| 待测 Agent 轨迹 | 根目录 `trajectory.jsonl` | `run` 阶段角色调用 | Trajectory 页签 |
| 评分 Judge 轨迹 | `evaluation/observation.jsonl` | `evaluate` 阶段 SDK 调用 | Verifier 页签（Trajectory 视图） |
| 确定性检查项 | `evaluation/checks.json` | `evaluator.py` 返回的 `checks` | Verifier 页签（Files 视图下预览） |

在 Verifier 页签中：若同时存在 `evaluation/observation.jsonl` 与 `evaluation/checks.json`，页签栏右侧提供 `Trajectory / Files` 切换开关（默认显示 Trajectory）；若仅存在其中一种，则直接渲染对应视图。

## 轨迹 `terminal.usage` 与 `extra` 扩展字段

封存后的 `terminal` 轨迹行包含标准化的 `usage` 字段与同级 `extra` 扩展字段：

```text
usage: { prompt_tokens, completion_tokens, cached_tokens, cost_usd }  # 标准统计项；未报告则省略
extra: { ... }                                                       # 厂商附加统计与插件扩展字段
```

- 标准字段（`prompt_tokens`、`completion_tokens`、`cached_tokens`、`cost_usd`）仅在后端实际报告时写入；若未报告、超时中断、解析失败或仅收到部分数据，则在 `usage` 中记录 `unavailable` 及原因（`not_reported` / `lost_on_timeout` / `parse_failed` / `partial`），绝不将缺失值填为 `0`。
- 厂商特定字段（如 `reasoning_tokens`、缓存写入 token、ACP `session_journal` 来源标记等）及插件自定义观测数据存放在 JSON-safe 的同级 `extra` 字段中。
- `trajectory_collect` 与 `trajectory_enrich` 链槽可在 `extra` 中补充字段，但不得删除标准 `usage` 字段。

## Attempt `summary.extra` 扩展字段

`summary.json` 支持根级可选字段 `extra`（按插件 ID 命名空间隔离，为空时整键省略）：

```text
extra: { <plugin_id>: { ... }, ... }
```

在 `trajectory_seal` 完成后，Core 触发一次 `summary_enrich` 链槽（起始值为 `{}`），各插件仅写入自身的 `extra[<plugin_id>]` 命名空间。Hub 与 Viewer 在运行详情页将其渲染为可折叠的 JSON 面板。

## `terminal.elapsed_ms` 耗时记录

单次调用的墙钟耗时记录在调用元数据 `latency_ms` 中，并在轨迹封存时同步至 `terminal.elapsed_ms`，供轨迹步骤卡片展示单步耗时。

## 封存后的默认保留文件集

在 `trajectory_seal` 封存成功后，`slim_sealed_attempt` 默认精简中间临时文件，在磁盘与 Hub 归档中保留以下核心文件：

```text
lock.json
result.json
trajectory.jsonl
summary.json
task-artifacts/**              # run 阶段结束时收集的文件或目录树快照
verifier-collect/**            # evaluation.collect 收集的路径快照（manifest 不含命令原文）
evaluation/observation.jsonl   # 仅当 evaluate 阶段发生 SDK 调用时存在
evaluation/checks.json         # 仅当 evaluator.py 返回有效 checks 时存在
```

若需在归档后保留底层原始调试文件（`backend_raw/`、单次调用的 `request.json` / `events.jsonl` / `final-response.json` / `metadata.json` 以及 `evaluator_raw.json`），可在运行时传入 `--keep-vendor-raw`。`--keep-workspace` 则用于保留宿主工作区临时目录，二者相互独立。
