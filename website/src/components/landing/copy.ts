import type { SiteLocale } from "@/lib/i18n";

export const landingCopy = {
  "zh-CN": {
    metaTitle: "ageval · 可配置可插拔的智能体评测统一框架",
    metaDescription:
      "通过插件切换待评测 Agent 与运行环境；安装 CLI 和 skill 支持 Agent 自动完成评测；在 ageval Hub 上共享与复用 dataset、插件和 Agent 包。",
    skip: "跳到正文",
    navAria: "页面导航",
    nav: {
      problem: "问题",
      position: "定位",
      environment: "环境",
      eval: "自动评测",
      plugin: "插件",
      faq: "FAQ",
      docs: "文档",
      hub: "Hub",
      menu: "目录",
      repo: "仓库",
      lang: "EN",
      themeToDark: "切换到深色",
      themeToLight: "切换到浅色",
    },
    hero: {
      titleA: "可配置可插拔的",
      accentA: ["可配置", "可插拔"],
      titleB: "智能体评测统一框架",
      accentB: [],
      note: "通过插件组合环境与待测 Agent；安装 CLI 和 skill，让 Agent 自动执行评测。",
      primary: "打开仓库",
      hub: "前往 Hub",
      secondary: "阅读文档",
      startAria: "开始使用",
      startTabs: ["快速开始", "安装源码"],
      copy: "复制",
      copied: "已复制",
      demo: "查看演示",
      demoAria: "产品演示视频：可配置可插拔的智能体评测，切换待评测 Agent，自动跑完看结果",
      demoClose: "关闭",
    },
    pactAria: "三个特点",
    pact: [
      [
        "一键切换待测 Agent",
        "无需修改框架或任务代码：安装插件并在配置中切换一行，同一份 dataset 即可跨配置运行。",
      ],
      [
        "让 Agent 自主执行评测",
        "安装 CLI 和 skill，支持 coding agent 设计、转换 benchmark 并端到端完成评测。",
      ],
      [
        "在 Hub 上共享与复用",
        "在 ageval Hub 上共享或复用 dataset、插件和 Agent 包，并归档可追溯的评测结果。",
      ],
    ] as const,
    problem: {
      index: "// 01",
      name: "The Problem",
      title: ["评测不能只比模型。", "真正执行任务的是 Model + Harness。"],
      items: [
        [
          "01 / MODEL",
          "仅替换模型标识",
          "固定提示词、工具和调用流程，仅将模型从 A 换成 B 并记录单个分数。",
        ],
        [
          "02 / HARNESS",
          "实际运行的是完整 Agent",
          "决定任务表现的是模型与外层 harness（交互循环、工具调用与执行控制）的组合。",
        ],
        [
          "03 / DRIFT",
          "更换 harness 或环境，表现随之改变",
          "同一模型接入不同 harness 或运行在不同环境中，任务通过率与调用开销均会发生变化。",
        ],
        [
          "04 / RECORD",
          "缺少配置锁定的分数难以对比",
          "仅报告模型名称无法复现实验条件：必须同时记录绑定的 harness、模型参数与运行环境。",
        ],
      ] as const,
      solLabel: "SOLUTION →",
      sol: "ageval 通过声明式插件组合环境与待测 Agent，在运行前锁定完整配置（lock），保障对照实验可复现、分数可对比",
    },
    position: {
      index: "// 02",
      name: "Positioning",
      title: "固定运行时基座，用插件组合组件。",
      lead: "ageval Core 管理固定的评测流水线：lock → environment → run → evaluate → record。执行环境与 Agent 执行器均通过插件槽接入，无需修改基座或任务代码即可替换。",
      flow: {
        aria: "单次 Attempt 的控制流：从外部输入经 lock 到 evidence 归档",
        svgDesc:
          "外部输入（用户、dataset、profiles）经 lock、environment、run、evaluate、record 到达 evidence。插件在 lock、environment、run 接入；limits 与 cleanup 贯穿全程。",
        user: "用户",
        userMeta: "lock / run / view",
        dataset: "dataset",
        datasetMeta: "ageval.yaml · tasks/",
        profiles: "profiles",
        profilesMeta: "profiles.yaml",
        pluginBind: "插件绑定",
        pluginBindMeta: "extension_bindings",
        pluginBindNote: "在此校验能力与模型契约",
        envPlugins: "环境插件",
        envPluginsMeta: "local · docker · e2b",
        envPluginsNote: "daytona · ssh",
        agentPlugins: "Agent 插件",
        agentPluginsMeta: "ACP（默认）",
        agentPluginsNote: "nooa · dsh · miniswe",
        lock: "lock",
        lockMeta: "lock.json · digest",
        environment: "环境",
        environmentMeta: "local / docker / e2b…",
        run: "run.py",
        runMeta: "任务循环 · ACP",
        evaluate: "evaluator.py",
        evaluateMeta: "PASS / FAIL / ERROR",
        evidence: "evidence",
        evidenceMeta: ".ageval/runs/<id>/",
        coreNote:
          "ageval Core · 单次 Attempt 启动受控环境，顺序执行 run.py 与独立评分 evaluator.py",
        limits: "limits · 执行前强制",
        limitsMeta: "(墙钟 · 内存 · 进程 · 调用次数)",
        cleanup: "cleanup · finally 始终执行",
        cleanupMeta: "(任何退出路径 · 环境与凭据安全回收)",
        legend: "LEGEND",
        legendExt: "外部输入 · Core 之外",
        legendCore: "单次 Attempt · Core 边界",
        legendEvidence: "evidence · 归档目录",
        legendPass: "绑定 PASS",
        legendPhase: "阶段推进",
        legendPlugin: "插件接入点",
        notes: [
          [
            "INPUTS",
            "用户输入、dataset 与 profiles 从外部传入。dataset 定义评测任务与评分标准；环境与角色配置写在 profiles.yaml 中，与任务逻辑解耦。",
          ],
          [
            "LOCK",
            "ageval lock 解析插件依赖图（ExtensionGraph），静态校验组件接口、能力依赖与 ModelSpec 参数契约并生成 lock.json。配置不兼容时直接报错终止。",
          ],
          [
            "ENVIRONMENT",
            "启动选定环境并上传任务输入数据。支持本机目录、Docker 容器、云沙箱（E2B、Daytona）或远程 SSH，切换环境无需重写 dataset。",
          ],
          [
            "RUN",
            "run.py 在执行阶段驱动任务交互循环、本地工具与角色会话调用；更换底层环境或待测 Agent 无需修改任务脚本。",
          ],
          [
            "EVALUATE",
            "封存 solver 会话后上传参考材料（gold）并启动独立 evaluator.py。支持确定性脚本评分与独立 judge 角色的 Agent-as-judge 评分，仅 evaluator.py 可产出 PASS 或 FAIL。",
          ],
          [
            "RECORD",
            "锁定配置、评分结果、交互轨迹与产物快照归档至 evidence（lock.json · result.json · trajectory.jsonl），并在 finally 中始终执行环境 cleanup。",
          ],
        ] as const,
      },
    },
    environment: {
      index: "// 03",
      name: "Environment",
      title: "切换运行环境，无需重写 dataset。",
      lead: "同一份任务可在本机、Docker 容器、云沙箱或远程主机上运行。环境通过插件接入，在 profiles.yaml 中一行切换。",
      items: [
        [
          "ENV · LOCAL",
          "本机目录",
          "真实文件系统，子进程直接执行。",
          "开箱即用",
          false,
        ],
        [
          "ENV · DOCKER",
          "本机容器",
          "容器化隔离；参考材料（gold）在评分阶段才上传至评分环境。",
          "开箱即用",
          true,
        ],
        [
          "ENV · E2B / SSH / DAYTONA",
          "云沙箱与远程环境",
          "本机统一编排，安装对应 SDK 并配置凭据后即可远程执行。",
          "需要凭据",
          false,
        ],
      ] as const,
    },
    eval: {
      index: "// 04",
      name: "Auto",
      title: "让 Agent 自主完成评测。",
      lead: "安装 CLI 和 skill 后，coding agent 可设计、转换 benchmark 并自动执行评测。内置 skill 支持按需加载。",
      tableAria: "内置 skill",
      columns: ["Skill", "功能说明"],
      skills: [
        ["ageval-platform", "仓库架构总览：职责边界、配置锁定与评分规范。"],
        ["ageval-cli", "运行 lock / run / campaign，查阅与上传评测结果。"],
        [
          "ageval-config-package",
          "编写与转换 dataset：ageval.yaml、task.yaml、profiles.yaml。",
        ],
        ["ageval-sdk-harness", "编写任务脚本：AgentSession、工具与产物发布。"],
        ["ageval-plugin", "开发插件：接入执行环境或 Agent 执行器。"],
      ] as const,
      steps: [
        ["01 CLI", "uv tool install ageval-cli"],
        ["02 skill", "npx skills add ZJU-REAL/ageval"],
        ["03 跑评测", "Agent 设计、转换 benchmark 并端到端完成评测。"],
      ] as const,
    },
    plugin: {
      index: "// 05",
      name: "Plugin",
      title: "声明式插件组合环境与 Agent。",
      lead: "更换待测 Agent 或环境无需修改框架源码：安装插件并在 profiles.yaml 中切换绑定。",
      slots: [
        [
          "ENV",
          "环境插件",
          "支持本机 / Docker / 云沙箱 / 远程 SSH。实现统一环境接口即可扩展新后端。",
        ],
        [
          "AGENT",
          "Agent 执行器插件",
          "默认经 ACP 接入（pi / Codex / Claude Code / OpenCode）；nooa / dsh / miniswe 通过同一插件槽接入。",
        ],
        [
          "LOCK",
          "运行前静态校验",
          "在 lock 阶段校验插件能力依赖、模型参数契约与凭据引用，不兼容配置在运行前直接终止。",
        ],
      ] as const,
      exampleTag: "EXAMPLE · DSH",
      exampleTitle: "以插件方式接入 DeepSeek Harness，无需改动 ageval 源码。",
      exampleBody:
        "dsh 采用不同于 ACP 的通信机制，同样通过 executor 插件槽接入：安装对应 extra 并在 profiles 中将 executor 设为 dsh，同一份任务即可原样运行。缺少 DEEPSEEK_API_KEY 时会在 lock / preflight 阶段直接报错终止。",
      exampleCode: `# 安装 dsh 插件依赖
uv tool install 'ageval-cli[dsh]'

# 将 executor 切换为 dsh，任务与 dataset 无需改动
ageval run <dataset> --task <task-id> \\
  --profiles profiles.dsh.yaml   # executor: dsh`,
    },
    cta: {
      title: ["安装 CLI 和 skill，", "开始可复现的 Agent 评测。"],
      primary: "打开仓库",
      hub: "前往 Hub",
      docs: "阅读文档",
    },
    faq: {
      index: "// 06",
      name: "FAQ",
      title: "常见问题",
      items: [
        [
          "如何切换待评测的 Agent？",
          [
            "待测对象是由模型与 harness 构成的完整 Agent（如 pi、Codex、Claude Code、dsh 等）。框架与 dataset 均无需改动：安装对应插件并在 profiles.yaml 中切换绑定，同一份任务即可直接运行。",
            "内置 Agent 包可直接通过 --agent pi（配合可选 --model）调用，无需预先安装；自定义 Agent 包先执行 ageval agent install，再通过 --agent org/name@version 绑定。",
          ],
        ],
        [
          "安装 CLI 后，如何让本机 Agent 自己跑评测？",
          [
            "执行 uv tool install ageval-cli 与 npx skills add ZJU-REAL/ageval。Skill 会指导 coding agent 调用 lock / run 命令及编写 dataset，从而自主设计或转换 benchmark 并完成评测。",
            "实际运行 coding agent 需要本机具备对应的 ACP 入口与凭据；仅执行 ageval lock 校验配置时则不需要。缺少依赖或凭据时会在预检阶段直接报错并给出安装提示。",
          ],
        ],
        [
          "如何运行 Hub 上的 dataset 并分享评测结果？",
          [
            "使用 ageval registry list 查看可见的 dataset，再执行 ageval run <org>/<name>@<version>（或指定本地 dataset 目录）。默认 profiles 使用 environment: docker，需确保本机 Docker 引擎已启动。",
            "dataset、插件、Agent 包与评测结果均可发布到 ageval Hub 供他人复现与对比；本机也可通过 ageval view 打开本地结果，或生成 /s/{token} 只读快照链接。",
          ],
        ],
        [
          "编写一份 dataset 需要准备哪些文件？",
          [
            "评测数据集的交付单位是 dataset：根目录包含 ageval.yaml，每个任务位于 tasks/<id>/ 下，包含 task.yaml、执行脚本 run.py、评分脚本 evaluator.py、输入数据 data/ 与参考材料 evaluation/。环境与角色配置写在外部 profiles.yaml 中。",
            "任务脚本负责业务交互循环与评分准则；配置锁定、环境生命周期、结果绑定与 finally 清理均由 ageval Core 管理。Python SDK 不决定 PASS，也不持有宿主明文凭据。",
          ],
        ],
        [
          "如何开发自定义环境或 Agent 插件？",
          [
            "通过编写 ageval.plugin/1 插件扩展环境或 executor 独占槽，无需 fork 框架源码。插件声明自身提供的槽位及通过 inject 依赖的服务能力，安装后即可在 profiles.yaml 中选用。",
            "若插件声明的能力依赖或模型契约不满足要求，ageval lock 会在运行前直接拦截。",
          ],
        ],
        [
          "切换本机、Docker 或云沙箱需要重写 dataset 吗？参考材料会暴露给待测 Agent 吗？",
          [
            "无需重写 dataset。在 profiles.yaml 中将 environment 切换为 local、docker 或 e2b / ssh / daytona，同一份任务即可在不同后端运行。",
            "参考材料（gold）存放在 tasks/<id>/evaluation/ 下，在 run 阶段不会挂载到待测 Agent 的工作区，仅在 solver 封存后的 evaluate 阶段上传至评分环境。",
          ],
        ],
      ] as const,
    },
    footer: {
      copy: "ZJU-REAL",
    },
  },
  en: {
    metaTitle: "ageval · Configurable and pluggable agent evaluation framework",
    metaDescription:
      "Swap evaluated agents and environments via declarative plugins. Empower coding agents to author and run benchmarks with the CLI and skills. Share datasets, plugins, and Agent packages on ageval Hub.",
    skip: "Skip to content",
    navAria: "Page navigation",
    nav: {
      problem: "Problem",
      position: "Positioning",
      environment: "Environment",
      eval: "Auto eval",
      plugin: "Plugin",
      faq: "FAQ",
      docs: "Docs",
      hub: "Hub",
      menu: "Menu",
      repo: "Repo",
      lang: "中文",
      themeToDark: "Switch to dark",
      themeToLight: "Switch to light",
    },
    hero: {
      titleA: "Configurable and pluggable",
      accentA: ["Configurable", "pluggable"],
      titleB: "agent evaluation framework",
      accentB: [],
      note: "Compose environments and evaluated agents with plugins. Equip coding agents with the CLI and skills to run evaluations end to end.",
      primary: "Open repo",
      hub: "Go to Hub",
      secondary: "Read the docs",
      startAria: "Get started",
      startTabs: ["Quick start", "From source"],
      copy: "Copy",
      copied: "Copied",
      demo: "Watch demo",
      demoAria:
        "Product demo: a configurable, pluggable agent evaluation framework — swap the agent under test and run it end to end",
      demoClose: "Close",
    },
    pactAria: "Three things you can do",
    pact: [
      [
        "Swap the evaluated agent in one line",
        "Keep task logic unchanged: install a plugin, update one line in config, and run the same dataset across configurations.",
      ],
      [
        "Automate evaluation with coding agents",
        "Install the CLI and skills so a coding agent can design, convert, and run benchmarks end to end.",
      ],
      [
        "Share and reuse on Hub",
        "Publish datasets, plugins, Agent packages, and traceable evaluation results on ageval Hub.",
      ],
    ] as const,
    problem: {
      index: "// 01",
      name: "The Problem",
      title: [
        "Evaluation cannot compare models alone.",
        "What executes tasks is Model + Harness.",
      ],
      items: [
        [
          "01 / MODEL",
          "Swapping only the model ID",
          "Prompts, tools, and interaction loops stay fixed while model B replaces model A to produce a single number.",
        ],
        [
          "02 / HARNESS",
          "The full agent system does the work",
          "Task outcomes depend on the model together with the harness managing the interaction loop, tool calls, and execution state.",
        ],
        [
          "03 / DRIFT",
          "Changing harness or environment shifts scores",
          "The same model paired with a different harness or execution environment yields different pass rates and resource costs.",
        ],
        [
          "04 / RECORD",
          "Unlocked configurations cannot be compared",
          "Reporting a bare model name leaves the harness, model parameters, and environment unspecified, making scores non-comparable.",
        ],
      ] as const,
      solLabel: "SOLUTION →",
      sol: "ageval composes environments and agent executors through plugins and locks the full configuration before execution, making scores reproducible and comparable",
    },
    position: {
      index: "// 02",
      name: "Positioning",
      title: "Keep Core fixed. Swap components with plugins.",
      lead: "ageval Core coordinates a fixed pipeline: lock → environment → run → evaluate → record. Execution environments and agent executors connect via declarative plugin slots without modifying Core or task scripts.",
      flow: {
        aria: "Control flow of a single Attempt: from external inputs through lock to archived evidence",
        svgDesc:
          "External inputs (User, dataset, profiles) flow through lock, environment, run, evaluate, and record into evidence. Plugins bind at lock, environment, and run. Limits and cleanup span every phase.",
        user: "User",
        userMeta: "lock / run / view",
        dataset: "dataset",
        datasetMeta: "ageval.yaml · tasks/",
        profiles: "profiles",
        profilesMeta: "profiles.yaml",
        pluginBind: "plugin binding",
        pluginBindMeta: "extension_bindings",
        pluginBindNote: "capabilities & contracts checked here",
        envPlugins: "environment plugins",
        envPluginsMeta: "local · docker · e2b",
        envPluginsNote: "daytona · ssh",
        agentPlugins: "Agent plugins",
        agentPluginsMeta: "ACP (default)",
        agentPluginsNote: "nooa · dsh · miniswe",
        lock: "lock",
        lockMeta: "lock.json · digest",
        environment: "environment",
        environmentMeta: "local / docker / e2b…",
        run: "run.py",
        runMeta: "task loop · ACP",
        evaluate: "evaluator.py",
        evaluateMeta: "PASS / FAIL / ERROR",
        evidence: "evidence",
        evidenceMeta: ".ageval/runs/<id>/",
        coreNote:
          "ageval Core · each Attempt provisions an environment and runs run.py followed by isolated evaluator.py",
        limits: "limits · enforced before execution",
        limitsMeta: "(wall-clock · memory · processes · calls)",
        cleanup: "cleanup · finally, always runs",
        cleanupMeta: "(every exit path · environment and credentials released)",
        legend: "LEGEND",
        legendExt: "external · outside Core",
        legendCore: "single Attempt · Core boundary",
        legendEvidence: "evidence · archive",
        legendPass: "binds PASS",
        legendPhase: "phase advance",
        legendPlugin: "plugin slot",
        notes: [
          [
            "INPUTS",
            "User commands, dataset definitions, and profiles enter from outside. The dataset defines task logic and grading criteria; environment and role bindings live externally in profiles.yaml.",
          ],
          [
            "LOCK",
            "ageval lock resolves the plugin dependency graph (ExtensionGraph) and validates interface contracts, capability requirements, and ModelSpec parameters into lock.json, failing fast on mismatch.",
          ],
          [
            "ENVIRONMENT",
            "Provision the selected environment and upload task input files. Switch among local processes, Docker containers, cloud sandboxes, or SSH hosts via profiles.yaml without rewriting the dataset.",
          ],
          [
            "RUN",
            "run.py drives the task interaction loop, local tools, and bound role sessions inside the environment; swapping the environment or harness leaves task scripts untouched.",
          ],
          [
            "EVALUATE",
            "After sealing solver sessions, Core uploads reference materials (gold) and runs evaluator.py. Supports deterministic scripts and multi-step Agent-as-judge with an independent judge profile; only evaluator.py can issue PASS or FAIL.",
          ],
          [
            "RECORD",
            "Locked configurations, verdicts, trajectories, and artifact snapshots are archived in evidence (lock.json · result.json · trajectory.jsonl), while cleanup runs unconditionally in finally.",
          ],
        ] as const,
      },
    },
    environment: {
      index: "// 03",
      name: "Environment",
      title: "Swap environments. Keep the dataset.",
      lead: "Run the same task on your host machine, in a local container, in a cloud sandbox, or over SSH by changing one line in profiles.yaml.",
      items: [
        [
          "ENV · LOCAL",
          "Host directory",
          "Real filesystem with subprocess execution.",
          "RUNS TODAY",
          false,
        ],
        [
          "ENV · DOCKER",
          "Local container",
          "Container isolation; reference materials (gold) are uploaded only during evaluate.",
          "RUNS TODAY",
          true,
        ],
        [
          "ENV · E2B / SSH / DAYTONA",
          "Cloud sandboxes and remote hosts",
          "Local orchestration with remote execution once the provider SDK and credentials are configured.",
          "NEEDS CREDENTIALS",
          false,
        ],
      ] as const,
    },
    eval: {
      index: "// 04",
      name: "Auto",
      title: "Teach coding agents automated evaluation.",
      lead: "Install the CLI and skills so a coding agent can design, convert, and run benchmarks end to end. Load only the skills your task requires.",
      tableAria: "Built-in skills",
      columns: ["Skill", "What it does"],
      skills: [
        [
          "ageval-platform",
          "Architecture overview: ownership boundaries, configuration locking, and evaluation rules.",
        ],
        [
          "ageval-cli",
          "Run lock / run / campaign; inspect, regrade, and upload results.",
        ],
        [
          "ageval-config-package",
          "Author or convert a dataset: ageval.yaml, task.yaml, and profiles.yaml.",
        ],
        ["ageval-sdk-harness", "Write task scripts: AgentSession, tools, and artifact publishing."],
        ["ageval-plugin", "Develop plugins: environment providers and agent executors."],
      ] as const,
      steps: [
        ["01 CLI", "uv tool install ageval-cli"],
        ["02 skill", "npx skills add ZJU-REAL/ageval"],
        ["03 run", "The coding agent designs, converts, and runs the benchmark."],
      ] as const,
    },
    plugin: {
      index: "// 05",
      name: "Plugin",
      title: "Compose environments and agents with plugins.",
      lead: "Swap the evaluated agent or environment by installing a plugin and updating profiles.yaml — with zero changes to ageval Core.",
      slots: [
        [
          "ENV",
          "Environment plugins",
          "Host / Docker / cloud sandbox / remote SSH. Implement the unified EnvironmentProvider protocol to add a backend.",
        ],
        [
          "AGENT",
          "Executor plugins",
          "ACP by default (pi / Codex / Claude Code / OpenCode); nooa / dsh / miniswe connect through the same executor slot.",
        ],
        [
          "LOCK",
          "Static verification at lock",
          "Unmatched capability requirements, model parameters, or credential locators fail fast during lock before execution begins.",
        ],
      ] as const,
      exampleTag: "EXAMPLE · DSH",
      exampleTitle:
        "DeepSeek Harness connects as an executor plugin — zero lines changed in ageval Core.",
      exampleBody:
        "Although dsh uses its own JSON-RPC runtime rather than ACP, it plugs into the same executor slot: install the extra, set executor to dsh in profiles, and run the same task. Missing credentials fail fast at lock/preflight.",
      exampleCode: `# Install the dsh plugin extra
uv tool install 'ageval-cli[dsh]'

# Switch executor to dsh; task and dataset remain untouched
ageval run <dataset> --task <task-id> \\
  --profiles profiles.dsh.yaml   # executor: dsh`,
    },
    cta: {
      title: ["Install the CLI and skills.", "Start running reproducible evals."],
      primary: "Open repo",
      hub: "Go to Hub",
      docs: "Read the docs",
    },
    faq: {
      index: "// 06",
      name: "FAQ",
      title: "FAQ",
      items: [
        [
          "How do I switch the evaluated agent?",
          [
            "ageval evaluates the combined agent system (Model + Harness, such as pi, Codex, Claude Code, or dsh) rather than a bare model ID. Install the corresponding plugin and update profiles.yaml to run the same dataset without modifying task code.",
            "Built-in Agent packages bind directly with --agent pi (and optional --model). Custom Agent packages install via ageval agent install and bind with --agent org/name@version.",
          ],
        ],
        [
          "After installing the CLI, how does my coding agent run evaluations?",
          [
            "Run uv tool install ageval-cli and npx skills add ZJU-REAL/ageval. The skills teach your coding agent how to invoke lock / run and author datasets, allowing it to convert benchmarks and execute evaluations end to end.",
            "Live coding-agent runs require the corresponding ACP entry and credentials on the host, whereas ageval lock validates configuration without starting an agent. Missing extras or credentials fail preflight with an explicit install hint.",
          ],
        ],
        [
          "How do I run a dataset from Hub and share results?",
          [
            "Use ageval registry list to inspect available datasets, then run ageval run <org>/<name>@<version> (or pass a local dataset root). Default profiles use environment: docker, which requires a running Docker engine.",
            "Publish datasets, plugins, Agent packages, and suite results to ageval Hub for reproducible comparison, inspect runs locally with ageval view, or generate a read-only /s/{token} snapshot link.",
          ],
        ],
        [
          "What files belong in a dataset?",
          [
            "A dataset is the standard delivery unit: ageval.yaml sits at the root, and each task lives under tasks/<id>/ with task.yaml, interaction logic in run.py, grading logic in evaluator.py, input files in data/, and reference materials in evaluation/. Environment and role bindings stay external in profiles.yaml.",
            "Task scripts own the interaction loop and grading criteria, while ageval Core manages configuration locking, environment provisioning, verdict binding, and finally cleanup. The Python SDK never decides PASS or holds plaintext host secrets.",
          ],
        ],
        [
          "How do I author a custom environment or agent plugin?",
          [
            "Create an ageval.plugin/1 package that implements the environment or executor exclusive slot and declares its required service capabilities via inject. Once installed, select it in profiles.yaml without forking ageval.",
            "If declared capability dependencies or model parameters are unsatisfied, ageval lock fails fast before execution starts.",
          ],
        ],
        [
          "Do I need to rewrite the dataset to switch among host, Docker, and cloud sandboxes? Can the solver see reference materials?",
          [
            "No rewrite is needed. Switch environment in profiles.yaml among local, docker, e2b, ssh, or daytona to run the same task across backends.",
            "Reference materials (gold) live under tasks/<id>/evaluation/, remain unmounted during the run phase, and are uploaded to the scoring environment only when evaluate begins.",
          ],
        ],
      ] as const,
    },
    footer: {
      copy: "ZJU-REAL",
    },
  },
} as const;

export type LandingCopy = (typeof landingCopy)[SiteLocale];
