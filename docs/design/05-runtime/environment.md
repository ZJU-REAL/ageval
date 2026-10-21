# Environment

环境通过独占槽 `environment` 接入，统一实现 `src/ageval/environments/protocol.py` 中的 `EnvironmentProvider` 协议，不向 Core 或上层模块暴露特定厂商的 SDK。源码结构与隔离约束见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)，接口方法定义见 [01](../01-ageval-core.md)。

环境内标准路径约定为：`/attempt/workspace`、`/attempt/home`、`/attempt/artifacts`、`/attempt/evaluation`。

```yaml
# profiles.yaml — 选择 environment 独占槽实现
format: ageval.profiles/1
environment: e2b    # local | docker | e2b | ssh | daytona
# environment_options:   # docker: image / platform / network / user / egress / egress_allow / python_version
#                        #         以及可选 network_mode / cap_add / main_environment
#                        # ssh: host / user / port / key_env / image
#                        # daytona: image / snapshot / timeout_seconds
# evaluate_host:         # 省略时复用 run 阶段环境进行评分
#   isolated: true       # 启动独立评分容器实例
#   environment_options: # 独立评分容器自身的网络与平台配置；省略时不继承待测 Agent 环境的 egress / egress_allow / network
#     egress: llm
#     egress_allow:
#       - registry.npmjs.org
```

## 环境类型（`kind`）与能力矩阵

任务 `requires.environment` 默认为空；非空时必须满足 `requires ⊆ capabilities`，否则 `ageval lock` 直接报错终止。

| 能力标记 | `local` | `docker` | `e2b` | `ssh` | `daytona` |
| --- | --- | --- | --- | --- | --- |
| `exec` / `upload` / `download` | yes | yes | yes | yes | yes |
| `attach_stdio` | 本机子进程管道 | `docker exec -i` | yes（SDK 双向 stdin 流） | `ssh -T` / 远程 `docker exec -i` | yes（session stdin + HTTP 日志流） |
| `uid_gid` / `path_views` | no | yes | no | no | no |
| `compose` | no | yes | no | 默认 no | no |

`path_views` 用于单容器内多角色的挂载与 UID 隔离（当前由 `docker` 提供）；参考材料（`gold`）的默认隔离不依赖 `path_views`，而是通过 `evaluate` 阶段延迟上传（或独立评分容器）实现。

任务的 `environment/Dockerfile`（或 `docker_image`）在 `docker`、`e2b` 与 `daytona` 间共用：
- `docker` 在本机构建镜像；
- `e2b` 通过 `Template.from_dockerfile` 构建云端模板并创建沙箱；
- `daytona` 通过 `Image.from_dockerfile`（或公开固定标签的 OCI 镜像，拒绝 `latest` / `lts` / `stable` 等浮动标签）构建 snapshot 并创建沙箱。

### 官方基础镜像与插件镜像层构建

官方 Attempt 基础镜像配方位于 `src/ageval/plugins/contrib/docker/attempt/`（随 `ageval-cli` 发行包分发）。运行时优先查找本地 `ageval-attempt:base`；若不存在则拉取 `ghcr.io/zju-real/ageval-attempt:<cli-ver>` 并标记为 `ageval-attempt:base`；若拉取未命中则使用包内 Dockerfile 在本地构建。

- `ARG PYTHON_VERSION` 指定基础镜像的 CPython 版本（默认 `3.12`）。当 `environment_options.python_version` 指定非默认版本（如 `"3.13"`）时，插件将任务配方中的 `FROM ageval-attempt:base` 解析为版本化标签（如 `ageval-attempt:py3.13`），不同 Python 版本的基础镜像可在本地并存。
- 任务 Dockerfile 也可直接基于其他发行版镜像（如 `FROM ubuntu:24.04`）：`docker` 插件在构建完任务配方后，按顺序叠加已绑定插件声明的 `config.image_layers`。ACP 插件仅在镜像中写入当前锁定的 `options.entry` 对应包版本（来自包内 `acp_entries.json` 与 `$AGEVAL_HOME/acp-entries.json` 的并集，且包内内置 ID 不可被覆盖），不在运行调用期间执行 `npm i` 或浮动 `npx`。Python 侧的 ACP SDK 仅驻留在宿主父进程中。
- ACP entry 在同一份表里声明 `runtime.node`（`>=主版本.次版本.补丁`）。插件层发现镜像里的 `node` 缺失或低于该下限时安装 Node 22.x，安装后仍低于下限则镜像构建失败；已经达到下限时保留任务配方中的 Node。任务 Dockerfile 里的业务软件包保持原样。下限写在 entry 上，由维护者随 pin 一起提交。

