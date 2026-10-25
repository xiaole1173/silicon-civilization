# DESIGN.md — 多智能体会话基座 · 视觉规范

> Material-inspired：借用 Material 3 的**原理与参数**（间距网格、色彩角色、层级、动效节奏），
> 不使用 Google 的 logo、产品图标、Product Sans 字体，也不复刻其具体页面。
> 所有页面只允许引用 `web/theme.css` 中的令牌与组件类。

## 1. 定位

一个面向研究者/开发者的**多智能体对局观察台**。信息密度高、长时间盯屏、需要快速判断
"谁在做什么、结果如何"。因此：**克制、中性、层级清晰**，强调色只用于主动作，其余靠
空间与描边建立结构。

## 2. 色彩

品牌色：**偏黑灰**（可整体替换，见 `--brand`）。

| 角色 | Light | Dark | 用途 |
|---|---|---|---|
| `--brand` | `#2b2f36` | `#e8eaef` | 主动作按钮、选中态、关键强调 |
| `--on-brand` | `#ffffff` | `#14161a` | 品牌色上的文字 |
| `--bg` | `#f5f6f8` | `#101216` | 页面底色 |
| `--surface` | `#ffffff` | `#171a1f` | 卡片/面板 |
| `--surface-2/3` | `#fafbfc` / `#f0f2f5` | `#1b1f25` / `#22262d` | 次级表面、hover |
| `--on-surface` | `#171b23` | `#e9ebf0` | 主文字 |
| `--on-surface-mid` | `#5b636f` | `#a6adba` | 次级文字 |
| `--on-surface-low` | `#8b929d` | `#767e8b` | 提示、占位 |
| `--outline` | `#e4e7ec` | `#2a2f37` | 分隔线、卡片描边 |
| `--outline-strong` | `#d4d8e0` | `#3a4048` | 输入框、按钮描边 |

语义色：`--ok / --warn / --err / --info` 各带 `-weak` 浅底版本，只用于**状态**，不做装饰。

## 3. 字体与字号

字体栈：`"Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Segoe UI", system-ui`
（不使用 Product Sans / Google Sans。）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--fs-12` | 12px | 标签、辅助信息、表格头 |
| `--fs-13` | 13px | 正文/列表主字号 |
| `--fs-14` | 14px | 默认 body |
| `--fs-16` | 16px | 页面标题 |
| `--fs-20` | 20px | 区块标题 |
| `--fs-28` | 28px | 空状态/大标题（少用） |

行高：正文 1.65，标题 1.35。数字统一 `font-variant-numeric: tabular-nums`。

## 4. 间距与形状

- 间距只用 4 的倍数：`--sp-1..--sp-8` = 4 / 8 / 12 / 16 / 20 / 24 / 32。
- 圆角：小控件 8、卡片 12、弹层 16、胶囊 999。
- 阴影只用三层：`--e0` 无、`--e1` 1px 轻投影、`--e2` 浮层。**禁止重投影**。

## 5. 动效

- 进入 `--t-base`（220ms），交互反馈 `--t-fast`（140ms），
  缓动统一 `cubic-bezier(.2,.8,.2,1)`。
- 只动 `background / border-color / opacity / transform`，不动布局属性。

## 6. 组件规格

| 组件 | 规格 |
|---|---|
| 顶栏 `header` | 高 56，左右 20，底部 1px `--outline`，标题 16/650 |
| 按钮 `button` | 高 32，横向 14，圆角 8，描边 `--outline-strong`；主按钮用 `--brand` 实底 |
| 输入 `input/select` | 高 32，圆角 8，focus 时 `--ring` 3px 半透明环 |
| 卡片 `.card` | 圆角 12，描边 1，`--e1`；内部 padding 16 |
| 标签 `.chip/.role/.tag` | 胶囊，12px，浅底；`.role` 用 `--brand-weak` |
| 投票条 `.vchip` | 高 20，圆角 6，左侧座位色块 16 |
| 空状态 `.empty` | 12px，`--on-surface-low`，居中 |

## 7. 主题切换（预留）

- 通过 `<html data-theme="light|dark">` 切换，令牌自动换肤；
- 用户选择存 `localStorage["theme"]`；
- 顶栏右侧放一个 34px 圆按钮（`web/theme.js` 自动注入）；
- 未来加"多品牌主题"时，只需覆盖 `--brand` 一组变量，无需改任何组件。

## 8. 页面清单与迁移要求

| 页面 | 职责 | 迁移要求 |
|---|---|---|
| `web/chat.html` | 会话观察台（核心） | 三栏固定、回合卡、裁判条、投票条全部走令牌 |
| `web/models.html` | 模型管理 | 表单/卡片/标签统一 |
| `web/werewolf.html` | 旧版狼人杀观察台（保留） | 至少做到底色/字体/卡片一致 |
| `viz/index.html` | 对局回放 | 卡片/指标条统一 |

## 9. 禁止清单

- 不用 emoji 或 Unicode 图形当图标（一律 SVG 或纯文字）；
- 不用紫粉渐变、彩色大色块、装饰性阴影；
- 不引入第三方 UI 框架/CDN（保持零依赖）；
- 同一页面内不出现两种主色。
