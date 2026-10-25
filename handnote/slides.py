"""`handnote slides`: turn lecture slides (PDF) into a handwritten class note.

The text of the PDF is extracted page by page and cleaned (page numbers and headers or footers that repeat on
every page are dropped).  Short decks go to the model in one request.  A long deck is first cut into chunks that
each get condensed into key points, and the note is written from those, so the context of a local model is never
overrun.  The note then goes through the same check-and-fix loop as `handnote write`.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .config import Config
from .writer import LlmError, SYSTEM_PROMPT, chat, generate

CJK = "一-鿿"
PAGE_NO = re.compile(r"^(?:[-—–\s]*\d{1,4}[-—–\s]*|第\s*\d+\s*页(?:\s*[/／]\s*共\s*\d+\s*页)?|\d+\s*[/／]\s*\d+|page\s*\d+(?:\s*(?:of|/)\s*\d+)?)$", re.I)

SLIDES_RULES = """

现在的任务是根据老师的课件（PDF 提取出的文字）整理课堂笔记，额外遵守：
- 课件是按页给的，页码标记（【第 N 页】）不要写进笔记。不要逐页照抄，要合并重复的内容，按知识的层次重新组织成章节。
- 只使用课件里有的内容，不要补充课件没有的事实、数字和例子；课件里看不清或残缺的地方跳过，不要猜。
- 课件的页眉页脚、课程名、教师、日期、致谢、「谢谢」「Q&A」等页不要写进笔记。
- 课件里的表格、图表文字如果被提取成零散的词，按意思整理成列表。
- 篇幅按课件内容多少决定，通常 1 到 3 页，宁可精简只留要点。"""

CONDENSE_SYSTEM = """你是一名认真听课的学生，正在把老师的课件整理成笔记。下面给你课件的一部分文字（按页给出，带【第 N 页】标记）。
请把它提炼成要点，输出纯文本，供后面写正式笔记使用：
- 保留术语、定义、公式、关键数字、例子、结论和步骤，保持课件里的层次（用缩进的短横线列表表示）。
- 去掉页眉页脚、页码、课程名、教师、日期、致谢，合并重复内容。
- 只用课件里有的内容，不要补充，不要评论。
- 不要写开场白和结尾，直接输出要点。长度控制在原文的三分之一以内。"""


def extract_pages(path: Path) -> List[str]:
    """Raw text of every page.  Raises ValueError when the file cannot be read or holds no text."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("读取 PDF 需要 pypdf：pip install pypdf") from None
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        return [(pg.extract_text() or "") for pg in reader.pages]
    except Exception as e:  # damaged, password protected, ...
        raise ValueError(f"打不开 PDF {path.name}：{e}") from None


def clean_pages(pages: List[str]) -> List[str]:
    """Normalise each page's text and drop page numbers and lines that repeat on most pages (headers, footers)."""
    lines_per_page: List[List[str]] = []
    for text in pages:
        text = text.replace(" ", " ").replace("　", " ").replace("\x00", "")
        out = []
        for ln in text.splitlines():
            ln = re.sub(r"[ \t]+", " ", ln).strip()
            ln = re.sub(rf"(?<=[{CJK}，。；：、！？（）]) +(?=[{CJK}，。；：、！？（）])", "", ln)  # spaces between CJK glyphs are layout noise
            if ln and not PAGE_NO.match(ln):
                out.append(ln)
        lines_per_page.append(out)
    n = sum(1 for p in lines_per_page if p)
    if n >= 3:
        count = Counter(ln for p in lines_per_page for ln in set(p))
        limit = max(3, 0.5 * n)
        lines_per_page = [[ln for ln in p if not (count[ln] >= limit and len(ln) <= 60)] for p in lines_per_page]
    return ["\n".join(p) for p in lines_per_page]


def format_pages(pages: List[str], first: int = 1) -> str:
    return "\n\n".join(f"【第 {i} 页】\n{t}" for i, t in enumerate(pages, first) if t.strip())


