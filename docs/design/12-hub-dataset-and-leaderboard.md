# 12 — Hub、Registry 与 Leaderboard

Dataset 唯一标识符字段为 `dataset_id`。软件包与评测结果的上传分别通过 `ageval publish` / `ageval plugin publish` / `ageval agent publish` 以及 `ageval results upload` / `upload-suite` 完成。此外，Hub 支持提交云端托管评测作业（详见 [15](15-hosted-jobs.md)），由后台 worker 在 E2B 或 Daytona 云沙箱中运行 `ageval run` 并回传结果。

## Git 源注册与 eval_digest

除上传整包外，Dataset 可以只注册 git 源：`ageval publish --repo github:org/repo@v1.0.0`（可带 `#<subdir>`）将 `{dataset_id, version, git_url, commit, eval_digest}` 写入 Hub（`POST /v1/packages/{dataset_id}/source`），不上传文件。git 引用的解析规则见 [02](02-task-package-and-config.md)。

- **eval_digest：** 由 CLI 本地计算并写入 lock。它只覆盖影响评分的文件：根清单 `ageval.yaml`（去掉描述性字段，其中 `assets` 清单只取 `path + sha256`）、每个任务成员的全部文件、数据集级 `shared/`，以及声明的 `prepare` 脚本内容。README、LICENSE 与其他根目录文档不计入，改文档不改变 digest。`package_digest` 仍覆盖整包，两者并存。
- **注册冲突：** 同一 `dataset_id@version` 已注册（或已上传发布）且 `eval_digest` 不同 → 拒绝（`eval_digest_mismatch`，"tasks changed, bump version"）；digest 相同（例如只改 README）→ 接受并刷新钉版 commit。注册遵循发布的所有权模型：dataset 属于组织（显式 `--org` 或 dataset_id 前缀），调用方必须是组织成员。`eval_digest` 在 lock 时按解析出的原始目录树计算（prepare 执行前），prepare 产物经脚本内容与 assets 清单传递性钉版，因此注册与运行的 digest 一致。
- **结果归因：** `upload-suite` 携带 lock 中的 `eval_digest`。Hub 按字符串比对：与已注册版本一致 → 结果归因到该版本（`bound_kind: source`，任务完备性按注册时记录的任务集判定，批准后可上榜）；未注册或 digest 不符 → 结果照常保存但不上榜（`bound_kind: unknown`）。
- **源健康：** `POST /v1/packages/{dataset_id}/versions/{version}/source-check` 探测源仓库可达性；不可达时标记 `source_available: false`（Dataset 页面显示 "source unavailable"），既有结果不受影响。
- **Hub 链接：** git 源版本的页面链接指向钉版 commit（`/tree/<sha>/<subdir>`、`/blob/<sha>/…`），永不指向分支。
- **Prepare 审查：** Dataset 详情页展示声明的 `prepare` 脚本（徽标 + 内容；git 源版本链接到钉版 commit 上的文件）、`assets` 清单（path + sha256 前缀）与源不可达标记，便于在运行前审查数据集级准备逻辑。带 prepare 脚本的版本在 CLI 执行前也会打印提示。

## Dataset Leaderboard 与准入规则

每个 Dataset 详情页的 Leaderboard 包含两个视图：
- **Public（公开榜）：** 仅展示同时满足三项条件的 suite 结果：1）任务完备（包含绑定版本下的全部任务结果）；2）绑定正式发布的 **release** 版本（非 `draft`）；3）经该 Dataset 所属组织的 owner 批准上榜（`board_listed: true`）。结果的公开可见性（`visibility: public`）与上榜批准（`board_listed`）相互独立。
- **Internal（内部视图）：** 向有权限的调用方展示未完备或绑定 `draft` 的 suite 结果。

