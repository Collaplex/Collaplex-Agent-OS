"""给臂 H 预生成"每道硬题会拿到什么样的桥候选" —— 落成 桥候选.json。

每项: {题号, 问, top3:[文本...], 桥:{文本, 权重, 簇从, 簇到, 关键实体}}
关键实体 = 桥候选里、既不在 top3 里也不是停用词的词 —— 用来机械判"它到底用没用上这条桥"。
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
      "原文", "知识", "概述", "第一", "第二", "已经", "没有", "不是", "就是", "一个", "进行",
      "用户", "要求", "询问", "告知", "系统", "分析", "本机", "产出", "声明"}


def 关键词(文: str) -> set[str]:
    return {x for x in 词.findall(文) if x not in 停 and len(x) >= 2}


键 = [set(sorted(关键词(str(t.get("text", ""))), key=len, reverse=True)[:8]) for t in 条]

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

cfg = 检索器.load_config(检索器.CONFIG_PATH)
mod = 检索器.resolve_model()
题库: list[dict[str, Any]] = [json.loads(l) for l in (H / "题库.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
出: list[dict[str, Any]] = []
for 题 in 题库:
    问 = str(题["题"])
    果 = 检索器.search(检索器.embed_query(问, cfg, mod), 规, 条, 3)
    取 = [int(g["index"]) for g in 果]
    top3 = [str(条[i]["text"])[:400] for i in 取]
    候: list[tuple[int, int]] = []
    for i in 取:
        for j, c in 邻.get(i, []):
            if j not in 取 and c >= 3:
                候.append((j, c))
    if not 候:
        出.append({"号": 题["号"], "问": 问, "top3": top3, "桥": None})
        continue
    j, c = sorted(候, key=lambda x: -x[1])[0]
    上: set[str] = set()
    for x in top3:
        上 |= 关键词(x)
    上 |= 关键词(问)
    新词 = sorted(键[j] - 上, key=len, reverse=True)[:4]
    出.append({"号": 题["号"], "问": 问, "top3": top3,
              "桥": {"文本": str(条[j]["text"])[:400], "权重": c,
                     "簇从": int(标[取[0]]), "簇到": int(标[j]), "新实体": [w for w in 新词 if len(w) >= 3]}})

(H / "桥候选.json").write_text(json.dumps(出, ensure_ascii=False, indent=1), encoding="utf-8")
有 = [x for x in 出 if x["桥"]]
print(f"题库 {len(出)} 题, 有桥候选的 {len(有)} 题 → 桥候选.json")
for x in 有[:8]:
    桥 = cast("dict[str, Any]", x["桥"])
    print(f"   题{x['号']:<3} 桥×{桥['权重']:<3} 簇{桥['簇从']}→{桥['簇到']}  "
          f"新实体{桥['新实体']}  {str(桥['文本'])[:46]}".replace(chr(10), " "))
