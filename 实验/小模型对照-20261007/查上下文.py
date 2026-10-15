"""臂 E 结论: 带上文 vs 不带上文 —— 同一批题成对比较, 慢在哪一段。

变量只有一个: 上文有没有(遍1 空, 遍2 带 8 轮约 3000 字的固定上文)。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
条们: list[dict[str, Any]] = []
for 行 in (HERE / "样本.jsonl").read_text(encoding="utf-8").splitlines():
    if 行.strip():
        try:
            条们.append(json.loads(行))
        except json.JSONDecodeError:
            pass

E = [t for t in 条们 if t["臂"] == "E"]
对: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
for t in E:
    对[int(t["题号"])][int(t["遍"])] = t

print("=== 成对比较（同一道题: 无上文 → 带上文）===")
print("| 题 | 用时 | 答案长 | 到挑完耗时(判定+检索) |")
print("|---|---|---|---|")
加时: list[float] = []
加字: list[int] = []
提skill: list[tuple[float, float]] = []
for 号 in sorted(对):
    组 = 对[号]
    if 1 not in 组 or 2 not in 组:
        continue
    无, 有 = 组[1], 组[2]
    加时.append(float(有["用时"]) - float(无["用时"]))
    加字.append(int(有["答案长"]) - int(无["答案长"]))
    a = 无.get("提skill耗时")
    b = 有.get("提skill耗时")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        提skill.append((float(a), float(b)))
    print(f"| {号} | {无['用时']}→{有['用时']}s | {无['答案长']}→{有['答案长']}字 "
          f"| {a if a is not None else '—'}→{b if b is not None else '—'}s |")

n = len(加时)
print(f"\n平均: 用时 {sum(加时) / n:+.1f}s | 答案长 {sum(加字) / n:+.0f}字")
if 提skill:
    print(f"到挑完(判定+检索那一段): 无上文均 {sum(x[0] for x in 提skill) / len(提skill):.1f}s"
          f" → 带上文均 {sum(x[1] for x in 提skill) / len(提skill):.1f}s")

print("\n=== 全样本: 到挑完耗时 vs 总用时 ===")
带时 = [t for t in 条们 if t.get("提skill耗时") is not None]
if 带时:
    比 = [float(t["提skill耗时"]) / float(t["用时"]) for t in 带时 if float(t["用时"]) > 0]
    print(f"  有记录的 {len(带时)} 轮里, 判定+检索那段占总用时的 {sum(比) / len(比) * 100:.0f}%")
    print(f"  这段本身均 {sum(float(t['提skill耗时']) for t in 带时) / len(带时):.1f}s")
    # 只算真跑过命令的轮(生成/执行才是大头)
    跑过 = [t for t in 带时 if t["命令数"]]
    前端 = [float(t["提skill耗时"]) for t in 跑过]
    后端 = [float(t["用时"]) - float(t["提skill耗时"]) for t in 跑过]
    print(f"  真跑过命令的 {len(跑过)} 轮: 前端(判定+检索)均 {sum(前端) / len(前端):.1f}s, "
          f"后端(执行+写答案)均 {sum(后端) / len(后端):.1f}s")
