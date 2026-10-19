# ageval 文档（设计规范）

## 文档定位

本目录是 **ageval** 产品与机制设计的规范来源（自包含）。实现、Issues、代码与读者向文档均以本目录定义的机制为准。

交付单位为 **dataset**（区分于 SQL 数据库）。术语规范见 [glossary.md](glossary.md)。

| 问题 | 归属文档 |
| --- | --- |
| 产品定位、成功标准、非目标、用户故事 | [PRD.md](PRD.md)、[design/00](design/00-overview-and-product.md) |
| 核心机制与模块边界设计 | [`design/`](design/) |
| 术语与用词规范 | [glossary.md](glossary.md) |
| 当前与目标代码结构 | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Agent 开发规范、边界与 CI 校验 | [../AGENTS.md](../AGENTS.md) |
| 增量交付与验收跟踪 | GitHub Issues |
| 读者向使用指南 | [../website/](../website/) |

`docs/reference/` 为历史归档长文，不作为日常开发规范。

## 设计文档目录

阅读顺序见 [design/README.md](design/README.md)。

| 文档 | 内容 |
| --- | --- |
| [design/00-overview-and-product.md](design/00-overview-and-product.md) | 产品总览、更名、dataset、目标与非目标、US1–US12、命名与架构红线 |
| [design/01-ageval-core.md](design/01-ageval-core.md) | Core：配置锁定（lock）、Attempt 阶段生命周期、插件槽（slot）与环境接口 |
| [design/02-task-package-and-config.md](design/02-task-package-and-config.md) | dataset、`task.yaml` 与 `profiles.yaml` 配置规则及默认文件识别 |
| [design/03-task-run-and-sdk.md](design/03-task-run-and-sdk.md) | 任务脚本 `run.py` 与 `ageval_sdk` 接口 |
| [design/05-runtime/](design/05-runtime/) | 环境插件、ACP、独立评分、执行证据、分析器与并发调度 |
| [design/06-capability-adapter-visibility.md](design/06-capability-adapter-visibility.md) | 环境能力标记、工作区可见性与参考材料（gold）隔离 |
| [design/07-budget-evaluation-failure.md](design/07-budget-evaluation-failure.md) | `limits` 资源上限、上游重试等待（stall）与失败语义 |
| [design/08-conversion-security-testing.md](design/08-conversion-security-testing.md) | Benchmark 转换、凭据安全与测试规范 |
| [design/09-owner-matrix-and-structure.md](design/09-owner-matrix-and-structure.md) | 模块职责矩阵、目标源码树与结构约束 |
| [design/10-examples-database-52.md](design/10-examples-database-52.md) | 仓库内置示例范围 |
| [design/11-extension-plugins.md](design/11-extension-plugins.md) | 独占槽与链槽、服务导出与依赖注入（export / inject）、`ageval.plugin/1` |
| [design/12-hub-dataset-and-leaderboard.md](design/12-hub-dataset-and-leaderboard.md) | Hub、Registry 与 Leaderboard 规则 |
| [design/13-web-ui-tokens.md](design/13-web-ui-tokens.md) | Web UI 视觉设计令牌与组件规范 |
| [design/14-agent-hub.md](design/14-agent-hub.md) | Agent 包（`ageval.agent/1`）与模型目录 |
| [design/15-hosted-jobs.md](design/15-hosted-jobs.md) | 云端托管评测作业（Hosted jobs） |
| [design/16-model.md](design/16-model.md) | `ModelSpec`、嵌套 `model:` 配置、环境与执行器抽象基类 |

文件名前缀仅表示推荐阅读顺序。

## 同步规则

1. **阶段收尾同步：** 涉及产品语义、机制或架构变更时，无需在开发开头单独提交纯文档 commit；在完成阶段性任务或提交 PR 收尾时，完成对应 `docs/design/`（及必要时 `PRD.md` / `glossary.md`）、`ARCHITECTURE.md`、`website/` 与 `skills/` 的同步更新即可。
2. `website/` 面向使用者提炼用法，不整页照搬 `docs/design/`。
3. 对外文档（`README*`、`website/`、示例与插件说明）不得包含 GitHub Issue 编号。
