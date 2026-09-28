# ageval Website Design System

**令牌与跨面不变量**以 [`docs/design/13-web-ui-tokens.md`](../docs/design/13-web-ui-tokens.md) 为准。本文件只写 website 的 landing / docs 例外（Anton 字标、hero stagger、像素标、ThreeUI），不另开一套色板，也不写 Hub / Viewer 页面清单。

本文档是 `website/` 的视觉与交互规范。

**色板策略：** 全站统一为 PPT / landing 的克莱因蓝（IKB `#002FA7`，暗底提亮 `#5B7BFF`）+ 冷墨中性色。文档站与 landing 共用同一套色相，不再使用暖棕 canvas。

## 设计方向

### 产品气质

- 面向 benchmark 作者、研究工程师和 Agent infrastructure 团队。
- **Landing** 跟整站同一套亮暗色：浅色是冷纸，深色是冷墨海报。字标 Anton，正文 Geist / Noto Sans SC，按钮圆角。导航里语言切换右侧是亮暗色按钮。
- **文档阅读层** 使用同一套克莱因蓝与冷墨中性色；壳与 SPA 一样左右分区（侧栏 `canvas-soft`、阅读列 `canvas`）。标题与正文都走 Geist / Noto Sans SC，不再用衬线。不引入 `liquid-gooey`。
- 装饰服从信息，不使用生成插画、拟真场景图或无语义的发光背景。

### 设计参数

| 参数 | 值 | 含义 |
| --- | --- | --- |
| Design variance | 5/10 | 允许非对称构图，保持工程秩序 |
| Motion intensity | 5/10 | Hero 进场 + ThreeUI signal-particles 背景 + 像素标 assemble/hover 推散/透明度呼吸 + 短距章节揭示 + FAQ 开合；SPA 允许 toast / squish / pill glide / star burst |
| Visual density | 4/10 | 技术信息清晰，保留足够留白 |

## 颜色

### 核心色板

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `canvas` | `#f1f3f5` | `#1b1e26` | 页面底（冷纸 / 冷墨） |
| `canvas-soft` | `#e9ebed` | `#20242d` | 次级面、表头 |
| `ink` | `#14161f` | `#eef0f6` | 主文字 |
| `body` | `#4a4e5c` | `#9aa0b4` | 正文与说明 |
| `hairline` | `#d2d6df` | 冷白 12% | 1px 边界 |
| `accent` | `#002FA7` | `#5B7BFF` | 链接、焦点、主按钮（克莱因蓝） |
| `accent-deep` | `#001f73` | `#8aa0ff` | hover / active |
| `dark`（landing 底） | `#1b1e26` | `#16181e` | landing 深色面 |

参考：IKB / Klein Blue 主题（#002FA7 / #5B7BFF）；viewer / hub 的冷灰 ink 仅作对比，不把 viewer link 蓝搬进本站。

### 使用规则

- 一个视口内最多出现一个主 CTA；主 CTA 用 accent 实底，链接与路径强调用同一套克莱因蓝。
- 中性色保持冷相，不要回暖棕。
- 文档卡片 / 弹层用 1px hairline 四面 + 与 SPA 相同的 `--viewer-shadow-pop` 几何。不要第二套阴影。Landing 深色面继续用 inset hairline，不搬 SPA pop。
- 深色技术区可用极轻的蓝色径向光带作路径提示，不使用多色 AI 渐变。

## 字体

### 字体职责

- Landing 字标使用 `Anton`。文档标题与正文使用 `Geist Sans`，中文由 `Noto Sans SC` 补全。
- 技术标签、按钮、状态和字段名使用 `Geist Mono`。
- 文档导航、sidebar、TOC、搜索和交互控件使用 `Geist Sans`。
- 标题使用 sentence case；mono 标签可以 uppercase。
- 正文不能使用 monospace。不使用衬线作为文档标题。

### 字号层级

| Token | Desktop | Mobile | 用途 |
| --- | --- | --- | --- |
| Display XXL | `64px/1.08` | `42px/1.08` | 首屏标题 |
| Display XL | `40px/1.16` | `32px/1.18` | Section 标题 |
| Display LG | `28px/1.2` | `24px/1.24` | 卡片或演示标题 |
| Body LG | `18px/1.5` | `17px/1.5` | Lead paragraph |
| Body MD | `16px/1.55` | `16px/1.55` | 正文 |
| Mono label | `11px/1.4` | `11px/1.4` | eyebrow、字段与状态 |

首屏标题桌面最多两行，正文最多四行。Anton 只用于 landing 字标，不能扩散到文档正文和交互控件。

### 文档阅读层

- Fumadocs 的页面标题和正文 H1-H4 使用 Geist / Noto Sans SC，字重 700；颜色跟正文 ink（浅色近黑、深色近白），不用克莱因蓝。
- 文档正文、导航、sidebar、TOC、搜索、面包屑和分页保持 Geist Sans。
- code、pre、kbd、字段名和配置示例使用 Geist Mono。
- Fumadocs semantic token 与 landing 共用冷墨半透明原则，light / dark 均禁止纯黑、纯白或完全不透明的近黑/近白大色块。
- 搜索、popover 和菜单使用接近实色的稳定 surface，确保叠加在正文上时仍有清晰边界和可读性。

## 布局

### 页面节奏

- 内容最大宽度为 `1280px`。
- 桌面 gutter 为 `32px`，移动端为 `16px`。
- Section 垂直间距为 `80px`，移动端降为 `56px`。
- 首屏使用左右分栏：价值主张在左，真实产品演示在右。
- 深色和浅色 section 交替；颜色带负责分区，不用大阴影制造层级。

