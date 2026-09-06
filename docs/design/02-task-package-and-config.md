# 02 — dataset 与配置

交付单位是 **dataset**（根配置 + 若干 task 成员），不是 SQL。侧车 Postgres 仍叫 compose service。lock 数据流见 [ARCHITECTURE.md](../../ARCHITECTURE.md) § Data Flow。

## 根

```yaml
format: ageval.dataset/1
dataset_id: example/minimal-demo
version: "0.1.0"
tasks:
  root: tasks
```

文件名 `ageval.yaml`。未知 format lock 失败：`invalid_format` 于 `/format`。

CLI 路径永远是 dataset 根：

```bash
ageval lock examples/datasets/minimal-demo --task terminal-jsonl-agg
ageval run  examples/datasets/minimal-demo --task terminal-jsonl-agg
ageval tasks examples/datasets/minimal-demo
ageval run  official/demo@0.1.0 --dir tmp
```

`run` / `lock` / `view` / `results upload-suite` 第一个参数是本地 dataset 根 **或** Hub ref（`dataset_id@version` / `@sha256:…`）。`--dir <path>` 只在 `run` 上、且只配合 Hub ref：在 `<path>/<dataset_id>/` 找包（例：`--dir tmp` + `official/demo@0.1.0` → `tmp/official/demo`）。子目录已是匹配 dataset 就复用，否则 fetch 进去再 run。相对路径相对 cwd。本地路径再加 `--dir` 是 `invalid_override`。`lock` / `view` / `upload-suite` 走已校验缓存，命中不打 Hub。`tasks` / `campaign` 仍只收本地目录。

`--profiles` 整份替换根上的配置文件。`--agent` 与 `--profiles` 互斥。`--model` 须配合 `--agent`，改已绑角色的 `binding.model`（包缺省否则保留）。`--set` 白名单：`/parameters/seed`、`/parameters/active_profile`、`/bindings/<role>/{model,executor,api_key,base_url,options/<key>}`。`limits.*` 不可 `--set`。`ageval results --model` 是上传观测标签，不是这条糖。

## 成员 `task.yaml`

```yaml
format: ageval.task/1
task_id: acp-local-min
parameters:
  instruction: "…"
agent_profiles:
  - id: solver
limits:
  wall_time_seconds: 600
  agent_invocations: 1
artifacts:
  publishable:
    - id: reply
      path: artifacts/reply.json
    # kind 省略 / file = 单文件 harvest（今日）。tree = 工作区快照：
    # - id: repo
    #   path: workspace
    #   kind: tree
    #   exclude: [target, "*.so", .git]
evaluation:
  inputs:
    - artifact: reply
      target: artifacts/reply.json
  # docker_image: ageval-eval:grader   # 仅 isolated 且未写 environments 时认
  # environments:                      # 多只打分 Host；写出则忽略 evaluate.Dockerfile / docker_image
  #   audit:
  #     dockerfile: environment/evaluate/audit/Dockerfile
  #   verification:
  #     docker_image: ageval-eval:verify
```

## 薄 task 目录

```text
tasks/<id>/
  task.yaml                 # 只写例外；目录名 == task_id == --task
  run.py                    # async def run(ctx) — 仅 run phase
  evaluator.py              # 仅 evaluate
  environment/
    Dockerfile              # Agent 环境配方；有则用；docker 与 e2b 同一份
    evaluate.Dockerfile     # 单只打分配方；仅 isolated 且未写 evaluation.environments 时认
    evaluate/               # 按名打分配方（audit/Dockerfile 等）；gold 不放这里
    setup.sh                # 有则 environment_setup 去 exec（只跑在 Agent 环境）
  data/                     # Agent 可见 seed；environment 相位 upload 到 /attempt/workspace
  evaluation/               # gold；agent 不可见；evaluate 开头才 upload 到打分 Host
                            # 禁止把打分 Dockerfile 放这里
```

**缺省（有文件就认，不必在 yaml 再写一遍）：**

| 没写时 | 默认 |
| --- | --- |
| run 入口 | 存在 `run.py` → `run:run` |
| evaluator 入口 | 存在 `evaluator.py` → `evaluator:evaluate` |
| 镜像配方 | 存在 `environment/Dockerfile` → 用之；或 job `environment_options.image` / `docker_image` |
| 打分镜像 | 存在 `environment/evaluate.Dockerfile` → isolated 且未写 `evaluation.environments` 时用之；或成员 `evaluation.docker_image`。写出 `evaluation.environments` 则按名认 `dockerfile` / `docker_image`，忽略上面两份单只配方。省略 `evaluate_host` 则忽略全部打分配方 |
| setup | 存在 `environment/setup.sh` → `environment_setup` exec；没有则跳过 |
| `requires.environment` | 空 = 不额外要 cap |
| seed | 存在 `data/` → environment 相位 upload |
| gold | 存在 `evaluation/` → evaluate 相位 upload |

