"""Configuration dataclasses, TOML loading and overrides.

Every tunable number in the pipeline lives here, so a config file (or repeated
``--set section.key=value`` on the command line) can change the look without
touching code.  Unknown keys are rejected, which catches typos early.

Convention: every effect that is a number is switched off by setting it to 0
(or "none" for the enumerations), and every effect that is a count or a
probability is switched off by 0 as well.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Pen colours (sRGB, 0-255).  "main" and "accent" pens pick from this table.
INK_COLORS = {
    "black": (36, 36, 42),
    "blue": (28, 52, 140),
    "blue-black": (24, 32, 70),
    "red": (178, 38, 38),
    "green": (30, 100, 60),
}

BUILTIN_PAPERS = ("ruled", "blank", "grid")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


@dataclass
class PageConfig:
    """Page geometry in pixels.  Defaults: A4 at 200 dpi.

    Text baselines sit on the grid ``margin_top + n * pitch``; ruled paper draws
    its lines on the same grid.  For a paper image that already has printed
    lines, set ``pitch`` and ``margin_top`` so the grid falls on them
    (``handnote template`` can detect both).
    """

    width: int = 1654  # 页宽
    height: int = 2339  # 页高
    margin_top: int = 150  # 上边距；也决定横线网格的起点
    margin_bottom: int = 130  # 下边距
    margin_left: int = 170  # 左边距
    margin_right: int = 100  # 右边距
    pitch: int = 64  # 行距，文字基线对齐到这个网格

    @property
    def lines_per_page(self) -> int:
        return max(1, (self.height - self.margin_top - self.margin_bottom) // self.pitch)


@dataclass
class TextConfig:
    # --- 字体（都可以替换） ------------------------------------------------
    fonts: list = field(default_factory=list)  # 正文字体文件，第一个为主字体，后面的只补缺字；留空则自动在 fonts/ 里找
    heading_font: str = ""  # 标题单独用的字体，留空则同正文
    code_font: str = ""  # 行内代码和代码块单独用的字体，留空则同正文
    punct_font: str = ""  # 全角标点单独用的字体；留空则同正文（自动选字体时，龙藏体的标点会借用文楷）
    latin_font: str = ""  # 英文字母、数字、半角符号单独用的字体；留空则同正文（自动选字体时同样借用文楷）
    font_dir: str = ""  # 额外的字体目录（fonts 为空时在这里找）

    # --- 字号与间距 -------------------------------------------------------
    size_ratio: float = 0.74  # 正文字号 / 行距
    heading_scales: list = field(default_factory=lambda: [1.6, 1.32, 1.16, 1.06, 1.0, 1.0])  # 一到六级标题相对正文的字号倍数
    heading_gap_before: list = field(default_factory=lambda: [1, 1, 1, 0, 0, 0])  # 一到六级标题上方的空行数
    heading_gap_after: list = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])  # 一到六级标题下方的空行数
    spacing_mode: str = "ink"  # 汉字怎么排：ink 按字形笔画的实际左右边界排（字与字之间留 ink_gap），advance 按字体声明的字宽排（再加 letter_spacing）
    ink_gap: float = 0.08  # ink 模式下相邻两字笔画边界之间的空隙，单位 em；可为负
    ink_min_width: float = 0.30  # ink 模式下一个字（含标点）至少占的宽度，单位 em，避免窄字和标点挤成一团
    letter_spacing: float = 0.03  # advance 模式下汉字的额外字距，单位 em
    paragraph_indent: float = 0.0  # 段首缩进，单位 em
    list_indent: float = 1.15  # 大括号到列表文字的距离，单位 em
    list_marker: str = "none"  # 大括号列表项前的额外标记：none 或 dot
    label_max_chars: int = 8  # 列表前“短标签：”最长多少字时才挪到括号尖端左侧
    softbreak: str = "auto"  # 段内换行：auto 像 Markdown 一样合并，newline 保留
    table_mode: str = "list"  # 表格：list 按行转成括号列表，skip 直接丢弃（表格线永远不画）

    script_marks: bool = True  # 把 x^2、10^-3、x^{n+1} 画成上标，v_0、a_n、x_{i+1} 画成下标；关闭则原样显示 ^ 和 _
    script_scale: float = 0.62  # 上下标的字号相对正文
    sup_rise: float = 0.38  # 上标抬高多少，单位 em
    sub_drop: float = 0.16  # 下标降低多少，单位 em

    # --- 引用与代码 -------------------------------------------------------
    quote_indent: float = 2.0  # 引用段整体缩进，单位 em
    quote_marker: str = "triangle"  # 首行缩进处的手绘标记：triangle 空心三角，filled 实心三角，none 不画
    code_scale: float = 0.88  # 代码字号相对正文
    code_rule: bool = True  # 代码块左侧的手绘竖线
    code_pen: str = "main"  # 代码用哪支笔：main 正文颜色，accent 第二支笔

    # --- 字形手写变化（每项设 0 即关闭） -----------------------------------
    pos_jitter: float = 0.02  # 每个字的位置抖动，单位 em
    baseline_wave: float = 0.025  # 基线缓慢起伏，单位 em
    line_slope_deg: float = 0.25  # 每行随机倾斜角度
    rotate_deg: float = 1.2  # 单字旋转上限（度）
    scale_jitter: float = 0.03  # 单字缩放抖动
    shear_jitter: float = 0.03  # 单字斜切抖动
    warp_amp: float = 0.008  # 单字笔画弹性扭曲幅度，单位 em
    warp_sigma: float = 0.10  # 上述扭曲的平滑程度，单位 em
    thickness_jitter: float = 0.06  # 笔画粗细变化（也用于手绘线条的粗细变化）
    pressure_var: float = 0.12  # 字内墨色深浅变化
    line_gain_var: float = 0.08  # 行与行、笔画与笔画之间的墨色深浅变化

    # --- 手绘线条：下划线、大括号、竖线、横线、三角 --------------------------
    line_wobble: float = 0.05  # 线条的弯曲抖动，单位 em；0 为尺子般笔直
    line_tilt_deg: float = 0.8  # 直线的随机倾斜角度
    line_overshoot: float = 0.3  # 笔画首末随机多出的长度上限，单位 em
    line_width: float = 0.047  # 笔宽相对字号
    brace_tip: float = 0.25  # 大括号尖角距顶部的高度比例，0.25 即 2/8

    # --- 笔 ---------------------------------------------------------------
    ink: str = "black"  # 主笔颜色：black / blue / blue-black / red / green
    accent: str = "red"  # 第二支笔颜色


@dataclass
class PaperConfig:
    kind: str = "ruled"  # 稿纸类型：ruled 横线纸，blank 白纸，grid 方格纸
    template: str = ""  # 纸张模板：builtin 名、模板 .toml 或纸张图片，见 README
    image: str = ""  # 直接指定纸张图片（模板会填这一项）
    image_fit: str = "cover"  # 图片适配页面：cover 裁剪铺满，stretch 拉伸
    color: tuple = (247, 245, 238)  # 纸色
    line_color: tuple = (150, 182, 208)  # 印刷横线颜色
    line_width: int = 2  # 印刷横线粗细（像素）
    line_var: float = 0.10  # 印刷横线深浅不均；0 为完全均匀
    margin_line: bool = False  # 左侧红色竖线
    grain: float = 0.012  # 纸张颗粒强度；0 关闭
    tint_var: float = 0.012  # 纸色缓慢不均；0 关闭
    stain_count: int = 2  # 随机污渍最多几处；0 关闭
    stain_strength: float = 0.16  # 污渍深浅
    stain_min: float = 0.015  # 污渍直径下限，占页宽比例
    stain_max: float = 0.05  # 污渍直径上限，占页宽比例
    stain_color: tuple = (150, 112, 62)  # 污渍颜色


@dataclass
class PhotoConfig:
    enabled: bool = True  # false 则只输出平整的稿纸图，不做任何拍照效果
    pad: float = 0.07  # 纸四周露出的桌面宽度，占长边比例
    perspective: float = 0.025  # 纸摆得不正：纸的四角随机位移，占页宽比例（只动纸，不动桌面）；0 关闭
    rotation: float = 1.2  # 纸在画面内的随机旋转（度，标准差）；0 关闭
    # 手机倾斜：整个画面（纸和桌面一起）做透视，像手机上端微微朝远处仰起时拍的
    tilt_min: float = 3.0  # 手机倾斜角度下限（度）
    tilt_max: float = 8.0  # 倾斜角度上限（度），每张照片在两者之间随机取值；0 关闭倾斜
    tilt_direction: str = "top"  # 哪一侧离镜头更远（画面里变窄）：top 纸的上端（手机上端仰起）/ bottom / left / right / random，也可写角度数字，0=上端，顺时针
    tilt_direction_jitter: float = 10.0  # 倾斜方向在上述方向附近随机偏转的最大角度（度）；0 为方向固定
    focal_length: float = 0.8  # 镜头焦距，相对画面对角线；越小透视越夸张，越大越接近正视
    # 纸的形状
    bend: float = 0.0025  # 整页平缓起伏，占短边比例；0 关闭
    edge_bow_min: float = 0.004  # 每条边各自随机弯曲一点（方向随机），幅度下限，占短边比例
    edge_bow_max: float = 0.010  # 幅度上限；设 0 则边缘笔直
    corner_lift: float = 0.018  # 某个角朝镜头或背离镜头翘起的幅度，占页宽比例；0 关闭
    corner_lift_prob: float = 0.8  # 出现翘角的概率
    dog_ear_prob: float = 0.3  # 出现折角的概率；0 关闭
    dog_ear_min: float = 0.03  # 折角直角边长下限，占页宽比例
    dog_ear_max: float = 0.06  # 折角直角边长上限
    # 纸后面的一沓纸
    stack_count: int = 0  # 这张纸后面垫着几张纸，错落露出边缘；0 关闭
    stack_offset: float = 0.012  # 每张纸比上一张多错开的最大距离，占页宽比例
    stack_rotation: float = 1.0  # 每张纸各自随机转的角度上限（度）
    stack_direction: str = "random"  # 纸堆朝哪个方位露出：random / top-left / top / top-right / left / right / bottom-left / bottom / bottom-right
    # 桌面与光
    paper_shadow: float = 0.55  # 纸落在桌面上的阴影深浅；0 关闭
    desk_color: tuple = (92, 74, 62)  # 桌面颜色
    desk_texture: float = 1.0  # 桌面木纹强度；0 为纯色
    shadow: str = "random"  # 投影形状：random / phone 手机 / window 窗框 / none 关闭
    shadow_position: str = "random"  # 手机阴影在画面的哪个方位：random / top-left / top / top-right / left / right / bottom-left / bottom / bottom-right；指定后 shadow=random 时固定用手机阴影，window 不受影响
    shadow_strength: float = 0.30  # 投影深浅
    light_gradient: float = 0.16  # 整体明暗渐变；0 关闭
    vignette: float = 0.20  # 暗角；0 关闭
    # 相机
    color_cast: float = 0.015  # 白平衡偏色；0 关闭
    tone_var: float = 0.05  # 随机伽马漂移；0 关闭
    blur: float = 0.7  # 镜头模糊（像素）；0 关闭
    sharpen: float = 0.35  # 模糊后的锐化；0 关闭
    noise: float = 3.0  # 传感器噪点（0-255 刻度）；0 关闭
    jpeg_quality: int = 86  # 保存 JPEG 的质量


@dataclass
class LlmConfig:
    """The language model that `handnote write` asks for the note (a llama.cpp `llama-server`, or anything else
    that speaks the OpenAI chat API).  The prompts are built into the program."""

    host: str = "127.0.0.1"  # 模型服务地址（llama-server 的 --host）
    port: int = 8080  # 模型服务端口（llama-server 的 --port）
    base_url: str = ""  # 完整的 OpenAI 兼容地址，如 http://192.168.1.5:8080/v1；留空则用 host 和 port
    model: str = "qwen3.6-35b-a3b"  # 请求里写的模型名（llama-server 单模型时基本忽略，多模型/代理时用来选模型）
    api_key: str = ""  # 服务要求鉴权时填；本机一般留空
    temperature: float = 0.6  # 采样温度，越低越稳
    top_p: float = 0.95  # 核采样
    max_tokens: int = 4096  # 一次最多生成多少 token
    thinking: bool = False  # 是否让模型先思考再写（Qwen3 一类；关闭更快，笔记不需要长推理）
    timeout: int = 900  # 单次请求最长等待秒数（本地大模型首个字可能要等很久）
    fix_rounds: int = 3  # 检查不通过时最多让模型改几轮；0 为不改
    notes_dir: str = "notes"  # 生成的笔记 .md 存放目录
    chunk_chars: int = 9000  # 课件文字超过这么多字时，先分段让模型提炼要点，再用要点写笔记（按模型上下文大小调）


SECTIONS = ("page", "text", "paper", "photo", "llm")


@dataclass
class Config:
    page: PageConfig = field(default_factory=PageConfig)
    text: TextConfig = field(default_factory=TextConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    photo: PhotoConfig = field(default_factory=PhotoConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    seed: Optional[int] = None

    # ------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "Config":
        """Defaults, then the file at ``path`` (if any) on top."""
        cfg = cls()
        if path:
            path = Path(path)
            try:
                with open(path, "rb") as fh:
                    data = tomllib.load(fh)
            except tomllib.TOMLDecodeError as e:
                raise ValueError(f"{path}: not valid TOML: {e}") from None
            tpl = (data.get("paper") or {}).get("template")
            if tpl:  # template first, so the file's own [paper]/[page] keys win over it
                cfg.apply_paper(tpl, base=path.parent)
            try:
                _merge(cfg, data)
            except ValueError as e:
                raise ValueError(f"{path}: {e}") from None
            cfg._anchor_paths(path.parent)
        return cfg

    @classmethod
    def load_default(cls) -> "tuple[Config, Optional[Path]]":
        """The config file found by :func:`find_config` on top of the defaults, and which file that was."""
        src = find_config()
        return cls.load(src), src

    def _anchor_paths(self, base: Path) -> None:
        """Relative font/image paths in a config file mean "next to that file", when such a file exists."""
        def fix(v: str) -> str:
            if v and not Path(v).is_absolute() and (base / v).exists():
                return str((base / v).resolve())
            return v

        t = self.text
        t.fonts = [fix(f) for f in t.fonts]
        for name in ("heading_font", "code_font", "punct_font", "latin_font", "font_dir"):
            setattr(t, name, fix(getattr(t, name)))
        self.paper.image = fix(self.paper.image)

    def apply(self, data: dict) -> "Config":
        _merge(self, data)
        return self

    def set(self, assignment: str) -> "Config":
        """Apply ``section.key=value`` (value in TOML syntax, bare words are strings)."""
        key, sep, raw = assignment.partition("=")
        if not sep:
            raise ValueError(f"--set expects key=value, got {assignment!r}")
        key, raw = key.strip(), raw.strip()
        try:
            val = tomllib.loads(f"v = {raw}")["v"]
        except Exception:
            val = raw
        if key == "paper.template":
            self.apply_paper(str(val))
            return self
        parts = key.split(".")
        if len(parts) not in (1, 2):
            raise ValueError(f"unknown config key: {key}")
        data: dict = {parts[0]: val} if len(parts) == 1 else {parts[0]: {parts[1]: val}}
        _merge(self, data)
        return self

    # ------------------------------------------------------------ paper templates
    def apply_paper(self, spec: str, base: "Path | None" = None) -> "Config":
        """Select the paper: a builtin kind, a paper image, or a template .toml."""
        spec = str(spec)
        if spec in BUILTIN_PAPERS:
            self.paper.kind, self.paper.image = spec, ""
            return self
        p = _find(spec, base)
        if p.suffix.lower() == ".toml":
            with open(p, "rb") as fh:
                data = tomllib.load(fh)
            image = data.pop("image", "")
            for sec in data:
                if sec not in ("page", "paper"):
                    raise ValueError(f"{p}: a paper template may only contain `image`, [page] and [paper], got {sec!r}")
            if image:
                ip = (p.parent / image).expanduser()
                if not ip.is_file():
                    raise FileNotFoundError(f"paper image not found: {ip}")
                data.setdefault("paper", {})["image"] = str(ip.resolve())
                data["paper"].setdefault("kind", "blank")
            _merge(self, data)
        elif p.suffix.lower() in IMAGE_EXTS:
            self.paper.image = str(p.resolve())
            self.paper.kind = "blank"
        else:
            raise ValueError(f"paper must be ruled|blank|grid, a .toml template or an image, got {spec!r}")
        return self

    # ------------------------------------------------------------ misc
    def pen_colors(self) -> dict:
        def get(name: str):
            if name not in INK_COLORS:
                raise ValueError(f"unknown ink colour {name!r}; choose from {sorted(INK_COLORS)}")
            return INK_COLORS[name]

        if self.text.code_pen not in ("main", "accent"):
            raise ValueError("text.code_pen must be 'main' or 'accent'")
        return {"main": get(self.text.ink), "accent": get(self.text.accent)}

    def to_toml(self, annotated: bool = False, commented: bool = False) -> str:
        """All options with their current values, as a TOML document.

        ``annotated`` puts the description and the candidate values above every option;
        ``commented`` additionally comments every option out (so only what you uncomment is overridden).
        """
        docs = field_docs() if annotated else {}
        mark = "# " if commented else ""
        out = [ANNOTATED_HEADER] if annotated else []
        if annotated:
            out += ["# 随机种子：固定后同样的输入得到同样的照片；不设置则每次都不一样", f"# 候选：{HINTS['seed']}"]
        if self.seed is not None:
            out.append(f"{mark}seed = {self.seed}")
        else:
            out.append("# seed = 42" if annotated else "# seed = 42   # unset: every run looks different")
        for sec in SECTIONS:
            out.append("")
            if annotated:
                title, blurb = SECTION_TITLES[sec]
                out += ["# " + "-" * 70, f"# {title}", f"# {blurb}", "# " + "-" * 70]
            out.append(f"[{sec}]")
            for f in fields(getattr(self, sec)):
                if annotated:
                    out.append("")
                    out.append(f"# {docs.get((sec, f.name), '')}")
                    out.append(f"# 候选：{HINTS[f'{sec}.{f.name}']}")
                out.append(f"{mark}{f.name} = {_toml_value(getattr(getattr(self, sec), f.name))}")
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the persistent config file

def user_config_path() -> Path:
    """Where `handnote init-config` puts the per-user config: %APPDATA%\\handnote on Windows, else ~/.config/handnote."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "handnote" / "config.toml"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "handnote" / "config.toml"


