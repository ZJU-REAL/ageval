# Evaluation

writer 必须先停。然后把 gold 与产物送进 **打分 Host**。`evaluator.py` 是 **parent 子进程**（与 `run.py` 同一形态）：控制面不 `import evaluator`，经进程边界调用。`Agent.session` 走本机 Parent Agent Service unix socket；evaluate 相位的 ACP `attach_stdio` 打打分 Host。禁止把 evaluator 再 `host.exec` 进环境再让它 `connect()` 一根挂进去的 socket。

打分 Host 缺省就是 run 那份环境。job `evaluate_host.isolated: true` 时是 **同一** EnvironmentProvider 赢家的更多实例（同 kind、不同配方、不同 work root），不是新独占槽。省略 `evaluation.environments` = 一只；写出 = 按名懒启动，互不共享 work root。

实现：`src/ageval/evaluation/package_evaluator.py` + `src/ageval/runtime/eval_worker.py` + `bind.py`。相位代码：`src/ageval/attempt/phases/evaluate.py`。harvest：`src/ageval/attempt/artifact_harvest.py`。

```text
run 结束 → 停 solver writer（run 相位已打开的 session 不得再 invoke）
         → Agent Service 保持（或 reopen）到 evaluate 结束
         → harvest 一次：file 缺的从环境内 /attempt/workspace/<basename>
           download 到 evidence/task-artifacts；tree 按 exclude 做成不可变快照
evaluate
  before_evaluate
  [isolated, 无名表] start 第二 Host（题包 evaluate 配方；独立 work root，不绑 Agent 盘）
  [无名表] upload artifacts / gold 到那只 Host
  [isolated, 无名表] 对未在 run 用过的 ACP profile 再跑 after_environment_ready
  evaluation_runtime.evaluate # 独占槽赢家；默认 parent 子进程跑 evaluator.py
                              # 无名表：scoring.exec 打缺省打分 Host（= run 环境，或 isolated 那一只）
                              # 有名表：evaluate 开头 **不** start；worker 管道 op=exec
                              #   或 session(environment=) 第一次点到某名才 start + upload
                              # 可选：evaluator.py 调 Agent.session(<role>).invoke
                              # invoke 走 parent JSON-RPC；ACP attach_stdio 打当时的打分 Host
  bind_evaluation             # Result.status 只在这里写入；赢家返回 raw，不得 bind
  after_evaluate              # 可注 metrics，改 status → RuntimeError
cleanup（finally）
  stop 每一只已启动的打分 Host（若与 run 环境不同）
  stop run 环境
```

PASS 只经 `bind_evaluation` 进入 Result。`RunTerminal.completed`、轨迹完整、ACP 正常结束、judge 输出、`evaluation/observation.jsonl` 是否写全、harvest 快照在不在、打分 Host 起没起、`exec` 退出码，都不是 PASS。缺轨迹不得发明 PASS。

`evaluation_runtime` 默认是 parent 子进程里的 `evaluator.py`（`src/ageval/runtime/eval_worker.py`），与 `run.py` 共用 Agent Service socket。缺省路径：evaluator **不**调 `Agent.session` → 无 `evaluation/observation.jsonl`，Verifier 仍是 `result.json` + 产物文件树。这是 opt-in，不是新槽、不是新 profile 文件。

## 可选：evaluate 相位 SDK invoke（LLM-as-judge）

同一份 job `profiles.yaml` 多一行 `agent_profiles.<id>`（例：`judge`），task 角色表列入同一 id。gold **已经** upload 之后，`evaluator.py` 可以 `Agent.session("judge").invoke(...)`（可多次）。提示词归题包。`invoke` kwargs 仍不得改 `profile_id` / executor。

这些 invoke 走 **同一** Parent Agent Service 与该 profile 自己的 executor 赢家（ACP、openai-http、anthropic-http、…）。同一 Attempt 上 solver 与 judge **可以** 选不同机制（solver `acp`、judge `openai-http`）。`environment` 仍是 Attempt 级一份赢家；isolated 时 evaluate 相位把该服务绑到打分 Host，所以 ACP `attach_stdio` 进打分环境，HTTP judge 仍在 parent 出站。有名表时 ACP 必须 `session(..., environment=<name>)` 才绑到那一只（run 相位点名或省略名字失败）；`openai-http` / `anthropic-http` 忽略该参数。不要把 Agent Service unix socket bind-mount 进容器。

