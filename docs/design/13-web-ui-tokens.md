# 13 — Web UI 令牌与不变量

适用面:ageval website(landing + docs)、apps/hub、apps/viewer 三个 web 表面的**风格一致性**。
权威顺序:本文件 → 各端令牌定义文件 → 业务代码(只允许引用语义令牌)。
机检:`python3 scripts/check_design_tokens.py`(CI job `design-tokens`),文档表格与脚本内置值**互相校验**,改值必须两侧同步。

本文件是视觉**宪法**:令牌、字体、圆角、动效曲线、焦点语言、组件角色。
它不描述某条路由上有哪些块、tab 叫什么、控件排在标题左还是右。那些随页面改;改页面不必改本文件。

SPA 实现对照的**常量清单**在 `apps/viewer/DESIGN.md` 文首 YAML(Hub 继承同一份,不要再开一套色板)。改本表必须同步那份 YAML 与 `scripts/check_design_tokens.py` 的 `CANONICAL`。YAML 只列主题常量,不写页面零件。
实现先复用已有组件,再拿本文件核对语言。Hub / Viewer 的**气质与反 slop**在各自 `DESIGN.md`(组件地图也在那里)。landing / docs 例外在 `website/DESIGN.md`。

三端已是同一套产品语言(冷纸 / 冷墨 + IKB + Geist)。不要再「设计一套新身份」。禁止用 shadcn 或 Tailwind 默认皮肤冒充本语言。Hub / Viewer 的落地页 playbook 禁令在 SPA `DESIGN.md` Taste。

## 色彩令牌

品牌强调色仍是 International Klein Blue(IKB)双阶;中性色为冷灰(cool paper / cool ink)。
功能色可以另有**命名令牌**(error / warning / star 金等),不把界面锁成只有墨、纸、蓝。
所有值为 hex,比较大小写不敏感。业务代码仍只写语义令牌名,hex 留在令牌文件。

| 令牌 | 浅色 | 深色 | 用途 | hub/viewer(`--viewer-*`) | docs(`--color-fd-*`) |
| --- | --- | --- | --- | --- | --- |
| canvas | `#F1F3F5` | `#1B1E26` | 页面底色 | `canvas` | `background` |
| canvas-soft | `#E9EBED` | `#20242D` | 卡片 / 悬浮面 / 行 hover | `canvas-soft`、`row-hover` | `muted`(`fd-card` 为本地近似) |
| canvas-soft-2 | `#E1E5ED` | `#2B3041` | 强填充 / 次级底 | `canvas-soft-2` | `secondary` |
| hairline | `#D2D6DF` | `#343948` | 分隔线 / ring | `hairline` | `border` |
| hairline-strong | `#979EB1` | `#5C6274` | 强分隔 / 相位图中阶 | `hairline-strong` | — |
| ink | `#14161F` | `#EEF0F6` | 标题 / 强文字 | `ink` | `foreground` |
| body | `#4A4E5C` | `#9AA0B4` | 正文 | `body` | `muted-foreground` |
| mute | `#5E6376` | `#8A90A4` | 次要文字 / 图标 | `mute` | — |
| link | `#1B54E8` | `#5B7BFF` | 链接 / 主色 / 焦点(IKB) | `link` | `primary`、`ring` |
| link-deep | `#001F73` | `#8AA0FF` | hover(浅色加深 / 深色提亮) | `link-deep` | — |
| error | `#D40000` | `#FF5C5C` | 错误 | `error` | — |
| error-soft | `#F7D4D6` | `#3B1414` | 错误次底(toast 等实色洗底,非透明) | `error-soft` | — |
| warning | `#F5A623` | `#F5A623` | 警告 | `warning` | — |
| warning-soft | `#F4ECDE` | `#3A2E1D` | 警告次底 | `warning-soft` | — |
| link-soft | `#DAE2F6` | `#1E2645` | IKB 次底(成功 / tip toast) | `link-soft` | — |
| star | `#E3B341` | `#F5C84C` | Star 填实金 | `star` | — |
| nav-home | `#2F6E4A` | `#6FBF93` | Hub Home 侧栏 lucide,**仅字形** | `nav-home` | — |
| nav-datasets | `#187A8C` | `#5EC4D4` | Hub Datasets 侧栏 lucide,**仅字形** | `nav-datasets` | — |
| nav-plugins | `#9A5C16` | `#D4924A` | Hub Plugins 侧栏 lucide,**仅字形** | `nav-plugins` | — |
| nav-agents | `#5A4AA8` | `#A898E8` | Hub Agents 侧栏 lucide,**仅字形** | `nav-agents` | — |
| nav-models | `#5A6B38` | `#B4C47A` | Hub Models 侧栏 lucide,**仅字形** | `nav-models` | — |
| nav-inbox | `#B34A3C` | `#E08A7A` | Hub Inbox 侧栏 lucide,**仅字形** | `nav-inbox` | — |
| nav-orgs | `#3E5F7A` | `#8AA8C0` | Hub Organizations 侧栏 lucide,**仅字形** | `nav-orgs` | — |
| code-bg | `#F1F3F5` | `#16181E` | 代码底 | `code-bg` | — |
| accent(landing) | `#5B7BFF`(亮)/ `#002FA7`(深) | 同左 | landing `--accent` / `--accent-deep` | — | — |

