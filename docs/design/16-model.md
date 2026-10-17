# 16 — Model

profile 上的 `model` 是一份嵌套 mapping。全仓只有一个 `ModelSpec`。字段表以本页为准。

```python
from ageval.model import ModelConfigError, ModelSpec, require_model_support, resolve_model
from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.errors import PluginContractError
```

`src/ageval/model/` 解析。`src/ageval/plugins/base.py` 是环境与 executor 的基类。`api_key` 与 `base_url` 留在 profile 上，是 locator，不是 Model 字段。

## 字段

`resolve_model(model, options=None)` 只接受嵌套 mapping。字符串 id 拒绝。`options` 里的平铺模型字段（`api`、`reasoning_effort`、`timeout`、`request_timeout`、`watchdog`、`extra_body`）拒绝，不翻译进 Spec。其它 option 键是 executor 旋钮，解析时忽略。

| YAML | Spec 字段 | 类型 | 省略 |
| --- | --- | --- | --- |
| `id` | `id` | `str` | 必填。空串拒绝 |
| `api` | `api` | `str` | `chat`。短名只有 `chat` 与 `responses` |
| `reasoning.effort` | `reasoning_effort` | `str \| None` | 不发送 |
| `timeout` | `timeout` | `float \| None` | Spec 保持 `None`。省略时 executor 读 [`src/ageval/runtime/clocks.py`](../../src/ageval/runtime/clocks.py) 的 `timeout` 行（180）。`0`、负数、非有限值拒绝 |
| `watchdog` | `watchdog` | `float \| None` | Spec 保持 `None`。省略时 executor 读同一张表的 `watchdog` 行（180）。`0`、负数、非有限值拒绝 |
| `extra` | `extra` | mapping | 空 mapping。不并进一等字段 |

`reasoning` 只认 `effort`。`summary` 等放进 `extra`。`none` 是会发送的 effort 值，不是省略。

配置文件写出 `reasoning.effort` 时，用该模型文档里的最高档。常见档名是 `xhigh` 或 `max`。解析器不把档名收成枚举：档名由模型决定。

`extra` 是厂商键，原样保留。这里没有网关名单。`extra` 不能改写一等字段，所以这些键拒绝：`id`、`api`、`timeout`、`watchdog`、`reasoning_effort`，以及 `extra.reasoning.effort`。

哪些 extra 键能进请求，由该 executor 的 `extra_allowlist` 决定。类体必须声明它，空 `frozenset` 表示拒绝全部 extra 键。不认识的 extra 键在校验时 `ModelConfigError`，不丢弃。

已写出、而该 executor 的 `supported_model_fields` 里没有的一等字段，同样 `ModelConfigError`。省略（`None`，或空 `extra`）不算写出。`api` 不在 `supported_apis` 里，也是 `ModelConfigError`。

`require_model_support(spec, *, supported_apis, supported_model_fields, extra_allowlist)` 做上面三项检查。`supports_model` 调用它，再加该 executor 自己的规则。

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

## 错误

| 类型 | 模块 | 何时 |
| --- | --- | --- |
| `PluginContractError` | `ageval.plugins.errors` | 类契约。未声明 `extra_allowlist` / `supported_apis` / `supported_model_fields`；capability 为真但没有对应方法；`requires_environment` 未满足。`kind` 是 `plugin_contract`。它是 `ExtensionRegistryError` 的子类 |
| `ModelConfigError` | `ageval.model` | 畸形 model、不认识的 `api`、不认识的一等字段、extra 键不在 allowlist。`kind` 是 `model_config` |

`ModelConfigError` 是配置错误。lock 失败。它不是传输失败，不进入 upstream stall。

## Lock

`load_and_lock` 在写出 lock 之前做完下面几步。配置错误停在 lock，不进入 upstream stall。

