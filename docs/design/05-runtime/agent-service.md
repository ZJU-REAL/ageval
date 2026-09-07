# Agent Service / ACP

两条 **独立** 的 coding-agent inlet，都占独占槽 `executor`。不要把第二条折进 ACP 插件，也不要写成 `executor: pi` / `executor: claude`。

`executor` 的独占赢家是 **每个 `agent_profiles` 一行一份**，不是 Attempt 上只许一个机制。同一 Attempt：solver 可以 `executor: acp`，judge 可以 `executor: openai-http`。`environment` 仍是 Attempt 级一份。两个插件仍不得抢**同一 profile graph** 上的 `executor`。lock 的 `extension_bindings` 按 profile id 各记一份。

| 赢家 | JSON-RPC client 在哪 | 环境 cap | 完成信号 |
| --- | --- | --- | --- |
| `executor: acp` | **parent 唯一** ACP client（`attach_stdio` 管子） | `attach_stdio` | ACP 帧（`stopReason`） |
| `executor: acp-oneshot` | **环境内** 一次性 client + ACP server | `exec` only | wrapper 进程退出 |

`executor: acp` 的规则不变：parent 是这条路径上**唯一**的 ACP JSON-RPC client。实现：`src/ageval/runtime/parent_agent.py` + `plugins/contrib/acp/`。结构约束见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)。

## `executor: acp`（parent client）

```yaml
# profiles.yaml
environment: docker
agent_profiles:
  solver:
    executor: acp
    model: …
    api_key: ${ZHIPU_API_KEY}   # locator；值不进 lock
    options:
      entry: pi   # 或 codex / claude-code / opencode / grok-build
    extensions:
      - plugin: acp
      - plugin: docker   # 与 environment 赢家一致
```

ACP `inject: [service: environment]`（按服务名拿 host，**不**绑 `plugin_id: e2b`），要求 capability `attach_stdio`。缺则 lock 失败，不要等到 invoke 才检查 attach_stdio。这是稳定接口：docker / e2b / ssh / daytona 都登记为同一个服务名；内部运输收在 `attach_stdio` 里。`exec` 是同一服务上的另一个方法（环境内一次性命令），不是第二 service。dsh / nooa inject `exec` / `upload`；`acp-oneshot` 只要 `exec`。三者都经 `host.exec` 跑环境内 worker，不得在 parent 里假定本机 POSIX 路径。环境没有 `attach_stdio` 时 **`executor: acp` 仍 lock 失败**；改走 `acp-oneshot`（或其它 exec 赢家），不是给 ACP 插件加 fallback。

```python
host = ctx.services.require("environment")
pipe = await host.attach_stdio(argv, placement=placement, env=child_env)
# JSON-RPC 走 pipe.stdin / pipe.stdout
```

Placement 无 `container_id`。ACP 禁止 import docker / e2b / daytona / ssh。`wrap_docker_exec` 缩进 docker 插件。`run_attempt` 也会把赢家放进 `ctx.host`；inject 是 lock 时的依赖声明。

不要写 `executor: pi` / `executor: codex`。entry 是 ACP / oneshot 的 `options.entry`，不是独占槽赢家。

## `executor: acp-oneshot`（环境内 oneshot client）

外置 `ageval.plugin/1`，`plugin_id: acp-oneshot`（机制名，不是产品名）。模式同 `plugins/miniswe/` / `plugins/dsh/`：parent 只 `host.exec`，不 `attach_stdio`。

```yaml
environment: docker   # 或任何声明 exec 的 kind
agent_profiles:
  solver:
    executor: acp-oneshot
    options:
      entry: pi   # 或 claude-code / opencode / …；与 ACP 同一组 id
    extensions: [acp-oneshot, docker]
```