def config_candidates() -> "list[tuple[str, Path]]":
    """Places looked at, in order, when no ``-c`` is given: label and path."""
    out = []
    env = os.environ.get("HANDNOTE_CONFIG", "")
    if env and env.lower() not in ("none", "off", "0"):
        out.append(("环境变量 HANDNOTE_CONFIG", Path(env).expanduser()))
    out.append(("当前目录", Path("handnote.toml")))
    out.append(("用户目录", user_config_path()))
    return out


def find_config() -> Optional[Path]:
    """The first config file that exists; ``HANDNOTE_CONFIG=none`` turns the search off."""
    if os.environ.get("HANDNOTE_CONFIG", "").lower() in ("none", "off", "0"):
        return None
    for label, p in config_candidates():
        if p.is_file():
            return p
        if label.startswith("环境变量"):
            raise FileNotFoundError(f"HANDNOTE_CONFIG points to a file that does not exist: {p}")
    return None


def field_docs() -> dict:
    """``{(section, name): description}`` taken from the comments next to the fields above."""
    out, cls = {}, None
    for line in Path(__file__).read_text(encoding="utf-8").splitlines():
        m = re.match(r"class (\w+)Config\b", line)
        if m:
            cls = m.group(1).lower()
            continue
        m = re.match(r"    (\w+): [^=#]+=.*?(?:#\s*(.*))?$", line)
        if cls and m:
            out[(cls, m.group(1))] = (m.group(2) or "").strip()
    return out


