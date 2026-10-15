"""臂 H 结论: 给了"桥"到底用没用上。

判据:
  ① 桥候选的"新实体"（只在桥里出现、top3 和题目里都没有的词）在答案里出现了几个
     —— 无桥那档如果也出现，说明是它自己想到的；只有有桥那档出现，才算"桥被用上了"
  ② 答案长 / 命令数 / 真跑 有没有变化
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

H = Path(__file__).resolve().parent
条们: list[dict[str, Any]] = []
for 行 in (H / "样本.jsonl").read_text(encoding="utf-8").splitlines():
    if 行.strip():
        try:
            条们.append(json.loads(行))
        except json.JSONDecodeError:
            pass

H臂 = [t for t in 条们 if t["臂"] == "H"]
表: dict[int, dict[str, Any]] = {}
for x in json.loads((H / "桥候选.json").read_text(encoding="utf-8")):
    表[int(x["号"])] = x

按题: dict[int, dict[str, dict[str, Any]]] = {}
for t in H臂:
    按题.setdefault(int(t["题号"]), {})[str(t["上文形态"])] = t

print("| 题 | 桥的新实体 | 无桥档用上 | 有桥档用上 | 答案长 | 命令数 |")
print("|---|---|---|---|---|---|")
无中用 = 有中用 = 总 = 0
for 号 in sorted(按题):
    g = 按题[号]
    if "无桥" not in g or "有桥" not in g:
        continue
    桥: dict[str, Any] = cast("dict[str, Any]", (表.get(号) or {}).get("桥") or {})
    新词: list[str] = [str(w) for w in cast("list[Any]", 桥.get("新实体") or [])]
    if not 新词:
        continue

    def 用上(条: dict[str, Any]) -> int:
        文 = str(条.get("答案", ""))
        return sum(1 for w in 新词 if w in 文)

    a, b = g["无桥"], g["有桥"]
    ua, ub = 用上(a), 用上(b)
    总 += 1
    无中用 += int(ua > 0)
    有中用 += int(ub > 0)
    print(f"| {号} | {', '.join(新词[:3])[:38]} | {ua} | {ub} | {a['答案长']}→{b['答案长']}字 | "
          f"{a['命令数']}→{b['命令数']} |")

print(f"\n**汇总**: 有桥档用上 {有中用}/{总}，无桥档自己想到 {无中用}/{总}")
加长 = [int(按题[号]["有桥"]["答案长"]) - int(按题[号]["无桥"]["答案长"]) for 号 in 按题
        if "无桥" in 按题[号] and "有桥" in 按题[号]]
if 加长:
    print(f"答案长度变化: {sum(加长) / len(加长):+.0f} 字/题")
真跑 = [号 for 号 in 按题 if "无桥" in 按题[号] and "有桥" in 按题[号]]
print(f"真跑率: 无桥 {sum(1 for 号 in 真跑 if 按题[号]['无桥']['真跑过'])}/{len(真跑)} → "
      f"有桥 {sum(1 for 号 in 真跑 if 按题[号]['有桥']['真跑过'])}/{len(真跑)}")

print("\n**逐条例子（有桥档答案里用上桥的地方）**")
for 号 in sorted(按题):
    g = 按题[号]
    if "有桥" not in g:
        continue
    桥 = cast("dict[str, Any]", (表.get(号) or {}).get("桥") or {})
    新词 = [str(w) for w in cast("list[Any]", 桥.get("新实体") or [])]
    文 = str(g["有桥"].get("答案", ""))
    命中 = [w for w in 新词 if w in 文]
    if 命中:
        段 = min((文.find(w) for w in 命中 if 文.find(w) >= 0), default=0)
        print(f"   题{号}: 用上 {命中}")
        print(f"      …{文[max(0, 段 - 60):段 + 80].replace(chr(10), ' ')}…")