1. `inject: { service: environment, capabilities: [exec] }`。缺 `exec` 则 lock 失败。**不要** `attach_stdio`。
2. 一次 `invoke` = 一次 `host.exec`。parent 把 entry 的 `acp_command`（来自 ACP entry 表）、prompt、cwd、模型绑定交给环境内 wrapper；等进程退出后解析 `AgentResult`。
3. wrapper 在环境内 spawn 该 entry 的 ACP stdio server，自己当一次性 client：`initialize` → `session/new` → `session/prompt`，permission RPC 与 `stopReason` 都留在环境内。默认 **不** 跨 `invoke` 复用 session。
4. `trajectory_collect` 映射 wrapper 写出的事件。Core **不** 刮 vendor CLI 日志。
5. entry 表与 ACP 共用 id（pi / claude-code / opencode / …）；本插件的 `execution_mode` 是 oneshot wrap，不是 `acp-stdio`。切厂商只改 `options.entry`。
6. 笛卡尔积：任何报 `exec` 的环境（docker / ssh B / e2b / 只提供 exec 的云 kind）。`executor: acp` 在没有 `attach_stdio` 的环境上仍然 lock 失败。

环境内 wrapper 是 stdlib JSON-RPC，**不是** 把 Python ACP SDK 装进 Attempt 镜像。SDK 仍只在 parent，且只服务 `executor: acp`。

无新 CLI flag。凭证仍是 locator，投影进 **exec** env（与 ACP 同一套 BYOK，不是 attach 管子）。空 job / 未装此插件 = 现行为。

## 调用链

```text
run.py / evaluator.py  Agent.session(profile).invoke
  → unix socket AGEVAL_AGENT_SERVICE_SOCK
  → ParentAgentService
       按该 profile 的 executor 赢家 invoke
       before_agent_invoke
       executor.invoke → host.attach_stdio(entry argv) 或 host.exec（环境内 worker）
                        或 openai-http POST /chat/completions
                        或 anthropic-http POST /messages
       after_agent_invoke
       normalize_agent_result
  → 轨迹文件：run 相位 → trajectory.jsonl
           evaluate 相位 → evaluation/observation.jsonl（省略 user）
```

`ParentAgentService.invoke` 只回 `AgentResult`（含可选 `tool_calls`）。**不**在每次 invoke 后 `download` 环境内 workspace。轨迹来自 executor events。publishable 在 **solver writer 停后** 由 run 相位 harvest 一次（Protocol `download`；tree 按 exclude 做快照），evaluate 再把快照 upload 进 **打分 Host**。

Agent Service **跨 evaluate 保持**（或 reopen）：`evaluator.py` 才能 `Agent.session`。run 结束停的是 **solver writer**（该相位已打开的 profile 不得再 invoke），不是把整段服务拆掉再打分。gold 已经在打分 Host；solver 不得在 gold 之后 invoke。Attempt 结束（cleanup / `run_attempt` finally）才停服务。

## evaluate 相位的 attach 目标与环境内 socket

`executor: acp` 仍 `inject: [service: environment]`，parent 仍是唯一 JSON-RPC client。缺省（同一环境）attach 目标就是 run 那只 Host，与今日相同。

`evaluate_host.isolated: true` 时：

- `evaluator.py` 与 `run.py` 一样是 **parent 子进程**。`AGEVAL_AGENT_SERVICE_SOCK` 是本机 unix 路径，不 bind-mount 进容器。
- evaluate 相位的 `Agent.session`（judge 等 **未** 在 run 用过的 profile）走同一 Parent Agent Service。ACP `attach_stdio` 打 **打分 Host**（environment 服务 rebound 到当时的打分实例），不是 Agent Host。solver 仍密封。
- 有 `evaluation.environments` 时，`session(profile_id, environment=<name>)` 只在 evaluate 相位（`seal_run` 之后）把 environment 服务绑到那只命名 Host（懒 start + **对该 profile** 跑 `after_environment_ready`）。未知名、run 相位点名、或 ACP 省略名字一次失败，不 start。省略 `environment=` = 无名表时的那只打分 Host。`openai-http` / `anthropic-http` 忽略 `environment=`。
- isolated 打分环境 start 之后，对上述 ACP profile 再跑 `after_environment_ready`（probe；bake 已匹配则跳过 `install_command`）。不要把 solver 的 ACP 配方装进打分镜像。
- Agent 容器 **没有** docker daemon socket。ACP / `attempt` / `run.py` 仍然不见 `container_id`。

