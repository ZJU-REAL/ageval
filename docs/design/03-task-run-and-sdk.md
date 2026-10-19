# 03 — 任务脚本 `run.py` 与 Python SDK

任务执行入口为 **`run.py`**（`async def run(ctx: RunContext) -> RunTerminal`）。`ageval_sdk` 与 `ageval` 同属 `ageval-cli` 发行包，通过架构测试保障单向依赖边界（`ageval_sdk` 不导入 `ageval` 内部模块）。

`ageval_sdk` 提供任务脚本所需的会话与工具辅助接口，不管理 Run 身份、环境启停、宿主凭据或最终 `PASS` 判定。

## 职责边界

| `run.py` 负责 | `run.py` 禁止 |
| --- | --- |
| 组织交互循环、多角色路由、领域工具调用、通过 `ctx.publish_json` / `ctx.publish_tree` 登记产物 | 直接产出最终 `PASS` 裁决 |
| 通过 `ctx.agent.session(profile_id).invoke` 调用已绑定角色 | 读取或持有宿主明文凭据 |
| 读取 `ctx.params` 与工作区文件 | 绕过 `lock` 自行读取外部配置文件 |
| 返回 `RunTerminal.completed` 或 `RunTerminal.failed` | 修改 `limits` 配额或按 benchmark 名称编写框架分支 |
| 在子进程内执行领域工具与状态更新 | 调用 `host.start` / `host.upload` / `host.stop` 或读取 `evaluation/` |

父进程控制面通过独立子进程启动 `run.py`，角色调用经 Unix domain socket 转发至父进程 `ParentAgentService`。在 `run.py` 启动前，`environment` 阶段已完成环境启动、初始数据上传与 `setup.sh` 初始化。

## 最小示例

```python
from ageval_sdk import RunContext, RunTerminal

async def run(ctx: RunContext) -> RunTerminal:
    async with ctx.agent.session("solver", max_turns=1) as session:
        reply = await session.invoke(ctx.params["instruction"])
    ctx.publish_json("reply", {"ok": bool(reply.get("ok")), "text": reply.get("text") or ""})
    if not reply.get("ok"):
        return RunTerminal.failed(str(reply.get("error") or "invoke_failed"))
    return RunTerminal.completed("ok")
```

## SDK 导出接口

```python
from ageval_sdk import (
    Agent,
    AgentSession,
    RunContext,
    RunParameterView,
    RunScope,
    RunTerminal,
    ScriptError,
    Tool,
    ToolSet,
    AllowList,
    CallLimit,
    bounded_gather,
    first_success,
    evaluation_check,
)
```

| 符号 | 用途 |
| --- | --- |
| `RunContext` | 提供 `params`、`workspace`、`artifact_dir`、`agent` 与产物发布方法 |
| `RunTerminal` | 表示 `run.py` 的执行终态（`completed` / `failed`），不决定 `PASS` |
| `ScriptError` | 当 `run.py` 或 `evaluator.py` 自身因配置或脚本异常无法继续时抛出（含稳定标签 `title` 与当次说明 `message`），计为对应阶段的 `ERROR` |
| `Agent.session(profile_id)` | 通过本机 Unix socket 连接父进程 `ParentAgentService` 开启角色会话 |
| `ToolSet` / `CallLimit` | 任务内领域工具集合与软性调用次数护栏（不替代 Core 的 `limits`） |
| `evaluation_check` | 构造 `evaluator.py` 可选返回的 `checks` 检查项明细 |

当领域工具在 `run.py` 子进程内执行完毕后，可调用 `AgentSession.record_observation` 将工具返回结果附加到当前调用事件中，由 `record` 阶段统一归档至 `trajectory.jsonl`。

### 在 `evaluate` 阶段调用 SDK（Agent-as-judge）

`evaluator.py` 同样在父进程的受限子进程中运行。在 `evaluation/` 参考材料上传完成后，`evaluator.py` 可调用 `Agent.session(<role>).invoke`（该角色需在 `profiles.yaml` 中独立声明，且不复用 solver 的凭据引用）。