landing 的 oklch 系(`oklch(15.4% 0.018 264)` 底等)是本表的 oklch 等值表达,视为同一令牌;
`shell-*` 语法高亮色为 viewer 本地扩展,不跨面。

## 字体

| 角色 | 栈 | 说明 |
| --- | --- | --- |
| sans | `Geist` → `Inter` → `system-ui` → CJK(`Noto Sans SC` / `PingFang SC` / `Microsoft YaHei`) | 全部界面正文;hub/viewer 为系统栈(Geist 命中本地),website 经 next/font 加载 |
| mono | `Geist Mono` → `ui-monospace` → `Menlo` | 代码块 / 命令条 / 数字对齐（`tabular-nums`）；列表与表格里的非数字可读字段用 sans |
| display | `Anton`(wordmark 专用) | 只用于品牌瞬间(hero、logo),**永不**进正文或工具 UI |

字号档只有 YAML 里那几档。`body-sm`(14px / `text-sm`)是操作者要读的字号:控件、表列名、单元格里的非数字正文。`caption`(12px)只给时间戳和 mute 说明,不当列名。禁止再发明第三档可点击小字。PillTabs 的 11px 是已记录的面板内紧凑例外,不是默认。

## 形状与动效

- **圆角**:8 / 10 / 14px 三档(sm 控件、md 字段、lg 卡片/弹层);不发明新档。
  按钮走 8px,不要 `clip-path` 切角。搜索扫描字段是 stadium(`rounded-full`),已记录例外。Landing 主按钮可保留 6px。
- **动效**:默认 `--ease-smooth` `cubic-bezier(0.22, 1, 0.36, 1)`、200ms。
  Hub / Viewer 默认只允许 CSS(无 GSAP / Motion),两条命名例外:
  1. 列表/详情 Loading 用 `ThinkingLogo`(本地 canvas 2D,owl 面标点云绕成工作结;不是 playground iframe)。`prefers-reduced-motion: reduce` 时同一组件停在静态帧,不是第二棵树。
  2. 滑动选中指示用 npm `liquid-gooey`(0 依赖):`Liquid` + `Liquid.Item` **Move**。只包 UnderlineTabs / PillTabs / Hub 侧栏选中行。Blur 3、Item radius 8。填充走 `canvas-soft-2`;侧栏选中走 `canvas`(侧栏底已是 `canvas-soft`)。Hover 走 `canvas-soft` 或 `canvas/50`,不得与选中填充同色。Morph 不进产品。Radix portal 不能加入 Liquid group。`prefers-reduced-motion` 时 thumb 仍测量到位,关掉 goo。Website docs / landing **不**引入该库。
  Landing 允许一次性 hero stagger 与 8px view-timeline 揭示,进场可到 400ms(强调瞬间,须在 `website/DESIGN.md` 写明)。
  Landing 像素标(`OwlPixelMark`)是 landing 例外:canvas 2D 把 owl 面标栅格成方块,hero 一次性 assemble(约 1.4s);指针在 hero 内时方块径向推开;assemble 完成后整标共用一条透明度呼吸(6s,最暗 35%,最亮 80%),并带轻微整体起伏/旋转与边缘 drift。不是磁吸或光标拖尾。`prefers-reduced-motion` 为静止像素标。导航 logo 仍用静态 SVG。
  Landing hero 背景允许 ThreeUI `signal-particles` 点阵场(本地 canvas,不走其 iframe;`speed` 为原 `time += 0.02` 的倍率)。只铺在 hero,`pointer-events: none`,`prefers-reduced-motion` 不挂载。
  第二档命名曲线是已记录例外,不得再发明 playground 弹簧:
  - `--ease-spring` `cubic-bezier(0.34, 1.56, 0.64, 1)`:toast 进场(可到 550ms)、star burst 回弹、按钮松开回弹(可到 500ms)
  - `--ease-glide` `cubic-bezier(0.65, 0, 0.35, 1)`:Liquid thumb 的 CSS `transform`/`width`/`height`(200ms)
  按下 `--t-press` 80ms `ease-out`(Squish Button)。Tooltip 等待 80ms 是意图延迟,不是位移时长。关闭可以快于打开。
  允许的语汇:UnderlineTabs / PillTabs / Hub 侧栏的 Liquid Move thumb、Chip、Toast Overshoot(底中)、Like Burst(仅 plugin/agent star;粒子最多 8 颗,色走 `star` 令牌)、Floating Label(编辑字段)、Squish Button、`data-ageval-pop` 弹层、`data-ageval-menu` 下拉。
  禁止:磁吸、光标拖尾、3D tilt、自定义光标、无限漂浮/旋转/脉冲、滚动钉住、横向 hijack。
  `prefers-reduced-motion: reduce` 必须落到最终态(toast 仍出现但不位移;burst 无粒子;按钮不缩放;liquid thumb 无 goo)。
