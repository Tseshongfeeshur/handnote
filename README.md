# handnote

把 Markdown 笔记变成"手写笔记的手机照片"。完全本地、离线运行，不用 GPU，不依赖任何在线服务。

文档：[功能说明](docs/guide.md) · [全部选项](docs/options.md) · [变更记录](docs/changelog.md)

## 工作流

```
notes.md
  │ 1 解析    markdown-it-py；表格降级成"表头：内容"的括号列表，永不画表格线
  │ 2 排版    按手写习惯排：标题左对齐变大字、无序列表用跨行大括号（尖角在 2/8 处）、
  │           粗体双横线、斜体单横线、引用 = 整段缩进 + 首行手画三角、代码块只有左竖线；
  │           中文避头尾；按行距网格分页
  │ 3 渲染    用手写字体逐字渲染（每个字单独做轻微形变）；下划线、大括号、竖线、三角
  │           都是带倾斜、弯曲、首末超出的手绘笔画
  │ 4 稿纸    叠到稿纸上：横线纸 / 白纸 / 方格纸 / 你自己的纸张模板；可加随机污渍
  │ 5 拍照    纸的边缘弯曲、翘角、折角、透视、桌面、投影、光照、暗角、偏色、模糊、噪点、JPEG
  ▼
out/notes/1.jpg  2.jpg ...      每份笔记一个子文件夹，用笔记文件名命名，图片用页码命名
```

"手写感"来自手写风格字体加逐字轻微形变，不是机器学习生成。字形骨架来自字体，所以**字体决定了像不像**，见下面"字体"一节。

## 安装与使用

```bash
pip install -e .                 # Python 3.9+
handnote fonts long-cang lxgw-wenkai   # 下载字体（OFL 许可）到 ./fonts
handnote notes.md -o out/        # 整套流程，按页输出 jpg：out/notes/1.jpg、2.jpg ……
handnote write                   # 不想自己写笔记：问主题和子标题，交给本地模型写，再渲染
handnote slides 课件.pdf          # 有课件：提取 PDF 文字，交给本地模型整理成笔记，再渲染（也可给一个放满 PDF 的目录）
```

```bash
handnote notes.md -o out/ --paper blank --ink blue-black --seed 7
handnote notes.md -o page.png                  # 只写第一页到这个文件，其余页写在同目录 page-2.png ...
handnote notes.md --no-photo --keep-stages     # 只出平整稿纸图，并保存墨迹层，方便调参
handnote notes.md -c examples/config.toml      # 指定配置文件（不加 -c 时自动读取，见下）
handnote notes.md --set photo.noise=0 --set text.warp_amp=0.02   # 命令行改任何选项（可重复）
cat notes.md | handnote - -o out/
```

代码里用：

```python
from handnote import Config, run_pipeline
cfg = Config.load("examples/config.toml")
for page in run_pipeline(open("notes.md", encoding="utf-8").read(), cfg, seed=1):
    print(page.index, page.photo.shape)   # uint8 RGB
```

## 字体（可替换）

```bash
handnote fonts --list           # 可下载的字体
handnote fonts --local          # 本机已有的字体
handnote preview                # 用每款字体渲染同一段样张，并排对比，输出 fonts-preview.png
handnote notes.md --font 我的字体.ttf --font LXGWWenKai-Regular.ttf   # 第一个为主字体，后面的补缺字
handnote notes.md --heading-font mashanzheng --code-font lxgw          # 标题、代码单独换字体
handnote notes.md --punct-font lxgw --latin-font lxgw                  # 标点、字母数字单独换字体
```

- `--font`、`--heading-font` 等既可以是文件路径，也可以是字体目录里文件名的一部分。
- 没指定字体时自动用 `./fonts` 里的：龙藏体为主字体（最像真手写），霞鹜文楷补缺字，并让文楷负责标点和英文数字，因为龙藏体的标点和字母偏小。
- 输入里有字体没有的字，会在命令行列出并跳过，不会画出方框。
- **想更像真人**，最有效的是换成更像你自己字迹的字体：用手写字体制作工具（例如手迹造字、FontForge）把自己的字写成 .ttf，丢进 `fonts/` 即可。我没有测过这些工具的输出，字体需包含常用汉字，缺的字会用后面的字体补。
- 字体文件各自有许可证，仓库不提交字体；分发成品图或字体时请保留各自的 OFL 声明。

