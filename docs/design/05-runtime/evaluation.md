# Evaluation

在进入 `evaluate` 阶段前，Core 先封存 solver 会话，再将产物快照与参考材料（`gold`）上传至**评分环境**。`evaluator.py` 作为宿主父进程的受限子进程运行（与 `run.py` 相同，控制面通过进程边界调用而不直接导入任务模块）。

评分环境默认复用 `run` 阶段的环境；当 `profiles.yaml` 配置 `evaluate_host.isolated: true` 时，Core 在 `evaluate` 阶段启动独立的 `EnvironmentProvider` 容器实例（若任务声明了 `evaluation.environments`，则按名称懒启动多个独立评分容器）。

代码实现位于 `src/ageval/evaluation/package_evaluator.py`、`src/ageval/runtime/eval_worker.py`、`src/ageval/evaluation/bind.py`、`src/ageval/attempt/phases/evaluate.py` 与 `src/ageval/attempt/artifact_harvest.py`。

```text
run 结束 → seal_run 封存 solver 会话（run 阶段打开的会话禁止继续调用）
         → Agent Service 保持开启至 evaluate 阶段结束
         → harvest 收集产物快照：将声明的单文件或按 exclude 过滤的目录树保存至 evidence/task-artifacts/
evaluate
  before_evaluate
  evaluation.collect          # 可选：按顺序在 attempt 容器与 compose 服务中执行收集命令并拷贝路径至 evidence/verifier-collect/
  [isolated, 无命名表] 启动独立评分容器（使用任务 evaluate 配方与独立工作区）
  [无命名表] 上传产物快照、verifier-collect 文件与 evaluation/ 参考材料至评分环境
  [isolated, 无命名表] 对 evaluate 阶段新增的 ACP 角色执行 after_environment_ready
  evaluation_runtime.evaluate # 独占槽实现；默认在父进程子进程中运行 evaluator.py
                              # 命名评分容器：首次调用 scoring.exec 或 session(environment=) 时懒启动并上传快照与参考材料
                              # 可选：evaluator.py 调用 Agent.session(<judge>).invoke
  bind_evaluation             # Result.status 唯一写入点
  after_evaluate              # 可补充 metrics，不得修改 status
cleanup (finally)
  停止所有已启动的独立评分容器与 run 环境
```

`PASS` 与 `FAIL` 仅能通过 `bind_evaluation` 写入 `Result`。`RunTerminal.completed`、轨迹文件存在、ACP 正常结束、`judge` 文本输出、或单条 `checks` 的退出码均不直接决定 `Result.status`。

## 可选评分策略一：Agent-as-judge / LLM-as-judge

在同一份 `profiles.yaml` 的 `agent_profiles` 中声明独立的评分角色（如 `judge`），并在 `task.yaml` 的 `agent_profiles` 中列出该角色 ID。在参考材料上传完成后，`evaluator.py` 可调用 `Agent.session("judge").invoke(...)` 进行单步或多步验证：

- `judge` 与 `solver` 可绑定不同的 `executor` 实现（例如 `solver` 使用 `acp`，`judge` 使用 `openai-http` 或带工具能力的 `acp`）。
- 在 `evaluate_host.isolated: true` 下，ACP `attach_stdio` 连接至独立评分容器（若配置了 `evaluation.environments` 命名表，ACP 角色必须显式传入 `session(..., environment=<name>)`）。
- `judge` 调用串行准入，不消耗 `limits.agent_invocations` 与 `limits.agent_concurrency`，整体受 `limits.evaluate_seconds` 时钟约束。
- `evaluate` 阶段的调用轨迹单独写入 `evaluation/observation.jsonl`（自动省略 `user` 提示行以防参考材料进入归档证据），不混入根 `trajectory.jsonl`。
- `evaluator.py` 最终返回 `{status, score, metrics}`，`status` 仅允许 `PASS` 或 `FAIL`（返回其他值会触发 `evaluator_invalid_status` 并记为 `ERROR`）。

## 可选评分策略二：分步检查项（`checks`）

`evaluator.py` 返回的字典可附带可选的 `checks` 列表。`bind_evaluation` 仅读取顶层 `status`、`score` 与 `metrics`；父进程在校验 `checks` 格式后将其写入 `evaluation/checks.json`（`ageval.evaluation.checks/1`），供 Viewer 与 Hub 展示分步检查明细：

