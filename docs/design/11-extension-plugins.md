# 11 — 插件（独占 / 链）

扩展只有独占槽与链槽。槽名权威：`src/ageval/plugins/slots.py`。emit 总图：[ARCHITECTURE.md](../../ARCHITECTURE.md) § Extension emit map、[05-runtime/README.md](05-runtime/README.md)。

两条轴。Core 做表与解析，不做业务实现。

| 轴 | 回答 | 谁定名 |
| --- | --- | --- |
| slot | 这次 Attempt **何时**跑 | `attempt/` / phase |
| service | 进程里 **有什么** 可被别人调 | 独占槽赢家自动同名登记；插件还可 `exports.services` |

参照 Cordis 的 `inject` + 按名取服务。不抄整机事件总线、热卸载、用事件替换 `run_attempt`。

## 稳定接口：export / inject / capabilities

扩展要解的是 **实现之间的编译期耦合**，不是「多几个钩子」。以独占槽 `executor` 与 `environment` 为范例（ACP × docker / e2b / ssh / daytona 是同一条规则）：

| | 含义 | 不该变成 |
| --- | --- | --- |
| **export** | 「我是什么」：独占赢家以**槽名**进服务表（`environment`）；可选再 export 别名 | 把 docker SDK、container id 漏进邻居模块 |
| **inject** | 「我需要什么」：按**服务名**声明依赖，并列出要用的 **capabilities** | `inject: {plugin_id: e2b}`；在 invoke 里 `if kind ==` |
| **调用** | 只打该服务的 Protocol 方法（`attach_stdio` / `exec` / `upload`） | 本机 POSIX `cwd`、vendor HTTPS、自己拼 `docker exec` |

效果是 **interface / implementation 分离**：ACP 的稳定接口是「名为 `environment`、且声明了 `attach_stdio` 的盒子」；docker 把 `exec -i` 收在自己的 `attach_stdio` 里，e2b 把 SDK stdin 流收在同一方法里。换一种 kind，ACP 源码与 lock 里的 inject 行都不改。盒子内部怎么实现，对 executor **不可见**（locality）。

`exec` 与 `attach_stdio` 是同一服务上的不同 capability，不是两个 service。缺 cap 在 **lock** 失败，不在 invoke 中途探测。PASS / identity / cleanup 不准 export。

笛卡尔积成立的条件：每个 executor 的 `invoke` 只通过已 inject 的 `environment` 服务碰盒子。本机 SDK + 碰巧能看见的 bind-mount **不算** 满足这条。dsh / nooa 必须走盒内 worker + `host.exec`，与 ACP 同一 seam。

| 槽 | 语义 | 例子 |
| --- | --- | --- |
| 独占 | 全 Attempt 一个赢家；登记为同名 service | `environment`、`executor`、`evaluation_runtime`、`trajectory_seal` |
| 链 | `(ctx, value, nxt)` | `after_environment_ready`、`environment_setup`、`trajectory_collect` |

`profiles.environment` / `profiles.executor` = 选独占槽赢家。`evaluation_runtime` / `trajectory_seal` **没有** job 字段糖；默认赢家即可，替换只能走显式 `extensions` 行（`slot` + `plugin`）。`extensions` 也是链槽 opt-in。未列入 `extensions` 的不进链、不进服务表（引擎默认除外）。

Current 独占槽：`environment`、`executor`、`evaluation_runtime`、`trajectory_seal`。后两者默认是引擎（`plugin_id: default`）。PASS 仍只经 `bind_evaluation` 进入；`pass` / `identity` / `cleanup` / `evidence` 不准 export。

## 声明（形状）

```yaml
# plugins/e2b/plugin.yaml（示意；contrib 也可内建注册）
format: ageval.plugin/1
plugin_id: e2b
description: Open the Attempt box on E2B. Exclusive environment winner.
slots:
  exclusive:
    - id: environment
      entry: e2b_plugin:E2BHost

# plugins/acp/plugin.yaml（示意）
format: ageval.plugin/1
plugin_id: acp
description: Parent ACP JSON-RPC client. Coding-agent executor; injects environment attach_stdio.
slots:
  exclusive:
    - id: executor
      entry: acp.executor:AcpExecutor
  chain:
    - id: after_environment_ready
      entry: acp.hooks:ensure_runtime
inject:
  - service: environment         # 要 attach_stdio；不写 plugin_id: e2b

# job
environment: ssh
agent_profiles:
  solver:
    executor: acp
    options:
      entry: pi
    extensions: [ssh, acp]
```

外置包实例见 `plugins/nooa/plugin.yaml`：`slots.exclusive` / `slots.chain`，`host_requires`，`config.image_layers`（给 environment 赢家 bake，**不是**时间线槽）。

