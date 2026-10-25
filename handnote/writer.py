"""`handnote write`: ask for a topic and sub-headings, have a local language model write the note, check it with
the linter (letting the model fix what the linter objects to), then render it.

The model is any OpenAI-compatible chat server; the usual one is llama.cpp's `llama-server`.  Where it is
(host, port, model name, sampling) comes from the `[llm]` section of the config file.  The prompts are built in.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .config import Config, LlmConfig


class LlmError(RuntimeError):
    pass


EXAMPLE = '# 牛顿运动定律\n\n## 一、第一定律（惯性定律）\n\n一切物体在不受外力时，总保持**静止**或**匀速直线运动**状态，直到外力迫使它改变。\n\n要点：\n- 力不是维持运动的原因，而是**改变**运动状态的原因\n- **惯性**：物体保持原有运动状态的性质，*inertia*\n- 质量越大，惯性越大\n\n> 易错：惯性只由质量决定，和速度、受力都无关。\n\n注意：第一定律无法用实验直接验证，是在实验基础上推理出来的理想结论。\n\n## 二、第二定律\n\n物体的加速度跟所受合外力成**正比**，跟质量成**反比**，方向与合外力相同。\n\n公式：`F = ma`\n\n各量：\n- `F`：合外力，单位 N\n- `m`：质量，单位 kg\n- `a`：加速度，单位 m/s²\n\n记：1 N 就是使 1 kg 的物体产生 1 m/s² 加速度的力。\n\n例：用 10 N 的水平力推一个 2 kg 的物体（忽略摩擦），`a = F / m = 5 m/s²`。\n\n解题步骤：\n1. 选研究对象，画受力分析图\n2. 沿加速度方向列式 `F合 = ma`\n3. 解方程，检查单位\n\n## 三、第三定律\n\n两个物体之间的作用力与反作用力，大小**相等**、方向**相反**，在同一条直线上。\n\n### 容易混的一对概念\n\n- 平衡力\n  - 作用在**同一个**物体上\n  - 效果可以抵消\n- 作用力与反作用力\n  - 作用在**两个**物体上\n  - 不能抵消\n\n> 作用力和反作用力同时产生、同时消失，性质相同。\n\n## 四、速记\n\n- 一：不受力，保持原状\n- 二：`F = ma`\n- 三：大小相等，方向相反，分别作用在两个物体上'

SYSTEM_PROMPT = """你是一名认真听课的学生，要把老师讲的内容记成一份手写课堂笔记。你写的 Markdown 会被程序渲染成手写笔记的照片：标题变大字，并列要点列表变成手画大括号，加粗变双横线，斜体变单横线，引用变成缩进加手画三角。所以必须按下面的规则用 Markdown。

内容与语气
- 像真正的课堂笔记：句子短，抓关键词，一个要点一行。写定义、原理、公式、例子、易错点、解题步骤。
- 常用「例：」「注意：」「记：」「易错：」开头。
- 篇幅 1 到 2 页（约 500 到 1000 个汉字）。子标题很多时可以到 3 页，但每部分都要精简。
- 只写有把握的内容；拿不准的数字、年份、人名、公式不要写，不要编造出处。
- 不要任何对话和套话：不要「好的」「以下是」「综上所述」「希望对你有帮助」。第一行直接是 # 题目，最后一行是笔记的最后一个要点。只输出 Markdown 正文，不要用 ``` 包起来。

Markdown 用法
- 第一行 `# 题目`，全文只有一个 #。
- 每个子标题用 `## 一、名称`（自己写序号：一、二、三），需要再细分时用 `### 小节名`，最多到三级。
- 普通说明写短段落，每段不超过 3 行（约 80 字）。
- 一组并列要点（2 到 6 条）用 `- 要点`，会被画成一个大括号；每条不超过一行半；只有 1 条就写成普通句子。列表最多嵌套两层。列表上一行可写 `短标签：`（8 字以内）作为括号的名字。
- 有先后顺序的步骤用 `1. 第一步`。
- 新概念、关键术语用 **加粗**（每处 2 到 8 个字，不要加粗整句，标题里不要加粗）；次要强调、英文名用 *斜体*。
- 老师特别强调的话、易错提醒用 `> 一两句话`，全篇两三处。
- 公式、变量、命令用行内 `代码`，用普通字符写公式（如 F = ma、v = s / t、a² + b²），真正的代码才用代码块（5 到 10 行）。
- 不要用：表格（改成「- 名称：说明」的列表）、图片、链接、HTML、LaTeX（$…$）、emoji、任务列表、四级及以下标题、手动缩进。`---` 全文最多 1 条。

下面是一份合格笔记的格式示例，只学格式和语气，不要照抄内容：

