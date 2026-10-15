# -*- coding: utf-8 -*-
"""草稿件 —— 毫秒级判断「该不该动手 / 是不是要算的题」

对应老板架构图里的**草稿模型**：不训输出模型，只训这些小的草稿件，
让贵的输出模型只做少数几次验证（"要是完整输出的话会慢死"）。

已训好的两个头（都在 CPU 上跑，不占显存）：
  · 习惯头：该不该动手（留一 88.1% vs 现有模型 83.1%）
  · math 头：是不是要算的题（留一 100% vs 现有模型 50%）

用法：
    from 判断件 import 草稿件
    件 = 草稿件()
    件.判("现在几点了")        # {'该动手': True, '要算': False, '毫秒': 160}
    件.判("加盐提浓度")        # {'该动手': True, '要算': True, '毫秒': 160}
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

根 = Path(__file__).parent
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")


class 草稿件:
    """小、快、不占显存。判断错了不要紧 —— 贵的输出模型会验。"""

    def __init__(self) -> None:
        self.分词器 = AutoTokenizer.from_pretrained(str(权重目录))
        self.塔 = AutoModel.from_pretrained(str(权重目录), dtype=torch.float32)
        self.塔.eval()
        习: Any = np.load(根 / "习惯头.npz")
        self.权习惯 = np.asarray(习["权"], dtype=np.float64)
        self.习惯均值 = np.asarray(习["均值"], dtype=np.float64)
        self.习惯标准差 = np.asarray(习["标准差"], dtype=np.float64)
        路: Any = np.load(根 / "路由头.npz")
        self.权math = np.asarray(路["权math"], dtype=np.float64)
        self.路由均值 = np.asarray(路["均值"], dtype=np.float64)
        self.路由标准差 = np.asarray(路["标准差"], dtype=np.float64)

    def _特(self, 题: str) -> np.ndarray:
        with torch.no_grad():
            批 = self.分词器(题, return_tensors="pt", truncation=True, max_length=128)
            h = self.塔(**批).last_hidden_state.mean(dim=1).squeeze(0).numpy()
        return np.asarray(h, dtype=np.float64)

    def 判(self, 题: str) -> dict[str, Any]:
        t0 = time.time()
        f = self._特(题)

        z = float(np.append((f - self.习惯均值) / self.习惯标准差, 1.0) @ self.权习惯)
        该动手 = (1.0 / (1.0 + np.exp(-float(np.clip(z, -30, 30))))) >= 0.5

        fm = (f - self.路由均值) / self.路由标准差
        zm = np.append(fm, 1.0) @ self.权math
        要算 = bool(int(np.argmax(zm)) == 1)

        return {"该动手": bool(该动手), "要算": 要算, "毫秒": round((time.time() - t0) * 1000)}

    def 批量判(self, 题们: list[str]) -> list[dict[str, Any]]:
        return [self.判(q) for q in 题们]


if __name__ == "__main__":
    # 自测：用题库里几个已知答案的题
    例 = [
        ("现在几点了", True, False),
        ("加盐提浓度", True, True),
        ("两车相向而行", True, True),
        ("三管齐开注水", True, True),
        ("帮我查一下资料库里关于两层库的原文", True, False),
        ("软路由的型号和配置是什么", False, False),
        ("把这句话翻译成英文：这台机器今天有点慢", False, False),
        ("根分区还剩多少", True, False),
    ]
    件 = 草稿件()
    对 = 0
    for 题, 该, 算 in 例:
        r = 件.判(题)
        ok = (r["该动手"] == 该) and (r["要算"] == 算)
        对 += int(ok)
        print(f"  {'✓' if ok else '✗'} {题[:26]:28s} 该动手={r['该动手']!s:5s} 要算={r['要算']!s:5s} {r['毫秒']}ms")
    print(f"\n自测 {对}/{len(例)}")
