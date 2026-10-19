# ageval Product Requirements

| 字段 | 值 |
| --- | --- |
| 产品名 | **ageval**（agent eval） |
| 设计规范 | 本仓 [README.md](README.md) 与 [design/](design/)（自包含） |
| 结构规范 | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| 状态 | 机制以本目录为准；增量交付与验收跟踪见代码与 GitHub Issues |

## 1. 核心定位

为解耦任务逻辑与执行后端，ageval 锁定一份 **dataset** 与角色配置（`profiles.yaml`），在选定的执行环境（本机、Docker、E2B、SSH 或 Daytona）中运行单次 **Attempt**，并由独立的 `evaluator.py` 给出评分结果。编排统一由本机 `ageval run` 驱动。

Core 负责配置锁定（`lock`）、环境生命周期、角色会话调用分发、独立评分绑定、执行证据归档与 `finally` 资源清理；任务内部的交互循环与工具调用逻辑由任务脚本 `run.py` 定义。

## 2. 解决的问题

当任务逻辑直接耦合特定 Agent 执行器的调用接口或底层环境管理 API 时，更换 harness 或执行环境就需要修改任务代码；同时，若评分参考材料（`gold`）在执行阶段暴露，或缺乏统一的资源预算与配置锁定记录，跨配置的评测分数便无法复现和对比。

ageval **统一管理** 配置锁定、环境启停、会话调用预算、执行与评分的阶段边界、结构化证据归档与环境清理；**保持开放** 任务内部的交互控制流与领域工具实现。

## 3. 目标用户与典型场景

| 角色 | 核心任务 |
| --- | --- |
| Benchmark 转换者 / 研究员 | 将上游 benchmark 转换为 ageval dataset，在固定任务逻辑下跨模型与 harness 开展受控评测 |
| Dataset 作者 | 编写 `run.py`、`evaluator.py` 与可选 `environment/` 配方，无需处理容器生命周期或宿主凭据 |
| 插件作者 | 实现 `environment` 或 `executor` 独占槽及生命周期链槽，按协议或机制扩展后端 |
| 实验操作者 | 使用 `ageval lock` / `run` / `campaign` 运行评测，通过 `profiles.yaml` 或 `--agent` 切换环境与 harness |
| 结果分析者 | 基于归档的 Attempt 证据查阅轨迹、运行只读分析器或执行 `regrade` 重新评分 |

## 4. 成功标准

1. `src/ageval/attempt/__init__.py` 直接体现 `environment → run → evaluate → record` 与 `finally cleanup` 的固定阶段顺序。
2. 切换运行环境仅需修改 `profiles.yaml` 中的 `environment:`，ACP 与 `run.py` 不感知 `container_id` 等底层句柄。
3. 同一份 `environment/Dockerfile` 可供 `docker`、`e2b` 与 `daytona` 复用。
4. `PASS` 与 `FAIL` 仅来自独立的 `evaluator.py`；`RunTerminal.completed` 或轨迹完成不代表 `PASS`。
5. 未知 schema format 在 `lock` 阶段直接报错 `invalid_format`（位于 `/format`）并终止。
6. 单次 Trial 的任务参数、环境配置、角色 executor 与 `ModelSpec` 均写入 lock 摘要，支持跨团队核验一致性。
7. 每次 Agent 调用均归档为标准化轨迹（`trajectory.jsonl`），并由 `Result.logs` 指向对应的证据目录。

详细架构红线、用户故事 US1–US12 与命名约定见 [design/00](design/00-overview-and-product.md)；轨迹格式见 [design/05-runtime/evidence.md](design/05-runtime/evidence.md)；生命周期与模块依赖见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 5. 职责划分

| 层级 | 核心职责 |
| --- | --- |
| **Core** | `load_and_lock` 配置锁定；Attempt 固定阶段调度；`EnvironmentProvider` 协议；`limits` 资源与配额控制；封存 solver 后上传参考材料并绑定评分结果；归档 Attempt 证据与轨迹 |
| **SDK (`ageval_sdk`)** | 可选任务辅助库：`RunContext`、`AgentSession`、`ToolSet` 与并发收集原语 |
| **Dataset 任务** | 任务交互循环（`run.py`）、领域工具、上游桥接代码、评分准则（`evaluator.py`） |
| **Application** | CLI 入口、Campaign 矩阵与 Suite 调度、组合根对象装配 |

## 6. 非目标（Out of Scope）

- 不在 Core 中直接耦合特定云厂商 SDK 或镜像模板缓存（缓存逻辑封装在各环境插件内部，Core 仅调用 `host.start()`）。
- 不在任务目录中重复编写 Attempt 阶段编排逻辑。
- 不将环境初始化（`setup.sh`）拆分为独立于 `environment` 的顶层阶段。
- 不允许插件跳过 `cleanup`、自行签发 `PASS` 或调换 `run` 与 `evaluate` 的先后顺序。
- 不为旧版 schema format 提供兼容映射层。
- 不在 Core 或插件中按具体 benchmark 或任务名称编写条件分支。

## 7. 用户故事索引

完整定义见 [design/00](design/00-overview-and-product.md)：

| ID | 概要 |
| --- | --- |
| US1 | 切换环境仅修改 `profiles.yaml` 的 `environment:` |
| US2 | 同一份 `Dockerfile` 同时支持本地容器与云沙箱构建 |
| US3 | `setup.sh` 作为 `environment` 阶段的末尾链槽执行 |
| US4 | ACP 通过环境提供的 `attach_stdio` 双向流接入任意兼容环境 |
| US5 | `lock` 阶段静态校验 `requires ⊆ capabilities` |
| US6 | 辅助服务通过 Docker Compose 或 `host.exec(service=)` 管理 |
| US7 | 新增环境插件无需修改 `attempt/`、ACP 或 `run.py` |
| US8 | 镜像与云沙箱模板缓存封装在环境插件内部，对 Core 透明 |
| US9 | `attempt/__init__.py` 清晰呈现完整阶段控制流 |
| US10 | 任务目录保持精简，默认入口文件自动识别 |
| US11 | 参考材料（`gold`）延迟至 `evaluate` 阶段上传 |
| US12 | `ssh` 支持远程主机（模式 A）与远程容器（模式 B）及 ACP 运行时探测 |
