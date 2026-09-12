# 12 — Hub 与 Registry

字段是 `dataset_id`。无 `database_id` 双读。Hub / Viewer 文案用 dataset，不是 Database。无 `ageval submit`；上传走 `ageval results upload` / `upload-suite`。

公开 Leaderboard：完备 suite + 绑定 **release** + Dataset 包所属 org 的 owner 批准 listing（`board_listed`）。官方与非官方 Dataset 同一道门。`public` 不是上榜：可见性与 listing 分开。新上传默认未列出；listing 加上去之后，库里已有的 suite 也不会自动出现在公开榜上。Internal（调用方可见的不完备 / draft-bound）不变。公开 / Internal 默认列出该 Dataset 下全部已过上榜条件的 suite，不跟页顶版本走（`?v=` 只切 README / Tasks / lock 命令）。Public 右侧另有版本 Select：默认 All versions；`?dataset_version=` 按 suite 上传时带的 `dataset_version` 过滤。过滤不是新的上榜条件，也不改 listing / fingerprint / PASS。

单 Attempt `results upload` 通常上不了榜。正确路径：`ageval run <dataset>`（无 `--task`）→ `ageval results upload-suite --suite-run <id> --with-attempts`。申请人是 suite `uploaded_by`；不完备或 draft-bound 申请上榜会被拒绝。批准只写 listing 标记，不改 lock / fingerprint / overlay。

`--agent` 投影进 profiles 通道，与 `--profiles` 互斥。`agent_ref` 是 harness 溯源不是身份，不进 `config_fingerprint`（内置 Agent 包 vs 定制卡与 `--model` 见 [14](14-agent-hub.md)）。已上传 suite 允许延后把 published `org/name@version` 写入 **Registry 存的** `job_overlay`。Hub Share Attach：一句填空「Register `<role>` as `<agent>`'s `<model>`。」Role 仍是 overlay `all` / 点名一个 role 的 Select。Agent 与 Model 点开搜索弹层（Models Cmd/Ctrl+F 同款；Agent 同布局的 harness 列表）。Apply 在句右下。Model 可改挑 pin 里另一条 canonical，不是自由文本。Attach **资格**仍是 harness（executor + ACP entry），不含 model。所有 role 的 harness 相同时默认 `all`；否则默认从前往后第一个有匹配 agent 的 role，并填入该 agent。点名一个 role 时只写该 role 的 `agent_ref`，不要把同一 suite 里其它同 harness 的 role 一起 stamp。申请行的 `agent_ref` 保留 `role=` 前缀，批准走同一条 attach；`agent_performance` 另带 proposed `canonical_model`（可空）。Unique join 且申请人是 Agent owner / Maintainer：attach 成功并记下 canonical 桶。Unique join 且申请人不是 owner：开 / 建 `agent_performance`，带 proposed canonical，仍 **pending**，不经同意就写入。无唯一匹配：申请人仍可提交、**不能**指定桶；owner / Maintainer 批准时必须挑 canonical 或拒绝。批准可 override Model Select。Agent owner（内置 = Maintainer，定制 = org owner）可从 Performance 行打开与 Leaderboard 相同的 suite 详情页，设置里 Remove：只剥该 role 的 `agent_ref`（最后一条则撤 consent）。canonical 桶是展示 / join，不是第二份包。不是黑名单；再 attach 重新 stamp 即可。Collect 开关仍管 plaza 自动采集。同一 suite 一旦有指向本卡的 `agent_ref`，Performance 只列那些已 stamp 的 role，不再把未 stamp 的同 harness 队友一并归堆。Performance 对齐尺子：executor + ACP entry（**不含** model，也不含其余 secret-free plugin options；`reasoning_effort` 等同 model 的 run 参数）。**展示桶**在 join 之后按 canonical（见 [14](14-agent-hub.md)）；plaza自动采集用同一 matcher，唯一匹配不另留前缀孤儿组。suite 可比性仍走 `_binding_role_key`（含实际 model 与 options）。不改 Attempt `lock.json`、digest、PASS。`local/` 与 `file:` 不能当 Hub 溯源。plaza 源行（官方 Dataset + public + complete + release）的定义不变。

