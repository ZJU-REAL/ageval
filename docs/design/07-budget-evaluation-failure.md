# 07 — limits 与失败

`limits` 由 Runtime 在效果前强制。dataset 软限（max_turns）不能替代 `limits`。事后 token/cost 只作观测。`record` 与 `cleanup` 不计预算。

三个相位各有一只时钟，从该相位入口起算。已有超时的步骤读当前相位剩余时间。`host.start` 本身不加超时。

| 键 | 缺省 | 覆盖 | 到期 |
| --- | --- | --- | --- |
| `limits.wall_time_seconds` | 300 | run：从入口到 task worker 返回 | 记下 `limit_reached`，名字 `wall_time_seconds`。run 结束，evaluate 照常打分 |
| `limits.environment_seconds` | 600 | environment：box start、seed upload、`after_environment_ready`、`environment_setup` | ERROR，phase `environment`，token `environment_timeout`。run 不开始 |
| `limits.evaluate_seconds` | 600 | evaluate：打分 Host 的 start 与 upload、evaluate 相位的 `after_environment_ready`、evaluator worker、`scoring.exec`、evaluate 相位的 invoke | ERROR，phase `evaluate`，token `evaluate_timeout` |

`limits.agent_invocations` 只计 run 相位的 invoke。`seal_run` 之后才打开的 profile（evaluate 的 judge）不占这只额度，由 `evaluate_seconds` 封顶。写出 `0` 时，run 相位每一次 invoke 都被拒绝。

run 相位强制一只 limit 时记一条 `limit_reached` 事实 `{"name": "<limits 键>"}`，先到的那条为准：

- task worker 在 run 时钟上被杀掉 → `wall_time_seconds`
- Agent Service 在 run 时钟之后拒绝 invoke 或 session → `wall_time_seconds`
- Agent Service 因额度拒绝 invoke → `agent_invocations`

此后 run 不以 `phase_failed` 结束。worker 被杀，或 `run.py` 随后抛出的异常，留在 `task_run` 事实里。writer 封口，产物 harvest，evaluate 照常跑。裁决是 evaluator 的：通常 FAIL，收获的工作过了也可以 PASS。

`result.json` 顶层 `limit` 是触到的 limits 键，没有则为 `null`。suite 的 task 行和 attempt 行在 `status`、`score` 旁带同一个 `limit`。

`evaluator.py` 的 `status` 只许 `PASS` 或 `FAIL`。其他值（含 `ERROR`）让 evaluate 相位失败一次，token `evaluator_invalid_status`，Attempt 为 ERROR，phase `evaluate`。打不了分就抛出。缺 verdict 仍是 ERROR。

`bind_result` 只有两个来源：evaluator 的 PASS / FAIL，以及 `phase_failed` 的 ERROR。引擎不写 `metrics.reason`、`metrics.timeout_phase`、`metrics.error`。`metrics` 是 evaluator 的。executor / host 的超时字符串不进入裁决。没有 `limit_reached` 时，`run.py` 或 `evaluator.py` 抛出的异常是 ERROR，与文本无关。

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
| environment 时钟到期 | ERROR，phase `environment`，`environment_timeout` | Attempt |
| evaluate 时钟到期 | ERROR，phase `evaluate`，`evaluate_timeout` | Attempt |
| evaluator 的 status 不是 PASS / FAIL | ERROR，phase `evaluate`，`evaluator_invalid_status` | Evaluation |
| Evaluator 崩、缺 verdict | `error.phase = evaluate` ERROR | Evaluation |
| Cleanup 失败 | warning | 不改已 bind 的分 |

相位失败记在该 phase。未知键：拒绝，一条消息。不要把 skip 写成通过。
