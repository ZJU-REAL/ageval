# 07 — limits 与失败

`limits` 由 Runtime 在效果前强制。dataset 软限（max_turns）不能替代 `limits`。事后 token/cost 只作观测。`record` 与 `cleanup` 不计预算。

三个相位各有一只时钟，从该相位入口起算。已有超时的步骤读当前相位剩余时间。`host.start` 本身不加超时。

| 键 | 缺省 | 覆盖 | 到期 |
| --- | --- | --- | --- |
| `limits.wall_time_seconds` | 300 | run：从入口到 task worker 返回 | 记下 `limit_reached`，名字 `wall_time_seconds`。run 结束，evaluate 照常打分 |
| `limits.environment_seconds` | 600 | environment：box start、seed upload、`after_environment_ready`、`environment_setup` | ERROR，phase `environment`，token `environment_timeout`。run 不开始 |
| `limits.evaluate_seconds` | 600 | evaluate：打分 Host 的 start 与 upload、evaluate 相位的 `after_environment_ready`、evaluator worker、`scoring.exec`、evaluate 相位的 invoke | ERROR，phase `evaluate`，token `evaluate_timeout` |

`limits.agent_invocations` 只计 run 相位的 invoke。`seal_run` 之后才打开的 profile（evaluate 的 judge）不占这只额度，由 `evaluate_seconds` 封顶。写出 `0` 时，run 相位每一次 invoke 都被拒绝。同一次 parent invoke 里的上游 stall 只扣这一次额度，中间的重试不另扣。

## 上游 stall

executor invoke 的 `ok` 不是 true 时，Parent 进入 upstream stall，而不是第一次失败就结束 Attempt。stall 停在 `ParentAgentService.invoke`。`before_agent_invoke` 与 `after_agent_invoke` 仍各跑一次，自己不转重试。没有名为 `invoke` 的槽。

`options.upstream_stall_seconds` 写在该 executor 已经在读的 profile `options` 上（与 miniswe 的 `options.step_limit` 同一处）。省略等于 `3600`。`0` 关掉 stall，第一次失败立刻返回，进度上不出现 `upstream_stall`。负数或非整数拒绝。重试间隔固定 60 秒，不是字段。

stall 期间当前相位的时钟不走。run 冻住 `limits.wall_time_seconds`，evaluate 里的 judge invoke 冻住 `limits.evaluate_seconds`。task worker 和 eval worker 的等待按同一段时间延长。只把 `deadline_monotonic` 往后推不够：这两处若在入口把剩余秒数抓住一次，原到期仍会杀掉 worker。环境启动不 stall。

睡眠之后用同一份 prompt、tools、messages 再调 `executor.invoke`，直到 `ok` 或 stall 预算用尽。成功后，实时进度回到该相位的名字（`run` 或 `evaluate`）。

executor 运行之前的拒绝立刻返回，不进入 stall，也不显示 `upstream_stall`：wall 已经到期、invoke 额度已经用完、redaction 失败、offline forced。

`repeatable: false` 不再调 `executor.invoke`。打一条 `upstream_stall`，outcome 为 `not_repeatable`，不在预算里空等。

三种 executor 的一次 invoke 大小不同：

- `openai-http` 与 `anthropic-http`：一次 invoke 是一次请求。任何非 ok 都可重试。状态码留在结果上，给证据事实用，不决定等不等。
- ACP：仅当这条 prompt 还没有改过 workspace 时，在同一 session 上重发。已经改过则 `repeatable: false`。
- miniswe：一次 invoke 是整段 agent。stall 包住进程内当前这一次模型查询。消息留在进程里，恢复后重发这一次查询，不新开 agent。这个集成关掉 mini-swe-agent 自己的 10 次、4–60 秒 tenacity，两段等待不叠。预算属于这一次 parent invoke。内层把预算用完时带 `stall_exhausted`，外层不再开一轮。

预算用尽：invoke 按失败 invoke 返回，Attempt 照今天的失败收场，cleanup 照跑。不给半成品 workspace 打分。最终 CLI 行仍是 PASS / FAIL / ERROR。

证据记一条 `upstream_stall` 事实：executor 的 reason 字符串、`started_at`、try count、outcome（`resumed`、`budget_exhausted` 或 `not_repeatable`）。它不是 `result.json` 的 status，也不是 PASS。

CLI 复用现有相位槽，不另做进度渲染。suite 的 `unit_phase` 与单题 `AttemptSpinner.phase` 在 stall 期间显示 `upstream_stall`。stderr 不是 TTY 时，stall 开始一行、每次等待一行、结束一行。行上有 task id、state `upstream_stall`、距下次尝试的秒数、剩余预算。没有新的 `--json` 事件流。

启动 probe、`--probe`、`after_environment_ready` 不因这段等待改动。响应正文里的 `token-limit` 不单列成一种原因。

run 相位强制一只 limit 时记一条 `limit_reached` 事实 `{"name": "<limits 键>"}`，先到的那条为准：

