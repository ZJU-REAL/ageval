# 06 — 环境能力标记与参考材料隔离

环境插件显式声明其支持的 `capabilities` 集合。当任务 `requires.environment` 非空时，`lock` 阶段校验 `requires ⊆ capabilities`，不满足则在运行前直接报错终止。`Result` 记录实际使用的环境 `kind` 与 `capabilities_used`。

标准能力标记包括：`exec`、`upload`、`download`、`attach_stdio`、`uid_gid`、`path_views`、`compose`。五种环境的完整能力矩阵见 [05-runtime/environment.md](05-runtime/environment.md)，协议定义见 `src/ageval/environments/protocol.py`。

## 参考材料（Gold）隔离

参考材料（`evaluation/`）默认通过**阶段边界**与待测 Agent 隔离：在 `environment` 与 `run` 阶段不挂载、不上传 `evaluation/`；仅当 `run` 阶段结束并封存 solver 会话后，`evaluate` 阶段才将参考材料上传至评分环境（或在 `evaluate_host.isolated: true` 下上传至独立的 Docker 评分容器）并运行 `evaluator.py`。

```text
environment / run     待测 Agent 环境中不存在 /attempt/evaluation
evaluate 开始         向评分环境上传 evaluation/ → 运行 evaluator.py
```

`path_views` 是用于单容器内多角色不同挂载视图的扩展能力（当前由 `docker` 提供），不替代 `evaluate` 阶段的参考材料延迟上传机制。

宿主凭据仅以环境变量名（locator）引用，并按最小白名单注入获准的子进程，绝不写入 `lock.json` 或归档证据中（详见 [ARCHITECTURE.md](../../ARCHITECTURE.md) § Failure and Privacy Boundaries）。
