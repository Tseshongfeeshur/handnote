"""`handnote lint`: check a Markdown note against what the renderer can draw naturally.

The renderer only understands a small part of Markdown and turns some of it into
things a person would not write by hand (tables, images, formulas).  This module
reports, line by line and with a concrete fix, everything in a note that would
render badly, so a language model (or a person) can correct the note before
rendering.  Messages are written as instructions on purpose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from markdown_it import MarkdownIt

from .config import Config

ERROR, WARN = "必须修改", "建议修改"

CHATTY = ("综上所述", "总而言之", "总的来说", "让我们", "本笔记", "希望对你", "希望这份", "以下是", "当然可以",
          "好的，", "好的。", "作为AI", "作为一个AI", "如果你还有", "需要我", "我来为你", "为您")
LATEX_CMD = re.compile(r"\\[a-zA-Z]{2,}|\\[()\[\]]")
LATEX_DOLLAR = re.compile(r"\$[^$\n]*[\\^_{}=][^$\n]*\$")


@dataclass
class Issue:
    level: str
    line: Optional[int]
    code: str
    message: str

    def __str__(self) -> str:
        where = f"第{self.line}行" if self.line else "全文"
        return f"[{self.level}] {where}：{self.message}"


@dataclass
class Report:
    issues: List[Issue] = field(default_factory=list)
    pages: int = 0
    lines: int = 0
    chars: int = 0

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == WARN]

    def codes(self) -> List[str]:
        return [i.code for i in self.issues]

    def text(self) -> str:
        out = [str(i) for i in sorted(self.issues, key=lambda i: (i.level != ERROR, i.line or 0))]
        head = f"预计渲染 {self.pages} 页（约 {self.lines} 行，{self.chars} 个汉字）。" if self.pages else ""
        if not self.issues:
            return f"{head}检查通过，没有需要修改的地方。"
        out.append(f"{head}共 {len(self.errors)} 处必须修改、{len(self.warnings)} 处建议修改。"
                   + ("修改后请重新运行检查。" if self.errors or self.warnings else ""))
        return "\n".join(out)


def _w(s: str) -> float:
    """Width in full-width character units."""
    return sum(1.0 if ord(c) > 0x2E7F else 0.5 for c in s)


def _inline_text(tok) -> str:
    return "".join(c.content for c in (tok.children or []) if c.type in ("text", "code_inline", "text_special"))


def lint(md: str, cfg: Optional[Config] = None, fonts=None) -> Report:
    cfg = cfg or Config()
    rep = Report()
    add = lambda level, line, code, msg: rep.issues.append(Issue(level, line, code, msg))  # noqa: E731
    lines = md.splitlines()
    pg = cfg.page
    cpl = (pg.width - pg.margin_left - pg.margin_right) / (pg.pitch * cfg.text.size_ratio * (1 + (cfg.text.ink_gap - 0.1 if cfg.text.spacing_mode == 'ink' else cfg.text.letter_spacing)))

    stripped = md.strip()
    if re.match(r"^`{3,}\s*(markdown|md)?\s*\n", stripped) and re.search(r"\n`{3,}\s*$", stripped):
        add(ERROR, 1, "whole-file-fence", "整份笔记被包在 ``` 代码块里。删掉最外层的 ``` 行，直接写 Markdown 正文。")
    if re.match(r"^---\s*\n(?:[^\n]*:[^\n]*\n)+---\s*\n", md):
        add(ERROR, 1, "front-matter", "文件开头有 YAML 头信息（--- 包起来的 key: value）。删掉，笔记只含正文。")
    for i, ln in enumerate(lines, 1):
        if ln.startswith("　"):
            add(WARN, i, "manual-indent", "行首有全角空格。不要手动缩进，排版会自动处理。")
            break

    # characters the fonts cannot draw
    if fonts is None:
        try:
            from .fonts import load_fontset

            fonts = load_fontset(cfg.text.fonts, cfg.text.font_dir, cfg.text.heading_font, cfg.text.code_font,
                                 cfg.text.punct_font, cfg.text.latin_font)
        except Exception:  # no fonts installed: skip the checks that need them
            fonts = None
    if fonts is not None:
        for i, ln in enumerate(lines, 1):
            bad = []
            for c in ln:
                if c.isprintable() and not c.isspace() and fonts.pick(c) < 0 and c not in bad:
                    bad.append(c)
            if bad:
                add(ERROR, i, "missing-glyph", f"字体里没有这些字，画不出来：{' '.join(bad)}。换成文字描述或常见符号（如 → × ≤ ✓），不要用 emoji。")

    for i, ln in enumerate(lines, 1):
        if any(p in ln for p in CHATTY):
            hit = next(p for p in CHATTY if p in ln)
            add(WARN, i, "chatty", f"出现了聊天或套话「{hit}」。笔记里不要写对话和总结套话，直接删掉这句。")

    parser = MarkdownIt("commonmark").enable(["strikethrough", "table"])
    toks = parser.parse(md)
    headings: List[tuple] = []  # (level, line, text)
    list_stack: List[dict] = []
    quote_depth = quote_count = 0
    rules = 0
    bold_chars = total_chars = 0
    prev_block = None

    for idx, t in enumerate(toks):
        line = (t.map[0] + 1) if t.map else None
        ty = t.type

        if ty == "table_open":
            add(ERROR, line, "table", "不要用表格，渲染时表格线不会画出来，内容会被拆成「表头：内容」。改写成列表，每行一项，如「- 名称：说明」。")
        elif ty == "html_block":
            add(ERROR, line, "html", "不要写 HTML 标签（如 <br>、<div>），它们不会显示。删掉标签，只留文字。")
        elif ty in ("fence", "code_block"):
            n = len(t.content.rstrip("\n").splitlines())
            if n > 12:
                add(WARN, line, "long-code", f"代码块有 {n} 行，太长。只留最关键的 5–10 行。")
            if re.search(r"^\|.*\|\s*$", t.content, re.M) and "-|-" in t.content.replace(" ", ""):
                add(WARN, line, "code-table", "代码块里画了表格，渲染出来会很乱。改成列表。")
        elif ty == "hr":
            rules += 1
        elif ty == "heading_open":
            lvl = int(t.tag[1])
            text = toks[idx + 1].content if idx + 1 < len(toks) else ""
            headings.append((lvl, line, text))
            if any(c.type in ("strong_open", "em_open") for c in (toks[idx + 1].children or [])):
                add(WARN, line, "heading-emphasis", "标题里不要再加粗或斜体，标题本身已经是大字。去掉 ** 或 *。")
        elif ty == "blockquote_open":
            quote_depth += 1
            if quote_depth == 1:
                quote_count += 1
                n = (t.map[1] - t.map[0]) if t.map else 0
                if n > 3:
                    add(WARN, line, "long-quote", f"引用块有 {n} 行，太长。引用只放老师强调的一两句话。")
        elif ty == "blockquote_close":
            quote_depth -= 1
        elif ty in ("bullet_list_open", "ordered_list_open"):
            list_stack.append({"ordered": ty == "ordered_list_open", "items": 0, "line": line})
            if len(list_stack) > 2:
                add(WARN, line, "deep-list", "列表嵌套超过两层，括号会挤在一起。把第三层并入第二层，或拆成新的小节。")
        elif ty == "list_item_open":
            list_stack[-1]["items"] += 1
        elif ty in ("bullet_list_close", "ordered_list_close"):
            lst = list_stack.pop()
            if not lst["ordered"] and lst["items"] == 1:
                add(WARN, lst["line"], "single-item-list", "只有一项的列表会画成一个小圆点，不像手写。改成一句普通的话，或补成至少两项。")
            if not lst["ordered"] and lst["items"] > 8:
                add(WARN, lst["line"], "long-list", f"一组并列要点有 {lst['items']} 项，括号会很长。精简到 6 项以内，或按类别拆成两组。")
            if lst["ordered"] and lst["items"] > 9:
                add(WARN, lst["line"], "long-list", f"编号列表有 {lst['items']} 项，太长。精简或分段。")
        elif ty == "inline":
            kids = t.children or []
            text = _inline_text(t)
            ctx = "heading" if prev_block == "heading_open" else ("list" if list_stack else ("quote" if quote_depth else "para"))
            if ctx != "heading":
                total_chars += int(_w(text))
            stack, span = [], ""
            for c in kids:
                if c.type == "image":
                    add(ERROR, line, "image", "不要插图片。渲染只会留下 [图片说明] 几个字。删掉，用文字描述。")
                elif c.type == "html_inline":
                    add(ERROR, line, "html", "不要写 HTML 标签（如 <br>），它们不会显示。换行直接另起一段。")
                elif c.type == "link_open":
                    add(WARN, line, "link", "不要写链接，网址不会显示，只留下链接文字。去掉 [ ]( ) 和网址，只写文字。")
                elif c.type in ("strong_open", "em_open", "s_open"):
                    stack.append(c.type)
                    span = ""
                    if c.type == "s_open":
                        add(WARN, line, "strike", "删除线很少用，会画成一道划掉的横线。除非是在更正错误，否则去掉 ~~。")
                elif c.type in ("strong_close", "em_close", "s_close"):
                    if stack:
                        stack.pop()
                    if c.type == "strong_close":
                        bold_chars += int(_w(span))
                    if _w(span) > 14:
                        add(WARN, line, "long-emphasis", f"「{span[:12]}…」这段加粗或斜体太长，划线应该只划关键词（几个字）。缩短被标记的部分。")
                elif stack and c.type in ("text", "code_inline", "text_special"):
                    span += c.content
            if len(kids) >= 3 and kids[0].type == "strong_open" and kids[-1].type == "strong_close" and ctx == "para" \
                    and sum(k.type == "strong_open" for k in kids) == 1:
                add(WARN, line, "bold-heading", "整行加粗的短句像标题，会被画成双横线。想表示小标题就用 ###，不是标题就去掉加粗。")
            full = t.content
            if LATEX_CMD.search(full) or LATEX_DOLLAR.search(full):
                add(ERROR, line, "latex", "不要写 LaTeX 公式（$…$、\\frac 等），不会被解析。用普通字符写公式，如 v = s / t、a² + b² = c²，或放进代码块。")
            if ctx == "list":
                if _w(text) > 2 * cpl:
                    add(WARN, line, "long-item", f"这一条有 {int(_w(text))} 个字，超过两行。拆成两条，或只留要点。")
            elif ctx == "para" and _w(text) > 3 * cpl:
                add(WARN, line, "long-paragraph", f"这一段有 {int(_w(text))} 个字，超过三行，不像课堂笔记。拆成短句，或改成列表。")
        if ty.endswith("_open") and ty != "inline":
            prev_block = ty

    # document-level checks
    h1 = [h for h in headings if h[0] == 1]
    if not h1:
        add(WARN, None, "no-h1", "没有标题。第一行写 `# 主题`，全文只用一个一级标题。")
    elif len(h1) > 1:
        add(ERROR, h1[1][1], "multi-h1", "有多个一级标题。一级标题只能出现一次（笔记题目），其余章节改用 ##。")
    for k, (lvl, ln, text) in enumerate(headings):
        if lvl >= 4:
            add(WARN, ln, "deep-heading", "用到了四级以下标题。最多用到 ###，更细的层次用列表表示。")
        if k and lvl > headings[k - 1][0] + 1:
            add(WARN, ln, "skip-level", f"标题层级跳级（{'#' * headings[k - 1][0]} 后面直接 {'#' * lvl}）。逐级使用。")
        nxt = headings[k + 1] if k + 1 < len(headings) else None
        end_line = (nxt[1] if nxt else len(lines) + 1)
        body = [x for x in lines[ln:end_line - 1] if x.strip()]
        if lvl > 1 and not body:
            add(WARN, ln, "empty-section", "这个小节下面没有内容。补上内容，或删掉这个标题。")
    if rules > 2:
        add(WARN, None, "many-rules", "用了太多 --- 分割线。整篇最多 1–2 条。")
    if bold_chars > 0.18 * max(total_chars, 1) and bold_chars > 30:
        add(WARN, None, "heavy-emphasis", "加粗太多，满篇都是双横线就没有重点了。只给每个新概念的名称加粗。")

    # layout estimate
    cjk = len(re.findall(r"[一-鿿]", md))
    rep.chars = cjk
    if fonts is not None:
        from . import parser as P
        from .layout import Layouter

        lay = Layouter(cfg, fonts)
        pages = lay.run(P.parse(md, cfg.text.table_mode))
        rep.pages, rep.lines = len(pages), lay.k
        if quote_count > 2 * max(1, rep.pages):
            add(WARN, None, "many-quotes", "引用块太多。引用（三角标记）只用于老师特别强调的话，每页最多一两处。")
        if rep.pages > 3:
            add(WARN, None, "too-long", f"渲染后有 {rep.pages} 页，太长。一份课堂笔记通常 1–2 页，精简或拆成两份。")
    if 0 < cjk < 150:
        add(WARN, None, "too-short", f"全文只有 {cjk} 个汉字，内容太少。补充定义、例子和要点。")
    return rep