```text
resolve 独占槽赢家
  → resolve_model(profile) → ModelSpec
  → requires_environment 为真：环境赢家必须在，且该 executor 对 environment 的 inject caps 必须由赢家提供
       否则 PluginContractError
  → 赢家是 BaseExecutor 子类：类方法 supports_model(spec)，不构造实例
       api 不在 supported_apis、写出的一等字段不在 supported_model_fields、
       extra 键不在 extra_allowlist（空集拒绝全部）→ ModelConfigError
  → 通过之后才写 lock
```

没有装饰类的外置 executor（plugin.yaml 的 factory，不是 `BaseExecutor` 子类，不能声明 allowlist）：

- 环境变量未设置，且注册 `source` 是 `first-party`：`PluginContractError`
- 环境变量未设置，其他 `source`：`YamlOnlyExecutorWarning`。警告写明第三方 factory 的截止日期尚未公布
- `AGEVAL_STRICT_MODEL_CONTRACT=1`（也接受 `true` / `yes` / `on` / `strict`）：不论 source，`PluginContractError`
- `0` / `false` / `no` / `off`：不论 source，仍是警告

allowlist 在 executor 类上，不在 `ModelSpec` 里。

Current：`resolve_model` 在 profile 解析和 lock 上拒绝字符串 id 与平铺模型键。独占 executor 赢家若是 `BaseExecutor` 子类，lock 调用类方法 `supports_model`，并在 `requires_environment` 未满足时拒绝。一类环境与一类 executor（`local` / `docker` / `e2b` / `ssh` / `daytona` / `acp` / `openai-http` / `anthropic-http`）继承基类并带装饰器。miniswe、nooa、dsh、acp-oneshot 使用同一份 `ModelSpec`，经 `load_installed` 进入，不在 builtin 名单里。仍是普通 factory 的第三方 executor 走上面的警告。

## BaseEnvironment

实现 `EnvironmentProvider`。`capabilities` 用 `ageval.environments.protocol.EnvironmentCapabilities`，不另造一套。

| 成员 | 契约 |
| --- | --- |
| `kind` | 类属性。稳定 id，与今天的赢家相同（`local`、`docker`、`e2b`、`ssh`、`daytona`） |
| `capabilities` | 类属性。布尔矩阵 |
| `python_command` | 类属性。环境内 Python 的 argv 前缀 |
| `preflight` / `start` / `stop` | 抽象。总是要 |
| `placement` / `visible_path` | 抽象。总是要。行为与今天的 Protocol 相同 |
| `exec` / `upload` / `download` / `attach_stdio` | 对应 capability 为真时，子类必须有这个方法。基类不提供默认实现，这样注册期能看出缺方法 |

缺方法的类不能实例化（`TypeError`）。capability 与方法不一致是注册期 `PluginContractError`，不是实例化检查。

## BaseExecutor

每个 executor 继承这一基类。`supports_model` 与 `bind_model` 都是抽象方法。

| 成员 | 契约 |
| --- | --- |
| `kind` | 类属性。稳定 id（如 `openai-http`） |
| `requires_environment` | 类属性。缺省 `True`。不需要环境的 executor（`openai-http`）设 `False` |
| `supported_apis` | 类属性。如 `{"chat"}` 或 `{"chat", "responses"}` |
| `supported_model_fields` | 类属性。Spec 字段名：`id`、`api`、`reasoning_effort`、`timeout`、`watchdog`、`extra` |
| `extra_allowlist` | 类属性。必须在类体声明。空集拒绝全部 extra 键 |
| `invoke` / `close` | 抽象 |
| `open` | 缺省空操作，返回 `None` |
| `supports_model` | 类方法。lock 不构造实例。不能接受就抛 `ModelConfigError` |
| `bind_model` | 把校验过的 Spec 写成内部请求参数。`extra` 只留下 allowlist 里的键 |

未实现的抽象方法不能实例化。

## Hub

Hub 的 `JobOverlayProfile.model` 只写本页的嵌套对象。展示、suite usage、Performance 读 `id`。已存的字符串 id 在再次写出 profile 时收成 `{id}`。`options` 不再携带 `extra_body` 或平铺 `reasoning_effort`。
