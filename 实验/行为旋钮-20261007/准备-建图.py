"""行为旋钮实验 · 建图 + 预检索

图：节点＝记忆库里的条目（用现成向量），边＝"同一轮任务里一起出现"的共现边（只留不同源的＝真桥）。
另外给每条情境预先算好：top-3 节点（档②）＋ 沿边一跳的桥节点（档③）。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import numpy as np

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent

# ── 节点：记忆库 ───────────────────────────────────────────────
库原: Any = json.loads((项目 / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
_列: list[Any] = cast("list[Any]", 库原) if isinstance(库原, list) else cast("list[Any]", 库原.get("items", []))
条: list[dict[str, Any]] = [cast("dict[str, Any]", x) for x in _列 if isinstance(x, dict)]
节点向 = np.asarray([cast("list[float]", x.get("vector") or []) for x in 条], dtype=np.float32)
节点文 = [str(x.get("text", "")) for x in 条]
节点源 = [str(x.get("source", "")) for x in 条]
节点向 = 节点向 / (np.linalg.norm(节点向, axis=1, keepdims=True) + 1e-9)
print(f"节点 {len(条)} 个, 向量 {节点向.shape}")

# ── 关键词 ─────────────────────────────────────────────────────
停 = {"这个", "那个", "什么", "怎么", "可以", "不是", "就是", "一个", "现在", "已经", "如果", "因为",
      "所以", "但是", "然后", "还是", "没有", "需要", "能不能", "问题", "结果", "时候", "这里", "我们",
      "本机", "命令", "执行", "输出", "文件", "目录", "用户", "要求", "建议", "使用", "可能", "应该"}
词形 = re.compile(r"[\u4e00-\u9fff]{2,4}|[A-Za-z_][A-Za-z0-9_.\-]{1,15}")


def 关键词(文: str) -> set[str]:
    return {w for w in 词形.findall(文) if w not in 停}


节点词 = [关键词(t) for t in 节点文]

# ── 共现边：扫真实样本，同一轮里一起出现的条目连边 ──────────────
样 = [json.loads(x) for x in (源 / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
边权: defaultdict[tuple[int, int], int] = defaultdict(int)
命中轮 = 0
for 行 in 样:
    轮文 = f"{行.get('题', '')} {行.get('答案', '')} {json.dumps(行.get('命令'), ensure_ascii=False)}"
    词集 = 关键词(轮文)
    if len(词集) < 3:
        continue
    中 = [i for i, 词 in enumerate(节点词) if len(词 & 词集) >= 2]
    if len(中) < 2:
        continue
    命中轮 += 1
    for a in range(len(中)):
        for b in range(a + 1, len(中)):
            i, j = 中[a], 中[b]
            if 节点源[i] == 节点源[j]:      # 同源的三种形态不算桥
                continue
            边权[(i, j)] += 1
print(f"有共现信号的轮: {命中轮}/{len(样)}  原边 {len(边权)}")
强边 = {k: v for k, v in 边权.items() if v >= 3}
print(f"强边(重复≥3): {len(强边)}")
邻: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)
for (i, j), w in 强边.items():
    邻[i].append((j, w))
    邻[j].append((i, w))
for i in 邻:
    邻[i].sort(key=lambda x: -x[1])

# ── 给每条情境预检索 ───────────────────────────────────────────
数 = np.load(这里 / "数据集.npz", allow_pickle=False)
情向 = 数["情境"]
相似 = 情向 @ 节点向.T
前3 = np.argsort(-相似, axis=1)[:, :3]
桥: list[list[int]] = []
for r in range(情向.shape[0]):
    候: list[tuple[int, int]] = []
    for i in 前3[r]:
        for j, _w in 邻.get(int(i), [])[:3]:
            if j not in 前3[r]:
                候.append((j, _w))
    候.sort(key=lambda x: -x[1])
    seen: set[int] = set()
    取: list[int] = []
    for j, _w in 候:
        if j not in seen:
            seen.add(j)
            取.append(j)
    桥.append(取[:2])
np.savez_compressed(这里 / "图.npz", 节点向=节点向, 前3=前3.astype(np.int64),
                    桥=np.asarray([x + [-1] * (2 - len(x)) for x in 桥], dtype=np.int64))
(这里 / "节点文.json").write_text(json.dumps(节点文, ensure_ascii=False), encoding="utf-8")
print(f"前3 平均相似 {相似[np.arange(len(情向)), 前3[:, 0]].mean():.3f}；有桥的情境 {sum(1 for x in 桥 if x)}/{len(桥)}")
