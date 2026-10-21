# 02 — Dataset 与配置规范

评测数据集的交付单位是 **dataset**（根清单 `ageval.yaml` + `tasks/<id>/` 任务成员目录）。配置锁定数据流见 [ARCHITECTURE.md](../../ARCHITECTURE.md) § Data Flow。

## 根清单 `ageval.yaml`

```yaml
format: ageval.dataset/1
dataset_id: example/minimal-demo
version: "0.1.0"
tasks:
  root: tasks
```

未知 `format` 在 `lock` 阶段直接报错 `invalid_format`（位于 `/format`）。CLI 的 dataset 参数始终指向 dataset 根目录或 Hub 引用：

根清单还可以声明数据集级 **assets 与 prepare**（在解析 Dataset 与打开任何 Attempt 之间执行，与逐任务的 `environment/setup.sh` 不同）：

```yaml
assets:
  - path: tasks/clip-01/data/clip.mp4   # 相对 dataset 根，禁止 `..`
    url: https://cdn.example.com/clip-01.mp4
    sha256: <64 位十六进制>
prepare: ./prepare.sh                    # 可选
```

`ageval prepare <dataset>`（`run` / `lock` 自动先行）逐项处理 assets：文件已存在且 sha256 一致则跳过，否则下载、校验、落盘；下载失败报错 `asset_download_failed`，摘要不一致报错 `asset_digest_mismatch`，均在打开 Attempt 前停止。`prepare` 脚本默认禁用：仅在 `--allow-prepare` 或 dataset 位于信任列表（环境变量 `AGEVAL_PREPARE_TRUST`，逗号分隔 dataset_id 或根路径）时运行；约束为 cwd = dataset 根、超时（默认 600 秒）、以调用用户身份运行、不得引用根外路径，运行后声明的 assets 仍须通过 sha256 校验，报错分别为 `prepare_not_allowed` / `prepare_failed`。脚本按（脚本内容 + assets 清单）哈希写完成标记 `.ageval-prepare.json`，同一次 suite 内不重复执行。下载的文件内容不进入 `eval_digest`（清单的 `path + sha256` 已计入），脚本内容计入，详见 [12](12-hub-dataset-and-leaderboard.md)。

```bash
ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg
ageval run  examples/datasets/minimal-demo --task terminal-jsonl-agg
ageval tasks examples/datasets/minimal-demo
ageval run  official/demo@0.1.0 --dir tmp
```

`run`、`lock`、`view` 与 `results upload-suite` 的首个参数支持本地 dataset 根目录或 Hub 引用（`dataset_id@version` / `@sha256:…`）。`--dir <path>` 仅在 `ageval run` 配合 Hub 引用时使用，将数据集检出至 `<path>/<dataset_id>/`（若已存在匹配目录则直接复用）；本地路径搭配 `--dir` 会报错 `invalid_override`。`lock`、`view` 与 `upload-suite` 优先读取本地已校验缓存。`tasks` 与 `campaign` 仅接受本地目录。

此外，首个参数可以是 **git 源引用**：`github:org/repo@<tag|全长 sha>` 或 `https://…@<tag|全长 sha>`（GitHub、Hugging Face datasets 等），可选 `#<subdir>` 选择仓库内的一个 Dataset 子目录（相对路径、禁止 `..`、必须包含 `ageval.yaml`；一个仓库可托管多个 Dataset，各自独立）。缺少 `@` 钉版或指向分支名的引用报错 `invalid_package`。CLI 将引用解析为完整 commit sha，以 partial + sparse checkout 拉取该 commit（远端不支持时回退全量拉取）并写入注册表 git 缓存（键为 `(git_url, commit, subdir)`），后续 lock/run 流程不变；子目录 Dataset 不得通过符号链接引用根外路径，lock 时报错 `invalid_package`。私有仓库使用本地 git / gh 凭据。https URL 禁止内嵌任何 userinfo（`https://<token>@host` 与 `https://user:pass@host` 一并拒绝），凭据不进入 lock。lock 摘要记录 `source.git_url`、`source.commit`（及 `source.subdir`）与 `eval_digest`（见 [12](12-hub-dataset-and-leaderboard.md)）。

