from handnote import parser as P
from handnote.config import Config
from handnote.elements import Brace, Deco, Glyph
from handnote.fonts import load_fontset
from handnote.layout import layout
from handnote.pipeline import run_pipeline

FONTS = load_fontset()


def _elements(md, cfg=None):
    cfg = cfg or Config()
    pages = layout(P.parse(md, cfg.text.table_mode), cfg, FONTS)
    return [e for p in pages for e in p.elements]


def _text(els):
    return "".join(e.ch for e in els if isinstance(e, Glyph))


TABLE = "| 算法 | 特点 |\n| --- | --- |\n| FCFS | 简单 |\n| SJF | 最短 |\n"


def test_table_never_leaks_pipes():
    els = _elements(TABLE)
    assert "|" not in _text(els) and "-" not in _text(els)
    assert "算法：FCFS" in _text(els)
    assert any(isinstance(e, Brace) for e in els)  # rows are grouped by a brace


def test_table_skip_mode():
    cfg = Config()
    cfg.text.table_mode = "skip"
    assert _elements(TABLE, cfg) == []


def test_bold_double_italic_single():
    els = _elements("**粗体**和*斜体*")
    kinds = sorted(e.kind for e in els if isinstance(e, Deco))
    assert kinds == ["double", "single"]


def test_unordered_list_gets_one_brace_ordered_does_not():
    assert sum(isinstance(e, Brace) for e in _elements("- 甲\n- 乙\n- 丙")) == 1
    assert sum(isinstance(e, Brace) for e in _elements("1. 甲\n2. 乙\n3. 丙")) == 0


def test_nested_list_nested_braces():
    assert sum(isinstance(e, Brace) for e in _elements("- 甲\n  - 子1\n  - 子2\n- 乙")) == 2


def test_heading_is_larger_than_body():
    els = [e for e in _elements("# 标题\n\n正文") if isinstance(e, Glyph)]
    assert els[0].size > els[-1].size


def test_long_document_paginates():
    md = "\n\n".join(f"第{i}段，" + "内容" * 30 for i in range(40))
    assert len(list(run_pipeline(md, _small(), FONTS, seed=1))) > 1


def _small():
    cfg = Config()
    cfg.photo.enabled = False
    return cfg


def test_same_seed_same_output_and_different_seed_differs():
    import numpy as np

    a = next(run_pipeline("你好，世界", _small(), FONTS, seed=3)).flat
    b = next(run_pipeline("你好，世界", _small(), FONTS, seed=3)).flat
    c = next(run_pipeline("你好，世界", _small(), FONTS, seed=4)).flat
    assert np.array_equal(a, b) and not np.array_equal(a, c)


def test_same_character_is_drawn_differently():
    import numpy as np

    cfg = _small()
    cfg.paper.kind = "blank"
    res = next(run_pipeline("永永永永永永永永", cfg, FONTS, seed=5, keep_ink=True))
    ink = res.ink[..., 0]
    xs = np.where(ink.min(axis=0) < 0.9)[0]
    cell = len(xs) and (xs.max() - xs.min()) // 8
    assert cell > 0
    crops = [ink[:, xs.min() + i * cell : xs.min() + (i + 1) * cell] for i in range(2, 5)]
    assert not np.array_equal(crops[0], crops[1])


def test_empty_and_blank_paper():
    cfg = _small()
    cfg.paper.kind = "blank"
    assert len(list(run_pipeline("", cfg, FONTS, seed=1))) == 1
    assert len(list(run_pipeline("纯文字", cfg, FONTS, seed=1))) == 1


# ---------------------------------------------------------------- round 2

import math
from pathlib import Path

import numpy as np
import pytest

from handnote import photo, templates
from handnote.elements import Tri, VBar
from handnote.layout import NO_START
from handnote.render import brace_points

ROOT = Path(__file__).resolve().parent.parent


def test_brace_tip_sits_at_two_eighths():
    pts = brace_points(100.0, 0.0, 400.0, 30.0, 20.0, tip=0.25)
    tip_y = pts[np.argmin(pts[:, 0]), 1]
    assert abs(tip_y - 100.0) < 3.0  # 2/8 of 400


