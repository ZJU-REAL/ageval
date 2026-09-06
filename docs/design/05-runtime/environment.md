# Environment

独占槽 `environment`。Protocol 在 `src/ageval/environments/protocol.py`，无厂商 SDK。结构总图与 locality 规则见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)。动词与 Placement 形状见 [01](../01-ageval-core.md)。

环境内路径合同：`/attempt/workspace`、`/attempt/home`、`/attempt/artifacts`、`/attempt/evaluation`。

配置文件：

```yaml
# profiles.yaml — 选独占槽 environment 的赢家
format: ageval.profiles/1
environment: e2b    # local | docker | e2b | ssh | daytona
# environment_options:   # docker：image / platform / network / user / egress / egress_allow / python_version
#                        # ssh：host / user / port / key_env / image
#                        # daytona：image / snapshot / timeout_seconds
# evaluate_host:         # 省略 = 同一环境打分
#   isolated: true       # 第二只 EnvironmentProvider；不是新槽
#   environment_options: # 打分盒自己的 docker 旋钮；省略 = 不继承 agent 的 egress / egress_allow / network
#     egress: llm        # network / egress / egress_allow / platform / user / python_version；不是 image（配方照旧）
#     egress_allow:      # 仅 egress: llm：额外 hostname，与该盒 base_url host 并集
#       - registry.npmjs.org
```

取消隔离档产品面。不要写 `provider.kind`、`assurance: l0/l1`。Result 记 `kind` + `capabilities_used`。

## kind 与能力

`requires ∩ capabilities`：task `requires.environment` 缺省为空；非空必须 ⊆ kind.capabilities，否则 lock 失败。不能兑现的 cap 不许报 yes。

| cap | local | docker | e2b | ssh | daytona |
| --- | --- | --- | --- | --- | --- |
| exec / upload / download | yes | yes | yes | yes | yes |
| attach_stdio | 本机进程 | `docker exec -i` | **yes**（SDK 双向 stdin 流；旧 envd 在 start 探针失败） | ssh / 远端 docker exec | **yes**（session stdin + `suppress_input_echo`，泵到 `fileno()`；实现期 ACP `initialize` 握手成功。不是每次 start / `--probe` 再测） |
| uid_gid / path_views | no | yes | 通常 no | 通常 no | no |
| compose | no | yes | no | 视远端而定，默认 no | no |

`path_views` 仅 docker 一类能做 per-actor mount+UID。gold 默认隔离 **不依赖** 它（evaluate 晚上传）。要 compose 而 kind 没有该 cap → lock 失败。

`environment/Dockerfile`（或 `docker_image`）对 docker 与 e2b 是同一配方。docker 本机编；e2b `Template.from_dockerfile` 再 `Sandbox.create`。daytona 把同一配方编成 **snapshot**（`Image.from_dockerfile` 或公开 OCI tag），再 `Sandbox.create` from snapshot。OCI tag 须带具体 tag/digest；Daytona 拒绝 `latest` / `lts` / `stable`。

官方 Attempt 镜像由 `docker/attempt/` 构建，`ARG PYTHON_VERSION` 选基座 CPython（缺省 3.12）。题包 Dockerfile 用 `FROM ageval-attempt:base`；job 声明非缺省 `python_version` 时 docker 插件把该 `FROM` 解析到版本化 tag（如 `ageval-attempt:py3.13`），镜像内容键含 `python_version`，两个版本的本地基座并存、不互相覆盖。题包也可以 `FROM ubuntu:24.04`（或其它发行版）：docker 按配方构建，再叠绑定插件的 `image_layers`。ACP 只 bake lock 的 `options.entry`（钉死包来自 `acp_entries.json`），不改写题包 `FROM`，也不把全部 ACP entry 写进每张题图。官方基座配方仍然有效；叠层在 pin 已存在时幂等。invoke 时禁止 `npm i` / 浮动 `npx`。Python ACP SDK 只在 parent，不进 Attempt 镜像。

docker `environment_options`：

