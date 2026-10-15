# -*- coding: utf-8 -*-
"""实测：窄头单条判断要多久（0.6B 提特征 + 逻辑回归）。"""
import json
import statistics
import time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

根 = Path(__file__).parent
权 = "/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master"

题: list[str] = []
for 行 in (根 / "题库.jsonl").read_text(encoding="utf-8").splitlines():
    if 行.strip():
        题.append(str(json.loads(行)["题"]))

tok = AutoTokenizer.from_pretrained(权)
m = AutoModel.from_pretrained(权, dtype=torch.float32)
m.eval()
次: list[float] = []
with torch.no_grad():
    for q in 题[:12]:
        t0 = time.time()
        批 = tok(q, return_tensors="pt", truncation=True, max_length=128)
        _ = m(**批).last_hidden_state.mean(dim=1).squeeze(0).numpy()
        次.append(time.time() - t0)
print(f"窄头单条 {len(次)} 条实测：中位 {statistics.median(次) * 1000:.0f}ms　均值 {statistics.mean(次) * 1000:.0f}ms")
