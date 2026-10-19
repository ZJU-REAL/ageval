# 01 — ageval Core

源码结构见 [ARCHITECTURE.md](../../ARCHITECTURE.md)，产品定位与命名见 [00](00-overview-and-product.md)。

Core 负责：配置锁定（`lock`）、Attempt 身份管理、`EnvironmentProvider` 协议、`limits` 资源与配额强制、阶段边界与评分结果绑定、以及 evidence 归档目录结构。任务交互逻辑、厂商专有 SDK 与具体评分算法不在 Core 内部实现。

## 核心子模块

| 模块组 | 路径 | 核心职责 |
| --- | --- | --- |
| Config | `src/ageval/config/` | `load_and_lock`、配置摘要（digest）、`profiles.yaml` 解析、插件与能力校验 |
| Lifecycle | `src/ageval/attempt/` + `runtime/identity.py` | Run / Trial / Attempt 身份签发；固定阶段顺序调度 |
| Environment | `environments/protocol.py` + `plugins/contrib/{local,docker,e2b,daytona,ssh}` | 环境隔离、命令执行、文件传输与 `attach_stdio` 通信 |
| Capability | `capabilities/` + lock `requires` | 授权操作集合与调用配额检查 |
| Evaluation | `evaluation/` | 阶段隔离屏障、子进程 `evaluator.py` 执行与 `bind_evaluation` 结果绑定 |

此外，`evidence/` 统一管理 `.ageval/runs/` 路径布局与 `trajectory.jsonl` 封存；`plugins/` 维护插件槽与服务注册表。

## 配置锁定（`ageval lock`）

Config 模块是配置文件的唯一规范解析入口，读取根 `ageval.yaml`（`ageval.dataset/1`）、成员 `task.yaml`（`ageval.task/1`）与运行配置 `profiles.yaml`（`ageval.profiles/1`）。

```text
CLI --task / --profiles / --set
  → dataset.resolve
  → merge task.yaml + profiles.yaml
  → validate format / keys / requires ⊆ capabilities
  → resolve exclusive-slot implementations + chain-slot order → extension_bindings
  → verify inject dependencies & ModelSpec contracts
  → canonicalize → digest
  → LockedTaskConfig (immutable)
```

遇到未知 format 时直接报错 `invalid_format`（位于 `/format`）。`api_key` 仅保留环境变量名引用（locator）。若两个插件在同一解析图上竞争同一独占槽或导出相同服务 ID，解析直接拒绝。解析后的插件绑定关系写入 `extension_bindings` 并纳入 lock digest；未列入 `extensions` 的可选插件不进入执行链或服务表。

`--profiles` 可整份替换默认配置文件；`--agent` 与 `--profiles` 互斥；`--model` 需配合 `--agent` 使用以覆盖绑定角色的 `model.id`。`--set` 允许覆盖的字段白名单见 [02](02-task-package-and-config.md)，`limits.*` 不允许通过 `--set` 修改。

## Attempt 阶段流水线

`src/ageval/attempt/__init__.py` 定义单次 Attempt 的权威阶段顺序。Attempt 身份签发、阶段超时控制、`try/finally` 中的 `cleanup` 以及仅通过 `evaluate` 绑定 `PASS` 均属于引擎不变量，不由插件覆盖。

```python
# src/ageval/attempt/__init__.py
async def run_attempt(ctx) -> None:
    try:
        await environment.run(ctx)  # 启动环境 + 上传数据 + 运行时准备与 setup.sh
        await run.run(ctx)          # 子进程运行任务 run.py
        await evaluate.run(ctx)     # 封存 solver 后上传参考材料并运行 evaluator.py
    finally:
        await record.run(ctx)       # 封存轨迹与运行摘要（环境已启动后即使后续阶段报错仍归档已有轨迹）
        await cleanup.run(ctx)      # 停止并清理已启动的评分环境与运行环境
```

若 `environment` 或 `run` 阶段失败，系统记录首次 `phase_failed` 事实并跳过后续未执行的业务阶段；一旦环境已启动，即使 `run` 或 `evaluate` 发生 `ERROR`，`finally` 中仍会执行 `record` 将已产生的调用事件封存为 `trajectory.jsonl`，随后执行 `cleanup` 释放环境资源。若 `record` 自身在已有阶段错误后再次异常，仅记录 `record_warning` 而不覆盖原阶段错误。