- task worker 在 run 时钟上被杀掉 → `wall_time_seconds`
- Agent Service 在 run 时钟之后拒绝 invoke 或 session → `wall_time_seconds`
- Agent Service 因额度拒绝 invoke → `agent_invocations`

此后 run 不以 `phase_failed` 结束。worker 被杀，或 `run.py` 随后抛出的异常，留在 `task_run` 事实里。writer 封口，产物 harvest，evaluate 照常跑。裁决是 evaluator 的：通常 FAIL，收获的工作过了也可以 PASS。

`result.json` 顶层 `limit` 是触到的 limits 键，没有则为 `null`。suite 的 task 行和 attempt 行在 `status`、`score` 旁带同一个 `limit`。

`evaluator.py` 的 `status` 只许 `PASS` 或 `FAIL`。其他值（含 `ERROR`）让 evaluate 相位失败一次，token `evaluator_invalid_status`，Attempt 为 ERROR，phase `evaluate`。打不了分就抛出。缺 verdict 仍是 ERROR。

`bind_result` 只有两个来源：evaluator 的 PASS / FAIL，以及 `phase_failed` 的 ERROR。引擎不写 `metrics.reason`、`metrics.timeout_phase`、`metrics.error`。`metrics` 是 evaluator 的。executor / host 的超时字符串不进入裁决。没有 `limit_reached` 时，`run.py` 或 `evaluator.py` 抛出的异常是 ERROR，与文本无关。

ERROR 的 `result.json` `error` 是一个对象。PASS / FAIL 时 `error` 为 `null`，包括已经写下 `limit` 的那次。`error.title` 标注这次 ERROR，不是裁决。Viewer 和 Hub 直接渲染 `error` 与 `limit`。

| 字段 | 含义 |
| --- | --- |
| `phase` | `run_attempt` 记下的失败相位：`environment`、`run`、`evaluate`、`record`。相位开始前的失败（lock、preflight）为 `null` |
| `title` | 两边页面显示、并用来筛选的标签 |
| `message` | 写在 title 旁边的说明 |

`title` 按这个顺序取：

- `run.py` 或 `evaluator.py` 抛出的 `ScriptError`：构造时的 `title`。`message` 是构造时的 `message`。同一个类，相位由抓住异常的 worker 决定。
- 脚本里逃出的其他异常：类名（`ValueError`），`message` 为 `str(exc)`。任务组里的 `ScriptError` 以 `ExceptionGroup` 到达 worker，worker 不拆开，title 为 `ExceptionGroup`。
- 引擎 ERROR：已经产出的稳定 token。worker envelope 的 `error`（`task_worker_no_result`、`task_worker_unreadable_result`），`EnvironmentFailure.kind`（`environment_setup_failed`），`environment_timeout`、`evaluate_timeout`、`evaluator_invalid_status`，以及 `ConfigError`。没有这种 token 时用异常类名。`message` 是已记下的文字：envelope 的 `message`，否则有界的 stderr 尾部。

traceback 留在 worker envelope 上，记在 `task_run` 事实里，不进 `result.json` 的 `error`。

suite 的 task 行和 attempt 行在 status 为 ERROR 时带同一个对象；`task_refs[]` 带 `run_id` 指向的那次 attempt 的 `error` 和 `limit`。`suite_cancelled` 仍是字符串。字符串 `error`，或没有 `title` 的对象，页面按原文显示。

`RunTerminal.failed` 和 evaluator 返回的 FAIL 不产生这个对象。Cleanup 失败和 `record_warning` 仍是 warning，不改已 bind 的分。

完整失败归属表：[ARCHITECTURE.md](../../ARCHITECTURE.md) § Failure and Privacy Boundary。

| 退出码 | 含义 |
| --- | --- |
| 0 | PASS；或 `--probe` ready |
| 1 | FAIL；或 probe 不可跑 |
| 2 | ERROR / 配置 / 运行时 |

| 失败类 | 表现 | 归属 |
| --- | --- | --- |
| 未知 format | `invalid_format` `/format` | Config |
| 缺 cap / inject | lock 失败 | Config / plugins |
| 缺钥 | preflight 一次失败，`started: false` | 环境 / executor |
| 评测低分 | FAIL + score | Evaluation |
| run 相位 limit（wall、invoke 额度） | evaluator 的 PASS / FAIL；`result.json` 的 `limit` 为该键 | Attempt |
| environment 时钟到期 | ERROR，`error.phase` 为 `environment`，`error.title` 为 `environment_timeout` | Attempt |
| evaluate 时钟到期 | ERROR，`error.phase` 为 `evaluate`，`error.title` 为 `evaluate_timeout` | Attempt |
| evaluator 的 status 不是 PASS / FAIL | ERROR，`error.phase` 为 `evaluate`，`error.title` 为 `evaluator_invalid_status` | Evaluation |
| Evaluator 崩、缺 verdict | ERROR，`error.phase` 为 `evaluate`，`error.title` 为类名或 `ScriptError.title` | Evaluation |
| Cleanup 失败 | warning | 不改已 bind 的分 |

相位失败记在该 phase。未知键：拒绝，一条消息。不要把 skip 写成通过。
