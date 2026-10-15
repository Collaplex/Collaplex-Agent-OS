"""SNN 设想的前置问题: 我们的数据里有没有"共现信号"（赫布式的边长出来的原料）。

做法（全是现成数据, 零模型）:
  ① 把 295 条库条目各自抽一组关键词（实体/名词）
  ② 扫 287 轮真实样本（问+答+命令），看每一轮"命中了哪几条库条目"
  ③ 同一轮里一起出现的条目两两连一条边 —— 数一数:
     - 能连出多少条边（含跨簇的）
     - 跨簇边占全部边的比例（现在静态跨簇只有 5%）
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

import numpy as np

A = Path("/home/lou/桌面/collaplex_agent")
H = A / "实验/小模型对照-20261007"

_结构: Any = json.loads((A / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
条 = cast("list[dict[str, Any]]", cast("dict[str, Any]", _结构).get("items", []))
矩 = np.asarray([t["vector"] for t in 条], dtype=np.float32)
模 = np.linalg.norm(矩, axis=1, keepdims=True)
规 = (矩 / np.where(模 == 0, 1.0, 模)).astype(np.float32)
随 = np.random.default_rng(7)
心 = 规[随.choice(len(规), 15, replace=False)]
标: np.ndarray[Any, np.dtype[np.int64]] = np.zeros(len(规), dtype=np.int64)
for _ in range(60):
    标 = ((规[:, None, :] - 心[None, :, :]) ** 2).sum(-1).argmin(1)
    for i in range(15):
        同 = 规[标 == i]
        if len(同):
            心[i] = 同.mean(0)
标 = cast("np.ndarray[Any, np.dtype[np.int64]]", 标)

# ① 关键词: 从条目文本里抽"像实体的词"——中文用 2~6 字的名词块, 加粗/引号里的优先
词 = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}|[\u4e00-\u9fa5]{2,8}")
停 = {"什么", "怎么", "为什么", "可以", "这个", "那个", "我们", "一下", "问题", "任务", "结论",
      "答案", "说明", "注意", "需要", "使用", "如果", "因为", "所以", "但是", "而且", "还有",
      "原文", "知识", "概述", "第一", "第二", "已经", "没有", "不是", "就是", "一个", "进行"}
键: list[set[str]] = []
for t in 条:
    w = {x for x in 词.findall(str(t.get("text", ""))) if x not in 停 and len(x) >= 2}
    键.append(set(sorted(w, key=len, reverse=True)[:8]))

# ② 逐轮看命中
样: list[dict[str, Any]] = [json.loads(l) for l in (H / "样本.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
边: Counter[tuple[int, int]] = Counter()
轮内跨度: list[int] = []
for t in 样:
    文 = str(t.get("题", "")) + str(t.get("答案", ""))
    原始: list[list[str]] = list(t.get("命令") or [])
    文 += " ".join(str(c) for 组 in 原始 for c in 组)
    中 = [i for i, w in enumerate(键) if w and len(w & set(词.findall(文))) >= 2]
    if len(中) < 2:
        continue
    轮内跨度.append(len({int(标[i]) for i in 中}))
    for a in range(len(中)):
        for b in range(a + 1, len(中)):
            键对: tuple[int, int] = (min(中[a], 中[b]), max(中[a], 中[b]))
            边[键对] += 1

print(f"① 库条目关键词抽好: {len(条)} 条")
print(f"② 有共现信号的轮: {len(轮内跨度)}/{len(样)} 轮（每轮至少命中 2 条库条目）")
print(f"   一轮里命中的条目平均横跨 {sum(轮内跨度) / max(1, len(轮内跨度)):.2f} 个簇")
# 真桥 vs 同源边: 同源 = 同一次问答的三种形态(原文/概述/知识)被连起来, 那是"同一件事"
def 同源(i: int, j: int) -> bool:
    a, b = str(条[i].get("source", "")), str(条[j].get("source", ""))
    return bool(a) and a == b


print(f"③ 共现边: 共 {len(边)} 条")
跨 = sum(1 for (a, b) in 边 if int(标[a]) != int(标[b]))
print(f"   其中跨簇边: {跨} 条 ({跨 / max(1, len(边)) * 100:.0f}%)  ← 静态库现在只有 5%")
重 = [(c, a, b) for (a, b), c in 边.items() if c >= 3]
print(f"   重复出现 ≥3 次的强边: {len(重)} 条")
真桥 = [k for k in 边 if int(标[k[0]]) != int(标[k[1]]) and not 同源(k[0], k[1])]
同源边 = [k for k in 边 if 同源(k[0], k[1])]
print(f"   ★ 拆一拆: 同源边(同一轮问答的 原文/概述/知识 互相连) {len(同源边)} 条")
print(f"   ★ 真桥 = 跨簇 且 不同源: {len(真桥)} 条 ({len(真桥) / max(1, len(边)) * 100:.0f}%)")
强桥 = [k for k in 真桥 if 边[k] >= 3]
print(f"   ★ 其中重复 ≥3 次的强桥: {len(强桥)} 条")
for k in sorted(强桥, key=lambda x: -边[x])[:6]:
    a, b = k
    print(f"     ×{边[k]}  [{str(条[a]['text'])[:30].replace(chr(10), ' ')}] ↔ [{str(条[b]['text'])[:30].replace(chr(10), ' ')}] (簇 {int(标[a])}↔{int(标[b])})")
print()
for c, a, b in sorted(重, reverse=True)[:3]:
    print(f"     ×{c}  [{str(条[a]['text'])[:26].replace(chr(10), ' ')}] ↔ [{str(条[b]['text'])[:26].replace(chr(10), ' ')}]  "
          f"(簇 {int(标[a])}↔{int(标[b])})")