## 纸张模板（可自定义）

内置三种：`ruled` 横线纸、`blank` 白纸、`grid` 方格纸（`--paper grid`）。

自定义有两种办法：

**1. 直接给一张纸的图片**（拍的、扫的、画的都行）：

```bash
handnote template my-paper.jpg -o my-paper.toml    # 自动检测横线的行距、首行位置和左侧竖线，写出模板
handnote notes.md --paper my-paper.toml --no-photo --keep-stages   # 看文字是否落在线上
```

检测时会把页面缩放到让行距刚好是整数像素，所以模板里的 `width/height` 可能和默认 A4 略有不同。检测不准（例如纸上没有规整的线）时，手改模板里的数字即可。

**2. 手写模板文件**（`examples/templates/legal-pad.toml` 是完整例子，配图 `legal-pad.jpg` 由同目录脚本生成）：

```toml
image = "my-paper.jpg"      # 相对模板文件；整张纸已经带线，所以 kind 用 blank

[page]
width = 1654
height = 2339
margin_top = 124            # 文字基线落在 margin_top + n × pitch，对准纸上的线
margin_left = 236
margin_bottom = 130
margin_right = 100
pitch = 58

[paper]
kind = "blank"
stain_count = 2             # 模板里也可以改任何 [paper] 选项
```

模板只能含 `image`、`[page]`、`[paper]`。配置文件里写 `paper.template = "路径"`，或命令行 `--paper 路径`，也可以直接 `--paper 某张图片.jpg`（此时用默认页面几何）。

## Markdown 到手写的对应关系

| Markdown | 手写效果 |
|---|---|
| `#` … `######` | 左对齐大字；上下空行数由 `heading_gap_before` / `heading_gap_after` 设置 |
| `**粗体**` | 双横线 |
| `*斜体*` | 单横线 |
| `~~删除~~` | 中间一横 |
| `- 无序列表` | 一个跨所有行的大括号，尖角在高度的 2/8 处（`brace_tip`）；嵌套列表嵌套括号；单项列表退化成圆点 |
| 列表前一句"短标签：" | 标签挪到大括号尖角左侧 |
| `1. 有序列表` | 手写序号，不画括号 |
| `> 引用` | 整段缩进（`quote_indent`），首行缩进处手画一个三角（`quote_marker`），笔画首末有随机超出 |
| 行内 `代码`、代码块 | 正文颜色（`code_pen` 可改成第二支笔）；代码块只有左侧一条手画竖线（`code_rule`），不拆页 |
| `---` | 手画横线 |
| 表格 | 禁用：按行转成"表头：内容；表头：内容"的括号列表，或用 `table_mode = "skip"` 丢弃 |
| `x^2`、`10^-3`、`x^{n+1}`、`v_0`、`a_n` | 画成上标 / 下标（`script_marks` 可关；代码里和前后有空格的 `^` 不处理） |
| 链接、图片、HTML | 链接保留文字，图片写成 `[alt]`，HTML 忽略 |

## 配置文件（自动读取）

不加 `-c` 时，handnote 按顺序找下面三处，**先找到的生效**：

1. 环境变量 `HANDNOTE_CONFIG` 指向的文件（设为 `none` 则不读任何配置文件）
2. 当前目录的 `handnote.toml`
3. 用户目录：`~/.config/handnote/config.toml`（Windows 为 `%APPDATA%\handnote\config.toml`）

```bash
handnote init-config                 # 在用户目录写出完整配置文件（全部选项，附说明和候选值）
handnote init-config -o handnote.toml   # 或者只给当前项目用
handnote init-config --commented     # 全部注释掉，只取消注释想改的项，以后默认值升级也能跟上
handnote config --path               # 看现在读的是哪个文件
handnote notes.md --no-config        # 这次不读任何配置
handnote notes.md --set text.ink_gap=0.12         # 在配置文件之上再覆盖单项
```

