# 功能说明

README 讲怎么上手，这里按功能把每一项讲清楚：它做什么、怎么开关、对应哪个选项。全部选项的默认值和候选值见 [options.md](options.md)，每次改动的来龙去脉见 [changelog.md](changelog.md)。

约定：**数值型效果设为 0 就是关闭，概率设为 0 是从不发生**；配置里拼错的键会直接报错。

## 1. 命令一览

| 命令 | 作用 |
|---|---|
| `handnote notes.md -o out/` | 渲染（`render` 可省略），图片存到 `out/notes/1.jpg、2.jpg…` |
| `handnote write` / `handnote-write` | 询问主题和子标题，用本地模型写笔记、检查、渲染 |
| `handnote slides 课件.pdf` / `handnote-slides` | 提取课件 PDF 的文字，用本地模型整理成笔记并渲染；给目录则对其中所有 PDF 依次处理 |
| `handnote lint notes.md` | 检查笔记里哪些写法渲染出来不自然，有"必须修改"时退出码为 1 |
| `handnote fonts` / `preview` | 下载开源字体 / 用每款字体渲染同一段样张并排对比 |
| `handnote template 纸.jpg` | 从一张纸的照片或扫描件生成纸张模板 |
| `handnote config` | 打印当前全部选项；`--annotated` 带说明和候选值；`--path` 看读的是哪个配置文件 |
| `handnote init-config` | 写出完整的、带候选值的配置文件，之后自动读取 |

## 2. 输出位置

同一份笔记的所有页放在同一个子文件夹：`<输出目录>/<笔记文件名>/<页码>.jpg`。例如 `handnote notes/牛顿.md -o out/` 得到 `out/牛顿/1.jpg`、`out/牛顿/2.jpg`。`--keep-stages` 额外保存 `1.flat.png`（只有稿纸和字）和 `1.ink.png`（墨迹层）。从标准输入读时名字是 `note`。`-o page.png` 这类写成图片文件名的用法保留：第一页写到该文件，其余页写在旁边的 `page-2.png`。

## 3. Markdown 到手写

| Markdown | 手写效果 | 相关选项 |
|---|---|---|
| `# … ######` | 左对齐大字 | `heading_scales`、`heading_gap_before/after`、`heading_font` |
| `**粗体**` / `*斜体*` | 双横线 / 单横线 | `line_wobble`、`line_tilt_deg`、`line_overshoot`、`line_width` |
| `- 列表` | 跨行大括号，尖角在高度 2/8 处 | `brace_tip`、`list_indent`、`list_marker` |
| 列表前"短标签：" | 标签挪到括号尖角左侧 | `label_max_chars` |
| `1. 列表` | 手写序号 | |
| `> 引用` | 整段缩进，首行缩进处手画三角 | `quote_indent`、`quote_marker` |
| 代码 | 正文颜色，代码块只有左竖线 | `code_font`、`code_rule`、`code_pen`、`code_scale` |
| 表格 | 禁用，转成括号列表 | `table_mode` |

## 4. 字体与排版

- 字体可替换：`fonts`（主字体和补缺字体）、`heading_font`、`code_font`、`punct_font`、`latin_font`，值可以是路径或文件名片段。
- **字距**：`text.spacing_mode`。
  - `ink`（默认）：按每个字**笔画的实际左右边界**排，相邻两字的笔画边界之间留 `ink_gap`（em，可为负）；`ink_min_width` 保证窄字和标点至少占一定宽度。窄字不再占满一格，宽字也不会被挤。下划线到最后一个字的笔画右边缘为止。
  - `advance`：按字体声明的字宽排，再加 `letter_spacing`。
  - 西文、数字、代码块始终按字体字宽。
- 字形手写变化：`pos_jitter`、`baseline_wave`、`line_slope_deg`、`rotate_deg`、`scale_jitter`、`shear_jitter`、`warp_amp`、`warp_sigma`、`thickness_jitter`、`pressure_var`、`line_gain_var`，全部可设 0。

## 5. 稿纸

`paper.kind`：`ruled` 横线纸、`blank` 白纸、`grid` 方格纸；`paper.template` 或 `--paper` 用自定义模板（模板 `.toml` 或一张纸张图片，`handnote template` 可自动检测行距和起点）；`stain_count`、`stain_strength` 等控制随机污渍；`grain`、`tint_var`、`line_var` 控制纸面质感。

## 6. 拍照效果

渲染完的平整稿纸再经过下面这些步骤，每一项都能单独关：