内置 Agent 包（builtin 短 id）的 **Performance** 默认自动采集 plaza 源行，按 overlay `resolve_agent_id` 归堆；model 展示桶再按 [14](14-agent-hub.md) 的 matcher join 到 canonical（无 unique hit 则仍按 overlay 原文）。Maintainer（`AGEVAL_REGISTRY_MAINTAINERS`，逗号分隔 GitHub login，与 official org 无关）是内置插件与内置 agent 的所有者：详情页右上角按钮打开 modal，采集模式为 `off` / `official`（默认）/ `official_and_personal`。`official` = 当前plaza。`official_and_personal` = plaza，再加非 official org Dataset 上同样 public + complete + release-bound 的 suite。`off` = 不自动采集，只收已同意的 `agent_ref`（Maintainer 直连 attach，或批准 `agent_performance` 申请）。非 Maintainer 不能直连内置短 id（Share / `PATCH …/agent-ref` 都拒绝）；他们发 Inbox 申请。定制 upload 包的 Performance 仍要该包 org 同意：owner 自己 attach，或批准 `agent_performance`。Leaderboard 上榜门（listing）不因此放宽。

Leaderboard 默认 **Table**（Harness / Model 列不变）。同一 tab 可用 `PillTabs` 切 **Pareto** / **Waffle**（`?chart=`；默认省略即 table）。Waffle：行 = task，列 = suite run，一格一 trial（`task_refs` + `previous`；缺历史时按 `n`/`c` 粗绘）。点有 Attempt 证据的方块进该 task 的 job 详情；否则打开 suite 详情页。Pareto：纵轴 pass rate，横轴 Cost / Tokens / Time（`?axis=`，默认 cost）；左便宜（横轴增大向右，左上更好）。模型名避让放置，过远时用同色指示线连回点；字号按 CSS 像素，不随 SVG viewBox 缩小。unique join 到 pin 时名称前画 lab SVG（与表的 `LabMark` 同源；无 hit 不加字母标），避让宽度含图标。帕累托前沿（最小化横轴、最大化 pass rate 的未支配点）用次要色连线，不另画点圈；非前沿点默认半透明，hover 该点恢复不透明。hover 并向两轴画虚线、在轴上标该点数值。suite 详情是路由页 `/datasets/{id}/suites/{suite_run_id}`（`?tab=` Profiles / Plugin / Jobs / Share），不是 modal。旧 `?suite=` 重定向到该页。suite `metrics.usage` 在 **summary / `upload-suite` 时写入**（每个 Attempt 的 `trajectory.jsonl` **每一条** `terminal.usage` 加总——ACP 是按轮次，不是取最后一轮；再把 suite 里全部 job 加总。有 agent `cost_usd` 用上报值，否则 token × pin directory price 写成 `cost_usd_estimated`）。Hub 只读这笔，不在每次开榜时重算。旧 suite 没有 `metrics.usage`、或 usage 是按最后一轮算的，就要重新 `upload-suite`（本地仍有 `.ageval/runs/`）。观测，不是 suite PASS，不是账单。

Leaderboard 两列保持 Harness / Model。plaza 行上的 `agent_refs` 变链：内置 Agent 包短 id（`--agent pi` / attach `pi`）不经 Agent org 同意；定制 `org/name` 仍要同意。Harness 格打开 `/agents/{package_id}`（builtin 短 id 或 ref；观测短名如 `codex@acp` 剥 `@` 后对 builtin 表）。Model 格 unique join 打开 `/models/{canonical}`。行点击仍进 suite 详情；格内链 `stopPropagation`。无 unique hit / 无 builtin 短 id 的观测文案不链，不要按 executor 猜包。不要 `/agents/…/models/…`。站内文字链 rest 为 ink、hover 下划线 + `link-deep`（与 `/models` Model 格相同），不要 rest IKB；站外 http(s) 仍用 `text-link`。Environment 仍是机制标。suite 详情页标题行的 Harness / Model 同一套链。

