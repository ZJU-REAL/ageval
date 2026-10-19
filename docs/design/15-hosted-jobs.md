# 15 — 云端托管评测作业（Hosted Jobs）

登录用户可在 Hub 上直接提交一份 suite 评测请求，由 Registry 将作业加入队列，并由同一部署环境中的后台 worker 进程拉取数据集、在云沙箱中运行 `ageval run` 并回传结果。当前支持 **e2b** 与 **daytona** 两种云沙箱环境；共享的 Hub / Registry 宿主机不直接启动租户 Docker 容器。

## 职责边界

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| Registry `hosted` 模块 | 管理组织加密密钥、托管作业队列与状态流转 | 判定任务 `PASS`、签发 Attempt 身份、执行 `limits` 控制 |
| 后台 Worker 进程 | 解密凭据、生成运行期 `profiles.yaml`、调用 `ageval run` 并上传 suite 结果 | 在 HTTP API 进程内直接执行评测、挂载宿主机 Docker socket |
| Dataset 与选定 Agent 包 | 定义任务逻辑、默认配置与角色绑定 | 维护第二套环境协议 |

后台 worker 作为独立进程运行（`python -m services.registry.hosted.worker`），与 Registry API 共享元数据库与对象存储。

## 作业状态机

`queued` → `running` → `succeeded` / `failed` / `canceled`。

| 终态 | 触发条件 |
| --- | --- |
| `succeeded` | suite 运行结束并成功上传（包括 `ageval run` 退出码为 `0` 全通过或 `1` 存在任务 `FAIL` 但无运行时 `ERROR` 的情况；具体单题 `PASS` / `FAIL` 记录在上传的 suite 中） |
| `failed` | `ageval run` 退出码为 `2`、`lock` / `preflight` 失败、密钥解密失败或结果上传失败 |
| `canceled` | 在 `queued` 状态取消时立即进入 `canceled`；在 `running` 状态取消时设置 `cancel_requested` 并向运行目录写入 `cancel.requested`，待运行收尾后标记为 `canceled` |

若 worker 进程意外终止导致作业停留在 `running`，可通过设置环境变量 `AGEVAL_HOSTED_STALE_SECONDS`（正整数秒；默认为 `0` 即不自动回收，防止长时任务被重复启动）在后续轮询中将超时作业退回 `queued`（已请求取消的作业则直接标为 `canceled`）。

## 提交接口与参数

`POST /v1/hosted/jobs`（调用方须为目标 `org_id` 成员，且对目标 `dataset` 版本具备读取权限）：

| 字段 | 规则 |
| --- | --- |
| `environment` | 仅允许 `e2b` 或 `daytona`；其他值直接拒绝（`hosted_environment_refused`） |
| `version` | 已发布版本号或 `draft` |
| `model` | 本次运行使用的模型 ID，写入生成的 `profiles.yaml` 中各角色的 `model.id` |
| `model_secret_id` | 同一组织下 `kind=model` 的密钥 ID |
| `provider_secret_id` | 同一组织下 `kind=provider` 且 `provider` 与 `environment` 一致的云沙箱密钥 ID |
| `agent_ref` | 可选；为空时使用 dataset 自带的 `profiles.yaml`，否则指定内置短 ID（如 `pi`）或 worker 已安装的 Agent 包 |
| `max_concurrent_tasks` | 并发任务数（整数 `1–32`，默认 `1`） |
| `task_id` | 可选；为空时运行整份 suite |

## 组织密钥管理（`hosted_secrets`）

组织密钥在创建请求中接收一次明文，使用环境变量 `AGEVAL_HOSTED_SECRET_KEY`（32 字节 urlsafe-base64 主密钥）经 HMAC-SHA256 流加密与消息认证后存储；列表与作业查询接口绝不返回明文或密文。

| 密钥类型 (`kind`) | 用途与注入边界 |
| --- | --- |
| `model` | 推理 API 密钥。locator 名称须匹配 `^[A-Z][A-Z0-9_]{0,63}$` 且以 `_API_KEY`、`_KEY` 或 `_TOKEN` 结尾（如 `OPENAI_API_KEY`，禁止使用 `E2B_API_KEY` / `DAYTONA_API_KEY`）。生成的 `profiles.yaml` 仅写入 `${LOCATOR}` 引用，由 `ageval` 父进程按白名单注入待测 Agent 进程。 |
| `provider` | 云沙箱提供方密钥（固定为 `E2B_API_KEY` 或 `DAYTONA_API_KEY`），仅保留在开启云沙箱的宿主机子进程环境中，不写入 `profiles.yaml`、`lock.json`、归档证据或沙箱内部环境。 |

## Worker 执行流程

1. 原子认领一条 `queued` 作业并将其状态更新为 `running`。
2. 将目标版本的 dataset 归档解压至临时工作目录。
3. 生成运行期 `ageval.profiles/1` 配置文件：将 `environment` 设为目标云沙箱（`e2b` 或 `daytona`），将各角色的 `model` 规范化为嵌套对象并填入本次提交的 `model.id`，将 `api_key` 设为 `${LOCATOR}`，并将环境扩展插件更新为对应云沙箱插件。
4. 调用 `python -m ageval.cli.main run <dataset> --profiles <file> --json`（附带可选的 `--task` 与 `--max-concurrent-tasks`）。
5. 通过 `ResultsCommands.upload_suite_result(..., with_attempts=True)` 将生成的 suite 与 Attempt 证据作为 `private` 结果上传至 Registry，并在作业记录上关联生成的 `suite_run_id`。
6. 清理本地临时工作目录。

注意：启用了 `evaluate_host.isolated: true` 的 dataset 依赖 `environment: docker`，在云端托管作业（仅支持 `e2b` / `daytona`）下会在 `lock` 阶段报错拒绝。

## HTTP 路由

| 方法 | 路径 |
| --- | --- |
| `POST` | `/v1/orgs/{org_id}/secrets` |
| `GET` | `/v1/orgs/{org_id}/secrets` |
| `DELETE` | `/v1/orgs/{org_id}/secrets/{secret_id}` |
| `POST` | `/v1/hosted/jobs` |
| `GET` | `/v1/hosted/jobs?org_id=&dataset_id=` |
| `GET` | `/v1/hosted/jobs/{job_id}` |
| `POST` | `/v1/hosted/jobs/{job_id}/cancel` |
