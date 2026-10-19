# 09 — 模块职责矩阵与结构约束

完整的当前源码树、模块依赖图与生命周期状态机以 [ARCHITECTURE.md](../../ARCHITECTURE.md) 为准。本文列出各核心模块的职责边界与不可退化的结构约束。

## 模块职责矩阵（Owner Matrix）

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| Core Config (`config/`) | `load_and_lock`、配置摘要（digest）、schema format 与能力依赖校验 | 启动环境、执行任务或评分 |
| Model (`model/`) | `ModelSpec` 解析与校验（`resolve_model`） | 网关特定参数名单、HTTP 请求构造、评分判定 |
| Attempt (`attempt/`) | 固定阶段顺序、身份传递、阶段计时器与 `finally cleanup` | 特定厂商 SDK、容器内部细节 |
| Environment plugins (`plugins/contrib/<kind>/`) | 对应环境的启停、文件传输、命令执行与 `attach_stdio` 实现 | ACP 协议解析、`PASS` 裁决 |
| ACP plugin (`plugins/contrib/acp/`) | 父进程 JSON-RPC 客户端、ACP entry 注册表、`attach_stdio` 消费 | `docker exec` 底层拼接、非结构化终端输出抓取 |
| Task `run.py` | 任务交互循环、本地领域工具、产物登记 | `PASS` 裁决、宿主凭据读取、环境启停 |
| Task `evaluator.py` | 评分逻辑与 `PASS` / `FAIL` 判定 | 启动待测 solver、持有宿主明文密钥 |
| Evidence (`evidence/`) | `.ageval/runs/` 路径常量、敏感信息脱敏、`trajectory.jsonl` 封存 | 厂商协议解析、`PASS` 裁决 |
| CLI (`cli/`) | 命令行参数解析、标准输出/错误格式化、退出码 | 业务逻辑组装（仅调用 `application.composition.build_*`） |
| Registry HTTP (`services/registry/`) | 数据集/插件/Agent 包与评测结果存储、托管作业队列 | 签发单题 `PASS` |
| Python SDK (`ageval_sdk`) | 任务脚本会话与工具辅助类型 | 控制面内部状态、凭据管理、`PASS` 裁决 |

## 目标源码树（`src/ageval/`）

```text
src/ageval/
  __init__.py
  cli/                      # 解析命令行参数，调用 composition.build_*
  application/
    composition.py          # 唯一生产组合根（composition root）
    lock.py                 # load_and_lock + 能力与 inject 依赖图校验
    run.py                  # 签发 Attempt 身份，调用 attempt.run_attempt
    regrade.py              # 基于产物快照的重新评分入口
    suite/
    plugin_ops/
    registry_ops/
    agent_ops/              # --agent（及可选 --model）投影至 profiles
    local_jobs/
    analysis/               # 运行后只读分析（stats / hack / review）
  attempt/                  # 单次 Attempt 阶段流水线
    __init__.py             # run_attempt 固定阶段序列
    ctx.py                  # AttemptCtx：持有 host / services / lock / bindings
    emit.py                 # 链槽调度器
    phases/
      environment.py        # 启动环境 · 运行时准备 · setup.sh
      run.py                # 子进程执行 run.py
      evaluate.py           # 封存 solver · 路径收集 · 上传参考材料 · evaluator.py
      record.py             # 收集并封存轨迹与运行摘要
      cleanup.py            # finally 环境清理
  config/                   # dataset、task.yaml 与 profiles.yaml 解析
  model/                    # ModelSpec 与 resolve_model
  plugins/                  # 插件槽注册表、服务表与依赖注入解析
    base.py                 # BaseEnvironment · BaseExecutor
    decorators.py           # @environment_plugin · @executor_plugin
    slots.py                # 独占槽与链槽标识定义
    registry.py / resolve.py / bootstrap.py / builtin.py
    contrib/                # 内置环境与执行器插件
      acp/
      openai_http/
      anthropic_http/
      docker/
      local/
      e2b/
      daytona/
      ssh/
    defaults/               # environment_setup、默认 evaluation_runtime 与 trajectory_seal
  environments/             # EnvironmentProvider 协议与能力定义（不含厂商 SDK）
    protocol.py
  runtime/                  # 身份签发、时钟表、ParentAgentService 与子进程启动器
    identity.py
    parent_agent.py
    task_launch.py / task_worker.py / eval_worker.py
  evaluation/               # 阶段屏障与 bind_evaluation
  evidence/                 # 证据目录布局与轨迹封存
  capabilities/             # 授权操作与配额管理
  registry/                 # Hub HTTP 客户端
```

外置插件位于仓库根目录 `plugins/`（通过 `ageval plugin install` 安装至 `~/.ageval/plugins`）。

## 结构约束（Structural Invariants）

1. **直观的阶段入口：** 打开 `attempt/__init__.py` 即可看到完整的顶层阶段顺序，不将单次运行流程拆散到多个平级脚本中。
2. **真实环境测试面：** 端到端测试基于公开 CLI 与真实环境实现（`local`、`docker` 等），不使用模拟环境或 `executor: mock` 替代。
3. **模块局部性（Locality）：** `docker exec` 仅存在于 `plugins/contrib/docker/` 中；ACP、`attempt/` 与 `run.py` 不感知 `container_id`，也不编写 `if kind == "e2b"` 等环境分支；`environments/protocol.py` 不导入任何云厂商或容器 SDK。
4. **单一插件解析路径：** 环境与执行器统一通过 `ExtensionRegistry` 的独占槽解析，不另建旁路解析函数。
5. **唯一的组合根：** 平台对象仅在 `application/composition.py` 的 `build_*` 中装配，CLI 仅导入 `composition`。
6. **进程隔离边界：** 控制面不将任务目录下的 `run.py` 或 `evaluator.py` 作为进程内模块导入，统一通过子进程边界调用；单次 Attempt 仅调用一次 `IdentityFactory.new_run`。
7. **引擎核心不变量不可覆盖：** `PASS` 绑定、Attempt 身份签发与 `finally cleanup` 不作为可替换插件服务导出。
8. **按机制命名：** 插件与适配器按协议或执行机制命名（`docker`、`ssh`、`acp`、`openai-http`），禁止按 benchmark 或任务名分支。
9. **统一证据路径管理：** `.ageval/runs` 布局字符串集中在 `evidence/` 中维护，且绝不写入明文密钥。
10. **锁定阶段完成依赖注入校验：** 执行器所需的 `environment` 服务能力（如 ACP 要求 `attach_stdio`，环境内 worker 要求 `exec` / `upload`）在 `ageval lock` 阶段完成静态校验，不留到运行期中途报错。

当修改模块结构或架构约束时，在阶段收尾时同步更新 [ARCHITECTURE.md](../../ARCHITECTURE.md) 与本目录对应文档。
