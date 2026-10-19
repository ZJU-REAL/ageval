# 10 — 仓库内置示例范围

本文列出仓库 `examples/` 目录下内置维护的示例数据集与 Agent 包，供本地回归校验与用法演示使用：

| 示例路径 | 包含内容与验证目标 |
| --- | --- |
| `examples/datasets/minimal-demo` | `terminal-jsonl-agg`（终端文件聚合）、`tau2-dialog-min`（双角色工具对话）、`multiagent-env-min`（多角色与数据库工具） |
| `examples/datasets/concurrent-research` | `fanout`（单次 Attempt 内多会话受控并发） |
| `examples/datasets/tau3-airline-5` | `airline-00` … `airline-04`（τ³-bench airline 域 5 题子集转换） |
| `examples/agents` | `dsh-default`、`nooa-default`、`miniswe-default`（外置执行器的 `ageval.agent/1` 配置包示例；内置 ACP 直接使用 `--agent pi` 等短 ID） |

`examples/datasets/minimal-demo/profiles.yaml` 默认使用 `environment: docker` 与 ACP `entry: pi`；同目录下提供 `profiles.nooa.yaml`、`profiles.dsh.yaml` 与 `profiles.e2b-*.yaml` 等备选运行配置。

完整 50 题 τ³-airline 及其他大规模转换数据集通过 Hub 发布与分发，不在代码仓库内保存全量副本。
