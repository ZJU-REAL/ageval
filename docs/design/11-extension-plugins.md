# 11 — 插件系统（独占槽、链槽与依赖注入）

为在替换底层环境与执行器的同时支持运行时准备、任务初始化与轨迹收集等横切扩展，且避免插件直接耦合具体实现类，ageval 提供基于**独占槽**（`exclusive slot`）、**链槽**（`chain slot`）与**声明式依赖注入**（`inject`）的插件机制。插件槽标识符定义在 `src/ageval/plugins/slots.py` 中，完整阶段调度顺序见 [ARCHITECTURE.md](../../ARCHITECTURE.md) § Extension Emit Map 与 [05-runtime/README.md](05-runtime/README.md)。

| 维度 | 作用 | 定义位置 |
| --- | --- | --- |
| **插件槽 (slot)** | 声明插件在 Attempt 生命周期的**哪个扩展点**接入 | `src/ageval/plugins/slots.py` |
| **命名服务 (service)** | 声明运行期内**可被其他插件调用的能力接口** | 独占槽实现自动注册为同名服务；插件也可通过 `exports.services` 显式导出 |

## 接口与实现分离：export / inject / capabilities

插件之间不通过硬编码 `plugin_id` 或直接导入对方模块通信，而是通过命名服务与能力契约解耦：

| 机制 | 含义 | 设计约束 |
| --- | --- | --- |
| **export** | 独占槽实现自动以槽位名称（如 `environment`）注册进服务表 | 不向外部模块泄露底层容器 ID 或厂商专有 SDK |
| **inject** | 插件按**服务名称**声明依赖，并列出所需的 **capabilities** 能力标记 | 不绑定具体 `plugin_id`（如不写 `inject: {plugin_id: e2b}`），也不在调用中编写 `if kind ==` 分支 |
| **协议调用** | 仅调用目标服务在协议中定义的方法（如 `attach_stdio`、`exec`、`upload`） | 不假定宿主机本地文件路径，不在执行器内自行拼接 `docker exec` |

例如，ACP 执行器仅声明依赖具备 `attach_stdio` 能力的 `environment` 服务；`docker` 将 `docker exec -i` 封装在自身的 `attach_stdio` 实现中，`e2b` 与 `daytona` 则将云沙箱双向标准流封装在同一方法内。因此，切换环境类型时，执行器代码与 `inject` 声明均无需改动。

### 两阶段静态契约校验

1. **导入期注册校验：** 内置与外置的环境及执行器插件分别继承 `BaseEnvironment` 与 `BaseExecutor`（`src/ageval/plugins/base.py`），并通过 `@environment_plugin` / `@executor_plugin` 装饰器注册。装饰器在模块导入时校验类体是否完整实现了必需的生命周期方法、声明的能力方法以及模型契约属性（`supported_apis`、`supported_model_fields`、`extra_allowlist`）；不满足契约时直接抛出 `PluginContractError`，拒绝插入注册表。
2. **锁定期配置校验（`ageval lock`）：** 解析器构建插件依赖图（`ExtensionGraph`），选定各独占槽实现、排定链槽顺序、核对 `requires_environment` 与 `inject` 能力依赖，并调用 `BaseExecutor.supports_model(spec)` 校验角色 profile 的 `ModelSpec`（详见 [16](16-model.md)）。对于缺少类级装饰器的第三方纯 YAML 工厂插件，默认给出 `YamlOnlyExecutorWarning`（提示在 2027-01-15 后停止支持），而在设置 `AGEVAL_STRICT_MODEL_CONTRACT=1` 时直接在 `lock` 阶段报错 `PluginContractError`。

### 独占槽与链槽的绑定粒度

| 槽位类型 | 语义 | 当前槽位 |
| --- | --- | --- |
| **独占槽 (exclusive)** | 每个解析图绑定唯一实现并导出为同名服务 | `environment`、`executor`、`evaluation_runtime`、`trajectory_seal` |
| **链槽 (chain)** | 按优先级排序串联执行的钩子 `(ctx, value, nxt)` | `after_environment_ready`、`environment_setup`、`trajectory_collect`、`trajectory_enrich`、`summary_enrich`、`cleanup_report` 等 |

- `environment`、`evaluation_runtime` 与 `trajectory_seal` 为 **Attempt 级**独占槽（后两者默认绑定引擎内置实现 `plugin_id: default`）。
- `executor` 为**角色 profile 级**独占槽：`agent_profiles` 中每个角色独立解析一份插件图，允许同一 Attempt 中 `solver` 与 `judge` 绑定不同的执行器实现。
- 未列入 `extensions` 的可选插件不会进入当前运行的调用链或镜像构建层。`PASS`、Attempt 身份与 `cleanup` 属于引擎核心不变量，不可通过插件服务覆盖。

