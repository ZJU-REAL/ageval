# ageval Glossary

本文规定仓库文档与对外文案的术语规范。机制定义以 [`design/`](design/) 为准。撰写或修改文档前请先核对本表：同一概念只使用规范名称，Avoid 列中的内部口语或自造黑话不得写入文档。

## 适用表面

| 表面 | 范围 |
| --- | --- |
| **public** | 根 `README.md` / `README.zh-CN.md`、[`website/`](../website/)、`examples/**/README*` |
| **internal** | `docs/design/`、`AGENTS.md`、`ARCHITECTURE.md`、skills |

public 表面使用标记为 `public` 或 `both` 的规范名称；仅标为 `internal` 的实现符号（如内部类名、协议名）不直接作为用户教程概念。

## 基本原则

1. 具有 CLI 命令、配置字段或 schema format 的概念，中英文统一保留拉丁标识符（如 `dataset`、`task`、`lock`、`PASS`、`gold`、`limits`、`Attempt`、`suite`），中文辅以自然说明，不另造生僻译名。
2. 可交付的 Agent 由 **Model + Harness** 构成。`harness` 指管理交互循环、工具调用与执行过程的运行时（如 `pi`、`Codex`、`Claude Code`、`OpenCode`、`miniswe`、`terminus-2`、`dsh`、`nooa`）；`ageval` 本身是评测框架，不是 harness。`ageval.agent/1` 打包产物称为 **Agent 包**（Agent package）。
3. 执行后端统一称为**环境**（`environment`：本机 `local`、容器 `docker`、云沙箱 `e2b` / `daytona`、远程主机 `ssh`）。禁止在文档中将环境或容器称为「盒子」「箱子」「打分盒」或 `box`（引用源码类名 `BoxSpec` 除外）。
4. 插件系统使用标准软件工程术语：**插件槽**（`slot`），分为**独占槽**（`exclusive slot`）与**链槽**（`chain slot`），以及**依赖注入**（`inject`）与服务导出（`export`）。禁止将独占槽绑定的插件实现称为「赢家」（`winner`），应写「独占槽实现」或「绑定的实现」。
5. 生命周期中的 `environment → run → evaluate → record` 统一称为**阶段**（`phase`）。禁止写「相位」。
6. `profiles.yaml` 称为**配置文件**或 `profiles`；Hub 与 Viewer 上的运行记录列表称为 **jobs**。禁止将 `profiles.yaml` 称为「job 文档」。
7. 资源与调用预算统一写 `limits` 或「资源上限 / 调用配额」，禁止写「硬顶」或 `hard ceilings`。
8. 禁止使用自造隐喻或工程黑话：如「题包」「证据包」「金标」「观察袋 / 插件袋 / 袋子」「层 B / 层 C」「时间切 / 空间切」「探测管子」「字段糖」「硬切」「机制卡」「勾选机」，也不要用量词「只」修饰会话、容器、环境或配额（如「一只 session」「那只容器」）。

检查脚本：`python3 scripts/check_public_terms.py`。

## 词表

