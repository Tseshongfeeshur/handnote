"""Stage 4: paper background and composition with the ink layer.

The sheet is either generated (ruled / blank / grid, with grain and a slow tint)
or loaded from a paper image given by a template.  Random stains can be added to
either.  Printed rules are drawn on the same grid the text baselines snap to.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from .config import PageConfig, PaperConfig


def _lowfreq(rng, h: int, w: int, cells: int) -> np.ndarray:
    n = rng.standard_normal((max(2, cells), max(2, int(cells * w / h)))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    return n / (n.std() + 1e-6)


@lru_cache(maxsize=4)
def _load_image(path: str, w: int, h: int, fit: str) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    iw, ih = im.size
    if fit == "stretch":
        im = im.resize((w, h), Image.LANCZOS)
    elif fit == "cover":
        sc = max(w / iw, h / ih)
        nw, nh = max(w, round(iw * sc)), max(h, round(ih * sc))
        im = im.resize((nw, nh), Image.LANCZOS)
        l, t = (nw - w) // 2, (nh - h) // 2
        im = im.crop((l, t, l + w, t + h))
    else:
        raise ValueError(f"unknown paper.image_fit {fit!r} (use 'cover' or 'stretch')")
    return np.asarray(im, np.float32) / 255.0


def make_paper(page: PageConfig, cfg: PaperConfig, rng: np.random.Generator) -> np.ndarray:
    """Return a float32 RGB sheet in 0..1, with grain, optional rules and stains."""
    h, w = page.height, page.width
    if cfg.image:
        img = _load_image(cfg.image, w, h, cfg.image_fit).copy()  # a real paper already has its own texture
    else:
        img = np.empty((h, w, 3), np.float32)
        img[:] = np.asarray(cfg.color, np.float32) / 255.0
        if cfg.tint_var > 0:
            img *= (1.0 + cfg.tint_var * _lowfreq(rng, h, w, 4))[..., None]
        if cfg.grain > 0:
            g = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 0.8)
            g /= g.std() + 1e-6
            fib = cv2.resize(cv2.GaussianBlur(rng.standard_normal((h // 2, w // 2)).astype(np.float32), (0, 0), 1.2),
                             (w, h), interpolation=cv2.INTER_LINEAR)
            fib /= fib.std() + 1e-6
            img *= (1.0 + cfg.grain * (0.7 * g + 0.5 * fib))[..., None]

    if cfg.kind in ("ruled", "grid"):
        _rules(img, page, cfg, rng, grid=cfg.kind == "grid")
    elif cfg.kind != "blank":
        raise ValueError(f"unknown paper kind {cfg.kind!r} (use 'ruled', 'blank' or 'grid')")
    if cfg.margin_line:
        _margin_line(img, page, cfg)
    if cfg.stain_count > 0 and cfg.stain_strength > 0:
        _stains(img, cfg, rng)
    return np.clip(img, 0.0, 1.0)


def _rules(img: np.ndarray, page: PageConfig, cfg: PaperConfig, rng, grid: bool) -> None:
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    y = page.margin_top % page.pitch  # same grid the text snaps to
    while y < h:
        if 0.03 * h < y < 0.97 * h:
            cv2.line(mask, (0, int(y)), (w - 1, int(y)), 255, int(cfg.line_width), cv2.LINE_AA)
        y += page.pitch
    if grid:
        x = page.margin_left % page.pitch
        while x < w:
            if 0.03 * w < x < 0.97 * w:
                cv2.line(mask, (int(x), 0), (int(x), h - 1), 255, int(cfg.line_width), cv2.LINE_AA)
            x += page.pitch
    alpha = (mask.astype(np.float32) / 255.0) * (0.78 + cfg.line_var * _lowfreq(rng, h, w, 30))
    alpha = np.clip(alpha, 0.0, 1.0)[..., None]
    img[:] = img * (1 - alpha) + (np.asarray(cfg.line_color, np.float32) / 255.0) * alpha


def _margin_line(img: np.ndarray, page: PageConfig, cfg: PaperConfig) -> None:
    h, w = img.shape[:2]
    x = max(2, page.margin_left - 30)
    m2 = np.zeros((h, w), np.uint8)
    cv2.line(m2, (x, 0), (x, h - 1), 255, int(cfg.line_width), cv2.LINE_AA)
    a2 = (m2.astype(np.float32) / 255.0 * 0.7)[..., None]
    img[:] = img * (1 - a2) + np.array([205, 110, 110], np.float32) / 255.0 * a2


def _stains(img: np.ndarray, cfg: PaperConfig, rng) -> None:
    """A few small irregular blots with a darker rim, like a drop of tea."""
    h, w = img.shape[:2]
    tint = np.asarray(cfg.stain_color, np.float32) / 255.0
    for _ in range(int(rng.integers(0, cfg.stain_count + 1))):
        diam = rng.uniform(cfg.stain_min, max(cfg.stain_min, cfg.stain_max)) * w
        r = max(3.0, diam / 2)
        cx, cy = rng.uniform(0.05, 0.95) * w, rng.uniform(0.05, 0.95) * h
        half = int(r * 2.0) + 2
        x0, y0 = int(cx) - half, int(cy) - half
        xa, ya, xb, yb = max(0, x0), max(0, y0), min(w, x0 + 2 * half), min(h, y0 + 2 * half)
        if xa >= xb or ya >= yb:
            continue
        yy, xx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
        dx, dy = xx - cx, yy - cy
        th = rng.uniform(0, np.pi)  # rotate and squash into an ellipse
        u = dx * np.cos(th) + dy * np.sin(th)
        v = (-dx * np.sin(th) + dy * np.cos(th)) / rng.uniform(0.6, 1.0)
        ang = np.arctan2(v, u)
        wob = sum(rng.uniform(0.03, 0.14) / k * np.cos(k * ang + rng.uniform(0, 6.28)) for k in (1, 2, 3, 4, 6))
        dist = np.hypot(u, v) / (r * (1.0 + wob))
        body = np.clip((1.0 - dist) / 0.15, 0.0, 1.0)
        rim = np.exp(-(((dist - 0.97) / 0.07) ** 2))
        a = cfg.stain_strength * (0.40 * body + 0.95 * rim) * float(rng.uniform(0.7, 1.1))
        patch = img[ya:yb, xa:xb]
        patch *= 1.0 - a[..., None] * (1.0 - tint)[None, None, :]


def compose(paper: np.ndarray, transmittance: np.ndarray) -> np.ndarray:
    """Multiply ink onto paper (ink absorbs light, paper texture shows through)."""
    return np.clip(paper * transmittance, 0.0, 1.0)
