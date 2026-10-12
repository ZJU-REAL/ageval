# 15 — Hosted jobs

Hub 上提交一份 suite，Registry 把任务排队，同一套部署里的 worker 拉走并跑 `ageval run`。笔记本不必一直开着。v1 环境只有 **e2b** 和 **daytona**。共享的 Hub / Registry 主机不跑租户 Docker / Podman，也没有用户自注册的 runner 或 SSH 执行面。

本页是机制。页面路径见 [website](../../website/content/docs/share/hosted.mdx)。没有 CLI `--launch`，也没有 MCP。

## 谁拥有什么

| 拥有 | 不拥有 |
| --- | --- |
| Registry `hosted` 聚合：组织密钥、hosted job 行、状态 | PASS、Attempt 身份、`limits` 的执行 |
| worker 进程：取密钥、改写 profiles、起 `ageval run`、走现有 suite 上传 | 在 API 进程里跑 Attempt；本机 Docker |
| dataset `profiles.yaml` + 选定的 Agent 包 | 第二套环境协议 |

worker 是部署里的另一个进程（`python -m services.registry.hosted.worker`），不是 HTTP 请求里的线程。它和 API 共用同一份元数据库和 blob。API 进程不调用 e2b / daytona SDK，也不挂载 Docker socket。

## 状态

`queued` → `running` → `succeeded` / `failed` / `canceled`。

| 终态 | 何时 |
| --- | --- |
| `succeeded` | suite 跑完并已上传。退出码 0（全 PASS）或 1（有 FAIL、没有 ERROR）。题的 PASS / FAIL 仍在 suite 上，hosted job 不另判 PASS |
| `failed` | 退出码 2、lock / 预检失败、密钥打不开、或上传失败 |
| `canceled` | 还在 `queued` 时取消，立即终态。已经 `running` 时只把 `cancel_requested` 记上，worker 往该 suite 目录写 `cancel.requested`，跑完后标 `canceled` |

崩溃的 worker 把行留在 `running`。`AGEVAL_HOSTED_STALE_SECONDS`（秒，省略或 `0` 表示不回收）到期后，下一次轮询把这种行退回 `queued`；已经请求取消的改成 `canceled`。默认不回收，避免一份还在跑的长 suite 被第二份同时打开。

## 提交

`POST /v1/hosted/jobs`。调用者必须是 `org_id` 的成员。dataset 必须是调用者能看见的 **dataset** release（`draft` 要有 draft 资格）。

| 字段 | 规则 |
| --- | --- |
| `environment` | `e2b` 或 `daytona`。其它值 `hosted_environment_refused`，不入队 |
| `version` | 已发布版本，或 `draft` |
| `model` | 这一次的 `binding.model` |
| `model_secret_id` | 同组织的 `kind=model` 密钥 |
| `provider_secret_id` | 同组织的 `kind=provider` 密钥，且 `provider` 等于 `environment` |
| `agent_ref` | 可空。空则用 dataset 自己的 profiles。否则是内置短 id（`pi`）或已装进 worker 的 `id@version` / `role=id@version`。worker 上没有的包，这一次 job 失败 |
| `max_concurrent_tasks` | 整数 1–32，默认 1 |
| `task_id` | 可空。空则整份 suite |

`max_concurrent_tasks` 只缩短墙钟，不改 PASS。单题且一次尝试时，suite 计划仍会把它收成 1，与本地 `ageval run` 相同。

## 密钥

组织密钥存在 `hosted_secrets`。明文只在创建请求里出现一次，随后是密文。列表和 job 行没有明文，也没有密文。

主密钥是环境变量 `AGEVAL_HOSTED_SECRET_KEY`：32 字节的 urlsafe-base64。加密是 HMAC-SHA256 计数器密钥流，再对密文做 HMAC-SHA256。缺这把钥匙时，创建密钥和 worker 解密都失败，不把明文落盘。

