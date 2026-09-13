# 01 — ageval Core

结构地图见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。产品故事与命名见 [00](00-overview-and-product.md)。

Core 拥有：配置锁定、Attempt 身份、环境 Protocol、limits、evaluate 绑定、evidence 布局。不拥有题业务、厂商 SDK、PASS 算法。

## 五组（映射到当前模块）

| 组 | 模块 | 职责 |
| --- | --- | --- |
| Config | `src/ageval/config/` | `load_and_lock`、digest、profiles、能力校验 |
| Lifecycle | `src/ageval/attempt/` + `runtime/identity.py` | Run/Trial/Attempt 身份；五个阶段顺序 |
| Box | `environments/protocol.py` + `plugins/contrib/{local,docker,e2b,daytona,ssh}` | 物理隔离与运输 |
| Capability | `capabilities/` + lock `requires` | 已授权操作面；缺 cap 则 lock 失败 |
| Evaluation | `evaluation/` | barrier、parent `evaluator.py`、`bind_evaluation` |

另：`evidence/` 是布局与轨迹轨迹文件 的唯一主人；`plugins/` 是槽表，不是第六组 Core。

## lock

Config 是唯一规范读取者。根 `ageval.yaml`（`ageval.dataset/1`）+ 成员 `task.yaml`（`ageval.task/1`）+ job `profiles.yaml`（`ageval.profiles/1`）。

```text
CLI --task / --profiles / --set
  → dataset.resolve
  → merge task.yaml + profiles
  → validate format / keys / requires ⊆ capabilities
  → resolve exclusive winners + chain order → extension_bindings
  → inject 检查（executor 要 environment 服务 + 其 capabilities；ACP：attach_stdio）
  → canonicalize → digest
  → LockedTaskConfig（冻结）
```

未知 format：`invalid_format` 于 `/format`。`api_key` 只留 locator 名。两个插件抢同一独占槽或同一 export id → 拒绝。绑定图进 lock digest。未列入 `extensions` 的不进链、不进服务表。

`--profiles` 整份替换配置文件。`--agent` 与 `--profiles` 互斥。`--model` 是 run 参数（须配合 `--agent`），改已绑角色的 `binding.model`；省略则用包缺省。`--set` 白名单见 [02](02-task-package-and-config.md)。`limits.*` 不可 `--set`。

## Attempt 流水线（可见链）

打开 `src/ageval/attempt/__init__.py` 就是权威时间线。引擎不变量（**不是插件**）：lock / Attempt 身份；deadline；`try/finally` 必调 cleanup；PASS 只从 evaluate 的结果绑定。

```python
# src/ageval/attempt/__init__.py（形状；以源码为准）
async def run_attempt(ctx) -> None:
    try:
        await environment.run(ctx)  # start + overlay + setup.entry
        await run.run(ctx)          # 调 task 的 run.py
        await evaluate.run(ctx)     # 独立 evaluator.py
    finally:
        await record.run(ctx)       # 轨迹落盘（environment 已 start 后，evaluate ERROR 也封）
        await cleanup.run(ctx)
```

environment / run 失败记 `phase_failed` 并跳过未跑的相；**environment 一旦 start，evaluate 无论成败都进 record**，把已有 invoke scratch 封成 `trajectory.jsonl`（Viewer / 上传读轨迹文件）。record 自己再失败且前面已有 `phase_failed` 时记 `record_warning`，不覆盖原相位。取消（`BaseException`）仍传播；cleanup 总是跑。相位失败是结果，不是静默吞掉。

`emit(slot)` 走 `lock.extension_bindings` 已排好的链。插件改的是绑定，不是运行时改写 `run_attempt`。

## phase 与 slot

**phase**：`run_attempt` 里的一大步，默认实现是 `phases/*.py`。  
**slot**：phase 内部的钩子，分两种（**没有**第三种叫 `provide` 的扩展模型）：

| 槽种类 | 语义 | 例子 |
| --- | --- | --- |
| **独占** | 每个 resolved graph 一个赢家；登记为同名 **service** | `environment`、`executor`、`evaluation_runtime`、`trajectory_seal` |
| **链** | `(ctx, value, nxt)` | `after_environment_ready`、`environment_setup` |

`environment` / `evaluation_runtime` / `trajectory_seal` 是 **Attempt 级** 一份赢家。`executor` 按 `agent_profiles` **每行一份**：solver 与 judge 可以选不同机制。两个插件仍不得抢同一 graph 上的同一独占槽。

`agent_profiles.<id>.executor: acp` = 选该 profile 独占槽 `executor` 的赢家，不是另一套插件系统，也不是 Attempt 上只许一个 executor 插件。

槽名权威：`src/ageval/plugins/slots.py`。新**时间线**槽仍要改 attempt 宿主；插件不可自造槽名。

