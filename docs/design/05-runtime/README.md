# 05 — 运行时执行链

本目录规定 ageval 运行时各核心子模块的机制设计：**执行环境、ACP 与 Agent Service、独立评分、执行证据、只读分析器以及 Suite / Campaign 调度**。模块结构总图见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)，用户故事 US1–US12 见 [00](../00-overview-and-product.md)。

| 文件 | 内容 |
| --- | --- |
| [lifecycle.md](lifecycle.md) | Run / Trial / Attempt 身份与固定阶段状态机 |
| [environment.md](environment.md) | `EnvironmentProvider` 协议、五种环境实现与容器资源参数 |
| [agent-service.md](agent-service.md) | 父进程 Agent Service、ACP `attach_stdio`、按角色绑定 executor 与并发会话调度 |
| [evaluation.md](evaluation.md) | 封存 solver、延迟上传参考材料、可选 Agent-as-judge 与 `checks`、绑定 `PASS` |
| [evidence.md](evidence.md) | `.ageval/runs/` 证据目录、`trajectory.jsonl`、`evaluation/observation.jsonl` 与 `checks.json` |
| [analysis.md](analysis.md) | 运行结束后的只读分析器（`stats` / `hack` / `review`） |
| [campaign-suite.md](campaign-suite.md) | Suite 全量运行、断点续跑、重评（`regrade`）与 Campaign 参数矩阵 |

## 阶段与插件槽调度总图（对应 `slots.py`）

```text
environment
  before_environment
  host.start
  upload data/
  after_environment_ready
  environment_setup
  after_environment

run
  before_run
  task_worker → run.py
    before/after_agent_open
    before_agent_invoke → 该角色 profile 绑定的 executor.invoke → after_agent_invoke
    normalize_agent_result
    before/after_agent_close
  seal_run（封存 solver 会话；Agent Service 保持开启供 evaluate 阶段使用）
  after_run

evaluate
  before_evaluate
  evaluation.collect          # 可选路径收集（引擎内置步骤）
  upload evaluation/          # 上传参考材料（引擎内置步骤）
  evaluation_runtime          # 独占槽；默认在父进程子进程中运行 evaluator.py
                              # 可选调用 Agent.session(<judge>).invoke
  bind_evaluation             # PASS / FAIL 唯一写入入口
  after_evaluate              # 可补充 metrics，不得修改 status

record
  trajectory_collect → trajectory_enrich
  trajectory_seal             # 独占槽；写出 run 阶段 trajectory.jsonl
                              # 若 evaluate 阶段存在 SDK 调用，另写 evaluation/observation.jsonl（省略 user 提示行）
  summary_enrich              # 写入 Attempt summary.extra（为空则省略）

cleanup (finally)
  cleanup_report
  stop 已启动的独立评分容器与运行环境
```

插件槽仅分为独占槽（`environment`、`executor`、`evaluation_runtime`、`trajectory_seal`）与链槽两类。其中 `executor` 按角色 profile 独立绑定，`environment` 按单次 Attempt 全局绑定，`PASS` 仅能通过 `bind_evaluation` 写入。