1. **纸的形状**：`bend` 整页缓慢起伏；`edge_bow_min/max` 每条边各自随机弯一点（不笔直也不过度扭曲）；`corner_lift` 某个角朝镜头或背离镜头翘起；`dog_ear_prob` 随机折角。
2. **纸后的一沓纸**（默认关）：`stack_count` 张，`stack_offset` 错开距离，`stack_rotation` 各自旋转，`stack_direction` 朝哪个方位露出，每张给下面一张投影。
3. **桌面与摆放**：`pad`、`desk_color`、`desk_texture`、`paper_shadow`；`perspective` 和 `rotation` 只让纸摆得不正。
4. **手机倾斜**：整个画面（纸和桌面一起）做透视。`tilt_min/tilt_max`（度，max 设 0 关闭）每张照片随机取角度；`tilt_direction` 决定哪一侧离镜头更远：默认 `top`，即手机上端微微仰起、纸的上端变窄；也可 `bottom`、`left`、`right`、`random` 或角度数字；`tilt_direction_jitter` 方向随机偏转；`focal_length` 焦距，越小透视越夸张。倾斜后纸仍会被重新居中、缩放回原取景范围。
5. **光影**：`shadow` 形状（`phone`、`window`、`random`、`none`）；`shadow_position` 手机阴影落在画面的哪个方位（`top-left`、`top`、`top-right`、`left`、`right`、`bottom-left`、`bottom`、`bottom-right` 或 `random`）；`shadow_strength`、`light_gradient`、`vignette`。
6. **相机**：`color_cast`、`tone_var`、`blur`、`sharpen`、`noise`、`jpeg_quality`。

## 7. 配置文件

不加 `-c` 时按顺序找，先找到的生效：环境变量 `HANDNOTE_CONFIG`（设为 `none` 不读任何文件）→ 当前目录 `handnote.toml` → `~/.config/handnote/config.toml`（Windows 为 `%APPDATA%\handnote\config.toml`）。`handnote init-config` 写出包含全部选项、每项带说明和候选值的文件（`examples/config.example.toml` 就是它的内容）；`--commented` 写成全部注释掉的版本；`--no-config` 这次不读；`--set 段.键=值` 在其上再覆盖单项。配置文件里的相对字体路径、纸张图片，在配置文件旁边找得到就按其所在目录解释。

## 8. 本地模型写笔记

三种用法，共用同一套规则：

- **`handnote write`**（自己运行的前置工具）：问主题、子标题、其他要求 → 调用 `[llm]` 里指定的 OpenAI 兼容服务（如 llama.cpp 的 `llama-server`）流式生成 → `lint` 检查，不通过就把检查结果发回让模型修改（`llm.fix_rounds` 轮）→ 存 `notes/<主题>.md` → 渲染到 `out/<主题>/`。提示词内置，host、port（或 `base_url`）、模型名、采样参数、`thinking` 开关等在 `[llm]`。
- **`handnote slides`**（课件变笔记）：见下一节。
- **opencode / 其他 agent**：根目录 `AGENTS.md` 是写作规则和示例，agent 自己写文件、运行 `handnote lint`、渲染。

`lint` 的检查项：表格、图片、HTML、LaTeX、emoji 等字体里没有的字、整篇被代码块包住、YAML 头、多个一级标题（以上为"必须修改"）；套话、段落或列表项过长、嵌套过深、单项列表、加粗过多、标题跳级、空小节、引用过多、页数过多或过少等（"建议修改"）。每条都带行号和改法。

## 9. 课件 PDF 变笔记

`handnote slides <PDF 或目录>`：

1. 用 pypdf 提取每页文字，清理页码、"第 N 页"和在大多数页重复出现的页眉页脚，去掉汉字之间的版面空格。
2. 文字不超过 `llm.chunk_chars` 就整份发给模型；超过则先按页分段（单页过长再切），每段让模型提炼要点，再用要点写笔记；要点仍太长就再提炼一轮。
3. 内置提示词 = 笔记写作规则 + 课件专用要求（按层次重组而不是逐页照抄、只用课件已有内容、不写页眉页脚/致谢页）。可用 `--note` 追加要求。
4. 与 `write` 相同：`lint` 检查，不通过就把检查结果发回让模型改（`llm.fix_rounds` 轮）。
5. 存 `notes/<PDF 名>.md`（重名加 `-2`），渲染到 `out/<PDF 名>/<页码>.jpg`。

目录模式：按文件名自然顺序处理 `*.pdf`（`-r` 含子目录，`--skip-existing` 跳过已有笔记的），某个文件失败不影响其他，最后汇总；有失败时退出码为 1。扫描件（提取不到文字）会提示先做 OCR，工具本身不识别图片里的字。`[llm]` 里 `chunk_chars` 按模型上下文大小调。