def test_code_block_has_only_a_left_rule_in_body_ink():
    els = _elements("```\nprint(1)\nprint(2)\n```")
    assert sum(isinstance(e, VBar) for e in els) == 1
    assert {e.pen for e in els if isinstance(e, Glyph)} == {"main"}


def test_quote_is_indented_paragraph_with_triangle():
    cfg = Config()
    els = _elements("> 引用的话\n\n正文", cfg)
    tri = [e for e in els if isinstance(e, Tri)]
    assert len(tri) == 1
    glyphs = [e for e in els if isinstance(e, Glyph)]
    quote_x = min(g.x for g in glyphs if g.ch == "引")
    body_x = min(g.x for g in glyphs if g.ch == "正")
    assert quote_x - body_x == pytest.approx(cfg.text.quote_indent * cfg.page.pitch * cfg.text.size_ratio)
    assert tri[0].x + 1 < quote_x  # the triangle stands in the indent


def test_quote_marker_none():
    cfg = Config()
    cfg.text.quote_marker = "none"
    assert not any(isinstance(e, Tri) for e in _elements("> 引用", cfg))


def test_heading_gap_is_a_parameter():
    def y_of_heading(before):
        cfg = Config()
        cfg.text.heading_gap_before = [before] * 6
        els = _elements("正文\n\n## 标题", cfg)
        return [e for e in els if isinstance(e, Glyph) and e.ch == "标"][0].y

    assert y_of_heading(3) - y_of_heading(0) == pytest.approx(3 * Config().page.pitch)


def test_punctuation_never_starts_a_line():
    for n in range(20, 45):
        els = _elements("甲乙丙丁" * 3 + "字" * n + "。后面还有一些字，" + "字" * 9 + "。")
        lines = {}
        for e in els:
            if isinstance(e, Glyph):
                lines.setdefault(e.line_id, []).append(e)
        for gl in lines.values():
            assert min(gl, key=lambda g: g.x).ch not in NO_START


def test_config_example_matches_defaults_and_roundtrips(tmp_path):
    assert Config.load(ROOT / "examples" / "config.example.toml") == Config()
    assert (ROOT / "examples" / "config.example.toml").read_text(encoding="utf-8") == Config().to_toml(annotated=True)
    p = tmp_path / "c.toml"
    cfg = Config()
    cfg.text.ink, cfg.photo.noise = "blue", 0.0
    p.write_text(cfg.to_toml(), encoding="utf-8")
    assert Config.load(p) == cfg


def test_set_override_and_unknown_key():
    cfg = Config().set("photo.noise=0").set('text.ink="blue"').set("text.heading_gap_before=[2,2,0,0,0,0]")
    assert cfg.photo.noise == 0 and cfg.text.ink == "blue" and cfg.text.heading_gap_before[0] == 2
    with pytest.raises(ValueError):
        Config().set("photo.nosuch=1")


def test_paper_template_toml_sets_image_and_grid():
    cfg = Config().apply_paper(str(ROOT / "examples" / "templates" / "legal-pad.toml"))
    assert cfg.paper.image.endswith("legal-pad.jpg") and cfg.paper.kind == "blank" and cfg.page.pitch == 58
    cfg.photo.enabled = False
    page = next(run_pipeline("你好", cfg, FONTS, seed=1))
    assert page.flat.shape == (cfg.page.height, cfg.page.width, 3)
    assert page.flat[..., 2].mean() < page.flat[..., 0].mean()  # yellow pad, not white


def test_template_detection_finds_pitch_and_grid():
    d = templates.detect(ROOT / "examples" / "templates" / "legal-pad.jpg")
    assert d.ruled and d.pitch == 58 and d.margin_top == 124


def test_bad_paper_spec():
    with pytest.raises(FileNotFoundError):
        Config().apply_paper("no-such-paper.toml")


def test_font_roles_pick_separate_fonts():
    paths = sorted((ROOT / "fonts").glob("*.ttf"))
    if len(paths) < 2:
        pytest.skip("needs two fonts")
    fs = load_fontset([str(paths[0])], heading=str(paths[1]))
    assert fs.pick("永", "heading") == 1 and fs.pick("永", "body") == 0
    cfg = Config()
    cfg.text.heading_font = str(paths[1])
    els = [e for e in _elements_fs("# 永\n\n永", cfg, fs) if isinstance(e, Glyph)]
    assert [e.font for e in els] == [1, 0]


