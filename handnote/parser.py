"""Stage 1: Markdown -> a small semantic document tree.

Only the constructs that have a meaningful handwritten counterpart survive.
Tables are parsed (so their syntax never leaks into the page as pipes) and then
degraded to a list of "header: value" rows, or dropped.  Links keep their text,
images become their alt text, raw HTML is ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional, Union
import re

from markdown_it import MarkdownIt

SOFT = "\r"  # soft line break, resolved at layout time
HARD = "\n"  # hard line break


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    strike: bool = False
    code: bool = False
    script: int = 0  # +1 superscript, -1 subscript


PLAIN = Style()


@dataclass
class Span:
    text: str
    style: Style = PLAIN


@dataclass
class Heading:
    level: int
    spans: List[Span]


@dataclass
class Paragraph:
    spans: List[Span]


@dataclass
class ListItem:
    blocks: list = field(default_factory=list)


@dataclass
class ListBlock:
    ordered: bool
    start: int
    items: List[ListItem]


@dataclass
class Quote:
    blocks: list


@dataclass
class CodeBlock:
    text: str
    lang: str = ""


@dataclass
class Rule:
    pass


Block = Union[Heading, Paragraph, ListBlock, Quote, CodeBlock, Rule]


def plain_text(spans: List[Span]) -> str:
    return "".join(s.text for s in spans if s.text not in (SOFT, HARD))


def parse(text: str, table_mode: str = "list", script_marks: bool = True) -> List[Block]:
    md = MarkdownIt("commonmark").enable(["strikethrough", "table"])
    tokens = md.parse(text)
    global _SCRIPTS
    _SCRIPTS = script_marks
    blocks, _ = _blocks(tokens, 0, None, table_mode)
    return blocks


# x^2, 10^-3, e^x, x^{n+1}, x^(n+1)  and  v_0, a_n, x_{i+1}: handwriting raises or lowers these, it does not write ^ or _
_SCRIPTS = True
_EXP = r"[+\-\u2212]?(?:\d+(?:\.\d+)?|[A-Za-z\u03b1-\u03c9\u0391-\u03a9])"
_SUP = re.compile(r"\^(?:\{([^{}\n]{1,12})\}|\(([^()\n]{1,12})\)|(" + _EXP + "))")
_SUB = re.compile(r"_(?:\{([^{}\n]{1,12})\}|(\d+|[A-Za-z\u03b1-\u03c9])(?![A-Za-z0-9_]))")


def _scripts(text: str, st: Style, prev_ok: bool) -> List[Span]:
    """Split ``text`` into plain parts and raised/lowered parts.  A mark only counts right after something that can
    carry it (not at the start of a word or after a space); anything else stays as typed."""
    if not _SCRIPTS or ("^" not in text and "_" not in text):
        return [Span(text, st)]
    out: List[Span] = []
    pos = 0
    for m in sorted(list(_SUP.finditer(text)) + list(_SUB.finditer(text)), key=lambda m: m.start()):
        if m.start() < pos:
            continue
        before = text[m.start() - 1] if m.start() else ("x" if prev_ok else " ")
        if not (before.isalnum() or before in ")]}）】"):
            continue
        sup = text[m.start()] == "^"
        if not sup and "_" in re.search(r"[A-Za-z0-9_]*$", text[:m.start()]).group():
            continue  # snake_case_names are not subscripts
        body = next(g for g in m.groups() if g is not None)
        if m.start() > pos:
            out.append(Span(text[pos:m.start()], st))
        out.append(Span(body, replace(st, script=1 if sup else -1)))
        pos = m.end()
    if pos < len(text):
        out.append(Span(text[pos:], st))
    return out or [Span(text, st)]


# ---------------------------------------------------------------- blocks

def _blocks(tokens, i: int, stop: Optional[str], table_mode: str):
    out: list = []
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if stop is not None and t.type == stop:
            return out, i + 1
        ty = t.type
        if ty == "heading_open":
            out.append(Heading(int(t.tag[1]), _inline(tokens[i + 1])))
            i += 3
        elif ty == "paragraph_open":
            out.append(Paragraph(_inline(tokens[i + 1])))
            i += 3
        elif ty in ("bullet_list_open", "ordered_list_open"):
            ordered = ty == "ordered_list_open"
            start = int(t.attrGet("start") or 1) if ordered else 1
            items = []
            i += 1
            while i < n and tokens[i].type == "list_item_open":
                sub, i = _blocks(tokens, i + 1, "list_item_close", table_mode)
                items.append(ListItem(sub))
            i += 1  # list close
            out.append(ListBlock(ordered, start, items))
        elif ty == "blockquote_open":
            sub, i = _blocks(tokens, i + 1, "blockquote_close", table_mode)
            out.append(Quote(sub))
        elif ty in ("fence", "code_block"):
            out.append(CodeBlock(t.content.rstrip("\n"), (t.info or "").strip()))
            i += 1
        elif ty == "hr":
            out.append(Rule())
            i += 1
        elif ty == "table_open":
            blk, i = _table(tokens, i, table_mode)
            if blk is not None:
                out.append(blk)
        else:  # html_block, stray closers, anything unsupported
            i += 1
    return out, i


def _table(tokens, i: int, mode: str):
    header: list = []
    rows: list = []
    cur: list = []
    in_head = False
    i += 1
    while tokens[i].type != "table_close":
        ty = tokens[i].type
        if ty == "thead_open":
            in_head = True
        elif ty == "thead_close":
            in_head = False
        elif ty == "tr_open":
            cur = []
        elif ty == "tr_close":
            if in_head:
                header = cur
            else:
                rows.append(cur)
        elif ty in ("th_open", "td_open"):
            cur.append(_inline(tokens[i + 1]))
        i += 1
    i += 1
    if mode == "skip":
        return None, i
    items = []
    for row in rows:
        spans: List[Span] = []
        for j, cell in enumerate(row):
            if not plain_text(cell).strip():
                continue
            if spans:
                spans.append(Span("；"))
            label = plain_text(header[j]).strip() if j < len(header) else ""
            if label:
                spans.append(Span(label + "："))
            spans.extend(cell)
        if spans:
            items.append(ListItem([Paragraph(spans)]))
    if not items:
        return None, i
    return ListBlock(False, 1, items), i


# ---------------------------------------------------------------- inline

def _inline(tok) -> List[Span]:
    spans: List[Span] = []
    st = PLAIN
    for c in tok.children or []:
        ty = c.type
        if ty == "text":
            spans.extend(_scripts(c.content, st, bool(spans) and spans[-1].text not in (SOFT, HARD) and not spans[-1].text[-1:].isspace()))
        elif ty == "text_special":
            spans.append(Span(c.content, st))
        elif ty == "softbreak":
            spans.append(Span(SOFT, st))
        elif ty == "hardbreak":
            spans.append(Span(HARD, st))
        elif ty == "strong_open":
            st = replace(st, bold=True)
        elif ty == "strong_close":
            st = replace(st, bold=False)
        elif ty == "em_open":
            st = replace(st, italic=True)
        elif ty == "em_close":
            st = replace(st, italic=False)
        elif ty == "s_open":
            st = replace(st, strike=True)
        elif ty == "s_close":
            st = replace(st, strike=False)
        elif ty == "code_inline":
            spans.append(Span(c.content, replace(st, code=True)))
        elif ty == "image":
            alt = (c.content or "").strip()
            spans.append(Span(f"[{alt or '图'}]", st))
        # link_open/link_close/html_inline: ignored, link text is plain text
    return _merge_spans(spans)


def _merge_spans(spans: List[Span]) -> List[Span]:
    out: List[Span] = []
    for s in spans:
        if out and out[-1].style == s.style and s.text not in (SOFT, HARD) and out[-1].text not in (SOFT, HARD):
            out[-1] = Span(out[-1].text + s.text, s.style)
        else:
            out.append(s)
    return out