- `image` / `docker_image` — 已有 tag，跳过本机构建
- `platform` — 缺省跟本机
- `network` — 缺省 `bridge`。这是 **原始 docker 网络名**。`none` 也是原始名：它会一并挡住环境内进程访问模型 API，**不是**下面的 LLM egress 模式。
- `egress` — 省略 = 今日 `bridge`。`egress: llm`（Current：仅 docker contrib）：Agent 环境出站 HTTP(S) 只能到达 **有效放行名单**（parent 侧代理 + 环境内 `HTTPS_PROXY` / `HTTP_PROXY`，或等价物）。ACP stdio 仍是 parent `attach_stdio`，不走这条代理。不能兑现的 kind 写了该键 → lock 失败。依赖仍 bake 在题包 `environment/Dockerfile`；官方 Attempt 镜像 invoke 时禁止 `npm i` / 浮动 `npx`。
- `egress_allow` — 仅与同一 map 上的 `egress: llm` 同写。hostname 列表（小写、无 scheme、无 path、无 port；与代理 exact match 同一规范化）。省略 = 只放行绑定 profile 的 `base_url` 主机（今日行为）。空列表 = 不加额外主机。有效名单 = 该盒相关 `base_url` 主机 ∪ 本 map 的 `egress_allow`，去重排序后写入内部 `egress_allowlist`；不另起代理。非 hostname 条目（带 path 的 URL、空串）→ lock 失败。非 docker kind 写了该键、或没有 `egress: llm` → lock 失败。不是新插件，也不是 chain slot。并集为空（`egress: llm` 且没有可解析 `base_url` 主机、也没有 extras）仍按今日规则拒绝启动代理，不静默放开网络。代理 allow/deny 不写 `Result.status`。
- `user` — 环境内身份，`docker run --user` 与 `exec`/`attach_stdio` 同一值。缺省 `10001:10001`。`root` / `0` / `0:0` 开 root（Harbor 式终端题要 `apt` 或写 `/usr/local` 时用）。其它值必须是 `uid` 或 `uid:gid`。未知字符串一次失败。默认仍带 `no-new-privileges`。
- `python_version` — 官方 Attempt 基座的 CPython minor（如 `"3.13"`）；省略 = 3.12。形状 `^\d+\.\d+$`；`latest` / `3` / 空串 / 其它形状一次拒绝。基座 `FROM python:${python_version}-slim-bookworm` 拉不到 → image build 一次失败，**不**回退 3.12。ACP 引擎仍在 build 期 bake，Node / Go 等引擎版本不受此旋钮影响。

`egress` / `egress_allow` 约束的是 **写它们的那只盒子**。两只盒子两份策略：打分 Host 有自己的
`evaluate_host.environment_options`（`network` / `egress` / `egress_allow` / `platform` / `user` /
`python_version`）；
嵌套表省略时打分盒沿用今日行为——只继承 job `environment_options` 的
`platform` / `user` / `python_version`，**不**继承 agent 的 `egress` / `egress_allow` / `network` 或镜像。
打分 `egress: llm` 的放行名单 = evaluate 相位 profile 的 `base_url` 主机 ∪ 打分 map 自己的 `egress_allow`
（judge 盒 reach judge 的 API host 与打分作者列出的额外 host），不是 solver 名单。不能兑现该键的 kind
写了任一处 `egress` / `egress_allow` → lock 失败，同一规则。

## 第二份环境（evaluate，opt-in）

`environment` 独占槽仍一份赢家。`evaluate_host.isolated: true` 时 Runtime 再 `start` **同一个赢家类** 的更多实例：