- **焦点**:分角色,不是「凡是可聚焦就刷 IKB」。IKB 仍是唯一允许的焦点**强调**色。
  - 按钮 / 链接 / 可点击卡:`ring-2 ring-link/70`(landing 3px outline)。
  - **扫描控件**(搜索、过滤、Select 触发器):焦点时描边保持 `hairline`,不换色、不叠 ring。产品语言是栏还在那儿,不是栏亮了。
  - **编辑控件**(要写入的值:Floating Label、名称 / 描述 / 邀请等表单):焦点时 1px `border-link`,不叠 ring。
- **选区**:`::selection` 用 IKB 28% 透明底(三端统一)。
- **深度**:唯一弹层阴影 `--viewer-shadow-pop`(hub/viewer/docs 弹层):浅色 `0 1px 1px rgb(0 0 0 / 3%), 0 4px 8px -2px rgb(0 0 0 / 8%)`;深色同一几何、不透明度 40% / 50%。禁硬投影,不要第二套 liquid 阴影令牌。blob-panel / 卡 / 弹层都是 1px hairline **四面** + 该阴影。
  `backdrop-blur` 至多两档(sticky header 用薄档)。

## 组件语汇(应用层)

角色,不是某页的零件清单。新控件先复用已有实现,不要对着 primitive 默认皮肤另画一条「差不多」的栏。

