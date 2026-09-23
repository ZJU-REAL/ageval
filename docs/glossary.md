# ageval Glossary

这是**约束**，不是释义百科。机制定义仍以 [`design/`](design/) 为准。写文档或改文案前先读本文件：同一个概念只用规范名，Avoid 里的写法一律不许新造。

未知概念先补本表，再写进正文。不要现场起名。

## 表面

| 表面 | 范围 |
| --- | --- |
| **public** | 根 `README.md` / `README.zh-CN.md`、[`website/`](../website/)、`examples/**/README*` |
| **internal** | `docs/design/`、`AGENTS.md`、`ARCHITECTURE.md`、skills |

public 只许出现「public」或「both」行的规范名。internal 词出现在 public 里算错。

## 总原则

1. 有 CLI / 字段 / format 的词，中英都用同一个拉丁词（`dataset`、`lock`、`PASS`、`gold`、`limits`）。解释用中文短语，不另造术语。
2. 中文 public：**一次运行** / **整份 dataset 跑完**。`Attempt`、`suite` 留在英文、CLI、Hub 控件和 internal。
3. 对外说**环境**（本机 / Docker / E2B / SSH / Daytona）。`kind` 和槽只在 internal。禁止「盒子」。
4. `profiles.yaml` 叫**配置文件 / profiles**。Hub 上的表继续叫 **jobs**。禁止「job 文档」。
5. 中文「锁定」只用于 `ageval lock` / digest。口号里不要把 lock 当营销动词。
6. 禁止单独写 `isolated`。证据等级写全名；打分容器写 `evaluate_host.isolated` 或「另起打分容器」。
7. 全仓不写「硬顶」。中英都写 `limits`。
8. 家喻户晓且不是本项目切口的词可以留英文：Agent、Harness、PASS、skip、BYOK、BYOA。ageval 自己不是一种 Harness；包身份说 Agent 包。项目名（dsh、Harbor）可保留原词。
9. 禁止自造组合词当普通中英文用：fail-closed、fail-open、host-loop、in-box、in-image、oneshot（插件 id `acp-oneshot` 除外）、机制卡、字段糖、硬切、一层 C、探测管子、密封轨迹。Inbox、plaza 是普通英文，可留。

## 写法（public）

- 直接说谁做什么。删「此外」「至关重要」「不仅仅……而是……」「作为……的证明」。
- 不造隐喻，不挂三条口令。不要「一等评测维度」「harness 之下的 harness」「可见 Attempt」。
- 中文阶段名写 phase 名（environment / run / evaluate），可说「阶段」。Avoid：相位。
- 导航和专名写 **Core**，不译「内核」。
- 破折号不当节奏拐杖。金句删掉，换成可检验的事实。

检查：`python3 scripts/check_public_terms.py`。

## 词表

