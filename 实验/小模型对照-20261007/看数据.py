# -*- coding: utf-8 -*-
"""看 2343 步轨迹能不能标出「六阶段」。"""
import collections
import json
from pathlib import Path

快照 = Path("/home/lou/桌面/collaplex_agent/实验/行为旋钮-20261007/情境快照.jsonl")
步: list[dict[str, object]] = [json.loads(l) for l in 快照.read_text().splitlines() if l.strip()]
print("步数:", len(步))
print("字段:", list(步[0].keys()))
print()
print("本步结果:", collections.Counter(str(s.get("本步结果")) for s in 步).most_common(8))
print()
print("上一步结果:", collections.Counter(str(s.get("上一步结果")) for s in 步).most_common(8))
print()
print("被拦次数:", collections.Counter(str(s.get("被拦次数")) for s in 步).most_common(6))
print()
for s in 步[:3]:
    print("--", "  ".join(k + "=" + str(v)[:56] for k, v in s.items()))