优先级：`--set` > `-c` 文件（或自动找到的文件）> 内置默认值。`examples/config.example.toml` 就是 `init-config` 写出的内容：每项上方是说明和候选值/建议范围。配置里的相对字体路径、纸张图片，如果在配置文件旁边找得到，就按配置文件所在目录解释。

## 选项

每个效果都能单独调或关：**数值设 0 就是关闭，概率设 0 是从不发生**。完整列表（含默认值和说明）在 [docs/options.md](docs/options.md)，由源码自动生成；`handnote config` 打印当前全部取值，`examples/config.example.toml` 是带说明和候选值的完整配置文件。

常用的几个：

| 想要 | 怎么设 |
|---|---|
| 字与字的间距 | 默认 `text.spacing_mode = "ink"`：按字形笔画的实际左右边界排，相邻两字边界之间留 `text.ink_gap`（em，默认 0.08，可为负），`ink_min_width` 防止窄字和标点挤在一起。设 `"advance"` 则按字体声明的字宽排，再加 `letter_spacing`。西文、数字、代码块仍按字体字宽 |
| 字形更工整 / 更潦草 | `text.warp_amp`、`text.rotate_deg`、`text.pos_jitter`（0 为完全不抖） |
| 手绘线条更直 / 更歪 | `text.line_wobble`、`text.line_tilt_deg`、`text.line_overshoot`（0 为尺子般笔直） |
| 纸边缘 | `photo.edge_bow_min/max`（每条边的弯曲幅度，max 设 0 则笔直）、`photo.bend` |
| 翘角 / 折角 / 污渍 | `photo.corner_lift`、`photo.dog_ear_prob`、`paper.stain_count`（设 0 关闭） |
| 光影 | `photo.shadow`（`none` 关闭）、`photo.shadow_position`（手机阴影在哪个方位）、`photo.light_gradient`、`photo.vignette`、`photo.paper_shadow` |
| 纸后一沓纸 | `photo.stack_count`（张数，0 关闭）、`stack_offset`、`stack_rotation`、`stack_direction`（往哪个方位露出边缘） |
| 手机倾斜 | `photo.tilt_min/tilt_max`（角度范围，度；max 设 0 关闭）、`photo.tilt_direction`（`top` 上端离镜头更远 / `bottom` / `left` / `right` / `random` / 角度数字）、`photo.tilt_direction_jitter`、`photo.focal_length`。整个画面包括桌面一起做透视 |
| 相机 | `photo.blur`、`photo.noise`、`photo.color_cast`、`photo.perspective` |

## 一键写笔记：`handnote write`

不想自己写 Markdown 时，用本地模型（llama.cpp 的 `llama-server`，或任何 OpenAI 兼容服务）直接生成：

```bash
llama-server -m 你的模型.gguf --port 8080     # 先把模型服务开起来
handnote write                                # 或 handnote-write
```

它会依次问你：笔记主题；要包含的子标题（每行一个，想补要点就写成"标题：要点"，空行结束，一个都不写则由模型安排）；其他要求（可留空）。然后：

1. 把主题和子标题连同内置的写作规则和示例一起发给模型，流式显示生成过程；
2. 用 `lint` 检查，不通过就把检查结果发回给模型让它改（最多 `llm.fix_rounds` 轮）；
3. 笔记存成 `notes/<主题>.md`（重名则加 `-2`），再渲染成 `out/<主题>/1.jpg、2.jpg ……`。

模型的地址、端口、名字都在配置文件的 `[llm]` 里（见"配置文件"），提示词内置在程序里：

```toml
[llm]
host = "127.0.0.1"          # 或者直接写完整地址：base_url = "http://192.168.1.5:8080/v1"
port = 8080
model = "qwen3.6-35b-a3b"
thinking = false            # Qwen3 一类模型：关闭思考更快
fix_rounds = 3
```

