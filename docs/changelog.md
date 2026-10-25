# 变更记录

按提出的顺序记录每一轮需求带来的改动。

## 0.1 初版

- 五阶段流程：Markdown 解析 → 手写排版 → 逐字渲染 → 稿纸合成 → 拍照后处理，完全本地、离线。
- 放弃机器学习手写生成（SDT、DiffBrush 效果太假），改用预置手写风格字体加逐字轻微形变。
- Markdown 对应：粗体双横线、斜体单横线、标题左对齐大字、无序列表跨行大括号、禁用表格。

## 第二轮（十项要求）

1. 字形扭曲大幅减小（`warp_amp` 默认 0.008）。
2. 纸边缘既不笔直也不过度扭曲：每条边各自随机弯一点（`edge_bow_*`），某个角翘起（`corner_lift`），随机折角（`dog_ear_prob`），随机污渍（`stain_*`）。
3. 自定义纸张模板：`.toml` + 图片，`handnote template` 自动检测行距、首行位置和左边线。
4. 字体可替换：主字体、补缺字体、标题、代码、标点、西文各自可指定；自动搭配龙藏体和文楷。
5. 代码块只留左竖线，字用正文颜色。
6. 下划线、大括号、竖线等手绘线条带倾斜、弯曲、首末超出（`line_*`）。
7. 大括号尖角在纵向 2/8 处（`brace_tip`）。
8. 引用 = 整段缩进 + 首行缩进处手画三角。
9. 所有效果可选可调，数值 0 即关闭。
10. 标题间距参数（`heading_gap_before/after`）。

## 本地模型与规则

- 新增 `AGENTS.md`：给 opencode 和本地模型的笔记写作规则（角色与 Markdown 对应、禁用项、正反例、通过检查的完整示例、自查清单）。
- 新增 `handnote lint`：按行号给出"必须修改 / 建议修改"和改法，有必须修改时退出码为 1，`--strict` 把建议也当错误。

## 字距与配置文件

- 汉字字距可调（`text.letter_spacing`）。
- 默认配置文件自动读取：`$HANDNOTE_CONFIG` → `./handnote.toml` → 用户目录；`handnote init-config` 生成；`--no-config`；`handnote config --path`；配置错误信息带文件名。
- `examples/config.example.toml`：全部选项，每项带说明和候选值（取代 `config.full.toml`）；`docs/options.md` 增加"候选 / 期望值"一列。

## 拍照效果扩展

- **手机倾斜**：整个画面（纸和桌面）做透视，`tilt_min/tilt_max`、`tilt_direction`（默认上端向远处）、`tilt_direction_jitter`、`focal_length`；倾斜后重新居中。
- **手机阴影方位**：`photo.shadow_position`，八个方位或随机。
- **纸后一沓纸**：`stack_count`、`stack_offset`、`stack_rotation`、`stack_direction`，默认关闭。

## 按笔画边界排字

- `text.spacing_mode = "ink"`（默认）：按字形笔画的实际左右边界排版，而不是字体声明的字宽；`ink_gap`、`ink_min_width`。`advance` 保留旧排法。下划线随之对齐笔画边缘。

## 一键写笔记与输出结构

- 新增 `handnote write`（也可用 `handnote-write`）：问主题和多个子标题 → 本地 llama 服务生成 → lint 并让模型修改 → 渲染。连接参数在配置文件的新 `[llm]` 段，提示词内置。
- 输出结构改为 `<输出目录>/<笔记文件名>/<页码>.jpg`，同一份笔记的所有图片在同一个子文件夹。
- 文档：新增 `docs/guide.md`（功能说明）和本文件，README 与 `docs/options.md` 同步更新。

## 上下标

- 模型常用 `^` 表示乘方，原来会把 `^` 原样写出来。现在 `x^2`、`10^-3`、`e^x`、`x^{n+1}`、`x^(n+1)` 画成上标，`v_0`、`a_n`、`x_{i+1}` 画成下标（缩小、抬高或降低，选项 `script_marks`、`script_scale`、`sup_rise`、`sub_drop`）；代码里、前后有空格的 ^、`snake_case`、被转义的 `\^` 不处理。写作规则、内置提示词和 lint 提示同步说明。

## 课件 PDF 变笔记

- 新增 `handnote slides`（也可用 `handnote-slides`）：指定一个课件 PDF，或一个放着多个 PDF 的目录（`-r` 含子目录，`--skip-existing` 续跑），提取文字 → 内置提示词交给本地模型写成课堂笔记 → lint 并让模型修改 → 渲染，笔记和图片以 PDF 文件名命名。
- 文字清理（页码、重复页眉页脚）、长课件分段提炼要点（`llm.chunk_chars`）、批量时单个失败不中断并汇总、扫描件明确提示。
- 新增依赖 `pypdf`；`write` 与 `slides` 共用的"生成—检查—修改"流程抽成 `writer.generate`。
- README、`docs/guide.md`、`docs/options.md`、示例配置同步更新。