## Leaderboard plaza

Hub 侧栏 Catalog 首位是 **Leaderboard**（`/leaderboard`），其后是 Datasets / Plugins / Agents / Models。这是已有三面的**索引**——Dataset Leaderboard、Agent Performance、Model Performance——不是第四套排名、不是新上传路径、不是 PASS 真值。三张表可以成员不一致：上榜 suite 可以没有 Agent Performance（未 attach / 未采集）；已同意的 Performance 行也不自动变成 Dataset Leaderboard 行。不要取交集，也不要因为 suite 已列出就把未同意的 harness 塞进 Agent / Model 视图。

| 片 | 规则 |
| --- | --- |
| 侧栏 | Catalog 组首位。标签 **Leaderboard**。lucide 新字形 + `nav-leaderboard`（只涂字形，不复用别的目的地 `nav-*`）。 |
| 路由 | `/leaderboard`。Hub `/` 与未知路径 `replace` 到这里（登录回跳无 return path 同此）。视图是 query `?view=dataset\|agent\|model`。省略 `view` = dataset。页上一条 `UnderlineTabs`。 |
| 活 | 索引已可见的 Performance。Dataset 视图复用 Dataset Leaderboard 的 Table / Pareto / Waffle Select（`?chart=` / `?axis=`；默认省略即 table），控件在 Dataset tab 行右侧。Pareto / Waffle **按 Dataset 组各画一份**，不要把不同 Dataset 的 task 混一张 waffle。Agent / Model 只要表。 |
| Chrome | 复用 `GroupedTables` 粘组头（org pin slot / `--*-stick-top`），与 `DatasetOrgTables` / `ModelLabTables` 同一套，不要第二套粘头。搜索抄 `CatalogScopeBar` 查询框；**不是**市场，不要 Explore / orgs / Stars。 |
| 分 | 内行带该 suite / Performance 行上的观测指标。不要发明 per-entity 汇总（latest / best）。说明：观测，不是 PASS，不可跨 Dataset 比。不要名次列。 |
| 默认排序 | 与 Dataset Leaderboard 相同：pass rate desc → mean score desc → `created_at` desc。`SortableHead` 跨组共享。 |
| 鉴权 | 未登录可看。plaza 永不展示 Dataset Internal / draft-bound / 未列出的 suite。 |
| 空 | `CatalogEmpty` + 该字形。本路由不加载 `leaderboard-fixtures.ts`。`?demo=1` 无效果。 |

三视图各守已有门：

**Dataset**（省略 `?view=`）

- 门 = 公开 Dataset Leaderboard：完备 + release-bound + `board_listed`。
- 组头 = Dataset（名称 + 描述；有包标则同市场解析）。一个 Dataset 一张表，不要按 org 再拆。
- 内行 = 一条已列出的 suite（Harness / Model / Pass rate / Mean）。不要 Dataset 列（组头已经是该 Dataset）。suite 有 `created_at` 则加 Uploaded 列。同一 Dataset 多条已列出 suite → 多行，不是一条汇总。Table / Pareto / Waffle 切到该组的已有图表组件，不另发明跨 Dataset 汇总。
- 组头 Dataset 名 → `/datasets/{id}?tab=leaderboard`。行点击 → 已有 suite 详情 `/datasets/{id}/suites/{suite_run_id}`。
- Harness / Model 格行为与 Dataset Leaderboard 相同（内置短 id 可链；定制 `org/name` 仅在已同意时）。不要按 executor / overlay 文案猜包。Model 格短名（去 provider 前缀）在 unique join 到 pin 时前置 `LabMark`（brand-marks 闭包或 pin lab SVG）；无 unique hit 不加标、不加字母占位。Harness 格同理：builtin 短 id（及 `codex@acp` 这种观测短名）前置 `BrandMark`（`brand-marks/assets` 闭包；`grok-build` / `openai-http` / `anthropic-http` 复用父品牌）。定制 `org/name` 有包行才用 `icon_key` / GitHub 头像；不要猜包、不加字母占位。
- 读：一次 `GET /v1/results/suites?board=1`（可省略 `dataset_id`）。不要按 Dataset N+1。

