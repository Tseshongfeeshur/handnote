"""Command line interface.

    handnote render notes.md -o out/                 # run the whole workflow -> out/notes/1.jpg, 2.jpg, ...
    handnote write                                   # ask for a topic, have the local model write the note, render it
    handnote slides lecture.pdf                      # lecture slides (a PDF, or a folder of PDFs) -> notes -> pictures
    handnote notes.md --paper blank --seed 7         # `render` is the default command
    handnote notes.md --set photo.noise=0 --set text.warp_amp=0.02
    handnote fonts                                   # download open-licensed fonts
    handnote preview                                 # compare the fonts you have
    handnote template scan.jpg -o my-paper.toml      # make a paper template from an image
    handnote config                                  # print every option and its value
    handnote init-config                             # write a full, annotated config file that is then read automatically
    handnote lint notes/x.md                         # check a note before rendering it
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import Config, config_candidates, find_config, user_config_path
from .writer import LlmError
from .fonts import (FONT_CATALOG, FontError, discover_fonts, download_fonts, font_search_dirs, list_font_files,
                    load_fontset, resolve_font)

COMMANDS = ("render", "write", "slides", "fonts", "preview", "template", "config", "init-config", "lint")


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", help="TOML config file (default: the first of $HANDNOTE_CONFIG, ./handnote.toml, "
                                          "the per-user config file; see `handnote config --path`)")
    p.add_argument("--no-config", action="store_true", help="do not read any config file, use the built-in defaults")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override any option, e.g. --set photo.noise=0 --set text.ink=\"blue\" (repeatable)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="handnote", description="Markdown notes -> photos of handwritten notes")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render a Markdown file")
    r.add_argument("input", help="Markdown file, or - for stdin")
    r.add_argument("-o", "--out", default="out",
                   help="output directory (pages go to <out>/<note name>/1.jpg, 2.jpg, ...), or a file name for a single page")
    _add_config_args(r)
    r.add_argument("--paper", help="ruled | blank | grid | a paper template .toml | a paper image")
    r.add_argument("--font", action="append", default=[], help="body font file or part of its name (repeat for fallbacks)")
    r.add_argument("--heading-font", help="separate font for headings")
    r.add_argument("--code-font", help="separate font for code")
    r.add_argument("--punct-font", help="separate font for full-width punctuation")
    r.add_argument("--latin-font", help="separate font for letters, digits and ASCII symbols")
    r.add_argument("--font-dir", help="directory to look for fonts in")
    r.add_argument("--ink", help="main pen colour: black | blue | blue-black | red | green")
    r.add_argument("--shadow", choices=["random", "phone", "window", "none"], help="cast shadow shape")
    r.add_argument("--seed", type=int, help="random seed (same seed, same output)")
    r.add_argument("--no-photo", action="store_true", help="stop after paper composition (flat scan)")
    r.add_argument("--keep-stages", action="store_true", help="also save flat and ink-layer images")
    r.add_argument("--format", choices=["jpg", "png"], default="jpg")

    w = sub.add_parser("write", help="ask for a topic and sub-headings, have the local model write the note, then render it")
    _add_config_args(w)
    w.add_argument("--topic", help="note topic (asked for if left out)")
    w.add_argument("--section", action="append", help="a sub-heading, optionally 'title：key points' (repeatable)")
    w.add_argument("--note", help="extra requirements for the model (empty string for none)")
    w.add_argument("--name", help="file name of the note (default: made from the topic)")
    w.add_argument("-o", "--out", default="out", help="output directory (pages go to <out>/<note name>/1.jpg, ...)")
    w.add_argument("--no-render", action="store_true", help="only write the note, do not make pictures")
    w.add_argument("--paper", help="ruled | blank | grid | a paper template .toml | a paper image")
    w.add_argument("--ink", help="main pen colour: black | blue | blue-black | red | green")
    w.add_argument("--seed", type=int, help="random seed")
    w.add_argument("--no-photo", action="store_true", help="stop after paper composition (flat scan)")
    w.add_argument("--format", choices=["jpg", "png"], default="jpg")

    sl = sub.add_parser("slides", help="write class notes from lecture slides: a PDF, or a folder of PDFs, one note each")
    _add_config_args(sl)
    sl.add_argument("input", help="a PDF file, or a directory with PDF files")
    sl.add_argument("-r", "--recursive", action="store_true", help="also take the PDFs in sub-directories")
    sl.add_argument("--note", default="", help="extra requirements for the model, e.g. 偏重公式推导")
    sl.add_argument("--skip-existing", action="store_true", help="skip a PDF whose note file already exists (to resume a batch)")
    sl.add_argument("-o", "--out", default="out", help="output directory (pages go to <out>/<PDF name>/1.jpg, ...)")
    sl.add_argument("--no-render", action="store_true", help="only write the notes, do not make pictures")
    sl.add_argument("--paper", help="ruled | blank | grid | a paper template .toml | a paper image")
    sl.add_argument("--ink", help="main pen colour: black | blue | blue-black | red | green")
    sl.add_argument("--seed", type=int, help="random seed")
    sl.add_argument("--no-photo", action="store_true", help="stop after paper composition (flat scan)")
    sl.add_argument("--format", choices=["jpg", "png"], default="jpg")

    f = sub.add_parser("fonts", help="download open-licensed handwriting fonts into ./fonts")
    f.add_argument("names", nargs="*", help=f"any of: {', '.join(FONT_CATALOG)} (default: lxgw-wenkai)")
    f.add_argument("--dest", help="target directory (default ./fonts)")
    f.add_argument("--list", action="store_true", help="list the download catalog and exit")
    f.add_argument("--local", action="store_true", help="list the fonts found on this machine and exit")

    v = sub.add_parser("preview", help="render a sample with every font you have, side by side")
    _add_config_args(v)
    v.add_argument("--font", action="append", default=[], help="fonts to compare (default: all found)")
    v.add_argument("--font-dir", help="directory to look for fonts in")
    v.add_argument("--text", help="sample Markdown to render")
    v.add_argument("-o", "--out", default="fonts-preview.png")

    t = sub.add_parser("template", help="make a paper template from a photo or scan of a sheet")
    t.add_argument("image")
    t.add_argument("-o", "--out", help="template file to write (default: <image>.toml)")

    li = sub.add_parser("lint", help="check a Markdown note for things that render badly (exit 1 if there are errors)")
    li.add_argument("input", help="Markdown file, or - for stdin")
    li.add_argument("--strict", action="store_true", help="treat warnings as errors too")
    _add_config_args(li)

    g = sub.add_parser("config", help="print every option with its value as TOML")
    _add_config_args(g)
    g.add_argument("--annotated", action="store_true", help="add the description and candidate values above every option")
    g.add_argument("--path", action="store_true", help="show which config file would be read, and where files are looked for")

    ic = sub.add_parser("init-config", help="write a full annotated config file (default: the per-user one, read automatically)")
    ic.add_argument("-o", "--out", help=f"where to write it (default: {user_config_path()}); "
                                        "use ./handnote.toml for a per-project config")
    ic.add_argument("--commented", action="store_true",
                    help="write every option commented out, so only what you uncomment overrides the defaults")
    ic.add_argument("--force", action="store_true", help="overwrite an existing file")
    return p


# ----------------------------------------------------------------- helpers

def _config_from(a, announce: bool = False) -> Config:
    """-c FILE, else the first config file found automatically (unless --no-config), plus --set overrides."""
    src: Optional[Path] = None
    if a.config:
        cfg, src = Config.load(a.config), Path(a.config)
    elif getattr(a, "no_config", False):
        cfg = Config()
    else:
        cfg, src = Config.load_default()
    if announce and src is not None and not a.config:
        print(f"handnote: using config {src}  (--no-config to ignore it)", file=sys.stderr)
    for item in getattr(a, "set", []) or []:
        cfg.set(item)
    return cfg


def _warn_missing(md: str, fonts) -> None:
    missing = sorted({c for c in md if c.isprintable() and not c.isspace() and fonts.pick(c) < 0})
    if missing:
        shown = "".join(missing[:30]) + ("…" if len(missing) > 30 else "")
        print(f"handnote: warning: {len(missing)} character(s) not in any font and skipped: {shown}\n"
              f"          add a fallback font with --font PATH (repeatable)", file=sys.stderr)


def _save(arr, path: Path, quality: int) -> None:
    im = Image.fromarray(arr)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        im.save(path, quality=quality, subsampling=2, optimize=True)
    else:
        im.save(path)


# ----------------------------------------------------------------- commands

def _cmd_fonts(a) -> int:
    if a.list:
        for k, (_, fname, desc) in FONT_CATALOG.items():
            print(f"{k:18s} {fname:28s} {desc}")
        return 0
    if a.local:
        files = list_font_files(font_search_dirs())
        for p in files:
            print(p)
        if not files:
            print("no fonts found; run `handnote fonts` or put .ttf/.otf files in ./fonts")
        return 0
    paths = download_fonts(a.names or ["lxgw-wenkai"], Path(a.dest) if a.dest else None)
    print("fonts ready:", ", ".join(str(p) for p in paths))
    return 0


def _cmd_render(a) -> int:
    from .pipeline import run_pipeline

    cfg = _config_from(a, announce=True)
    if a.paper:
        cfg.apply_paper(a.paper)
    if a.font:
        cfg.text.fonts = a.font
    if a.heading_font:
        cfg.text.heading_font = a.heading_font
    if a.code_font:
        cfg.text.code_font = a.code_font
    if a.punct_font:
        cfg.text.punct_font = a.punct_font
    if a.latin_font:
        cfg.text.latin_font = a.latin_font
    if a.font_dir:
        cfg.text.font_dir = a.font_dir
    if a.ink:
        cfg.text.ink = a.ink
    if a.shadow:
        cfg.photo.shadow = a.shadow
    if a.no_photo:
        cfg.photo.enabled = False
    cfg.pen_colors()  # validate colour names early

    if a.input == "-":
        md, stem = sys.stdin.read(), "note"
    else:
        src = Path(a.input)
        md, stem = src.read_text(encoding="utf-8"), src.stem

    for p in render_note(md, stem, cfg, Path(a.out), a.seed, a.format, a.keep_stages):
        print(p)
    return 0


def render_note(md: str, stem: str, cfg: Config, out: Path, seed: Optional[int] = None, fmt: str = "jpg",
                keep_stages: bool = False) -> List[Path]:
    """Render a note to ``<out>/<stem>/1.<fmt>``, ``2.<fmt>``, ... (page numbers).  If ``out`` itself names an image
    file, page 1 goes there and the other pages beside it."""
    from .pipeline import run_pipeline

    fonts = load_fontset(cfg.text.fonts, cfg.text.font_dir, cfg.text.heading_font, cfg.text.code_font,
                         cfg.text.punct_font, cfg.text.latin_font)
    _warn_missing(md, fonts)
    single_file = out.suffix.lower() in (".jpg", ".jpeg", ".png")
    out_dir = out.parent if single_file else out / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower().lstrip(".") if single_file else fmt

    written: List[Path] = []
    for res in run_pipeline(md, cfg, fonts, seed=seed, keep_ink=keep_stages):
        n = res.index + 1
        base = out if single_file and n == 1 else (out_dir / f"{out.stem}-{n}.{ext}" if single_file else out_dir / f"{n}.{ext}")
        final = res.photo if res.photo is not None else res.flat
        _save(final, base, cfg.photo.jpeg_quality)
        written.append(base)
        if keep_stages:
            _save(res.flat, base.with_name(base.stem + ".flat.png"), 95)
            if res.ink is not None:
                _save((res.ink * 255 + 0.5).astype("uint8"), base.with_name(base.stem + ".ink.png"), 95)
    return written


def _cmd_write(a) -> int:
    from .writer import interactive, make_note, note_filename, unique_path

    cfg = _config_from(a, announce=True)
    if a.paper:
        cfg.apply_paper(a.paper)
    if a.ink:
        cfg.text.ink = a.ink
    if a.no_photo:
        cfg.photo.enabled = False
    cfg.pen_colors()
    topic, sections, extra = interactive(a)

    def log(msg: str) -> None:
        print(f"\n[{msg}]", file=sys.stderr)

    print(f"\n向模型请求笔记（{cfg.llm.model}）……\n", file=sys.stderr)
    md, rep = make_note(cfg, topic, sections, extra, log, lambda t: print(t, end="", flush=True, file=sys.stderr))
    print("\n", file=sys.stderr)

    notes_dir = Path(cfg.llm.notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = (notes_dir / f"{a.name}.md") if a.name else unique_path(notes_dir, note_filename(topic))
    path.write_text(md, encoding="utf-8")
    print(f"笔记：{path}")
    print(rep.text())
    if rep.errors:
        print("注意：仍有「必须修改」的问题，渲染结果可能不自然；可以手动改笔记后运行 handnote " + str(path), file=sys.stderr)
    if a.no_render:
        return 0
    for p in render_note(md, path.stem, cfg, Path(a.out), a.seed, a.format):
        print(p)
    return 0


def _cmd_slides(a) -> int:
    from .slides import collect_pdfs, note_from_pdf
    from .writer import note_filename, unique_path

    cfg = _config_from(a, announce=True)
    if a.paper:
        cfg.apply_paper(a.paper)
    if a.ink:
        cfg.text.ink = a.ink
    if a.no_photo:
        cfg.photo.enabled = False
    cfg.pen_colors()
    pdfs = collect_pdfs(Path(a.input), a.recursive)
    notes_dir = Path(cfg.llm.notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(f"\n[{msg}]", file=sys.stderr)

    done, failed = [], []
    for i, pdf in enumerate(pdfs, 1):
        stem = note_filename(pdf.stem)
        print(f"\n===== [{i}/{len(pdfs)}] {pdf} =====", file=sys.stderr)
        if a.skip_existing and (notes_dir / f"{stem}.md").exists():
            print("已有笔记，跳过", file=sys.stderr)
            continue
        try:
            md, rep, n_slides = note_from_pdf(cfg, pdf, a.note, log, lambda t: print(t, end="", flush=True, file=sys.stderr))
            print("\n", file=sys.stderr)
            path = unique_path(notes_dir, stem)
            path.write_text(md, encoding="utf-8")
            print(f"笔记：{path}（课件 {n_slides} 页）")
            print(rep.text())
            if not a.no_render:
                for p in render_note(md, path.stem, cfg, Path(a.out), a.seed, a.format):
                    print(p)
            done.append(pdf)
        except (LlmError, ValueError) as e:
            print(f"\n失败：{pdf.name}：{e}", file=sys.stderr)
            failed.append(pdf)
    if len(pdfs) > 1 or failed:
        print(f"\n完成 {len(done)} 个，失败 {len(failed)} 个" + ("：" + "、".join(p.name for p in failed) if failed else ""), file=sys.stderr)
    return 1 if failed else 0


PREVIEW_MD = "# 手写样张\n\n永远的**重点**与*斜体*，快速的狐狸 jumps 123。\n\n- 要点一：资源分配\n- 要点二：线程调度\n"


def _cmd_preview(a) -> int:
    from .pipeline import run_pipeline

    cfg = _config_from(a)
    cfg.photo.enabled = False
    cfg.paper.kind, cfg.paper.image, cfg.paper.stain_count = "blank", "", 0
    cfg.page.height = 150 + 8 * cfg.page.pitch + 130
    paths = [resolve_font(f, a.font_dir or "") for f in a.font] if a.font else list_font_files(font_search_dirs(a.font_dir or ""))
    if not paths:
        raise FontError("no fonts to preview; run `handnote fonts` first")
    md = a.text or PREVIEW_MD
    label_font = ImageFont.load_default()
    rows = []
    for p in paths:
        fs = load_fontset([str(p)])
        page = next(run_pipeline(md, cfg, fs, seed=1))
        arr = page.flat
        dark = np.where(arr.min(axis=2) < 200)
        if len(dark[0]) == 0:
            continue
        y0, y1 = max(0, dark[0].min() - 20), min(arr.shape[0], dark[0].max() + 20)
        rows.append((p.name, Image.fromarray(arr[y0:y1])))
    width = max(im.width for _, im in rows)
    sheet = Image.new("RGB", (width, sum(im.height + 28 for _, im in rows)), (255, 255, 255))
    d, y = ImageDraw.Draw(sheet), 0
    for name, im in rows:
        d.text((10, y + 8), name, fill=(200, 0, 0), font=label_font)
        sheet.paste(im, (0, y + 28))
        y += im.height + 28
    sheet.save(a.out)
    print(a.out)
    return 0


def _cmd_template(a) -> int:
    from .templates import write_template

    out = Path(a.out) if a.out else Path(a.image).with_suffix(".toml")
    d = write_template(a.image, out)
    if d.ruled:
        print(f"{out}: found {d.n_lines} ruled lines, pitch {d.pitch}px, first baseline grid at margin_top {d.margin_top}")
    else:
        print(f"{out}: no regular ruling found (blank paper?); using default pitch {d.pitch}, margin_top {d.margin_top}")
    print("check the alignment with:  handnote notes.md --paper", out, "--no-photo")
    return 0


def _cmd_lint(a) -> int:
    from .lint import lint

    cfg = _config_from(a)
    md = sys.stdin.read() if a.input == "-" else Path(a.input).read_text(encoding="utf-8")
    rep = lint(md, cfg)
    print(rep.text())
    return 1 if (rep.errors or (a.strict and rep.warnings)) else 0


def _cmd_config(a) -> int:
    if a.path:
        src = None if (a.no_config or a.config) else find_config()
        if a.config:
            print(f"{a.config}  (from -c)")
        elif a.no_config:
            print("(--no-config: no file is read)")
        else:
            print(f"{src}  (in use)" if src else "(no config file found: built-in defaults)")
        print("looked for, in order:")
        for label, p in config_candidates():
            print(f"  {label}: {p}  {'[exists]' if p.is_file() else ''}")
        return 0
    print(_config_from(a).to_toml(annotated=a.annotated), end="")
    return 0


def _cmd_init_config(a) -> int:
    out = Path(a.out).expanduser() if a.out else user_config_path()
    if out.exists() and not a.force:
        raise ValueError(f"{out} already exists; use --force to overwrite it, or `handnote config --annotated` to see the defaults")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(Config().to_toml(annotated=True, commented=a.commented), encoding="utf-8")
    print(out)
    auto = [p for _, p in config_candidates()]
    if not any(Path(p).resolve() == out.resolve() for p in auto):
        print(f"note: this location is not read automatically; use -c {out} or set HANDNOTE_CONFIG={out}", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS + ("-h", "--help"):
        argv.insert(0, "render")  # `handnote notes.md` == `handnote render notes.md`
    args = _build_parser().parse_args(argv)
    handlers = {"render": _cmd_render, "fonts": _cmd_fonts, "preview": _cmd_preview,
                "template": _cmd_template, "config": _cmd_config, "init-config": _cmd_init_config,
                "lint": _cmd_lint, "write": _cmd_write, "slides": _cmd_slides}
    try:
        return handlers[args.cmd](args)
    except (FontError, ValueError, FileNotFoundError, LlmError) as e:
        print(f"handnote: error: {e}", file=sys.stderr)
        return 2


def write_main() -> int:
    """Entry point of the `handnote-write` command: the same as `handnote write ...`."""
    return main(["write"] + sys.argv[1:])


def slides_main() -> int:
    """Entry point of the `handnote-slides` command: the same as `handnote slides ...`."""
    return main(["slides"] + sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
