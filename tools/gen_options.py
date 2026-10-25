"""Write docs/options.md from handnote/config.py (names, defaults and the comments next to them).

    python tools/gen_options.py          # rewrite the file
    python tools/gen_options.py --check  # exit 1 if it is out of date (the test suite does this)
"""
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from handnote.config import HINTS, SECTION_TITLES, SECTIONS, Config, field_docs  # noqa: E402

TITLES = SECTION_TITLES


def comments() -> dict:
    return field_docs()


def render() -> str:
    cfg, notes = Config(), comments()
    lines = [
        "# 全部选项",
        "",
        "本文件由 `python tools/gen_options.py` 从源码生成，不要手改。",
        "在配置文件里写成 `[section]` 下的 `key = value`，或在命令行用 `--set section.key=value`（可重复）。",
        "`handnote config` 打印当前全部取值；`examples/config.example.toml` 是带说明和候选值的完整配置文件（`handnote init-config` 可生成并自动生效）。",
        "约定：数值型的效果设为 0 就是关闭；概率设为 0 是从不发生，设为 1 是必定发生。",
        "",
    ]
    for sec in SECTIONS:
        title, blurb = TITLES[sec]
        lines += [f"## {title}", "", blurb, "", "| 选项 | 默认值 | 候选 / 期望值 | 说明 |", "|---|---|---|---|"]
        obj = getattr(cfg, sec)
        for f in fields(obj):
            val = getattr(obj, f.name)
            shown = "`" + str(list(val) if isinstance(val, tuple) else val).replace("|", "\\|") + "`" if val != "" else "`\"\"`"
            lines.append(f"| `{f.name}` | {shown} | {HINTS[f'{sec}.{f.name}'].replace('|', '\\|')} | {notes.get((sec, f.name), '').replace('|', '\\|')} |")
        lines.append("")
    lines += ["## 顶层", "", "| 选项 | 默认值 | 候选 / 期望值 | 说明 |", "|---|---|---|---|", f"| `seed` | 未设置 | {HINTS['seed']} | 固定随机种子；不设则每次都不一样 |", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    text = render()
    target = ROOT / "docs" / "options.md"
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text(encoding="utf-8") == text else 1)
    target.write_text(text, encoding="utf-8")
    print(target)
