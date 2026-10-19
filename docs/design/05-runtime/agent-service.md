# Agent Service / ACP

Coding agent 支持两条执行器接入路径，均实现 `executor` 独占槽。每个角色的 `agent_profiles.<role>` 独立绑定自身的 `executor` 实现（例如同一 Attempt 中 `solver` 可使用 `executor: acp`，`judge` 可使用 `executor: openai-http`），`lock.extension_bindings` 按角色 ID 分别记录绑定关系。

| 执行器 | JSON-RPC 客户端位置 | 所需环境能力 | 完成判定信号 |
| --- | --- | --- | --- |
| `executor: acp` | **宿主父进程**唯一 ACP 客户端（经 `attach_stdio` 双向流） | `attach_stdio` | ACP 协议帧（`stopReason`） |
| `executor: acp-oneshot` | **环境内部**单次包装器进程 + ACP 服务端 | `exec` | 包装器子进程退出 |

`executor: acp` 的核心实现位于 `src/ageval/runtime/parent_agent.py` 与 `src/ageval/plugins/contrib/acp/`。

## `executor: acp`（父进程客户端）

```yaml
# profiles.yaml
environment: docker
agent_profiles:
  solver:
    executor: acp
    model: …
    api_key: ${ZHIPU_API_KEY}   # 环境变量名引用；明文不写入 lock
    options:
      entry: pi                 # pi | codex | claude-code | opencode | grok-build
    extensions:
      - plugin: acp
      - plugin: docker
```

ACP 插件通过 `inject: [service: environment]` 声明依赖具备 `attach_stdio` 能力的环境服务；若所选环境不提供 `attach_stdio`，`ageval lock` 在运行前直接报错。

```python
host = ctx.services.require("environment")
pipe = await host.attach_stdio(argv, placement=placement, env=child_env)
# JSON-RPC 通信通过 pipe.stdin / pipe.stdout 进行
```

切换不同的 coding agent 仅需修改 `options.entry`，不应写成 `executor: pi` 或 `executor: codex`。

## `executor: acp-oneshot`（环境内单次客户端）

`acp-oneshot` 为外置插件包（`plugins/acp-oneshot`），仅要求环境提供 `exec` 能力：

```yaml
environment: docker
agent_profiles:
  solver:
    executor: acp-oneshot
    options:
      entry: pi
    extensions: [acp-oneshot, docker]
```

每次 `invoke` 通过一次 `host.exec` 在环境内启动包装器脚本，由包装器在环境内拉起对应 `entry` 的 ACP stdio 服务端并顺序完成 `initialize`、`session/new` 与 `session/prompt`，默认不跨调用复用会话；结束后由 `trajectory_collect` 将事件映射为标准轨迹格式。

## 调用流程与上游重试等待（Upstream Stall）

```text
run.py / evaluator.py  Agent.session(profile).invoke
  → Unix socket (AGEVAL_AGENT_SERVICE_SOCK)
  → ParentAgentService
       before_agent_invoke（单次调用仅触发一次）
       executor.invoke → host.attach_stdio(entry argv) 或 host.exec（环境内 worker）
                        或 openai-http / anthropic-http 请求
       若返回非 ok 且可重试 → 进入 upstream_stall（暂停当前阶段计时器，每 60 秒重试一次）
       after_agent_invoke（最终结果触发一次）
       normalize_agent_result
  → 轨迹记录：run 阶段写入 trajectory.jsonl；evaluate 阶段写入 evaluation/observation.jsonl（省略 user 提示行）
```

当 `executor.invoke` 返回可重试的传输错误时，`ParentAgentService` 进入 `upstream_stall` 等待重试（详细规则见 [07](../07-budget-evaluation-failure.md)）：
- 等待预算由 `options.upstream_stall_seconds` 控制（默认读取 `clocks.py` 中的 `3600` 秒；设为 `0` 时禁用重试），重试间隔固定为 `60` 秒，且同一次 `invoke` 的重试不重复扣减 `agent_invocations` 配额。
- 等待期间暂停 `run` 阶段的 `wall_time_seconds`（或 `evaluate` 阶段的 `evaluate_seconds`）计时器。
- HTTP 执行器除 `408` 与 `429` 外的 `4xx` 响应属于不可重试的 `ModelConfigError`；ACP 执行器仅在当前 prompt 尚未修改工作区时允许在同一会话上重发。

## 多会话并发调度