**Agent**（`?view=agent`）

- 门 = 已有 Agent Performance（plaza 采集或 Agent-org 同意）。不是 `board_listed`。
- 组头 = Agent org；**内置短 id 一组**（它们没有 `org_id`）。
- 内行 = 已有 Performance 行（组内必有 Agent 列；Dataset / Role / Model / Pass rate / Mean）。Agent 格同 Dataset 视图 Harness：builtin 短 id 前置 `BrandMark`。Model 格同 Dataset 视图：unique join 前置 `LabMark`。
- Agent 名 → `/agents/{id}?tab=performance`。行点击 → Agent 页已打开的同一 suite 详情。

**Model**（`?view=model`）

- 门 = Agent Performance 经 canonical join。评测事实仍是那些行；不要混第三方 bench。
- 组头 = lab（`LabGroupHead`），与 `/models` 相同。组头已有 lab 标，内行 Model 列不再前置 `LabMark`。
- 内行 = 已 join 的 appearance（Model / Harness / Dataset / overlay / Pass）。未 join 的 overlay **本视图省略**（Dataset / Agent 视图仍可按 overlay 原文出现）。
- Model 名 → `/models/{canonical}?tab=performance`。Harness → `/agents/{id}?model={overlay}`。Harness 列前置 builtin `BrandMark`（组头是 lab，不是 harness，所以行内要标）。

Registry 只做展示聚合。没有 `performances` 表，没有新的 listing / consent 写，没有 `package_kind=leaderboard` / `ageval.leaderboard/1`。Agent / Model 视图走一次派生读：`GET /v1/results/performances`，复用 `RuntimeService.performances_for_agent` 已有的 reducer（对可见 suite 跑一遍，不是按包 N+1）。未知查询键拒绝。可见性与包详情 Performance 相同。v1 可一次拉全量派生列表（`GroupedTables` 不把组拆页）。分页是后续；不要第二份客户端缓存。

`/datasets/:id?tab=leaderboard`、`/agents/:id?tab=performance`、`/models/{canonical}?tab=performance` 仍是下钻，不被 plaza 替换。Internal 仍只在 Dataset 页。lock / fingerprint / PASS / `board_listed` / `agent_performance` 同意都不因 plaza 改写。

Inbox：Registry 一等 request 行（`pending` / `approved` / `rejected`）。两种 kind：`leaderboard_list`（收件人 = Dataset org owner）、`agent_performance`（收件人 = Agent 包 org owner；内置短 id 的收件人 = Maintainer，`owner_org_id=_maintainers`）。`agent_performance` 载荷带 proposed `canonical_model`（可空）。Inbox批准必须出示并可改 Model Select：唯一匹配可预填；无唯一匹配时 owner / Maintainer **必须**挑一条或拒绝，申请人不能指定桶。批准只跑已有写入（listing 标记，或同一条 attach 路径记下 canonical 桶）。申请人已是该 Agent org owner / Maintainer 时走 attach、不建请求。加入 org 仍是 invite key。搜索栏右侧 Kind / Dataset 过滤。History 标题右侧删除：对本用户隐藏已处理行（不删请求、不撤销 listing/attach、其他决策人仍可见）。

## 身份页