- 单只配方：题包 `environment/evaluate.Dockerfile`，或 `evaluation.docker_image`。与 Agent 的 `environment/Dockerfile` 不是同一文件。Current 只要求 docker。
- **构造时机：evaluate 相位。** run 密封（`seal_run`）之后才知道哪些 profile 属 evaluate 相位；打分盒实例在 evaluate 相位按 evaluate 相位 graph 联合的 `image_layers` 构造（见 [evaluation.md](evaluation.md)），composition 不再预建。cleanup 只停已构造 / 已启动的实例。
- 名表：成员 `evaluation.environments.<name>.dockerfile` 或 `.docker_image`。每只一个 `BoxSpec.attempt_root`（evidence `eval-box/<name>`）。evaluate 开头不 start；第一次 `exec` / `session(environment=)` 才 start。写出名表则忽略单只配方。
- work root **独立**。禁止把 Agent 的 bind-mount 或 live workspace symlink 进打分环境。
- 不加入 Agent compose 网络。compose 侧车仍随 Agent `host.start()` 起来，寿命与 Agent 环境相同；不要拿侧车当打分镜像。
- **禁止**把 docker daemon socket 挂进 **Agent** 环境。打分环境也不挂 daemon socket。locator 只给 parent 的 docker CLI。
- gold、tree/file 快照只 upload 到 **已 start** 的打分实例。`evaluator.py` 在 parent 跑，连本机 Agent Service socket；不要把该 socket bind-mount 进容器。
- cleanup 停每一只已启动的打分实例再停 Agent 实例（或并行，但都要停）。`keep_workspace` 只保留引擎声明要留的 work root，不得把打分盘并回 Agent 盘。

不能再起第二环境的 kind（Current：`local` 以及尚未兑现的云 kind）遇到 `isolated: true` 或名表 → lock 失败。不要为此发明 cap 名。

## `attach_stdio`

在**已开的环境**里再起一个前台进程，把 stdin/stdout 交回 parent。ACP 只拿 `StdioTransport`，不写 `if docker`。

| 赢家 | `attach_stdio(argv)` 内部 |
| --- | --- |
| local | 本机 `Popen(argv)` |
| docker | `Popen(["docker","exec","-i", …, *argv])`（旧 `wrap_docker_exec` 缩进此插件） |
| ssh **A** 环境=整机 | `Popen(["ssh","-T", …, "--", *argv])`，agent 就是这台 VM 上的进程 |
| ssh **B** 环境=远端容器 | `start()` 远端 `docker run` 已有 tag；`attach_stdio` = `ssh -- docker exec -i <cid> argv` |
| e2b | SDK 双向流（`stdin=True` + send stdin）。只跑完收 stdout 不够 ACP |
| daytona | **yes**。`create_session` + async session command + `send_session_command_input`（`suppress_input_echo`），stdout 用 HTTP logs 泵到 `os.pipe()`。未回退 PTY。kind 常量，之后不再探测 |

两种 ssh **agent 都在云上**。差别是隔离单元：整机 vs 机上容器。options：无 `image` → A；有已有 tag → B。`stop(delete=False)` 默认不 terminate 云主机。密钥 locator 不进 lock。

缺 `E2B_API_KEY` / `DAYTONA_API_KEY` / ssh locator：preflight 一次失败，不建 sandbox、不开远端容器。`--probe` 必须 `ready: false` 且未 start。`--probe` **不**发现 stdio。

E2B 模板 alias/hash 只在 `plugins/contrib/e2b`。Daytona snapshot 名 / sandbox id 只在 `plugins/contrib/daytona`。Core 只调 `host.start()`。

## daytona

独占赢家 `plugin_id: daytona`，first-party，与 e2b 同 locality。厂商 SDK 不得漏进 ACP / `attempt` / `run.py`。

Locator：`DAYTONA_API_KEY`（接受 `daytona_api_key`）。缺钥或缺 SDK import → 一次 `environment_preflight_failed`。

`environment_options`：

- `snapshot` — 已有 Daytona snapshot 名，跳过编 snapshot
- `image` — 公开 OCI tag/digest（禁止 `latest` / `lts` / `stable`）
- `timeout_seconds` — sandbox 寿命（映射 Daytona `auto_stop_interval`，分钟向上取整；默认 900）

无 `snapshot` 时：有 `image` 则 snapshot-from-OCI；否则用题包 `environment/Dockerfile`（`Image.from_dockerfile`）。snapshot 名按配方 digest 复用。环境内路径仍是 `/attempt/workspace` 等。