| 语汇 | 规则 |
| --- | --- |
| 主按钮(SPA Button `default`) | IKB 填充 + `rounded-[8px]` + `font-mono text-[13px] font-semibold` + pop 阴影 + `focus-visible:ring-2 ring-link/70`,hover `link-deep`。`:active` 为 Squish(`scale` 0.96、80ms 按下 / spring 松开) |
| 分段 tab | `UnderlineTabs`:sans `text-sm` + Liquid Move thumb(fill `canvas-soft-2`)。一页一条。不要再画 IKB `border-b-2` 底条。Models plaza 模态过滤是记录例外：搜索栏下第二条 `UnderlineTabs`（All / Text / Image / Video / PDF / Transcription / Speech）。选中/hover 只给图标上色，走现有 `nav-*`（text=`nav-models`，image=`nav-agents`，video=`nav-inbox`，pdf=`nav-orgs`，transcription=`nav-datasets`，speech=`nav-plugins`），标签走 `body`，不要新 hex 族；thumb 仍是 `canvas-soft-2`。行名右侧可叠多枚徽章（纯 text 才出 text 标；PDF 用 `FileText`，色走 `nav-orgs`）。徽章 hover 走共用 tooltip。次底用该色与 canvas 的 `color-mix`，禁止 `/15` 透明度拼色 |
| 紧凑 pill | `PillTabs`:同上,11px。只用于面板内紧凑分段。同页再出现互斥选择用 `Select` |
| 按钮组 | 并列选项收进**一个** hairline 容器(8px 圆角)。选中 `canvas-soft-2` + `ink`,hover `canvas-soft`。字号 `body-sm`。不要 IKB 填充 |
| Chip | 散开的标签用 `Chip`:8px、hairline、选中 `canvas-soft-2`、hover `canvas-soft`。不要 `bg-link/10`。**不要**用 Chip 做模型浏览（`/models` 是 lab 分组表；harness Model 区是 `ModelItem`） |
| 扫描字段 | 搜索是 stadium,焦点描边保持 `hairline`。不要给新搜索叠 `border-link` |
| Toast | 底中 Overshoot 进场;只用于没有本地成功态的写操作。Copy / star 等控件自身已有反馈的不要再 toast。实色 `*-soft` 次底 + `--viewer-shadow-pop`,无描边、无第三方面包。图标走对应功能色,正文走 `body` |
| Select / 下拉 | `Select` / `DropdownMenu` 用 `data-ageval-menu` 进场(220ms smooth, 随 `data-side` 上下),触发器 chevron 旋转 + squish;选项 `data-highlighted` 色过渡,选中勾 `ease-spring` pop。触发器焦点走扫描字段,不是 IKB 描边 |
| Floating Label | 编辑字段:placeholder 在 focus 或有值时抬成 label;焦点描边走 `link` |
| Catalog 卡 | 市场实体(plugin / agent)用 `CatalogCard`:14px、四面 hairline + pop 阴影、hover `canvas-soft`、按下 `squish`(0.96)。描述三行。宽屏三列(`xl:grid-cols-3`)。卡上不画 slot / binding tag。star 在卡上是计数不是写入口;写收藏不是卡上的控件,填实用 `star` 金。first-party overlay 走短 id + lucide builtin 标(`link`),不要冒充 OfficialMark。可比行(dataset / jobs / leaderboard / members / 模型 Performance)用表。模型百科**不是**市场包:按 lab 分组的表,不要复用 `CatalogCard` |
| 表 | hairline 表。表头底 `canvas-soft`，表身 `canvas`。列名 `text-sm` / `mute`。不要 zinc 灰表头，也不要表头表身同色 |
| 页头(PageHead) | h1 + 可选 sub + hairline(无编号 kicker) |
| 相位/耗时图谱 | `--viewer-phase-1..6` 用 ink / body / mute / hairline 冷灰阶。执行段 `--viewer-phase-1` 为 ink 与 mute 的 `color-mix`（约 55% ink），不用实心 ink，也不用 IKB。IKB 留给链接 / 焦点 / 主 CTA。禁 zinc 等外部灰阶 |
| 弹层(tooltip/select/dropdown/dialog) | hairline 边框 + `--viewer-shadow-pop`。Portal 到 `document.body` 或 `OverlayRoot`;不要挂在已有 `transform` 的 pop 里(`position:fixed` 会跟错) |
| 危险确认 | Modal：较大标题 + mute 说明后果 + Cancel / Confirm 两枚按钮 |
| Hub 壳 | 左右分区:整列侧栏 `canvas-soft` + 右 hairline;顶栏与主列 `canvas`(不透明,无 blur)。Logo 行 `border-b`,GitHub / Documentation 脚 `border-t`。选中侧栏行 Liquid fill 走 `canvas`;hover `canvas/50`。宽屏(`xl`)正文居中 `w-[80%]`;顶栏仍铺满主列 |
| Viewer 壳 | 无侧栏。顶栏 `canvas-soft` + `border-b`;主列 `canvas`。宽屏(`xl`)正文居中 `w-[80%]`;顶栏仍铺满 |
| Docs 壳 | 文档侧栏 `muted`(canvas-soft) + 右 hairline;阅读列 `background`(canvas)。不引入 liquid-gooey |
| 侧栏字形色 | Hub 目的地 lucide 只涂对应 `nav-*`。标签走正文 sans + `body-sm`(`text-sm`),不是 mono。未选:该令牌与 `mute` 的 `color-mix`,标签 `font-normal`,描边 2;选中:令牌本体 + 行底 `canvas`,标签 `font-semibold`,描边 2.5。字重与描边用默认 200ms `--ease-smooth` 过渡;不要 fill。`prefers-reduced-motion: reduce` 时瞬时到位。焦点环仍是 IKB。不要拿字形色铺页面或涂正文。Viewer 无 Hub 侧栏;功能图标继续 `mute` |
| Loading | 与 empty **分开**。正在拉取时:`ThinkingLogo` + 一行「Loading …」,不要骨架栅格,也不要用 empty 的虚线井。画布停在屏外/隐藏页时不转 |
| Empty | 在剩余主列里**双轴居中**。栈:大图标(owl 或该目的地 lucide,静态,无 thinking) → 一行标题 → **要么**一行说明 **要么**一个控件,不要一段里两者都有。无 thinking 动效 |

## 不变量(十条)