```json
{
  "schema": "ageval.evaluation.checks/1",
  "checks": [
    {
      "id": "audit",
      "title": "schema audit",
      "status": "PASS",
      "score": 1.0,
      "script": "evaluation/audit.py",
      "environment": "audit",
      "exit_code": 0,
      "stdout": "…",
      "stderr": ""
    }
  ]
}
```

- 每条检查项的 `status` 与 `score` 仅作分步观测展示，不覆盖顶层 `Result` 裁决。
- `script` 为 dataset 内部相对路径，Viewer 与 Hub 直接从数据包读取脚本内容，不将参考材料或检查脚本拷贝进 Attempt 归档。

## 参考材料（Gold）的阶段边界隔离与容器隔离

```text
environment / run     待测 Agent 环境中不存在 /attempt/evaluation
evaluate 开始         向评分环境上传 evaluation/ → 启动 evaluator.py
```

- **默认阶段边界隔离：** 在 `environment` 与 `run` 阶段绝不挂载或上传 `evaluation/`；仅在 solver 封存后才上传至评分环境。
- **独立评分容器隔离（`evaluate_host.isolated: true`）：** 参考材料与产物快照仅上传至独立启动的评分容器，待测 Agent 环境在整个生命周期内完全不接触 `evaluation/`。

## 产物快照收集（`file` 与 `tree`）与路径收集（`evaluation.collect`）

### `artifacts.publishable`

`run` 阶段结束、solver 封存后，Core 按 `artifacts.publishable` 执行一次产物快照收集并存入 `evidence/task-artifacts/`：
- `kind: file`（默认）：收集声明的单个文件；
- `kind: tree`：按可选 `exclude` 过滤规则（如 `target`、`*.so`、`.git`）将工作区目录保存为不可变快照（保留符号链接节点本身而不跟随宿主机路径）。若 `evaluation.inputs[].target` 设为 `workspace`，则在 `evaluate` 阶段将该快照恢复至评分环境的 `/attempt/workspace`。

### `evaluation.collect`

`evaluation.collect` 是在 `before_evaluate` 之后、上传参考材料之前执行的引擎步骤，用于从 attempt 容器或 compose 辅助服务中导出绝对路径文件：

| 字段 | 规则 |
| --- | --- |
| `path` | 容器内绝对路径（不含 `..`）；在评分环境中放回相同绝对路径 |
| `service` | 省略或 `main` 表示 attempt 容器；其余名称表示 compose 服务名 |
| `command` | 可选，在目标容器中通过 `sh -c` 执行以生成待收集文件 |
| `timeout_sec` | 可选正数（默认 `60` 秒），约束 `command` 执行时间 |
| `exclude` | 可选，针对目录路径按名称或 glob 过滤 |

执行顺序固定为：1）attempt 容器上的全部 `command`；2）attempt 容器上的全部 `path`；3）辅助服务上的全部 `command`；4）辅助服务上的全部 `path`。若命令返回非零退出码或路径缺失，`evaluate` 阶段直接记为 `ERROR`（`environment_collect_failed` / `environment_collect_missing`）。收集到的文件存入 `evidence/verifier-collect/`（命令原文在归档证据中脱敏省略）。

执行 `ageval results regrade` 时，系统直接复用来源 Attempt 归档的 `task-artifacts/` 与 `verifier-collect/` 快照，不重新运行 `run.py` 或 `collect` 命令。

## 多命名评分容器（`evaluation.environments`）

当不同评分步骤需要各自独立的容器镜像环境时，可在 `task.yaml` 中声明 `evaluation.environments`：

```yaml
# task.yaml
evaluation:
  environments:
    audit:
      dockerfile: environment/evaluate/audit/Dockerfile
    behavioural:
      dockerfile: environment/evaluate/behavioural/Dockerfile
    verification:
      dockerfile: environment/evaluate/verification/Dockerfile
```

```text
evaluator.py (parent subprocess)
  scoring.exec("audit", argv)     → 首次调用时启动 audit 容器、上传快照与参考材料并执行命令
  scoring.exec("behavioural", …)  → 启动独立 behavioural 容器并上传同一份快照拷贝
  agent.session("judge", environment="verification")
                                  → ACP attach_stdio 连接至 verification 容器
cleanup                           → 停止所有已启动的评分容器与待测 Agent 环境
```

声明 `evaluation.environments` 时，运行配置必须启用 `evaluate_host.isolated: true` 且 `environment: docker`。各命名容器采用按需懒启动策略，未被调用的容器不会构建或启动。