Current 独占槽：`environment`、`executor`、`evaluation_runtime`、`trajectory_seal`。后两者的默认赢家是引擎（`plugin_id: default`，`is_default=True`）：parent 子进程跑 `evaluator.py`（与 `run.py` 同一 JSON-RPC 口）与轨迹文件 写入（run 相位 `trajectory.jsonl`；evaluate 相位若有 SDK invoke 则另写 `evaluation/observation.jsonl`）。没有单独的配置字段；替换只能走显式 `extensions` 行（`slot` + `plugin`）。缺默认注册 → lock 失败，不能进入运行。

PASS 仍只经 `AttemptCtx.bind_evaluation` 进入 Result。`evaluation_runtime` 赢家返回 raw，不得自己写 verdict。`pass` / `identity` / `cleanup` / `evidence` 仍不是服务。

默认 phase：

| phase | 默认做什么 |
| --- | --- |
| `environment` | `host.start` + upload seed + 槽（见下） |
| `run` | 调 task `run.py`；内含 agent open/invoke/close **子槽**。结束时停 solver writer，**保持** Agent Service |
| `evaluate` | 选打分 Host（缺省 = run 环境；job `evaluate_host.isolated` 则另起同 kind 实例：一份配方 = 一只；`evaluation.environments` = 按名懒启动多只）、放入环境 gold **只进打分 Host**、调 `evaluation_runtime` 赢家（可选 SDK `Agent.session` / `scoring.exec`）、`bind_evaluation` |
| `record` | collect/enrich → `trajectory_seal` 写 run 相位 `trajectory.jsonl`；evaluate 相位 invoke 另封 `evaluation/observation.jsonl`（省略 user） |
| `cleanup` | `host.stop`；isolated 时停 **每一只** 已启动的打分 Host 再停 Agent Host。实现可加报告，不能选择跳过 |

**没有 `provision` phase。**

槽只有独占与链两种。独占槽就是赢家，没有第三套扩展种类。

### environment 内的 slot 顺序（权威）

以 `src/ageval/attempt/phases/environment.py` 为准：

```python
async def run(ctx) -> None:
    await emit(ctx, "before_environment")
    await ctx.host.start(force_build=ctx.lock.force_build)
    await ctx.host.upload(ctx.seed_dir, "/attempt/workspace")  # 有 data/ 才 upload
    await emit(ctx, "after_environment_ready")  # 铺 HOME / 补 env / skills；ACP probe
    await emit(ctx, "environment_setup")        # 末槽：setup.sh；无则 no-op
    await emit(ctx, "after_environment")
```

- `after_environment_ready`：环境已开、`environment_setup` 之前。HOME overlay、env inject、**ACP 探测**挂这里。按 `options.entry` 探名字 + 钉死包版本 + 一次 stdio `initialize`；docker bake 已匹配则跳过 `install_command`；不对再按 entry 的 `install_command` `exec`。失败 = environment 相位失败。不把安装写进 task `setup.sh`。invoke 不是装引擎的 happy path。
- `environment_setup`：默认插件若存在 `environment/setup.sh`（或 yaml 覆盖的 entry）则 `host.exec`。本题依赖，不是 agent CLI。
- bake / `image_layers` 消化在 `host.start()` 内部（docker build / e2b template），不是 attempt 上的独立 phase。`kind: ssh` 且 skip_build 时无 bake。

### evaluate：缺省同一环境晚上传 gold；opt-in 第二 Host（权威）

以 `src/ageval/attempt/phases/evaluate.py` 为准。`environment` 仍是 **Attempt 级一份**赢家，只服务 **run**。打分另开环境 **不是新槽、不是第二套 resolve**：同一 `environment` 赢家再构造一个 EnvironmentProvider 实例（不同 `BoxSpec` / 不同 work root）。

**缺省**（省略 job `evaluate_host`）：同一环境、进 phase 再 upload gold。形状不变：

```python
async def run(ctx) -> None:
    await emit(ctx, "before_evaluate")          # solver writer 已在 run 结束停掉；Agent Service 仍在
    # 引擎 upload gold —— 不挂在 before_evaluate 链上
    if ctx.evaluation_src.exists():
        await ctx.host.upload(ctx.evaluation_src, "/attempt/evaluation")
    result = await ctx.evaluation_runtime.evaluate(ctx)  # 独占槽赢家；默认 parent evaluator.py
    ctx.bind_evaluation(result)                 # PASS 只从这里进；赢家不得 bind
    await emit(ctx, "after_evaluate")            # 不得改 status
```

**opt-in**（job `evaluate_host.isolated: true`）：harvest 之后、evaluate 开头，Runtime 用题包 `environment/evaluate.Dockerfile`（或 `evaluation.docker_image`）`start` **一只**第二实例。gold 与 harvest 快照只进这个 Host。`evaluator.py` 仍在 parent 跑；evaluate 相位的 ACP `attach_stdio` 打第二实例。Agent 环境永不 mount / upload `evaluation/`。cleanup 停两个。Current 要求 kind 是 `docker`；不能再起一份环境的 kind + `isolated: true` → lock 一次失败（不要报假 cap）。