1. 色值只允许出现在令牌定义文件与品牌资产(owl 组件);业务代码只写语义令牌名。
2. IKB 仍是链接 / 焦点 / 主 CTA / 品牌位,禁大面积底色(landing ink-banner 例外)。error / warning / star 等功能色走各自令牌,不挤进 IKB,也不要求界面只有墨纸蓝。
3. 中性色三层语义:`canvas*` 是面、`hairline` 是线、`ink/body/mute` 是字;`mute` 永不做正文。
4. `Anton` 只做 wordmark;正文一律 sans 栈 + CJK 回退;中文标题粗细上限 semibold。
5. 主 CTA 用 8px 圆角 + IKB 填充;表格 / 输入 / 普通控件用同一套圆角三档。搜索是 stadium。不要切角 `clip-path`。
6. 焦点可见性不妥协,但扫描与编辑不是同一条。按钮 / 链接 / 卡用 2px IKB 环(landing 3px outline);编辑字段用 1px IKB 描边;搜索与过滤保持 hairline 描边,不换焦点色。
7. 选区、hover、active 的色彩表达一律引用令牌,不自调 hex / opacity 组合。
8. 动效默认 `--ease-smooth` 200ms。`--ease-spring` / `--ease-glide`、按下 80ms、toast 550ms、landing hero/章节揭示 400ms、Hub/Viewer `ThinkingLogo` canvas、Hub/Viewer `liquid-gooey` Move 是已记录的例外。其它曲线、时长或运动库先改本文件。
9. 图标三用途:产品品牌用 owl 系列(`owl-flat.tsx` / `OwlIcon`);功能用 lucide;plugin/agent 实体标默认 GitHub 头像(`uploaded_by`),**official / builtin 默认仓内 `zju-real`**(不在打开列表时 fetch GitHub)。可改闭包彩色标或另一个 GitHub login。闭包 SVG/PNG 在 `apps/hub/src/lib/brand-marks/assets/`,彩色,不把第三方 logo 组件库当运行时依赖。模型百科的 **lab** 标是 pin 里 vendored 的 lab SVG,缺则字母标;不进 plugin/agent 闭包、不装 `@lobehub/icons`。Lab ≠ Hub org。文件树仍用 `material-icon-theme`(既有例外)。
10. 深度感只用 `--viewer-shadow-pop`;blur 分档封顶,不为单个组件发明新档或第二套阴影令牌。

## 品牌资产入口

| 资产 | 位置 | 用途 |
| --- | --- | --- |
| `OwlFlatMark` / `Icon` / `Peek` / `Plate` / `Lockup` / `Watermark` | `website/src/components/owl-flat.tsx` | landing 水印、导航、docs lockup、备用底板。字形是面标(Figma cubic),不是全身立姿 |
| `OwlIcon`(面标) | `apps/hub/src/components/owl-icon.tsx`、`apps/viewer/src/components/owl-icon.tsx` | 两 SPA 导航品牌位。与 website `OwlFlatIcon` 同一 path |
| `ThinkingLogo` | `apps/hub/src/components/thinking-logo.tsx`、`apps/viewer/src/components/thinking-logo.tsx` | Hub / Viewer 拉取中的工作态点云(owl 面标烘焙点,canvas 2D)。empty 与导航 logo 仍用静态 SVG |
| favicon | `website/src/app/favicon.ico` + `website/public/favicon.svg`；`apps/{hub,viewer}/public/favicon.{ico,svg}` | 黑方底板 + 白面标。只用 ico（浏览器默认 `/favicon.ico`）和 svg，不另备 png |
| 实体/机制标 | `apps/hub/src/lib/brand-marks/` | plugin / agent 卡片与详情、Leaderboard。默认 uploader GitHub 头像;official / builtin 用闭包 `zju-real`。闭包为彩色真实标。ink 标固定白底，paper 标固定黑底 |
| 模型 lab 标 | 随 pin 提交的 lab SVG | `/models` 与 harness 模型目录。缺 SVG 字母标。不进 `brand-marks/`。Lab ≠ Hub org |

`owl-flat` 与 `owl-icon` 内的 IKB、墨、纸、奶油 hex 是品牌资产允许值,纳入机检 allowlist。预设彩色图标 hex 只许出现在 `brand-marks/assets/`(svg/png),不进 ts/tsx。模型 lab SVG hex 只许出现在 pin 资产目录,同样不进 ts/tsx。
`OwlFlatPlate` 四色:`paper` / `cream`(深底浅标)、`ink`(浅底深标)、`klein`(IKB `#1B54E8` 底 + 白标)。导航图标走 `currentColor`。
