"""The five-stage workflow, wired together.

    parse -> layout -> render ink -> compose on paper -> photo effects

`run_pipeline` is a generator that yields one `PageResult` per page, so large
documents never hold more than one page of float images in memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np

from . import parser
from .config import Config
from .fonts import FontSet, load_fontset
from .layout import layout
from .paper import compose, make_paper
from .photo import shoot
from .render import render_page


@dataclass
class PageResult:
    index: int
    flat: np.ndarray  # uint8 RGB: paper + ink, no photo effects
    photo: Optional[np.ndarray]  # uint8 RGB, None if photo effects are disabled
    ink: Optional[np.ndarray] = None  # float32 transmittance, only if keep_ink


def _to_u8(a: np.ndarray) -> np.ndarray:
    return (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def run_pipeline(
    markdown: str,
    cfg: Optional[Config] = None,
    fonts: Optional[FontSet] = None,
    seed: Optional[int] = None,
    keep_ink: bool = False,
) -> Iterator[PageResult]:
    cfg = cfg or Config()
    fonts = fonts or load_fontset(cfg.text.fonts, cfg.text.font_dir, cfg.text.heading_font, cfg.text.code_font,
                                  cfg.text.punct_font, cfg.text.latin_font)
    blocks = parser.parse(markdown, cfg.text.table_mode, cfg.text.script_marks)
    pages = layout(blocks, cfg, fonts)

    root = np.random.SeedSequence(seed if seed is not None else cfg.seed)
    for page, child in zip(pages, root.spawn(len(pages))):
        r_ink, r_paper, r_photo = (np.random.default_rng(s) for s in child.spawn(3))
        ink = render_page(page, cfg, fonts, r_ink)
        trans = ink.transmittance(cfg.pen_colors())
        flat = compose(make_paper(cfg.page, cfg.paper, r_paper), trans)
        photo = shoot(flat, cfg.photo, r_photo) if cfg.photo.enabled else None
        yield PageResult(page.index, _to_u8(flat), photo, trans if keep_ink else None)