def _elements_fs(md, cfg, fs):
    pages = layout(P.parse(md, cfg.text.table_mode), cfg, fs)
    return [e for p in pages for e in p.elements]


def _top_edge_bow(alpha):
    """How far the middle of the top edge sits from the chord between its two ends (pixels)."""
    h, w = alpha.shape
    row = lambda c: int(np.argmax(alpha[:, c] > 0.5))  # noqa: E731
    return abs(row(w // 2) - 0.5 * (row(int(0.03 * w)) + row(int(0.97 * w))))


def test_sheet_edges_are_neither_ruler_straight_nor_wavy():
    flat = np.full((600, 450, 3), 0.9, np.float32)
    cfg = Config().photo
    cfg.corner_lift = 0.0
    cfg.dog_ear_prob = 0.0
    short = 450
    bows = [_top_edge_bow(photo.bend(flat, cfg, np.random.default_rng(s))[1]) for s in range(40)]
    assert np.median(bows) >= 0.002 * short  # visibly bowed, not a ruler edge
    assert max(bows) <= 0.02 * short  # but never wavy
    cfg.bend = cfg.edge_bow_min = cfg.edge_bow_max = 0.0
    assert _top_edge_bow(photo.bend(flat, cfg, np.random.default_rng(0))[1]) == 0


def test_dog_ear_cuts_a_corner_and_corner_lift_moves_it():
    flat = np.full((600, 450, 3), 0.9, np.float32)
    cfg = Config().photo
    cfg.bend = cfg.edge_bow_max = cfg.edge_bow_min = 0.0
    cfg.corner_lift, cfg.dog_ear_prob = 0.0, 1.0
    _, a = photo.bend(flat, cfg, np.random.default_rng(1))
    corners = [a[:12, :12].mean(), a[:12, -12:].mean(), a[-12:, :12].mean(), a[-12:, -12:].mean()]
    assert min(corners) < 0.6  # one corner is folded away
    cfg.dog_ear_prob, cfg.corner_lift, cfg.corner_lift_prob = 0.0, 0.05, 1.0
    c0, a0 = photo.bend(flat, cfg, np.random.default_rng(2))
    assert not np.allclose(a0, 1.0)  # a corner moved off its place


def test_every_effect_can_be_switched_off():
    cfg = Config()
    p, t, pp = cfg.photo, cfg.text, cfg.paper
    p.bend = p.edge_bow_max = p.corner_lift = p.dog_ear_prob = 0.0
    p.tilt_max = p.perspective = p.rotation = p.paper_shadow = p.desk_texture = p.light_gradient = p.vignette = 0.0
    p.color_cast = p.tone_var = p.blur = p.sharpen = p.noise = 0.0
    p.shadow = "none"
    t.pos_jitter = t.baseline_wave = t.line_slope_deg = t.rotate_deg = t.scale_jitter = t.shear_jitter = 0.0
    t.warp_amp = t.thickness_jitter = t.pressure_var = t.line_gain_var = 0.0
    t.line_wobble = t.line_tilt_deg = t.line_overshoot = 0.0
    pp.stain_count, pp.grain, pp.tint_var, pp.line_var = 0, 0.0, 0.0, 0.0
    t.line_gain_var = 0.0
    page = next(run_pipeline("# 标题\n\n**粗**与*斜*\n\n- 甲\n- 乙\n\n> 引\n\n```\ncode\n```", cfg, FONTS, seed=1))
    assert page.photo is not None and page.photo.std() > 0
    again = next(run_pipeline("# 标题\n\n**粗**与*斜*\n\n- 甲\n- 乙\n\n> 引\n\n```\ncode\n```", cfg, FONTS, seed=9))
    assert np.array_equal(page.photo, again.photo)  # nothing random left


def test_options_doc_is_up_to_date():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_options.py"), "--check"])
    assert r.returncode == 0, "run: python tools/gen_options.py"


def test_punctuation_font_role_and_default_pairing():
    paths = {p.name.split("-")[0].lower(): p for p in (ROOT / "fonts").glob("*.ttf")}
    if "longcang" not in paths or "lxgwwenkai" not in paths:
        pytest.skip("needs LongCang and LXGWWenKai")
    fs = load_fontset()  # automatic choice
    assert "longcang" in fs.paths[0].name.lower()
    assert "lxgw" in fs.paths[fs.pick("，")].name.lower()  # punctuation borrowed from Wenkai
    assert "longcang" in fs.paths[fs.pick("永")].name.lower()
    assert "lxgw" in fs.paths[fs.pick("P")].name.lower() and "lxgw" in fs.paths[fs.pick("3")].name.lower()
    fs2 = load_fontset([str(paths["longcang"])], punct=str(paths["lxgwwenkai"]))
    assert fs2.pick("，") != fs2.pick("永")


# ------------------------------------------------------------------ config file discovery

def _run_cli(args, monkeypatch, tmp_path, capsys):
    from handnote.cli import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("HANDNOTE_CONFIG", raising=False)
    rc = main(args)
    return rc, capsys.readouterr()


def test_hints_cover_every_option():
    from dataclasses import fields
    from handnote.config import HINTS
    names = {"seed"} | {f"{s}.{f.name}" for s in ("page", "text", "paper", "photo", "llm") for f in fields(getattr(Config(), s))}
    assert set(HINTS) == names


def test_config_search_order(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(["config", "--path"], monkeypatch, tmp_path, capsys)
    assert rc == 0 and "no config file found" in out.out
    user = tmp_path / "xdg" / "handnote" / "config.toml"
    rc, out = _run_cli(["init-config"], monkeypatch, tmp_path, capsys)
    assert rc == 0 and user.is_file()
    rc, out = _run_cli(["config", "--path"], monkeypatch, tmp_path, capsys)
    assert f"{user}  (in use)" in out.out
    (tmp_path / "handnote.toml").write_text("[text]\nink = \"red\"\n", encoding="utf-8")
    rc, out = _run_cli(["config", "--set", "photo.noise=0"], monkeypatch, tmp_path, capsys)
    assert 'ink = "red"' in out.out and "noise = 0.0" in out.out  # ./handnote.toml beats the user file; --set beats both
    rc, out = _run_cli(["config", "--no-config"], monkeypatch, tmp_path, capsys)
    assert 'ink = "black"' in out.out
    monkeypatch.setenv("HANDNOTE_CONFIG", "none")
    from handnote.config import find_config
    assert find_config() is None


def test_init_config_refuses_overwrite_and_is_valid(monkeypatch, tmp_path, capsys):
    rc, _ = _run_cli(["init-config", "-o", "x.toml"], monkeypatch, tmp_path, capsys)
    assert rc == 0 and Config.load(tmp_path / "x.toml") == Config()
    rc, out = _run_cli(["init-config", "-o", "x.toml"], monkeypatch, tmp_path, capsys)
    assert rc == 2 and "already exists" in out.err
    rc, _ = _run_cli(["init-config", "-o", "y.toml", "--commented"], monkeypatch, tmp_path, capsys)
    assert Config.load(tmp_path / "y.toml") == Config()  # everything commented out means nothing overridden


def test_config_errors_name_the_file(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[text]\nink_colour = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.toml"):
        Config.load(p)
    p.write_text("[text\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid TOML"):
        Config.load(p)


def test_config_relative_font_path_means_next_to_config(tmp_path):
    (tmp_path / "f.ttf").write_bytes(b"x")
    p = tmp_path / "c.toml"
    p.write_text('[text]\nfonts = ["f.ttf", "lxgw"]\n', encoding="utf-8")
    assert Config.load(p).text.fonts == [str(tmp_path / "f.ttf"), "lxgw"]


def test_letter_spacing_changes_line_width():
    def width(ls):
        cfg = Config()
        cfg.text.spacing_mode, cfg.text.letter_spacing = "advance", ls
        g = [e for e in _elements("一二三四五六七八九十", cfg) if isinstance(e, Glyph)]
        return max(e.x for e in g) - min(e.x for e in g)
    assert width(0.3) > width(0.03) > width(-0.05)


# ------------------------------------------------------------------ lint and AGENTS.md

def _lint(md):
    from handnote.lint import lint
    return lint(md, Config())


def test_agents_md_example_lints_clean():
    import re
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(r"````markdown\n(.*?)\n````", text, re.S)
    assert m, "AGENTS.md must contain a ````markdown example"
    rep = _lint(m.group(1) + "\n")
    assert rep.issues == [], rep.text()
    assert 1 <= rep.pages <= 2


def test_lint_catches_forbidden_markdown():
    bad = "# 题目\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n![图](x.png)\n\n公式 $\\frac{a}{b}$ 好的，以下是\n\n## 二\n\n# 又一个\n"
    codes = set(_lint(bad).codes())
    assert {"table", "image", "latex", "chatty", "multi-h1", "empty-section", "too-short"} <= codes
    assert _lint(bad).errors


def test_lint_flags_whole_file_fence_and_single_item_list():
    codes = _lint("```markdown\n# 题目\n\n- 只有一项\n```\n").codes()
    assert "whole-file-fence" in codes
    assert "single-item-list" in codes or "single-item-list" in _lint("# 题目\n\n- 只有一项\n").codes()


def test_lint_cli_exit_codes(monkeypatch, tmp_path, capsys):
    (tmp_path / "bad.md").write_text("# 题\n\n| a |\n|---|\n| 1 |\n", encoding="utf-8")
    rc, _ = _run_cli(["lint", "bad.md", "--no-config"], monkeypatch, tmp_path, capsys)
    assert rc == 1


# ------------------------------------------------------------------ phone tilt

def test_tilt_matrix_far_side_shrinks():
    from handnote.photo import tilt_matrix
    import cv2 as _cv
    pts = np.float32([[[-300, -400], [300, -400], [300, 400], [-300, 400]]])
    for name, ang, idx in (("top", 0.0, (0, 1)), ("bottom", np.pi, (2, 3))):
        out = _cv.perspectiveTransform(pts, tilt_matrix(600, 800, 8, ang, 0.8))[0]
        far = abs(out[idx[0], 0] - out[idx[1], 0])
        near = abs(out[3 - idx[0] if False else (2 if idx[0] == 0 else 0), 0] - out[(3 if idx[0] == 0 else 1), 0])
        assert far < near < 600 * 1.2, name  # the far edge is shorter than the near one
        assert far > 600 * 0.7  # but only slightly: it is a gentle tilt


def test_tilt_direction_parsing():
    from handnote.config import PhotoConfig
    from handnote.photo import tilt_direction_angle
    rng = np.random.default_rng(0)
    c = PhotoConfig(tilt_direction_jitter=0.0)
    assert tilt_direction_angle(c, rng) == 0.0
    c.tilt_direction = "left"
    assert abs(tilt_direction_angle(c, rng) - 1.5 * np.pi) < 1e-9
    c.tilt_direction = "45"
    assert abs(tilt_direction_angle(c, rng) - np.pi / 4) < 1e-9
    c.tilt_direction = "sideways"
    with pytest.raises(ValueError):
        tilt_direction_angle(c, rng)


def test_tilt_warps_the_desk_too():
    from handnote.photo import shoot
    flat = np.full((600, 450, 3), 0.9, np.float32)
    def run(tmax):
        cfg = Config().photo
        cfg.tilt_min = cfg.tilt_max = tmax
        cfg.tilt_direction_jitter = 0.0
        cfg.blur = cfg.noise = cfg.vignette = cfg.light_gradient = cfg.color_cast = cfg.tone_var = 0.0
        cfg.shadow = "none"
        cfg.rotation = cfg.perspective = cfg.bend = cfg.edge_bow_max = cfg.corner_lift = cfg.dog_ear_prob = cfg.paper_shadow = 0.0
        cfg.desk_texture = 1.0
        return shoot(flat, cfg, np.random.default_rng(3)).astype(float)
    a, b = run(0.0), run(12.0)
    assert a.shape == b.shape
    # paper width (bright pixels) near the top vs near the bottom of the picture
    def width(img, row):
        return (img[row].mean(axis=1) > 150).sum()
    h = b.shape[0]
    assert width(b, int(0.25 * h)) < width(b, int(0.75 * h)) - 5  # top is farther away, so narrower
    assert abs(width(a, int(0.25 * h)) - width(a, int(0.75 * h))) <= 3
    assert np.abs(a[:20] - b[:20]).mean() > 0.5  # the desk texture changed as well


def test_shadow_position():
    from handnote.photo import SHADOW_POSITIONS, shadow_mask
    for name, (fx, fy) in SHADOW_POSITIONS.items():
        m = shadow_mask(400, 300, "phone", np.random.default_rng(1), name)
        ys, xs = np.nonzero(m > 0.5)
        cx, cy = xs.mean() / 300, ys.mean() / 400
        assert (cx - 0.5) * (fx - 0.5) >= -0.01 and (cy - 0.5) * (fy - 0.5) >= -0.01, name  # centroid on the named side
        if fx != 0.5:
            assert (cx < 0.5) == (fx < 0.5), name
        if fy != 0.5:
            assert (cy < 0.5) == (fy < 0.5), name
    with pytest.raises(ValueError):
        shadow_mask(40, 30, "phone", np.random.default_rng(1), "middle")


def test_ink_mode_spaces_glyph_edges_not_font_cells():
    cfg = Config()
    cfg.text.spacing_mode, cfg.text.ink_gap, cfg.text.ink_min_width = "ink", 0.12, 0.0
    g = [e for e in _elements("国小大中永学习", cfg) if isinstance(e, Glyph)]
    assert len(g) == 7
    for a, b in zip(g, g[1:]):
        ea, eb = FONTS.ink_extent(a.ch), FONTS.ink_extent(b.ch)
        gap = (b.x + eb[0] * b.size) - (a.x + ea[1] * a.size)  # between the two real ink boxes
        assert abs(gap - 0.12 * a.size) < 0.01 * a.size, (a.ch, b.ch, gap)
    cfg.text.ink_gap = 0.3
    wide = [e for e in _elements("国小大中永学习", cfg) if isinstance(e, Glyph)]
    assert wide[-1].x > g[-1].x


def test_ink_mode_underline_stops_at_last_ink_edge():
    cfg = Config()
    cfg.text.ink_gap = 0.2
    els = _elements("**国小大**", cfg)
    d = [e for e in els if isinstance(e, Deco)][0]
    last = [e for e in els if isinstance(e, Glyph)][-1]
    assert abs(d.x1 - (last.x + FONTS.ink_extent(last.ch)[1] * last.size)) < 0.5


def test_paper_stack_changes_only_the_surroundings():
    from handnote.photo import shoot
    flat = np.full((600, 450, 3), 0.9, np.float32)
    def run(n):
        cfg = Config().photo
        cfg.stack_count, cfg.stack_direction, cfg.stack_offset = n, "bottom-right", 0.03
        cfg.tilt_max = cfg.blur = cfg.noise = cfg.vignette = cfg.light_gradient = cfg.color_cast = cfg.tone_var = 0.0
        cfg.shadow, cfg.desk_texture = "none", 0.0
        cfg.rotation = cfg.perspective = cfg.bend = cfg.edge_bow_max = cfg.corner_lift = cfg.dog_ear_prob = 0.0
        return shoot(flat, cfg, np.random.default_rng(3)).astype(float)
    a, b = run(0), run(3)
    h, w = a.shape[:2]
    assert np.abs(a[h // 3: 2 * h // 3, w // 3: 2 * w // 3] - b[h // 3: 2 * h // 3, w // 3: 2 * w // 3]).max() < 2  # the sheet itself
    br = (slice(int(0.85 * h), int(0.97 * h)), slice(int(0.85 * w), int(0.97 * w)))
    assert (b[br].mean() - a[br].mean()) > 20  # pale sheets show where there was dark desk
    tl = (slice(int(0.0 * h), int(0.1 * h)), slice(0, int(0.1 * w)))
    assert abs(b[tl].mean() - a[tl].mean()) < 3  # nothing on the far side


# ------------------------------------------------------------------ handnote write + output layout

def test_render_output_layout_is_out_name_pagenumber(monkeypatch, tmp_path, capsys):
    md = tmp_path / "牛顿.md"
    md.write_text("# 题\n\n" + "这是一行很长的笔记内容，用来撑出第二页。\n\n" * 40, encoding="utf-8")
    rc, out = _run_cli(["render", str(md), "-o", "out", "--no-config", "--no-photo", "--seed", "1"], monkeypatch, tmp_path, capsys)
    assert rc == 0
    files = sorted(p.name for p in (tmp_path / "out" / "牛顿").iterdir())
    assert files[:2] == ["1.jpg", "2.jpg"], files
    rc, out = _run_cli(["render", str(md), "-o", "x/page.png", "--no-config", "--no-photo", "--seed", "1"], monkeypatch, tmp_path, capsys)
    assert (tmp_path / "x" / "page.png").is_file() and (tmp_path / "x" / "page-2.png").is_file()


def test_writer_example_is_the_documented_one_and_clean():
    from handnote.writer import EXAMPLE, SYSTEM_PROMPT
    assert EXAMPLE.strip() == (ROOT / "examples" / "agents-example.md").read_text(encoding="utf-8").strip()
    assert _lint(EXAMPLE).issues == []
    assert EXAMPLE in SYSTEM_PROMPT


def test_writer_clean_and_filename():
    from handnote.writer import clean, note_filename, parse_section
    assert clean("<think>想想</think>\n好的，以下是笔记：\n# 题\n\n内容\n") == "# 题\n\n内容\n"
    assert clean("```markdown\n# 题\n\n内容\n```") == "# 题\n\n内容\n"
    assert note_filename('牛顿/运动: 定律?') == "牛顿运动-定律"
    assert note_filename("///") == "note"
    assert parse_section("惯性：质量决定") == ("惯性", "质量决定")
    assert parse_section("只有标题") == ("只有标题", "")


def test_write_end_to_end_with_a_fake_llama_server(monkeypatch, tmp_path, capsys):
    import json, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    good = (ROOT / "examples" / "agents-example.md").read_text(encoding="utf-8")
    bad = "好的，以下是笔记：\n# 牛顿\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            text = bad if len(seen) == 1 else good
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(text), 40):
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": text[i:i + 40]}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rc, out = _run_cli(["write", "--no-config", "--topic", "牛顿运动定律", "--section", "第一定律：惯性", "--section", "第二定律",
                            "--note", "", "--no-photo", "--seed", "1", "--set", f"llm.port={srv.server_port}"],
                           monkeypatch, tmp_path, capsys)
    finally:
        srv.shutdown()
    assert rc == 0, out.err
    assert len(seen) == 2  # the first answer had a table, so the model was asked once more
    assert "第一定律（要点：惯性）" in seen[0]["messages"][1]["content"]
    assert "做了检查" in seen[1]["messages"][-1]["content"] and "表格" in seen[1]["messages"][-1]["content"]
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False} and seen[0]["stream"] is True
    note = tmp_path / "notes" / "牛顿运动定律.md"
    assert note.read_text(encoding="utf-8").startswith("# 牛顿运动定律")
    assert (tmp_path / "out" / "牛顿运动定律" / "1.jpg").is_file()


def test_write_reports_unreachable_server(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(["write", "--no-config", "--topic", "t", "--note", "", "--set", "llm.port=1", "--set", "llm.timeout=2"],
                       monkeypatch, tmp_path, capsys)
    assert rc == 2 and "连不上模型服务" in out.err


# ------------------------------------------------------------------ handnote slides

def _make_pdf(path, pages):
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "LXGW" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LXGW", str(ROOT / "fonts" / "LXGWWenKai-Regular.ttf")))
    c = rl.Canvas(str(path))
    for i, lines in enumerate(pages, 1):
        c.setFont("LXGW", 18)
        c.drawString(60, 780, "操作系统课程 第三章")  # the same header on every page
        for k, ln in enumerate(lines):
            c.drawString(60, 700 - 30 * k, ln)
        c.drawString(300, 30, str(i))
        c.showPage()
    c.save()


class _FakeLlm:
    def __init__(self, answers):
        import json, threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.seen.append(body)
                text = answers(body, len(outer.seen))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for i in range(0, len(text), 50):
                    self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": text[i:i + 50]}}]}).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def test_slides_clean_pages_drops_numbers_and_repeated_headers():
    from handnote.slides import clean_pages
    pages = [f"操作系统课程 第三章\n进 程 调 度 {i}\n内容{i}\n{i}\n第 {i} 页" for i in range(1, 5)]
    out = clean_pages(pages)
    assert out[0] == "进程调度 1\n内容1"
    assert all("操作系统课程" not in p and "页" not in p for p in out)


def test_slides_chunking_and_pdf_collection(tmp_path):
    from handnote.slides import chunk_pages, collect_pdfs
    chunks = chunk_pages(["甲" * 400, "乙" * 400, "", "丙" * 2500], 1000)
    assert all(len(c) <= 1000 for c in chunks) and "".join(chunks).count("丙") == 2500
    (tmp_path / "sub").mkdir()
    for n in ("10.pdf", "2.pdf", "a.PDF", "x.txt"):
        (tmp_path / n).write_bytes(b"")
    (tmp_path / "sub" / "z.pdf").write_bytes(b"")
    assert [p.name for p in collect_pdfs(tmp_path)] == ["2.pdf", "10.pdf", "a.PDF"]
    assert [p.name for p in collect_pdfs(tmp_path, recursive=True)][-1] == "z.pdf"
    with pytest.raises(ValueError):
        collect_pdfs(tmp_path / "x.txt")


def test_slides_end_to_end_single_and_folder(monkeypatch, tmp_path, capsys):
    good = (ROOT / "examples" / "agents-example.md").read_text(encoding="utf-8")
    folder = tmp_path / "ppt"
    folder.mkdir()
    _make_pdf(folder / "第一讲.pdf", [["进程是资源分配的基本单位", "线程是调度的基本单位"], ["进程状态：就绪、运行、阻塞"], ["进程通信：管道、消息队列"]])
    _make_pdf(folder / "第二讲.pdf", [["死锁的四个必要条件"]])
    (folder / "scan.pdf").write_bytes(b"%PDF-1.4 broken")
    llm = _FakeLlm(lambda body, n: good)
    try:
        rc, out = _run_cli(["slides", str(folder), "--no-config", "--no-photo", "--seed", "1", "--set", f"llm.port={llm.port}"],
                           monkeypatch, tmp_path, capsys)
    finally:
        llm.close()
    assert rc == 1  # the broken PDF failed, the others went through
    assert "scan.pdf" in out.err and "失败 1 个" in out.err
    for stem in ("第一讲", "第二讲"):
        assert (tmp_path / "notes" / f"{stem}.md").is_file()
        assert (tmp_path / "out" / stem / "1.jpg").is_file()
    first = llm.seen[0]["messages"]
    assert "进程是资源分配的基本单位" in first[1]["content"] and "【第 2 页】" in first[1]["content"]
    assert "操作系统课程" not in first[1]["content"]  # the header repeats on every page, so it is dropped
    assert "课件" in first[0]["content"]


def test_slides_long_deck_is_condensed_first(monkeypatch, tmp_path, capsys):
    good = (ROOT / "examples" / "agents-example.md").read_text(encoding="utf-8")
    pdf = tmp_path / "长课件.pdf"
    _make_pdf(pdf, [[f"第{i}页的内容很重要，{'字' * 150}"] for i in range(1, 9)])
    def answers(body, n):
        return "- 要点提炼" if "提炼成要点" in body["messages"][0]["content"] else good
    llm = _FakeLlm(answers)
    try:
        rc, out = _run_cli(["slides", str(pdf), "--no-config", "--no-render", "--set", f"llm.port={llm.port}", "--set", "llm.chunk_chars=1000"],
                           monkeypatch, tmp_path, capsys)
    finally:
        llm.close()
    assert rc == 0, out.err
    condense = [b for b in llm.seen if "提炼成要点" in b["messages"][0]["content"]]
    assert len(condense) >= 2
    final = llm.seen[-1]["messages"][1]["content"]
    assert "课件各部分提炼出的要点" in final and "要点提炼" in final


def test_slides_pdf_without_text(tmp_path):
    from handnote.config import Config as C
    from handnote.slides import note_from_pdf
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    p = tmp_path / "img.pdf"
    c = rl.Canvas(str(p)); c.rect(10, 10, 100, 100); c.showPage(); c.save()
    with pytest.raises(ValueError, match="提取不到文字"):
        note_from_pdf(C(), p)
