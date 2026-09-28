# 00 — 产品与红线

ageval 把一次评测收成可见的 Attempt：锁定 **dataset**，打开一个 **环境**，跑题包 `run.py`，再由独立 `evaluator.py` 出分。编排始终在本机 `ageval run`；环境可以在本机、本机 Docker、E2B、SSH 或 Daytona 上。

未发版不兼容旧名，不留别名。题包根叫 **dataset**，不是 SQL，也不是侧车 Postgres。

本文件吸收产品模型（目标、非目标、用户故事、三层、命名、术语对照）。机制细节在 [01](01-ageval-core.md) 与 [05-runtime/](05-runtime/)。结构地图：[ARCHITECTURE.md](../../ARCHITECTURE.md)。施工红线：[AGENTS.md](../../AGENTS.md)。

**权威只在本仓 `docs/`。** 不要去仓外 BRIEF / vault 找第二套产品形状。

## 产品更名（不兼容旧名）

| 面 | 值 |
| --- | --- |
| 产品名 / 文档站 / README | **ageval**（agent eval） |
| CLI | `ageval lock` / `ageval run` |
| Python 包与 import | `ageval` / `ageval_sdk` |
| PyPI 发行名 | **`ageval-cli`**（`ageval` 槽位已被占；单 wheel 双顶层包，import 名不变） |
| 环境变量 / 家目录 | `AGEVAL_*`、`~/.ageval` |
| 配置 format | `ageval.dataset/1`、`ageval.task/1`、`ageval.plugin/1`、`ageval.profiles/1` |
| GitHub 路径 | [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval) |

未知 format：**一个**错误（`invalid_format` 于 `/format`），停。不要在报错里教映射。

## 规范交付单位：dataset

现在叫 Database 的东西是历史误名。它是评测 **数据集 / 题包**（根配置 + 若干 task 成员），不是 SQL。

不要和侧车 Postgres、`host.exec(service="db")` 混为一谈。那些仍叫数据库资源 / compose service。

| 面 | 值 |
| --- | --- |
| 产品用语 / CLI help | **dataset** |
| 根 format | `format: ageval.dataset/1` |
| 根清单文件 | `ageval.yaml` |
| 标识符 | `dataset_id`、`dataset_root`、`load_dataset` |
| 成员 | `tasks/<id>/task.yaml`（`ageval.task/1`） |

`shared/` 相对 **dataset 根** 解释；gold 仍在 `tasks/*/evaluation/`。

## 控制流

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

打开 `src/ageval/attempt/__init__.py` 能说出 phase 顺序。插件改的是 lock 时的绑定，不是运行时改写这五行。

## 三层各管什么

| 层 | 文件 | 干什么 |
| --- | --- | --- |
| 产品 | `src/ageval/attempt/` + `attempt/phases/*.py` | 开环境 → run → eval → 归档 → 拆环境 |
| Job | `profiles.yaml` / `extensions` | 选独占槽赢家（`environment` / `executor`）、列 extensions |
| Task | `run.py` / `evaluator.py` / `environment/` | 这一题的业务、打分、环境配方 |

要换整条链：换 job 用的 attempt 模块或默认插件图。**不要**在 50 个 task 里复制编排。

## 命名（已拍板）

| 角色 | 用这个 |
| --- | --- |
| 产品里串 phase | **`src/ageval/attempt/__init__.py`**（`run_attempt`） |
| task 里只做 run | **`run.py`**（`async def run(ctx)`） |
| 打分 | `evaluator.py` |
| 环境运输面 | 独占槽 **`environment`**；`ctx.host` / `ctx.services.require("environment")` |
| Agent 后端 | 独占槽 **`executor`**（赢家常是 acp） |

## 目标

1. 一次 Attempt 的链写在产品包 `attempt/`：串行调 phase；每个 phase 文件内串行 `emit(slot)`。打开就能看见。
2. **phase**（提供默认实现，可换独占赢家）与 **slot**（链）分开。插件改绑定，不改 `run_attempt` 的默认顺序。
3. 环境只有一个入口：独占槽 `environment`（`local` / `docker` / `e2b` / `ssh` / `daytona`）。能力 `requires ⊆ capabilities`，缺则 lock 失败。
4. `environment/Dockerfile`（或 `docker_image`）对 docker 与 e2b 同一配方。`setup.sh` 是 environment 的末槽，不是单独 phase。
5. **Task 不包含流水线文件。** 业务只在 `run.py`，打分在 `evaluator.py`。`task.yaml` **缺省有文件就认**。
6. Agent 仍是 `executor: acp` + `options.entry`。附着 `host.attach_stdio`。PASS 只来自独立 evaluate。
7. 产品 / CLI / 包名为 ageval；交付单位为 dataset。

