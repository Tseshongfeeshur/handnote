"""Stage 2: document tree -> positioned drawing elements, then pagination.

Everything is first laid out on one tall "scroll" whose line grid is the
ruled-paper grid: line `k` has its baseline at y = (k + 1) * pitch.  Text lines
are atoms (a heading may span several grid lines but is never split).  The
scroll is then cut into pages at atom boundaries, keeping short lists and code
blocks together and never leaving a heading stranded at the bottom of a page.

Handwriting conventions implemented here:
  * unordered lists are grouped by one curly brace spanning all their lines
    (nested lists get nested braces, the tip sits at 2/8 of the height); a short
    "Label:" paragraph directly above a list is moved to the left of the tip
  * headings are left aligned, larger, snap to whole grid lines and have a
    configurable number of blank lines above and below
  * a quotation is an indented paragraph with a hand-drawn triangle in the
    indent of its first line; a code block has only a rule on its left
  * line breaking follows Chinese punctuation rules (no closing punctuation at
    line start, no opening bracket at line end)
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from . import parser as P
from .config import Config
from .elements import Brace, Deco, Dot, Glyph, HRule, Page, Tri, VBar
from .fonts import is_cjk

NO_START = set("，。、；：！？）】》」』”’…—·,.;:!?)]}%")
NO_END = set("（【《「『“‘([{")

_CODE_STYLE = P.Style(code=True)


@dataclass
class PC:
    """A character with its style and advance, ready to be placed."""

    ch: str
    style: P.Style
    adv: float
    font: int
    x: float = 0.0  # where the glyph's ink starts (ink mode) or its cell starts (advance mode)
    lsb: float = 0.0  # distance from the glyph origin to its ink edge, so the origin is drawn at x - lsb
    gap: float = 0.0  # space after the glyph that is not part of it (underlines stop before it)


class Layouter:
    def __init__(self, cfg: Config, fonts):
        self.cfg = cfg
        self.fonts = fonts
        pg = cfg.page
        self.pitch = float(pg.pitch)
        self.base = pg.pitch * cfg.text.size_ratio
        self.x_left = float(pg.margin_left)
        self.x_right = float(pg.width - pg.margin_right)
        self.k = 0  # next free grid line
        self.elements: list = []
        self.occupied: set = set()
        self.forbidden: set = set()  # cut points that would split a multi-line atom
        self.groups: List[Tuple[int, int]] = []  # keep-together line ranges
        self.active: List[list] = []  # open extents (braces, code rules)
        self._line_id = 0
        self._role = "body"  # font role of the text being laid out: body | heading
        self._mark: Optional[Tuple[float, bool]] = None  # quote triangle waiting for its text line

    # ------------------------------------------------------------ driver
    def run(self, blocks) -> List[Page]:
        self.blocks(blocks, self.x_left, self.x_right)
        return self._paginate()

    # ------------------------------------------------------------ chars
    def _metrics(self, ch: str, size: float, code: bool = False, role: str = "body"):
        """(advance, left bearing, trailing gap) of one character."""
        t = self.cfg.text
        if ch == " ":
            return size * (0.5 if code else 0.3), 0.0, 0.0
        if code and not is_cjk(ch):
            return size * 0.55, 0.0, 0.0
        if is_cjk(ch):
            if t.spacing_mode == "ink" and not code:
                ext = self.fonts.ink_extent(ch, role)
                if ext:
                    gap = t.ink_gap * size
                    return max((ext[1] - ext[0]) * size + gap, t.ink_min_width * size), ext[0] * size, gap
            gap = size * t.letter_spacing
            return self.fonts.advance(ch, size, role) + gap, 0.0, gap
        return self.fonts.advance(ch, size, role), 0.0, 0.0

    def _adv(self, ch: str, size: float, code: bool = False, role: str = "body") -> float:
        return self._metrics(ch, size, code, role)[0]

    def _pc(self, ch: str, style: P.Style, size: float, code: bool = False) -> PC:
        role = "code" if (code or style.code) else self._role
        adv, lsb, gap = self._metrics(ch, size, code, role)
        return PC(ch, style, adv, self.fonts.pick(ch, role), lsb=lsb, gap=gap)

    def _text_width(self, text: str, size: float) -> float:
        return sum(self._adv(c, size) for c in text)

    def _n_lines(self, size: float) -> int:
        return max(1, math.ceil(size / self.pitch - 0.03))

    def _flatten(self, spans, code: bool = False):
        raw = []
        for sp in spans:
            for ch in sp.text:
                raw.append((ch, sp.style))
        out = []
        for i, (ch, st) in enumerate(raw):
            if ch == "\t":
                out.extend([(" ", st)] * 4)
            elif ch == P.SOFT:
                if self.cfg.text.softbreak == "newline":
                    out.append((P.HARD, st))
                    continue
                prev = out[-1][0] if out else ""
                j = i + 1
                while j < len(raw) and raw[j][0] == P.SOFT:
                    j += 1
                nxt = raw[j][0] if j < len(raw) else ""
                if prev and nxt and is_cjk(prev) and is_cjk(nxt):
                    continue
                if prev and prev != " ":
                    out.append((" ", st))
            elif ch.isprintable() or ch == P.HARD:
                out.append((ch, st))
        return out

    # ------------------------------------------------------------ line breaking
    def _break(self, chars, size: float, avail_first: float, avail_rest: float, code: bool = False):
        lines: List[List[PC]] = []
        cur: List[PC] = []
        state = {"w": 0.0, "avail": avail_first}

        def newline(carry=None):
            while cur and cur[-1].ch == " " and not code:
                cur.pop()
            lines.append(list(cur))
            cur.clear()
            if carry:
                cur.extend(carry)
            state["w"] = sum(p.adv for p in cur)
            state["avail"] = avail_rest

        i, n = 0, len(chars)
        while i < n:
            ch, st = chars[i]
            if ch == P.HARD:
                newline()
                i += 1
                continue
            if ch == " " and not code:
                if cur:
                    pc = self._pc(ch, st, size)
                    cur.append(pc)
                    state["w"] += pc.adv
                i += 1
                continue
            j = i + 1
            if not code and not is_cjk(ch) and ch != " ":
                while j < n and chars[j][0] not in (P.HARD, " ") and not is_cjk(chars[j][0]):
                    j += 1
            unit = [self._pc(c, s, size, code) for c, s in chars[i:j]]
            i = j
            uw = sum(p.adv for p in unit)
            if state["w"] + uw <= state["avail"] + 0.5:
                cur.extend(unit)
                state["w"] += uw
                continue
            # closing punctuation may hang past the margin by up to one em
            if len(unit) == 1 and unit[0].ch in NO_START and cur and state["w"] + uw <= state["avail"] + size * 1.05:
                cur.extend(unit)
                state["w"] += uw
                continue
            if cur:
                carry = []
                while cur and cur[-1].ch in NO_END:
                    carry.insert(0, cur.pop())
                if len(unit) == 1 and unit[0].ch in NO_START and len(cur) > 1:
                    # never start a line with closing punctuation: bring the previous word along
                    k = 1
                    while k < len(cur) and not is_cjk(cur[-k].ch) and cur[-k].ch != " " and not is_cjk(cur[-k - 1].ch) and cur[-k - 1].ch != " ":
                        k += 1
                    if k < len(cur):
                        carry = cur[-k:] + carry
                        del cur[-k:]
                newline(carry)
            if uw <= state["avail"] - state["w"] + 0.5:
                cur.extend(unit)
                state["w"] += uw
            else:  # a single over-long word: wrap it character by character
                for p in unit:
                    if cur and state["w"] + p.adv > state["avail"] + 0.5:
                        newline()
                    cur.append(p)
                    state["w"] += p.adv
        while cur and cur[-1].ch == " " and not code:
            cur.pop()
        if cur or not lines:
            lines.append(list(cur))
        return lines

    # ------------------------------------------------------------ placing
    def _place(self, line: List[PC], x: float, k: int, n: int, size: float) -> float:
        """Emit glyphs and decorations for one text line; returns its baseline y."""
        y = (k + n) * self.pitch
        if self._mark is not None:
            mx, filled = self._mark
            self._mark = None
            self.elements.append(Tri(mx, y, size, "main", k + n - 1, filled))
        lid = self._line_id
        self._line_id += 1
        cx = x
        kb = k + n - 1
        for pc in line:
            pc.x = cx
            if pc.font >= 0 and not pc.ch.isspace():
                pen = self.cfg.text.code_pen if pc.style.code else "main"
                gx = cx - pc.lsb
                if pc.style.code and not is_cjk(pc.ch):  # fixed-width cell: centre the glyph in it
                    gx += 0.5 * (pc.adv - self.fonts.advance(pc.ch, size, "code"))
                self.elements.append(Glyph(pc.ch, gx, y, size, pc.font, pen, lid, kb))
            cx += pc.adv
        self._decorate(line, y, size, lid, kb)
        for kk in range(k, k + n):
            self.occupied.add(kk)
        for kk in range(k + 1, k + n):
            self.forbidden.add(kk)
        extent = (y - 0.9 * size, y + 0.1 * size)
        for ext in self.active:
            ext.append(extent)
        return y

    def _decorate(self, line, y, size, lid, kb):
        def runs(fn):
            res, cur, a, b = [], None, 0.0, 0.0
            for pc in line:
                v = fn(pc.style)
                end = pc.x + pc.adv - pc.gap
                if v is not None and v == cur:
                    b = end
                else:
                    if cur is not None:
                        res.append((cur, a, b))
                    cur, a, b = (v, pc.x, end) if v is not None else (None, 0.0, 0.0)
            if cur is not None:
                res.append((cur, a, b))
            return res

        def under(st):
            if st.code:
                return None
            return "double" if st.bold else ("single" if st.italic else None)

        for kind, a, b in runs(under) + runs(lambda st: "strike" if st.strike else None):
            self.elements.append(Deco(kind, a, b, y, size, "main", lid, kb))

    def text(self, spans, x0, x1, size, indent=0.0, marker=None, code=False) -> Optional[float]:
        chars = self._flatten(spans, code)
        if not chars:
            return None
        avail = x1 - x0
        lines = self._break(chars, size, avail - indent, avail, code)
        n = self._n_lines(size)
        first_y = None
        first = True
        for line in lines:
            if not line:
                self.k += n  # blank line from consecutive hard breaks
                first = False
                continue
            if first and marker:
                mtxt, mx = marker
                self._place([self._pc(c, P.PLAIN, size) for c in mtxt], mx, self.k, n, size)
            y = self._place(line, x0 + (indent if first else 0.0), self.k, n, size)
            if first_y is None:
                first_y = y
            self.k += n
            first = False
        return first_y

    # ------------------------------------------------------------ blocks
    def blocks(self, blks, x0, x1):
        i = 0
        while i < len(blks):
            b = blks[i]
            nxt = blks[i + 1] if i + 1 < len(blks) else None
            if isinstance(b, P.Paragraph) and isinstance(nxt, P.ListBlock) and not nxt.ordered and self._label_ok(b, x0, x1):
                self.list_block(nxt, x0, x1, label=b)
                i += 2
                continue
            self.block(b, x0, x1)
            i += 1

    def block(self, b, x0, x1):
        if isinstance(b, P.Heading):
            self.heading(b, x0, x1)
        elif isinstance(b, P.Paragraph):
            self.text(b.spans, x0, x1, self.base, indent=self.cfg.text.paragraph_indent * self.base)
        elif isinstance(b, P.ListBlock):
            self.list_block(b, x0, x1)
        elif isinstance(b, P.Quote):
            self.quote(b, x0, x1)
        elif isinstance(b, P.CodeBlock):
            self.code_block(b, x0, x1)
        elif isinstance(b, P.Rule):
            self.rule(x0, x1)

    def heading(self, h: P.Heading, x0, x1):
        t = self.cfg.text
        lvl = min(max(h.level, 1), 6) - 1

        def at(seq, default):
            return seq[lvl] if lvl < len(seq) else (seq[-1] if seq else default)

        size = self.base * at(t.heading_scales, 1.0)
        if self.k > 0:
            self.k += max(0, int(at(t.heading_gap_before, 0)))
        k0 = self.k
        self._role = "heading"
        try:
            self.text(h.spans, x0, x1, size)
        finally:
            self._role = "body"
        if self.k > k0:
            self.groups.append((k0, self.k + 1))  # keep with the next line
            self.k += max(0, int(at(t.heading_gap_after, 0)))

    def rule(self, x0, x1):
        k = self.k
        y = (k + 1) * self.pitch - 0.35 * self.pitch
        self.elements.append(HRule(x0, x1, y, "main", k))
        self.occupied.add(k)
        self.k += 1

    def quote(self, q: P.Quote, x0, x1):
        """An indented paragraph; a hand-drawn triangle stands in the first line's indent."""
        t = self.cfg.text
        size = self.base
        ind = max(0.0, t.quote_indent) * size
        if t.quote_marker in ("triangle", "filled") and ind > 0:
            w = 0.56 * size
            self._mark = (x0 + max(0.0, ind - w - 0.38 * size), t.quote_marker == "filled")
        self.blocks(q.blocks, x0 + ind, x1)
        self._mark = None

    def code_block(self, cb: P.CodeBlock, x0, x1):
        t = self.cfg.text
        size = self.base * t.code_scale
        pad = 0.75 * size if t.code_rule else 0.0
        k0 = self.k
        self.active.append([])
        for src in cb.text.replace("\t", "    ").split("\n"):
            if not src.strip():
                self.k += 1
                self.occupied.add(self.k - 1)
                for ext in self.active:
                    ext.append(((self.k) * self.pitch - 0.9 * size, (self.k) * self.pitch + 0.1 * size))
                continue
            chars = [(c, _CODE_STYLE) for c in src if c.isprintable()]
            for line in self._break(chars, size, (x1 - x0) - pad, (x1 - x0) - pad, code=True):
                self._place(line, x0 + pad, self.k, 1, size)
                self.k += 1
        rec = self.active.pop()
        if rec and t.code_rule:
            top = min(a for a, _ in rec) - 0.06 * self.pitch
            bot = max(b for _, b in rec) + 0.06 * self.pitch
            self.elements.append(VBar(x0 + 0.12 * size, top, bot, "main"))
        if 0 < self.k - k0 <= 14:
            self.groups.append((k0, self.k))

    # ------------------------------------------------------------ lists
    def _label_pcs(self, para: P.Paragraph, size: float) -> List[PC]:
        chars = self._flatten(para.spans)
        while chars and chars[-1][0] in " :：":
            chars.pop()
        return [self._pc(c, s, size) for c, s in chars]

    def _label_ok(self, para: P.Paragraph, x0, x1) -> bool:
        txt = P.plain_text(para.spans).strip()
        if not txt or txt[-1] not in ":：":
            return False
        if any(s.text in (P.SOFT, P.HARD) for s in para.spans):
            return False
        body = txt[:-1].strip()
        if not body or len(body) > self.cfg.text.label_max_chars:
            return False
        w = sum(p.adv for p in self._label_pcs(para, self.base))
        return w <= 0.35 * (x1 - x0)

    def list_block(self, lst: P.ListBlock, x0, x1, label: Optional[P.Paragraph] = None):
        size = self.base
        t = self.cfg.text
        lab = self._label_pcs(label, size) if label is not None else None
        xb = x0 + (sum(p.adv for p in lab) + 0.4 * size if lab else 0.0)
        if lst.ordered:
            mw = max(self._text_width(f"{lst.start + i}.", size) for i in range(len(lst.items)))
            x_items = x0 + mw + 0.35 * size
        else:
            x_items = xb + t.list_indent * size
        k0 = self.k
        self.active.append([])
        for idx, item in enumerate(lst.items):
            marker = (f"{lst.start + idx}.", x0) if lst.ordered else None
            self.list_item(item, x_items, x1, marker, lst.ordered)
        rec = self.active.pop()
        if not rec:
            return
        if not lst.ordered:
            top = min(a for a, _ in rec) - 0.08 * self.pitch
            bot = max(b for _, b in rec) + 0.05 * self.pitch
            if len(rec) >= 2:
                self.elements.append(Brace(xb, top, bot, size, "main"))
            else:
                self.elements.append(Dot(xb + 0.25 * size, (top + bot) / 2, 0.07 * size, "main", k0))
            if lab:
                tip = top + t.brace_tip * (bot - top)
                kl = int(round((tip + 0.30 * size) / self.pitch)) - 1
                kl = max(k0, min(self.k - 1, kl))
                self._place(lab, x0, kl, 1, size)
        if 0 < self.k - k0 <= 14:
            self.groups.append((k0, self.k))

    def list_item(self, item: P.ListItem, x_text, x1, marker, ordered_parent: bool):
        size = self.base
        first = True
        for blk in item.blocks:
            if isinstance(blk, P.Paragraph):
                fy = self.text(blk.spans, x_text, x1, size, marker=marker if first else None)
                if first and fy is not None and marker is None and self.cfg.text.list_marker == "dot":
                    kk = int(round(fy / self.pitch)) - 1
                    self.elements.append(Dot(x_text - 0.32 * size, fy - 0.30 * size, 0.075 * size, "main", kk))
            elif isinstance(blk, P.ListBlock):
                self.list_block(blk, x_text + (0.0 if ordered_parent else 0.35 * size), x1)
            else:
                self.block(blk, x_text, x1)
            first = False

    # ------------------------------------------------------------ pagination
    def _starts(self, total: int, n: int) -> List[int]:
        starts: List[int] = []
        cur = 0
        while cur < total and cur not in self.occupied:
            cur += 1
        while True:
            starts.append(cur)
            limit = cur + n
            if total <= limit:
                break
            c = limit
            changed = True
            while changed and c > cur + 1:
                changed = False
                if c in self.forbidden:
                    c -= 1
                    changed = True
                    continue
                for g0, g1 in self.groups:
                    if cur < g0 < c < g1 and (g1 - g0) <= n:
                        c = g0
                        changed = True
                        break
            if c <= cur:
                c = limit
            nxt = c
            while nxt < total and nxt not in self.occupied:
                nxt += 1
            if nxt >= total:
                break
            cur = nxt
        return starts

    def _paginate(self) -> List[Page]:
        pg = self.cfg.page
        pitch = self.pitch
        if not self.elements:
            return [Page(0, [])]
        total = self.k
        starts = self._starts(total, pg.lines_per_page)
        ends = starts[1:] + [total]
        pages = [Page(i, []) for i in range(len(starts))]
        for el in self.elements:
            if isinstance(el, (Glyph, Deco, HRule, Dot, Tri)):
                p = max(bisect_right(starts, el.k) - 1, 0)
                dy = pg.margin_top - starts[p] * pitch
                pages[p].elements.append(replace(el, y=el.y + dy))
                continue
            y0, y1 = el.y0, el.y1
            for p, (s, e) in enumerate(zip(starts, ends)):
                ys, ye = s * pitch, e * pitch
                if y1 <= ys + 0.3 * pitch or y0 >= ye:
                    continue
                a = max(y0, ys)
                b = y1 if y1 <= ye + 0.3 * pitch else ye
                if b - a < 0.6 * pitch:
                    continue
                dy = pg.margin_top - ys
                pages[p].elements.append(replace(el, y0=a + dy, y1=b + dy))
        return pages


def layout(blocks, cfg: Config, fonts) -> List[Page]:
    return Layouter(cfg, fonts).run(blocks)
