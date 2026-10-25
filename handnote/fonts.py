"""Font handling: discovery, glyph coverage, advances, and a downloader.

The pipeline draws characters from one or more handwriting-style fonts.  The
first font is primary; later ones only fill gaps (characters the earlier fonts
do not contain).  Coverage is read from each font's cmap with fontTools, so a
missing glyph is never drawn as a tofu box.
"""
from __future__ import annotations

import unicodedata
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import ImageFont

FONT_EXTS = {".ttf", ".otf", ".ttc"}

# Characters that CJK typography sets in a full em box.
_WIDE_EXTRA = set("“”‘’—…·")


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x2E80 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0xFF00 <= cp <= 0xFFEF
        or 0x3000 <= cp <= 0x303F
        or 0xFE30 <= cp <= 0xFE4F
        or 0x20000 <= cp <= 0x2FFFF
        or ch in _WIDE_EXTRA
    )


class FontError(RuntimeError):
    pass


class FontSet:
    """Ordered list of fonts with coverage lookup and cached PIL fonts.

    ``paths`` is the body chain: the first font is primary, later ones only fill
    gaps.  ``heading`` and ``code`` optionally name separate fonts for those
    roles; a role font that lacks a glyph falls back to the body chain.
    """

    def __init__(self, paths: Sequence["str | Path"], heading: "str | Path | None" = None,
                 code: "str | Path | None" = None, punct: "str | Path | None" = None,
                 latin: "str | Path | None" = None):
        self.paths: List[Path] = [Path(p) for p in paths]
        if not self.paths:
            raise FontError(no_font_message())
        self._n_body = len(self.paths)
        self.roles: Dict[str, int] = {}
        for role, extra in (("heading", heading), ("code", code), ("punct", punct), ("latin", latin)):
            if not extra:
                continue
            p = Path(extra)
            if p not in self.paths:
                self.paths.append(p)
            self.roles[role] = self.paths.index(p)
        for p in self.paths:
            if not p.is_file():
                raise FontError(f"font file not found: {p}")
        self._cmaps = [_read_cmap(p) for p in self.paths]
        self._fonts: Dict[Tuple[int, int], ImageFont.FreeTypeFont] = {}
        self._ratio: Dict[Tuple[int, str], float] = {}
        self._ink: Dict[Tuple[int, str], Optional[Tuple[float, float]]] = {}

    def pick(self, ch: str, role: str = "body") -> int:
        """Index of the font that draws `ch` in this role, or -1."""
        cp = ord(ch)
        ri = self.roles.get(role)
        if ri is not None and cp in self._cmaps[ri]:
            return ri
        li = self.roles.get("latin")
        if li is not None and role in ("body", "heading", "code") and ch.isascii() and not ch.isspace() and cp in self._cmaps[li]:
            return li  # letters, digits and ASCII punctuation can come from a different font than the characters
        pi = self.roles.get("punct")
        if pi is not None and role in ("body", "heading") and is_cjk(ch) and unicodedata.category(ch).startswith("P") \
                and cp in self._cmaps[pi]:
            return pi  # full-width punctuation can come from a different font than the characters
        for i in range(self._n_body):
            if cp in self._cmaps[i]:
                return i
        return -1

    def font(self, idx: int, size: int) -> ImageFont.FreeTypeFont:
        key = (idx, int(size))
        f = self._fonts.get(key)
        if f is None:
            f = ImageFont.truetype(str(self.paths[idx]), int(size))
            self._fonts[key] = f
        return f

    def ink_extent(self, ch: str, role: str = "body") -> Optional[Tuple[float, float]]:
        """Left and right edge of what the glyph really draws, in em, measured from its origin
        (not the advance width the font declares).  None if the glyph draws nothing."""
        idx = self.pick(ch, role)
        if idx < 0:
            return None
        key = (idx, ch)
        if key not in self._ink:
            l, t, r, b = self.font(idx, 200).getbbox(ch, anchor="ls")
            self._ink[key] = (l / 200.0, r / 200.0) if r > l and b > t else None
        return self._ink[key]

    def advance(self, ch: str, size: float, role: str = "body") -> float:
        if ch == " ":
            return size * 0.3
        if is_cjk(ch):
            return size
        idx = self.pick(ch, role)
        if idx < 0:
            return size * 0.5
        key = (idx, ch)
        r = self._ratio.get(key)
        if r is None:
            r = self.font(idx, 100).getlength(ch) / 100.0
            self._ratio[key] = r
        return r * size


def _read_cmap(path: Path) -> set:
    from fontTools.ttLib import TTFont

    f = TTFont(str(path), lazy=True, fontNumber=0)
    try:
        return set((f.getBestCmap() or {}).keys())
    finally:
        f.close()


# --------------------------------------------------------------- discovery

_PREFERRED = ("longcang", "lxgw", "mashanzheng", "liujian", "zhimang")


def package_font_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fonts"


