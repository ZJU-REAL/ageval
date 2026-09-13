# 05 — 执行链

Runtime 在这里指：**环境、ACP、evaluate、evidence、campaign**。结构总图见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)。产品故事 US1–US12 见 [00](../00-overview-and-product.md)。

| 文件 | 内容 |
| --- | --- |
| [lifecycle.md](lifecycle.md) | Run / Trial / Attempt 身份与五个阶段状态机 |
| [environment.md](environment.md) | Protocol 与四 kind |
| [agent-service.md](agent-service.md) | parent ACP client + `attach_stdio`；executor 按 profile 绑；openai-http / anthropic-http 原生 `tools=` |
| [evaluation.md](evaluation.md) | 停 solver writer、upload gold、可选 judge SDK invoke、可选 `checks`、绑定 PASS |
| [evidence.md](evidence.md) | `.ageval/runs/`；`evaluation/observation.jsonl`；`evaluation/checks.json` |
| [campaign-suite.md](campaign-suite.md) | campaign 与 suite |

Core 保留：身份、deadline、limits、cleanup、PASS 入口。题包保留 loop。插件填槽。

## emit 总图（与 slots.py 对齐）

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
    before_agent_invoke → 该 profile 的 executor.invoke → after_agent_invoke
    normalize_agent_result
    before/after_agent_close
  停 solver writer；Agent Service 保持到 evaluate 结束
  after_run

evaluate
  before_evaluate
  upload evaluation/          # 引擎代码；不是 before_evaluate 链槽
  evaluation_runtime          # 独占槽；默认 parent 子进程 evaluator.py
                              # 可选 Agent.session(<judge>).invoke（同一 Parent Agent Service）
  bind_evaluation             # PASS 只从这里进
  after_evaluate              # 不得改 status

record
  trajectory_collect → enrich
  trajectory_seal             # 独占槽；run 相位 → trajectory.jsonl
                              # evaluate 相位 → evaluation/observation.jsonl（有才写；省略 user）
  summary_enrich              # 失败不挡后续；Attempt summary.extra，空则省略

cleanup (finally)
  cleanup_report
  host.stop
```

槽种类只有 exclusive（`environment`、`executor`、`evaluation_runtime`、`trajectory_seal`）与 chain。`executor` 按 profile 各绑一份；`environment` 仍 Attempt 级一份。PASS 仍只经 `bind_evaluation`。
