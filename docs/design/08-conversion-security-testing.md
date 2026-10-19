# 08 — Benchmark 转换、凭据安全与测试准则

## Benchmark 转换约定

将上游 benchmark 转换为 ageval **dataset** 时：
- 每个任务保持精简的 `run.py` 与 `evaluator.py`，跨任务复用的交互循环、工具桥接与公共评分逻辑集中放在 dataset 根目录的 `shared/lib` 下（通过 `from shared.lib…` 导入）。
- 在 `ageval.yaml` 或 `task.yaml` 中填写 `provenance` 溯源信息（上游仓库 URL、版本或 commit，以及已知差异说明）。
- 框架插件与适配器统一按协议或执行机制命名，不在 Core 中按特定 benchmark 名称编写分支。

## 凭据与容器镜像安全

- 配置文件（`ageval.yaml`、`task.yaml`、`profiles.yaml`）、锁定记录（`lock.json`）与归档证据中仅保存环境变量名（locator），绝不写入明文密钥。
- 子进程与容器环境仅按白名单注入声明过的凭据变量（BYOK）或复制受控的订阅认证文件（BYOA，不直接挂载宿主机整个 `$HOME`）。
- 官方 Attempt 基础镜像（`src/ageval/plugins/contrib/docker/attempt/`）与任务 Dockerfile 在**镜像构建阶段**固定安装所需的 Python 依赖与 ACP 运行时，并在构建时校验可导入性，避免在运行调用期间执行 `apt-get`、`pip install` 或 `npm i`。
- Docker 构建不会自动隐式拷贝 dataset 根目录的 `shared/`；若容器内脚本需导入 `shared.lib.*`，需在 Dockerfile 中显式声明 `COPY` 与 `PYTHONPATH`。

## 测试与验收准则

- 端到端验收以公开 CLI（`ageval lock` / `ageval run`）配合真实环境实现（`local`、`docker` 等）为准。
- 缺少外部凭据或设置 `AGEVAL_SKIP_REAL_ACP=1` 时，对应测试记为跳过（not run / skip），不视为通过验收，也不使用模拟执行器（`executor: mock`）伪造通过结果。