def font_search_dirs(extra_dir: str = "") -> List[Path]:
    dirs = []
    if extra_dir:
        dirs.append(Path(extra_dir).expanduser())
    dirs += [Path.cwd() / "fonts", package_font_dir(), Path.home() / ".local" / "share" / "handnote" / "fonts"]
    return dirs


def list_font_files(dirs: Sequence[Path]) -> List[Path]:
    found: List[Path] = []
    seen = set()
    for d in dirs:
        if d.is_dir():
            for p in sorted(p for p in d.iterdir() if p.suffix.lower() in FONT_EXTS):
                if p.resolve() not in seen:  # cwd/fonts and the package fonts/ are often the same directory
                    seen.add(p.resolve())
                    found.append(p)
    return found


def discover_fonts(extra_dir: str = "") -> List[Path]:
    """Fonts of the first search directory that has any, best-liked first."""
    found: List[Path] = []
    for d in font_search_dirs(extra_dir):
        found = list_font_files([d])
        if found:
            break

    def rank(p: Path) -> Tuple[int, str]:
        name = p.name.lower()
        for i, key in enumerate(_PREFERRED):
            if key in name:
                return (i, name)
        return (len(_PREFERRED), name)

    return sorted(found, key=rank)


def resolve_font(spec: "str | Path", font_dir: str = "") -> Path:
    """A font given as a path, or as part of a file name found in the font directories."""
    p = Path(spec).expanduser()
    if p.is_file():
        return p
    key = str(spec).lower().replace("-", "").replace("_", "").replace(" ", "")
    for cand in list_font_files(font_search_dirs(font_dir)):
        if key and key in cand.stem.lower().replace("-", "").replace("_", "").replace(" ", ""):
            return cand
    raise FontError(f"font not found: {spec} (not a file, and no font in {', '.join(map(str, font_search_dirs(font_dir)))} matches)")


def load_fontset(font_paths: Iterable[str] = (), font_dir: str = "", heading: str = "", code: str = "",
                 punct: str = "", latin: str = "") -> FontSet:
    paths = [resolve_font(p, font_dir) for p in font_paths]
    punct_path = resolve_font(punct, font_dir) if punct else None
    latin_path = resolve_font(latin, font_dir) if latin else None
    if not paths:
        paths = discover_fonts(font_dir)
        # Long Cang's punctuation, letters and digits are tiny: when nothing was chosen by hand, borrow Wenkai's
        if paths and "longcang" in paths[0].name.lower():
            lxgw = next((p for p in paths if "lxgw" in p.name.lower()), None)
            punct_path = punct_path or lxgw
            latin_path = latin_path or lxgw
    return FontSet(
        paths,
        resolve_font(heading, font_dir) if heading else None,
        resolve_font(code, font_dir) if code else None,
        punct_path,
        latin_path,
    )


def no_font_message() -> str:
    return (
        "No handwriting font found. Put .ttf/.otf files in ./fonts, pass --font PATH, "
        "or run `handnote fonts` to download open-licensed ones."
    )


# --------------------------------------------------------------- downloader

# All entries are SIL Open Font License 1.1.  Check each licence before you
# redistribute generated output together with a font file.
FONT_CATALOG = {
    "lxgw-wenkai": (
        "https://github.com/lxgw/LxgwWenKai/releases/latest/download/LXGWWenKai-Regular.ttf",
        "LXGWWenKai-Regular.ttf",
        "霞鹜文楷 (OFL-1.1), neat regular-script hand",
    ),
    "long-cang": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/longcang/LongCang-Regular.ttf",
        "LongCang-Regular.ttf",
        "龙藏体 (OFL-1.1), fast pen hand",
    ),
    "ma-shan-zheng": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/mashanzheng/MaShanZheng-Regular.ttf",
        "MaShanZheng-Regular.ttf",
        "马善政毛笔楷书 (OFL-1.1), brush",
    ),
    "zhi-mang-xing": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/ZhiMangXing-Regular.ttf",
        "ZhiMangXing-Regular.ttf",
        "志莽行书 (OFL-1.1), cursive",
    ),
    "liu-jian-mao-cao": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/liujianmaocao/LiuJianMaoCao-Regular.ttf",
        "LiuJianMaoCao-Regular.ttf",
        "刘建毛草 (OFL-1.1), grass script",
    ),
}


def download_fonts(names: Sequence[str], dest: Optional[Path] = None, log=print) -> List[Path]:
    dest = Path(dest) if dest else Path.cwd() / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        if name not in FONT_CATALOG:
            raise FontError(f"unknown font {name!r}; choose from {', '.join(FONT_CATALOG)}")
        url, fname, desc = FONT_CATALOG[name]
        target = dest / fname
        if target.exists() and target.stat().st_size > 0:
            log(f"= {fname} already present")
            out.append(target)
            continue
        log(f"- downloading {fname}  [{desc}]")
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        tmp.replace(target)
        out.append(target)
    return out