| 规范中文 | 规范英文 | 表面 | 含义（一句话） | Avoid |
| --- | --- | --- | --- | --- |
| ageval | ageval | both | 产品名 | AgEval 当产品名、agent-eval 当 CLI |
| dataset | dataset | both | 交付单位：根 `ageval.yaml` + `tasks/<id>/` | Database、`database_id`、task package；public 禁止「题包」 |
| （内部口语）题包 | — | internal | 仅口头，等于 dataset | 当作规范名；英文 task package |
| task | task | both | dataset 成员：`task.yaml` + `run.py` + `evaluator.py` | 题目、用例（指这一层时） |
| 配置文件 / profiles | profiles / `profiles.yaml` | both | 环境和 Agent 绑定写在这里 | job 文档、job 文件 |
| jobs | jobs | both | Hub / Viewer 上的运行记录表 | 用 job 统称一次运行或 `profiles.yaml` |
| Agent 包 | Agent package | both | format `ageval.agent/1`（executor、entry、overlays） | 把包身份叫 harness |
| Agent 运行时 / coding agent | agent runtime / coding agent | public | pi / Codex / Claude Code / dsh 等外部运行时 | 用 Harness 当 ageval 的产品主词 |
| — | harness | internal | 仅行业对比或项目名（Harbor、deepseek-harness） | harness 之下的 harness；一等评测维度；first-class eval axis |
| 一次运行 | Attempt | 见原则 2 | 一次外层执行；失败重试 = 新 Attempt。目录 `.ageval/runs/<id>/` | public 中文写 Attempt；可见 Attempt |
| — | Trial | internal | 一题 × 一套 profile（lock digest） | public 教 Trial |
| — | Run | both | CLI 顶层 `ageval run`，不当中文「一次评测」的规范名 | 用 run 指 Attempt |
| 整份 dataset 跑完 | suite | 见原则 2 | 一份 dataset 去掉 `--task` 的全成员跑。指标是观测，不是 suite PASS | public 中文写 suite（CLI `upload-suite` 除外） |
| Campaign | Campaign | both | `ageval campaign` 矩阵展开 | — |
| Core | Core | both | 产品层专名 | 内核、把 Runtime / 控制面写进 public |
| 环境 | environment | public | 本机 / Docker / E2B / SSH / Daytona | 盒子、box；public 写 kind |
| environment（槽） | environment slot | internal | 独占槽名；kind 是它的取值 | public 教槽 |
| kind | kind | internal | 环境类型字段 | public 当正文词 |
| executor | executor | both | `profiles.yaml` 里 Agent 后端字段 | Agent 后端当规范名 |
| 独占槽 | exclusive slot | internal | 每个 graph 一个实现 | public 写独占槽 / 赢家 / exclusive-slot winner |
| 链槽 | chain slot | internal | phase 内钩子 | public 写链槽 |
| inject / export | inject / export | internal | lock 期按名取服务 | public 写按名注入 |
| `ageval lock` / digest | lock / digest | both | 合成可复现绑定。中文「锁定」只指这件事 | 一并锁定、锁定评测维度 |
| limits | limits | both | 执行前强制的墙钟 / 内存 / 进程 / 调用次数 | 硬顶、配额、ceilings |
| 参考答案 | gold | both | 评分对照的标准答案，在 `tasks/*/evaluation/`；evaluate 才 upload。zh public 写「参考答案」，EN / CLI / 路径用 gold | 金标；zh public 直接写 gold |
| evidence | evidence | both | 目录 `.ageval/runs/<id>/` | 用 evidence 指那条 jsonl；存证 |
| 轨迹 | trajectory | both | `trajectory.jsonl`。复盘用，不能发明 PASS | 用轨迹指整个 runs 目录 |
| checks | checks / `evaluation/checks.json` | both | 确定性 evaluator 可选返回的检查项观察；parent 写入 `evaluation/checks.json`。不是 PASS | 把 check 退出码 / stdout 当 PASS；Verifier 检查点 |
| 投影 / Agent 能看见 | projected workspace | both | Agent 看见的文件 | 单独写「可见性」指这件事 |
| 公开 / 私有 | public / private | both | Hub 范围。CLI 旗标仍是 `--visibility` | 单独写可见性、visibility 当正文（旗标除外） |
| PASS / FAIL / ERROR | PASS / FAIL / ERROR | both | 见下 | completed、轨迹完整当通过；用超时文本决定 FAIL |
| 阶段 | phase | both | environment → run → evaluate → record；cleanup 始终执行 | 相位；用「步骤」指这些阶段（轨迹 tool step 除外） |
| attach_stdio | attach_stdio | both | 已开环境里起前台进程，交回 stdin/stdout | — |
| ACP entry | ACP entry | both | `options.entry`：`pi` / `codex` / `claude-code` / `opencode` / `grok-build` | — |
| capabilities | capabilities | both | 环境声明能兑现什么；`requires ⊆ capabilities`，否则 lock 失败 | — |
| BYOK / BYOA | BYOK / BYOA | internal | 密钥 / 本机 auth 投影 | public 不必教这两个缩写 |
| composition root | composition root | internal | `application/composition.py` | 不必中译 |
| 控制面 | Control Plane | internal | — | public 出现 |
| 检查不过就不能进入运行 | the check fails; the run does not start | both | 探测或配置检查不过，就不能进入真正运行 | fail-closed、fail closed |
| bake | bake | internal | 镜像在 build 期写入 | 烘焙；public 写「写入镜像」 |
| isolated | isolated | — | 禁止单独出现。证据等级写 `runnable-mvp` 等全名；字段写 `evaluate_host.isolated` | isolated 当形容词裸用 |
| —（内部分级，勿外露） | evidence grade | internal | `runnable-mvp` 等内部验收分级，只在 AGENTS / Issue / evidence 声明里出现 | public 出现「证据等级 / evidence grade」；「证据等级升级 / evidence-grade upgrade」当公开文案——public 写事实：「不影响评测结果」「不会让结果更可信」 |

### PASS / FAIL / ERROR

| 词 | 含义 |
| --- | --- |
| **PASS** | 只来自 `evaluator.py` 绑定的 `status: PASS`。`RunTerminal.completed`、轨迹、ACP `end_turn`、`limit` 都不是 PASS |
| **FAIL** | 只来自 `evaluator.py` 绑定的 `status: FAIL`（评测低分）。run 阶段触到的 limit 仍由 evaluator 打分 |
| **ERROR** | 环境起不来、environment / evaluate 时钟到期、evaluator 崩或返回的 status 不是 PASS / FAIL、配置。`result.json` 的 `limit` 是 run 阶段触到的 limits 键，没有则为 `null` |

## format

`ageval.dataset/1` · `ageval.task/1` · `ageval.plugin/1` · `ageval.profiles/1` · `ageval.agent/1` · `ageval.trajectory.event/1`

未知 format：一个错误，停。
