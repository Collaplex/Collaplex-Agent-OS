# -*- coding: utf-8 -*-
"""查切片器认不认得实际语料 —— 判据和真实格式对不上的话, 走错分支就白切。

对比三件事:
  ① 语料文件的真实格式（头几行长什么样）
  ② chunker 的判据认不认它（_looks_like_dialogue）
  ③ 实际走了哪条分支、切出几片
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import chunker  # noqa: E402

语料目录 = Path("/home/lou/桌面/collaplex_agent/skill/rag/corpus/hermes-history")
候选 = sorted(语料目录.glob("*.md"), key=lambda p: p.stat().st_size, reverse=True)[:6]

print("══ 一、语料真实格式（最大的几个文件，头 12 行）")
for p in 候选[:4]:
    print(f"\n  ── {p.name}  ({p.stat().st_size} 字节)")
    for 行 in p.read_text(encoding="utf-8").splitlines()[:12]:
        print(f"     {行!r}")

print("\n══ 二、判据认不认它")
认得 = 0
总数 = 0
for p in sorted(语料目录.glob("*.md")):
    try:
        文 = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    总数 += 1
    if chunker._looks_like_dialogue(文):  # type: ignore[reportPrivateUsage]
        认得 += 1
print(f"  _looks_like_dialogue 判为对话的: {认得} / {总数}  ({认得 * 100 // max(1, 总数)}%)")

print("\n══ 三、同一个文件走两条分支的差别")
p = 候选[0]
文 = p.read_text(encoding="utf-8")
按规则 = chunker.split_rules(文, ".md", 800)
按语义 = chunker.split_dialogue_semantic(文, 800)
import statistics  # noqa: E402

for 名, 片 in (("规则(split_rules)", 按规则), ("对话语义(split_dialogue_semantic)", [c for c, _ in 按语义])):
    if 片:
        长 = sorted(len(x) for x in 片)
        print(
            f"  {名:<34} {len(片):>4} 片  中位 {statistics.median(长):>5.0f}  "
            f"最小 {长[0]:>4}  最大 {长[-1]:>6}"
        )

print("\n══ 四、_looks_like_dialogue 期待什么标记")
print(f"  {chunker._DIALOGUE_MARKS!r}")  # type: ignore[reportPrivateUsage]