**再 opt-in**（成员 `evaluation.environments`）：同一 `environment` 赢家、多只实例，按 yaml 名键。不是新槽、不是第二套 resolve、不是 compose 侧车。evaluate **开头不 start**；`evaluator.py` 第一次 `scoring.exec(<name>, argv)` 或 `Agent.session(..., environment=<name>)` 才 `preflight` + `start` + upload 快照与 gold。未点到的名字不 build。省略 `evaluation.environments` = 上面那只（或同一环境）。写了该键则必须 `evaluate_host.isolated: true` 且 kind docker，否则 lock 一次失败。`ctx.evaluate_host`（单数）在有名表时不用；权威是 `ctx.evaluate_hosts`。

- Agent / `run.py` / `environment_setup` **禁止**看到 `evaluation/`（不 upload、不 mount、不 COPY 进 Agent 用镜像层）。isolated 时这条红线变成 **空间切开 + 时间切开**：gold 根本不进 Agent 环境。
- 这不是 `path_views`。evidence 记 `gold_materialized`（at evaluate）；isolated 另记打分 Host 的 start/stop（含 `name`），那些事实 **不是** PASS。`exec` 退出码也不是。
- gold 进打分环境之后 solver 不得再 invoke。evaluate 相位可以按 **另一** profile（例 `judge`）走同一 Parent Agent Service；isolated 时 attach 目标是当时的打分 Host；有名表时 ACP 必须 `environment=` 选那一只（run 相位点名失败）。
- 省略开关 = 今日 Attempt。judge 观察不是 PASS。`observation.jsonl` 缺席 = 今日脚本评测路径。可选 `checks` 不是 PASS；缺席 = 不写 `evaluation/checks.json`。
- 阶梯（顺序、短路、分数混合）在 `evaluator.py`，不在 Core。

### 其他 slot

| 挂在 | slot |
| --- | --- |
| run | `before_run` / `after_run`；`before/after_agent_open\|invoke\|close`；`normalize_agent_result` |
| evaluate | `before_evaluate` / `after_evaluate`（可注 metrics，**不能改 PASS**）。**upload gold 是引擎代码**，不是 `evaluation_runtime` 的方法。独占槽 `evaluation_runtime` 默认 parent 跑 `evaluator.py` |
| record | `trajectory_collect` / `trajectory_enrich`（失败不挡后续）；独占槽 `trajectory_seal` 写 run 相位轨迹文件（丢文件即阶段失败）；evaluate 相位 invoke 封到 `evaluation/observation.jsonl`（有才写；省略 user）；`summary_enrich`（失败不挡后续，seal 成功后一次，写 Attempt `summary.extra`） |
| cleanup | `cleanup_report`（链）；cleanup phase 本身由 finally 调用 |

`executor` 是 **profile graph 里的独占槽**（run 与 evaluate 的 `Agent.session` 都走它），不是 attempt 上的独立 phase。ACP attach 发生在该 profile 第一次 invoke，不是独立 phase。

`FAIL_OPEN_SLOTS`：`before_run` / `after_run` / `trajectory_collect` / `trajectory_enrich` / `summary_enrich` / `cleanup_report`。其余槽失败即该相位失败。

完整 emit 图：[ARCHITECTURE.md](../../ARCHITECTURE.md) § Extension emit map、[05-runtime/README.md](05-runtime/README.md)。

## 环境 Protocol

独占槽 `environment`。赢家实现 `src/ageval/environments/protocol.py`。厂商 SDK 只活在 `plugins/contrib/<kind>/`。Protocol 文件禁止出现 `e2b` / `docker` / `paramiko` 实现。

动词：`preflight` / `start` / `exec` / `upload` / `download` / `attach_stdio` / `stop`。另有 `placement()` 与 `visible_path()`。

```python
class EnvironmentProvider(Protocol):
    kind: str
    capabilities: EnvironmentCapabilities  # exec/upload/download/attach_stdio/uid_gid/path_views/compose
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

`exec(..., service=)` 仅 `capabilities.compose`。Placement 只有 opaque `target_id` + user + workdir/home。ACP 只拿 `StdioTransport`，不写 `if docker`。

kind：`local` | `docker` | `e2b` | `ssh` | `daytona`。能力矩阵与 `attach_stdio` 运输见 [05-runtime/environment.md](05-runtime/environment.md)。

合同路径：`/attempt/workspace`、`/attempt/home`、`/attempt/artifacts`、`/attempt/evaluation`。

job 选环境：`profiles.yaml` 的 `environment:`，不是 `provider.kind`。

## composition

```text
cli → application.composition.build_*
        → config.load_and_lock
        → identity.new_run / new_trial / new_attempt
        → bind environment winner（Attempt 级）+ 各 profile 的 executor 赢家
        → ParentAgentService
        → run_attempt
```

平台对象只在 `application/composition.py` 的 `build_*` 接线。CLI 只 import composition。一次 Attempt 只 `IdentityFactory.new_run` 一次。控制面不 import 题包模块；`run.py` / `evaluator.py` 走进程边界。

结构规范（不可退化）全文见 [09](09-owner-matrix-and-structure.md)。