| kind | 谁读 | 写到哪 |
| --- | --- | --- |
| `model` | `ageval` 父进程按 profiles 里的 locator 投影进 ACP entry。这是 [agent-service](05-runtime/agent-service.md) 已有的契约：文件里只有 `${NAME}` | locator 由用户指定，形如 `OPENAI_API_KEY`。不能是 `E2B_API_KEY` / `DAYTONA_API_KEY`（及小写别名） |
| `provider` | worker 父进程用来开沙箱。e2b 固定 `E2B_API_KEY`，daytona 固定 `DAYTONA_API_KEY` | 只进入 `ageval` 子进程的环境，不写进 profiles、lock、evidence，也不改成模型 locator |

子进程环境会去掉另一家提供方的钥匙、`AGEVAL_HOSTED_SECRET_KEY`、Registry token 和对象存储钥匙。e2b / daytona 的沙箱只收调用方声明的环境，不收整份父环境。提供方钥匙因此留在开沙箱的进程上。

删除：创建者或该组织 owner。

## worker 怎么跑

1. 认领一行 `queued`（`status` 仍是 `queued` 才改成 `running`）。
2. 按 job 上的版本把 dataset blob 解到临时目录。
3. 写成一份 `ageval.profiles/1`：`environment` 改成该 job 的 e2b 或 daytona；每个 role 的 `model` 写成这次提交的 model id，`api_key` 写成 `${LOCATOR}`；extensions 里的环境插件（`docker` / `local` / `ssh` / `podman` / `e2b` / `daytona`）收成一行这个环境 id。写完后若文件里出现密钥明文，或 `environment` 不是 e2b / daytona，这一次失败，不起进程。
4. `python -m ageval.cli.main run <dataset> --profiles <file> --json`，带上 `--task` 和 `--max-concurrent-tasks`。
5. 用现有 `ResultsCommands.upload_suite_result(..., with_attempts=True)` 把 suite 和 Attempt 上传成 **private**。上传者是提交 job 的用户。Hub 上已有的 suite 页负责终态结果。
6. 删临时目录。

`evaluate_host.isolated` 仍要求 `environment: docker`。这种 dataset 在 hosted v1 上会 lock 失败，worker 不会改去跑 Docker。

镜像里可以带 e2b / daytona 的安装 extra，供 worker 开沙箱。这不表示 API 进程会起容器。

## HTTP

都要登录。组织以外的人看组织密钥或按组织列 job，是 `404`。

| 方法 | 路径 |
| --- | --- |
| `POST` | `/v1/orgs/{org_id}/secrets` |
| `GET` | `/v1/orgs/{org_id}/secrets` |
| `DELETE` | `/v1/orgs/{org_id}/secrets/{secret_id}` |
| `POST` | `/v1/hosted/jobs` |
| `GET` | `/v1/hosted/jobs?org_id=&dataset_id=` |
| `GET` | `/v1/hosted/jobs/{job_id}` |
| `POST` | `/v1/hosted/jobs/{job_id}/cancel` |

Hub：dataset 页 **Hosted** 提交并轮询状态；终态有 `suite_run_id` 时链到已有 suite 页。组织页 **Secrets** 管理密钥。

## 真沙箱冒烟（Hub 路径）

队列、密钥、profiles 改写、认领、上传接线有自动测试（含 `upload_hosted_suite` 离线测）。Hub 真路径已用两边钥匙各跑通一份最小 hosted suite（本地发布的 `smoke/minimal-demo@0.1.3-hosted2`，不必落在本仓库树里）：

| 环境 | hosted job | suite_run_id | 终态 |
| --- | --- | --- | --- |
| e2b | `d0d43320e45d3958` | `23967a1c` | `succeeded`（已上传） |
| daytona | `9c4676eadf36772c` | `c3845df3` | `succeeded`（已上传） |

`succeeded` 只表示 suite 跑完并上传；题的 PASS / FAIL 仍在 suite 上。云沙箱若只吃 Dockerfile、不应用 ACP `image_layers`，ACP agent（如 pi）要把 Node 等运行时 bake 进镜像，否则会 `acp_runtime_install_failed`。截图等 UI 证据挂在 PR / release 附件上，不进产品树。