单次 Attempt 上传（`ageval results upload`）仅归档单题证据，不生成榜单行。标准上榜流程为：先执行 `ageval run <dataset>`（省略 `--task`）跑完整个 suite，再执行 `ageval results upload-suite --suite-run <id> --with-attempts` 上传，最后提交 `leaderboard_list` 申请由 Dataset 组织 owner 在 Inbox 中批准。

Public 视图默认展示该 Dataset 下所有已批准上榜的 suite，右侧版本选择器可按上传时绑定的 `dataset_version` 过滤（默认 `All versions`）。

### 图表视图（Table / Pareto / Waffle）

Dataset Leaderboard 与本地 Viewer 的 Suite Jobs 均支持三种视图切换：
- **Table（默认表格）：** 展示 Harness、Model、Pass rate、Mean score 等指标列，支持按列排序（默认按 `pass_rate` 降序 → `mean_score` 降序 → `created_at` 降序）。
- **Pareto（帕累托前沿）：** 纵轴为通过率（Pass rate），横轴可选总费用（Cost）、总 Token 数（Tokens）或总耗时（Time）。横轴数值来自 `upload-suite` 时汇总的 `metrics.usage`（累加每个 Attempt `trajectory.jsonl` 中全部轮次的 `terminal.usage`；若执行器未直接上报 USD 费用，则按模型目录单价估算为 `cost_usd_estimated`）。非支配解连接为帕累托前沿。
- **Waffle（华夫格图）：** 行表示 task，列表示 suite run，每个方格代表一次 trial，点击已上传证据的方格可直接跳转至对应 Attempt 详情页。

### Agent 溯源关联（Attach）与 Performance 聚合

通过 `--agent` 运行或事后在 Hub Suite 详情页的 **Share → Attach**（`Register <role> as <agent>'s <model>`）可将 suite 中的角色关联至已发布的 Agent 包（`agent_ref`）与模型目录中的规范模型标识（`canonical_model`）：
- **匹配条件：** 角色绑定的 harness（`executor` + ACP `options.entry`）必须与目标 Agent 包一致。`agent_ref` 作为溯源元数据存储在 Registry 的 `job_overlay` 中，不改变 Attempt 的 `lock.json` 或 `config_fingerprint`。
- **内置 Agent 包（Builtin short IDs）：** 由平台维护者（`AGEVAL_REGISTRY_MAINTAINERS`）管理，默认开启 `official` 自动采集模式（自动收录官方 Dataset 上公开、完备且绑定 release 的 suite），维护者也可将其切换为 `official_and_personal` 或 `off`。非维护者向内置 Agent 包关联结果需提交 `agent_performance` 申请。
- **自定义 Agent 包（`org/name`）：** 需由该 Agent 包所属组织的 owner 直接关联或在 Inbox 中批准 `agent_performance` 申请。

## Leaderboard Plaza（`/leaderboard`）

Hub 左侧导航栏 Catalog 分组的首项为 **Leaderboard**（`/leaderboard`，根路径 `/` 默认跳转至此）。它是对既有三个评测视图的**全局索引**（通过 `?view=dataset|agent|model` 切换），不引入新的存储表或独立的评分标准：

| 视图 | 准入范围 | 分组与展示结构 |
| --- | --- | --- |
| **Dataset**（默认） | 公开 Dataset Leaderboard（完备 + release + `board_listed`） | 按 Dataset 分组（组头显示名称与描述），组内支持切换 Table / Pareto / Waffle，复用一次 `GET /v1/results/suites?board=1` 请求 |
| **Agent**（`?view=agent`） | 已收录的 Agent Performance（自动采集或经 Agent 组织批准） | 按 Agent 所属组织分组（内置 Agent 包单独成组），展示 Agent、Dataset、Role、Model、Pass rate 与 Mean score |
| **Model**（`?view=model`） | 已唯一关联至规范模型目录（canonical pin）的 Agent Performance | 按模型实验室（Lab）分组，展示 Model、Harness、Dataset 与通过率（未匹配到规范目录的模型标识仅在 Dataset / Agent 视图按原名展示） |

