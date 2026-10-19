# 16 — ModelSpec 与插件基类契约

为独立于 harness 配置模型参数并防止静默协议回退改变实验条件，角色 profile 中的 `model` 块统一解析为不可变的 `ModelSpec` 数据结构。

```python
from ageval.model import ModelConfigError, ModelSpec, require_model_support, resolve_model
from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.errors import PluginContractError
```

`src/ageval/model/` 负责解析与校验 `ModelSpec`；`src/ageval/plugins/base.py` 定义环境与执行器的抽象基类。`api_key` 与 `base_url` 作为凭据与端点定位符保留在角色 profile 顶层，不属于 `ModelSpec` 内部字段。

## `ModelSpec` 字段定义

`resolve_model(model, options=None)` 仅接受嵌套字典格式（拒绝纯字符串 `model` 或在 `options` 中平铺 `api`、`reasoning_effort`、`timeout`、`request_timeout`、`watchdog`、`extra_body` 等模型字段）：

| YAML 路径 | `ModelSpec` 属性 | 类型 | 省略时行为 |
| --- | --- | --- | --- |
| `id` | `id` | `str` | 必填（空字符串直接拒绝） |
| `api` | `api` | `str` | 默认为 `"chat"`；仅允许 `"chat"` 或 `"responses"` |
| `reasoning.effort` | `reasoning_effort` | `str \| None` | 保持 `None`（请求中不发送该字段） |
| `timeout` | `timeout` | `float \| None` | 保持 `None`（执行器默认读取 [`clocks.py`](../../src/ageval/runtime/clocks.py) 中的 `180` 秒；拒绝 `0`、负数或非有限值） |
| `watchdog` | `watchdog` | `float \| None` | 保持 `None`（执行器默认读取 `clocks.py` 中的 `180` 秒；拒绝 `0`、负数或非有限值） |
| `extra` | `extra` | `Mapping[str, Any]` | 默认为空字典 `{}` |

- **`reasoning.effort`：** 唯一的一等推理强度字段。显式设置 `"none"` 时会按值发送；省略时不发送。当设置为别名 `"max"` 时，`lock` 阶段先将该角色的 `model.id` 唯一关联至规范模型目录（canonical pin），并将其替换为该模型 `reasoning_options` 列表中的最高档位写入锁定配置；若无法唯一匹配模型或该模型未声明推理档位列表，`lock` 阶段直接报错并提示填写具体档位名。
- **`extra` 与 `extra_allowlist`：** `extra` 用于传递厂商专有扩展参数（如 `reasoning.summary`、`thinking` 或 `provider`），不得覆盖一等字段（禁止包含 `id`、`api`、`timeout`、`watchdog`、`reasoning_effort` 或 `extra.reasoning.effort`）。每个 `BaseExecutor` 子类通过类属性 `extra_allowlist` 声明允许接收的 `extra` 顶层键集合（空 `frozenset` 拒绝一切 `extra` 键）。
- **`supports_model` 静态检查：** `require_model_support(spec, *, supported_apis, supported_model_fields, extra_allowlist)` 校验 `api` 是否在 `supported_apis` 内、非空一等字段是否在 `supported_model_fields` 内、以及 `extra` 键是否在 `extra_allowlist` 内；任一不满足即抛出 `ModelConfigError`。

```yaml
model:
  id: openai/example-model
  api: responses
  reasoning:
    effort: xhigh
  timeout: 120
  watchdog: 300
  extra:
    reasoning:
      summary: auto
```

## 契约与配置异常类型

| 异常类 | 所在模块 | 触发时机 |
| --- | --- | --- |
| `PluginContractError` | `ageval.plugins.errors` | 插件类未声明 `extra_allowlist` / `supported_apis` / `supported_model_fields`；声明的能力标记缺少对应实现方法；或 `requires_environment` 未满足（`kind` 为 `plugin_contract`） |
| `ModelConfigError` | `ageval.model` | `model` 结构非法、不支持的 `api`、不支持的一等字段或不在 `extra_allowlist` 中的扩展键（`kind` 为 `model_config`） |

`ModelConfigError` 属于配置错误，在 `ageval lock` 阶段直接终止，不会在运行期触发 `upstream_stall` 重试。

## Lock 阶段校验流程

```text
解析各独占槽实现
  → resolve_model(profile) → ModelSpec
  → 若 requires_environment 为 True：校验 environment 服务已绑定且满足 inject 声明的 capabilities
       否则抛出 PluginContractError
  → 若执行器为 BaseExecutor 子类：调用类方法 supports_model(spec)（无需实例化）
       校验 supported_apis、supported_model_fields 与 extra_allowlist
       不满足则抛出 ModelConfigError
  → 校验通过后生成 LockedTaskConfig 与配置摘要（digest）
```

对于未继承 `BaseExecutor` 的外置纯 YAML 工厂插件：
- 若注册 `source` 为 `first-party`，直接抛出 `PluginContractError`；
- 若为第三方来源，在 `2027-01-15` 前默认发出 `YamlOnlyExecutorWarning`（设置 `AGEVAL_STRICT_MODEL_CONTRACT=1` 时立即提升为 `PluginContractError`；自 `2027-01-15` 起一律拒绝）。

