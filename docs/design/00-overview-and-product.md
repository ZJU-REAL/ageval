# 00 — 产品总览与架构红线

为解耦任务逻辑与执行后端，ageval 将单次任务评测组织为结构化的 **Attempt**：锁定 **dataset** 与角色配置（`profiles.yaml`），启动选定的**环境**，运行任务脚本 `run.py`，并在封存 solver 会话后由独立的 `evaluator.py` 给出评分。编排统一在本机 `ageval run` 进程中完成，底层环境支持本机目录（`local`）、Docker 容器（`docker`）、云沙箱（`e2b`、`daytona`）与远程主机（`ssh`）。

本文汇总产品模型、职责分层、命名规范、用户故事 US1–US12 与架构红线。机制细节见 [01](01-ageval-core.md) 与 [05-runtime/](05-runtime/)；代码结构见 [ARCHITECTURE.md](../../ARCHITECTURE.md)；开发规范见 [AGENTS.md](../../AGENTS.md)。

## 产品标识与配置格式

| 维度 | 规范值 |
| --- | --- |
| 产品名 / 文档站 / README | **ageval**（agent eval） |
| CLI | `ageval lock` / `ageval run` / `ageval view` 等 |
| Python 包与导入名 | `ageval` / `ageval_sdk` |
| PyPI 发行包名 | **`ageval-cli`**（单 wheel 内含 `ageval` 与 `ageval_sdk` 两个顶层包） |
| 环境变量 / 主目录 | `AGEVAL_*`、`~/.ageval` |
| Schema formats | `ageval.dataset/1`、`ageval.task/1`、`ageval.plugin/1`、`ageval.profiles/1`、`ageval.agent/1` |
| GitHub 仓库 | [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval) |

遇到未知 format 时，配置解析直接报 `invalid_format`（位于 `/format`）并终止，不做旧格式兼容映射。

## 规范交付单位：dataset

评测数据集的交付单位是 **dataset**（根清单 `ageval.yaml` + `tasks/<id>/` 任务成员目录），区分于关系型数据库（如任务通过 Docker Compose 启动的 PostgreSQL 辅助服务）。

| 维度 | 规范值 |
| --- | --- |
| 产品术语 / CLI 帮助 | **dataset** |
| 根清单格式 | `format: ageval.dataset/1` |
| 根清单文件 | `ageval.yaml` |
| 代码标识符 | `dataset_id`、`dataset_root`、`load_dataset` |
| 任务成员清单 | `tasks/<id>/task.yaml`（`ageval.task/1`） |

`shared/` 相对于 **dataset 根目录**解析；评分参考材料（`gold`）存放在各任务的 `tasks/<id>/evaluation/` 下。

## 控制流总览

```text
ageval.yaml (ageval.dataset/1)
  → task.yaml + profiles.yaml
  → load_and_lock → digest + extension_bindings
  → host.preflight
  → run_attempt
       environment → run → evaluate → record
       finally cleanup
  → .ageval/runs/<attempt_id>/
```

`src/ageval/attempt/__init__.py` 直接定义上述阶段顺序。插件通过 `lock` 阶段解析的绑定介入各扩展点，不改写 `run_attempt` 的主阶段顺序。

## 三层职责划分

| 层级 | 核心文件 | 职责 |
| --- | --- | --- |
| **Core 运行时** | `src/ageval/attempt/` + `attempt/phases/*.py` | 环境准备 → 任务执行 → 独立评分 → 证据归档 → `finally` 环境清理 |
| **运行配置 (Profiles)** | `profiles.yaml` / `extensions` | 选择 `environment` 与各角色 `executor` 的独占槽实现、模型参数（`ModelSpec`）及链槽插件 |
| **Dataset 任务** | `run.py` / `evaluator.py` / `environment/` | 单题交互逻辑、评分标准与环境构建配方 |

## 核心命名规范

