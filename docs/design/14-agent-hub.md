# 14 — Agent 对象

format `ageval.agent/1`。一条 binding：executor、entry、overlays。Registry `package_kind=agent`。

CLI：`ageval agent install …` 后 `--agent local/id@version` 投影进 profiles。不要把 Agent 包当成第二套 lock 权威。

已上传 suite 可延后写入 published `agent_ref`（只改 Registry `job_overlay`）。对齐尺子是 `_binding_role_key`，与 `--agent` 互斥的 `--profiles` 路径补溯源，不是第二套 lock。plaza 规则不变。Appearances 另需该 Agent 包 org 同意：owner 自己 attach，或批准 `agent_appearance` 请求。

产品禁止 mock-default Agent。