## 阶段（Phase）与插件槽（Slot）

- **阶段（Phase）：** `run_attempt` 中的顶层生命周期步骤，默认实现位于 `attempt/phases/*.py`。
- **插件槽（Slot）：** 阶段内部的扩展接入点，仅分为**独占槽**（`exclusive slot`）与**链槽**（`chain slot`）两类：

| 插件槽类型 | 语义 | 示例 |
| --- | --- | --- |
| **独占槽 (exclusive)** | 每个解析图绑定唯一实现，并自动注册为同名服务（service） | `environment`、`executor`、`evaluation_runtime`、`trajectory_seal` |
| **链槽 (chain)** | 按优先级顺序串联执行的钩子函数 `(ctx, value, nxt)` | `after_environment_ready`、`environment_setup`、`trajectory_collect` |

其中，`environment`、`evaluation_runtime` 与 `trajectory_seal` 为 **Attempt 级**独占槽（单次 Attempt 全局绑定一个实现）；`executor` 为**角色 profile 级**独占槽（`agent_profiles` 中每个角色独立解析一份绑定，允许同一 Attempt 中 `solver` 与 `judge` 使用不同的执行器插件）。

`evaluation_runtime` 与 `trajectory_seal` 默认绑定引擎内置实现（`plugin_id: default`），分别负责在父进程子进程中运行 `evaluator.py` 和封存 `trajectory.jsonl`（若 `evaluate` 阶段调用了 SDK 会话，则另写 `evaluation/observation.jsonl`）。`PASS` 仅能通过 `AttemptCtx.bind_evaluation` 写入 `Result`，`evaluation_runtime` 实现只返回原始评分输出。

各阶段默认行为如下：

| 阶段 | 默认行为 |
| --- | --- |
| `environment` | 调用 `host.start` 启动环境，上传 `data/` 至工作区，依次触发 `after_environment_ready` 与 `environment_setup` 链槽 |
| `run` | 在受限子进程中运行 `run.py`，通过父进程 Agent Service 处理角色会话调用；结束时封存 solver 会话并收集声明的任务产物快照 |
| `evaluate` | 确定评分环境（默认复用 `run` 环境；若配置 `evaluate_host.isolated: true` 则启动独立 Docker 评分容器；若声明 `evaluation.environments` 则按名称懒启动多个评分容器），执行 `evaluation.collect`，上传产物快照与 `evaluation/` 参考材料，调用 `evaluation_runtime` 运行 `evaluator.py` 并通过 `bind_evaluation` 绑定结果 |
| `record` | 触发 `trajectory_collect` / `trajectory_enrich`，由 `trajectory_seal` 写出 `trajectory.jsonl`（及可选的 `evaluation/observation.jsonl`），最后触发 `summary_enrich` |
| `cleanup` | 在 `finally` 中停止所有已启动的独立评分容器与 `run` 环境 |

### `environment` 阶段内的执行顺序

以 `src/ageval/attempt/phases/environment.py` 为准：

```python
async def run(ctx) -> None:
    await emit(ctx, "before_environment")
    await ctx.host.start(force_build=ctx.lock.force_build)
    await ctx.host.upload(ctx.seed_dir, "/attempt/workspace")  # 存在 data/ 时上传
    await emit(ctx, "after_environment_ready")  # 写入 HOME 配置覆盖层、注入环境变量、执行 ACP 运行时探测
    await emit(ctx, "environment_setup")        # 执行 environment/setup.sh（不存在则跳过）
    await emit(ctx, "after_environment")
```

- `after_environment_ready`：在环境启动后、`environment_setup` 之前执行，负责写入角色配置覆盖层及探测 ACP 运行时（核对 `npm ls -g --depth=0` 版本、可执行文件 `realpath` 与 stdio `initialize` 握手；若已在镜像构建期写入且匹配则直接跳过安装）。
- `environment_setup`：若任务包含 `environment/setup.sh`，则通过 `host.exec` 安装任务级依赖。
- 镜像层构建（`image_layers`）在 `host.start()` 内部完成（如 Docker 镜像构建或 E2B 模板构建）。

### `evaluate` 阶段：延迟上传参考材料与可选独立评分容器

以 `src/ageval/attempt/phases/evaluate.py` 为准：