yaml 显式字段覆盖缺省。旧 `harness.entrypoint` 与未知 format **拒绝**，不映射。

不要：`provider.kind`、`assurance`、`harness:` 块、角色上的 `executor` / `api_key`（那些在 profiles）。

`run.py` **禁止**：`host.start`、`apt`、装环境、读 `evaluation/`。只做 session / invoke / 业务 Tool。环境在它被调用前已经就绪。ACP attach 发生在第一次 invoke。

多题同构时，循环放 `shared/lib`，成员 `run.py` 只转发。gold 永不进 `shared/`。Runtime 注入 path 前缀是 `[task_dir, dataset_root]`，不会把 `shared/lib` 叶子再塞进 path。docker 镜像 **不会** 由 Core 隐式 COPY `shared/`；容器内要用时在 Dockerfile 里显式 `COPY`，并把 dataset 根放进 `PYTHONPATH`。

## job `profiles.yaml`

```yaml
format: ageval.profiles/1
environment: local          # 或 docker / e2b / ssh / daytona
# environment_options:      # docker：image / platform / network / user（`root` 开 root）/ egress / egress_allow / python_version
#                           # ssh：host / user / port / key_env / image
#                           # daytona：image / snapshot / timeout_seconds
# evaluate_host:            # 省略 = 同一环境 evaluate
#   isolated: true
#   environment_options:     # 打分盒自己的 network / egress / egress_allow / platform / user / python_version；省略 = 不继承 agent 的 egress/egress_allow/network
agent_profiles:
  solver:
    executor: acp
    model: …
    api_key: ${ZHIPU_API_KEY}
    options:
      entry: pi
    extensions:
      - plugin: acp
      - plugin: local
```

`environment_options` 给 **run** 环境；locator 在 preflight 解析，密钥不进 digest。`evaluate_host.isolated: true` 要求成员题有打分配方，且 kind 能再起一份环境（Current：docker）；否则 lock 失败。`evaluate_host.environment_options` 是打分盒自己的旋钮（`network` / `egress` / `egress_allow` / `platform` / `user` / `python_version`；不是 `image`），要求 `isolated: true`；省略时打分盒只继承 job `environment_options` 的 `platform` / `user` / `python_version`，不继承 agent 的 `egress` / `egress_allow` / `network`。`egress_allow` 是 hostname 列表，必须与同一 map 的 `egress: llm` 同写（Current：仅 docker）；省略 = 该盒只放行相关 `base_url` 主机。未知顶键与未知嵌套键一次拒绝。

`evaluation.environments` 是成员题上的名 → 配方表。名字 `[a-z][a-z0-9_-]*`。每个名字只允许 `dockerfile`（题相对路径）或 `docker_image`（OCI tag），或两者（与今日单只配方同一识别规则）。未知键一次错误。`dockerfile` 必须存在且不得落在 `evaluation/`（那是 gold）。写出该表则：

- job 必须 `evaluate_host.isolated: true` 且 `environment: docker`，否则 lock 失败。
- 每个名字必须落到已有 Dockerfile 或非空 tag；缺文件 → lock 失败，不 start。
- 忽略 `environment/evaluate.Dockerfile` 与 `evaluation.docker_image`。

`artifacts.publishable[]` 允许键：`id`、`path`、`kind`（`file` \| `tree`，省略 = `file`）、`exclude`（仅 `tree`，字符串列表）。其它键一次错误，不映射。`evaluation.inputs[].target: workspace` 把对应 tree 铺到打分 Host `/attempt/workspace`；省略则 file 产物仍上 `/attempt/artifacts`。有名表时，**每只被 start 的** 打分 Host 各收一份快照拷贝。

## 所有权

| 字段 | 消费者 |
| --- | --- |
| `parameters` | `ctx.params` |
| `limits.*` | Runtime limits |
| `evaluation/` | evaluate 相位（gold；可含 `docker_image` 供单只 isolated；禁止放 Dockerfile） |
| `environment/` | Agent 环境配方；`evaluate.Dockerfile` 或 `evaluate/<name>/` 仅 isolated 打分环境 |
| `data/` | Agent 可见 seed |
| `profiles.yaml` | 选环境 / executor / entry；可选 `evaluate_host` / `egress` / `egress_allow` |

实现：`src/ageval/config/`（`dataset.py`、`profiles.py`、`load_and_lock.py`、`validate.py`、`digest.py`）。