## 非目标

- 不把 Harbor 的全部云厂商一次搬进来。
- 不把 vendor SDK、alias 缓存写进 Core。Core 只调 `host.start()`。
- 不保留 Environment Manager。
- 不把环境做成 `provide(executor)`。没有第三种叫 `provide()` 的扩展模型。
- **不在每个 task 里复制 `attempt.py` / phase 文件。**
- 不单开 `provision` phase，不要 `before/after_provision`。
- 插件不能取消 cleanup、不能发明 PASS、不能重排「先打分再跑 agent」。
- Core 仍拥有：Attempt 身份与 lock digest、deadline/cancel、`try/finally` 必进 cleanup、PASS 只从 evaluate 进入。
- 未知 format 一个错误，不映射。
- Core 内不建通用 Graph / Handoff / BranchAuthority 平台。
- 不是开放插件商店。
- 适配器禁止按 Benchmark / task 名分支。

## 用户故事（产品形状）

这些故事是产品约束，不是进度勾选。实现是否兑现看代码与公开 smoke（见 [ARCHITECTURE.md](../../ARCHITECTURE.md) Current / Target）。

### US1 — 换环境只改 kind

`ageval run` 选独占槽 `environment: e2b`（或 `local` / `docker` / `ssh`）。`run_attempt` 调用串不变。缺 `E2B_API_KEY` 在 preflight/lock 失败。

### US2 — 一份 Dockerfile，两种环境

`environment/Dockerfile`（或 `docker_image`）。docker 本机编；e2b `Template.from_dockerfile`。要 compose 而 kind 没有该 cap → lock 失败。

### US3 — setup 是 environment 末槽，不进 run.py

有 `environment/setup.sh` 则 environment phase 最后 `emit("environment_setup")` → `host.exec`。无文件则默认 no-op。失败是 environment 阶段失败，不是 Agent 轨迹。重依赖进 Dockerfile。

### US4 — ACP 进任意环境

ACP `inject: [service: environment]`，`host.attach_stdio`。Placement 无 `container_id`。ACP 禁止 import docker/e2b/ssh。

### US5 — 能力 lock

`requires` 缺省为空。非空则必须 ⊆ kind.capabilities。Result 记 `kind` + `capabilities_used`。

### US6 — 无 Manager

侧车 = compose 或 `host.exec(service=)`。`run.py` 读投影 DSN。

### US7 — 厂商扩 kind

实现独占槽 `environment` 的赢家（同一 Protocol）。不改 `attempt/` / ACP / `run.py`。

### US8 — 缓存对 Core 无感

只调 `host.start()`。alias/hash 在 e2b 实现里。Core 不实现 E2B 模板缓存。

### US9 — 打开 attempt 看见整条链

贡献者 / 任务作者不读 lifecycle 迷宫。产品包里的 `run_attempt` 五行 + `phases/environment.py` 里的 slot 顺序就是权威时间线。

### US10 — task 目录很薄

作者只维护 `run.py`、`evaluator.py`、`environment/`。不写入口字段也能跑（见 [02](02-task-package-and-config.md) 缺省）。

### US11 — gold 进 evaluate 再上传

Agent / `run.py` 阶段 **不得** `upload` `evaluation/`。evaluate phase 开头再 `host.upload` gold/测例，然后 exec evaluator。同一环境即可。这是默认隔离，**不**等于 `path_views`。

### US12 — 云上已有 image：连上 + 探测再装 agent

`environment: ssh`。**A** 无 `image`：环境=整机，`attach_stdio` = `ssh -T -- argv`。**B** 有已有 tag：`start` 远端 `docker run`，`attach_stdio` = `ssh -- docker exec -i`。两种 agent 都在云上。ACP 挂 `after_environment_ready`：名字 + 钉死包版本 + stdio `initialize`；docker bake 已匹配则跳过安装，不对再按 entry `install_command` 装。

## 红线