observe 这些 invoke：`evaluation/observation.jsonl`（省略 `user` 行）。不是 PASS。

ACP attach 发生在第一次 invoke，不是独立 phase。`acp-oneshot` 每次 invoke 都 exec 一次 wrapper，完成 = 该进程退出码 + 解析出的 `AgentResult`。Harness completed / 轨迹 / judge 输出 **不是** PASS。

Socket 帧可带 `tools` / `messages`（省略 = prompt-only）。parent 原样转给 executor；ACP 忽略这两项。`tool_calls` 回 worker。request.json / trajectory **只记 locator 与目录名，不记密钥**。

## openai-http 原生 tools

kind 名仍是 `openai-http`（api-client，Chat Completions）。**不要**在这个 kind 里加 Anthropic dialect 开关。Core 没有 LiteLLM。DashScope 等 OpenAI 兼容口、以及 Anthropic 官方的 OpenAI 兼容层，仍走 `openai-http`。Anthropic Messages（`POST /messages`、`x-api-key`、`tool_use` 块）是另一独占赢家 `anthropic-http`。

| | 行为 |
| --- | --- |
| 省略 `tools` | 今日路径：`messages: [{role: user, content: prompt}]`，读 `choices[0].message.content` |
| 题包传入 `tools` | POST body 带 `tools`；读 `choices[0].message.tool_calls` → `AgentResult.tool_calls` |
| `messages` | 若提供，作为 chat 历史（不再只包一轮 prompt） |
| capability | `tools: native`，`session: new-only`（逻辑 session，无 provider resume） |
| 凭证 | 一等字段 `model` / `base_url` / `api_key`（env locator）。远程 URL 缺钥则不能进入运行。loopback 空钥是 **HTTP executor 规则**（`openai-http` / `anthropic-http` / `dsh` / `nooa` / `miniswe`），不是 openai-http 特例 |
| `options.reasoning_effort` | 可选。有值则写入 Chat Completions 的 `reasoning_effort`；缺省不发该键。evidence：`locked_reasoning_effort` / `actual_reasoning_effort`（HTTP 200 时二者相同；4xx 时 actual 为 null） |
| `options.extra_body` | 可选 mapping，原样 merge 进 Chat Completions JSON（在 `reasoning_effort` 之后，撞键 extra_body 赢）。省略 / 空 = 不发。非 mapping 则拒绝。拒绝 `model` / `api_key` / `messages` / `tools`。Core 不翻译厂商字段。 |

tau2-class harness（`minimal-demo` 的 `tau2-dialog-min`、`examples/datasets/tau3-*`）把域 schema 传入 invoke；收到 `tool_calls` 后走 package `Environment.get_response` / `ToolSet.call`，再 `record_observation` 把回包挂到该 invoke。原生 `tool_calls` 是 **HTTP api-client 的主动作通道**（`openai-http` / `anthropic-http`）；「Return ONLY JSON」只留给没有 `tool_calls` 的文本 executor（ACP）。禁止在 Core 里 scrape vendor stdout 当工具通道。

`openai-http` 的 executor events 用 Core 合同：`kind: tool` + `phase: start` + `tool_call_id` / `function_name` / `args`。环境观察是 `phase: update`（source `ageval`），不是 HTTP 响应的一部分。

`AgentResult.usage` 与轨迹文件 `terminal.usage` 同一形状（见 [evidence.md](evidence.md)）：一等 `prompt_tokens` / `completion_tokens` / `cached_tokens` / `cost_usd`（未知省略）。厂商 leftover 与插件袋在兄弟字段 `extra`。`openai-http` 从 Chat Completions `usage` 映射；`anthropic-http` 从 Messages `usage` 映射；ACP 从 `PromptResponse.usage` + `usage_update` 映射。缺 usage 就省略，不编造。usage / extra 是观察，不是 PASS。

## anthropic-http 原生 tools

