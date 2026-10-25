"""Stage 3: drawing elements -> an ink layer.

The ink layer is stored as per-pen coverage maps (0..1).  Converting it to a
transmittance image (1 = no ink) lets the paper stage multiply it onto the
sheet, which is how real ink behaves: it darkens the paper instead of covering
its texture.

Glyphs come from fonts, but no glyph is ever drawn twice the same way: every
instance gets its own affine jitter, a (small) elastic displacement field that
bends the strokes, a stroke-weight change and a pressure texture.  Lines get a
wavy, tilted baseline.  Decorations (underlines, braces, rules, the quote
triangle) are drawn as hand-wobbled variable-width strokes with random tilt and
overshoot at the ends, at 4x resolution and then downsampled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .config import Config
from .elements import Brace, Deco, Dot, Glyph, HRule, Page, Tri, VBar

BASELINE_SHIFT = -0.05  # em; lifts glyphs so their bottoms sit on the ruled line


# ------------------------------------------------------------------ ink layer

class Ink:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.layers: Dict[str, np.ndarray] = {}

    def layer(self, pen: str) -> np.ndarray:
        if pen not in self.layers:
            self.layers[pen] = np.zeros((self.h, self.w), np.float32)
        return self.layers[pen]

    def stamp(self, pen: str, mask: np.ndarray, x0: int, y0: int, gain: float = 1.0) -> None:
        h, w = mask.shape
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(self.w, x0 + w), min(self.h, y0 + h)
        if xa >= xb or ya >= yb:
            return
        m = mask[ya - y0 : yb - y0, xa - x0 : xb - x0] * gain
        sl = self.layer(pen)[ya:yb, xa:xb]
        sl += m - sl * m  # union of coverages

    def transmittance(self, colors: Dict[str, Tuple[int, int, int]]) -> np.ndarray:
        t = np.ones((self.h, self.w, 3), np.float32)
        for pen, cov in self.layers.items():
            c = np.asarray(colors[pen], np.float32) / 255.0
            t *= 1.0 - cov[..., None] * (1.0 - c)[None, None, :]
        return t


# ------------------------------------------------------------------ helpers

def smooth1d(rng, n: int, corr: float) -> np.ndarray:
    """Unit-variance smooth noise of length n with correlation length `corr`."""
    corr = max(float(corr), 1e-3)
    pad = int(corr * 3) + 1
    w = rng.standard_normal(n + 2 * pad)
    k = np.exp(-0.5 * (np.arange(-pad, pad + 1) / corr) ** 2)
    k /= k.sum()
    s = np.convolve(w, k, mode="same")[pad : pad + n]
    sd = s.std()
    return s / sd if sd > 1e-6 else s


def bezier(p0, p1, p2, p3, n: int = 14) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3


def brace_points(x: float, y0: float, y1: float, w: float, rv: float, dens: float = 5.0,
                 tip: float = 0.5) -> np.ndarray:
    """Outline of a left curly brace "{": tip at (x, y0 + tip * height), arms reach x + w."""
    xr, xm = x + w, x + 0.5 * w
    ym = y0 + tip * (y1 - y0)
    k = 0.5523
    P = lambda a, b: np.array([a, b], float)  # noqa: E731

    def line(a, b):
        n = max(2, int(np.hypot(*(b - a)) / dens))
        return np.linspace(a, b, n)

    parts = [
        bezier(P(xr, y0), P(xr - k * (xr - xm), y0), P(xm, y0 + rv - k * rv), P(xm, y0 + rv)),
        line(P(xm, y0 + rv), P(xm, ym - rv)),
        bezier(P(xm, ym - rv), P(xm, ym - rv + k * rv), P(x + k * (xm - x), ym), P(x, ym)),
        bezier(P(x, ym), P(x + k * (xm - x), ym), P(xm, ym + rv - k * rv), P(xm, ym + rv)),
        line(P(xm, ym + rv), P(xm, y1 - rv)),
        bezier(P(xm, y1 - rv), P(xm, y1 - rv + k * rv), P(xr - k * (xr - xm), y1), P(xr, y1)),
    ]
    pts = np.concatenate(parts)
    keep = np.r_[True, np.hypot(*np.diff(pts, axis=0).T) > 1e-6]
    return pts[keep]


@dataclass
class LineParams:
    x_ref: float
    slope: float
    a1: float
    l1: float
    p1: float
    a2: float
    l2: float
    p2: float
    gain: float

    def offset(self, x):
        d = np.asarray(x, np.float64) - self.x_ref
        return (
            self.slope * d
            + self.a1 * np.sin(2 * np.pi * d / self.l1 + self.p1)
            + self.a2 * np.sin(2 * np.pi * d / self.l2 + self.p2)
        )


# ------------------------------------------------------------------ renderer

class PageRenderer:
    def __init__(self, cfg: Config, fonts, rng: np.random.Generator):
        self.cfg = cfg
        self.fonts = fonts
        self.rng = rng
        self._lines: Dict[int, LineParams] = {}
        self._base: Dict[tuple, Optional[tuple]] = {}
        self._grids: Dict[tuple, tuple] = {}

    # -------------------------------------------------------------- driver
    def render(self, page: Page, width: int, height: int) -> Ink:
        ink = Ink(width, height)
        for el in page.elements:
            if isinstance(el, Glyph):
                self._glyph(ink, el)
            elif isinstance(el, Deco):
                self._deco(ink, el)
            elif isinstance(el, Brace):
                self._brace(ink, el)
            elif isinstance(el, Tri):
                self._tri(ink, el)
            elif isinstance(el, VBar):
                self._vbar(ink, el)
            elif isinstance(el, HRule):
                self._hrule(ink, el)
            elif isinstance(el, Dot):
                self._dot(ink, el)
        return ink

    # -------------------------------------------------------------- lines
    def _line(self, lid: int, x_ref: float, size: float) -> LineParams:
        lp = self._lines.get(lid)
        if lp is None:
            t, r = self.cfg.text, self.rng
            lp = LineParams(
                x_ref=x_ref,
                slope=math.tan(math.radians(r.normal(0, t.line_slope_deg))),
                a1=t.baseline_wave * size * r.uniform(0.5, 1.0),
                l1=r.uniform(6, 12) * size,
                p1=r.uniform(0, 2 * math.pi),
                a2=t.baseline_wave * size * r.uniform(0.2, 0.5),
                l2=r.uniform(2.5, 5) * size,
                p2=r.uniform(0, 2 * math.pi),
                gain=float(np.clip(1.0 - abs(r.normal(0, t.line_gain_var)), 0.7, 1.0)),
            )
            self._lines[lid] = lp
        return lp

    # -------------------------------------------------------------- glyphs
    def _base_glyph(self, ch: str, idx: int, s2: int):
        key = (ch, idx, s2)
        if key in self._base:
            return self._base[key]
        font = self.fonts.font(idx, s2)
        l, t, r, b = font.getbbox(ch, anchor="ls")
        if r <= l or b <= t:
            self._base[key] = None
            return None
        pad = int(0.30 * s2) + 6
        ox, oy = pad - l, pad - t
        ox += ox % 2
        oy += oy % 2
        w, h = ox + r + pad, oy + b + pad
        w += w % 2
        h += h % 2
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).text((ox, oy), ch, font=font, fill=255, anchor="ls")
        res = (np.asarray(img, np.float32) / 255.0, ox, oy)
        self._base[key] = res
        return res

    def _grid(self, h: int, w: int):
        g = self._grids.get((h, w))
        if g is None:
            g = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
            self._grids[(h, w)] = g
        return g

    def _glyph_mask(self, ch: str, idx: int, size: float, fx: float, fy: float):
        s2 = max(8, int(round(size * 2)))
        base = self._base_glyph(ch, idx, s2)
        if base is None:
            return None
        arr, ox, oy = base
        h2, w2 = arr.shape
        t, rng = self.cfg.text, self.rng

        # affine jitter about the middle of the em box, plus the sub-pixel shift
        adv2 = self.fonts.advance(ch, size) * 2
        cx, cy = ox + 0.5 * adv2, oy - 0.36 * s2
        ang = math.radians(float(np.clip(rng.normal(0, t.rotate_deg / 2), -t.rotate_deg, t.rotate_deg)))
        sx = 1 + float(np.clip(rng.normal(0, t.scale_jitter / 2), -t.scale_jitter, t.scale_jitter))
        sy = 1 + float(np.clip(rng.normal(0, t.scale_jitter / 2), -t.scale_jitter, t.scale_jitter))
        sh = float(np.clip(rng.normal(0, t.shear_jitter / 2), -t.shear_jitter, t.shear_jitter))
        ca, sa = math.cos(ang), math.sin(ang)
        lin = np.array([[ca, -sa], [sa, ca]]) @ np.array([[1, sh], [0, 1]]) @ np.diag([sx, sy])
        c = np.array([cx, cy])
        tr = c - lin @ c + np.array([2 * fx, 2 * fy])
        m = cv2.warpAffine(
            arr, np.hstack([lin, tr[:, None]]).astype(np.float32), (w2, h2),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        )

        # smooth elastic displacement: strokes bend a little, differently every time
        amp = t.warp_amp * s2
        if amp > 0.05:
            sig = max(2.0, t.warp_sigma * s2)
            nx = cv2.GaussianBlur(rng.standard_normal((h2, w2)).astype(np.float32), (0, 0), sig)
            ny = cv2.GaussianBlur(rng.standard_normal((h2, w2)).astype(np.float32), (0, 0), sig)
            nx /= nx.std() + 1e-6
            ny /= ny.std() + 1e-6
            gx, gy = self._grid(h2, w2)
            m = cv2.remap(m, gx + nx * amp, gy + ny * amp, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)

        # stroke weight: blur then re-threshold with a random bias
        m = cv2.GaussianBlur(m, (0, 0), 0.8)
        bias = float(np.clip(rng.normal(0, t.thickness_jitter / 2), -t.thickness_jitter, t.thickness_jitter))
        m = np.clip((m - (0.42 - bias)) * 2.6, 0.0, 1.0)

        # pressure: slow density variation across the glyph
        if t.pressure_var > 0:
            p = cv2.GaussianBlur(rng.standard_normal((h2, w2)).astype(np.float32), (0, 0), 0.12 * s2)
            p /= p.std() + 1e-6
            m *= 1.0 - t.pressure_var * (0.5 + 0.5 * np.tanh(p))

        m1 = cv2.resize(m, (w2 // 2, h2 // 2), interpolation=cv2.INTER_AREA)
        return m1, ox // 2, oy // 2

    def _glyph(self, ink: Ink, g: Glyph) -> None:
        t, r = self.cfg.text, self.rng
        lp = self._line(g.line_id, g.x, g.size)
        x = g.x + r.normal(0, t.pos_jitter * g.size)
        y = g.y + float(lp.offset(g.x)) + r.normal(0, 0.4 * t.pos_jitter * g.size) + BASELINE_SHIFT * g.size
        ix, iy = math.floor(x), math.floor(y)
        res = self._glyph_mask(g.ch, g.font, g.size, x - ix, y - iy)
        if res is None:
            return
        mask, ox, oy = res
        ink.stamp(g.pen, mask, ix - ox, iy - oy, lp.gain)

    # -------------------------------------------------------------- strokes
    def _stroke(self, ink: Ink, pen: str, pts, widths, gain: float = 1.0, ss: int = 4) -> None:
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        widths = np.broadcast_to(np.asarray(widths, np.float32), (len(pts),))
        pad = float(widths.max()) / 2 + 2
        x0, y0 = int(math.floor(pts[:, 0].min() - pad)), int(math.floor(pts[:, 1].min() - pad))
        x1, y1 = int(math.ceil(pts[:, 0].max() + pad)), int(math.ceil(pts[:, 1].max() + pad))
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0 or w * h * ss * ss > 6e7:
            return
        cvs = np.zeros((h * ss, w * ss), np.uint8)
        q = np.rint((pts - np.array([x0, y0], np.float32)) * ss).astype(np.int32)
        th = np.maximum(1, np.rint(widths * ss)).astype(int)
        for i in range(len(q)):
            cv2.circle(cvs, (int(q[i, 0]), int(q[i, 1])), int(th[i] // 2), 255, -1, cv2.LINE_AA)
            if i + 1 < len(q):
                cv2.line(cvs, (int(q[i, 0]), int(q[i, 1])), (int(q[i + 1, 0]), int(q[i + 1, 1])),
                         255, int(round((th[i] + th[i + 1]) / 2)), cv2.LINE_AA)
        m = cv2.resize(cvs, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        ink.stamp(pen, m, x0, y0, gain)

    def _fill(self, ink: Ink, pen: str, poly, gain: float = 1.0, ss: int = 4) -> None:
        poly = np.asarray(poly, np.float32).reshape(-1, 2)
        x0, y0 = int(math.floor(poly[:, 0].min())) - 2, int(math.floor(poly[:, 1].min())) - 2
        x1, y1 = int(math.ceil(poly[:, 0].max())) + 2, int(math.ceil(poly[:, 1].max())) + 2
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        cvs = np.zeros((h * ss, w * ss), np.uint8)
        q = np.rint((poly - np.array([x0, y0], np.float32)) * ss).astype(np.int32)
        cv2.fillPoly(cvs, [q], 255, cv2.LINE_AA)
        m = cv2.resize(cvs, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        ink.stamp(pen, m * 0.92, x0, y0, gain)

    def _hand_line(self, p0, p1, size: float, wob: float = 1.0, step: float = 5.0,
                   os_scale: float = 1.0) -> np.ndarray:
        """A straight stroke as a hand draws it: slightly tilted, overshooting at
        both ends by a random amount, bowed once and wavy along its length.
        All amounts scale with `size` (the font size around the stroke) and are
        switched off by line_tilt_deg / line_overshoot / line_wobble = 0."""
        t, r = self.cfg.text, self.rng
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = p1 - p0
        L = float(np.hypot(*d))
        if L < 1e-6:
            return np.array([p0, p1])
        if t.line_tilt_deg > 0:
            ang = math.radians(float(np.clip(r.normal(0, t.line_tilt_deg / 2), -t.line_tilt_deg, t.line_tilt_deg)))
            c, s = math.cos(ang), math.sin(ang)
            mid, hv = (p0 + p1) / 2, d / 2
            hv = np.array([c * hv[0] - s * hv[1], s * hv[0] + c * hv[1]])
            p0, p1 = mid - hv, mid + hv
        u = (p1 - p0) / L
        if t.line_overshoot > 0:
            os = t.line_overshoot * size * os_scale
            p0 = p0 - u * r.uniform(0, os)
            p1 = p1 + u * r.uniform(0, os)
            L = float(np.hypot(*(p1 - p0)))
        n = max(3, int(L / step) + 1)
        s = np.linspace(0.0, 1.0, n)
        pts = p0 + s[:, None] * (p1 - p0)
        amp = t.line_wobble * size * wob
        if amp > 0:
            nrm = np.array([-u[1], u[0]])
            off = (smooth1d(r, n, max(2.0, n / 4)) * 0.6 + float(r.choice([-1.0, 1.0])) * 0.8 * np.sin(np.pi * s)) * amp
            pts = pts + off[:, None] * nrm
        return pts

    def _taper(self, n: int, widths):
        s = np.linspace(0.0, 1.0, n)
        edge = np.minimum(1.0, np.minimum(s, 1.0 - s) / 0.10)
        return np.asarray(widths) * (0.70 + 0.30 * edge)

    def _gain(self) -> float:
        """Ink density of one drawn stroke; varies by up to line_gain_var."""
        return 1.0 - float(self.rng.uniform(0.0, self.cfg.text.line_gain_var))

    def _pen_width(self, size: float, k: Optional[float] = None) -> float:
        return max(1.7, (self.cfg.text.line_width if k is None else k) * size)

    def _deco(self, ink: Ink, d: Deco) -> None:
        r = self.rng
        lp = self._line(d.line_id, d.x0, d.size)
        w = self._pen_width(d.size)
        offs = {"strike": [-0.32], "single": [0.17], "double": [0.15, 0.33]}[d.kind]
        for j, off in enumerate(offs):
            xa = d.x0 + (r.uniform(0, 0.2 * self.cfg.text.line_overshoot) * d.size if j else 0.0)
            xb = d.x1 - (r.uniform(0, 0.2 * self.cfg.text.line_overshoot) * d.size if j else 0.0)
            yb = d.y + off * d.size
            pts = self._hand_line((xa, yb), (xb, yb), d.size)
            pts[:, 1] += lp.offset(pts[:, 0]) + r.normal(0, 6.0 * self.cfg.text.line_wobble)
            ws = np.maximum(1.2, w * (1.0 + 1.6 * self.cfg.text.thickness_jitter * smooth1d(r, len(pts), 4)))
            self._stroke(ink, d.pen, pts, self._taper(len(pts), ws), gain=lp.gain)

    def _brace(self, ink: Ink, b: Brace) -> None:
        t, r = self.cfg.text, self.rng
        tip = float(np.clip(t.brace_tip, 0.1, 0.9))
        h = b.y1 - b.y0
        w = float(np.clip(0.30 * b.size + 0.035 * h, 0.35 * b.size, 0.85 * b.size)) * (1.0 + 2.0 * t.line_wobble * r.uniform(-1, 1))
        rv = max(2.0, min(0.9 * w, tip * h / 2 - 1, (1 - tip) * h / 2 - 1))
        pts = brace_points(b.x, b.y0, b.y1, w, rv, tip=tip)
        n = len(pts)
        amp = t.line_wobble * b.size
        if amp > 0:
            pts = pts + np.c_[smooth1d(r, n, 8), smooth1d(r, n, 8)] * (0.8 * amp)
        if t.line_tilt_deg > 0:
            ang = math.radians(float(np.clip(r.normal(0, t.line_tilt_deg / 2), -t.line_tilt_deg, t.line_tilt_deg)))
            c, s = math.cos(ang), math.sin(ang)
            ctr = np.array([b.x + 0.5 * w, 0.5 * (b.y0 + b.y1)])
            pts = (pts - ctr) @ np.array([[c, s], [-s, c]]) + ctr
        tip_y = b.y0 + tip * h
        bell = np.exp(-(((pts[:, 1] - tip_y) / max(h / 2, 1.0)) ** 2) * 2.0)
        ws = self._pen_width(b.size, t.line_width * 1.06) * (0.85 + 0.30 * bell)
        self._stroke(ink, b.pen, pts, self._taper(n, ws), gain=self._gain())

    def _vbar(self, ink: Ink, v: VBar) -> None:
        base = self.cfg.page.pitch * self.cfg.text.size_ratio
        pts = self._hand_line((v.x, v.y0), (v.x, v.y1), base)
        ws = self._taper(len(pts), self._pen_width(base) * (1.0 + 1.3 * self.cfg.text.thickness_jitter * smooth1d(self.rng, len(pts), 5)))
        self._stroke(ink, v.pen, pts, ws, gain=self._gain())

    def _hrule(self, ink: Ink, h: HRule) -> None:
        base = self.cfg.page.pitch * self.cfg.text.size_ratio
        pts = self._hand_line((h.x0, h.y), (h.x1, h.y), base, step=8.0)
        ws = self._taper(len(pts), self._pen_width(base) * (1.0 + 1.3 * self.cfg.text.thickness_jitter * smooth1d(self.rng, len(pts), 5)))
        self._stroke(ink, h.pen, pts, ws, gain=self._gain())

    def _tri(self, ink: Ink, g: Tri) -> None:
        """Right-pointing triangle in three pen strokes whose ends miss or overshoot."""
        r = self.rng
        lp = self._line(-1 - g.k, g.x, g.size)
        s = g.size
        w, hgt = 0.56 * s, 0.64 * s
        cx, cy = g.x, g.y - 0.40 * s + float(lp.offset(g.x))
        v = np.array([[cx, cy - hgt / 2], [cx + w, cy], [cx, cy + hgt / 2]])
        v = v + r.normal(0, 0.5 * self.cfg.text.line_wobble * s, v.shape)
        order = [(0, 1), (1, 2), (2, 0)]
        if g.filled:
            self._fill(ink, g.pen, v, gain=self._gain())
        pw = self._pen_width(s)
        for a, b in order:
            pts = self._hand_line(v[a], v[b], s, wob=0.5, step=3.0, os_scale=0.12)
            self._stroke(ink, g.pen, pts, self._taper(len(pts), pw * (1.0 + self.cfg.text.thickness_jitter * r.uniform(-1, 1))),
                         gain=self._gain())

    def _dot(self, ink: Ink, d: Dot) -> None:
        self._stroke(ink, d.pen, [(d.x, d.y)], [2 * d.r])


def render_page(page: Page, cfg: Config, fonts, rng: np.random.Generator) -> Ink:
    return PageRenderer(cfg, fonts, rng).render(page, cfg.page.width, cfg.page.height)