""" + EXAMPLE


def build_user_prompt(topic: str, sections: List[Tuple[str, str]], extra: str = "") -> str:
    lines = [f"主题：{topic}"]
    if sections:
        lines.append("笔记必须包含下面这些子标题，按这个顺序，每个子标题单独成一个 ## 章节（序号写一、二、三…）：")
        for i, (title, detail) in enumerate(sections, 1):
            lines.append(f"{i}. {title}" + (f"（要点：{detail}）" if detail else ""))
    else:
        lines.append("子标题由你按这个主题的常见讲法安排，3 到 5 个章节。")
    if extra.strip():
        lines.append(f"其他要求：{extra.strip()}")
    lines.append("现在直接输出这份笔记的 Markdown，第一行是 # 题目，不要有任何前言或结尾说明。")
    return "\n".join(lines)


def fix_prompt(report_text: str) -> str:
    return ("程序对你写的笔记做了检查，结果如下：\n" + report_text +
            "\n\n请逐条修改，然后输出修改后的**完整**笔记。只输出 Markdown 正文，不要解释，不要用 ``` 包起来。")


# --------------------------------------------------------------------------- talking to the model

def endpoint(cfg: LlmConfig) -> str:
    base = cfg.base_url.strip().rstrip("/") or f"http://{cfg.host}:{cfg.port}/v1"
    return base + "/chat/completions"


def chat(cfg: LlmConfig, messages: list, on_text: Optional[Callable[[str], None]] = None) -> str:
    """Send the conversation, stream the answer (calling ``on_text`` with each piece) and return all of it."""
    body = {"model": cfg.model, "messages": messages, "temperature": cfg.temperature, "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens, "stream": True,
            "chat_template_kwargs": {"enable_thinking": bool(cfg.thinking)}}
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    req = urllib.request.Request(endpoint(cfg), json.dumps(body).encode("utf-8"), headers)
    out: List[str] = []
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {})
                except (ValueError, KeyError, IndexError):
                    continue
                piece = delta.get("content") or ""
                if piece:
                    out.append(piece)
                    if on_text:
                        on_text(piece)
    except urllib.error.HTTPError as e:
        raise LlmError(f"模型服务返回 {e.code}：{e.read().decode('utf-8', 'replace')[:300]}（地址 {endpoint(cfg)}）") from None
    except (urllib.error.URLError, OSError) as e:
        raise LlmError(f"连不上模型服务 {endpoint(cfg)}：{e}。请确认 llama-server 已启动，并检查配置文件 [llm] 里的 host / port / base_url。") from None
    text = "".join(out)
    if not text.strip():
        raise LlmError("模型没有返回任何内容。")
    return text


def clean(text: str) -> str:
    """Strip what a chatty model wraps around a note: <think> blocks, a ``` fence, text before the first # title."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^.*?</think>", "", text, flags=re.S) if "</think>" in text else text
    text = text.strip()
    m = re.match(r"^`{3,}[ \t]*(?:markdown|md)?[ \t]*\n(.*?)\n`{3,}[ \t]*$", text, re.S)
    if m:
        text = m.group(1).strip()
    m = re.search(r"^# .+$", text, re.M)
    if m and m.start() > 0:
        text = text[m.start():]
    return text.strip() + "\n"


def generate(cfg: Config, system: str, user: str, log: Callable[[str], None] = lambda s: None,
             stream: Optional[Callable[[str], None]] = None) -> Tuple[str, "object"]:
    """Ask the model, then let the linter and the model go back and forth until the note passes (or the rounds
    run out).  Returns the note and its last lint report."""
    from .lint import lint

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    md = clean(chat(cfg.llm, messages, stream))
    rep = lint(md, cfg)
    for rnd in range(1, cfg.llm.fix_rounds + 1):
        if not rep.issues:
            break
        log(f"检查发现 {len(rep.errors)} 处必须修改、{len(rep.warnings)} 处建议修改，让模型改第 {rnd} 轮……")
        messages += [{"role": "assistant", "content": md}, {"role": "user", "content": fix_prompt(rep.text())}]
        md = clean(chat(cfg.llm, messages, stream))
        rep = lint(md, cfg)
    return md, rep


def make_note(cfg: Config, topic: str, sections: List[Tuple[str, str]], extra: str = "",
              log: Callable[[str], None] = lambda s: None, stream: Optional[Callable[[str], None]] = None) -> Tuple[str, "object"]:
    return generate(cfg, SYSTEM_PROMPT, build_user_prompt(topic, sections, extra), log, stream)


# --------------------------------------------------------------------------- asking the person

def note_filename(topic: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", topic).strip()
    name = re.sub(r"\s+", "-", name)[:40].strip(" .-")
    return name or "note"


def unique_path(directory: Path, stem: str) -> Path:
    p = directory / f"{stem}.md"
    n = 2
    while p.exists():
        p = directory / f"{stem}-{n}.md"
        n += 1
    return p


def parse_section(line: str) -> Tuple[str, str]:
    """`标题：要点说明` -> ("标题", "要点说明"); a line without a colon is just a title."""
    m = re.match(r"^\s*([^:：]+?)\s*[:：]\s*(.+?)\s*$", line)
    return (m.group(1), m.group(2)) if m else (line.strip(), "")


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def interactive(args) -> Tuple[str, List[Tuple[str, str]], str]:
    topic = args.topic or ask("笔记主题（如：牛顿运动定律）：")
    if not topic:
        raise ValueError("没有给出主题。")
    sections = [parse_section(s) for s in (args.section or [])]
    if not args.section and sys.stdin.isatty():
        print("要包含的子标题，每行一个；想补充要点就写成「标题：要点」；直接回车结束（一个都不写则由模型安排）：")
        while True:
            line = ask(f"  子标题 {len(sections) + 1}：")
            if not line:
                break
            sections.append(parse_section(line))
    extra = args.note if args.note is not None else (ask("其他要求（可留空，如：偏重解题方法）：") if sys.stdin.isatty() else "")
    return topic, sections, extra
