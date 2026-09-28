# ageval Product Requirements

| 字段 | 值 |
| --- | --- |
| 产品名 | **ageval**（agent eval） |
| 设计权威 | 本仓 [README.md](README.md) 与 [design/](design/)（自包含；不要读仓外 BRIEF） |
| 结构权威 | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| 状态 | 机制以本目录为准；实现与验收见代码与 GitHub Issues |

## 1. 一句话

ageval 锁定一份 dataset，在选定的环境里跑一次 Attempt，由独立 evaluator 出分。环境可以是本机、Docker、E2B、SSH 或 Daytona；编排始终在本机 `ageval run`。

Core 只做 lock、开环境、invoke、评测、evidence、cleanup。题怎么 loop 写在 dataset 的 `run.py`，不写进 Core。

## 2. 问题

Agent 评测把编排、隔离、可见性和打分权威散落在各家 harness 里。换 coding agent 或换环境，分数就不可比。

ageval **统一** lock、开环境、invoke、评测、evidence、拆环境；**不统一** 题内部怎么 loop、怎么用 Tool。

## 3. 用户与 Jobs

| 角色 | Job |
| --- | --- |
| 转换者 / 研究员 | 上游 task → ageval dataset，少改 workflow，自动评测 |
| 题包作者 | `run.py` + `evaluator.py` + 可选 `environment/`，不碰 Docker/credential/verdict |
| 插件作者 | 填独占槽 `environment` 或 `executor`，按机制命名 |
| 实验操作者 | `ageval lock` / `run` / `campaign`；换 `profiles.yaml` 的 `environment` 与 ACP `entry` |
| 观察 / 训练消费者 | 从 Attempt evidence 复盘并导出轨迹（轨迹不是 PASS） |

## 4. 成功标准

1. 打开 `src/ageval/attempt/__init__.py` 能说出 phase 顺序。
2. 换环境只改 job `environment:`，ACP / `run.py` 不见 `container_id`。
3. 同一份 `environment/Dockerfile` 可供 docker 与 e2b 使用。
4. PASS 只来自独立 evaluator；`RunTerminal.completed` 不是 PASS。
5. 未知 format lock 失败：`invalid_format` 于 `/format`，一个错误，不映射。
6. 一次 Trial 的参数、envelope、kind 与 evaluator 输入可锁定、可比较。
7. 每次真实 Agent invocation 落盘为可解析轨迹；`Result.logs` 指向该树。

度量优先：**可转换覆盖面与单次转换成本**，不是示例个数。没有 invocation 落盘，不算完整产品路径。

详细红线、用户故事 US1–US12、命名与术语对照见 [design/00](design/00-overview-and-product.md)。轨迹布局见 [design/05-runtime/evidence.md](design/05-runtime/evidence.md)。生命周期图见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 5. 能力地图（对齐 Core）

| 层 | 能力 |
| --- | --- |
| **Core** | Config `load_and_lock`；Attempt 五个阶段；环境 Protocol；Capability；停写后再打分 + 结果绑定；Agent 只能看见允许的文件；Attempt evidence / 轨迹落盘 |
| **SDK** | 可选：`RunContext`、AgentSession、Tool/Guard |
| **题包** | 业务 workflow、本地 Tool、upstream bridge、`evaluator.py` |
| **Application** | CLI、Campaign/matrix、内置/插件接线 |

## 6. 这轮非目标

- 不把 Harbor 的全部云厂商一次搬进来。
- 不把 vendor SDK / alias 缓存写进 Core。Core 只调 `host.start()`。
- 不保留 Environment Manager。
- 不把环境做成 `provide(executor)`。没有第三种 `provide()` 扩展模型。
- 不在每个 task 里复制 Attempt 编排。
- 不单开 `provision` phase。

- 插件不能取消 cleanup、不能发明 PASS、不能重排「先打分再跑 agent」。
- 未知 format 不映射。
- Core 内通用 Graph / Handoff / BranchAuthority 平台。
- 开放插件商店。
- 按 Benchmark 名的 Core 分支。
- gaia / tau3 全 suite、五条 ACP 全部付费 invoke、默认 CI 真打 E2B、多 group 真调度 run。见 [design/00](design/00-overview-and-product.md)「这轮不包含」。

## 7. 用户故事（摘要）

完整约束在 [design/00](design/00-overview-and-product.md)：

| ID | 一句话 |
| --- | --- |
| US1 | 换环境只改 `environment:` kind |
| US2 | 一份 Dockerfile，docker 与 e2b 都能用 |
| US3 | `setup.sh` 是 environment 末槽 |
| US4 | ACP 只经 `attach_stdio` 进任意环境 |
| US5 | `requires ⊆ capabilities`，否则 lock 失败 |
| US6 | 无 Environment Manager；侧车 compose / `host.exec(service=)` |
| US7 | 厂商扩 kind 不改 attempt / ACP / `run.py` |
| US8 | 缓存对 Core 无感 |
| US9 | 打开 `attempt/__init__.py` 看见整条链 |
| US10 | task 目录薄；有文件就认 |
| US11 | gold 进 evaluate 再 upload |
| US12 | ssh A 整机 / B 远端已有容器 |

实现是否兑现：Current = 代码与公开 smoke；Target = e2b/ssh 真跑等，见 ARCHITECTURE。
