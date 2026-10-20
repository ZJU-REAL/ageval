# 07 — 资源上限（Limits）、上游等待与失败语义

`limits` 由 Core 运行时在调用前强制检查，任务脚本内的软性步数限制（如 `max_turns`）不替代 `limits`。事后统计的 token 与费用默认作为观测指标记录，`record` 与 `cleanup` 阶段不消耗业务预算。

容器硬件资源限额（`cpus`、`memory_mb`、`gpus`、`gpu_types`、`verifier_gpus`）声明在任务 `parameters` 下，由 `docker` 环境在容器启动前施加（见 [environment](05-runtime/environment.md)）。

三个业务阶段各自维护独立的阶段计时器，从进入对应阶段时起算：

| 配置键 | 默认值 | 约束范围 | 到期行为 |
| --- | --- | --- | --- |
| `limits.wall_time_seconds` | 300 | `run` 阶段：从阶段入口到任务子进程返回 | 记录 `limit_reached`（`wall_time_seconds`），结束 `run` 阶段并继续进入 `evaluate` 评分 |
| `limits.environment_seconds` | 600 | `environment` 阶段：环境启动、初始数据上传、`after_environment_ready`、`environment_setup` | 记为 `ERROR`（`phase: "environment"`，`title: "environment_timeout"`），不启动 `run` 阶段 |
| `limits.evaluate_seconds` | 600 | `evaluate` 阶段：评分环境启动与上传、评分阶段 `after_environment_ready`、`evaluator.py`、`scoring.exec` 与 `judge` 调用 | 记为 `ERROR`（`phase: "evaluate"`，`title: "evaluate_timeout"`） |

- `limits.agent_invocations` 仅统计 `run` 阶段的模型调用次数（在即将执行 `executor.invoke` 时原子扣减一次；排队期间被取消不扣减，同一次调用内的 `upstream_stall` 重试不重复扣减）。`evaluate` 阶段的 `judge` 调用不占用该额度，由 `evaluate_seconds` 统一约束。
- `limits.agent_concurrency`（正整数，默认 `1`）限制单次 Attempt 在 `run` 阶段同时处于 `executor.invoke` 运行状态的调用数量（跨会话、跨角色共享）。`judge` 调用保持串行准入。

## 上游重试等待（Upstream Stall）

当 `executor.invoke` 返回可重试的传输异常时，`ParentAgentService.invoke` 进入 `upstream_stall` 等待重试，避免因瞬时网络或网关波动直接终止评测：

- 等待预算由角色 profile 的 `options.upstream_stall_seconds` 控制（默认读取 [`src/ageval/runtime/clocks.py`](../../src/ageval/runtime/clocks.py) 中的 `3600` 秒；设为 `0` 时关闭重试），重试间隔固定为 `60` 秒（`stall_interval`）。
- 在 `upstream_stall` 等待期间，当前阶段的计时器（`wall_time_seconds` 或 `evaluate_seconds`）暂停计时（多并发调用按在途 stall 数量引用计数，全部恢复后才继续走表），子进程等待超时同步顺延。
- 在进入执行器之前的本地拒绝（阶段时钟已到期、调用额度已耗尽、脱敏校验失败、强制离线模式）直接返回失败，不进入 `upstream_stall`。

各执行器的可重试判定规则：
- **`openai-http` 与 `anthropic-http`：** 读取超时、连接失败、HTTP `408`、`429` 与 `5xx` 归为可重试的 `TransportStall`；其余 HTTP `4xx` 响应属于不可重试的 `ModelConfigError`（`repeatable=False`）；非法 JSON 为 `ProtocolError`。
- **ACP：** 超时、空闲超时、非预期 EOF 与协议传输错误归为 `TransportStall`，仅当该次 prompt 尚未修改工作区文件（`repeatable=True`）时允许在同一会话上重发。
- **`miniswe`：** 在进程内针对当前单步模型请求执行 stall 重试（关闭其内置的短周期 tenacity 重试），保留已有的对话上下文。
- **`terminus-2`：** 同一次 episode 里对单次模型 POST 做 stall 重试。tmux 安装失败或按键已经写入窗格时不再把整段 episode 交给父进程重放。

