# ageval Agent 指令

本文件是仓库级 **Agent / 贡献者路由**：说明读什么、谁说了算、当前事实、不可违反的边界，以及如何交付与校验。  
机制设计正文在 [`docs/design/`](docs/design/)；结构地图在 [`ARCHITECTURE.md`](ARCHITECTURE.md)；增量交付在 **GitHub Issues**。

## 产品名

| 项 | 值 |
| --- | --- |
| 全称 / 发版名 | **ageval**（agent eval） |
| 交付单位 | **dataset**（`ageval.dataset/1`），不是 SQL |
| CLI / 包 | `ageval` / import `ageval` |
| 家目录 / 环境变量 | `~/.ageval`、`AGEVAL_*` |
| GitHub 路径 | [`ZJU-REAL/ageval`](https://github.com/ZJU-REAL/ageval) |
| 代际 | greenfield；不兼容归档 v1；未知 format 为 `invalid_format` |
| v1 只读参考 | 本机归档 v1（勿 import、勿假设 API 兼容） |

## 必读顺序

修改代码、契约或公开行为前，**按序**阅读：

1. [ARCHITECTURE.md](ARCHITECTURE.md) — 当前/目标结构、模块所有权、依赖方向、生命周期与数据流
2. [docs/README.md](docs/README.md) 与本次相关的 [docs/design/](docs/design/) — **设计权威（自包含）**；用词先读 [docs/glossary.md](docs/glossary.md)（规范名 + Avoid + 表面）
3. [docs/PRD.md](docs/PRD.md) — 产品规格与非目标
4. 相关 **GitHub Issue**（Acceptance / 非目标 / 证据要求）
5. 代码、测试、`examples/`、公开 smoke

读者向产品文档在 [`website/`](website/)（可选阅读）；**不**拥有设计真理。

## 权威顺序

```text
docs/（PRD + design/*）     ← 产品与机制设计权威；自包含
  → ARCHITECTURE.md         ← 实现结构权威（当前 vs 目标、所有权、依赖）
  → GitHub Issues           ← 增量交付、讨论与验收跟踪（主轨道）
  → 公开 smoke / 代码 / 测试 / evidence

website/                    ← 读者向产品文档（重写）；不拥有设计真理
apps/* / services/* README  ← SPA / 服务开发细节；非产品教程权威
```

### 冲突处理

1. 停止冲突实现。
2. 判断是设计变更、结构变更、范围变更还是实现偏差。
3. **先改最高权威 artifact**（设计 → `docs/`；结构 → Architecture；交付跟踪 → Issue；实现 → 代码）。
4. 同一变更内同步下游（README、skills、website 相关页、测试、证据声明）。

### 与历史 SDD 脚手架的关系

仓库**已移除**仓内 `specs/`（Active Spec / ROADMAP / constitution / BLOCKED）。  
历史 Git 中仍可查阅；日常**禁止**再新建 Spec 工作区或勾选机。  
设计已定稿在 `docs/`（自包含）；交付跟踪在 Issues。

曾有仓外 BRIEF 作为一次性施工 brief。**产品模型已吸收进本仓 `docs/`。** 不要再读 vault / BRIEF 当权威，不要两套设计。

## 当前事实

| 项 | 状态 |
| --- | --- |
| 设计 | `docs/`（PRD + design 00–14 + glossary）**自包含**；不要读仓外 BRIEF |
| production 源码 | Config → `attempt.run_attempt` 五个阶段 → 环境 kind → ACP `attach_stdio` → 环境内 evaluate → evidence；`src/ageval/plugins/` 注册表 + contrib；外置 `plugins/` |
| 公开 entrypoint | `ageval lock` / `run` / `campaign` / `view` / `evidence` / `plugin` / `jobs` / `results` 等（以 `ageval --help` 为准；`ageval run` 输出 `logs` locator） |
| 环境 | `local` / `docker` 有公开真 run；`e2b` / `ssh` / `daytona` 代码在，缺钥则 `--probe` 过不了，不能进入运行，**不得**标完成 |
| 证据等级 | **限定 `runnable-mvp`**（core local/docker ACP、`minimal-demo` 明确列出的示例）；见 [examples/README.md](examples/README.md)；**不得**扩写全 suite `isolated` |
| 交付跟踪 | **GitHub Issues** |
| 文档站 | [`website/`](website/) 读者向 Fumadocs；机制权威仍在 `docs/` |
| ACP | `executor: acp` + `options.entry`；parent 唯一 JSON-RPC client |
| Agent Hub | [docs/design/14](docs/design/14-agent-hub.md)：`ageval.agent/1` harness；`--agent` 与 `--profiles` 互斥；`--model` 是 run 参数 |

**禁止**从文档存在、Issue 存在、`ageval lock` 成功或设计示意推导 `runnable-mvp` / `isolated` / `real-benchmark-verified`。

## 四条硬规则（施工）

### 1. 不向后兼容

不兼容旧名。没有迁移层、没有双读、没有旧名别名。

- format 只认 `ageval.dataset/1`、`ageval.task/1`、`ageval.plugin/1`、`ageval.profiles/1`。
- 未知 format：**一个**错误（`invalid_format` 于 `/format`），停。不要在报错里教映射。
- 环境变量 / 家目录 / CLI 只有 `AGEVAL_*`、`ageval`、`~/.ageval`。
- `provider.kind`、`assurance`：拒绝或删除，不翻译。

### 2. 删除优先于缝补

旧路径和新路径不能并存。新路径能跑的同一刀里删旧文件。

- 禁止：`compose_from_*` 别名、空壳转发、`NotImplemented` 占位、两套 Agent Service 并存。
- 禁止：为了「先绿」包一层 try/except 把旧模块藏起来。
- 碰到 `EnvironmentManager`、`wrap_docker_exec`：删。逻辑进 design 指定的新位置，或不做。

### 3. 禁止 mock / fake

没有产品级 `executor: mock`。没有 `FakeHost` / 空 `AgentService` 充当完成证据。

| 允许 | 禁止 |
| --- | --- |
| `environment: local`（真文件系统） | `FakeHost`、内存环境当验收 |
| `environment: docker`（真容器） | mock docker SDK 当该面完成 |
| 真 ACP CLI + `attach_stdio` | stub Agent Service、进程内假 worker |
| 凭证没有时 **跳过** 该 job | 用假 agent 把测试标绿再标完成 |
| 测试打真实 `ageval lock` / `ageval run` | 只测内部函数当公开 smoke |

`AGEVAL_SKIP_REAL_ACP=1` 只表示 **CI 没跑这条**。没跑 ≠ 通过。

### 4. 禁止防御性编程

写直路。失败就失败。

- 不要为每个旧字段写友好错误码表。未知键：拒绝，一条消息。
- 不要 `try/except Exception` 收成 `{"status":"ERROR"}` 再继续（evaluate 边界按相位记失败除外）。
- 不要未证实的探针、重试、兼容层。
- 配额、缺 cap、缺凭证、缺 `attach_stdio`：lock 或 invoke **一次**失败。

## 项目边界（Agent 不可违反）

### 架构与所有权

- **Core：** Config `load_and_lock`；Attempt 五个阶段；环境 Protocol；Capability；停写后再打分 与结果绑定。
- **Agent 只能看见允许的文件**是能力；gold 靠 **不 mount + 评测前 upload**，禁止只靠「配置里删字段」。
- **题包 `run.py`** 拥有 Attempt 内业务 workflow（loop、角色、本地 Tool、handoff）。
- **SDK** 可选；可被 upstream Framework 替代；**不**拥有 Run identity、环境控制、credential、final PASS。
- Control Plane **不** import/execute 题包 `run.py` 或 evaluator **模块**；经进程/适配器边界调用。
- 具体平台对象只在 **production composition root**（`application/composition.py` 的 `build_*`）连接。
- 第三方 Agent/workflow SDK 不得成为 Core identity / effect / verdict authority。
- **禁止 marker 生命周期：** `cleanup` / `evaluate` / `bind` 不得只返回空 `_fact` 而生产另有一份真逻辑。
- 一次 Attempt 只允许一次 `IdentityFactory.new_run`（测试 double 除外）。
- CLI 只 import `ageval.application.composition`。
- `.ageval/runs` 布局字符串只在 `evidence/`。
- 新的 `application` 公开用例必须有 `build_*`。
- Registry Handler 不得直接 `state.meta` / 再 `_bearer`；业务在 `*Service`。

### 结构红线（design §4.10）

1. `attempt/` 打开 `attempt/__init__.py` 就能说出阶段。禁止再摊成按隔离档分叉的生命周期文件。
2. 测试面 = **真实 kind + 公开 CLI**。docker / e2b 的 seam 成立条件是两个真实赢家，不是 FakeHost。
3. **禁止文案 grep 测试。** 不要 `read_text` 落地页 / `website/` snippet / README，再 `assert "某字符串" in/not in text`。那不证明 invoke、lock 或 Protocol，改一句宣传就假红。读者向对了就改文档；行为对了就测 `ageval lock` / `run` / 环境方法。架构测试只钉运行时红线（import、slot、composition root）。
4. locality：`docker exec` 只在 docker contrib。ACP / `attempt` / `run.py` 不见 `container_id`、不见 `if kind == e2b`。
5. 一条路径：选环境 / executor 只经独占槽。禁止第二套 resolve。
6. 平台对象只在 `application/composition.py` 的 `build_*` 接线。
7. 控制面不 import 题包模块。
8. PASS / 身份 / cleanup 不是插件服务。cleanup 在 `try/finally`。
9. 适配器按机制命名。禁止按 bench / task 名分支。
10. 布局字符串只在 `evidence/`。lock / evidence 不写 host token。
11. inject 在 lock 完成。缺 `attach_stdio` 就 lock 失败。

### 安全与评测

- `RunTerminal.completed` **≠** PASS；PASS 只能来自独立 evaluator。
- Runtime outcome、Agent 结果、evaluator raw、最终 evaluation 保持为**独立事实**。
- 不复制、序列化或把 host credential / token 写入 lock、evidence 或题包默认环境；仅 scoped projection 给获准进程。
- `limits` 由 Runtime **执行前**强制；`run.py` 不可自提。事后 token/cost 默认只作观测。
- Adapter / 插件按**协议、资源类型或执行机制**命名；**禁止**按 Benchmark / task / domain 名分支。
- 插件模型 = entry point + 包安装；**不是**开放应用商店。Agent Service 留主仓。

### Agent 后端 / ACP

- Coding-agent **Target inlet**：`executor: acp` + `- plugin: acp` / `options.entry`；parent **唯一** ACP JSON-RPC client → evidence。
- Vendor 私有格式翻译在 **进程外** ACP entry（Mode 1 shim / Mode 2 原生 / Mode 3 厂商包）；**禁止**在 ageval 内再写第二套 vendor stdout scrape。
- **官方 Attempt 镜像** `src/ageval/plugins/contrib/docker/attempt/` 在 **build 期** 写入镜像 最低 entry 的 engine + ACP 入口（Mode 1 **同时装 engine 和 adapter**：codex/claude/**pi** + 各自 adapter）。配方打进 wheel；`ageval run` 从包内路径构建，不依赖 cwd checkout。题包配方再叠 ACP `image_layers`，只 bake 绑定的 `options.entry`；禁止 invoke 时 `npm i` / floating `npx`。Python ACP SDK **只在 parent**，不进 Attempt 镜像。
- Pi：官方 registry **`pi-acp`**（npm `pi-acp`，桥 `pi --mode rpc`）；勿与反向桥 `pi-shell-acp` 混淆。
- **可见性**：mount + `docker exec -u/-w` + UID/GID（只在 docker contrib）。**Permission**：batch 默认 ACP auto-approve，**不**提权、**不**突破未投影路径；evidence 记录 decision。
- 权威：[docs/design/05-runtime/agent-service.md](docs/design/05-runtime/agent-service.md)。

### 多 Agent 调度

- docker 上多 actor 必须与 local 相同 SDK 表面：`Agent.session(...).invoke`；**禁止**悄悄改回宿主机。
- YAML 只声明逻辑 isolation（`shared-container` / `container-per-group`、groups、actors、`shared_write`）；container id / UID 由 Runtime 拥有。
- 详见 [`docs/design/05-runtime/`](docs/design/05-runtime/) 与 ARCHITECTURE Current。本轮 **不**承诺多 group 真调度 run（lock 有 topology 即可）。

### Package 与配置

- 规范交付单位为 **dataset**（根 `ageval.yaml` / `ageval.dataset/1`）；每 task 为成员 `task.yaml`；Config Core 是唯一规范读取者。
- `parameters` 给 `run.py`（`ctx.params`）；envelope / profiles / limits 给 Runtime；禁止 `run.py` 再读第二份「真配置」覆盖 lock。
- 环境变量只作 locator，不能代替生产机制来源。
- job 选环境：`profiles.yaml` 的 `environment:`，不是 `provider.kind`。

### 交付与证据

- **新工作默认开 GitHub Issue**（写清 Acceptance / 非目标 / 证据）；**不**新建仓内 Active Spec / ROADMAP。
- Fixture/mock 只能作自动化回归，**不能**单独充当公开 smoke 或升级证据等级。
- 不要为落地页 / README / website snippet 写「文件里有没有某句」的 pytest；见结构红线第 3 条。
- 实现期安全可逆选择可自行推进；需新权限/不可逆/改产品安全语义时先问用户或写在 Issue。
- `docs/reference/` 是归档，**不是**权威，也不是 vault 入口。
- **有 `website/` ≠** 证据等级升级。

## 交付规则（操作）

| 情况 | 做什么 |
| --- | --- |
| 改产品/机制设计 | 先改 `docs/design/*`（及必要时 PRD/glossary），再改 Architecture / 代码 / website 相关页 |
| 改模块树/依赖/composition root | 先改 [ARCHITECTURE.md](ARCHITECTURE.md) |
| 增量功能 / 验收跟踪 | 开或更新 **GitHub Issue**；实现与 PR 链 Issue |
| 教人怎么用（CLI / Viewer / Hub） | 更新 [`website/`](website/)；开发细节留在 `apps/*` / `services/*` README |
| 未授权实现 | **不**创建无依据的 production 行为变更 / 不跑「假装完成」的 smoke 声明 |

跟踪 Markdown 使用**仓库相对链接**。不要在 AGENTS/Architecture 里写死仅本机可用的绝对路径作为权威链接（归档路径可用文字说明）。

### 对外文档禁止 Issue 编号痕迹（硬规则）

**读者向 / 对外文档不得出现 GitHub Issue 编号**（如 `#66`、`#59`、`Issue #60`、`Closes #xx` 文案）。

| 适用 | 不适用（可保留 Issue 引用） |
| --- | --- |
| 根 `README.md` / `README.zh-CN.md` | `AGENTS.md`、`ARCHITECTURE.md`（贡献者路由） |
| [`website/`](website/) 全部读者向正文（中/英） | `docs/design/*`、内部 PR/Issue 讨论 |
| `examples/**/README*` 及包内读者向说明 | 实现与 PR 描述里的 `Closes #N` |
| 产品站、教程、公开 smoke 叙述 | 测试名 / 代码注释若仅开发者可见（仍宜少写） |

**写法：** 用产品语义写边界（例：「monorepo 只收缩略版 tau3-airline-5；更大 bench 只走 Hub」），**不要**用「#66 交付边界」这类交付跟踪编号当章节标题或正文标记。  
改文档时若发现对外文面有 `#数字` Issue 痕迹，**先删再合**；中英文同步。

## 证据等级

| 等级 | 含义 | 何时可声称 |
| --- | --- | --- |
| `design-only` | 仅文档 | 未被公开 smoke 覆盖的路径 |
| `runnable-mvp` | 真实 public entrypoint + 真实 Agent 路径 | 有对应公开 journey 证据时 |
| `isolated` | 隔离 Attempt + 隔离红线 | 有对应隔离验收证据时 |
| `real-benchmark-verified` | 固定 upstream + 限定范围公开 journey | 有对应验收证据时；不得扩写成全 suite |

## 校验

### 何时跑 CI 门禁（必须强调）

| 操作 | 是否本地先跑通 CI |
| --- | --- |
| **日常本地 commit** | **不需要**每次全量 CI；按改动路径跑对应门禁即可 |
| **`git push`**（尤其推到将合入 `main` 的分支） | **需要**：先本地跑通与 [`.github/workflows/ci.yml`](.github/workflows/ci.yml) 等价的相关 job |
| **开 / 更新 PR**、**发版 / 打 tag / 发布** | **必须**先本地确认会触发的 CI job 会过，再 push / 开 PR / 发版 |

Agent 在协助 push、PR、发版前：**不得**假设「本地能 import」或「只改了文档」就跳过；应按路径跑下面 **CI 等价命令**（或明确说明已跑且通过）。失败则先修再推。

### CI 门禁（path-filtered 并行 job）

| Job | 触发路径（摘要） | 本地等价 |
| --- | --- | --- |
| `python-core` | `src/` `sdk/` `tests/` `examples/` `services/` `docker/` `scripts/` `pyproject.toml` `uv.lock` `VERSION` … | 见下方 Python core |
| `python-registry` | 同上（与 core 并行；仅 `tests/registry`） | `uv sync --frozen --extra registry` + `pytest tests/registry` |
| `viewer-app` | `apps/viewer/**` | `pnpm --dir apps/viewer install --frozen-lockfile && pnpm --dir apps/viewer lint && pnpm --dir apps/viewer build` |
| `hub-app` | `apps/hub/**` | `pnpm --dir apps/hub install --frozen-lockfile && pnpm --dir apps/hub lint && pnpm --dir apps/hub build` |
| `website` | `website/**` | `pnpm --dir website install --frozen-lockfile && pnpm --dir website build` |
| `design-tokens` | `docs/design/13*` / token 脚本 / 三端 CSS | `python3 scripts/check_design_tokens.py` |

`.github/workflows/ci.yml` 变更会重跑全部 job。纯 SPA / 纯 website 变更**不**跑全量 Python。  
默认 CI **无**真 Docker e2e、**无**真 Agent/API e2e、**无**真 E2B/SSH。那些 skip **不是** Acceptance 通过。

#### Python core（`python-core`）

```bash
uv sync --frozen
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
export AGEVAL_OFFLINE_AGENT=1 AGEVAL_SKIP_DOCKER=1
export AGEVAL_SKIP_REAL_CODEX=1 AGEVAL_SKIP_REAL_PI=1
export AGEVAL_SKIP_REAL_OPENCODE=1 AGEVAL_SKIP_REAL_ACP=1
# pytest 的 --ignore 列表必须与 .github/workflows/ci.yml job python-core 完全一致
uv run pytest --ignore=tests/registry -q
```

#### Python registry（`python-registry`）

```bash
uv sync --frozen --extra registry
export AGEVAL_OFFLINE_AGENT=1 AGEVAL_SKIP_DOCKER=1
uv run pytest tests/registry -q
```

若改动触及 docker / 真 Agent / e2b / ssh 路径，须按 Issue 或相关测试补跑（那些**不**在默认 CI 内）。  
分支保护 required checks 须包含上述 job 名。

## 相关入口

| 文档 | 用途 |
| --- | --- |
| [`.agents/skills/`](.agents/skills/) → [`skills/`](skills/) | clone 后可发现的 skills（ageval-platform / cli / config-package / sdk-harness / plugin） |
| [README.md](README.md) | 人类入口与状态 |
| [website/](website/) | 读者向产品文档（中/英） |
| [docs/design/00-overview-and-product.md](docs/design/00-overview-and-product.md) | 产品模型、US1–US12、命名 |
| [docs/design/01-ageval-core.md](docs/design/01-ageval-core.md) | Core：lock + 五个阶段 + 环境 |
| [docs/design/09-owner-matrix-and-structure.md](docs/design/09-owner-matrix-and-structure.md) | Owner 矩阵 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 源码树、依赖、生命周期图 |
| [GitHub Issues](https://github.com/ZJU-REAL/ageval/issues) | 增量交付与验收跟踪 |
