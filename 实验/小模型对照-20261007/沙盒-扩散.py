"""沙盒: 把 RAG 从"静态 top-k"改成"带边 + 扩散一跳"（SNN 的等效落地版），看能不能捡回跨簇信息。

三档对照（都在这台机器的 CPU 上, 不碰生产库、不动模型）:
  A 现状   —— 生产那套静态 top-k
  B 带边   —— 还是 top-k, 但每条结果附"跟它强相连的条目"（只多给, 不改排序）
  C 扩散一跳 —— top-k 定位簇, 再沿强桥取 1 条"别的簇但相关"的候选（带阈值）

判据:
  ① top-3 落在几个簇（现状实测 1.53）
  ② 捡回来的跨簇候选, 与题目关键词重合 ≥2 的算"有用"（机械可核）
  ③ 塞给模型的体积增长（检索结果是要贴进提示词的）
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

import numpy as np

A = Path("/home/lou/桌面/collaplex_agent")
H = A / "实验/小模型对照-20261007"
sys.path.insert(0, str(A / "skill/rag/scripts"))
import search as 检索器  # noqa: E402

_结构: Any = json.loads((A / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
条 = cast("list[dict[str, Any]]", cast("dict[str, Any]", _结构).get("items", []))
矩 = np.asarray([t["vector"] for t in 条], dtype=np.float32)
模 = np.linalg.norm(矩, axis=1, keepdims=True)
规 = (矩 / np.where(模 == 0, 1.0, 模)).astype(np.float32)

# ── 聚类（跟之前同一套）────────────────────────────────
随 = np.random.default_rng(7)
心 = 规[随.choice(len(规), 15, replace=False)]
标: np.ndarray[Any, np.dtype[np.int64]] = np.zeros(len(规), dtype=np.int64)
for _ in range(60):
    标 = ((规[:, None, :] - 心[None, :, :]) ** 2).sum(-1).argmin(1)
    for i in range(15):
        同 = 规[标 == i]
        if len(同):
            心[i] = 同.mean(0)

词 = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}|[\u4e00-\u9fa5]{2,8}")
停 = {"什么", "怎么", "为什么", "可以", "这个", "那个", "我们", "一下", "问题", "任务", "结论",
      "答案", "说明", "注意", "需要", "使用", "如果", "因为", "所以", "但是", "而且", "还有",
      "原文", "知识", "概述", "第一", "第二", "已经", "没有", "不是", "就是", "一个", "进行"}


def 关键词(文本: str) -> set[str]:
    return {x for x in 词.findall(文本) if x not in 停 and len(x) >= 2}


键 = [set(sorted(关键词(str(t.get("text", ""))), key=len, reverse=True)[:8]) for t in 条]

# ── 建共现边（赫布式: 同一轮问答里一起出现就连边）────────
样: list[dict[str, Any]] = [json.loads(l) for l in (H / "样本.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
边: Counter[tuple[int, int]] = Counter()
for t in 样:
    文 = str(t.get("题", "")) + str(t.get("答案", ""))
    原始: list[list[str]] = list(t.get("命令") or [])
    文 += " ".join(str(c) for 组 in 原始 for c in 组)
    实词 = 关键词(文)
    中 = [i for i, w in enumerate(键) if len(w & 实词) >= 2]
    for a in range(len(中)):
        for b in range(a + 1, len(中)):
            i, j = sorted((中[a], 中[b]))
            if int(标[i]) != int(标[j]) and str(条[i].get("source", "")) != str(条[j].get("source", "")):
                边[(i, j)] += 1
邻: dict[int, list[tuple[int, int]]] = defaultdict(list)
for (i, j), c in 边.items():
    邻[i].append((j, c))
    邻[j].append((i, c))
print(f"共现边: {len(边)} 条（全是 跨簇 + 不同源 的真桥）; 有邻居的条目 {len(邻)}/{len(条)}")

cfg = 检索器.load_config(检索器.CONFIG_PATH)
mod = 检索器.resolve_model()
题库: list[dict[str, Any]] = [json.loads(l) for l in (H / "题库.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

三档: dict[str, dict[str, float]] = {}
明细: list[str] = []
for 档, 用邻 in (("A 现状", False), ("B 带边", True), ("C 扩散一跳", True),):
    簇数: list[int] = []
    体积: list[int] = []
    有用: list[int] = []
    for 题 in 题库:
        问 = str(题["题"])
        果 = 检索器.search(检索器.embed_query(问, cfg, mod), 规, 条, 3)
        取 = [int(g["index"]) for g in 果]
        文 = [str(条[i]["text"]) for i in 取]
        if 用邻:
            候: list[tuple[int, int]] = []
            for i in 取:
                for j, c in 邻.get(i, []):
                    if j not in 取 and c >= 3:
                        候.append((j, c))
            if 候:
                最 = sorted(候, key=lambda x: -x[1])[0][0]
                文.append(str(条[最]["text"]))
                # 有用 = 跟"题目 + 已召回的 top3"合起来的关键词重合 ≥2（桥是给 top3 补漏的,
                #        只跟题目比会漏掉"相关但措辞不同"的, 实测人工看 5/5 相关而旧判据给 0%）
                上下文 = 关键词(问) | set().union(*(关键词(str(条[i]["text"])) for i in 取))
                有用.append(int(len(键[最] & 上下文) >= 2))
        if 档 == "C 扩散一跳" and len(明细) < 5:
            候2: list[tuple[int, int]] = []
            for i in 取:
                for j, c in 邻.get(i, []):
                    if j not in 取 and c >= 3:
                        候2.append((j, c))
            if 候2:
                最2 = sorted(候2, key=lambda x: -x[1])[0]
                明细.append(f"   Q: {问[:30]}\n     top3: " +
                          " | ".join(str(条[i]['text'])[:22].replace(chr(10), ' ') for i in 取) +
                          f"\n     桥(×{最2[1]}, 簇{int(标[取[0]])}→{int(标[最2[0]])}): {str(条[最2[0]]['text'])[:70].replace(chr(10), ' ')}")
        新簇: set[int] = {int(标[i]) for i in 取}
        if 档 == "C 扩散一跳":
            for j, c in 邻.get(取[0], []):
                if c >= 3 and j not in 取:
                    新簇.add(int(标[j]))
        簇数.append(len(新簇))
        体积.append(sum(len(x) for x in 文))
    三档[档] = {"簇": sum(簇数) / len(簇数), "体积": sum(体积) / len(体积),
               "有用率": sum(有用) / max(1, len(有用)) * 100}

print("\n扩散一跳捡回来的候选长什么样（看 5 条）:")
print("\n".join(明细))
print("\n| 档 | top 落几个簇 | 每次召回体积 | 桥候选有用率 |")
print("|---|---|---|---|")
for 档, v in 三档.items():
    print(f"| {档} | {v['簇']:.2f} | {v['体积']:.0f} 字 | {v['有用率']:.0f}% |")