### Docker `environment_options` 参数

- `image` / `docker_image`：使用已有镜像标签，跳过本地 Dockerfile 构建。
- `platform`：目标架构平台（默认跟随宿主机）。
- `network`：Docker 网络名（默认 `bridge`；设为 `none` 时完全禁用容器网络）。若任务包含 `environment/compose.yaml`，Attempt 容器默认接入 `{project}_default` 网络（除非指定了 `network_mode: service:<name>`）。
- `egress`：省略时保持默认 `bridge` 网络。设为 `egress: llm`（仅支持 `docker`）时，容器内出站 HTTP(S) 流量经父进程白名单代理（`HTTP_PROXY` / `HTTPS_PROXY`）过滤，仅放行允许的目标域名。
- `egress_allow`：必须与同一字典下的 `egress: llm` 配合使用，为小写主机名列表（不含协议头、路径或端口）。有效放行域名为当前环境对应阶段绑定角色的 `base_url` 主机名与 `egress_allow` 的并集。
- `user`：容器内运行身份（`docker run --user` 及 `exec` / `attach_stdio` 共用），默认为 `10001:10001`；设为 `root`、`0` 或 `0:0` 时以 root 身份运行；容器始终附带 `no-new-privileges`。
- `python_version`：官方基础镜像的 CPython 次版本（格式 `^\d+\.\d+$`，默认 `"3.12"`）；若拉取或构建失败则直接报错，不静默回退至 `3.12`。

## 容器 CPU、内存与 GPU 限额

容器硬件资源限额声明在任务 `task.yaml` 的 `parameters` 下，在 `environment: docker` 的 `host.start` 阶段读取并施加（其他环境类型忽略这些参数）：

| 参数键 | 类型要求 | 省略、`0` 或空列表时 | `docker` 行为 |
| --- | --- | --- | --- |
| `cpus` | 非负整数或浮点数（拒绝布尔值） | 不添加 `--cpus` | `docker run --cpus <n>` |
| `memory_mb` | 非负整数（拒绝布尔值） | 不添加 `--memory` | `docker run --memory <n>m` |
| `gpus` | 非负整数（拒绝布尔值） | 不添加 `--gpus` | 大于 0 时请求对应数量的 GPU |
| `gpu_types` | 非空字符串列表 | 不按型号过滤 | 非空时要求宿主机可见 GPU 名称包含匹配子串（大小写不敏感） |
| `verifier_gpus` | 非负整数（拒绝布尔值） | 评分容器不添加 `--gpus` | 大于 0 时为独立评分容器分配对应数量的 GPU（沿用 `gpu_types` 过滤） |

当 `gpus > 0` 或 `gpu_types` 非空时，系统在启动容器前通过 `nvidia-smi` 检查宿主机可用 GPU；若数量不足、型号不匹配或 `nvidia-smi` 不可用，`environment` 阶段直接以 `environment_gpu_unavailable` 失败，不启动容器。Compose 辅助服务若声明了 `cpus` 或 `mem_limit` 且未设置 `deploy.resources.limits`，插件会自动生成 override 补齐该限额。

## 独立评分容器（`evaluate` 阶段可选配置）

当 `evaluate_host.isolated: true` 时，Core 在 `evaluate` 阶段（solver 会话封存之后）构造并启动独立的 `EnvironmentProvider` 实例（当前支持 `docker`）：

