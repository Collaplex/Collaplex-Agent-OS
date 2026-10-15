"""把"臂 B 变慢"拆开: 是题不一样、还是答案变长、还是机器降频、还是检索变慢。

判据: 同一道题在两个循环里的用时对比 —— 题的难度不变, 时间差才是真"变慢"。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = Path("/home/lou/桌面/collaplex_agent")


def 读(路: Path) -> list[dict[str, Any]]:
    出: list[dict[str, Any]] = []
    for 行 in 路.read_text(encoding="utf-8").splitlines():
        if 行.strip():
            try:
                出.append(json.loads(行))
            except json.JSONDecodeError:
                pass
    return 出


条们 = 读(HERE / "样本.jsonl")
B = [t for t in 条们 if t["臂"] == "B"]
A = [t for t in 条们 if t["臂"] == "A"]

print("=== ① 臂B 用时 by 题（同一道题各轮用时）===")
按题: dict[int, list[tuple[int, float, int, int]]] = defaultdict(list)
for i, t in enumerate(B):
    按题[int(t["题号"])].append((i + 1, float(t["用时"]), int(t["答案长"]), int(t["命令数"])))
慢题 = sorted(按题.items(), key=lambda kv: -sum(x[1] for x in kv[1]) / len(kv[1]))[:8]
for 号, 组 in 慢题:
    时 = [f"{x[1]:.0f}s(轮{x[0]},答{x[2]}字,令{x[3]})" for x in 组]
    print(f"  题{号:<3} 均{sum(x[1] for x in 组) / len(组):5.1f}s  {', '.join(时)}")

print("\n=== ② 同一道题: 第一循环 vs 第二循环（题难度不变）===")
在B两轮: list[str] = []
for 号, 组 in sorted(按题.items()):
    一 = [x for x in 组 if x[0] <= 58]
    二 = [x for x in 组 if x[0] > 58]
    if 一 and 二:
        在B两轮.append(f"  题{号:<3} 一轮{sum(x[1] for x in 一) / len(一):5.1f}s → 二轮{sum(x[1] for x in 二) / len(二):5.1f}s  (答{一[0][2]}→{二[0][2]}字)")
print("\n".join(在B两轮) if 在B两轮 else "  (没有两边都出现的题)")

print("\n=== ③ 用时 vs 答案长/命令数（相关性）===")
def 相关(对们: list[tuple[float, float]]) -> float:
    n = len(对们)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in 对们) / n
    my = sum(p[1] for p in 对们) / n
    up = sum((p[0] - mx) * (p[1] - my) for p in 对们)
    dx = sum((p[0] - mx) ** 2 for p in 对们) ** 0.5
    dy = sum((p[1] - my) ** 2 for p in 对们) ** 0.5
    return up / (dx * dy) if dx and dy else 0.0

for 臂, 组 in (("A", A), ("B", B)):
    print(f"  臂{臂}: 用时~答案长 r={相关([(float(t['用时']), float(t['答案长'])) for t in 组]):+.2f}"
          f" | 用时~命令数 r={相关([(float(t['用时']), float(t['命令数'])) for t in 组]):+.2f}")

print("\n=== ④ 首轮 vs 末轮（臂B 前后各 15 轮，看整体趋势）===")
头 = B[:15]
尾 = B[-15:]
print(f"  头15轮: 均{sum(float(t['用时']) for t in 头) / len(头):.1f}s 均答{sum(int(t['答案长']) for t in 头) / len(头):.0f}字"
      f" 均命令{sum(int(t['命令数']) for t in 头) / len(头):.1f}")
print(f"  尾15轮: 均{sum(float(t['用时']) for t in 尾) / len(尾):.1f}s 均答{sum(int(t['答案长']) for t in 尾) / len(尾):.0f}字"
      f" 均命令{sum(int(t['命令数']) for t in 尾) / len(尾):.1f}")
print(f"  头15轮题号: {[t['题号'] for t in 头]}")
print(f"  尾15轮题号: {[t['题号'] for t in 尾]}")

print("\n=== ⑤ 显卡/内存采样（每 20 轮一次）===")
采 = 读(HERE / "采样.jsonl")
for s in 采:
    print(f"  {s.get('时间', '')[-8:]}  显卡={s.get('显卡', '')}  可用内存={s.get('可用内存', '')}M")
if not 采:
    print("  (没采到)")

print("\n=== ⑥ RAG 那条: 检索是不是在热路上、耗时多少 ===")
有库 = [t for t in 条们 if re.search(r"资料库|原文|库", str(t["题"]))]
print(f"  题库里 「库检索」类题（会真走 rag）: {len(有库)} 轮")
# 从事件里找 rag 痕迹 & 用它当"检索发生"的代理指标
拉格 = [t for t in 条们 if "rag" in str(t.get("挑中skill", ""))]
print(f"  挑中 rag skill 的轮数: {len(拉格)}")
if 拉格:
    print(f"  这些轮均用时 {sum(float(t['用时']) for t in 拉格) / len(拉格):.1f}s"
          f"（全体均 {sum(float(t['用时']) for t in 条们) / len(条们):.1f}s）")
