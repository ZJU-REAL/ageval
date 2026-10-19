# 14 — Agent 包（`ageval.agent/1`）与模型目录

Agent 包的 Schema 格式为 `ageval.agent/1`。包内的 `model.id` 仅作为运行时未指定 `--model` 时的默认模型，不构成 Agent 包的唯一身份标识；`base_url` 与 `api_key` 仅保存环境变量名引用（locator）。

## 两类 Agent 包

1. **内置 Agent 包（Builtin catalog overlay）：** 维护在 `src/ageval/agents/builtin/catalog.json` 及同级目录树中（`builtin: true`，无 `org_id`），供 CLI `--agent <id>` 与 Hub `/agents` 页面直接读取，无需预先执行 `ageval agent install`。保留短 ID 包括：
   - **ACP 入口：** `pi`、`opencode`、`codex`、`claude-code`、`grok-build`（对应 `options.entry`；`$AGEVAL_HOME/acp-entries.json` 可扩展本机自定义 entry，但不可覆盖包内保留 ID）；
   - **HTTP 执行器：** `openai-http`、`anthropic-http`。
   环境类型（`docker`、`local` 等）不属于 Agent 包；外置执行器（`dsh`、`nooa`、`miniswe`）通过 `examples/agents/` 或 Hub 自定义包提供。
2. **自定义 Agent 包（Uploaded packages）：** 通过 `ageval agent publish` 发布为 `org/name@version`。其核心 harness 标识由 `executor` 与 ACP `options.entry` 共同决定；默认 `model`（含 `id` 与 `reasoning.effort`）、`overlays/` 配置文件与其余插件选项共同组成运行配方。

## CLI 行为

- `ageval agent install …` 将 Agent 包写入 `~/.ageval/agents`，并自动安装 `binding.extensions[].plugin` 中声明的非内置外置插件（写入 `~/.ageval/plugins`）。若缺少插件或宿主机不满足 `host_requires`，安装直接报错终止。
- `--agent pi` 直接解析内置目录；`--agent org/name@version` 解析已安装的自定义包。
- `--agent` 与 `--profiles` 互斥；`--model` 需配合 `--agent` 使用（支持 `lock`、`run`、`campaign` 与 `results regrade`），用于覆盖本次运行绑定角色的 `model.id`。

## 溯源关联与模型目录（Models Catalog）

- **溯源元数据（`agent_ref`）：** 记录在 Registry 的 `job_overlay` 中，不改变 `config_fingerprint` 或 Attempt `lock.json`。
- **规范模型目录（Canonical Pin）：** 维护者通过脚本生成版本化的模型目录快照（含规范 ID 如 `deepseek/deepseek-v4-flash`、实验室 SVG 图标与目录参考单价），Hub、Registry 与 CI 在请求路径上绝不实时请求外部模型列表或图标 CDN。目录参考单价仅用于估算未上报 USD 费用的运行成本（`cost_usd_estimated`），不代表实际账单。
- **确定性模型匹配（Join）：** 将运行配置中的 `model.id` 原文按以下顺序匹配至规范模型 ID：1）精确匹配 `aliases`；2）按最长优先顺序依次尝试完整字符串、剥离已知网关前缀（如 `openrouter/`、`dashscope/`）后的字符串、最后两段路径及最后一段路径，与规范 ID、规范叶节点名及提供商模型 ID 做精确匹配。仅当存在**唯一匹配**时自动关联至规范模型词条；若无唯一匹配则保留原文字展示。

### Hub `/agents` 与 `/models` 页面

- **`/agents`：** 内置 Agent 包排在前面，随后为上传的自定义包。详情页 `/agents/{id}?model=` 使用 `ModelItem` 列表展示已收录的模型（含实验室图标、模态徽章、上下文窗口与参考价格），点击可切换当前聚焦的模型并更新命令条中的 `--model` 参数。
- **`/models`：** 按模型实验室（Lab）分组的表格目录，支持按模态（All / Text / Image / Video / PDF / Transcription / Speech）筛选与 `Cmd/Ctrl+F` 搜索。点击模型名称进入 `/models/{canonical}` 详情页（包含 Overview 规格参数表与关联的 Agent Performance 列表）。