`description` 可选。一段功能说明；Hub 插件详情把它画在 Install (CLI) 上方。缺省不展示。空字符串 / 非字符串 fail closed。Hub 渲染 Markdown 链接（`[text](https://…)`）；其它块级语法不展示。

## 规则

- `host_requires` / `plugin_requires` 只保留「没装先装谁」。调用一律 `inject: [service:…]`。
- 两个插件抢同一独占槽或同一 export id → fail closed。绑定图进 lock digest。
- 参数走该插件 `config` / 服务方法。禁止翻别人 yaml。密钥 locator。
- 拆时先拆 inject 方。PASS / 身份 / cleanup **不是**可 export 的服务。
- 新插座不必先改 `slots.py`；新 **时间线** 槽仍要改 attempt 宿主。
- `ageval plugin install` 只写 `~/.ageval/plugins`，永不改 profiles。
- 按机制命名（`acp` / `acp-oneshot` / `docker` / `e2b` / `daytona` / `ssh` / `nooa`）。禁止按 bench 名。

独占槽默认赢家（Current）：`environment` 由 job `environment:` 选出（缺省常见 local 或 docker，以 profiles 为准）；`executor` 由 `agent_profiles.*.executor` 选出（coding-agent 默认 acp）；`evaluation_runtime` / `trajectory_seal` 由引擎 `plugin_id: default` 赢（盒内 `evaluator.py` / 层 C writer）。缺默认注册 → lock fail-closed。

链默认：`after_environment_ready`（ACP 探测安装 + HOME overlay）；`environment_setup`（`setup.sh`，引擎 defaults）。

## 解析

```text
profiles.environment / executor / extensions
  → registry resolve
       exclusive  单赢家（priority，并列 fail closed）
       chain      已排序的 nxt 链
  → lock.extension_bindings 进 digest
```

inject 用 `service: environment`，不写死 `plugin_id: e2b`。`executor: acp` 要 `attach_stdio`；盒内 worker（dsh / nooa / `acp-oneshot`）要 `exec`（dsh / nooa 另要 `upload`）。缺则 lock 失败。盒子没有 `attach_stdio` 不是把 oneshot 折进 ACP 插件的理由。

Resolve：显式 binding > 更低 priority 赢；并列且无显式挑选 → fail closed。`DEFAULT_PRIORITY = 1000`。**数字更小的先跑（链）/ 先赢（独占）。**

## 包

manifest：`ageval.plugin/1`。first-party：`src/ageval/plugins/contrib/{acp,docker,local,e2b,daytona,ssh,openai_http}`。引擎默认：`plugins/defaults`（`environment_setup`、`evaluation_runtime`、`trajectory_seal`）。外置包在仓库根 `plugins/`（nooa、dsh、miniswe、acp-oneshot、home-files、agent-skills）。`acp-oneshot` 是第二条 coding inlet（盒内 oneshot client + `exec`），不是 first-party `acp` 的运输开关。

Recognition（list/lock 认得）≠ 本机能跑 ≠ 镜像已 bake。缺 extra / 钥 → skip，不要假绿。

Hub `/plugins` 可以把 first-party contrib 画成 **catalog overlay**，不是 upload。手写 JSON（`services/registry/builtin_plugins.json`）列出七个 bootstrap id：`local`、`docker`、`e2b`、`ssh`、`daytona`、`acp`、`openai-http`。Registry 读这个文件；**禁止**在 Registry 进程 `import ageval.plugins.contrib`。行上 `builtin: true`，不绑 `org_id`，不设 `official`（`official` 仍是 upload-org allowlist）。没有 blob / digest / version / 下载数 / 安装命令。详情路由是短 id（`/plugins/docker`）。`plugins/defaults` 与 `ageval.agent/1` 不进这张表。

四条不相等：**Hub 认得** ≠ **本机能跑** ≠ **镜像已 bake** ≠ **`ageval plugin install` 装过**。空店 Explore 仍应看到这七张卡；e2b / ssh / daytona 缺 extra 或缺钥时卡仍在，lock/run 维持既有 skip / fail-closed。七个短 id 保留：`ageval plugin publish` 与 `ageval plugin install` 撞到它们 fail-closed，避免 `/plugins/docker` 和店包抢同一条路由。运行时装载路径仍是 `bootstrap.py`。

`FAIL_OPEN_SLOTS`：`before_run` / `after_run` / `trajectory_collect` / `trajectory_enrich` / `cleanup_report`。其余失败即该相位失败。

钩子形状：

```python
async def trajectory_collect(ctx, value, nxt):
    out = await nxt(value)
    return out
```