不想被提问时全部用参数给：`handnote write --topic 牛顿运动定律 --section "第一定律：惯性" --section 第二定律 --note ""`。`--no-render` 只写笔记不出图，`--name` 指定文件名，另外 `--paper`、`--ink`、`--seed`、`--no-photo`、`--format`、`-o` 与渲染命令相同。连不上模型时会提示检查 llama-server 和 `[llm]` 配置。

## 课件 PDF 变笔记：`handnote slides`

把老师的课件直接整理成课堂笔记并出图，和 `handnote write` 用同一个本地模型（`[llm]` 配置）和同一套检查、修改流程：

```bash
handnote slides 第三讲.pdf                 # 一个课件 -> notes/第三讲.md -> out/第三讲/1.jpg ...
handnote slides ./课件/                    # 目录下所有 PDF，按文件名自然顺序（2 在 10 之前）依次处理
handnote slides ./课件/ -r --skip-existing # 连子目录一起；已有笔记的跳过，方便中断后接着跑
handnote slides 第三讲.pdf --note "偏重公式推导" --no-render   # 加要求；只写笔记不出图
```

- 提取每页文字后会清理：去掉页码、"第 N 页"，以及在大多数页都重复出现的页眉页脚（课程名、章名等），合并字间多余空格。
- 课件文字不多时一次发给模型；文字超过 `llm.chunk_chars`（默认 9000 字）时，先分段让模型提炼要点，再用要点写笔记，所以很长的课件也不会撑爆本地模型的上下文。
- 提示词（内置）要求：不逐页照抄、按知识层次重新组织、只用课件里有的内容、不写页眉页脚和致谢页，笔记题目取课件主题。
- 笔记文件和图片以 PDF 文件名命名；重名的笔记加 `-2`，不会覆盖你改过的笔记。
- 处理目录时某个 PDF 失败（打不开、没有文字、模型出错）不会中断其余文件，最后汇总列出失败的；有失败时退出码为 1。
- 扫描件或纯图片课件提取不到文字，会明确提示，本工具不做文字识别（先用 OCR 工具转成带文字的 PDF）。
- 参数：`-r` 递归子目录、`--skip-existing`、`--note`、`--no-render`、`-o`，以及 `--paper`、`--ink`、`--seed`、`--no-photo`、`--format`。也可以直接运行 `handnote-slides`。

## 让本地模型写笔记（opencode）

根目录的 `AGENTS.md` 就是给模型的写作规则：怎么用 Markdown 表示标题、要点、术语、易错提醒，什么不能写，以及一份通过检查的完整示例。opencode 会自动读取项目根目录的 `AGENTS.md`，所以：

```bash
cd handnote && opencode        # 然后直接说：写一份"进程调度"的课堂笔记
```

模型的流程是：写 `notes/xxx.md` → `handnote lint` 检查并按提示改 → `handnote` 渲染。`lint` 会用"必须修改 / 建议修改"和行号告诉它哪里不对（表格、图片、LaTeX、套话、段落过长、嵌套过深、一级标题重复……），退出码 1 表示有必须修改的问题。

- 在 opencode 里执行 `/init` 会就地改写已有的 `AGENTS.md`；用之前先备份，或事后检查改动。
- 想让规则全局生效，可复制到 `~/.config/opencode/AGENTS.md`，或在 `opencode.json` 的 `instructions` 里引用。
- 小模型容易照抄示例内容；规则里已经提醒"只学格式"，仍照抄时换一份别的主题示例即可。

## 目录

```
handnote/    parser.py layout.py render.py paper.py photo.py   五个阶段
             pipeline.py 串联   config.py 全部选项   fonts.py 字体   templates.py 纸张模板检测
             lint.py 笔记检查   writer.py 调本地模型写笔记   slides.py 课件 PDF 变笔记   cli.py
docs/        guide.md 功能说明   options.md 全部选项（自动生成）   changelog.md 变更记录
AGENTS.md    给 opencode / 本地模型的笔记写作规则
examples/    sample.md  config.toml（精简）  config.example.toml（全部选项+候选值）  agents-example.md  templates/
tools/       gen_options.py    重新生成 docs/options.md
tests/       pytest -q
```

## 许可

代码 MIT。字体各自遵循其许可证。