`--profiles` 整份替换默认配置文件；`--agent` 与 `--profiles` 互斥；`--model` 需配合 `--agent` 覆盖已绑定角色的 `model.id`。`--set` 允许覆盖的白名单路径包括：`/parameters/seed`、`/parameters/active_profile`、`/agent_profiles/<role>/{model,executor,api_key,base_url,options/<key>}`，以及嵌套模型字段 `model/id`、`model/api`、`model/timeout`、`model/watchdog`、`model/reasoning/effort`（`model` 必须为嵌套对象）。`limits.*` 不允许通过 `--set` 修改。

## 任务成员 `task.yaml`

```yaml
format: ageval.task/1
task_id: acp-local-min
parameters:
  instruction: "…"
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 600       # 仅约束 run 阶段；默认 300
  environment_seconds: 600     # 约束 environment 阶段；默认 600
  evaluate_seconds: 600        # 约束 evaluate 阶段；默认 600
  agent_invocations: 1         # 仅统计 run 阶段的调用次数
  agent_concurrency: 1         # run 阶段同时执行的调用上限；默认 1
artifacts:
  publishable:
    - id: reply
      path: artifacts/reply.json
    # kind 省略或为 file 时收集单个文件；设为 tree 时保存工作区目录快照：
    # - id: repo
    #   path: workspace
    #   kind: tree
    #   exclude: [target, "*.so", .git]
evaluation:
  inputs:
    - artifact: reply
      target: artifacts/reply.json
  # collect:                          # 评分前从 attempt 容器或 compose 服务收集文件
  #   - path: /tmp/agent.patch        # 容器内绝对路径；在评分环境中放回相同路径
  #     service: main                 # 省略或 main 表示 attempt 容器
  #     command: "git diff > /tmp/agent.patch"
  #     timeout_sec: 60               # 默认 60，仅约束 command
  #   - path: /tmp/pg.dump
  #     service: postgres-db          # compose 服务；先执行全部 main，再执行辅助服务
  #     command: "pg_dump -f /tmp/pg.dump"
  # docker_image: ageval-eval:grader   # 仅在 isolated 且未声明 environments 时生效
  # environments:                      # 多命名评分容器；声明后忽略 evaluate.Dockerfile 与 docker_image
  #   audit:
  #     dockerfile: environment/evaluate/audit/Dockerfile
  #   verification:
  #     docker_image: ageval-eval:verify
```

`limits.agent_concurrency` 为正整数（省略时默认为 `1`；`0`、负数、布尔值或非整数在 `lock` 阶段直接拒绝），用于限制单次 Attempt 在 `run` 阶段同时处于执行器运行状态的调用数量（跨会话、跨角色共享）。它不限制子协程创建数量、`agent_invocations` 总额度或 suite 并发任务数；`run.py` 中的 `bounded_gather(limit=)` 与 `first_success(limit=)` 受此上限约束。

## 精简任务目录与默认文件识别

```text
tasks/<id>/
  task.yaml                 # 目录名必须等于 task_id 与 --task 参数
  run.py                    # async def run(ctx) — 仅在 run 阶段执行
  evaluator.py              # 仅在 evaluate 阶段执行
  environment/
    Dockerfile              # 待测 Agent 环境配方（docker / e2b / daytona 共用）
    evaluate.Dockerfile     # 单个独立评分容器配方（isolated 且未声明 evaluation.environments 时生效）
    evaluate/               # 多命名评分容器配方目录（如 audit/Dockerfile）
    setup.sh                # 存在时由 environment_setup 在 Agent 环境中执行
  data/                     # 待测 Agent 可见的初始文件，在 environment 阶段上传至 /attempt/workspace
  evaluation/               # 评分参考材料（gold），run 阶段不可见，evaluate 阶段上传至评分环境
```

**默认约定（存在对应文件即自动识别，无需在 YAML 中重复声明）：**

