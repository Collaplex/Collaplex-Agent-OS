#!/usr/bin/env python3
"""正文页 -> 标题 + 正文段落.

★ 只干"去壳留肉": 扔掉 script / style / 导航 / 页头页脚 / 侧栏 / 表单 / 弹层, 按块级标签断段.
★ 不做正文识别算法(那个容易误伤) —— 段落够长就留, 太短的(导航词、按钮字)扔掉.
★ 输出段落是**原文**, 一个字都不改写 —— 摘要在 pick.py 里按问题挑, 这里只负责干净.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# 这些标签里面的东西一律不要（脚本/样式/交互件/装饰）
DROP = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "select",
        "option", "button", "template", "head", "nav", "footer", "aside"}
# 这些标签意味着"一段到此为止"
BLOCK = {"p", "div", "li", "td", "th", "dd", "dt", "tr", "section", "article",
         "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"}
MIN_LEN = 10          # 短于这个字数的段直接扔（导航词、按钮、面包屑）
MAX_PARA = 4000       # 单段上限，超了硬切
_SPACES = re.compile(r"[ \t\r\f\v\u00a0]+")
_BLANKS = re.compile(r"\n{2,}")


class ArticleParser(HTMLParser):
    """把 HTML 拆成标题与段落."""

    def __init__(self, min_len: int = MIN_LEN) -> None:
        super().__init__()
        self.title = ""
        self.paragraphs: list[str] = []
        self.min_len = min_len
        self._drop_depth = 0
        self._in_title = False
        self._buf: list[str] = []

    # ── 内部 ─────────────────────────────────────────────
    def _flush(self) -> None:
        text = _SPACES.sub(" ", "".join(self._buf)).strip()
        self._buf = []
        if len(text) < self.min_len:
            return
        if text in self.paragraphs:            # 页面上重复出现的块（版权/导航）只要一次
            return
        while len(text) > MAX_PARA:
            self.paragraphs.append(text[:MAX_PARA])
            text = text[MAX_PARA:]
        self.paragraphs.append(text)

    # ── HTMLParser 回调 ──────────────────────────────────
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP:
            self._drop_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:              # ★ 标题在 <head> 里, 而 head 是丢弃标签 —— 先认标题再看丢弃计数
            self.title += data
            return
        if self._drop_depth:
            return
        self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()
        self.title = _BLANKS.sub(" ", _SPACES.sub(" ", self.title)).strip()


def extract(html: str, min_len: int = MIN_LEN) -> tuple[str, list[str]]:
    """(标题, 正文段落). 解析炸了不抛 —— 返回已经收到的部分."""
    parser = ArticleParser(min_len)
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 —— 网页再脏也不该让取正文这一步整个失败
        pass
    parser.close()
    return parser.title, parser.paragraphs


def _save(url: str, title: str, paragraphs: list[str], query: str, shot: str = "",
          status: int = 0) -> None:
    """把整页正文切片落热库（切片借 rag 的算法, 向量借 rag 的嵌入件）.

    落不动不改已经拿到的正文, 但错误必须打出来 —— 不静默。
    shot 是这页的截图（有就记上）: 记了才会跟着 TTL 一起被清掉。
    status 是这页的状态码（从 取 的输出里抄; 0 = 不知道）。
    """
    if not url:
        print("[落库没成] 得给 --url, 不然这页是哪来的都不知道", file=sys.stderr)
        return
    if not paragraphs:
        print("[落库没成] 正文是空的, 没什么可落", file=sys.stderr)
        return
    try:
        import corpus
        config: dict[str, Any] = corpus.load_config()
        page = {"url": url, "title": title, "text": "\n\n".join(paragraphs),
                "来源": "直连", "shot": shot, "status": int(status)}
        with corpus.connect(config) as conn:
            corpus.ensure_schema(conn, config)
            added, reused = corpus.put_page(conn, config, query, page)
            tidied: dict[str, int] = corpus.tidy(conn, config)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"[落库没成] {error}", file=sys.stderr)
        return
    tail = "; 顺手维护 " + " ".join(f"{key} {value}" for key, value in tidied.items() if value) if any(tidied.values()) else ""
    print(f"[落库] 热库: 新增 {added} 块, 复用 {reused} 块{tail}", file=sys.stderr)


def main() -> int:
    """命令行: HTML(文件或标准输入) -> 标题 + 正文段落."""
    ap = argparse.ArgumentParser(description="正文页 -> 标题 + 正文段落")
    ap.add_argument("file", help="HTML 文件; 给 - 就从标准输入读")
    ap.add_argument("--min", type=int, default=MIN_LEN, help=f"段至少几个字(默认 {MIN_LEN}); 想滤掉导航词就调大, 如 40")
    ap.add_argument("--max", type=int, default=0, help="最多打几段(默认全给)")
    ap.add_argument("--json", action="store_true", help="出 JSON")
    ap.add_argument("--save", action="store_true", help="把正文按 rag 的算法切片落热库(要配 --url)")
    ap.add_argument("--url", default="", help="这一页的地址(落库要用, 从 取 的输出里抄)")
    ap.add_argument("--query", default="", help="这次是搜什么搜到它的(落库记一笔)")
    ap.add_argument("--status", type=int, default=0, help="这页的状态码(从 取 的输出里抄; 不填就翻同名 .meta.json, 再没有按 0)")
    args = ap.parse_args()

    if args.file == "-":
        html = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            print(f"[没这个文件] {path}")
            return 2
        html = path.read_text(encoding="utf-8", errors="replace")

    title, paragraphs = extract(html, int(args.min))
    # 状态码: 优先 --status; 没给就翻同名 .meta.json(直抓会写一份); 再没有按 0
    status = int(args.status) if args.status else 0
    if not status and args.file != "-":
        meta = Path(args.file).with_suffix(".meta.json")
        if meta.is_file():
            try:
                info: Any = json.loads(meta.read_text("utf-8"))
                status = int(info.get("status", 0) or 0)
            except (OSError, ValueError, TypeError, AttributeError):
                status = 0
    if args.save:
        shot = ""
        if args.file != "-":
            candidate = Path(args.file).parents[1] / "shots" / (Path(args.file).stem + ".jpg")
            shot = str(candidate) if candidate.is_file() else ""
        _save(str(args.url), title, paragraphs, str(args.query), shot, status)
    total, all_chars = len(paragraphs), sum(len(para) for para in paragraphs)
    if args.max > 0:
        paragraphs = paragraphs[: args.max]
    chars = sum(len(para) for para in paragraphs)
    if args.json:
        print(json.dumps({"title": title, "count": total, "chars": all_chars,
                          "shown": len(paragraphs), "paragraphs": paragraphs},
                         ensure_ascii=False, indent=2))
        return 0 if paragraphs else 1
    shown = f"（这里打了前 {len(paragraphs)} 段 / {chars} 字）" if len(paragraphs) < total else ""
    print(f"标题: {title}    正文 {total} 段 / {all_chars} 字 {shown}")
    for i, para in enumerate(paragraphs, 1):
        print(f"\n[{i}] {para}")
    return 0 if paragraphs else 1


if __name__ == "__main__":
    sys.exit(main())
