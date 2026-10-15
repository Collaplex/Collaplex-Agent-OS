# -*- coding: utf-8 -*-
"""补判据：math 头的精确率（它说"要算"的里面，有多少真的是要算的）。"""
import json
from pathlib import Path
from typing import Any

import numpy as np

根 = Path(__file__).parent
题: list[str] = []
向: list[str] = []
for 行 in (根 / "题库.jsonl").read_text(encoding="utf-8").splitlines():
    if 行.strip():
        条: dict[str, Any] = json.loads(行)
        题.append(str(条["题"]))
        s = 条.get("skill")
        向.append(str(s) if s not in (None, "None", "") else "空")

路: Any = np.load(根 / "路由头.npz")
习: Any = np.load(根 / "习惯模型-特征.npz")
特征 = np.asarray(习["特征"], dtype=np.float64)
特征 = (特征 - np.asarray(路["均值"], dtype=np.float64)) / np.asarray(路["标准差"], dtype=np.float64)
权m = np.asarray(路["权math"], dtype=np.float64)

真 = [1 if d == "math" else 0 for d in 向]
预 = []
for i in range(len(题)):
    z = np.append(特征[i], 1.0) @ 权m
    预.append(int(np.argmax(z)))

tp = sum(1 for i in range(len(题)) if 真[i] == 1 and 预[i] == 1)
fp = sum(1 for i in range(len(题)) if 真[i] == 0 and 预[i] == 1)
fn = sum(1 for i in range(len(题)) if 真[i] == 1 and 预[i] == 0)
tn = sum(1 for i in range(len(题)) if 真[i] == 0 and 预[i] == 0)
print(f"math 头（全量训后，训练集上）混淆：TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"  召回 {tp}/{tp+fn} = {tp/(tp+fn)*100:.0f}%　精确 {tp}/{tp+fp} = {tp/(tp+fp)*100 if tp+fp else 0:.0f}%")
print("  被误报成 math 的题:")
for i in range(len(题)):
    if 真[i] == 0 and 预[i] == 1:
        print(f"    {i+1:2d} 该={向[i]:6s} 「{题[i][:30]}」")
