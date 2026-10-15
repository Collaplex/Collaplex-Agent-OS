"""库里到底有没有"簇"? —— 295 条嵌入做一次聚类看结构。

判据:
  ① 簇内平均余弦 vs 全局平均余弦 —— 差得多说明"同簇的确实更近"（有结构）
  ② 每簇条数分布 —— 有没有天然成团的（而不是均匀摊平）
  ③ 有没有"跨簇的边" —— 同一条经验能不能同时贴着两个簇（人脑的联想边）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np

A = Path("/home/lou/桌面/collaplex_agent")
_结构: Any = json.loads((A / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
_映射 = cast("dict[str, Any]", _结构) if isinstance(_结构, dict) else {}
条 = cast("list[dict[str, Any]]", _映射.get("items", []))
矩 = np.asarray([t["vector"] for t in 条], dtype=np.float32)
规 = 矩 / np.where(np.linalg.norm(矩, axis=1, keepdims=True) == 0, 1.0,
                   np.linalg.norm(矩, axis=1, keepdims=True))
sim = 规 @ 规.T
np.fill_diagonal(sim, np.nan)
print(f"库: {len(条)} 条, 全局两两平均余弦 = {np.nanmean(sim):.3f}")

# 简易 k-means（numpy, 无依赖）
def 聚类(x: np.ndarray[Any, np.dtype[np.float32]], k: int, 轮: int = 60,
         种: int = 7) -> np.ndarray[Any, np.dtype[np.int64]]:
    随 = np.random.default_rng(种)
    心 = x[随.choice(len(x), k, replace=False)]
    for _ in range(轮):
        距 = ((x[:, None, :] - 心[None, :, :]) ** 2).sum(-1)
        标 = 距.argmin(1)
        for i in range(k):
            同 = x[标 == i]
            if len(同):
                心[i] = 同.mean(0)
    return 标


标 = 聚类(规, 15)
print("\n① 簇内 vs 全局:")
print(f"   {'簇':>3} {'条数':>4}  簇内平均余弦")
for i in range(15):
    内 = sim[np.ix_(标 == i, 标 == i)]
    均 = float(np.nanmean(内)) if 内.size else float("nan")
    if np.isnan(均):
        continue
    print(f"   {i:>3} {int((标 == i).sum()):>4}  {均:.3f}")

# ② 条数分布
c = np.bincount(标, minlength=15)
print(f"\n② 每簇条数: 最大 {c.max()} / 最小 {c.min()} / 中位 {int(np.median(c))}")
print(f"   有点成团的簇（≥20 条）: {int((c >= 20).sum())} 个, 占 {int(c[c >= 20].sum())}/{len(条)} 条")

# ③ 跨簇边: 每条距最近的 2 个簇心都差不多近 = 它骑在两个簇上
print("\n③ 跨簇的边（骑在两个簇上的条目）:")
跨 = 0
样例: list[tuple[float, str]] = []
for i, v in enumerate(规):
    距 = np.linalg.norm(规[标 == i].mean(0) - v)
    次远 = sorted(np.linalg.norm(np.stack([规[标 == j].mean(0) for j in range(15) if j != 标[i]]) - v, axis=1))[0]
    if 次远 - 距 < 0.15:  # 离本簇和隔壁簇几乎一样近
        跨 += 1
        样例.append((次远 - 距, str(条[i]["text"])[:70].replace("\n", " ")))
print(f"   骑车在两簇上的: {跨}/{len(条)} ({跨 / len(条) * 100:.0f}%)")
for 差, 文 in sorted(样例)[:4]:
    print(f"     {差:+.3f}  {文}")