公开用户 `GET /v1/users/{user_id}`：`user_id` 即 GitHub login。`display_name` / `avatar_url` 来自登录快照，不是 Hub 可写字段。Hub 可写的只有 `description`（`PATCH /v1/users/{user_id}`，仅本人）。主页用 `https://github.com/{user_id}` 作为 GitHub 链，不另存 URL。`maintainer`（bool）来自 `AGEVAL_REGISTRY_MAINTAINERS`，与 `official` 独立。Hub 个人主页标题旁与右上角头像旁显示 Maintainer 标（lucide `ShieldUser`，色走侧栏 Home 的 `nav-home` 绿），不用 Official 的 BadgeCheck。

组织：`display_name` 与可选 `description`。owner `PATCH /v1/orgs/{id}` 可改其中任一；创建时可带 `description`。

组织图标与 plugin / agent 同一套预设彩色图标：owner `PATCH /v1/orgs/{id}` 可带 `icon_key` / `icon_github`（校验与清除语义同包；无 uploader 兜底，默认回字母标）。列表与详情的 org 行都带这两个字段；Hub 组织详情页标题旁用与包详情同一套 Choose icon modal，datasets 首页组头、组织列表等展示处按 icon_key → icon_github → 字母标解析。

未知键拒绝。空 description 表示清除。

## 市场下载量

`download_count` 按 `dataset_id` 累计，不是 per-version，也不是 PASS / 安装成功。每次成功 `GET /v1/packages/{id}/by-digest/{dig}/content`（真 blob，不是 `/files` 预览）加一。列表与 by-digest meta 都带该字段（缺记录为 0）。Hub 在 plugin / agent 卡片与详情展示；dataset 表不展示。

## 市场收藏

`favorite_count` 按 `dataset_id` 累计，不是 per-version。每人每个包最多一条收藏。只允许 **plugin** 与 **agent**（dataset 拒绝）。列表与 by-digest meta 带 `favorite_count`（缺记录为 0）；已登录调用方另带 `favorited`。

- `POST /v1/packages/{id}/favorite`：登录后收藏；须能看见该包。已收藏则幂等返回当前状态。
- `DELETE /v1/packages/{id}/favorite`：取消收藏；未收藏也幂等。
- `GET /v1/packages?favorited=1`：只列当前用户收藏且仍可见的包。无登录用户 id 则空列表。
- `GET /v1/packages?orgs=1`：只列调用方所属组织发布的包。无登录用户 id 则空列表。
- `GET /v1/packages?visibility=public`：只列公开包（Explore）。

Hub 列表 tab **就是**这些查询参数（不要再叠一层 `scope=`）。默认 Explore：

| URL | Tab |
| --- | --- |
| `/plugins`、`/agents`、`/datasets`（无额外参数或 `?visibility=public`） | Explore |
| `?orgs=1` | Your organizations（请求带 `orgs=1`） |
| `?favorited=1` | Stars（仅 `/plugins`、`/agents`） |

列表上的 star 是计数，不是写入口。写收藏只在包上；未登录走登录。组织详情的 settings 用 `?tab=settings`（默认 overview 省略 `tab`）。

## Dataset Tasks / Jobs 分页

Hub 表分页**就是**查询参数（不要再叠 `page=` 之外的 scope 层）。默认 `limit=20`，上限 `100`。`offset` 默认 `0`。响应带 `items`、`total`、`limit`、`offset`。

| URL / 请求 | 含义 |
| --- | --- |
| Dataset `?tab=tasks` | 第一页 Tasks |
| Dataset `?tab=tasks&offset=20` | 下一页；Hub 请求 `GET /v1/packages/{id}/by-digest/{dig}/tasks?limit=20&offset=20` |
| Task Jobs `?tab=jobs&offset=` | 该 task 的 suite/attempt 行 |