`ParentAgentService` 的 socket 接收循环采用异步并发分发：
- `run` 阶段的每次调用依次经过 `admitted → queued → running → terminal` 四个状态；`limits.agent_invocations` 在即将执行 `executor.invoke` 时原子扣减一次（排队期间被取消不扣减）。
- `limits.agent_concurrency`（默认 `1`）限制同时处于 `running` 状态的 `run` 阶段调用数。同一会话内的调用按到达顺序串行；不同会话的调用可在支持并发的执行器（声明了 `concurrent_sessions` 的 `openai-http` 与 `acp`）上并发重叠，直至达到 `agent_concurrency` 上限。未声明并发支持的执行器在发生重叠调用前直接拒绝并返回 `executor_not_concurrent`。
- 取消操作通过 `op: cancel`（携带 `request_id`）发送至父进程：父进程移除排队项，或通知执行器终止当前调用（如 ACP 发送 `session/cancel` 并关闭对应进程），待调用进入 `terminal` 状态后返回。
- `run` 阶段结束时，`seal_run` 拒绝新的 solver 调用、移除排队项并取消及排干所有在途 solver 调用，随后标记 `mark_writers_stopped`。`ParentAgentService` 保持运行，供 `evaluate` 阶段的 `judge` 角色串行调用（`judge` 调用不占用 `agent_concurrency` 与 `agent_invocations`）。

## `evaluate` 阶段的环境绑定

当启用 `evaluate_host.isolated: true` 时，`evaluator.py` 仍在父进程子进程中运行并通过本机 Unix socket 连接 `ParentAgentService`；`evaluate` 阶段新开启的角色（如 `judge`）会将环境服务绑定至独立评分容器（若声明了 `evaluation.environments` 命名评分容器表，ACP 角色必须通过 `session(profile_id, environment=<name>)` 指定目标评分容器，并在该容器启动后执行一次 `after_environment_ready` 探测）。

## `openai-http` 与 `anthropic-http` 原生工具调用

- **`openai-http`：** 支持 `api: chat`（`/chat/completions`，顶层 `reasoning_effort`）与 `api: responses`（`/responses`，嵌套 `reasoning.effort` 及扁平函数工具格式），绝不在失败时从 `responses` 隐式回退至 `chat`。
- **`anthropic-http`：** 独立实现 Anthropic Messages API（`POST /messages`，使用 `x-api-key` 与 `anthropic-version` 请求头），仅支持 `api: chat`，将 SDK 的 OpenAI 格式 `tools` 与 `messages` 转换为 Anthropic `input_schema`、`tool_use` 与 `tool_result` 块，并支持 `model.extra.thinking`。
- **Token 与费用记录（`usage`）：** 每次调用的 `AgentResult.usage` 与轨迹 `terminal.usage` 记录标准字段 `prompt_tokens`、`completion_tokens`、`cached_tokens` 与 `cost_usd`（仅在后端实际报告时写入；未报告、超时丢失、解析失败或仅部分返回时标记 `unavailable` 原因：`not_reported` / `lost_on_timeout` / `parse_failed` / `partial`，绝不虚构为 `0`）。厂商附加统计信息保存在同级 `extra` 字段中。若 ACP 入口未直接返回一等 usage 但声明了 `usage_journal`，执行器会从 Attempt `$HOME` 下的会话日志累加对应指标。

## 凭据管理（BYOK / BYOA）与 Loopback 规则

| 模式 | 含义 | 缺失时行为 |
| --- | --- | --- |
| **BYOK** | 将声明的 API 密钥环境变量（`credential_env_names` 或 profile `api_key` 引用）按白名单注入子进程环境 | 预检或调用直接报错终止 |
| **BYOA** | `keyless_auth`：按白名单将本机订阅登录凭据复制到 Attempt `$HOME`（不直接挂载宿主机整个 `$HOME`） | 仅输出警告 |

对于 HTTP 类执行器（`openai-http`、`anthropic-http`、`dsh`、`nooa`、`miniswe`），当锁定的 `base_url` 主机名为本机回环地址（`127.0.0.1`、`localhost` 或 `::1`）时，允许省略 `api_key` 或对应的环境变量值为空。

## ACP 运行时配置覆盖与探测（`after_environment_ready`）

运行时 ACP entry 表由包内 `acp_entries.json` 与可选的 `$AGEVAL_HOME/acp-entries.json` 合并而成（包内内置 ID 不可被覆盖）。在环境启动后、`attach_stdio` 之前：
1. **生成运行时配置覆盖文件：** 在 Attempt `$HOME` 下按 `entry` 生成对应的配置文件（如 Pi 的 `.pi/agent/models.json`、OpenCode 的 `.config/opencode/opencode.json`、Codex 的 `.codex/config.toml`、Claude Code 的 `.claude/settings.json`），其中仅写入环境变量引用或已解析的 `base_url`，不写入明文密钥，也不拷贝宿主机个人目录配置。
2. **版本与路径探测：** 通过 `host.exec` 核对全局 npm 包版本（`npm ls -g --depth=0`）与必需命令的 `realpath`，随后执行一次 stdio JSON-RPC `initialize` 握手。若三项均通过（如已在构建期写入镜像），则跳过安装；若版本或路径不匹配，则执行一次该 entry 的 `install_command` 并再次探测，仍不满足则以 `acp_runtime_install_failed` 或 `acp_runtime_missing` 终止 `environment` 阶段。
