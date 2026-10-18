# Lifecycle

一次公开 `ageval run --task` 铸造：Run → Trial（lock digest）→ Attempt。重跑是新 Attempt，不改写旧身份。一次 Attempt 只 `new_run` 一次。

## 外层状态

```text
created
  → locking          # load_and_lock
  → preflight        # host.preflight；缺钥在此失败
  → environment      # start + seed + setup
  → run              # run.py + ACP
  → evaluate         # 停写 + gold + bind
  → record
  → cleanup          # finally，任何失败路径都进
  → terminal         # PASS | FAIL | ERROR
```

实现：`application/run.py` 铸造 identity 与 evidence 根，然后 `attempt.run_attempt`。相位失败记 `phase_failed` 事实（只记第一处）；environment 已 start 后，evaluate / run ERROR **仍跑 record**，密封已有 `trajectory.jsonl`。`BaseException`（取消）仍传播；cleanup 总是跑。

## 相位

1. **environment** — `host.start`（docker 在此消化 `image_layers`，含 ACP 绑定 entry），upload `data/`，链 `after_environment_ready`（ACP 探测；bake 已匹配则跳过安装）、`environment_setup`（`setup.sh`，末槽，不是 provision phase）。
2. **run** — 子进程调 `run.py`。Agent invoke 走 parent socket。结束时 `seal_run` 去掉排队的 solver invoke、取消并排干在途的 solver 执行，再 `mark_writers_stopped`。Agent Service 仍留给 evaluate。
3. **evaluate** — 停 writer 之后 upload `evaluation/`，环境内跑 `evaluator.py`，`bind_evaluation`。
4. **record** — collect/enrich → 引擎写 `trajectory.jsonl`。
5. **cleanup** — `try/finally` 里 `host.stop`。失败记 warning，不改已绑定分数。

没有 provision phase。没有 `run_l0.py` / `run_l1_*.py`。

## 顺序不变量

1. 未 lock 成功不得 start / invoke。
2. Evaluator 不得与可写 Agent/`run.py` writer 并发面对同一评测输入。
3. cleanup 必须可从超时/取消/异常进入。
4. Campaign 只调度格点，不与 `run.py` 内 scheduler 合并。
5. `seal_run` 排干 solver 的排队与在途执行之后，才 `mark_writers_stopped`，才 upload gold。

## 续跑、换格、重评分

身份规则同一条：已落地的 Attempt 目录不改写。`result.json` 一旦写下就留在那次 Attempt 上。

| 路径 | 身份 | 做的事 |
| --- | --- | --- |
| Suite resume（`--resume-suite`） | 同一个 `suite_run_id` | 跳过已完成的格，补缺的 index。默认已完成包含 PASS、FAIL、**ERROR**。取消占位（没真正跑过）会再调度。 |
| `--retry-errors` | 仍是同一个 `suite_run_id` | 只加在 resume 上。本次过滤里状态为 ERROR 的已完成格再跑一遍，不必逐个 `--replace-slot`。PASS / FAIL 仍跳过。每一格铸造新 Attempt，旧行进 `previous[]`。 |
| `--replace-slot` | 仍是同一个 `suite_run_id` | 点名换一格（PASS / FAIL / ERROR 都可以）。新 Attempt；旧行进 `previous[]`。与 `--retry-errors` 可以同用。 |
| `ageval results regrade` | **新** Attempt | 不跑 `run` 相位。把来源 Attempt 的 `task-artifacts/` 与 `verifier-collect/` 拷进新的打分 Host，只跑 evaluate。不重跑 `evaluation.collect` 的 command。gold 与 `evaluator.py` 来自**当前 dataset**。来源 `result.json` 保持原样。 |

Regrade 的外层顺序是 lock → preflight → 只 `host.start`（不跑 `environment_setup`、不跑 agent）→ evaluate → record → cleanup。五个相位的名字不变；这条入口省掉 `run`。

Harvest 缺失或不够（没有 `artifacts.publishable`，或声明的 file / tree 不在 `task-artifacts/`）时，新 Attempt 的状态是 ERROR（`regrade_harvest_missing`）。轨迹全文不是裁决，不能拿来凑 PASS / FAIL。没有 `supports_regrade` 这类题包字段：凡是能对上 harvest 的 Attempt 都走同一条 evaluate。

不做的事：中途恢复一次还活着的 agent session；provider session resume token；原地改写 Attempt 目录；用轨迹代替缺失的 harvest；Hub 远程编排。

`slim_sealed_attempt` 默认留下 `task-artifacts/` 和 `verifier-collect/`。cleanup 拆的是活的 box work root，不删这两份快照。