- **默认模式（省略 `evaluate_host`）：** 复用 `run` 阶段已打开的环境，在 solver 会话封存后将 `evaluation/` 上传至 `/attempt/evaluation`，再由父进程启动 `evaluator.py` 子进程完成评分。

```python
async def run(ctx) -> None:
    await emit(ctx, "before_evaluate")          # solver 会话已在 run 阶段末尾封存
    # 执行可选的 evaluation.collect 路径收集
    if ctx.evaluation_src.exists():
        await ctx.host.upload(ctx.evaluation_src, "/attempt/evaluation")
    result = await ctx.evaluation_runtime.evaluate(ctx)
    ctx.bind_evaluation(result)                 # PASS / FAIL 唯一绑定入口
    await emit(ctx, "after_evaluate")            # 可补充指标，不可修改 status
```

- **单独立评分容器（`evaluate_host.isolated: true`）：** 在产物快照收集完成后，使用任务的 `environment/evaluate.Dockerfile`（或 `evaluation.docker_image`）启动一个独立的 Docker 评分容器，将产物快照与 `evaluation/` 仅上传至该评分容器。待测 Agent 所在的环境全程不接触 `evaluation/`。
- **多命名评分容器（`evaluation.environments`）：** 任务声明多个命名评分环境配方，在 `evaluator.py` 首次调用 `scoring.exec(<name>, argv)` 或 `Agent.session(..., environment=<name>)` 时按需启动对应容器并上传产物快照与参考材料。该模式要求 `evaluate_host.isolated: true` 且 `environment: docker`。

### 各阶段挂载的插件槽汇总

| 所属阶段 | 插件槽 |
| --- | --- |
| `run` | `before_run` / `after_run`；`before/after_agent_open\|invoke\|close`；`normalize_agent_result` |
| `evaluate` | `before_evaluate` / `after_evaluate`；独占槽 `evaluation_runtime` |
| `record` | `trajectory_collect` / `trajectory_enrich`；独占槽 `trajectory_seal`；`summary_enrich` |
| `cleanup` | `cleanup_report`（`cleanup` 阶段本身由 `finally` 无条件调用） |

`FAIL_OPEN_SLOTS` 包含：`before_run`、`after_run`、`trajectory_collect`、`trajectory_enrich`、`summary_enrich`、`cleanup_report`；其余插件槽抛出异常时直接使当前阶段失败。完整调度顺序见 [ARCHITECTURE.md](../../ARCHITECTURE.md) § Extension Emit Map。

## 环境协议（`EnvironmentProvider`）

`environment` 独占槽实现遵循 `src/ageval/environments/protocol.py` 定义的协议，厂商 SDK 仅封装在 `plugins/contrib/<kind>/` 内：

```python
class EnvironmentProvider(Protocol):
    kind: str
    capabilities: EnvironmentCapabilities  # exec / upload / download / attach_stdio / uid_gid / path_views / compose
    python_command: tuple[str, ...]

    async def preflight(self) -> None: ...
    async def start(self, *, force_build: bool = False) -> None: ...
    def placement(self) -> Placement: ...          # opaque target_id + user + workdir/home
    async def exec(self, command, *, cwd=None, env=None, timeout_sec=None, user=None, service=None): ...
    async def upload(self, source, dest) -> None: ...
    async def download(self, source, dest) -> None: ...
    async def attach_stdio(self, argv, *, placement, env=None) -> StdioTransport: ...
    async def stop(self, *, delete: bool) -> None: ...
```

支持的环境类型（`kind`）：`local` | `docker` | `e2b` | `ssh` | `daytona`。环境内标准路径约定为 `/attempt/workspace`、`/attempt/home`、`/attempt/artifacts` 与 `/attempt/evaluation`。

## 组合根（Composition Root）

```text
cli → application.composition.build_*
        → config.load_and_lock
        → identity.new_run / new_trial / new_attempt
        → bind environment plugin (Attempt-wide) + per-profile executor plugins
        → ParentAgentService
        → run_attempt
```

所有平台对象的实例化与装配均集中在 `application/composition.py` 的 `build_*` 函数中；控制面通过进程边界调用任务脚本 `run.py` 与 `evaluator.py`。模块职责与结构约束详见 [09](09-owner-matrix-and-structure.md)。