宽屏下列表右侧提供 `GroupOutline` 快速导航条，悬停可展开组名与数量，点击可将该组定位至吸顶工具栏下方。

## Inbox 审批流

Registry 维护统一的审批请求表（状态为 `pending` / `approved` / `rejected`），包含两类请求：
1. `leaderboard_list`：由 Dataset 所属组织的 owner 审批是否将某份完备 suite 列入公开榜；
2. `agent_performance`：由 Agent 包所属组织的 owner（内置 Agent 包为平台维护者）审批是否将某份 suite 关联至该 Agent 的 Performance 页面，并在审批时确认或调整关联的规范模型（`canonical_model`）。

## 用户与组织主页、图标及描述

- **用户主页（`/users/{user_id}`）：** `user_id` 对应 GitHub 登录名，展示头像、显示名、个人简介（本人可通过 `PATCH /v1/users/{user_id}` 编辑 `description`）以及公开包与维护者标识（`AGEVAL_REGISTRY_MAINTAINERS`）。
- **组织管理（`/organizations/{org_id}`）：** 支持成员管理（owner 排在首位）、组织描述与图标配置。
- **包与组织图标（`icon_key` / `icon_github`）：** 插件与 Agent 包默认使用上传者的 GitHub 头像（官方与内置包默认使用仓库内置的 `zju-real` 矢量标识）；组织 owner 可通过 `PATCH` 设置预设彩色品牌图标（`icon_key`）或指定 GitHub 账号头像（`icon_github`）。
- **Dataset 描述覆写：** Dataset 描述默认提取自包内 `ageval.yaml` 的 `/description`；组织 owner 可通过 Hub 标题区或 `ageval registry set-description <dataset_id> --description "…"` 设置覆写描述（传入空字符串可清除覆写并恢复为清单描述）。

## 市场下载量、收藏与列表分页

- **下载计数（`download_count`）：** 按 `dataset_id` 统计真实包归档下载次数（`GET /v1/packages/{id}/by-digest/{dig}/content`），在插件与 Agent 卡片及详情页展示。
- **收藏（`favorite_count`）：** 支持已登录用户对 **plugin** 与 **agent** 包进行收藏（`POST / DELETE /v1/packages/{id}/favorite`），可通过 `?favorited=1`（Stars）、`?orgs=1`（Your organizations）或默认的 Explore 视图筛选。
- **任务与运行记录分页：** Dataset 详情页的 Tasks 表（`GET /v1/packages/{id}/by-digest/{dig}/tasks?limit=20&offset=0`）与 Suites 列表支持 `limit`（默认 20，上限 100）与 `offset` 分页，避免一次性拉取整棵文件树或全量运行记录。

## 快照分享（Snapshot Share）

操作者可将本地已完成或正在运行的 suite（或单次 Attempt）生成匿名只读分享链接 `/s/{token}`，对方无需登录即可在浏览器中查看：

- **`static` 模式（默认）：** 定格在创建时刻上传的 suite 汇总与 Attempt 证据归档，后续本地磁盘变动不影响该链接。
- **`live` 模式（`--live`）：** 通过 `ageval results share-snapshot <dataset> --suite-run <id> --live` 创建，在本机 `.ageval/suite-runs/<id>/live-share.json` 记录关联信息。当运行中的子任务到达终态或执行 `ageval results sync-snapshot` 时，客户端通过 `PATCH /v1/shares/{token}` 增量更新同一条链接的汇总与新增 Attempt 文件，Hub 页面自动轮询刷新。
- **权限与安全隔离：** 快照分享存储在独立的 `snapshot_shares` 表与 `shares/` 对象前缀下，不改变原结果的公开/私有状态（`visibility`）、身份共享列表（`result_shares`）或公开榜状态（`board_listed`）。上传与增量更新前自动扫描并剥离非环境变量引用的明文密钥。所有者可随时通过 `ageval results revoke-snapshot <token-or-url>` 撤销链接并清理对应存储。