SECTION_TITLES = {
    "page": ("[page] 页面几何", "单位是像素。默认 A4、200 dpi。文字基线落在 margin_top + n × pitch 这条网格上，横线纸的线画在同一网格上。"),
    "text": ("[text] 字体、排版、手写抖动、手绘线条", "字形抖动和线条抖动的每一项设为 0 即关闭；heading_* 的数字是空行数。"),
    "paper": ("[paper] 稿纸", "template 可以是 ruled / blank / grid、纸张模板 .toml、或一张纸张图片。"),
    "llm": ("[llm] 本地模型（handnote write 用）", "指向一个 OpenAI 兼容的服务，例如 llama.cpp 的 llama-server。提示词内置在程序里，这里只配连接和采样。"),
    "photo": ("[photo] 拍照效果", "每一项数值设为 0（或 shadow = \"none\"）即关闭对应效果；enabled = false 整体关闭拍照阶段。"),
}

ANNOTATED_HEADER = """\
# handnote 配置文件（全部选项，附说明与候选值）
#
# 放在下面任一位置，不加 -c 时会自动读取（先找到的生效）：
#   1. 环境变量 HANDNOTE_CONFIG 指向的文件（设为 none 则不读任何配置文件）
#   2. 当前目录的 handnote.toml
#   3. 用户目录：Linux/macOS 是 ~/.config/handnote/config.toml，Windows 是 %APPDATA%\\handnote\\config.toml
# 命令行 -c 文件.toml 指定别的文件；--no-config 完全不读；--set 段.键=值 在以上之上再覆盖单项。
# `handnote config --path` 查看当前读到的是哪个文件。
#
# 想改什么就改什么：删掉不想固定的行也可以，缺省的项用内置默认值。
# 键名拼错会直接报错。数值型效果设为 0 即关闭。
# 文件里的相对路径（字体、纸张图片）若在本文件旁边能找到，就按本文件所在目录解释。
"""

