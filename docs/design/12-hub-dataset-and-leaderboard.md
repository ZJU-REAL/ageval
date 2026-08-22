# 12 — Hub 与 Registry

字段是 `dataset_id`。无 `database_id` 双读。Hub / Viewer 文案用 dataset，不是 Database。无 `ageval submit`；上传走 `ageval results upload` / `upload-suite`。

公开 Leaderboard：完备 suite + 绑定 **release** + Dataset 包所属 org 的 owner 批准 listing（`board_listed`）。官方与非官方 Dataset 同一道门。`public` 不是上榜：可见性与 listing 分开。新上传默认未列出；不祖父旧行。Internal（调用方可见的不完备 / draft-bound）不变。

单 Attempt `results upload` 通常上不了榜。正确路径：`ageval run <dataset>`（无 `--task`）→ `ageval results upload-suite --suite-run <id> --with-attempts`。申请人是 suite `uploaded_by`；不完备或 draft-bound 申请 listing fail closed。批准只写 listing 标记，不改 lock / fingerprint / overlay。

`--agent` 投影进 profiles 通道，与 `--profiles` 互斥。`agent_ref` 是溯源不是身份，不进 `config_fingerprint`。已上传 suite 允许延后把 published `org/name@version` 写入 **Registry 存的** `job_overlay`（对齐 `_binding_role_key`：executor、ACP entry、model、secret-free plugin options）。不改 Attempt `lock.json`、digest、PASS。`local/` 与 `file:` 不能当 Hub 溯源。plaza 出场（官方 Dataset + public + complete + release）不变；仅 overlay 有 `agent_ref` 不够 —— Appearances 还要 Agent 包 org 同意。

Inbox：Registry 一等 request 行（`pending` / `approved` / `rejected`）。两种 kind：`leaderboard_list`（收件人 = Dataset org owner）、`agent_appearance`（收件人 = Agent 包 org owner）。批准只跑已有写入（listing 标记，或同一条 attach 路径）。申请人已是该 Agent org owner 时出场走 attach、不建请求。加入 org 仍是 invite key。

## 身份页

公开用户 `GET /v1/users/{user_id}`：`user_id` 即 GitHub login。`display_name` / `avatar_url` 来自登录快照，不是 Hub 可写字段。Hub 可写的只有 `description`（`PATCH /v1/users/{user_id}`，仅本人）。主页用 `https://github.com/{user_id}` 作为 GitHub 链，不另存 URL。

组织：`display_name` 与可选 `description`。owner `PATCH /v1/orgs/{id}` 可改其中任一；创建时可带 `description`。

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

Hub 列表 tab **就是**这些查询参数（不要再叠一层 `scope=`）：

| URL | Tab |
| --- | --- |
| `/plugins`、`/agents`、`/datasets`（无额外参数） | Your organizations（请求带 `orgs=1`） |
| `?visibility=public` | Explore |
| `?favorited=1` | Stars（仅 `/plugins`、`/agents`） |

卡片把 `favorite_count` 与 `download_count` **同一行**展示（star 只是计数）。详情页头右侧用 icon 按钮 star/unstar；未登录点它去登录页。组织详情用 `?tab=settings`（默认 overview 省略 `tab`）。

## 组织成员顺序

`GET /v1/orgs/{id}/members` 的 `items`：**owner 在前**，同角色按 `user_id`。Hub 成员表按该顺序渲染。

## 市场图标

Plugin / agent 的实体标默认是 **uploader 的 GitHub 头像**（`uploaded_by` 即 GitHub login）。Hub org **不是** GitHub org，不要用 `org_id` 去拼 `github.com/{org}.png`。

Owner `PATCH /v1/packages/{id}` 可改写（与 `display_name` 同权，不进 blob，不按 version）。只认这两个键：

| 字段 | 含义 |
| --- | --- |
| `icon_key` | 闭包目录 id。未知 key：**一条** `invalid_request` |
| `icon_github` | GitHub login。从 `github.com/{login}` 或 `github.com/{login}/{repo}` 取出 owner；非法 login 一条 `invalid_request` |

空字符串清除该字段。两个都空 = 回到 uploader 头像。一次 PATCH 可同时带两键（picker 保存时：选用录则清 github，填 link 则清 key）。

解析顺序：已存 `icon_key` → 已存 `icon_github` → `uploaded_by` 的 `https://github.com/{login}.png?size=64` → 字母占位。裂图走字母。不把图片字节写入 Registry。

闭包目录是 **彩色真实标**（官方 kit / Lobe static SVG / Simple Icons 路径 + 官方 hex）。禁止自造厂商 logo。黑标（ink，如 OpenAI）固定白底；白标（paper，如 Kimi）固定黑底。底板不跟主题反相。详情页（`canEdit`）点标打开 modal：搜目录，或填 GitHub link。卡片整卡导航，不在卡上开 picker。Viewer 本轮不做。

机制标（Leaderboard Environment 的 `docker` / `e2b` 等）仍走闭包精确 id，不是 uploader 头像。
