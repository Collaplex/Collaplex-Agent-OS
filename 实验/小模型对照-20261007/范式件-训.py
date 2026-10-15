# -*- coding: utf-8 -*-
"""范式件 —— 训「检验矛盾 → 修正假设」这一环（老板六阶段里的第 3、4 步）

老板定的思考范式：
    提出假设 → 调取证据 → **检验假设是否矛盾 → 修正假设** → 反复验证 → 稳定可信 → 输出结论

数据限制（诚实）：`情境快照.jsonl` 2343 步**只有"动手"的步，没有 think 文本**，
所以能标出来的是中间四步；「提出假设」「输出结论」在数据里不存在。

为什么先训这一环（最要命的一环）：
    上一步失败后的真实选择与结果 ——
        同族再试（换写法不换思路）：24 次 **全部再被拦** ✗
        换族（真的换方向）        ：148 次里 **142 次成功** ✓
    ⇒ 治"走了死路不换方向"就是治这个。而 `本步同族` 字段正好把这件事标了出来。

训练目标（刻意选成"预测这一步会不会成功"，而不是直接学"该同族/该换族"）：
    · 标签是**结果**（成功/报错/拦截）——硬真值，不用我编；
    · 输入含"上一步同族/失败次数/上一步反馈"，所以它天然覆盖"同族 ⇒ 危险"这个信号；
    · 判据**两个方向都看**：该报警的有没有报（召回）、报了警的真是危险吗（精确）。

对照：多数类基线（一律"会成功"）= 1895/2343 = **80.9%**。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
快照 = 项目 / "实验/行为旋钮-20261007/情境快照.jsonl"
特征文件 = 产出 / "范式特征.npz"
留出比例 = 0.2


def 取样本() -> tuple[list[str], list[int], list[bool]]:
    """返回 (文本, 标签=这一步是否成功, 是否同族)。"""
    文本: list[str] = []
    标签: list[int] = []
    同族: list[bool] = []
    for 行 in 快照.read_text().splitlines():
        if not 行.strip():
            continue
        s: dict[str, Any] = json.loads(行)
        上 = str(s.get("上一步结果", "")).strip()
        反馈 = str(s.get("上一步反馈", ""))[:300]
        文本.append(
            f"任务：{s.get('任务', '')}\n"
            f"上一步动作：{s.get('上一步动作', '')}\n"
            f"上一步结果：{上 or '（还未动手）'}\n"
            f"上一步反馈：{反馈}\n"
            f"这一步动作：{s.get('本步动作', '')}\n"
            f"这一步是否与上一步同族：{'是' if s.get('本步同族') else '否'}"
        )
        标签.append(1 if str(s.get("本步结果", "")) == "成功" else 0)
        同族.append(bool(s.get("本步同族")))
    return 文本, 标签, 同族


def 提特征(文本: list[str]) -> np.ndarray:
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    # ★ 铁律（见技能 §18）：float32 加载 0.6B 要 2.4G，先看内存
    可用 = 0.0
    for _行 in Path("/proc/meminfo").read_text().splitlines():
        if _行.startswith("MemAvailable:"):
            可用 = int(_行.split()[1]) / 1024 / 1024
    if 可用 < 3.0:
        raise SystemExit(f"内存只剩 {可用:.1f}G（需要 >=3G）—— 拒跑")
    print(f"内存可用 {可用:.1f}G")

    分词器 = AutoTokenizer.from_pretrained(str(权重目录))
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.float32)
    模型.eval()
    出: list[np.ndarray] = []
    t0 = time.time()
    with torch.no_grad():
        for i in range(0, len(文本), 32):
            批 = 分词器(文本[i:i + 32], padding=True, truncation=True,
                        max_length=192, return_tensors="pt")
            h = 模型(**批, output_hidden_states=True).hidden_states[-1]
            掩 = 批["attention_mask"].unsqueeze(-1).float()
            均 = (h * 掩).sum(1) / 掩.sum(1)                     # 均值池化
            出.append(均.numpy().astype(np.float32))
    print(f"提特征 {len(文本)} 条，{time.time() - t0:.0f}s，维度 {出[0].shape[1]}")
    return np.concatenate(出, axis=0)


def 训练(X: np.ndarray, y: np.ndarray, 同族: np.ndarray) -> dict[str, float]:
    切 = int(len(X) * (1 - 留出比例))
    Xtr, ytr = X[:切], y[:切]
    Xte, yte, 同te = X[切:], y[切:], 同族[切:]
    # 标准化
    均, 标 = Xtr.mean(0), Xtr.std(0) + 1e-6
    Xtr, Xte = (Xtr - 均) / 标, (Xte - 均) / 标

    头 = torch.nn.Linear(Xtr.shape[1], 1)
    优 = torch.optim.AdamW(头.parameters(), lr=1e-2, weight_decay=1e-3)
    损 = torch.nn.BCEWithLogitsLoss()
    甲 = torch.from_numpy(Xtr)
    乙 = torch.from_numpy(ytr.astype(np.float32)).unsqueeze(1)
    for _ in range(600):
        l = 损(头(甲), 乙)
        优.zero_grad()
        l.backward()
        优.step()

    with torch.no_grad():
        预 = (头(torch.from_numpy(Xte)).sigmoid().squeeze(1).numpy() > 0.5).astype(int)
    准 = float((预 == yte).mean())
    基线 = float(max(yte.mean(), 1 - yte.mean()))
    # ★ 两个方向都看：把"会失败"当正类
    tp = int(((预 == 0) & (yte == 0)).sum())
    fp = int(((预 == 0) & (yte == 1)).sum())
    fn = int(((预 == 1) & (yte == 0)).sum())
    召 = tp / (tp + fn) if tp + fn else 0.0
    精 = tp / (tp + fp) if tp + fp else 0.0
    # 同族子集上的表现（这是最该报的）
    同 = 同te
    return {"准确率": 准, "多数类基线": 基线, "失败召回": 召, "失败精确": 精,
            "同族样本数": float(同.sum()),
            "同族被判成功的比例": float(预[同].mean()) if 同.sum() else 0.0}


if __name__ == "__main__":
    文本, 标签, 同族 = 取样本()
    y = np.array(标签)
    同 = np.array(同族)
    print(f"样本 {len(文本)}，成功 {int(y.sum())} / 失败 {int((1 - y).sum())}，同族 {int(同.sum())}")
    if 特征文件.exists():
        存 = np.load(特征文件)
        特 = 存["X"]
        print(f"复用特征 {特.shape}")
    else:
        特 = 提特征(文本)
        np.savez(特征文件, X=特)
    r = 训练(特, y, 同)
    print("\n═══ 判据（留出 20%）═══")
    print(f"  准确率            {r['准确率']:.4f}   （多数类基线 {r['多数类基线']:.4f}）")
    print(f"  失败召回          {r['失败召回']:.4f}   ← 该报警的报出来了吗")
    print(f"  失败精确          {r['失败精确']:.4f}   ← 报了警的真是危险吗")
    print(f"  同族样本          {int(r['同族样本数'])}")
    print(f"  同族被判成功比例  {r['同族被判成功的比例']:.4f}   ← 低=它看出同族危险")
