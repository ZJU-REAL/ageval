# Campaign 与 Suite

| 运行模式 | 命令 | 含义 |
| --- | --- | --- |
| 单次 Attempt | `ageval run <dataset> --task <id>` | 单题单次运行 |
| Suite | `ageval run <dataset>`（省略 `--task`） | 运行 dataset 下的全部任务成员 |
| Always-k | `ageval run … -k N` | 每道任务独立运行 N 次（仅作为 CLI / 运行期参数，不写入 `task.yaml`） |
| Campaign | `ageval campaign <dataset> --task a --task b --matrix …` | 在指定任务上按参数网格展开运行 |

退出码约定：全部任务 `PASS` 时返回 `0`；存在 `FAIL` 时返回 `1`；发生 `ERROR` 或配置错误时返回 `2`。

```text
suite job
  .ageval/suite-runs/<id>/
    summary.json    metrics.pass_rate / pass_at_k（汇总观测指标）
    progress.json   计划槽位、在途任务与取消状态
    task_refs[]     各任务的 run_id / attempt_run_ids 引用
```

- 在 suite 运行期间，`summary.json` 实时维护已完成（settled）Attempt 的观测快照（`status` 为 `running` 或 `cancelling`，`metrics.pass_rate` 按已完成任务数计算）；待全部任务完成或取消后重写为最终汇总文档。
- 本地 Viewer 的 Jobs 列表将正在运行的 suite 展示为单行（显示 `settled / planned` 进度）；`ageval results upload-suite` 仅接受已进入终态且完备的 suite。
- Hub 公开 Leaderboard 仅收录完备、绑定正式 release 且经组织 owner 批准上榜（`board_listed`）的 suite 结果。

## 断点续跑、单格替换与重新评分

Suite 续跑沿用同一个 `suite_run_id`，且绝不原地改写已生成的 Attempt 目录：

- **`--resume-suite`**：跳过已完成的任务槽位（默认包含 `PASS`、`FAIL` 与 `ERROR`），仅补充尚未运行的槽位或此前因取消而未实际执行的占位项，并重新计算 `pass@k` / `pass^k`。
- **`--retry-errors`**：配合 `--resume-suite` 使用，将当前筛选范围内状态为 `ERROR` 的槽位重新运行（每次生成新 Attempt，旧记录移入 `previous[]`）。
- **`--replace-slot`**：配合 `--resume-suite --task`（及可选 `--attempt-index`）重新运行指定槽位，生成新 Attempt 并将旧记录移入 `previous[]`。

**`ageval results regrade <dataset> --run <attempt_id>`**（`--run` 可重复指定）用于在不重跑模型的情况下重新评分：
- 签发新的 Attempt，保持来源 Attempt 目录与 `result.json` 不变；
- 跳过 `run` 阶段（不运行 `run.py` 与 `evaluation.collect` 命令），将来源 Attempt 的 `task-artifacts/` 与 `verifier-collect/` 快照复制到评分环境中，并使用当前 dataset 的 `evaluation/` 与 `evaluator.py` 执行 `evaluate` 阶段；
- 若来源 Attempt 缺少声明的产物快照，则新 Attempt 记为 `ERROR`（`regrade_harvest_missing`）。
