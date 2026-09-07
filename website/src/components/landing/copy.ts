import type { SiteLocale } from "@/lib/i18n";

export const landingCopy = {
  "zh-CN": {
    metaTitle: "ageval · 配置一次 Agent Eval，任意切换运行",
    metaDescription:
      "一键切换待评测 Agent；装上 CLI 和 skill，让 Agent 学会自动评测；在 ageval Hub 上分享或复用 dataset、插件和 Agent 配置。",
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
    },
    hero: {
      titleA: "配置一次 Agent Eval，",
      accentA: "一次",
      titleB: "任意切换运行",
      accentB: "任意",
      note: "装插件换待评测 Agent。装上 CLI 和 skill，Agent 能自己跑评测。",
      primary: "打开仓库",
      hub: "前往 Hub",
      secondary: "阅读文档",
      startAria: "开始使用",
      startTabs: ["快速开始", "安装源码"],
      copy: "复制",
      copied: "已复制",
      demo: "查看演示",
      demoAria: "产品演示视频：配置一次评测，切换待评测 Agent，自动跑完看结果",
      demoClose: "关闭",
    },
    pactAria: "三个特点",
    pact: [
      [
        "SWITCH",
        "一键切换待评测 Agent",
        "换 Agent 不改 ageval：装插件，在配置里切一行，同一份 dataset 原样跑。",
      ],
      [
        "TEACH",
        "让 Agent 学会自动评测",
        "装上 CLI 和 skill，让 Agent 能设计、转化 benchmark，并自动跑评测。",
      ],
      [
        "HUB",
        "在 Hub 上分享与复用",
        "在 ageval Hub 上分享或复用 dataset、插件和 Agent 配置，并上传评测结果。",
      ],
    ] as const,
    problem: {
      index: "// 01",
      name: "The Problem",
      title: ["评测还在只比模型。", "可真正干活的是 Agent。"],
      items: [
        [
          "01 / MODEL",
          "只换模型名",
          "提示词、工具和流程全都不动，把模型从 A 换成 B，跑一遍记一个分。",
        ],
        [
          "02 / RUNTIME",
          "实际运行的是 Agent",
          "决定最终表现的是模型加上外层的 coding agent 运行时；模型只是其中一块。",
        ],
        [
          "03 / DRIFT",
          "换个跑法，分数就变",
          "同一个模型，接上不同的 coding agent、放进不同的环境，任务得分和调用成本都会不一样。",
        ],
        [
          "04 / RECORD",
          "只报模型名，分数没法比",
          "『模型 X 跑了 80 分』说明不了什么：是哪个 Agent 运行时、哪套环境跑出来的？不说清就没法比。",
        ],
      ] as const,
      solLabel: "SOLUTION →",
      sol: "ageval 用插件组合环境与待测 Agent，把每次运行的组合写入不可变的 lock，分数才有得比",
    },
    position: {
      index: "// 02",
      name: "Positioning",
      title: "运行基座不动，装插件换 Agent。",
      lead: "ageval 的运行时基座是一条固定流水线：lock → environment → run → evaluate → record。环境和 Agent 运行时都经插件接入，不必修改基座；装插件，在配置里切一行，同一份 dataset 原样跑。",
      flow: {
        aria: "一次运行的控制流：输入之后从 lock 走到 evidence",
        svgDesc:
          "外部输入（用户、dataset、profiles）经 lock、environment、run、evaluate、record 到达 evidence。插件在 lock、environment、run 接入；limits 与 cleanup 横贯全程。",
        user: "用户",
        userMeta: "lock / run / view",
        dataset: "dataset",
        datasetMeta: "ageval.yaml · tasks/",
        profiles: "profiles",
        profilesMeta: "profiles.yaml",
        pluginBind: "插件绑定",
        pluginBindMeta: "extension_bindings",
        pluginBindNote: "能力 / 凭证在此检查",
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
          "ageval Core · 一次运行打开一个环境，run.py 与 evaluator 在其中执行",
        limits: "limits · 执行前强制",
        limitsMeta: "(墙钟 · 内存 · 进程 · 调用次数)",
        cleanup: "cleanup · finally 始终执行",
        cleanupMeta: "(任何退出路径 · 环境与凭据回收)",
        legend: "LEGEND",
        legendExt: "外部输入 · Core 之外",
        legendCore: "一次运行 · Core 边界",
        legendEvidence: "evidence · 焦点",
        legendPass: "绑定 PASS",
        legendPhase: "阶段推进",
        legendPlugin: "插件接入点",
        notes: [
          [
            "INPUTS",
            "用户输入、dataset 与 profiles 从外部传入。dataset 定义评测任务；环境和 Agent 写在 profiles.yaml，不绑进 dataset。",
          ],
          [
            "LOCK",
            "ageval lock 静态解析依赖图（ExtensionGraph），将插件与基座接入点绑定，写入 lock.json。能力或凭证对不上，这里失败，不会开跑。",
          ],
          [
            "ENVIRONMENT",
            "打开一个环境，把 task 文件传进去。本机、Docker、云沙箱或远端：换环境改 profiles，不重写 dataset。",
          ],
          [
            "RUN",
            "run.py 在环境里跑任务循环。循环、本地工具和对 Agent 的调用都写在这份文件里；换环境或换 Agent 不用改它。",
          ],
          [
            "EVALUATE",
            "评分独立，只有 evaluator.py 能给出 PASS。默认确定性脚本，也支持 LLM-as-judge 与多阶段打分。评测容器网络隔离（如 network: none），参考答案到这一阶段才 upload。",
          ],
          [
            "RECORD",
            "分数和轨迹写入 evidence（lock.json · result.json · trajectory.jsonl）。无论结果如何，cleanup 都会执行。",
          ],
        ] as const,
      },
    },
    environment: {
      index: "// 03",
      name: "Environment",
      title: "换环境，不重写 dataset。",
      lead: "同一份 task 在本机、容器、云沙箱、远端上跑。环境是 profiles.yaml 里的一行，经插件接入。",
      items: [
        [
          "ENV · LOCAL",
          "本机目录",
          "真文件系统，子进程直接跑。",
          "开箱即跑",
          false,
        ],
        [
          "ENV · DOCKER",
          "本机容器",
          "同一份 Dockerfile。参考答案到评分阶段才进环境。",
          "开箱即跑",
          true,
        ],
        [
          "ENV · E2B / SSH / DAYTONA",
          "云沙箱与远端",
          "编排仍在本机。装上 SDK、配好凭证即可进入运行。",
          "需要凭证",
          false,
        ],
      ] as const,
    },
    eval: {
      index: "// 04",
      name: "Auto",
      title: "让 Agent 学会自动评测。",
      lead: "装上 CLI 和 skill，Agent 能设计、转化 benchmark，并自动跑评测。内置 skill 按任务装，不必一次全上。",
      tableAria: "内置 skill",
      columns: ["Skill", "做什么"],
      skills: [
        ["ageval-platform", "进仓库时读：谁 lock、谁打分、红线是什么。"],
        ["ageval-cli", "跑 lock / run / campaign，看结果、上传。"],
        [
          "ageval-config-package",
          "写 dataset：ageval.yaml、task.yaml、profiles。",
        ],
        ["ageval-sdk-harness", "写 run.py：session、工具、publish。"],
        ["ageval-plugin", "写插件：接环境或 Agent 运行时。"],
      ] as const,
      steps: [
        ["01 CLI", "uv tool install ageval-cli"],
        ["02 skill", "npx skills add ZJU-REAL/ageval"],
        ["03 跑评测", "Agent 设计、转化 benchmark，并自动跑完。"],
      ] as const,
    },
    plugin: {
      index: "// 05",
      name: "Plugin",
      title: "一键切换待评测 Agent。",
      lead: "换 Agent 不改 ageval：装插件，在 profiles 里切一行。环境同理。",
      slots: [
        [
          "ENV",
          "环境插件",
          "本机 / Docker / 云沙箱 / 远端。缺哪样就补一个插件，基座不动。",
        ],
        [
          "AGENT",
          "Agent 运行时插件",
          "默认 ACP（pi / Codex / Claude Code / OpenCode）；nooa / dsh / miniswe 走同一条插件路。",
        ],
        [
          "LOCK",
          "装上即检",
          "插件要的能力或凭证对不上，lock 就失败，不会开始跑。",
        ],
      ] as const,
      exampleTag: "EXAMPLE · DSH",
      exampleTitle: "接入 DeepSeek 官方 harness，没改 ageval 一行源码。",
      exampleBody:
        "dsh 与 ACP 机制完全不同，照样以插件方式接入：装上 extras，在 profiles 里把 executor 切成 dsh，同一份 task 原样开跑。缺少 DEEPSEEK_API_KEY 时 lock 阶段直接拦截——装上即检在起作用。",
      exampleCode: `# dsh 是插件，不是 ageval 的分支
uv tool install 'ageval-cli[dsh]'

# executor 切成 dsh；task 与 dataset 原样
ageval run <dataset> --task <task-id> \\
  --profiles profiles.dsh.yaml   # executor: dsh`,
    },
    cta: {
      title: ["装上 CLI 和 skill，", "开始跑评测。"],
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
          "怎么切换待评测的 Agent？",
          [
            "待评测的是 coding agent（pi、Codex、Claude Code、dsh 这类），不是只换一个模型名。基座和 dataset 都不动：装上对应插件，在 profiles.yaml 里切换，同一份 task 原样跑。",
            "内置 Agent 包可以直接 --agent pi，不必先 install。自定义 Agent 包先 ageval agent install，再 --agent org/name@version。环境和绑定写在 profiles.yaml，不写进 dataset。换 Agent 不用 fork 框架。",
          ],
        ],
        [
          "装上 CLI 之后，怎么让本机 Agent 自己跑评测？",
          [
            "uv tool install ageval-cli，再 npx skills add ZJU-REAL/ageval。skill 会告诉你的 coding agent 怎么调用 lock / run，以及怎么写 dataset。之后可以由 Agent 设计或转化 benchmark，并自动跑评测。",
            "跑真的 coding agent 还需要本机 ACP 入口和凭据；只做 ageval lock 检查配置时不需要。缺 extras 或凭据时，检查不过就不会开始跑，报错里会写该装什么。",
          ],
        ],
        [
          "Hub 上的 dataset 怎么跑？结果怎么分享？",
          [
            "ageval registry list 查看当前可见的 dataset，然后 ageval run <org>/<name>@<version>。也可以直接跑本地 dataset 根目录。默认 profiles 用 environment: docker，需要本机有可用的 Docker 引擎。",
            "dataset、插件和 Agent 配置都可以在 ageval Hub 上分享或复用，评测结果也可以上传。别人拿去是为了接着跑，不只是看一张分数表。本机用 ageval view 按 Jobs → Tasks 打开一次运行。",
          ],
        ],
        [
          "写一份 dataset 要准备哪些文件？",
          [
            "评测的组织单位是 dataset。根目录放 ageval.yaml；每个 task 一个 tasks/<id>/，里面是 task.yaml、任务循环 run.py、评分 evaluator.py，以及参考答案。环境和 Agent 绑定写在 profiles.yaml，不要在 dataset 里绑死某一种运行时。",
            "任务循环、角色和本地工具留在 task 里。lock 锁定依赖图、打开环境、将分数绑定到 Result 以及清理环境，全由 ageval 负责。SDK 是可选的，不决定 PASS，也不持有宿主凭据。",
          ],
        ],
        [
          "想接自己的环境或 Agent，插件怎么写？",
          [
            "给 ageval 写插件，不要改 ageval 源码。插件声明自己补的是环境还是 Agent 运行时，装上之后在 profiles 里切换。默认走 ACP；dsh、nooa、miniswe 也是同一类插件。",
            "插件声明的能力或凭证如果对不上，ageval lock 会失败，不会开始跑。",
          ],
        ],
        [
          "换成本机、Docker 或云沙箱，dataset 要重写吗？参考答案会进 Agent 能看见的目录吗？",
          [
            "不用重写 dataset。换环境改 profiles.yaml：本机、Docker，或 E2B / SSH / Daytona。同一份 task 在不同环境下跑。",
            "参考答案放在 tasks/<id>/evaluation/。Agent 跑的时候不会把它 mount 进去；evaluate 阶段才 upload 到环境里打分。",
          ],
        ],
      ] as const,
    },
    footer: {
      copy: "ZJU-REAL",
    },
  },
  en: {
    metaTitle: "ageval · Configure Agent Eval Once. Run It Anywhere.",
    metaDescription:
      "Switch the agent under test with plugins. Teach the Agent automated evaluation with the CLI and skills. Share datasets, plugins, and agent configs on ageval Hub.",
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
    },
    hero: {
      titleA: "Configure Agent Eval Once,",
      accentA: "Once",
      titleB: "Run It Anywhere.",
      accentB: "Anywhere",
      note: "Swap the agent under test with plugins. Teach the Agent to run evals with the CLI and skills.",
      primary: "Open repo",
      hub: "Go to Hub",
      secondary: "Read the docs",
      startAria: "Get started",
      startTabs: ["Quick start", "From source"],
      copy: "Copy",
      copied: "Copied",
      demo: "Watch demo",
      demoAria:
        "Product demo: configure the eval once, swap the agent under test, and run it end to end",
      demoClose: "Close",
    },
    pactAria: "Three things you can do",
    pact: [
      [
        "SWITCH",
        "Swap the agent under test in one line",
        "No changes to ageval: install a plugin, flip one line of config, and the same dataset runs as-is.",
      ],
      [
        "TEACH",
        "Teach the Agent automated evaluation",
        "Install the CLI and skills so the Agent can design, convert benchmarks, and run evaluations.",
      ],
      [
        "HUB",
        "Share and reuse on Hub",
        "Share or reuse datasets, plugins, and agent configs on ageval Hub, and upload evaluation results.",
      ],
    ] as const,
    problem: {
      index: "// 01",
      name: "The Problem",
      title: [
        "Evaluation still compares models only.",
        "What actually runs is the whole agent.",
      ],
      items: [
        [
          "01 / MODEL",
          "Only the model swaps",
          "Prompts, tools, and flow stay frozen; swap in model B for model A, run once, record a score.",
        ],
        [
          "02 / RUNTIME",
          "The whole agent does the work",
          "What actually executes tasks is the model plus the coding agent runtime around it; the model is one part.",
        ],
        [
          "03 / DRIFT",
          "Different setup, different score",
          "The same model through another coding agent or in another environment scores differently — and costs differently.",
        ],
        [
          "04 / RECORD",
          "A bare model name compares nothing",
          "“Model X scored 80” says little: which agent runtime, which environment? Without that, scores cannot be compared.",
        ],
      ] as const,
      solLabel: "SOLUTION →",
      sol: "ageval pairs environments and agents under test with plugins and pins the combination in lock — making scores comparable",
    },
    position: {
      index: "// 02",
      name: "Positioning",
      title: "Keep the base. Swap the agent with plugins.",
      lead: "The ageval runtime base is a fixed pipeline: lock → environment → run → evaluate → record. Environments and agent runtimes join as plugins; the base stays untouched. Install a plugin, flip one line of config, and the same dataset runs as-is.",
      flow: {
        aria: "Control flow of one run: after the inputs, lock through evidence",
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
        pluginBindNote: "capabilities checked here",
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
          "ageval Core · one run opens one environment; run.py and evaluator.py execute inside it",
        limits: "limits · enforced before the run",
        limitsMeta: "(wall-clock · memory · processes · calls)",
        cleanup: "cleanup · finally, always runs",
        cleanupMeta: "(every exit path · environment and credentials released)",
        legend: "LEGEND",
        legendExt: "external · outside the Core",
        legendCore: "one run · Core boundary",
        legendEvidence: "evidence · focal",
        legendPass: "binds PASS",
        legendPhase: "phase advance",
        legendPlugin: "plugin point",
        notes: [
          [
            "INPUTS",
            "User, dataset, and profiles enter from outside. The dataset defines evaluation tasks; environment and Agent live in profiles.yaml, not in the dataset.",
          ],
          [
            "LOCK",
            "ageval lock resolves the dependency graph (ExtensionGraph) into lock.json, binding plugins to runtime extension points. A capabilities or credentials mismatch fails here — the run never starts.",
          ],
          [
            "ENVIRONMENT",
            "Open one environment and upload the task files. Host, Docker, cloud sandbox, or remote: switching is a profiles change, not a dataset rewrite.",
          ],
          [
            "RUN",
            "run.py runs the task loop inside that environment. The loop, local tools, and Agent invocations live in this file; changing environment or Agent doesn't touch it.",
          ],
          [
            "EVALUATE",
            "Scoring is independent: only evaluator.py can return PASS. Default is a deterministic script; LLM-as-judge and multi-stage evaluation are supported. The scoring container is network-isolated (e.g. network: none); gold uploads only at evaluate.",
          ],
          [
            "RECORD",
            "Score and trajectory land in evidence (lock.json · result.json · trajectory.jsonl). Whatever the outcome, cleanup runs.",
          ],
        ] as const,
      },
    },
    environment: {
      index: "// 03",
      name: "Environment",
      title: "Swap environments. Keep the dataset.",
      lead: "The same task runs on your machine, in a container, in a cloud sandbox, or on a remote host. The environment is one line in profiles.yaml, plugged in as a plugin.",
      items: [
        [
          "ENV · LOCAL",
          "A directory on your machine",
          "Real filesystem, child-process worker.",
          "RUNS TODAY",
          false,
        ],
        [
          "ENV · DOCKER",
          "A local container",
          "Same Dockerfile. Gold arrives only at evaluate.",
          "RUNS TODAY",
          true,
        ],
        [
          "ENV · E2B / SSH / DAYTONA",
          "Cloud sandbox and remote",
          "Orchestration stays local. Install the SDK, add credentials, and it runs.",
          "NEEDS CREDENTIALS",
          false,
        ],
      ] as const,
    },
    eval: {
      index: "// 04",
      name: "Auto",
      title: "Teach the Agent automated evaluation.",
      lead: "Install the CLI and skills so the Agent can design, convert benchmarks, and run evaluations. Load only the skill the task needs.",
      tableAria: "Built-in skills",
      columns: ["Skill", "What it does"],
      skills: [
        [
          "ageval-platform",
          "Start here: who locks, who scores, the red lines.",
        ],
        [
          "ageval-cli",
          "Run lock / run / campaign; inspect and upload results.",
        ],
        [
          "ageval-config-package",
          "Author a dataset: ageval.yaml, task.yaml, profiles.",
        ],
        ["ageval-sdk-harness", "Write run.py: sessions, tools, publish."],
        ["ageval-plugin", "Author a plugin: environment or agent runtime."],
      ] as const,
      steps: [
        ["01 CLI", "uv tool install ageval-cli"],
        ["02 skill", "npx skills add ZJU-REAL/ageval"],
        ["03 run", "The Agent designs, converts, and runs the benchmark."],
      ] as const,
    },
    plugin: {
      index: "// 05",
      name: "Plugin",
      title: "Swap the agent under test in one line.",
      lead: "Swapping the Agent means installing a plugin and flipping one line in profiles — no changes to ageval. Environments work the same way.",
      slots: [
        [
          "ENV",
          "Environment plugins",
          "Host / Docker / cloud sandbox / remote. Missing one? Write a plugin; the base stays put.",
        ],
        [
          "AGENT",
          "Agent-runtime plugins",
          "ACP by default (pi / Codex / Claude Code / OpenCode); nooa / dsh / miniswe take the same plugin path.",
        ],
        [
          "LOCK",
          "Checked at lock",
          "If a plugin's capabilities or credentials don't match, lock fails and the run never starts.",
        ],
      ] as const,
      exampleTag: "EXAMPLE · DSH",
      exampleTitle:
        "DeepSeek's harness came in as a plugin — zero lines changed in ageval.",
      exampleBody:
        "dsh is fundamentally different from ACP and still arrives as a plugin: install the extra, switch executor to dsh in a profile, and run the same task. A missing deepseek_api_key fails at lock — early verification does its job.",
      exampleCode: `# dsh is a plugin, not a fork of ageval
uv tool install 'ageval-cli[dsh]'

# switch executor to dsh; task and dataset untouched
ageval run <dataset> --task <task-id> \\
  --profiles profiles.dsh.yaml   # executor: dsh`,
    },
    cta: {
      title: ["Install the CLI and skills.", "Start running evals."],
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
          "How do I switch the agent under test?",
          [
            "The thing under test is a coding agent (pi, Codex, Claude Code, dsh), not a model name. Neither the base nor the dataset changes: install the plugin, switch it in profiles.yaml, and the same task runs.",
            "Built-in Agent packages bind with --agent pi (no install). Custom Agent packages use ageval agent install, then --agent org/name@version. Environment and bindings live in profiles.yaml, not in the dataset. You do not fork the framework to swap Agent.",
          ],
        ],
        [
          "After I install the CLI, how does my Agent run evals itself?",
          [
            "uv tool install ageval-cli, then npx skills add ZJU-REAL/ageval. The skill tells your coding agent how to call lock / run and how to write a dataset. From there the Agent can design or convert a benchmark and run the eval.",
            "A live coding-agent run still needs a host ACP entry and credentials. ageval lock alone does not. Missing extras or credentials fail the check and the run does not start; the error names the install command.",
          ],
        ],
        [
          "How do I run a dataset from Hub, and how do I share results?",
          [
            "ageval registry list shows datasets you can see. Then ageval run <org>/<name>@<version>. You can also run a local dataset root. Default profiles use environment: docker, so a working Docker engine is required.",
            "Share or reuse datasets, plugins, and Agent configurations on ageval Hub, and upload evaluation results. Others should be able to run what you shared, not only read a score table. Locally, ageval view opens a run under Jobs → Tasks.",
          ],
        ],
        [
          "What files belong in a dataset?",
          [
            "The standard unit of evaluation is a dataset. Put ageval.yaml at the root. Each task lives in tasks/<id>/ with task.yaml, the task loop in run.py, scoring in evaluator.py, and gold. Environment and Agent bindings live in profiles.yaml; do not bake one runtime into the dataset.",
            "The task keeps the loop, roles, and local tools. ageval owns lock, opening the environment, binding the score, and cleanup. The SDK is optional: it does not decide PASS and does not hold host credentials.",
          ],
        ],
        [
          "How do I plug in my own environment or Agent?",
          [
            "Write a plugin for ageval; do not fork it. The plugin declares whether it adds an environment or an agent runtime; after install, switch it in profiles. ACP is the default path; dsh, nooa, and miniswe are the same kind of plugin.",
            "If the plugin's capabilities or credentials do not match, ageval lock fails and the run does not start.",
          ],
        ],
        [
          "If I switch among host, Docker, and a cloud sandbox, do I rewrite the dataset? Can the Agent see gold?",
          [
            "No rewrite. Change the environment in profiles.yaml: host, Docker, or E2B / SSH / Daytona. The same task runs in each.",
            "Keep gold in tasks/<id>/evaluation/. It is not mounted while the Agent runs. It uploads into the environment at evaluate.",
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