# Candidate / expected values shown above every option in the annotated config.
HINTS = {
    "seed": "整数，如 42；不设置则每次随机",
    "page.width": "整数像素；A4@200dpi 为 1654，A5 为 1169（用纸张模板时模板会给出）",
    "page.height": "整数像素；A4@200dpi 为 2339，A5 为 1654",
    "page.margin_top": "整数像素，100 ~ 200；决定第一行基线和横线的起点",
    "page.margin_bottom": "整数像素，80 ~ 200",
    "page.margin_left": "整数像素，120 ~ 260",
    "page.margin_right": "整数像素，60 ~ 160",
    "page.pitch": "整数像素，52 ~ 72；越小一页越密，字号 = pitch × text.size_ratio",
    "text.fonts": '字体文件路径或文件名片段的列表，如 ["fonts/LongCang-Regular.ttf", "lxgw"]；[] 为自动',
    "text.heading_font": '字体路径或名片段，如 "mashanzheng"；"" 同正文',
    "text.code_font": '字体路径或名片段；"" 同正文',
    "text.punct_font": '字体路径或名片段，如 "lxgw"；"" 同正文（自动选字体时借用文楷）',
    "text.latin_font": '字体路径或名片段，如 "lxgw"；"" 同正文（自动选字体时借用文楷）',
    "text.font_dir": '目录路径；"" 为只在 ./fonts 和系统字体目录里找',
    "text.size_ratio": "0.6 ~ 0.85，越大字越大；0.74 为默认",
    "text.heading_scales": "六个数，1.0 ~ 2.0；1.0 与正文同大",
    "text.heading_gap_before": "六个整数，0 ~ 3；0 为不空行",
    "text.heading_gap_after": "六个整数，0 ~ 3；0 为不空行",
    "text.spacing_mode": "ink | advance",
    "text.ink_gap": "-0.05 ~ 0.3；0.08 为默认，0 为笔画边界相贴，越大越疏",
    "text.ink_min_width": "0 ~ 0.6；0 为完全按笔画宽度",
    "text.letter_spacing": "-0.08 ~ 0.3；0 为字与字紧贴，负数更挤，0.03 为默认，0.15 以上很疏",
    "text.paragraph_indent": "0 ~ 2；0 顶格，2 为中文常见的空两格",
    "text.list_indent": "0.8 ~ 1.6；大括号与文字的距离",
    "text.list_marker": "none | dot",
    "text.label_max_chars": "0 ~ 12；0 为不把标签挪到括号尖角左侧",
    "text.softbreak": "auto | newline",
    "text.table_mode": "list | skip",
    "text.script_marks": "true | false",
    "text.script_scale": "0.5 ~ 0.8",
    "text.sup_rise": "0.2 ~ 0.6",
    "text.sub_drop": "0.05 ~ 0.3",
    "text.quote_indent": "0 ~ 4；0 为不缩进",
    "text.quote_marker": "triangle | filled | none",
    "text.code_scale": "0.7 ~ 1.0",
    "text.code_rule": "true | false",
    "text.code_pen": "main | accent",
    "text.pos_jitter": "0 ~ 0.06；0 关闭",
    "text.baseline_wave": "0 ~ 0.06；0 关闭",
    "text.line_slope_deg": "0 ~ 1.0；0 关闭",
    "text.rotate_deg": "0 ~ 3；0 关闭，1.2 为默认",
    "text.scale_jitter": "0 ~ 0.08；0 关闭",
    "text.shear_jitter": "0 ~ 0.08；0 关闭",
    "text.warp_amp": "0 ~ 0.03；0 关闭，0.008 工整，0.02 已经很潦草",
    "text.warp_sigma": "0.05 ~ 0.2；越大扭曲越平缓",
    "text.thickness_jitter": "0 ~ 0.2；0 关闭",
    "text.pressure_var": "0 ~ 0.3；0 关闭",
    "text.line_gain_var": "0 ~ 0.2；0 关闭",
    "text.line_wobble": "0 ~ 0.15；0 为尺子般笔直，0.05 为默认",
    "text.line_tilt_deg": "0 ~ 3；0 关闭",
    "text.line_overshoot": "0 ~ 0.6；0 为首末不超出",
    "text.line_width": "0.03 ~ 0.07；越大笔越粗",
    "text.brace_tip": "0.1 ~ 0.5；0.25 即大括号纵向 2/8 处，0.5 为正中",
    "text.ink": "black | blue | blue-black | red | green",
    "text.accent": "black | blue | blue-black | red | green",
    "paper.kind": "ruled | blank | grid",
    "paper.template": '"" | ruled | blank | grid | "路径/模板.toml" | "路径/纸张.jpg"',
    "paper.image": '"" 或纸张图片路径',
    "paper.image_fit": "cover | stretch",
    "paper.color": "[R, G, B]，如 [247, 245, 238] 米白，[255, 255, 255] 纯白，[240, 232, 210] 泛黄",
    "paper.line_color": "[R, G, B]，如 [150, 182, 208] 浅蓝，[200, 200, 200] 浅灰",
    "paper.line_width": "整数 1 ~ 4",
    "paper.line_var": "0 ~ 0.3；0 为完全均匀",
    "paper.margin_line": "true | false",
    "paper.grain": "0 ~ 0.03；0 关闭",
    "paper.tint_var": "0 ~ 0.03；0 关闭",
    "paper.stain_count": "整数 0 ~ 5；0 关闭",
    "paper.stain_strength": "0 ~ 0.4",
    "paper.stain_min": "0.01 ~ 0.03",
    "paper.stain_max": "0.03 ~ 0.08",
    "paper.stain_color": "[R, G, B]，如 [150, 112, 62] 茶渍",
    "llm.host": '主机名或 IP，如 "127.0.0.1"、"192.168.1.5"',
    "llm.port": "整数端口，llama-server 默认 8080",
    "llm.base_url": '"" | "http://主机:端口/v1"；填了就忽略 host 和 port',
    "llm.model": '模型名字符串，如 "qwen3.6-35b-a3b"',
    "llm.api_key": '"" | 密钥字符串',
    "llm.temperature": "0 ~ 1.2；0.4 ~ 0.8 比较稳",
    "llm.top_p": "0.8 ~ 1.0",
    "llm.max_tokens": "整数，2048 ~ 8192；两页笔记约 1500 token",
    "llm.thinking": "true | false",
    "llm.timeout": "整数秒，120 ~ 1800",
    "llm.fix_rounds": "整数 0 ~ 5；0 为检查出问题也不让模型改",
    "llm.chunk_chars": "整数，3000 ~ 30000；模型上下文越大可以越大",
    "llm.notes_dir": '目录路径，如 "notes"',
    "photo.enabled": "true | false；false 则只输出平整的稿纸图",
    "photo.pad": "0 ~ 0.15",
    "photo.perspective": "0 ~ 0.05；0 关闭",
    "photo.tilt_min": "0 ~ 15（度）；3 ~ 8 是随手拍的常见范围",
    "photo.tilt_max": "0 ~ 20（度）；0 关闭倾斜；超过 15 就很夸张",
    "photo.tilt_direction": 'top | bottom | left | right | random | 角度数字如 "30"（0=上端，顺时针）',
    "photo.tilt_direction_jitter": "0 ~ 45（度）；0 为方向固定",
    "photo.focal_length": "0.5 ~ 1.5；0.8 约等于手机主摄，越小透视越夸张",
    "photo.rotation": "0 ~ 3；0 关闭",
    "photo.bend": "0 ~ 0.006；0 关闭",
    "photo.edge_bow_min": "0 ~ 0.01；与 max 一起决定每条边的弯曲幅度",
    "photo.edge_bow_max": "0 ~ 0.02；0 则边缘笔直",
    "photo.corner_lift": "0 ~ 0.04；0 关闭",
    "photo.corner_lift_prob": "0 ~ 1",
    "photo.dog_ear_prob": "0 ~ 1；0 从不出现折角",
    "photo.dog_ear_min": "0.02 ~ 0.05",
    "photo.dog_ear_max": "0.04 ~ 0.1",
    "photo.stack_count": "整数 0 ~ 6；0 关闭，2 ~ 4 像一沓纸",
    "photo.stack_offset": "0.005 ~ 0.03",
    "photo.stack_rotation": "0 ~ 3（度）；0 为每张摆得很齐",
    "photo.stack_direction": "random | top-left | top | top-right | left | right | bottom-left | bottom | bottom-right",
    "photo.paper_shadow": "0 ~ 1；0 关闭",
    "photo.desk_color": "[R, G, B]，如 [92, 74, 62] 木色，[60, 60, 64] 深灰",
    "photo.desk_texture": "0 ~ 2；0 为纯色",
    "photo.shadow": "random | phone | window | none",
    "photo.shadow_position": "random | top-left | top | top-right | left | right | bottom-left | bottom | bottom-right",
    "photo.shadow_strength": "0 ~ 0.6",
    "photo.light_gradient": "0 ~ 0.4；0 关闭",
    "photo.vignette": "0 ~ 0.5；0 关闭",
    "photo.color_cast": "0 ~ 0.04；0 关闭",
    "photo.tone_var": "0 ~ 0.15；0 关闭",
    "photo.blur": "0 ~ 2（像素）；0 关闭",
    "photo.sharpen": "0 ~ 1；0 关闭",
    "photo.noise": "0 ~ 8；0 关闭",
    "photo.jpeg_quality": "整数 60 ~ 95",
}


def _find(spec: str, base: "Path | None") -> Path:
    cands = [Path(spec).expanduser()]
    if base is not None:
        cands.insert(0, base / spec)
    cands += [Path("templates") / spec, Path("templates") / (spec + ".toml")]
    for c in cands:
        if c.is_file():
            return c
    raise FileNotFoundError(f"paper template not found: {spec}")


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(type(v))


def _merge(obj: Any, data: dict, prefix: str = "") -> None:
    names = {f.name for f in fields(obj)}
    for key, val in data.items():
        if key not in names:
            raise ValueError(f"unknown config key: {prefix}{key}")
        cur = getattr(obj, key)
        if is_dataclass(cur):
            if not isinstance(val, dict):
                raise ValueError(f"config section {prefix}{key} must be a table")
            _merge(cur, val, f"{prefix}{key}.")
            continue
        if isinstance(cur, bool):
            val = bool(val)
        elif isinstance(cur, int):
            val = int(val)
        elif isinstance(cur, float):
            val = float(val)
        elif isinstance(cur, tuple):
            val = tuple(val)
        elif isinstance(cur, list):
            val = list(val)
        setattr(obj, key, val)
