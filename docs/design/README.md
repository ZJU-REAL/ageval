# design/ — 机制设计索引

本目录是 ageval **机制与红线**的设计权威（自包含）。进度不写在这里。不要读仓外 BRIEF。  
源码树、依赖图、生命周期图、数据流表：**[ARCHITECTURE.md](../../ARCHITECTURE.md)**。施工约束：**[AGENTS.md](../../AGENTS.md)**。

```text
PRD + 00     产品
01–03        Attempt、dataset、run.py、SDK
05-runtime   环境、ACP、evaluate、evidence、campaign
06–09        可见性、limits、转换、owner
11–15        插件、Hub、UI 令牌、Agent 对象、hosted job
ARCHITECTURE.md
Issues / 代码
```

| 文档 | 内容 |
| --- | --- |
| [00-overview-and-product.md](00-overview-and-product.md) | 产品、US1–US12、命名、红线 |
| [01-ageval-core.md](01-ageval-core.md) | lock + 五个阶段 + Protocol |
| [02-task-package-and-config.md](02-task-package-and-config.md) | `ageval.yaml` / `task.yaml` / profiles |
| [03-task-run-and-sdk.md](03-task-run-and-sdk.md) | dataset `run.py` 与 `ageval_sdk` |
| [05-runtime/](05-runtime/) | 执行链 |
| [05-runtime-core.md](05-runtime-core.md) | stub → `05-runtime/` |
| [06-capability-adapter-visibility.md](06-capability-adapter-visibility.md) | 能力与 gold |
| [07-budget-evaluation-failure.md](07-budget-evaluation-failure.md) | limits 与失败 |
| [08-conversion-security-testing.md](08-conversion-security-testing.md) | 转换与安全 |
| [09-owner-matrix-and-structure.md](09-owner-matrix-and-structure.md) | Owner 与目标树 |
| [10-examples-database-52.md](10-examples-database-52.md) | 点名示例 |
| [11-extension-plugins.md](11-extension-plugins.md) | 独占 / 链；export / inject 稳定接口 |
| [12-hub-dataset-and-leaderboard.md](12-hub-dataset-and-leaderboard.md) | Hub |
| [13-web-ui-tokens.md](13-web-ui-tokens.md) | UI 令牌与视觉不变量（跨面宪法；不写页面清单） |
| [14-agent-hub.md](14-agent-hub.md) | `ageval.agent/1` |
| [15-hosted-jobs.md](15-hosted-jobs.md) | Hub 提交 suite；worker 只跑 e2b / daytona |

Runtime 读序：`lifecycle` → `environment`（四 kind、ssh A/B、能力表）→ `agent-service` → `evaluation`（gold 时间切）→ `evidence` → `campaign-suite`。
