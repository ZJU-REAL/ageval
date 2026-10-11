# 09 — Owner 与目标树

完整模块表、依赖图、生命周期图以 [ARCHITECTURE.md](../../ARCHITECTURE.md) 为结构权威。本文给设计侧的 owner 决策表与不可退化的结构规范（产品模型 §4.9 / §4.10 的仓内正文）。

## Owner 矩阵

| 谁 | 拥有 | 不拥有 |
| --- | --- | --- |
| Core Config | lock、digest、format 校验 | 开环境、打分 |
| Attempt 宿主 | 相位序、identity、deadline、cleanup | 厂商 SDK |
| 环境 contrib | 一种 kind 的运输 | ACP 协议、PASS |
| ACP contrib | parent client、`attach_stdio` 消费 | `docker exec` 实现 |
| 题包 `run.py` | 业务、本地 Tool、publish | PASS、凭据、开环境 |
| evaluator | 真值算法 | 启动 Agent |
| evidence | 路径字符串、轨迹轨迹文件 | PASS |
| CLI | argv、exit code | 业务规则（只调 `build_*`） |
| Registry HTTP | 包与结果存储 | 颁发 PASS |
| SDK | 题包 helper | identity / 凭据 / verdict |

词汇：module / interface / seam / adapter / locality / depth。施工纪律以 [AGENTS.md](../../AGENTS.md) 为准。

## 目标树（`src/ageval/`）

包名 `ageval`。CLI 只 import `ageval.application.composition`。`.ageval/runs` 路径字符串只出现在 `evidence/`。

```text
src/ageval/
  __init__.py
  cli/                      # 薄：解析 argv，调 composition.build_*
  application/
    composition.py          # 唯一 composition root：接线，不写业务规则
    lock.py                 # load_and_lock + 能力/inject 图
    run.py                  # 公开 usecase：开 Attempt，调 attempt.run_attempt
    suite/
    plugin_ops/
    registry_ops/
    agent_ops/              # --agent（+ 可选 --model）投影进 profiles
    local_jobs/
    analysis/               # 跑完之后的 stats / hack / review；不改 PASS
  attempt/                  # 一次 Attempt 的流水线
    __init__.py             # run_attempt — 五行相位
    ctx.py                  # AttemptCtx：host / services / lock / bindings
    emit.py                 # 链槽 next()
    phases/
      environment.py        # start · ready · setup
      run.py                # 调题包 run.py
      evaluate.py           # 停写 · upload gold · evaluator
      record.py             # collect → 引擎写轨迹文件
      cleanup.py            # finally；host.stop
  config/                   # dataset 根 + task.yaml 缺省；无 Database 名
  plugins/                  # 槽表 + 服务表 + inject；不是业务
    slots.py                # 独占 / 链 id（宿主定名）
    registry.py / resolve.py / bootstrap.py
    contrib/                # first-party；按机制命名
      acp/                  # 独占槽 executor
      openai_http/
      anthropic_http/
      docker/               # 独占槽 environment；attach_stdio=exec -i
      local/
      e2b/                  # SDK 只在本包
      ssh/                  # A 整机 / B 远端容器
    defaults/               # environment_setup 认 setup.sh；透传链
  environments/             # 只有 Protocol + caps，无厂商 SDK
    protocol.py
  runtime/                  # 身份、协调、limits、ParentAgentService
    identity.py             # 一次 Attempt 一次 new_run
    parent_agent.py         # 只认 executor 服务 + host.attach_stdio
    task_launch.py / task_worker.py
  evaluation/               # barrier + 绑定 PASS；算法在题包
  evidence/                 # 布局字符串的唯一主人
  capabilities/             # 配额 / 授权面；不发明 PASS
  registry/                 # Hub 客户端
```

Current 还含 `viewer/`、`control/`、`agents/`（见 ARCHITECTURE Current 树）。外置插件仍在仓库根 `plugins/`（install 进 `~/.ageval/plugins`），不进 `src/ageval`。`sdk/` 仍是题包 `run.py` 用的薄 SDK，不拥有 identity / credential / PASS。

**刻意不建（Current 已删除，Target 也不得回潮）：**

- `environment/manager.py`
- `adapters/` 大杂烩、`agent_container.wrap_docker_exec`
- `run_l0.py` / `run_l1_*.py`
- 产品 `executor: mock` / FakeHost
- ACP 里的 `wrap_docker_exec`

Target 未全部兑现：`plugins/defaults` 与 `contrib/defaults` 不要两套；e2b/ssh 真跑证据；外置 nooa/dsh 真 run。对照 [ARCHITECTURE.md](../../ARCHITECTURE.md) Target。

## 结构规范（不可退化）

1. **少文件跳转。** `attempt/` 打开 `__init__.py` 就能说出阶段。禁止再拆出 `run_l1_prepare.py` 这类把复杂度摊到十个浅文件。删除测试：删掉一个文件若只是把逻辑搬到邻居，说明它是浅的，不要新建。
2. **测试面是公开 CLI + 真实 kind。** `local` 用真目录；`docker` / `e2b` / `ssh` 用真环境。禁止 `FakeHost` / `executor: mock` / 空 Agent Service 当完成证据。两个真实赢家（docker + e2b/ssh）才使 Protocol seam 成立。无凭证就 skip 该 job，不要标完成。
3. **locality。** `docker exec` 只活在 `plugins/contrib/docker/`。ACP / `attempt` / `run.py` 不得出现 `container_id`、`if kind == e2b`。厂商 SDK 不得进 `environments/protocol.py`。
4. **一条路径。** 选 executor / environment 只经注册表独占槽。禁止第二套 `resolve_executor`、CLI 旁路、application 里手 new Docker。
5. **composition root 唯一。** 平台对象（SDK client、docker CLI、SSH）只在 `application/composition.py` 的 `build_*` 连接。新公开 usecase 必须有 `build_*`。CLI 只 import composition。
6. **控制面不 import 题包模块当权威。** 经进程/适配器边界调 `run.py` / `evaluator.py`。一次 Attempt 只 `IdentityFactory.new_run` 一次。
7. **PASS / 身份 / cleanup 不是服务。** 插件 `exports` 不得覆盖这三样。cleanup 必须在 `try/finally`。
8. **adapter 按机制命名**（`docker` / `ssh` / `acp`），禁止按 bench / task 名分支。
9. **layout 字符串只在 `evidence/`。** lock / evidence / 默认环境禁止写入 host token。
10. **inject 在 lock 完成。** executor 只通过已 inject 的 `environment` 服务调用 Protocol。ACP 要 `attach_stdio`；环境内 worker 要 `exec` / `upload`。缺则拒绝，不能进入运行，不要等到 invoke 才检查 attach_stdio。`exec` 不是独立 service。

决策检查：改树先改 ARCHITECTURE；改红线先改 design；不要在代码里发明第二套 owner。
