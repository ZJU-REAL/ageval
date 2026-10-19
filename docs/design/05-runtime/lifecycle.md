# Lifecycle

单次 `ageval run --task` 签发三层身份：`Run → Trial（绑定 lock digest）→ Attempt`。重跑或重评均会创建新的 Attempt，绝不原地覆盖已归档的 Attempt 目录；单次 Attempt 仅调用一次 `IdentityFactory.new_run`。

## 外层状态机

```text
created
  → locking          # load_and_lock
  → preflight        # host.preflight；缺失凭据在此直接终止
  → environment      # start + upload seed + setup
  → run              # run.py + 绑定的 executor
  → evaluate         # 封存 solver + 上传参考材料 + evaluator.py + bind_evaluation
  → record           # 封存轨迹与运行摘要
  → cleanup          # finally，任何退出路径均无条件执行
  → terminal         # PASS | FAIL | ERROR
```

代码实现：`application/run.py` 签发身份与 evidence 目录后调用 `attempt.run_attempt`。若某个阶段发生异常，系统记录首次 `phase_failed` 事实；一旦环境已启动，即使 `run` 或 `evaluate` 发生 `ERROR`，仍会进入 `record` 封存已产生的 `trajectory.jsonl`，并在 `finally` 中执行 `cleanup`。

## 固定阶段职责

1. **environment** — 调用 `host.start`（Docker 在此构建基础镜像与插件 `image_layers`），上传 `data/` 至工作区，依次执行 `after_environment_ready`（ACP 运行时探测；若构建期已写入匹配版本则跳过安装）与 `environment_setup`（运行 `setup.sh`）。
2. **run** — 在受限子进程中运行 `run.py`，角色调用经父进程 socket 分发。结束时调用 `seal_run` 取消排队的 solver 调用并排干在途调用，随后标记 `mark_writers_stopped` 并收集任务声明的产物快照。`ParentAgentService` 保持开启供 `evaluate` 阶段使用。
3. **evaluate** — 在 solver 封存后执行可选的 `evaluation.collect`，上传产物快照与 `evaluation/` 参考材料，运行 `evaluator.py` 并通过 `bind_evaluation` 绑定结果。
4. **record** — 依次触发 `trajectory_collect`、`trajectory_enrich` 与 `trajectory_seal` 写出 `trajectory.jsonl`，并运行 `summary_enrich`。
5. **cleanup** — 在 `try/finally` 中调用 `host.stop`（及停止已启动的独立评分容器）。清理失败仅记录 warning，不覆盖已绑定的评分结果。

## 顺序不变量

1. `load_and_lock` 成功前不得启动环境或发起模型调用。
2. `evaluator.py` 不得与仍可写入的 solver 会话并发访问同一评测输入；`seal_run` 排干 solver 的排队与在途调用并标记 `mark_writers_stopped` 后，才上传参考材料（`gold`）。
3. `cleanup` 在正常结束、超时、用户取消与未捕获异常下均可达。
4. `ageval campaign` 仅在外层展开参数矩阵，不介入 `run.py` 内部控制流。

## 断点续跑、单格替换与重新评分（Regrade）

所有续跑与重评操作均遵循不可变证据原则：已生成的 Attempt 目录与 `result.json` 保持不变，新执行均生成新的 Attempt。

| 操作路径 | 身份归属 | 行为说明 |
| --- | --- | --- |
| Suite 续跑（`--resume-suite`） | 沿用同一 `suite_run_id` | 跳过已完成的任务槽位（默认包含 `PASS`、`FAIL` 与 `ERROR`），仅补跑缺失槽位或此前因取消而未实际执行的占位项。 |
| 重试错误项（`--retry-errors`） | 沿用同一 `suite_run_id` | 配合 `--resume-suite` 使用，将当前筛选范围内状态为 `ERROR` 的已完成槽位重新运行（`PASS` 与 `FAIL` 仍跳过）。每次重跑生成新 Attempt，旧记录移入 `previous[]`。 |
| 替换指定槽位（`--replace-slot`） | 沿用同一 `suite_run_id` | 配合 `--resume-suite --task` 重新运行指定槽位（无论原状态为 `PASS`、`FAIL` 或 `ERROR`），生成新 Attempt 并将旧记录移入 `previous[]`。 |
| 重新评分（`ageval results regrade`） | 生成**新** Attempt | 跳过 `run` 阶段（不运行 `run.py`，也不重新执行 `evaluation.collect` 的命令），直接将来源 Attempt 归档的 `task-artifacts/` 与 `verifier-collect/` 快照复制到新的评分环境中，使用当前 dataset 的 `evaluation/` 与 `evaluator.py` 执行 `evaluate` 阶段。 |

`regrade` 的阶段顺序为：`lock → preflight → host.start（不执行 environment_setup 与 solver）→ evaluate → record → cleanup`。若来源 Attempt 缺少声明的产物快照（未配置 `artifacts.publishable` 或对应文件/目录不在 `task-artifacts/` 中），新 Attempt 直接记为 `ERROR`（`regrade_harvest_missing`），绝不用交互轨迹文本替代产物进行评分。

`slim_sealed_attempt` 默认保留 `task-artifacts/` 与 `verifier-collect/` 快照；`cleanup` 仅清理运行期工作区，不删除归档目录中的这两份快照。
