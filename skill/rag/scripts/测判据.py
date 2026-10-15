# -*- coding: utf-8 -*-
"""测 _looks_like_dialogue 改前改后 —— 两个指标一起看。

  ① 该认没认: 30 个真对话语料, 有没有全认出来
  ② 不该认却认: 项目里的普通 .md, 会不会被误判成对话（误判会让文档被按问答对切, 切坏）

单一指标会骗人: 全判 True 能拿 100% 的"该认没认", 但普通文档全被切坏。
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import chunker  # noqa: E402

项目根 = Path("/home/lou/桌面/collaplex_agent")
语料目录 = 项目根 / "skill/rag/corpus/hermes-history"


def 旧判据(text: str) -> bool:
    """改前的实现: 只看前 80 行。"""
    头 = text.splitlines()[:80]
    return sum(1 for line in 头 if line.strip() in chunker._DIALOGUE_MARKS) >= 2  # type: ignore[reportPrivateUsage]


def 跑(判据: Callable[[str], bool], 名: str) -> tuple[int, int, int]:
    该认 = 对话文件 = 误判 = 0
    for p in sorted(语料目录.glob("*.md")):
        文 = p.read_text(encoding="utf-8")
        对话文件 += 1
        if 判据(文):
            该认 += 1
    for p in sorted(项目根.glob("skill/*/SKILL.md")) + sorted(项目根.glob("*.md")) + sorted(项目根.glob("skill/rag/corpus/*.md")):
        try:
            文 = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if 判据(文):
            误判 += 1
    print(f"  {名:<16} ① 该认没认 {该认}/{对话文件}   ② 不该认却认 {误判}")
    return 该认, 对话文件, 误判


print("══ 两个指标一起看（只报①会骗人：全判 True 也能拿满分）")
旧 = 跑(旧判据, "改前(前80行)")
新 = 跑(chunker._looks_like_dialogue, "改后(全文数)")  # type: ignore[reportPrivateUsage]

print()
print("══ 改前的差别（漏判的 2 个文件）")
for p in sorted(语料目录.glob("*.md")):
    文 = p.read_text(encoding="utf-8")
    if not 旧判据(文) and chunker._looks_like_dialogue(文):  # type: ignore[reportPrivateUsage]
        print(f"  {p.name}  ({p.stat().st_size} 字节)")
        头 = 文.splitlines()[:80]
        标记数 = sum(1 for line in 头 if line.strip() in chunker._DIALOGUE_MARKS)  # type: ignore[reportPrivateUsage]
        print(f"     前 80 行里只有 {标记数} 个标记（<2 就漏判）；全文有 {文.count('**用户**')} 个『**用户**』")

print()
print("══ ③ 端到端: 对话文件现在走哪条路、切出来多大")
import statistics  # noqa: E402

p = max(语料目录.glob("*.md"), key=lambda x: x.stat().st_size)
文 = p.read_text(encoding="utf-8")
print(f"  {p.name} ({p.stat().st_size} 字节)")
for 名, 片 in (
    ("规则(split_rules)", chunker.split_rules(文, ".md", 800)),
    ("语义入口(split_file_semantic)", [c for c, _ in chunker.split_file_semantic(str(p), 800)]),
):
    长 = sorted(len(x) for x in 片)
    短 = sum(1 for x in 长 if x < 60)
    print(f"     {名:<32} {len(片):>4} 片  中位 {statistics.median(长):>5.0f}  <60字 {短}")