| 职责 | 规范名称 |
| --- | --- |
| Attempt 阶段编排 | **`src/ageval/attempt/__init__.py`**（`run_attempt`） |
| 任务执行阶段入口 | **`run.py`**（`async def run(ctx)`） |
| 独立评分阶段入口 | **`evaluator.py`** |
| 环境插件槽 | 独占槽 **`environment`**；通过 `ctx.host` 或 `ctx.services.require("environment")` 访问 |
| Agent 执行器插件槽 | 独占槽 **`executor`**（按角色 profile 独立绑定，如 `acp`、`openai-http`、`miniswe`、`terminus-2`） |

## 设计目标

1. **清晰的阶段流水线：** 单次 Attempt 的执行顺序集中在 `attempt/__init__.py` 中，各阶段文件按绑定顺序调用 `emit(slot)`。
2. **阶段与插件槽解耦：** 阶段（`phase`）定义宏观生命周期，插件槽（`exclusive slot` 与 `chain slot`）定义可替换的组件服务与钩子。
3. **统一环境接口：** 环境通过独占槽 `environment`（`local` / `docker` / `e2b` / `ssh` / `daytona`）接入；`lock` 阶段校验 `requires ⊆ capabilities`，不满足则在运行前终止。
4. **环境配方复用：** `environment/Dockerfile`（或 `docker_image`）可在 `docker`、`e2b` 与 `daytona` 间复用；`setup.sh` 作为 `environment` 阶段的末尾链槽 `environment_setup` 执行。
5. **精简任务目录：** 任务目录仅维护业务交互（`run.py`）、评分准则（`evaluator.py`）、数据与环境配方，`task.yaml` 自动识别默认文件。
6. **独立评分与参考材料隔离：** `PASS` 与 `FAIL` 仅来自 `evaluate` 阶段的 `evaluator.py`，参考材料（`gold`）延迟至 `evaluate` 阶段上传。

## 非目标

- 不在 Core 中内置特定云厂商 SDK 或镜像模板缓存（Core 仅调用 `host.start()`，模板缓存封装在对应环境插件内部）。
- 不在任务目录下复制生命周期编排代码。
- 不单独拆分 `provision` 顶层阶段。
- 不允许插件跳过 `cleanup`、自行返回 `PASS` 或改变阶段先后顺序。
- 不在适配器或插件中按具体 benchmark 或任务名称编写条件分支。

## 用户故事（US1–US12）

以下用户故事定义系统的目标契约；当前已完成公开验证的范围见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

### US1 — 切换环境仅改配置

`ageval run` 通过 `profiles.yaml` 的 `environment:` 选择环境实现（`local`、`docker`、`e2b`、`ssh`、`daytona`），`run_attempt` 编排逻辑保持不变；缺少云沙箱凭据时在 `preflight` / `lock` 阶段直接报错。

### US2 — 同一份 Dockerfile 跨环境复用

任务的 `environment/Dockerfile`（或 `docker_image`）在 `docker` 下本地构建，在 `e2b` / `daytona` 下构建云端模板或快照；若任务声明需要 `compose` 而所选环境不支持该能力，`lock` 阶段直接报错拒绝。

### US3 — `setup.sh` 在 `environment` 阶段末尾执行

若存在 `environment/setup.sh`，`environment` 阶段末尾通过 `emit("environment_setup")` 调用 `host.exec` 执行；不存在则跳过。脚本失败计为 `environment` 阶段 `ERROR`，不混入 Agent 轨迹。系统级重度依赖应写入 `Dockerfile`。

### US4 — ACP 跨环境统一接入

ACP 执行器通过 `inject: [service: environment]` 依赖 `attach_stdio` 能力，`Placement` 不暴露 `container_id` 等底层标识，ACP 插件不导入 `docker`、`e2b` 或 `ssh` 模块。

### US5 — 静态能力校验

`requires.environment` 默认为空；非空时必须满足 `requires ⊆ capabilities`，否则 `ageval lock` 直接报错。

### US6 — 辅助服务管理

多容器辅助服务（如数据库）通过 `environment/compose.yaml` 或 `host.exec(service=)` 管理，`run.py` 通过环境变量或任务参数读取连接信息。

### US7 — 扩展新环境插件不改动上层模块