约束：

- gold 进环境之后，**solver（run 相位已用过的 profile）不得再 invoke**。
- evaluate 相位的 invoke scratch 不得进 `agent/invocations/`，以免 Agent 页 / 根 `trajectory.jsonl` 吞掉。布局字符串只在 `src/ageval/evidence/`。
- 轨迹行写入 `evaluation/observation.jsonl`（轨迹文件，与 Agent 轨迹同一行形）。**省略 `user` 行**（judge 提示常含 hidden reference）。不是 bind 的输入，不拷进 `result.json` / `metrics` / `summary.extra` / `evaluation/evaluator_raw.json`。
- `evaluator.py` 仍返回 `{status, score, metrics}`；`bind_evaluation` 只读这份。

低分是有效 FAIL。cleanup 失败只 warning。evaluator 缺产物应 FAIL，不要把 KeyError 变成引擎崩溃。

## gold：时间切开（默认）；isolated 再加空间切开

```text
environment / run     Agent 环境 /attempt/evaluation  不存在
evaluate 开头         打分 Host.upload(evaluation_src, /attempt/evaluation)
                      然后 parent 跑 evaluator.py；ACP attach 打打分 Host
```

- Agent / `run.py` / `environment_setup` **禁止**看到 `evaluation/`（不 upload、不 mount、不 COPY 进 Agent 用镜像层）。
- 缺省打分 Host = run 环境：Harbor 同档的 **时间切开**，**不是** `path_views`。不要只靠 YAML 删字段。
- `evaluate_host.isolated: true`：gold **只**上打分 Host。Agent 环境整段 Attempt 都没有这份树。不要把 Agent 活 workspace bind-mount / symlink 进打分环境（会漏 `target/`、`*.so`、Agent 安装闭包）。
- evidence 可记 gold 在 evaluate 才 upload。第二 Host 的 start 不是 PASS。
- 省略 `evaluate_host` = 今日同一环境。题包即使有 `environment/evaluate.Dockerfile`，没开开关也不 start 第二环境、不认那份配方。

`path_views` 是额外能力（当前仅 docker 报 yes）：同时多角色不同盘（mount+UID）。不要用它表示「晚上传 gold」，也不要用 compose 侧车当顺序打分镜像。

## 产物：file 与 tree

`artifacts.publishable` 缺省仍是单个文件（`kind` 省略 / `file`）。`kind: tree` 把题包声明的工作区树收成 **一次** 不可变快照（writer 停后、evaluate 前，仍走 `harvest_workspace_artifacts`）。可选 `exclude`（目录名与 glob 路径段，例如 `target`、`*.so`、`.git`）。

- harvest **一次**。后面 evaluate 的 upload / 再 upload / 环境内读取都消费这份快照的拷贝，不是 Agent 活目录，也不是三次 export。
- `evaluation.inputs[].target: workspace` 把 tree 铺到打分 Host 的 `/attempt/workspace`。省略 target 的 file 产物仍上 `/attempt/artifacts`。有名表时，每只 **已 start** 的 Host 各收一份拷贝。
- docker：tree download 读已有 bind-mount 再按 exclude 拷到 evidence；不要 `docker cp` 一整棵再在 Core 里拆。
- 打分 Host 的 workspace **不是** Agent bind-mount。harvest 之后改 Agent 树，evaluator 看不见。

快照在不在、exclude 清没清，都不是 PASS。

## isolated 打分 Host

job：

```yaml
# profiles.yaml — 省略 evaluate_host = 同一环境
evaluate_host:
  isolated: true
  # environment_options:      # 打分盒自己的网络策略；省略 = 不继承 agent 的 egress/egress_allow/network
  #   egress: llm             # ACP judge 在打分盒里时放行其 API host
  #   egress_allow:           # 仅 egress: llm；不继承 agent extras
  #     - api.judge.example.com
  #   network: bridge
```

lock：