## Executor Options 参数表

以下表格由 `scripts/gen_param_tables.py` 根据各执行器的冻结 `Options` 类与 `CLOCKS` 自动生成（`--check` 校验同步）：

### openai-http

<!-- ageval:param-table executor=openai-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### anthropic-http

<!-- ageval:param-table executor=anthropic-http -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.max_tokens` | 4096 | Required Messages max_tokens. Positive int. Non-int values are rejected. |
| `options.anthropic_version` | 2023-06-01 | anthropic-version request header. Non-string values are rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### acp

<!-- ageval:param-table executor=acp -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id. Shipped: codex, claude-code, pi, opencode, grok-build. Missing fails lock with acp_entry_required. |
| `options.idle_timeout_seconds` | unset | Stall ceiling during session/prompt. Any session_update or request_permission resets it. Unset or a non-positive value leaves only the wall-clock invoke timeout. Fires acp_idle_timeout. Non-numeric fails lock with acp_idle_timeout_invalid. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### miniswe

<!-- ageval:param-table executor=miniswe -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.stream` | `true` on `api: chat` | Chat Completions use SSE when true. false sends one JSON body. An omitted key is true, so AGEVAL_MINISWE_CHAT_STREAM=0 does not turn a profile run off. Responses ignores this. |
| `options.step_limit` | 30 | Agent step cap. 0 is unlimited. Negative values are rejected. |
| `options.cost_limit` | 0 | Cost cap. 0 is unlimited. Negative values are rejected. |
| `options.cmd_timeout` | 30 | Seconds per host.exec bash action. Negative values are rejected. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### nooa

<!-- ageval:param-table executor=nooa -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.agent` | *(required)* | Package-local module:Class (subclass nooa.Agent, or a deterministic class). Missing fails lock with nooa_options_agent_required. |
| `options.method` | run | Method invoked on that class. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### dsh

<!-- ageval:param-table executor=dsh -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.composition` | slim | Bundled compositions/<name>.cordis.yml. Path separators and a leading dot are rejected. Setting permission with omit or slim switches to sandboxed. |
| `options.permission` | unset | read-only, workspace-write, or danger-full-access. Omit keeps unrestricted slim tools. Invalid values are rejected. Sets DSH_PERMISSION_MODE. File-tool writes are fenced; bash redirect can still write. |
| `options.max_tokens` | unset | Omit, blank, or null does not pass max_tokens. A positive int is forwarded. A non-positive int, bool, string, or float is rejected. |
| `options.provider` | deepseek-official | Provider id on initialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

### acp-oneshot

<!-- ageval:param-table executor=acp-oneshot -->
| Name | Default | Purpose |
| --- | --- | --- |
| `options.entry` | *(required)* | ACP entry id (codex, claude-code, pi, opencode, grok-build). Missing or unknown fails materialize. |
| `options.upstream_stall_seconds` | 3600 | Parent stall budget in seconds. Omit uses the upstream_stall clock. 0 disables. A negative value or a non-integer is rejected. |
<!-- /ageval:param-table -->

## `BaseEnvironment` 抽象基类

所有环境插件继承 `BaseEnvironment` 并实现 `EnvironmentProvider` 协议：

| 属性 / 方法 | 契约要求 |
| --- | --- |
| `kind` | 类属性，环境唯一标识符（`local`、`docker`、`e2b`、`ssh`、`daytona`） |
| `capabilities` | 类属性，`EnvironmentCapabilities` 实例 |
| `python_command` | 类属性，环境内 Python 解释器命令元组 |
| `preflight` / `start` / `stop` | 抽象异步方法，子类必须实现 |
| `placement` / `visible_path` | 抽象方法，子类必须实现 |
| `exec` / `upload` / `download` / `attach_stdio` | 当对应 `capabilities` 字段为 `True` 时，子类必须实现对应方法（导入注册期由装饰器校验） |

## `BaseExecutor` 抽象基类

所有执行器插件继承 `BaseExecutor`：

| 属性 / 方法 | 契约要求 |
| --- | --- |
| `kind` | 类属性，执行器唯一标识符（如 `acp`、`openai-http`、`miniswe`） |
| `requires_environment` | 类属性（默认 `True`；纯 HTTP 执行器如 `openai-http` 与 `anthropic-http` 设为 `False`） |
| `supported_apis` | 类属性，`frozenset`（如 `{"chat"}` 或 `{"chat", "responses"}`） |
| `supported_model_fields` | 类属性，支持的 `ModelSpec` 属性名集合（`id`、`api`、`reasoning_effort`、`timeout`、`watchdog`、`extra`） |
| `extra_allowlist` | 类属性，`frozenset`，必须在类体显式声明（空集拒绝全部 `extra` 键） |
| `invoke` / `close` | 抽象异步方法 |
| `open` | 可选异步方法（默认返回 `None`） |
| `supports_model` | 类方法，在 `lock` 阶段静态校验 `ModelSpec`，不通过则抛出 `ModelConfigError` |
| `bind_model` | 将校验通过的 `ModelSpec` 转换为执行器内部请求参数 |