新增环境后端只需实现 `EnvironmentProvider` 协议并注册至 `environment` 独占槽，无需修改 `attempt/`、ACP 或任务脚本。

### US8 — 模板缓存对 Core 透明

镜像与云沙箱模板的哈希缓存封装在对应环境插件内部，Core 统一调用 `host.start()`。

### US9 — 直观的阶段实现

开发者打开 `attempt/__init__.py` 与 `phases/*.py` 即可完整掌握单次 Attempt 的执行阶段与扩展槽顺序。

### US10 — 任务目录默认识别

任务作者只需提供 `run.py`、`evaluator.py`、`data/`、`evaluation/` 与可选 `environment/`，无需在 `task.yaml` 中重复声明标准入口文件名（详见 [02](02-task-package-and-config.md)）。

### US11 — 参考材料在 `evaluate` 阶段延迟上传

在 `environment` 与 `run` 阶段绝不挂载或上传 `evaluation/` 目录；仅在 `run` 结束并封存 solver 会话后，`evaluate` 阶段才将参考材料上传至评分环境并启动 `evaluator.py`。

### US12 — SSH 远程环境与 ACP 运行时探测

`environment: ssh` 支持模式 A（无 `image`，直接使用远程主机，`attach_stdio` 执行 `ssh -T -- argv`）与模式 B（指定远程已有镜像标签，`start` 执行远程 `docker run`，`attach_stdio` 执行 `ssh -- docker exec -i`）。在 `after_environment_ready` 阶段，ACP 插件检查全局 npm 包版本（`npm ls -g --depth=0`）与可执行文件真实路径（`realpath`），通过后执行一次 stdio `initialize` 握手；若版本或路径不匹配，则按 `install_command` 安装一次并复检，仍不满足则终止 `environment` 阶段。

## 架构红线

1. `PASS` 仅来自 `evaluate` 阶段绑定的 `evaluator.py` 返回值；轨迹、`RunTerminal.completed` 或 ACP `end_turn` 均不代表 `PASS`。
2. `lock.json`、evidence 目录与默认环境不得写入宿主明文密钥，凭据仅以环境变量名（locator）引用。
3. 插件与适配器按协议或执行机制命名（`acp`、`docker`、`e2b`、`ssh`、`openai-http`），禁止按 benchmark 名称分支。
4. ACP、`attempt/` 与 `run.py` 不得引用 `container_id` 或编写 `if kind == "e2b"` 分支。
5. `run` 阶段待测 Agent 环境中不存在 `evaluation/` 目录，参考材料在 `evaluate` 阶段开始时才上传。
6. 未知 schema format 直接报错 `invalid_format`（位于 `/format`）。
7. 不设产品级 `executor: mock`，不用模拟环境充当验收证据。
8. `cleanup` 始终在 `try/finally` 中执行，插件不得跳过 `cleanup` 或自行签发 `PASS`。
9. CLI 仅导入 `ageval.application.composition`。
10. 单次 Attempt 仅调用一次 `IdentityFactory.new_run`。
11. `inject` 能力检查在 `lock` 阶段完成；缺少 `attach_stdio` 等必需能力时在 `lock` 阶段直接报错。

## 快照分享

Hub 支持为本地 suite 或单次 Attempt 生成匿名只读分享链接 `/s/{token}`。默认模式（`static`）定格在创建时刻的汇总与证据快照；`mode=live` 时由运行端在子任务完成时增量更新同一链接。创建快照分享不改变原结果的公开/私有属性，也不将其列入公开 Leaderboard（详见 [12](12-hub-dataset-and-leaderboard.md)）。

## 当前范围之外

以下事项不在当前默认范围内；后续纳入并在阶段收尾时需同步更新 `docs/`：

- 全量上游大型 benchmark 的仓库内内置副本（大体积转换包通过 Hub 发布）
- 默认 CI 中的付费模型调用或真实云沙箱（E2B / Daytona / SSH）端到端执行
- 多容器分组（multi-group）并发调度的完整运行时执行（当前 `lock` 支持解析拓扑结构）
