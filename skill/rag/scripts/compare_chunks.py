# -*- coding: utf-8 -*-
"""对比对话切片改前改后 —— 一问一答切法到底好多少。

旧: 攒到 chunk_size 就断（把两对问答混一片, 或轮到就断）
新: 一问一答为一个单元, 短的并、长的拆
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import chunker  # noqa: E402

语料 = Path("/home/lou/桌面/collaplex_agent/skill/rag/corpus/hermes-history")
文件 = sorted(语料.glob("*.md"), key=lambda p: p.stat().st_size, reverse=True)[:10]


def 统计(名: str, 片: list[str]) -> None:
    if not 片:
        print(f"  {名:<26} 空")
        return
    长 = sorted(len(x) for x in 片)
    短 = sum(1 for x in 长 if x < 60)
    print(
        f"  {名:<26} {len(片):>4} 片  中位 {statistics.median(长):>5.0f}  "
        f"最小 {长[0]:>4}  最大 {长[-1]:>6}   <60字: {短:>3} ({短 * 100 // len(长)}%)"
    )


print(f"══ 抽 {len(文件)} 个最大的会话文件")
print()
print("  ── 新切法: 一问一答为一个单元（min_chunk=280, max_chunk=2000）")
新总: list[str] = []
for p in 文件:
    文 = p.read_text(encoding="utf-8")
    片 = chunker._split_dialogue(文, 800, 2000, 280)  # type: ignore[reportPrivateUsage]
    新总.extend(片)
统计("合计", 新总)

print()
print("  ── 旧切法: 攒到 800 就断（min_chunk=0）")
旧总: list[str] = []
for p in 文件:
    文 = p.read_text(encoding="utf-8")
    片 = chunker._split_dialogue(文, 800, 2000, 0)  # type: ignore[reportPrivateUsage]
    旧总.extend(片)
统计("合计", 旧总)

print()
print("══ 具体长什么样（第一个文件的前 6 片）")
文 = 文件[0].read_text(encoding="utf-8")
for i, 片 in enumerate(chunker._split_dialogue(文, 800, 2000, 280), 1):  # type: ignore[reportPrivateUsage]
    if i > 6:
        break
    首行 = 片.strip().splitlines()[0][:64]
    print(f"  [{len(片):>5}字] {首行!r}")

print()
print("══ 诚实检查: 有没有把不该并的并了（一个切片里出现两个『**用户**』= 两对被混了）")
混 = 0
for 片 in 新总:
    if 片.count("**用户**") > 1:
        混 += 1
print(f"  含 2 个以上『**用户**』的切片: {混} / {len(新总)}  ({混 * 100 // max(1, len(新总))}%)")
print("  （>0 是正常的: 太短的对会被并起来, 起点仍是问题, 检索时能带出答案就是对的）")