证据中的 `summary.json` 会记录一条 `upstream_stall` 事实（含原因、`started_at`、重试次数与结果 `resumed` / `budget_exhausted` / `not_repeatable`）。

## `run` 阶段触及配额上限时的处理

当 `run` 阶段触发 `wall_time_seconds` 或 `agent_invocations` 上限时，系统记录 `limit_reached` 事实，封存 solver 会话并正常收集已有产物快照，随后继续进入 `evaluate` 阶段由 `evaluator.py` 对已生成的产物评分（返回 `PASS` 或 `FAIL`）。此时 `result.json` 顶层 `limit` 字段记录对应的配额键名，`error` 字段保持为 `null`。

## `Result` 状态与 `error` 结构

`bind_evaluation` 的结果仅有两个来源：`evaluator.py` 返回的 `PASS` / `FAIL`（若返回其他字符串则以 `evaluator_invalid_status` 记为 `ERROR`），以及阶段异常产生的 `ERROR`。

当状态为 `ERROR` 时，`result.json` 的 `error` 字段为结构化对象 `{phase, title, message}`（状态为 `PASS` 或 `FAIL` 时 `error` 为 `null`）：

| 字段 | 含义 |
| --- | --- |
| `phase` | 发生错误的阶段名：`environment`、`run`、`evaluate` 或 `record`（进入阶段前的 `lock` / `preflight` 错误为 `null`） |
| `title` | 稳定错误分类标签（供 Viewer 与 Hub 展示及筛选） |
| `message` | 当次错误的具体说明（不含完整堆栈或敏感命令原文） |

`title` 的取值优先级为：
1. `run.py` 或 `evaluator.py` 主动抛出的 `ScriptError(title, message)`：使用传入的 `title` 与 `message`；
2. 任务脚本抛出的其他未捕获异常：使用异常类名（如 `ValueError`）；
3. 引擎内置错误标识：如 `task_worker_no_result`、`environment_setup_failed`、`environment_collect_failed`、`environment_collect_missing`、`environment_timeout`、`evaluate_timeout`、`evaluator_invalid_status`、`ConfigError` 等。

## CLI 退出码与失败归属汇总

| 退出码 | 含义 |
| --- | --- |
| `0` | `PASS`（或 `--probe` 检查就绪） |
| `1` | `FAIL`（或 `--probe` 检查未就绪） |
| `2` | `ERROR` / 配置校验失败 / 运行时异常 |

| 失败类别 | 结果表现 | 归属模块 |
| --- | --- | --- |
| 未知 schema format | `invalid_format`（位于 `/format`） | Config |
| 能力不满足或 `inject` 缺失 | `ageval lock` 报错终止 | Config / plugins |
| 缺失运行凭据 | `preflight` 报错终止（`started: false`） | Environment / executor |
| 任务未达标 | `FAIL` + 连续得分 | Evaluation (`evaluator.py`) |
| `run` 阶段触及配额上限 | 由 `evaluator.py` 判定 `PASS` / `FAIL`，`result.json` 记录 `limit` | Attempt |
| `environment` 阶段超时 | `ERROR`（`phase: "environment"`，`title: "environment_timeout"`） | Attempt |
| `evaluate` 阶段超时 | `ERROR`（`phase: "evaluate"`，`title: "evaluate_timeout"`） | Attempt |
| `evaluator.py` 返回非法状态 | `ERROR`（`phase: "evaluate"`，`title: "evaluator_invalid_status"`） | Evaluation |
| `evaluation.collect` 失败或路径缺失 | `ERROR`（`phase: "evaluate"`，`title: "environment_collect_failed"` / `"environment_collect_missing"`） | Attempt |
| `evaluator.py` 崩溃或缺失返回值 | `ERROR`（`phase: "evaluate"`，`title` 为异常类名或 `ScriptError.title`） | Evaluation |
| `cleanup` 阶段异常 | 记录 warning，不覆盖已绑定的评分结果 | Environment / Attempt |