`GET /v1/packages/{id}/by-digest/{dig}/tasks` 读 publish 时按 `package_digest` 落下的任务摘要（`task_id`、`has_readme`），并返回 `has_shared` 与 `overlay_prefixes`。`overlay_prefixes` 来自包内全部 overlay 源文档（根 `profiles.yaml` 以及 `tasks/` 之外、basename 为 `profiles` / `profiles.*` 的 yaml），不是只读根文件。分页 item 另带观测字段 `job_count` / `last_status` / `last_score`（调用方可见 suite 的 `task_refs`，不是 PASS）。不把整棵文件树交给浏览器，也不为 Tasks 表拉全量 suite。未知查询键拒绝。缺失摘要时才回退 inflate 一次并写回。

`GET /v1/results/suites` 增加可选 `task_id`、`limit`、`offset`。省略 `limit` 时返回全量（兼容现有客户端）。`task_id` 按 suite `task_refs` 过滤。

README 预览不经过整包文件树闸门；其它区块按需拉取。不要为打开包就把文件树和 suite 一次拉完。

## 组织成员顺序

`GET /v1/orgs/{id}/members` 的 `items`：**owner 在前**，同角色按 `user_id`。Hub 成员表按该顺序渲染。

## 市场图标

Plugin / agent 的实体标默认是 **uploader 的 GitHub 头像**（`uploaded_by` 即 GitHub login）。Hub org **不是** GitHub org，不要用 `org_id` 去拼 `github.com/{org}.png`。

Owner `PATCH /v1/packages/{id}` 可改写（与 `display_name` 同权，不进 blob，不按 version）。只认这两个键：

| 字段 | 含义 |
| --- | --- |
| `icon_key` | 图标目录 id。未知 key：**一条** `invalid_request` |
| `icon_github` | GitHub login。从 `github.com/{login}` 或 `github.com/{login}/{repo}` 取出 owner；非法 login 一条 `invalid_request` |

空字符串清除该字段。两个都空 = 回到 uploader 头像。一次 PATCH 可同时带两键（picker 保存时：选用录则清 github，填 link 则清 key）。

解析顺序：已存 `icon_key` → 已存 `icon_github` → **official / builtin 包用闭包 `zju-real`（仓内 SVG，不 fetch GitHub）** → `uploaded_by` 的 `https://github.com/{login}.png?size=64` → 字母占位。裂图走字母。不把图片字节写入 Registry。`zju-real` 是 REAL Lab / ZJU-REAL 组织标，出现在图标 picker 里，owner 可改成其它目录标或 GitHub login。

图标目录是 **彩色真实标**（官方 kit / Lobe static SVG / Simple Icons 路径 + 官方 hex）。禁止自造厂商 logo。黑标（ink，如 OpenAI）固定白底；白标（paper，如 Kimi）固定黑底。底板不跟主题反相。改标是包级写，不在列表卡上开 picker。Viewer 本轮不做。

机制标（Leaderboard Environment 的 `docker` / `e2b` 等）仍走闭包精确 id，不是 uploader 头像。

## 市场描述

Dataset 描述来源是包根 `ageval.yaml` 的 `/description`（`ageval.dataset/1`）。上传 / 发布建 task summary 时一并提取（按 `package_digest` 存储，不进 blob 重写）；`GET /v1/packages`、`GET /v1/packages/{id}/versions` 与 by-digest meta 都带 `description`（无则为空，不给假文案）。

Owner `PATCH /v1/packages/{id}` 另认 `description` 键（与 `display_name` 同权，不进 blob，不按 version）：字符串、trim 后 ≤500 字符，空字符串清除。`description` 是 owner 覆写，与 manifest 描述分层：**覆写 > manifest**，清除后回到 manifest 值。未知键拒绝不变。

CLI：`ageval registry set-description <dataset_id> --description "…"`（`--description ""` 清除覆写）。Hub 端展示：datasets 首页 Description 列在 Dataset 列右侧、最多两行截断；Dataset 详情页标题区用与 org 详情同一套 DescriptionEditor，org owner 可编辑并同步该覆写。plugin / agent 卡仍用各自 manifest 的 preview description，不走此覆写。
