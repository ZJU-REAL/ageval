# design/ — 机制设计索引

本目录维护 ageval 的**核心机制与架构约束**（自包含）。
源码目录结构、模块依赖方向、生命周期状态机与数据流见 **[ARCHITECTURE.md](../../ARCHITECTURE.md)**；开发与校验规范见 **[AGENTS.md](../../AGENTS.md)**。

```text
PRD + 00     产品定位、用户故事与架构红线
01–03        Core 阶段生命周期、dataset 配置、run.py 与 SDK
05-runtime   执行环境、ACP、独立评分、证据归档、只读分析器、suite 与 campaign
06–09        能力标记與参考材料隔离、limits 与失败语义、Benchmark 转换、模块职责矩阵
11–16        插件系统、Hub 与排行榜、Web UI 令牌、Agent 包、托管评测、ModelSpec
```

| 文档 | 内容 |
| --- | --- |
| [00-overview-and-product.md](00-overview-and-product.md) | 产品定位、US1–US12、命名约定与架构红线 |
| [01-ageval-core.md](01-ageval-core.md) | 配置锁定（lock）、Attempt 固定阶段与 `EnvironmentProvider` 协议 |
| [02-task-package-and-config.md](02-task-package-and-config.md) | `ageval.yaml`、`task.yaml` 与 `profiles.yaml` 规范 |
| [03-task-run-and-sdk.md](03-task-run-and-sdk.md) | 任务脚本 `run.py` 与 `ageval_sdk` 接口 |
| [05-runtime/](05-runtime/) | 运行时执行链各子模块说明 |
| [05-runtime-core.md](05-runtime-core.md) | 指向 `05-runtime/` 的跳转索引 |
| [06-capability-adapter-visibility.md](06-capability-adapter-visibility.md) | 环境能力标记与参考材料（gold）隔离 |
| [07-budget-evaluation-failure.md](07-budget-evaluation-failure.md) | `limits` 资源上限、上游重试等待（stall）与失败分类 |
| [08-conversion-security-testing.md](08-conversion-security-testing.md) | Benchmark 转换、凭据安全与测试准则 |
| [09-owner-matrix-and-structure.md](09-owner-matrix-and-structure.md) | 模块职责矩阵、目标源码树与结构约束 |
| [10-examples-database-52.md](10-examples-database-52.md) | 仓库内置示例说明 |
| [11-extension-plugins.md](11-extension-plugins.md) | 独占槽与链槽、服务导出与依赖注入（export / inject） |
| [12-hub-dataset-and-leaderboard.md](12-hub-dataset-and-leaderboard.md) | Hub、Registry 与 Leaderboard 机制 |
| [13-web-ui-tokens.md](13-web-ui-tokens.md) | Web UI 视觉设计令牌与跨端一致性规范 |
| [14-agent-hub.md](14-agent-hub.md) | `ageval.agent/1` Agent 包与模型目录 |
| [15-hosted-jobs.md](15-hosted-jobs.md) | Hub 提交、后台 worker 在 E2B / Daytona 上执行的托管评测 |
| [16-model.md](16-model.md) | `ModelSpec` / `resolve_model`、`BaseEnvironment` / `BaseExecutor` |

`05-runtime/` 推荐阅读顺序：`lifecycle` → `environment` → `agent-service` → `evaluation` → `evidence` → `analysis` → `campaign-suite`。