### 圆角与边界

- 文档阅读层跟 SPA：`8 / 10 / 14px`。搜索是 stadium。
- Landing 主按钮 `6px` 是 marketing 例外；大型演示容器最多 `8px`。
- 只允许圆形 icon button 与搜索使用全圆角。
- 按钮、卡片、节点和表格统一使用 1px hairline。

## 产品演示

### 架构路径

- Positioning 用 Core 高阶图（`CoreFlow`）代替「ageval 管 / dataset 管」对照：输入 → lock → environment → run → evaluate → record。
- 默认停在第一列（INPUTS）。不自动播放。hover 整列热区高亮该列；离开后停在最后一次高亮的列。
- 当前列的说明用注释字样写在嵌入图块下方（`// PHASE` + 一句），不是图上 tooltip。
- 高亮色走 landing `--accent`（`#5B7BFF`）。
- 节点文案中英随 locale；阶段条（INPUTS / LOCK / …）保持英文。
- 移动端横向滚动看完整节点，不压缩技术标签。

### 其他视觉内容

- 优先使用配置片段、运行状态、事件表、审计工件和结果摘要。
- 不使用 AI 生成图片作为产品能力解释。
- 不使用装饰性悬浮节点或视差背景。章节允许 8px 的一次性 view-timeline 揭示，禁止 pin / scrub / 横向劫持。

## 动效

缓动默认 `cubic-bezier(0.22, 1, 0.36, 1)`（`--ease`）。文档站 chrome 默认 `200ms`（`--t`）。
SPA 第二档曲线见 `docs/design/13`（`--ease-spring` / `--ease-glide`）。Landing 不引入 spring 过冲。

### 允许

- `160-240ms` 的颜色、边框和背景过渡。
- Landing hero 一次性 stagger（40ms 间隔，进场 400ms；强调瞬间，不是 chrome 默认）。
- Landing 章节 8px `view-timeline` 揭示（`@supports` 回退为静止）。浏览器不支持时不得把内容停在 `opacity: 0`。
- FAQ 用 `<details>` + `grid-template-rows` 开合，不用 hover 展开。
- Landing 卡片 hover 最多 `translateY(-1px)`。
- Positioning `CoreFlow`：默认第一列高亮；hover 整列热区切换列，离开后保持最后一列。列切换 200ms `--ease`。不自动播放。`prefers-reduced-motion` 关掉列切换过渡。
- 按钮 Squish：`:active` `scale(0.97)`、80ms 按下；松开用 `--ease` 回弹。不要 6px 实体底边。
- Landing 像素标（`OwlPixelMark`，canvas 2D）：hero 一次性从散点 assemble（约 1.4s）；指针在 hero 内时，邻近方块径向推开。assemble 完成后整标一起做透明度呼吸（6s 一周期，最暗 35%，最亮 80%），并带轻微整体起伏。导航 logo 用静态 SVG。无磁吸、无光标拖尾。`prefers-reduced-motion` 为静止像素标。
- Landing hero 背景允许 ThreeUI `signal-particles` 点阵场（本地 canvas；`speed` 是原步进倍率，`1` 为库默认）。只铺 hero、不接收指针、`prefers-reduced-motion` 不挂载。

### 禁止

- 视差滚动、滚动钉住、横向 hijack、GSAP / Motion 进 landing 或 docs。
- 无限漂浮、无限旋转和无限脉冲。
- 磁吸、光标拖尾、3D tilt、自定义光标。
- 超过 12px 的 scroll travel。
- 多段 sticky 叙事；全站只保留导航栏 sticky。

所有动效必须支持 `prefers-reduced-motion: reduce`，此模式下直接显示最终状态、关掉 animation 与 hover 位移。

## 组件规范

### 按钮

- 高度最少 `44px`，圆角 `6px`（landing 例外；文档 chrome 走 8px）。
- Label 使用 Geist Mono，保持短且不换行。
- hover 改变背景、边框或文字色。Landing 卡片允许 1px 上移；CTA hover 不位移，`:active` 允许 Squish 缩放。
- focus-visible 使用 3px 半透明 accent ring。

### 卡片与数据区

- Docs 卡片用冷纸 canvas、四面 hairline、pop 阴影。
- Landing 深色面继续用 inset hairline，不搬 SPA pop。
- 技术字段采用 `label / value` 结构，label 使用 mono uppercase。
- 状态颜色必须同时配合文字，不能只依赖颜色传递信息。

### 链接与 CTA

- Hero 允许一个 primary CTA 和一个 secondary CTA。
- 相同意图在页面中保持同一文案。
- CTA hover 不移动；active 只改变填充或 inset border。

## 响应式与无障碍

- 断点使用 `768px` 和 `1024px` 作为主要布局转换点。
- 所有交互目标最少 `44 × 44px`。
- 桌面双栏在 `< 1024px` 时改为单栏。
- 图表、tab 和 inspector 必须支持键盘操作和可见 focus ring。
- 正文、按钮和状态文字至少满足 WCAG AA 对比度。
- 页面在 JavaScript 失效时仍需保留标题、正文和文档入口。

## 发布前检查

- 首屏标题、说明和 CTA 在初始视口内完整可见。
- 页面没有视差、漂浮节点和 hover 位移。
- 每个 section 都有明确的信息目标，布局类型不机械重复。
- 架构路径在桌面和移动端均无文字裁切，节点信息可键盘访问。
- 中英文文案长度均通过真实视口验证。
- `prefers-reduced-motion`、light theme 和 dark theme 均通过检查。
