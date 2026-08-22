# ageval

**agent eval** — 锁定 dataset，组合环境与 Agent，跑同一份题包。

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">中文</a>
  &nbsp;&nbsp;
  <a href="https://github.com/ZJU-REAL/ageval/releases"><img alt="Release" src="https://img.shields.io/github/v/release/ZJU-REAL/ageval?display_name=tag&sort=semver"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-blue"></a>
</p>

> [!IMPORTANT]
> 大多数 Agent 评测仍停留在**模型**层面：同一套提示、同一套工具约定，比较不同权重或不同 API。这一划分正在失效——可交付的 Agent 是 Model 与 Harness 的组合：同一套权重接到不同的 coding-agent 运行时、工具策略或环境隔离上，行为与成本都会变。因此要把 Harness 作为一等评测维度，与 Model、运行环境一并锁定。

**ageval** 把一次 bench 的 runtime 组成拆开：Environment 与 Agent 经插件组合，同一份 `run.py` 在不同绑定下运行。

## 目录

- [是什么](#是什么)
- [如何运行](#如何运行)
- [功能](#功能)
- [快速开始](#快速开始)
- [架构](#架构)
- [目录结构](#目录结构)
- [文档](#文档)

## 是什么

ageval 把 **Harness** 作为一等评测维度。

- **交付单位是 dataset。** 一份 dataset 含若干 task；每个 task 有业务循环（`run.py`）、评分（`evaluator.py`）和 gold。Environment 与 Agent 在 job 上绑定，不写进题包。
- **一次 Attempt 可见。** 顺序是 environment → run → evaluate → record，cleanup 始终执行。
- **Environment 按名注入。** 环境赢家 **export** 服务名 `environment`；Agent 后端 **inject** 这个名字，并 **require** 所需能力（`attach_stdio` 或 `exec`）。缺能力在 lock 失败。调用只打 Protocol。默认本机与 docker；云沙箱可选 [e2b](https://e2b.dev) 与 [daytona](https://www.daytona.io)。
- **Coding agent 通过插件接入。** 默认用 [ACP](https://agentclientprotocol.com) 跑 agent（[pi](https://pi.dev)、[Codex](https://github.com/openai/codex)、[Claude Code](https://github.com/anthropics/claude-code)、[OpenCode](https://github.com/sst/opencode)）；[nooa](https://github.com/NVIDIA-NeMo/labs-OO-Agents)、[dsh](https://github.com/deepseek-ai/deepseek-harness)、[miniswe](https://github.com/SWE-agent/mini-swe-agent) 等异构 harness 同样经插件进 runtime。开放 slot 用来替换 harness，走同一套 Attempt 与榜单。

## 如何运行

```text
            你 ── lock / run ──►  ┌─────────────────┐
                                  │     Attempt     │  锁定 dataset · digest
                                  │   ageval core   │  environment → run
                                  │                 │  evaluate → record
                                  │                 │  finally cleanup
                                  └────────┬────────┘
                                           │ 打开一个环境
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
        ┌───────────┐                ┌───────────┐                ┌───────────┐
        │   local   │                │  docker   │                │ e2b/ssh/daytona │
        └─────┬─────┘                └─────┬─────┘                └─────┬─────┘
              └──────── Protocol: upload · exec · attach_stdio ─────────┘
                                           │
                                           ▼
                                  ┌─────────────────┐
                                  │     run.py      │  任务循环 · 调用 Agent
                                  │  ACP / plugin   │  插件接入
                                  └────────┬────────┘
                                           ▼
                                  ┌─────────────────┐
                                  │  evaluator.py   │  PASS 的唯一来源
                                  └─────────────────┘
```

1. **锁定实验。** 将 dataset、Environment 与 Agent 合成为 digest。密钥仅作为 locator，不以明文写入 lock。
2. **打开环境。** 本机、docker，或云沙箱 / 远端。能力不足或凭证缺失时，在打开之前失败。
3. **执行题包。** `run.py` 负责循环、工具与 Agent 调用。更换环境或 Agent 无需修改题包。
4. **独立评分。** gold 在此时进入环境，由 `evaluator.py` 给出 PASS / FAIL / ERROR。cleanup 始终执行。

## 功能

**评测**

- **锁定一次实验。** dataset、Harness 与运行环境一并 lock，得到可复现 digest。绑定不同则分数不可比。
- **单题、整包、矩阵与重复。** 可运行单个 task、完整 dataset、同一 task 上的参数矩阵，或同一 job 的多次独立 Attempt（pass@k）。
- **评分与 Agent 分离。** gold 不进入 Agent 可见范围。PASS 仅来自 `evaluator.py`；轨迹用于检查。
- **上限在调用前强制。** 墙钟、内存、进程与调用次数由 runtime 在 invoke 之前强制；`run.py` 不得自行提升。

**组合**

- **同一份 `run.py`，更换绑定。** Environment 与 Agent 经插件组合。默认 [ACP](https://agentclientprotocol.com)；[nooa](https://github.com/NVIDIA-NeMo/labs-OO-Agents)、[dsh](https://github.com/deepseek-ai/deepseek-harness)、[miniswe](https://github.com/SWE-agent/mini-swe-agent) 等异构 harness 同样经插件接入。开放 slot 以补充和替换 harness，并走同一套 Attempt 与榜单。
- **Agent 包。** 将一次 job 的 Agent 绑定封装为 `ageval.agent/1`，安装后即可绑定。
- **多角色与多 session。** 题包拥有对话、工具与 handoff；runtime 提供环境与 Agent 入口。
- **调用前校验。** 能力与凭证在 Agent 调用之前核验；缺失则失败，不进入 invoke。

**环境**

- **本机、容器、云沙箱、远端，同一套 Protocol。** local、docker、[e2b](https://e2b.dev)、ssh、[daytona](https://www.daytona.io)：`upload` / `exec` / `attach_stdio`。
- **可见范围隔离。** Agent 仅看见投影后的 workspace；gold 与宿主凭据不进入题包默认环境。
- **官方 Attempt 镜像。** docker 在 build 期装入 ACP 入口，invoke 时不再安装。

**结果与协作**

- **本机 Viewer。** 按 Jobs → Tasks → Attempt 查阅轨迹、环境与评分。
- **密封轨迹。** 导出副本，不修改分数。
- **Hub。** 发布 dataset、插件与 Agent 包，上传 suite。组织管理成员、可见性与版本；公开榜仅收录完备且绑定 release 的 suite。部署可用 `docker compose -f services/registry/docker-compose.yml up -d`（Postgres、对象存储、Registry、Hub），发版标签会把 `ghcr.io/zju-real/ageval-hub` / `ageval-registry` 推到 GHCR。

**编写**

- **题包只承担该题。** 循环、工具、评分与 gold；编排不属于 task。
- **SDK 可选。** session、Tool、终端。不判定 PASS，不持有宿主凭据。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/) 与 CPython **3.12+**。实际运行 coding agent 还需要本机 ACP 入口与凭据。仅执行 `ageval lock` 时不需要。

```bash
git clone https://github.com/ZJU-REAL/ageval.git
cd ageval
uv sync --frozen --all-packages
uv run ageval -V
```

```bash
uv run ageval tasks examples/journeys
uv run ageval lock examples/journeys --task terminal-jsonl-agg
uv run ageval run  examples/journeys --task terminal-jsonl-agg
uv run ageval run  examples/journeys --task terminal-jsonl-agg \
  --profiles examples/journeys/profiles.e2b-acp.yaml --probe
uv run ageval executors -v
uv run ageval view examples/journeys --no-browser
```

`examples/journeys` 的默认环境为 docker。先执行 `ageval agent install examples/agents/pi-default`，再使用 `--agent` 绑定。

仓库内示例见 [`examples/README.md`](examples/README.md)：journeys、`tau3-airline`，以及 Agent 目录包。

## 架构

```text
  ageval.yaml + task.yaml + profiles.yaml
                 │
                 ▼
           ageval lock                 digest · extension_bindings
                 │
                 ▼
           ageval run  ── Attempt ── environment → run → evaluate → record
                 │                      finally cleanup
                 ▼
        .ageval/runs/<id>/             lock.json · result.json · trajectory.jsonl
                 │
      ┌──────────┼──────────┐
      ▼                     ▼
 ageval view          Registry / Hub
 本机 Jobs            publish · upload-suite · Leaderboard
```

- lock 是规范入口：未知 format 一次失败。插件改的是绑定，不重排 Attempt 的五个阶段。
- Attempt 管身份、时限、cleanup 与出分。
- 本机 Viewer 读文件；Hub 连 Registry。

## 目录结构

由 [`ARCHITECTURE.md`](ARCHITECTURE.md) 简化。`.ageval/`、`.venv/` 等生成目录不算源码。

```text
ageval/
├── src/ageval/
│   ├── cli/                         # 参数、帮助、退出码
│   ├── application/
│   │   ├── composition.py           # 生产接线唯一入口；CLI 只 import 此处的 build_*
│   │   ├── lock.py                  # load_and_lock
│   │   ├── run.py                   # 签发身份 → run_attempt
│   │   ├── campaign.py / suite/     # 矩阵 · suite · Always-k
│   │   └── agent_ops/ / plugin_ops / registry_ops/
│   ├── attempt/                     # 可见流水线
│   │   ├── __init__.py              # run_attempt
│   │   └── phases/                  # environment → run → evaluate → record · cleanup
│   ├── config/                      # dataset + task.yaml + profiles
│   ├── environments/protocol.py     # EnvironmentProvider · 能力；不含厂商 SDK
│   ├── plugins/
│   │   ├── slots.py                 # 独占槽 / 链槽
│   │   └── contrib/                 # acp · local · docker · e2b · daytona · ssh
│   ├── runtime/                     # 身份、父进程 Agent Service、task_worker
│   ├── evaluation/                  # 评测屏障 + 绑定 PASS
│   └── evidence/                    # trajectory.jsonl 布局
├── sdk/python/                      # run.py 用的 ageval_sdk（不判定 PASS，不持有宿主凭据）
├── plugins/                         # 外置 ageval.plugin/1（nooa、dsh、miniswe 等）
├── examples/
│   ├── journeys/                    # terminal-jsonl-agg · tau2-dialog-min · multiagent-env-min
│   ├── tau3-airline/
│   └── agents/                      # ageval.agent/1
├── apps/viewer                      # ageval view SPA
├── apps/hub                         # Hub SPA
├── services/registry/               # 包与结果 HTTP
├── docker/attempt/                  # 官方镜像；ACP entry 在 build 期装入
├── docs/                            # 机制设计
└── website/                         # 产品文档
```

## 文档

- 用法：[website/](website/)
- 设计：[docs/](docs/README.md)
- 示例：[examples/README.md](examples/README.md)
- [AGENTS.md](AGENTS.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
