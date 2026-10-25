"""Paper templates: detect the printed ruling of a paper image and write a template file.

A template is a small TOML file (see examples/templates) that points at a paper
image and says where the text grid lies:

    image = "legal-pad.png"
    [page]
    width = 1654
    height = 2339
    margin_top = 190
    margin_left = 210
    pitch = 62
    [paper]
    kind = "blank"        # the image already has its lines

`detect` finds the ruled lines in a photo or scan of a sheet so that `pitch` and
`margin_top` put the text baselines on them.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from PIL import Image


@dataclass
class Detected:
    width: int
    height: int
    pitch: int
    margin_top: int
    margin_left: int
    n_lines: int
    ruled: bool


def _peaks(profile: np.ndarray, z: float, min_gap: int) -> List[int]:
    sd = profile.std()
    if sd < 1e-6:
        return []
    thr = profile.mean() + z * sd
    idx = [i for i in range(1, len(profile) - 1)
           if profile[i] > thr and profile[i] >= profile[i - 1] and profile[i] >= profile[i + 1]]
    out: List[int] = []
    for i in idx:
        if out and i - out[-1] < min_gap:
            if profile[i] > profile[out[-1]]:
                out[-1] = i
        else:
            out.append(i)
    return out


def detect(image: "str | Path", width: int = 1654) -> Detected:
    im = Image.open(image).convert("L")
    iw, ih = im.size
    height = max(1, round(width * ih / iw))
    g = np.asarray(im.resize((width, height), Image.LANCZOS), np.float32)

    prof = (255.0 - g[:, int(0.10 * width): int(0.95 * width)]).mean(axis=1)
    prof = prof - cv2.GaussianBlur(prof.reshape(-1, 1), (0, 0), 40).ravel()  # remove slow lighting trends
    rows = _peaks(prof, 1.0, 12)

    pitch, margin_top, ruled = 64, 150, False
    scale = 1.0
    if len(rows) >= 4:
        rows_a = np.asarray(rows, float)
        med = float(np.median(np.diff(rows_a)))
        if med >= 20:
            idx = np.round((rows_a - rows_a[0]) / med)
            keep = np.ones(len(rows_a), bool)
            slope, icpt = med, rows_a[0]
            for _ in range(3):  # least squares line through the rules, dropping outliers (header rules, stains)
                if keep.sum() < 4:
                    break
                slope, icpt = np.polyfit(idx[keep], rows_a[keep], 1)
                keep = np.abs(rows_a - (icpt + slope * idx)) < 0.2 * slope
            if keep.sum() >= 4 and slope >= 20 and keep.sum() >= 0.6 * len(rows_a):
                ruled = True
                pitch = int(round(slope))
                scale = pitch / slope  # resize the page so the pitch is a whole number of pixels
                first_row = icpt * scale
                margin_top = int(round(first_row % pitch + pitch * np.ceil((110 - first_row % pitch) / pitch)))
                width, height = int(round(width * scale)), int(round(height * scale))

    margin_left = 170
    band = (255.0 - g[int(0.05 * g.shape[0]): int(0.95 * g.shape[0]), : int(0.4 * g.shape[1])]).mean(axis=0)
    band = band - cv2.GaussianBlur(band.reshape(-1, 1), (0, 0), 30).ravel()
    cols = _peaks(band, 5.0, 10)
    if cols:
        margin_left = int(round((cols[0] + 40) * scale))
    return Detected(width, height, pitch, margin_top, margin_left, len(rows), ruled)


def write_template(image: "str | Path", out: "str | Path", width: int = 1654) -> Detected:
    d = detect(image, width)
    out = Path(out)
    rel = os.path.relpath(Path(image).resolve(), out.resolve().parent)
    text = (
        f"# Paper template written by `handnote template`: edit the numbers freely.\n"
        f"# Check the grid with:  handnote notes.md --paper {out.name} --no-photo --keep-stages\n"
        f"image = {json.dumps(rel)}\n"
        + f"\n[page]\nwidth = {d.width}\nheight = {d.height}\nmargin_top = {d.margin_top}\n"
        f"margin_bottom = 130\nmargin_left = {d.margin_left}\nmargin_right = 100\npitch = {d.pitch}\n"
        f'\n[paper]\nkind = "blank"   # the image already has its lines\n'
    )
    out.write_text(text, encoding="utf-8")
    return d