1. PASS 只来自 evaluate 绑定。轨迹、`RunTerminal.completed`、ACP `end_turn` 都不是 PASS。
2. lock / evidence / 默认环境不写 host token。环境变量只作 locator。
3. 适配器按机制命名（`acp` / `docker` / `e2b` / `ssh`），禁止按 bench 名分支。
4. ACP / `attempt` / `run.py` 不见 `container_id`、不见 `if kind == e2b`。
5. Agent 阶段磁盘上没有 `evaluation/`。gold 在 evaluate 开头才 upload。
6. 未知 format 一个错误（`invalid_format` 于 `/format`）。
7. 没有产品 `executor: mock`、没有 FakeHost 当完成证据。
8. cleanup 在 `try/finally`。插件不能取消 cleanup，不能发明 PASS。
9. CLI 只 import `ageval.application.composition`。
10. 一次 Attempt 只 `new_run` 一次。
11. 测试面 = 真实 kind + 公开 CLI。无凭证 skip 该 job，不标完成。
12. inject 在 lock 完成。缺 `attach_stdio` 就 lock 失败，不要等到 invoke 才检查 attach_stdio。

## 可见性

gold 隔离是**时间切**：不 mount，evaluate 再 upload。这是默认，不等于 `path_views`。`path_views` 只有环境真能兑现时才报 yes（当前：docker）。

## Harbor 对照（实现事实，不是产品名）

对照 Harbor 只取运输形状，不 import、不抄 20 个 vendor adapter：

- 环境五个动词：`start` / `exec` / `upload_*` / `download_*` / `stop`。ageval 再加 `attach_stdio` 与 `preflight`。
- 编排器和 parent ACP client 在本机；远程的是 workspace。
- **Dockerfile 不是 docker 私货。** e2b 云上也可从同一配方编 template。多数 cloud 厂商不认 compose。
- 模板缓存（内容 SHA → alias）若存在，只活在 e2b contrib。**ageval Core 不实现这套缓存**——只调 `host.start()`。
- Harbor trial 把 setup agent 单开一步。ageval 把「setup agent」收进 run 里的 ACP attach，不单开 phase。灌数 / `setup.sh` 是 **environment 的最后一个 slot**。

## 说法

- 环境：`environment: local | docker | e2b | ssh | daytona`。能力记在 `kind` + `capabilities_used`。
- 题包入口：`run.py` / `RunContext`。编排：`attempt/__init__.py` 的 `run_attempt`。
- 装依赖：environment 末槽 `environment_setup`（`setup.sh`），不是单独 phase。
- 侧车：compose 或 `host.exec(service=)`。
- Agent 后端：独占槽 `executor`。环境：独占槽 `environment`。扩展只有 exclusive 与 chain。
- 题包根：**dataset**，format `ageval.dataset/1`。CLI：`ageval lock` / `ageval.yaml`。
- gold：同一环境；evaluate 开头再 upload。
- ACP：docker 在 `host.start()` 用插件 `image_layers` bake 绑定的 `options.entry`；`after_environment_ready` 探名字 + 钉死包版本 + stdio `initialize`，已匹配则跳过，不对再按 entry `install_command` 装。
- ssh：A 整机 / B 远端已有容器。inject：`service: environment`。

## 审查问题（实现时对照）

1. `attempt/__init__.py` 能否不打开别的文件就说出 phase 顺序？
2. ACP / `run.py` 有没有 `if kind == e2b`？
3. ACP 还能不能看见 container/sandbox id？
4. 缺 cap 会不会仍开跑？
5. task 目录里有没有编排文件？
6. Agent 阶段磁盘上有没有 `evaluation/`？
7. 云镜像已有 `pi` 时还会不会再装一遍？

## 快照分享

Hub 上有只读链接 `/s/{token}`，匿名可以打开。默认是创建时的 suite 与 Attempt 证据。`mode=live` 时，owner 在 job 结束时更新同一条链接。创建这条链接不改 suite 的公开 / 私有，也不把它放进身份 ACL 或 Leaderboard。机制在 [12](12-hub-dataset-and-leaderboard.md)。

## 这轮不包含

下面这些不在这轮里。要纳入，先改 `docs/` 再写代码。

- gaia / tau3 全 suite 手改
- 五条 ACP 的付费 invoke 全部跑一遍
- Harbor 的其它云厂商
- 默认 CI 真打 E2B
- 多 group 真调度 run（lock 带 topology 即可）
- Hub REST 全表