- `isolated: true` 必须能在成员题上落到配方：存在 `environment/evaluate.Dockerfile`，或 `evaluation.docker_image`（OCI tag）。两者都无 → lock 失败，不 start。
- 配方文件 **不** 放 `evaluation/`（那是 gold）。
- Current：`environment: docker`。local / 不能再起一份环境的 kind + `isolated: true` → lock 失败。
- 嵌套 `environment_options` 要求 `isolated: true`；键允许 `network` / `egress` / `egress_allow` / `platform` / `user`（与盒子同一旋钮名，**不是** `image`）；`egress` / `egress_allow` 的 kind 门禁与 agent 同一规则；`egress_allow` 必须与同一 map 的 `egress: llm` 同写；未知键一次错误，不映射。agent extras 不出现在打分 `egress_allowlist`，打分 extras 不出现在 agent 名单。
- 未知 `evaluate_host` 键、未知 `artifacts.publishable` 键：一次错误，不映射。

runtime：打分盒实例在 **evaluate 相位**（writer 已密封）构造：composition 不再预建
第二 EnvironmentProvider。构造时 `image_layers` 取 **evaluate 相位 profile graph**
的联合（`bind_winner` 的赢家工厂仍是 Attempt 级 docker 插件；`BoxSpec` 仍只装
evaluate 配方与独立 attempt root）——
declare 了 `config.image_layers` 的 judge 插件由此 bake 进打分镜像，solver 独占的
插件不进。无 `image_layers` 的插件不加东西。ACP 若出现在 evaluate 相位 graph（例如
ACP judge）则只 bake 该 graph 绑定的 `options.entry`；solver 的 ACP 层不进打分镜像。
官方 ACP 引擎仍可走 **配方**（`FROM` 官方 attempt 基座）；非基座配方由 ACP 插件层
补绑定 entry，不是 Core wrap。`evaluation_runtime` 仍是独占槽
默认引擎，parent 子进程跑 `evaluator.py`。isolated 时对 **未在 run 打开过的 profile**
（不限 executor kind）在打分环境上再跑 `after_environment_ready`；空链 no-op，
不跑 `environment_setup`。SDK 仍不得拥有 `host.start` / `host.upload`。

## 命名打分 Host（`evaluation.environments`）

题包声明名字与配方；Runtime start / upload / stop；evaluator 只点名。compose 侧车随 Agent `host.start()` 起来，不是顺序打分镜像。

```yaml
# task.yaml
evaluation:
  environments:
    audit:
      dockerfile: environment/evaluate/audit/Dockerfile
    behavioural:
      dockerfile: environment/evaluate/behavioural/Dockerfile
    verification:
      dockerfile: environment/evaluate/verification/Dockerfile
```

```text
evaluator.py  (parent)
  scoring.exec("audit", argv)     → 首次：start audit、upload 快照+gold、host.exec
  scoring.exec("behavioural", …)  → 另一只镜像、另一份 work root、同一份快照拷贝
  agent.session("judge", environment="verification")
                                  → ACP attach_stdio 打 verification
cleanup                           → 停已 start 的每一只 + Agent Host
```

- 名表非空 ⇒ lock 要求 `evaluate_host.isolated: true` + `environment: docker`。缺配方文件一次失败。
- evaluate 相位 **懒启动**：未 `exec` / 未 `session(environment=)` 的名字不 build、不 start。
- `scoring.exec` 走 eval worker 管道 `{"op":"exec","environment":…,"argv":[…]}`，parent 答 `exit_code` / stdout / stderr。不要把 docker socket 挂进 worker。
- 省略 `evaluation.environments`：`scoring.exec` 打缺省打分 Host（run 环境，或 `evaluate_host.isolated` 的那一只）。名表非空时必须点名；未知名、run 相位 `session(environment=)`、或有名表时 ACP 省略名字：`unknown_evaluate_environment`，不 start。
- evidence 可记 `evaluate_host_started`（含 `name`）与 `evaluate_exec`（name + exit_code）。都不是 PASS。
- 阶梯与短路在 `evaluator.py` / `shared/lib`。

失败归属总表见 [ARCHITECTURE.md](../../../ARCHITECTURE.md) § Failure and Privacy Boundary。
