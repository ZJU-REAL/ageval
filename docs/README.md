# ageval 文档（设计权威）

## 权威角色

本目录是 **ageval** 产品与机制设计的权威来源（**自包含**）。实现、Issues、代码与读者向文档均应对齐这里；冲突时**先改 `docs/`**，再同步下游。

不要去仓外 BRIEF、Obsidian vault 找第二套产品形状。那些材料若存在，只是历史施工 brief；产品模型已写进本目录。

交付单位叫 **dataset**，不是 SQL。口语「题包」只留在 internal。术语约束见 [glossary.md](glossary.md)。

| 问题 | 归属 |
| --- | --- |
| 产品是什么、成功标准、非目标、用户故事 | [PRD.md](PRD.md)、[design/00](design/00-overview-and-product.md) |
| 机制如何设计、边界如何切 | [`design/`](design/) |
| 术语与 public 用词 | [glossary.md](glossary.md)（约束：规范名 + Avoid + 表面）。抄进 website / README 只许 public 行；独占槽、kind、Attempt、suite 不当普通中文 |
| 当前/目标代码结构 | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Agent 交付路由、红线、校验 | [../AGENTS.md](../AGENTS.md) |
| 增量交付与验收跟踪 | GitHub Issues |
| 读者向「怎么用」 | [../website/](../website/)（**非**设计权威） |

`docs/reference/` 是归档长文，**不是**日常权威，也不是 vault 入口。

## 设计文档目录

读序见 [design/README.md](design/README.md)。

| 文档 | 内容 |
| --- | --- |
| [design/00-overview-and-product.md](design/00-overview-and-product.md) | 产品、更名、dataset、目标/非目标、US1–US12、命名、红线 |
| [design/01-ageval-core.md](design/01-ageval-core.md) | Core：lock、Attempt 五个阶段、phase/slot、环境 Protocol |
| [design/02-task-package-and-config.md](design/02-task-package-and-config.md) | dataset / task / profiles；缺省有文件就认 |
| [design/03-task-run-and-sdk.md](design/03-task-run-and-sdk.md) | dataset `run.py` 与 `ageval_sdk` |
| [design/05-runtime/](design/05-runtime/) | 环境 kind、ACP、evaluate、evidence、campaign |
| [design/06-capability-adapter-visibility.md](design/06-capability-adapter-visibility.md) | 能力、可见性、gold |
| [design/07-budget-evaluation-failure.md](design/07-budget-evaluation-failure.md) | limits、失败语义 |
| [design/08-conversion-security-testing.md](design/08-conversion-security-testing.md) | 转换、安全、测试 |
| [design/09-owner-matrix-and-structure.md](design/09-owner-matrix-and-structure.md) | Owner 矩阵、目标树、§4.10 结构规范 |
| [design/10-examples-database-52.md](design/10-examples-database-52.md) | 点名示例（非进度） |
| [design/11-extension-plugins.md](design/11-extension-plugins.md) | 独占槽 / 链槽、export / inject、`evaluation_runtime` / `trajectory_seal`、`ageval.plugin/1` |
| [design/12-hub-dataset-and-leaderboard.md](design/12-hub-dataset-and-leaderboard.md) | Hub / Registry |
| [design/13-web-ui-tokens.md](design/13-web-ui-tokens.md) | Web UI 令牌 |
| [design/14-agent-hub.md](design/14-agent-hub.md) | `ageval.agent/1` |
| [design/16-model.md](design/16-model.md) | `ModelSpec`、嵌套 `model:`、环境与 executor 基类 |

文件名前缀只表示读序。

## 同步规则

1. 改设计只改 `docs/design/`（及必要时 PRD/glossary），再改 Architecture、Issues、代码、website、skills。
2. website **提炼**，禁止整页镜像 design。
3. 对外文档不得出现 GitHub Issue 编号。
4. 新机制必须先有 design 段落，再编码。