kind 名是 `anthropic-http`（api-client，Anthropic Messages）。与 `openai-http` **并列**的独占 `executor` 赢家，不是它的 dialect。SDK `tools=` / `messages=` 仍是 OpenAI 形（见 [03](../03-task-run-and-sdk.md)）；翻译发生在 **这个 executor 边界**，Core 不翻译。

| | 行为 |
| --- | --- |
| 路径 | `POST {base_url}/messages`（默认 `https://api.anthropic.com/v1`） |
| 鉴权 | `x-api-key` + `anthropic-version`（默认 `2023-06-01`）。不用 Chat Completions 的 `Authorization: Bearer` |
| 省略 `tools` | `messages` 仅 user/assistant；`system` / `developer` 提到顶栏 `system`；读 `content[]` 里的 `text` |
| 题包传入 `tools` | 译成 Anthropic `tools[].input_schema`；读 `content[]` 里的 `tool_use` → `AgentResult.tool_calls` |
| `messages` | OpenAI 形历史：`tool_calls` → `tool_use` 块；role `tool` → `tool_result`（可合并连续条） |
| capability | `tools: native`，`session: new-only`，`execution_mode: api-client` |
| 凭证 | 同 HTTP executor 规则。`api_key` 缺省 locator `ANTHROPIC_API_KEY`。loopback 空钥省略 `x-api-key` |
| `options.max_tokens` | 必发。缺省 `4096`。非正整数则拒绝 |
| `options.anthropic_version` | 请求头。缺省 `2023-06-01`。非字符串则拒绝 |
| `options.extra_body` | 原样 merge 进 Messages JSON（在一等字段之后，撞键 extra_body 赢）。thinking / cache 等厂商键走这里。拒绝 `model` / `api_key` / `messages` / `tools` / `system` / `max_tokens` |

`thinking` 块映成 thought 事件（`channel: thought`）。events 合同与 openai-http 相同（`source: anthropic-http`）。

官方 Anthropic 的 OpenAI 兼容口（同一把 `ANTHROPIC_API_KEY` + `base_url: https://api.anthropic.com/v1` 打 `/chat/completions`）继续用 `openai-http`。只有 Messages 的端点、以及要 thinking 块 / prompt cache 原生字段时，用 `anthropic-http`。

## 凭证：BYOK / BYOA

两条，都不是整份 `os.environ`：

| | 含义 | 缺则 |
| --- | --- | --- |
| **BYOK** | 声明过的 API key env（`credential_env_names` / binding `api_key` locator）投影进环境 | 缺钥则不能进入运行 |
| **BYOA** | `keyless_auth`：allowlist copy 本机订阅 auth 文件进 attempt HOME，**不** mount 宿主 `$HOME` | 仅警告（OAuth / 本机登录 entry） |

子进程环境只投影 allowlist（`PATH` / `HOME` / `LANG`、entry 声明的 credential 名、binding 的 `api_key` / `base_url`、`fixed_env`）。宿主里未声明的 token 进不了 entry。

`--probe` / `ageval executors -v`：`credential_missing` 在需要密钥的 entry 上过不了检查就不能进入运行；keyless 只警告。HTTP executor 在锁定 `base_url` 为 loopback 且钥省略 / locator 为空时 **不** 报 `credential_missing`。

### HTTP loopback 空钥

`openai-http` / `anthropic-http` / `dsh` / `nooa` / `miniswe` 共用一条 host-only 判断（`src/ageval/plugins/http_loopback.py`）：host 仅为 `127.0.0.1` / `localhost` / `::1`。不含 RFC1918、不含名字里碰巧带这些子串的 URL。

- loopback 且 `api_key` 省略或 locator env 为空 → invoke 继续（空 `Authorization` 或按该协议省略头）。
- 非 loopback 缺钥 → 仍不能进入运行。
- 不改 lock schema；locator **值**不进 lock / overlay / trajectory。ACP / `keyless_auth` 不动。

## Agent 运行时（挂 `after_environment_ready`）