| 未显式声明项 | 默认识别规则 |
| --- | --- |
| `run` 入口 | 存在 `run.py` → `run:run` |
| `evaluator` 入口 | 存在 `evaluator.py` → `evaluator:evaluate` |
| Agent 环境镜像配方 | 存在 `environment/Dockerfile` → 自动使用；或使用 `environment_options.image` / `docker_image` |
| 评分容器配方 | 存在 `environment/evaluate.Dockerfile`（或 `evaluation.docker_image`）→ 在 `evaluate_host.isolated: true` 且未声明 `evaluation.environments` 时使用；若声明了 `evaluation.environments` 则按名称读取；省略 `evaluate_host` 时忽略所有独立评分容器配方 |
| 环境初始化脚本 | 存在 `environment/setup.sh` → 在 `environment_setup` 链槽中执行；不存在则跳过 |
| `requires.environment` | 默认为空（不额外要求特定环境能力） |
| 初始数据 (`seed`) | 存在 `data/` → 在 `environment` 阶段上传至工作区 |
| 参考材料 (`gold`) | 存在 `evaluation/` → 在 `evaluate` 阶段上传至评分环境 |

`evaluation.collect` 省略或为空列表 `[]` 时不执行。每条声明至少包含 `path`（不含 `..` 的绝对路径）或 `command`，可选指定 `service`（省略或 `main` 表示 attempt 容器，其余值表示 compose 服务名）。命令或路径拷贝失败时，在 `evaluate` 阶段记为 `ERROR`（`environment_collect_failed` / `environment_collect_missing`）。详见 [05-runtime/evaluation.md](05-runtime/evaluation.md)。

## Harbor 布局（`--layout harbor`）

省略 `--layout` 时只接受上面的 `ageval.dataset/1` 包。`--layout harbor` 是显式开关，不会根据目录内容自动判断。它接受两种本地路径：

1. **单个任务**：目录含 `task.toml`、`instruction.md`、`tests/test.sh`，以及 `environment/` 或 `environment.docker_image`。此时 `--task` 非法。
2. **隐式任务集**：父目录的直接子目录都是 Harbor 任务。省略 `--task` 跑整份 suite；可重复 `--task` 做过滤。任务 id 是目录名。`[task].name` 若出现且不等于目录名，锁定失败。

根上的 Harbor `registry.json` 索引在 v1 直接拒绝（`harbor_registry_rejected`）。已经转换成 ageval 成员的树（`ageval.yaml`，或 `task.yaml` + `data/` + `evaluation/`）再加 `--layout harbor` 时失败（`harbor_layout_mix`），不猜测该用哪一种。

没有 `ageval.yaml` 时，dataset id 取路径目录名（小写，下划线改为连字符），version 固定为 `1`。`.ageval/` 与可选的 `profiles.yaml` 放在 CLI 传入的那个路径根上，不放进任务集里的每个任务。git 源的 `#subdir` 在该布局下不要求 `ageval.yaml`，只要子目录是 Harbor 任务或任务集。`prepare` / `assets` 不在 Harbor 树上执行。

`task.toml` 映射：

| Harbor | ageval |
| --- | --- |
| `agent.timeout_sec`（仅当键存在） | `limits.wall_time_seconds`。缺省不继承 verifier 的超时 |
| `verifier.timeout_sec` | `limits.evaluate_seconds` |
| `environment.build_timeout_sec` | `limits.environment_seconds`。这是整个 environment 阶段预算，docker build 的截止时间在 v1 只是近似 |
| `cpus` / `memory_mb` / `gpus` / `gpu_types` | `parameters`，由 docker 插件施加到 Attempt 容器 |
| `network_mode` `public` \| `no-network`（省略为 public）；旧字段 `allow_internet` | 与 compose 的 `network_mode: service:…` 分开。`allowlist` 和按阶段覆盖直接失败（`harbor_network_unsupported`），不会当成 public |
| `user` | 只接受数字 UID；用户名拒绝 |
| `[[verifier.collect]]` 然后顶层 `artifacts` | `evaluation.collect`：先跑命令，再拷贝绝对路径 |

`storage_mb`、verifier 容器的 CPU/内存、`skills_dir`、`solution.env` 记入 `parameters.harbor_known_gaps`，不假装已经生效。`steps`、Windows、MCP、healthcheck、TPU 直接拒绝。

