"""Stage 5: make the flat sheet look like a phone photo of paper on a desk.

Order of effects (each one is a separate function and every one can be turned
off from the config by setting its amount to 0):
  1. sheet shape: a gentle undulation, every edge bowed by a bounded random
     amount (never ruler straight, never wavy), a corner lifting toward or away
     from the camera, and sometimes a small folded corner
  2. the sheet placed on a desk, with a soft drop shadow and a paper rim, then
     the whole picture (sheet and desk together) seen by a tilted phone camera;
     optionally a pile of more sheets peeks out from under the sheet
  3. lighting gradient and vignette
  4. a cast shadow of the phone / a window frame
  5. white balance drift, tone curve
  6. lens softness, sensor noise (signal dependent, slightly blurred)
JPEG compression is applied by the caller when saving.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .config import PhotoConfig


def _lowfreq(rng, h: int, w: int, cells: int) -> np.ndarray:
    n = rng.standard_normal((max(2, cells), max(2, int(cells * w / h)))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    return n / (n.std() + 1e-6)


# ------------------------------------------------------------------ 1. sheet shape

def _corner_points(w: int, h: int):
    return [(0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0)]


def dog_ear(col: np.ndarray, alpha: np.ndarray, cfg: PhotoConfig, rng):
    """Fold one corner over: the corner triangle disappears, the back of the
    paper (plain, a little darker) shows as a flap, and the flap shades the sheet."""
    h, w = alpha.shape
    ci = int(rng.integers(0, 4))
    C = np.array(_corner_points(w, h)[ci])
    sx = 1.0 if C[0] < 1 else -1.0
    sy = 1.0 if C[1] < 1 else -1.0
    L = rng.uniform(cfg.dog_ear_min, max(cfg.dog_ear_min, cfg.dog_ear_max)) * w
    A = C + np.array([sx * L * rng.uniform(0.85, 1.15), 0.0])
    B = C + np.array([0.0, sy * L * rng.uniform(0.85, 1.15)])
    ab = (B - A) / (np.hypot(*(B - A)) + 1e-6)
    d = C - A
    Cr = C - 2.0 * (d - ab * float(d @ ab))  # C reflected over the fold line AB

    def mask(poly, blur=0.0):
        m = np.zeros((h, w), np.uint8)
        cv2.fillPoly(m, [np.rint(np.asarray(poly)).astype(np.int32)], 255, cv2.LINE_AA)
        m = m.astype(np.float32) / 255.0
        return cv2.GaussianBlur(m, (0, 0), blur) if blur > 0 else m

    cut = mask([C + (C - A) * 0.2 + (C - B) * 0.2, A + (A - C) * 0.0, B])  # corner triangle (slightly enlarged outward)
    cut = np.maximum(cut, mask([C, A, B]))
    flap = mask([A, B, Cr])
    back = np.median(col.reshape(-1, 3)[:: max(1, col.size // 30000)], axis=0) * rng.uniform(0.88, 0.94)
    # shading: the flap is lighter near the fold's far corner
    gyy, gxx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.abs((gxx - A[0]) * ab[1] - (gyy - A[1]) * ab[0])  # distance to the fold line
    shade = 1.0 + 0.09 * np.clip(dist / (0.7 * L), 0, 1)
    flap_col = back[None, None, :] * shade[..., None]
    sh = cv2.GaussianBlur(flap, (0, 0), max(1.5, 0.035 * L))
    sh = cv2.warpAffine(sh, np.float32([[1, 0, -sx * 0.02 * L], [0, 1, -sy * 0.02 * L]]), (w, h))
    col = col * (1.0 - 0.30 * sh * (1.0 - flap))[..., None]  # shadow of the flap on the sheet
    col = col * (1.0 - cut)[..., None]
    alpha = alpha * (1.0 - cut)
    col = col * (1.0 - flap)[..., None] + flap_col * flap[..., None]
    alpha = np.maximum(alpha, flap)
    crease = np.zeros((h, w), np.uint8)  # the fold itself: a thin dark line with a light edge beside it
    cv2.line(crease, tuple(np.rint(A).astype(int)), tuple(np.rint(B).astype(int)), 255, 2, cv2.LINE_AA)
    crease = cv2.GaussianBlur(crease.astype(np.float32) / 255.0, (0, 0), 0.9)
    lit = cv2.warpAffine(crease, np.float32([[1, 0, sx * 1.5], [0, 1, sy * 1.5]]), (w, h))
    col = col * (1.0 - 0.28 * crease)[..., None] + 0.05 * lit[..., None] * (alpha > 0.5)[..., None]
    return col, alpha


def bend(flat: np.ndarray, cfg: PhotoConfig, rng):
    """Returns (premultiplied colour, alpha) of the deformed sheet."""
    h, w = flat.shape[:2]
    short = float(min(h, w))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = xx / (w - 1), yy / (h - 1)
    dx = np.zeros((h, w), np.float32)
    dy = np.zeros((h, w), np.float32)
    shade = np.ones((h, w), np.float32)

    if cfg.bend > 0:  # very smooth overall undulation (2 cells: at most one hump per direction)
        dx += _lowfreq(rng, h, w, 2) * cfg.bend * short
        dy += _lowfreq(rng, h, w, 2) * cfg.bend * short

    if cfg.edge_bow_max > 0:  # every edge bows by a bounded random amount, sign random
        lo, hi = sorted((max(0.0, cfg.edge_bow_min), cfg.edge_bow_max))

        def amount():
            return float(rng.choice([-1.0, 1.0]) * rng.uniform(lo, hi) * short)

        hump_x, hump_y = 4 * xn * (1 - xn), 4 * yn * (1 - yn)
        dy += amount() * hump_x * (1 - yn) ** 2  # top edge
        dy += amount() * hump_x * yn**2  # bottom edge
        dx += amount() * hump_y * (1 - xn) ** 2  # left edge
        dx += amount() * hump_y * xn**2  # right edge

    if cfg.corner_lift > 0 and rng.random() < cfg.corner_lift_prob:
        n_lift = 1 + int(rng.random() < 0.25)
        for ci in rng.choice(4, size=n_lift, replace=False):
            cx, cy = _corner_points(w, h)[int(ci)]
            vx, vy = (w / 2 - cx), (h / 2 - cy)
            vn = float(np.hypot(vx, vy))
            vx, vy = vx / vn, vy / vn  # unit vector from the corner toward the page centre
            sign = float(rng.choice([-1.0, 1.0]))  # +1 toward the camera, -1 away
            amp = cfg.corner_lift * w * rng.uniform(0.6, 1.0)
            R = rng.uniform(0.25, 0.40) * short
            g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / R**2))
            dx += sign * vx * amp * g  # toward: the corner appears pushed outward (source is further in)
            dy += sign * vy * amp * g
            shade *= 1.0 + sign * 0.045 * g  # brighter when tilted to the light, darker when away

    if cfg.bend > 0 or cfg.edge_bow_max > 0:
        shade *= np.clip(1.0 + 2.0 * np.gradient(dy, axis=0), 0.90, 1.08)
    src = flat * shade[..., None]
    alpha0 = np.ones((h, w), np.float32)
    if cfg.dog_ear_prob > 0 and rng.random() < cfg.dog_ear_prob:
        src, alpha0 = dog_ear(src, alpha0, cfg, rng)
    kw = dict(interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    col = cv2.remap(src, xx + dx, yy + dy, **kw)
    alpha = cv2.remap(alpha0, xx + dx, yy + dy, **kw)
    return col, alpha


# ------------------------------------------------------------------ 2. desk

def desk(oh: int, ow: int, cfg: PhotoConfig, rng) -> np.ndarray:
    base = np.asarray(cfg.desk_color, np.float32) / 255.0
    streak = cv2.resize(rng.standard_normal((oh // 3 + 2, 5)).astype(np.float32), (ow, oh),
                        interpolation=cv2.INTER_CUBIC)
    streak /= streak.std() + 1e-6
    fine = cv2.GaussianBlur(rng.standard_normal((oh, ow)).astype(np.float32), (0, 0), 1.0)
    fine /= fine.std() + 1e-6
    tex = 1 + cfg.desk_texture * (0.10 * _lowfreq(rng, oh, ow, 3) + 0.04 * _lowfreq(rng, oh, ow, 14)
                                  + 0.05 * streak + 0.03 * fine)
    return np.clip(base * tex[..., None], 0, 1)


def tilt_direction_angle(cfg: PhotoConfig, rng) -> float:
    """Direction (radians, clockwise from the top of the picture) of the side that is farther from the camera."""
    names = {"top": 0.0, "right": 90.0, "bottom": 180.0, "left": 270.0}
    d = str(cfg.tilt_direction).strip().lower()
    if d == "random":
        base = float(rng.uniform(0, 360))
    elif d in names:
        base = names[d]
    else:
        try:
            base = float(d)
        except ValueError:
            raise ValueError(f"photo.tilt_direction must be top|bottom|left|right|random or a number of degrees, got {d!r}") from None
    j = max(0.0, cfg.tilt_direction_jitter)
    return math.radians(base + (float(rng.uniform(-j, j)) if j > 0 else 0.0))


def tilt_matrix(width: int, height: int, tilt_deg: float, direction: float, focal: float) -> np.ndarray:
    """3x3 homography (about the picture centre) of a camera turned by ``tilt_deg`` so that it looks toward
    ``direction``: that side of the picture goes farther away, so it shrinks, like the top of a sheet when the
    top of the phone is tipped up."""
    f = max(0.05, focal) * math.hypot(width, height)
    th = math.radians(tilt_deg)
    u = np.array([math.sin(direction), -math.cos(direction)])  # image x right, y down
    t = np.array([u[0] * math.sin(th), u[1] * math.sin(th), math.cos(th)])
    k = np.cross([0.0, 0.0, 1.0], t)
    k = k / (np.linalg.norm(k) + 1e-12)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    rot = np.eye(3) + math.sin(th) * kx + (1 - math.cos(th)) * kx @ kx  # takes the optical axis to t
    kk = np.diag([f, f, 1.0])
    return kk @ rot.T @ np.linalg.inv(kk)


def _stack_directions():
    return {"top-left": (-1.0, -1.0), "top": (0.0, -1.0), "top-right": (1.0, -1.0), "left": (-1.0, 0.0),
            "right": (1.0, 0.0), "bottom-left": (-1.0, 1.0), "bottom": (0.0, 1.0), "bottom-right": (1.0, 1.0)}


def paper_stack(d: np.ndarray, paper_rgb: np.ndarray, corners: np.ndarray, cfg: PhotoConfig, rng) -> np.ndarray:
    """Draw ``stack_count`` more sheets onto the desk image ``d``, under the sheet whose corners are given.

    Each lower sheet is shifted a little further toward one side (with a random sideways drift and its own small
    rotation), so the edges of the pile peek out unevenly; every sheet casts a soft shadow on the one below."""
    bh, bw = d.shape[:2]
    dirs = _stack_directions()
    name = str(cfg.stack_direction).strip().lower()
    if name == "random":
        name = str(rng.choice(list(dirs)))
    if name not in dirs:
        raise ValueError(f"photo.stack_direction must be random or one of {', '.join(dirs)}, got {name!r}")
    v = np.asarray(dirs[name], np.float64)
    v = v / np.linalg.norm(v)
    side = np.array([-v[1], v[0]])
    page_w = float(np.ptp(corners[:, 0]))
    ctr = corners.mean(axis=0)
    out = d
    for i in range(int(cfg.stack_count), 0, -1):  # lowest sheet first
        step = cfg.stack_offset * page_w
        shift = v * step * i * rng.uniform(0.7, 1.3) + side * step * rng.normal(0, 0.6)
        th = math.radians(float(rng.normal(0, cfg.stack_rotation)))
        c, s = math.cos(th), math.sin(th)
        quad = (corners - ctr) @ np.array([[c, -s], [s, c]]).T + ctr + shift
        quad += rng.normal(0, 0.0015 * page_w, quad.shape)  # corners never quite square
        m = np.zeros((bh, bw), np.uint8)
        cv2.fillPoly(m, [np.rint(quad * 4).astype(np.int32)], 255, cv2.LINE_AA, shift=2)
        a = cv2.GaussianBlur(m.astype(np.float32) / 255.0, (0, 0), 0.8)
        sh = cv2.GaussianBlur(a, (0, 0), 0.006 * page_w)
        sh = cv2.warpAffine(sh, np.float32([[1, 0, 0.002 * page_w], [0, 1, 0.003 * page_w]]), (bw, bh))
        out = out * (1 - 0.35 * sh)[..., None]
        tone = paper_rgb * (0.97 - 0.012 * i + rng.normal(0, 0.006))
        edge = a - cv2.erode(a, np.ones((5, 5), np.uint8))
        sheet = tone[None, None, :] * (1 - 0.35 * cv2.GaussianBlur(edge, (0, 0), 1.2))[..., None]
        out = out * (1 - a[..., None]) + sheet * a[..., None]
    return out


def place_on_desk(col, alpha, cfg: PhotoConfig, rng):
    h, w = alpha.shape
    pad = int(cfg.pad * max(h, w))
    oh, ow = h + 2 * pad, w + 2 * pad  # the picture that comes out
    tilt = 0.0
    if cfg.tilt_max > 0:
        lo, hi = sorted((max(0.0, cfg.tilt_min), cfg.tilt_max))
        tilt = float(rng.uniform(lo, hi))
    m = int(0.30 * max(oh, ow)) if tilt > 0 else 0  # extra desk all round, so the tilt never shows an empty corner
    bh, bw = oh + 2 * m, ow + 2 * m
    o = pad + m
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[o, o], [o + w, o], [o + w, o + h], [o, o + h]])
    dst += rng.uniform(-1, 1, (4, 2)).astype(np.float32) * cfg.perspective * w
    th = math.radians(float(rng.normal(0, cfg.rotation)))
    c, s = math.cos(th), math.sin(th)
    ctr = np.float32([bw / 2, bh / 2])
    dst = (dst - ctr) @ np.float32([[c, -s], [s, c]]).T + ctr
    mtx = cv2.getPerspectiveTransform(src, dst)
    kw = dict(flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    prem = cv2.warpPerspective(col, mtx, (bw, bh), **kw)
    a = cv2.warpPerspective(alpha, mtx, (bw, bh), **kw)

    d = desk(bh, bw, cfg, rng)
    if cfg.stack_count > 0:
        solid = alpha > 0.99
        paper_rgb = np.median(col[solid][:: max(1, int(solid.sum()) // 20000)], axis=0)
        d = paper_stack(d, paper_rgb, cv2.perspectiveTransform(src[None].astype(np.float64), mtx.astype(np.float64))[0], cfg, rng)
    if cfg.paper_shadow > 0:
        sh = cv2.GaussianBlur(a, (0, 0), 0.012 * max(oh, ow))
        sh = cv2.warpAffine(sh, np.float32([[1, 0, 0.005 * ow], [0, 1, 0.009 * ow]]), (bw, bh))
        d *= (1 - cfg.paper_shadow * sh)[..., None]
    rim = cv2.GaussianBlur(a - cv2.erode(a, np.ones((5, 5), np.uint8)), (0, 0), 2.0)
    img = d * (1 - a[..., None]) + prem * (1 - 0.18 * rim[..., None])
    if tilt > 0:  # the camera sees the paper and the desk together, so the desk is distorted as well
        direction = tilt_direction_angle(cfg, rng)
        mt = tilt_matrix(ow, oh, tilt, direction, cfg.focal_length)
        to_c = np.array([[1, 0, -bw / 2], [0, 1, -bh / 2], [0, 0, 1.0]])
        full = mt @ to_c
        corners = cv2.perspectiveTransform(dst[None].astype(np.float64), full)[0]  # where the sheet ends up after the tilt
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        # keep the sheet framed as it was: centre it and fit it into the same margin, whatever the tilt did to it
        k = min((ow - 2 * pad) / max(x1 - x0, 1.0), (oh - 2 * pad) / max(y1 - y0, 1.0))
        fit = np.array([[k, 0, ow / 2 - k * (x0 + x1) / 2], [0, k, oh / 2 - k * (y0 + y1) / 2], [0, 0, 1.0]])
        img = cv2.warpPerspective(img.astype(np.float32), fit @ full, (ow, oh), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REFLECT)
    return img


# ------------------------------------------------------------------ 3/4. light

def _rounded_rect(cx, cy, rw, rh, rad, ang_deg, n=10):
    pts = []
    for ccx, ccy, a0 in [(rw / 2 - rad, -rh / 2 + rad, -90), (rw / 2 - rad, rh / 2 - rad, 0),
                         (-rw / 2 + rad, rh / 2 - rad, 90), (-rw / 2 + rad, -rh / 2 + rad, 180)]:
        for a in np.linspace(a0, a0 + 90, n):
            pts.append((ccx + rad * math.cos(math.radians(a)), ccy + rad * math.sin(math.radians(a))))
    pts = np.asarray(pts)
    t = math.radians(ang_deg)
    rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    return pts @ rot.T + np.array([cx, cy])


SHADOW_POSITIONS = {"top-left": (0.0, 0.0), "top": (0.5, 0.0), "top-right": (1.0, 0.0), "left": (0.0, 0.5),
                    "right": (1.0, 0.5), "bottom-left": (0.0, 1.0), "bottom": (0.5, 1.0), "bottom-right": (1.0, 1.0)}


def shadow_mask(oh: int, ow: int, kind: str, rng, position: str = "random") -> np.ndarray:
    """Soft 0..1 mask of a cast shadow.  'phone' = a rounded slab over one
    corner/edge (the phone and the hand holding it); 'window' = diagonal bands."""
    s = 4
    h, w = oh // s, ow // s
    m = np.zeros((h, w), np.uint8)
    position = str(position).strip().lower()
    if position != "random" and position not in SHADOW_POSITIONS:
        raise ValueError(f"photo.shadow_position must be random or one of {', '.join(SHADOW_POSITIONS)}, got {position!r}")
    if kind == "random":
        kind = "phone" if position != "random" else str(rng.choice(["phone", "window"]))
    if kind == "phone":
        rw, rh = rng.uniform(0.38, 0.62) * w, rng.uniform(0.30, 0.55) * h
        if position == "random":
            fx, fy = (0.0 if rng.random() < 0.5 else 1.0), (0.0 if rng.random() < 0.5 else 1.0)
        else:
            fx, fy = SHADOW_POSITIONS[position]
        cx = fx * w + rng.uniform(-0.12, 0.12) * w
        cy = fy * h + rng.uniform(-0.12, 0.12) * h
        poly = _rounded_rect(cx, cy, rw, rh, 0.10 * min(rw, rh), float(rng.uniform(-18, 18)))
        cv2.fillPoly(m, [np.rint(poly).astype(np.int32)], 255)
        sigma = rng.uniform(0.018, 0.045) * w
    elif kind == "window":
        phi = math.radians(float(rng.uniform(25, 65)) * float(rng.choice([-1, 1])))
        d = np.array([math.cos(phi), math.sin(phi)])
        for _ in range(int(rng.integers(1, 3))):
            c = np.array([rng.uniform(0.1, 0.9) * w, rng.uniform(0.1, 0.9) * h])
            p0, p1 = c - d * 2 * (w + h), c + d * 2 * (w + h)
            cv2.line(m, tuple(np.rint(p0).astype(int)), tuple(np.rint(p1).astype(int)), 255,
                     int(rng.uniform(0.07, 0.16) * w))
        sigma = rng.uniform(0.02, 0.05) * w
    else:
        return np.zeros((oh, ow), np.float32)
    m = cv2.GaussianBlur(m.astype(np.float32) / 255.0, (0, 0), max(sigma, 1.0))
    return cv2.resize(m, (ow, oh), interpolation=cv2.INTER_LINEAR)


def lighting(img: np.ndarray, cfg: PhotoConfig, rng) -> np.ndarray:
    oh, ow = img.shape[:2]
    yy, xx = np.mgrid[0:oh, 0:ow].astype(np.float32)
    xn, yn = xx / ow * 2 - 1, yy / oh * 2 - 1
    th = float(rng.uniform(0, 2 * math.pi))
    grad = 1.0 + cfg.light_gradient * 0.5 * (xn * math.cos(th) + yn * math.sin(th))
    vig = 1.0 - cfg.vignette * 0.5 * (xn**2 + yn**2)
    out = img * (grad * vig)[..., None]
    if cfg.shadow != "none" and cfg.shadow_strength > 0:
        out *= (1.0 - cfg.shadow_strength * shadow_mask(oh, ow, cfg.shadow, rng, cfg.shadow_position))[..., None]
    return out


# ------------------------------------------------------------------ 5/6. camera

def camera(img: np.ndarray, cfg: PhotoConfig, rng) -> np.ndarray:
    oh, ow = img.shape[:2]
    gains = 1.0 + rng.normal(0, cfg.color_cast / 2, 3)
    warm = float(rng.normal(0, cfg.color_cast))
    gains = gains * np.array([1 + warm, 1.0, 1 - warm])
    img = img * gains.astype(np.float32)[None, None, :] * 0.97
    img = np.clip(img, 0, 1) ** float(1.0 + rng.uniform(-cfg.tone_var, cfg.tone_var))

    if cfg.blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), cfg.blur)
        if cfg.sharpen > 0:
            img = np.clip(img + cfg.sharpen * (img - cv2.GaussianBlur(img, (0, 0), 1.6)), 0, 1)

    if cfg.noise > 0:
        sd = cfg.noise / 255.0
        lum = rng.standard_normal((oh, ow, 1)).astype(np.float32)
        chroma = rng.standard_normal((oh, ow, 3)).astype(np.float32) * 0.6
        n = cv2.GaussianBlur(lum + chroma, (0, 0), 0.6)
        img = img + n * sd * (0.5 + 0.5 * np.sqrt(np.clip(img, 0, 1))) * 1.6
    return np.clip(img, 0, 1)


# ------------------------------------------------------------------ entry point

def shoot(flat: np.ndarray, cfg: PhotoConfig, rng: np.random.Generator) -> np.ndarray:
    """flat: float32 RGB 0..1 sheet -> uint8 RGB photo."""
    col, alpha = bend(flat, cfg, rng)
    img = place_on_desk(col, alpha, cfg, rng)
    img = lighting(img, cfg, rng)
    img = camera(img, cfg, rng)
    return (img * 255.0 + 0.5).astype(np.uint8)
