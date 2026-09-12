# 10 — 点名示例

这里不是进度表。

必须能 `ageval lock`（有凭证则 run）的包：

| 包 | 点名 |
| --- | --- |
| `examples/datasets/minimal-demo` | `terminal-jsonl-agg`、`tau2-dialog-min`、`multiagent-env-min` |
| docker topology 示例 | `sdk-session-single-actor` lock；`multi-agent-*` lock 有 topology 即可（本轮不承诺多 group 真调度 run） |
| `examples/datasets/tau3-airline-5` | `airline-00` lock |
| `examples/agents` | `dsh-default` / `nooa-default` / `miniswe-default`；`--agent` 绑定 |

docker 默认在 `examples/datasets/minimal-demo/profiles.yaml`。e2b 见同目录 `profiles.e2b-*.yaml`。ssh A 不支持 live ACP stdio。

不要把 gaia / tau3 全 suite、五条 ACP 全付费 invoke 当成「设计漏了」。产品禁止 `examples/agents/mock-default`。