| 规范中文 | 规范英文 | 表面 | 含义 | Avoid |
| --- | --- | --- | --- | --- |
| ageval | ageval | both | 产品与 CLI 名称 | AgEval 当产品名、agent-eval 当 CLI |
| dataset | dataset | both | 评测数据集交付单位：根 `ageval.yaml` + `tasks/<id>/` | Database、`database_id`、题包、task package |
| task / 任务 | task | both | dataset 成员：`task.yaml` + `run.py` + `evaluator.py` | 把单题目录称为题包 |
| 任务脚本 | task script | both | 任务目录下的 `run.py` 与 `evaluator.py` | 把 `run.py` 称为 harness.py |
| 配置文件 / profiles | profiles / `profiles.yaml` | both | 环境、角色 executor 与模型绑定配置 | job 文档、job document |
| jobs | jobs | both | Hub / Viewer 上的运行记录表 | 用 job 称呼 `profiles.yaml` |
| Agent 包 | Agent package | both | `ageval.agent/1` 配置包（含 executor、entry、overlays） | 把包格式本身称为 harness |
| harness / Agent 运行时 | harness / agent runtime | both | 管理交互循环与工具调用的待测运行时（pi、Codex、Claude Code、dsh、miniswe 等） | 把 ageval 称为 harness；受测；一等评测维度；first-class eval axis；harness 之下的 harness |
| 单次运行 / Attempt | Attempt | both | 单题单次执行，目录为 `.ageval/runs/<id>/`；重跑或重评会生成新 Attempt | 可见 Attempt |
| Trial | Trial | internal | 单题 × 单套锁定配置（lock digest）的多次采样序列 | 在基础教程中混用 Trial 与 Attempt |
| `ageval run` | Run | both | CLI 运行入口，不作单次 Attempt 的同义词 | 用 run 指代 Attempt 目录 |
| 整份 dataset 运行 / suite | suite | both | 省略 `--task` 时对 dataset 全部成员的执行，结果位于 `.ageval/suite-runs/<id>/` | 把 suite 汇总指标称为 suite PASS |
| Campaign | Campaign | both | `ageval campaign` 参数矩阵展开运行 | — |
| Core | Core | both | 运行时引擎专名，管理配置锁定与四个固定执行阶段 | 内核 |
| 环境 | environment | both | 本机 `local`、容器 `docker`、云沙箱 `e2b` / `daytona`、远程 `ssh` | 盒子、箱子、打分盒、box、in-box、in-image |
| 评分环境 / 评分容器 | scoring host / scoring container | both | `evaluate` 阶段运行评分命令或 judge 的环境实例 | 打分盒、scoring box |
| executor / 执行器 | executor | both | `profiles.yaml` 中角色绑定的 Agent 执行插件（如 `acp`、`openai-http`、`miniswe`） | — |
| 插件槽 | plugin slot / slot | both | Core 预留的扩展接入点 | — |
| 独占槽 | exclusive slot | both | 每个解析图绑定唯一实现并导出为同名服务的插件槽（如 `environment`、`executor`） | 赢家、独占赢家、exclusive-slot winner、exclusive winner |
| 链槽 | chain slot | both | 生命周期节点上按顺序串联执行的钩子槽 | — |
| 插件依赖图 / `ExtensionGraph` | plugin dependency graph / `ExtensionGraph` | both | `ageval lock` 解析出的槽位绑定与服务依赖图，驱动运行时调度 | — |
| 依赖注入 / 服务导出 | inject / export | both | 插件通过 `inject` 声明所需服务名与能力，通过独占槽或 `exports` 提供服务 | 按名注入 |
| `ageval lock` / 配置锁定 | configuration locking / lock / digest | both | 执行前校验组件契约、能力依赖与模型参数，生成配置摘要（digest） | 一并锁定、锁定评测维度 |
| limits / 资源上限 | limits | both | 执行前强制检查的时长与调用次数上限 | 硬顶、hard ceiling、hard ceilings |
| 参考材料 / 参考答案 / gold | reference materials / gold | both | `tasks/*/evaluation/` 下用于评分的标准答案与测试套件，仅在 `evaluate` 阶段上传 | 金标 |
| 执行证据 / evidence | evidence | both | 单次 Attempt 的归档目录 `.ageval/runs/<id>/` | 证据包、存证 |
| 轨迹 | trajectory | both | `trajectory.jsonl`（及评分阶段的 `evaluation/observation.jsonl`），仅作交互记录，不决定 PASS | 密封轨迹、层 C、layer-C |
| 扩展字段 / `extra` | `extra` field | both | `terminal.extra` 或 `summary.extra` 中的结构化附加观测数据 | 观察袋、插件袋、袋子、这袋 |
| 分析器 / analyzer | analyzer | both | 运行结束后对归档证据的只读分析（`stats` / `hack` / `review`），不修改 PASS 或 `checks.json` | — |
| 检查项 / checks | checks / `evaluation/checks.json` | both | `evaluator.py` 可选返回的分步检查明细，不直接替代顶层 PASS/FAIL | — |
| 工作区可见文件 | projected workspace | both | `run` 阶段向待测 Agent 暴露的工作区文件 | 单独用「可见性」代指文件挂载边界 |
| 公开 / 私有 | public / private | both | Hub 资源访问范围（CLI 参数为 `--visibility`） | — |
| 快照分享 | snapshot share | both | 只读分享链接 `/s/{token}`，默认定格在创建时的结果快照；`--live` 模式下随子任务完成更新 | — |
| PASS / FAIL / ERROR | PASS / FAIL / ERROR | both | 评测结果状态（定义见下表） | 把进程正常退出或轨迹完整当作 PASS |
| 阶段 | phase | both | `environment → run → evaluate → record`，以及 `finally` 中的 `cleanup` | 相位 |
| `attach_stdio` | `attach_stdio` | both | 在已启动环境中拉起前台进程并返回双向标准流（stdin/stdout） | 探测管子、attach 管子 |
| ACP entry | ACP entry | both | `options.entry`，包内内置 `pi` / `codex` / `claude-code` / `opencode` / `grok-build`，可叠加 `$AGEVAL_HOME/acp-entries.json` 中的自定义项 | 内置卡 |
| 能力标记 | capabilities | both | 环境插件声明支持的操作集合；lock 阶段校验 `requires ⊆ capabilities` | — |
| BYOK / BYOA | BYOK / BYOA | internal | 环境变量密钥投影 / 本机订阅认证文件按白名单复制 | — |
| 托管评测 / 托管运行 | hosted job | both | Hub 提交、后台 worker 在 E2B 或 Daytona 云沙箱中执行的评测作业 | — |
| 组织密钥 | org secret | both | 组织保存的模型密钥或云沙箱提供方密钥，列表接口不返回明文 | vault |
| 组合根 | composition root | internal | `application/composition.py`，生产环境对象唯一装配入口 | — |
| 控制面 | Control Plane | internal | 宿主父进程编排层 | — |
| 校验失败即终止 | fail fast before execution | both | 配置锁定或预检未通过时直接报错退出，不启动运行阶段 | fail-closed、fail closed |
| 构建期写入镜像 | image bake | both | 在镜像构建阶段安装运行时与依赖层，不在调用期间执行包安装 | 烘焙 |
| 独立评分容器 | `evaluate_host.isolated` | both | `evaluate` 阶段启动独立容器环境执行评分 | 禁止单独写裸词 `isolated` 指代评分容器 |
| 内部验收分级 | evidence grade | internal | `runnable-mvp` 等仓库内部交付验收等级，仅用于 `AGENTS.md` 与 Issue 验收说明 | 在对外文档中出现「证据等级 / evidence grade」 |
| `ModelSpec` | `ModelSpec` | both | 从角色 profile 嵌套 `model:` 解析出的独立模型配置规格（`id` / `api` / `reasoning_effort` / `timeout` / `watchdog` / `extra`） | — |
| `BaseEnvironment` | `BaseEnvironment` | internal | 环境插件抽象基类，配合 `@environment_plugin` 注册 | — |
| `BaseExecutor` | `BaseExecutor` | internal | 执行器插件抽象基类，实现 `supports_model` 与 `bind_model` | `consumes_model` |
| `extra_allowlist` | `extra_allowlist` | internal | 执行器类声明允许传递的 `model.extra` 键集合，空集合拒绝全部扩展键 | — |

### PASS / FAIL / ERROR

| 状态 | 含义 |
| --- | --- |
| **PASS** | 仅来自 `evaluator.py` 返回并绑定的 `status: PASS`。`RunTerminal.completed`、轨迹完成、ACP `end_turn` 或未触发 `limit` 均不代表 PASS |
| **FAIL** | 仅来自 `evaluator.py` 返回并绑定的 `status: FAIL`（未达到通过标准）。`run` 阶段触及 `limits` 后仍进入 `evaluate` 由 `evaluator.py` 给出 PASS 或 FAIL |
| **ERROR** | 环境启动失败、`environment` / `evaluate` 阶段超时、`evaluator.py` 崩溃或返回非 `PASS`/`FAIL` 状态、配置或收集错误。`result.json` 中 `error` 为 `{phase, title, message}`；PASS 与 FAIL 时 `error` 为 `null`，若 `run` 阶段触及配额则在 `limit` 字段记录对应键名 |

## Schema Formats

`ageval.dataset/1` · `ageval.task/1` · `ageval.plugin/1` · `ageval.profiles/1` · `ageval.agent/1` · `ageval.trajectory.event/1`

遇到未知 format 时直接报错 `invalid_format`（位于 `/format`）并终止，不做旧名兼容映射。
