# Campaign 与 Suite

| | 命令 | 含义 |
| --- | --- | --- |
| 单 Attempt | `ageval run <dataset> --task <id>` | 一题一次 |
| Suite | `ageval run <dataset>`（无 `--task`） | 全成员 |
| Always-k | `ageval run … -k N` | 每题 N 次；CLI/job only，不是 yaml 字段 |
| Campaign | `ageval campaign <dataset> --task a --task b --matrix …` | 参数格点；一格失败其它格仍在 |

退出码：全 PASS = 0，否则 1。禁止 dry-run 冒充完成。

```text
suite job
  .ageval/suite-runs/<id>/
    summary.json    metrics.pass_rate / pass_at_k（观测）
    progress.json
    task_refs[]     run_id / attempt_run_ids
```

`summary.json` 在 suite 进行中就存在，是 **观测快照**：只统计已 settle 的 attempt，
`status` 为 `running` / `cancelling`，`metrics.pass_rate` =
`n_pass / (n_pass + n_fail + n_error)`（分母是已 settle 的任务，不是计划任务数）；
`tasks[]` / `attempts[]` / `task_refs[]` 只列已 settle 的工作，未跑的 task id 不出现。
它不是 suite PASS。suite 完成 / 取消时同一文件被按全计划 id 集重写为终值；
`created_at` 在首次写入时锁定，resume 重写不改写它。`progress.json` 仍是
slot / cancel 文档（计划数、in-flight、取消请求），两文件各管各的。

Viewer Jobs 对进行中的 suite 显示 **一行**（suite_run_id 唯一），pass rate 取自该
快照，Trials 显示 `settled / planned`；已 settle 的 run id 归属该 suite 行，
不再以单题 job 重复出现。`ageval results upload-suite` 拒绝 `running` /
`cancelling` 的快照——观测快照不是完备 suite，完备性门禁不变。

Hub Leaderboard 吃的是 **suite** 上传（`ageval results upload-suite`），不是单 Attempt `results upload`。公开榜还要完备且绑定 release。draft / 不完备只上 Jobs。

`--agent` 与 `--profiles` 互斥。`--model` 须配合 `--agent`（`lock` / `run` / `campaign` / `results regrade`）。Campaign 不与 `run.py` 内 scheduler 合并。

## Resume、换格、重评分

Suite 可以沿用同一个 `suite_run_id`。Attempt 目录不改写。

- **`--resume-suite`**：跳过已完成格（默认含 PASS / FAIL / ERROR），追加还没有的 index，重算 pass@k / pass^k。取消占位会再跑。`created_at` 保持首次写入。
- **`--retry-errors`**：必须和 `--resume-suite` 一起用。本次过滤里的 ERROR 格再跑，不必写 `--replace-slot`。PASS / FAIL 仍跳过。新 Attempt；旧行进 `previous[]`；指标只看现行指针。
- **`--replace-slot`**：点名换一格已完成的 PASS / FAIL / ERROR。仍要求 `--resume-suite` 与 `--task`。可以和 `--retry-errors` 同用。fingerprint 不一致时这一格拒绝换。
- resume 的 `progress.json` / 结束摘要带 `skipped` 与 `retried` 计数（跳过的已完成格、这次重跑的 ERROR 格）。

**`ageval results regrade <dataset> --run <attempt_id>`**（`--run` 可重复）是另一条入口，不进 suite 调度：

- 铸造新 Attempt。来源 `result.json` 与来源目录不改。
- 不跑 agent / `run.py`。把来源 `task-artifacts/` 与 `verifier-collect/` 拷进打分 Host，只 evaluate。不重跑 collect command。
- gold 与 evaluator 读**当前 dataset**，不读来源 Attempt 里冻住的那份脚本。
- harvest 缺失或对不上当前 `artifacts.publishable` → 新 Attempt 为 ERROR，不从轨迹编 PASS / FAIL。
- 没有题包字段声明「这题能否 regrade」。

`task-artifacts/` 在 `slim_sealed_attempt` 之后默认仍在。`--keep-workspace` 只影响活的 work root。

不做：把一次进行中的 agent 对话接着跑；session resume token；原地覆盖 Attempt。