def chunk_pages(pages: List[str], limit: int) -> List[str]:
    """Greedy groups of consecutive pages, each at most ``limit`` characters (a longer single page is cut)."""
    chunks, cur, size = [], [], 0
    for i, t in enumerate(pages, 1):
        if not t.strip():
            continue
        block = f"【第 {i} 页】\n{t}"
        while len(block) > limit:  # one enormous page
            if cur:
                chunks.append("\n\n".join(cur))
                cur, size = [], 0
            chunks.append(block[:limit])
            block = block[limit:]
        if cur and size + len(block) + 2 > limit:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(block)
        size += len(block) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def slides_text(cfg: Config, pages: List[str], log: Callable[[str], None] = lambda s: None,
                stream: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
    """The text to write the note from, and whether it had to be condensed first."""
    limit = max(1000, cfg.llm.chunk_chars)
    body = format_pages(pages)
    if len(body) <= limit:
        return body, False
    parts = chunk_pages(pages, limit)
    for rnd in range(3):
        log(f"课件文字 {len(body)} 字，分 {len(parts)} 段提炼要点……")
        points = []
        for k, part in enumerate(parts, 1):
            log(f"提炼第 {k}/{len(parts)} 段")
            points.append(chat(cfg.llm, [{"role": "system", "content": CONDENSE_SYSTEM},
                                         {"role": "user", "content": part}], stream).strip())
        body = "\n\n".join(f"【课件第 {k} 部分要点】\n{p}" for k, p in enumerate(points, 1))
        if len(body) <= limit:
            return body, True
        parts = chunk_pages(["\n".join(points)], limit)  # still too long: condense the points again
        parts = [p.replace("【第 1 页】\n", "", 1) for p in parts]
    return body[:limit], True


def build_user_prompt(name: str, text: str, condensed: bool, extra: str = "") -> str:
    head = f"课件文件：{name}\n"
    head += ("下面是课件各部分提炼出的要点：\n" if condensed else "下面是课件提取出的文字（按页）：\n")
    tail = ("\n\n现在根据以上内容直接输出这份课堂笔记的 Markdown。第一行是 # 题目（用课件的主题作题目），"
            "不要任何前言或结尾说明。")
    if extra.strip():
        tail = f"\n\n其他要求：{extra.strip()}" + tail
    return head + "\n" + text + tail


def note_from_pdf(cfg: Config, path: Path, extra: str = "", log: Callable[[str], None] = lambda s: None,
                  stream: Optional[Callable[[str], None]] = None) -> Tuple[str, "object", int]:
    """Returns the note, its lint report and the number of slides."""
    raw = extract_pages(path)
    pages = clean_pages(raw)
    if not any(p.strip() for p in pages):
        raise ValueError(f"{path.name} 里提取不到文字（可能是扫描件或纯图片课件）。本工具不做文字识别，请先用 OCR 工具转成带文字的 PDF。")
    text, condensed = slides_text(cfg, pages, log, stream)
    md, rep = generate(cfg, SYSTEM_PROMPT + SLIDES_RULES, build_user_prompt(path.name, text, condensed, extra), log, stream)
    return md, rep, len(raw)


def collect_pdfs(target: Path, recursive: bool = False) -> List[Path]:
    """The PDF itself, or the PDFs in a directory (natural order: 2.pdf before 10.pdf)."""
    if target.is_file():
        if target.suffix.lower() != ".pdf":
            raise ValueError(f"不是 PDF 文件：{target}")
        return [target]
    if not target.is_dir():
        raise FileNotFoundError(f"找不到 {target}")
    files = [p for p in (target.rglob("*") if recursive else target.iterdir()) if p.is_file() and p.suffix.lower() == ".pdf"]

    def key(p: Path):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p.relative_to(target)))]

    files.sort(key=key)
    if not files:
        raise ValueError(f"{target} 里没有 PDF 文件" + ("" if recursive else "（子目录里的可以加 -r）"))
    return files