## 插件清单示例（`ageval.plugin/1`）

```yaml
# 环境插件示例
format: ageval.plugin/1
plugin_id: e2b
description: Provision the Attempt environment on E2B cloud sandboxes.
slots:
  exclusive:
    - id: environment
      entry: e2b_plugin:E2BHost

# 执行器插件示例
format: ageval.plugin/1
plugin_id: acp
description: Parent ACP JSON-RPC client over environment attach_stdio.
slots:
  exclusive:
    - id: executor
      entry: acp.executor:AcpExecutor
  chain:
    - id: after_environment_ready
      entry: acp.hooks:ensure_runtime
inject:
  - service: environment
    capabilities: [attach_stdio]
```

外置插件包（如 `plugins/nooa/plugin.yaml`、`plugins/dsh/plugin.yaml`）还可声明 `host_requires`（宿主机依赖检查）与 `config.image_layers`（供 Docker 环境在构建期叠加镜像层）。`description` 为可选的单段功能说明（支持行内 Markdown 链接），在 Hub 插件详情页的命令条上方展示。

## 优先级与解析规则

```text
profiles.environment / agent_profiles.<id>.executor / extensions
  → ExtensionRegistry.resolve → ExtensionGraph（按每个角色 profile 解析独立依赖图；Attempt 级 environment 必须一致）
       exclusive: 选出唯一实现（显式指定优先，否则数值更小的 priority 优先；并列冲突则拒绝）
       chain:     按 priority 升序排列的钩子调用链
  → 写入 lock.extension_bindings 并纳入配置摘要（digest）
```

默认优先级 `DEFAULT_PRIORITY = 1000`，**数值越小优先级越高**（在链槽中越先执行）。`ageval plugin install` 仅将插件安装至 `~/.ageval/plugins`，不会自动修改任何 `profiles.yaml`。

## 内置插件与外置插件目录

- **内置插件（First-party contrib）：** 位于 `src/ageval/plugins/contrib/`，共 8 个保留短 ID：`local`、`docker`、`e2b`、`ssh`、`daytona`、`acp`、`openai-http`、`anthropic-http`。它们通过 `services/registry/packages/builtin_plugins.json` 在 Hub `/plugins` 页面展示为内置目录项，无需通过 `ageval plugin install` 安装（尝试发布或安装同名短 ID 会被拒绝）。
- **外置插件（External plugins）：** 位于仓库根 `plugins/`（`nooa`、`dsh`、`miniswe`、`terminus-2`、`openhands`、`acp-oneshot`、`home-files`、`agent-skills`），或发布在 Hub 上。每个插件目录必须包含 `plugin.yaml` 与包含 **Capabilities** 和 **Parameters** 表格的 `README.md`（详见 `skills/ageval-plugin`）。`openhands` 在 Attempt 环境内运行固定版本的 OpenHands SDK，注入 `exec`、`upload`、`download`。任务说明以上传文件进入环境。worker 写出 `openhands.trajectory/1`，记录阶段映射为 `ageval.trajectory.event/1`。每次 tool call 前的 `thought`、`reasoning_content` 与可见 thinking 映射为 channel `thought`，封存为 assistant turn 的 `part: thought`。SDK 只在该环境内导入。镜像层与环境内安装使用同一精确 pin；安装失败时 invoke 返回 `openhands_sdk_install_failed`。`terminus-2` 把模型循环留在父进程，tmux 按需装进 Attempt 环境。四条路径（ACP、miniswe、terminus-2、openhands）的放置对照见 [05-runtime/agent-service.md](05-runtime/agent-service.md#executor-placement)。

注意区分四个独立状态：**Hub 目录可见** ≠ **本机已安装插件包** ≠ **本机满足 `host_requires` 运行条件** ≠ **Docker 镜像已写入插件层**。

## 链槽钩子签名与扩展字段约定

```python
async def trajectory_collect(ctx, value, nxt):
    out = await nxt(value)
    return out
```

- `FAIL_OPEN_SLOTS`（`before_run`、`after_run`、`trajectory_collect`、`trajectory_enrich`、`summary_enrich`、`cleanup_report`）发生异常时记录警告而不中断后续步骤；其余插件槽异常直接使当前阶段失败。
- `trajectory_collect` 与 `trajectory_enrich` 可在单次调用载荷的 `extra` 字段中补充 JSON-safe 观测数据，不得删除标准 `usage` 字段。
- `summary_enrich` 在 `trajectory_seal` 完成后执行一次，各插件仅向 `value[<plugin_id>]` 写入 Attempt 级汇总观测数据（详见 [05-runtime/evidence.md](05-runtime/evidence.md)）。