0. **lock overlay（Attempt HOME，不拷宿主）。** lock 已有 `model` / `api_key` locator / 可选 `base_url`。箱子 `start` 之后、`attach_stdio` 之前，ACP contrib 按 **entry** 写成该引擎自己的配置文件（Pi：`.pi/agent/models.json` + `settings.json`；OpenCode：`.config/opencode/opencode.json`；Codex：`.codex/config.toml`（Attempt 已隔离，写 `sandbox_mode = danger-full-access`，禁止再套一层 bwrap）；Claude Code：`.claude/settings.json`）。`entry-default` 不写。locator **值**不进文件（Pi `$ENV`、OpenCode `{env:NAME}`）。**禁止**从宿主 `~/.pi` / `~/.config` 拷 catalog。local / docker / e2b 同一条 Attempt HOME。Claude Code 同时把 lock 的 `model` 投影进 attach env（`ANTHROPIC_MODEL`；有 `base_url` 时再写 `ANTHROPIC_DEFAULT_*` / `CLAUDE_CODE_SUBAGENT_MODEL`）。Codex ACP 默认 `workspace-write`（bwrap）；Attempt 里投影 `INITIAL_AGENT_MODE=agent-full-access`，并写 `.codex/models.json` + `model_catalog_json`（slug 等于 `model`）。grok-build 仍 argv `--model`。
1. 读 `options.entry`（如 `pi`）→ 需要哪些环境内二进制（`pi`、`pi-acp`、…）以及 entry 表钉死的包版本。
2. `host.exec` 探测三件事：名字（`which`）、钉死的 npm 包版本（`npm ls -g pkg@pin`）、一次便宜的 stdio JSON-RPC `initialize`（不是 `session/prompt`）。同名但协议不是 stdio ACP（例如只开 TCP 的旧 `opencode`）算未命中。
3. **三件都齐就跳过。** docker 上题包配方已叠 ACP `image_layers`、且 pin + stdio `initialize` 命中时，不跑 `install_command`。local / 未 bake 的云 snapshot 等面，任一不对再按 **ACP entry 自己的** `install_command` `exec`，装完再探一次。失败 = environment 相位失败。不把「怎么装 opencode」下放到 environment 插件。invoke 禁止把 `npm i` / 浮动 `npx` 当 happy path。
4. 不把安装写进 task `setup.sh`。`setup.sh` 只本题依赖。
5. **build 期 bake（docker）。** ACP 插件声明 `config.image_layers`（`docker/Dockerfile.bake`），合同与 miniswe / dsh / nooa 相同：`ARG BASE_IMAGE` / `FROM ${BASE_IMAGE}`，缺 Node 才装 Node，再 `npm install -g` lock 绑定 `options.entry` 在 `acp_entries.json` 里钉死的 engine + ACP 包。只 bake **当前绑定的 entry**，不把五份 entry 写进每张题图。内容键已含插件层正文（`src/ageval/plugins/contrib/docker/images.py`）：同配方 + 同 entry + 同 platform 复用；同配方换 entry → 新层；换 `model` 不进内容键。题包已 `FROM ageval-attempt:base` 时叠层幂等（pin 已在基座则同 pin）。无浮动 `npx`。

Python ACP SDK 只在 parent，不进 Attempt 镜像。

厂商私有格式翻译在进程外 ACP entry（Mode 1 shim / Mode 2 原生 / Mode 3 厂商包）。禁止在 Core 里再写 vendor stdout scrape。

batch 默认 auto-approve，不提权、不突破未投影路径。decision 进 evidence。

Pi：官方 registry `pi-acp`（npm `pi-acp`，桥 `pi --mode rpc`）。勿与反向桥 `pi-shell-acp` 混淆。

官方 Attempt 镜像 `src/ageval/plugins/contrib/docker/attempt/` 在 **build 期** 写入镜像 最低 entry 的 engine + ACP 入口（Mode 1 同时装 engine 和 adapter：codex/claude/**pi** + 各自 adapter）。配方随 CLI wheel 分发；`ageval run` 从包内路径构建。题包配方不是这份基座时（例如 `FROM ubuntu:24.04`），由 ACP `image_layers` 在题图上再 bake **绑定的** `options.entry`；不要为此改写题包 `FROM`，也不要在 invoke 后再 `npm i`。
