# 08 — 转换、安全、测试

上游题包迁进来：薄 `run.py` / `evaluator.py`，共享逻辑进 `shared/lib`（`from shared.lib…`）。填 `provenance`。适配器禁止按 bench 名分支。

安全：locator only；lock/evidence 无 token；ACP 凭据按 allowlist 投影进子进程（BYOK 缺钥则不能进入运行 / BYOA allowlist copy，不 mount 宿主 `$HOME`）。

测试面是公开 CLI + 真实 kind。无凭证 skip 该 job，不标完成。禁止 FakeHost / `executor: mock`。默认 CI skip 真 ACP/E2B/SSH，不得提供 mock 绿路径。`AGEVAL_SKIP_REAL_ACP=1` 只表示 CI 没跑这条。

官方 Attempt 镜像由 `src/ageval/plugins/contrib/docker/attempt/` 构建（题包 `FROM ageval-attempt:base`）。非基座配方（例如 `FROM ubuntu:24.04`）由绑定插件的 `image_layers` 在题图上补依赖；ACP 只 bake 当前 `options.entry`。`FROM` 此基座不是上游 runtime：钉死 checkout 实际 import 的版本，在 **image build** 门禁，不要靠运行时 `apt`/`pip`/`npm i` 当默认等价路径。Core **不会**隐式 COPY `shared/` 进镜像。

lock 成功、Hub 上架、改 import 契约 **都不**升级证据等级。