- **单独立评分容器：** 使用任务的 `environment/evaluate.Dockerfile` 或 `evaluation.docker_image`，叠加 `evaluate` 阶段绑定角色（如 `judge`）所需的 `image_layers`。
- **多命名评分容器：** 在 `task.yaml` 的 `evaluation.environments.<name>` 中声明 `dockerfile` 或 `docker_image`，每个命名容器拥有独立的工作目录（`eval-box/<name>`），在 `evaluator.py` 首次调用 `scoring.exec` 或 `Agent.session(..., environment=<name>)` 时按需启动。
- **完全隔离：** 评分容器拥有独立的工作区，不挂载待测 Agent 的实时工作区，也不挂载宿主 Docker daemon socket；产物快照（`task-artifacts/`）、收集路径（`verifier-collect/`）与参考材料（`evaluation/`）仅上传至已启动的评分容器。`cleanup` 阶段负责停止所有已启动的评分容器与运行环境。

## `attach_stdio` 双向流传输

`attach_stdio` 在已启动的环境中拉起前台进程并将标准输入/输出流交回宿主父进程，使 ACP 客户端无需关心底层环境差异：

| 环境类型 | `attach_stdio(argv)` 实现方式 |
| --- | --- |
| `local` | 本机 `Popen(argv)` |
| `docker` | `Popen(["docker", "exec", "-i", …, *argv])` |
| `ssh` 模式 A（远程整机） | `Popen(["ssh", "-T", …, "--", *argv])` |
| `ssh` 模式 B（远程容器） | `start()` 在远端执行 `docker run`，`attach_stdio` 执行 `ssh -- docker exec -i <cid> argv` |
| `e2b` | E2B SDK 双向标准输入/输出流 |
| `daytona` | Daytona session 命令输入流与日志管道 |

当缺少 `E2B_API_KEY`、`DAYTONA_API_KEY` 或 SSH 凭据时，`preflight` / `--probe` 直接返回未就绪状态，不创建云端沙箱或远程容器。

## 模块局部性（Locality）与产物收集

执行器通过 `inject: [service: environment]` 按服务名获取环境实例并在 `lock` 阶段核对能力标记（如 ACP 要求 `attach_stdio`，环境内 worker 要求 `exec` / `upload`）。

```text
ACP / acp-oneshot / dsh / nooa  invoke
        │  inject service: environment
        │  仅调用 EnvironmentProvider 协议方法 (attach_stdio / exec / upload)
        ▼
contrib/docker   → docker exec / compose / uid_gid / path_views
contrib/e2b      → E2B SDK 与模板缓存
contrib/daytona  → Daytona SDK 与 snapshot 管理
contrib/ssh      → SSH 模式 A/B 与远程 docker
contrib/local    → 本机目录
```

在 `run` 阶段结束、solver 会话封存后，Core 按 `artifacts.publishable` 声明统一收集一次产物快照至 `evidence/task-artifacts/`（单文件或按 `exclude` 过滤的 `tree` 目录快照），供后续 `evaluate` 与 `regrade` 消费。

## Docker Compose 辅助服务与 Attempt 容器参数

当任务包含 `environment/compose.yaml` 时，`docker compose up -d` 先启动辅助服务（自动剔除 `depends_on` 中指向 `main` 的依赖项），待测 Agent 仍运行在独立的 `docker run` 容器中。

针对待测 Agent 容器，`network_mode`、`cap_add` 与 `main_environment` 按以下优先级合并（后置覆盖前置，评分容器不读取这三项）：
1. `environment/docker-compose.yaml` 中 `services.main` 的对应字段（当该文件不作为 compose-up 主文件时）；
2. `task.yaml` 中 `parameters.network_mode`、`parameters.cap_add`、`parameters.main_environment`；
3. `profiles.yaml` 中 `environment_options` 的同名字段。

其中，`network_mode: service:<name>` 使待测 Agent 容器以 `docker run --network container:<id>` 共享指定 compose 服务的网络命名空间（与 `egress: llm` 互斥）；`main_environment` 通过 `docker run -e KEY=VALUE` 注入环境变量（拒绝无值键名，且过滤 `DOCKER_HOST` 等守护进程变量）；`cap_add` 转换为 `--cap-add`（仍保留 `no-new-privileges`）。