`attach_stdio` 是 kind 常量，与 e2b 一样。实现期用真钥在 session stdin 上完成 ACP `initialize`（echo fixture，干净 JSON，无 TTY echo）。因此 `executor: acp` + `environment: daytona` lock 成功。缺钥的 skip 不是这条 cap 的证据。

## ssh A / B

ssh A / B 由 `environment_options.image` 是否为空决定。host/user/`key_env` 是 locator，preflight 解析，不进 lock 明文密钥。

ACP 挂 `after_environment_ready`：名字 + 钉死包版本 + 一次 stdio `initialize`。docker bake 已匹配 pin + stdio `initialize` 时跳过 `install_command`；不对再按 ACP entry 的 `install_command` 装。云镜像 / 官方基座已 bake 且版本/协议对得上时探测命中，不得再装一遍。同名但不是 stdio ACP 的二进制不算命中。

## locality

executor **inject** 名为 `environment` 的服务（独占赢家自动 export 该名），lock 时核 capabilities。`executor: acp` 要 `attach_stdio`；环境内 worker（dsh / nooa / `acp-oneshot`）要 `exec`。调用只打 Protocol 方法。`exec` 不是独立 service。

```text
ACP / acp-oneshot / dsh / nooa  invoke
        │  inject service: environment
        │  只看见 Protocol（attach_stdio / exec / upload）
        ▼
contrib/docker   → docker exec / compose / uid_gid / path_views
contrib/e2b      → e2b SDK、template alias
contrib/daytona  → Daytona SDK、snapshot 名、sandbox id
contrib/ssh      → ssh A/B、远端 docker
contrib/local    → 本机目录
```

`docker exec` 只在 `plugins/contrib/docker/`。ACP 禁止 import docker/e2b/daytona/ssh。`attempt` / `run.py` 不见 `container_id`、不见 `if kind == e2b`。换 kind 不必改 executor 源码。

`run.py` 是 parent 子进程。seed 在 launch 投影到 `ctx.workspace_root`（local/docker 即共享盘；ssh/e2b/daytona 是 evidence 上的 seed 拷贝）。Agent Service **不**在每次 invoke 后 `download` workspace。writer 停后 runtime 按题包 `artifacts.publishable` harvest **一次**：`kind` 省略/`file` 收缺的单文件（环境内 `/attempt/workspace/<basename>` → parent `task-artifacts/`）；`kind: tree` 按 `exclude` 把工作区树拷成 evidence 上的不可变快照。共享盘上 `run.py` 已从磁盘 `publish_json` 的 file 跳过；远程环境走 Protocol `download`。tree 在 docker 上读已有 bind-mount 再拷，不要三次 export。搬哪些由题包声明，不写 `if kind`。聊天文本不是 Terminal 类题的权威产物，不得 publish 成功并挡住 harvest。evaluate 消费快照拷贝，不是 Agent 活目录。

## setup.sh 与侧车

`setup.sh` 是 environment **末槽** `environment_setup`，不是独立 provision phase。无文件则 no-op。失败是 environment 相位失败。重依赖进 Dockerfile，不要在 `run.py` 里 `apt`。

侧车：拆掉 Environment Manager。compose 或 `host.exec(service=)`。`run.py` 读投影 DSN。旧 `setup_steps` 废止。

## Current vs Target

| 项 | Current | Target（未宣称完成） |
| --- | --- | --- |
| local / docker | 公开真 `ageval run`（core ACP、`minimal-demo` 明确列出的示例） | — |
| e2b / ssh / daytona | 代码在；缺钥则 `--probe` 过不了，不能进入运行 | 有凭证时同一题公开 `ageval run`（ssh 含 A+B） |
| Protocol seam | docker 已是真实赢家 | 第二个云赢家（e2b **或** ssh）真跑后 seam 才算成立 |

默认 CI **无**真 E2B/SSH/Daytona。没跑不要标完成。不得从 docker 一次 PASS 推导 `isolated`。