Agent 绑定仍来自 `--agent` / `--profiles`（角色 id 为 `solver`）。`--oracle` 才运行 `solution/solve.sh`；省略时 `solution/` 不进入评分路径。

当多个任务共享相同的交互逻辑时，可将公共模块置于 dataset 根目录的 `shared/lib` 下，由各任务的 `run.py` 导入（Runtime 注入的 `sys.path` 前缀为 `[task_dir, dataset_root]`）。参考材料（`gold`）严禁放入 `shared/`。Docker 构建不会隐式拷贝 `shared/`；若容器内脚本需导入 `shared.lib.*`，需在 Dockerfile 中显式 `COPY` 并将 dataset 根目录加入 `PYTHONPATH`。

## 运行配置文件 `profiles.yaml`

```yaml
format: ageval.profiles/1
environment: local          # local | docker | e2b | ssh | daytona
# environment_options:      # docker: image / platform / network / user / egress / egress_allow / python_version
#                           #         以及可选 network_mode / cap_add / main_environment
#                           # ssh: host / user / port / key_env / image
#                           # daytona: image / snapshot / timeout_seconds
# evaluate_host:            # 省略时复用 run 阶段环境进行评分
#   isolated: true
#   environment_options:    # 独立评分容器自身的网络与平台配置（network / egress / egress_allow / platform / user / python_version）
agent_profiles:
  solver:
    executor: acp
    model: …                # 嵌套 ModelSpec 字段见 16-model.md
    api_key: ${ZHIPU_API_KEY}
    options:
      entry: pi
    extensions:
      - plugin: acp
      - plugin: local
```

- `environment_options` 配置 `run` 阶段环境；凭据 locator 在 `preflight` 阶段解析，明文密钥不进入 lock digest。
- `evaluate_host.isolated: true` 要求任务具备评分容器配方且环境类型支持启动独立容器（当前为 `docker`），否则 `lock` 失败。`evaluate_host.environment_options` 配置独立评分容器自身的 `network`、`egress`、`egress_allow`、`platform`、`user` 与 `python_version`；省略时仅继承顶层 `environment_options` 的 `platform`、`user` 与 `python_version`，不继承待测 Agent 环境的 `egress`、`egress_allow` 或 `network`。
- `egress_allow` 为小写主机名列表，必须与同一字典下的 `egress: llm` 同时声明（当前仅支持 `docker`）；有效放行列表为对应阶段绑定角色的 `base_url` 主机名与 `egress_allow` 的并集。
- `evaluation.environments` 定义多命名评分容器配方（键名匹配 `[a-z][a-z0-9_-]*`），每项指定 `dockerfile`（相对任务目录，禁止位于 `evaluation/` 下）或 `docker_image`，并要求 `evaluate_host.isolated: true` 且 `environment: docker`。
- `artifacts.publishable[]` 支持 `id`、`path`、`kind`（`file` | `tree`，默认 `file`）与 `exclude`（仅 `tree` 模式）。当 `evaluation.inputs[].target` 设为 `workspace` 时，将对应的 `tree` 快照恢复至评分环境的 `/attempt/workspace`；否则文件产物放置在 `/attempt/artifacts`。

## 配置字段归属

| 字段 / 目录 | 消费者 |
| --- | --- |
| `parameters` | 注入 `ctx.params` 供 `run.py` 读取；在 `environment: docker` 下，`cpus`、`memory_mb`、`gpus`、`gpu_types`、`verifier_gpus` 以及 `network_mode`、`cap_add`、`main_environment` 同时作为容器启动参数（见 [environment](05-runtime/environment.md)） |
| `limits.*` | Core 运行时强制执行的阶段时长、调用次数与并发度上限 |
| `evaluation/` | `evaluate` 阶段上传的参考材料（gold） |
| `environment/` | 待测 Agent 环境配方与独立评分容器配方 |
| `data/` | `environment` 阶段上传至 `/attempt/workspace` 的初始文件 |
| `profiles.yaml` | 绑定环境插件、角色 executor、`ModelSpec` 及可选的 `evaluate_host` |

代码实现位于 `src/ageval/config/`（`dataset.py`、`profiles.py`、`load_and_lock.py`、`validate.py`、`digest.py`）。