- 在 `evaluate_host.isolated: true` 模式下，ACP `attach_stdio` 自动连接至独立评分容器；若任务声明了 `evaluation.environments` 命名评分容器表，则 ACP 角色调用必须显式指定 `Agent.session(id, environment=<name>)`（未知名称或在 `run` 阶段传入 `environment=` 会直接报错 `unknown_evaluate_environment`）。`openai-http` 与 `anthropic-http` 执行器在父进程发起请求，忽略 `environment=` 参数。
- `evaluate` 阶段产生的会话轨迹单独写入 `evaluation/observation.jsonl`（自动省略 `user` 提示行以防泄露参考材料），不混入根 `trajectory.jsonl`。
- `evaluator.py` 最终仍须返回 `{status, score, metrics}`，由 `bind_evaluation` 绑定 `PASS` 或 `FAIL`。

## 单次 Attempt 内的多会话并发

`Agent.session`、`invoke`、`record_observation` 与 `close` 均采用异步通信，支持在单次 Attempt 内并发开启多个会话（包括绑定同一角色 profile 的多个独立会话，各自维护独立的消息历史）。同一个会话内部的多次 `invoke` 按到达顺序串行执行。

- **`bounded_gather(aws, *, limit, timeout=None)`：** 在并发上限 `limit` 内执行一组协程并按输入顺序返回结果列表。单个子任务抛出的 `Exception` 保留在对应位置，不影响其他已完成结果；若设置 `timeout`（秒）到期，未完成位置填入 `TimeoutError`，其余在途任务被取消并排干。
- **`first_success(aws, *, limit=None, accept=None)`：** 在并发上限内返回首个未抛异常且满足 `accept` 谓词的结果（例如 `accept=lambda reply: reply.get("ok") is True`），随后立即取消并排干其余未完成子任务；若全部子任务均未满足条件则抛出 `RuntimeError("no acceptable result")`。该原语仅用于任务内控制流选择，不替代 `evaluator.py` 的 `PASS` 判定。
- 任务脚本指定的 `limit` 受 Core 的 `limits.agent_concurrency` 约束，不能突破运行时并发上限。

### 分步脚本评分（`scoring.exec` 与 `checks`）

在 `evaluate` 阶段，`evaluator.py` 可通过注入的 `inputs["scoring"]` 在命名评分容器中执行验证命令，并通过 `evaluation_check` 构造分步检查结果：

```python
from ageval_sdk import evaluation_check

audit = await scoring.exec("audit", ["python", "/attempt/evaluation/audit.py"])
return {
    "status": "PASS" if audit.exit_code == 0 else "FAIL",
    "score": 1.0 if audit.exit_code == 0 else 0.0,
    "checks": [
        evaluation_check(
            "audit",
            status="PASS" if audit.exit_code == 0 else "FAIL",
            script="evaluation/audit.py",
            environment="audit",
            exec_result=audit,
        )
    ],
}
```

首次调用某个命名评分容器时，Core 自动启动该容器并上传产物快照与参考材料。`checks` 列表由父进程写入 `evaluation/checks.json` 供界面展示，最终 `Result` 的 `status` 与 `score` 仍仅取决于顶层返回字段。

## 结构化工具调用通道（`tools` 与 `messages`）

`AgentSession.invoke` 默认接受纯文本 `prompt`，同时支持传入可选的 `tools` 与 `messages` 参数：

| 参数 | 含义 |
| --- | --- |
| `tools` | OpenAI 函数调用格式的工具声明列表：`[{type: "function", function: {name, description?, parameters}}]` |
| `messages` | 显式对话历史列表（包含 `user`、`assistant`、`tool_calls` 与 `tool` 消息轮次） |

- **HTTP 执行器（`openai-http`、`anthropic-http`）：** 根据绑定的 API 协议编码 `tools` 与 `messages`，并在返回字典的 `tool_calls` 字段中返回结构化调用列表 `[{id, name, arguments}]`。任务脚本在本地执行对应工具后，通过 `session.record_observation(...)` 记录观测结果：

```python
reply = await session.invoke(
    instruction,
    tools=catalog,
    messages=history,
)
for call in reply.get("tool_calls") or ():
    obs = await tools.call(call["name"], call["arguments"])
    await session.record_observation(
        str(call.get("id") or ""),
        content=str(obs),
        raw_output=obs,
        function_name=str(call.get("name") or ""),
        invocation_id=reply.get("invocation_id"),
    )
```

- **ACP 执行器（`executor: acp`）：** 忽略 `tools` 与 `messages` 参数，由环境内的交互式 harness 根据文本 prompt 自主管理工具调用循环。
