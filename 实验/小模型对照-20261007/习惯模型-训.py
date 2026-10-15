# -*- coding: utf-8 -*-
"""习惯模型：把"该动手 / 不该动手"当**训练目标**训出来

对应老板新架构图 `diagrams/模型架构设计.drawio` 里的「习惯模型」这一件。
老板的话："这个是目前模型训练的遗留问题，所以正确的路还是去搞模型架构设计加训练"。

做法（8G 卡友好、0 元、不碰显存）：
  1. 拿 Qwen3-0.6B 当特征提取器（**冻结**），用 **CPU** 一次提完 59 道题的隐层特征，缓存到磁盘
  2. 在特征上训一个**窄头**（逻辑回归，1024 维 → 1），留一交叉验证
  3. 三臂对照：① 现有模型的实际判断（从 样本.jsonl 反推）② 多数类基线 ③ 训练出来的窄头

★ 最重的判据不是总准确率，是「**该动没动**」还剩下几题。
"""
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

根 = Path("/home/lou/桌面/collaplex_agent/实验/小模型对照-20261007")
权重 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
缓存 = 根 / "习惯模型-特征.npz"


def 读题库() -> tuple[list[str], np.ndarray]:
    题: list[str] = []
    标: list[float] = []
    for 行 in (根 / "题库.jsonl").read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        条: dict[str, Any] = json.loads(行)
        题.append(str(条["题"]))
        标.append(1.0 if str(条["该动手"]) == "True" else 0.0)
    return 题, np.asarray(标)


def 提特征(题: list[str]) -> np.ndarray:
    if 缓存.exists():
        旧: Any = np.load(缓存)
        if 旧["特征"].shape[0] == len(题):
            print(f"  用缓存 {缓存.name}（{旧['特征'].shape}）")
            return np.asarray(旧["特征"])
    print(f"  提特征：{len(题)} 条，CPU，全精度（第一次要几分钟）")
    t = AutoTokenizer.from_pretrained(str(权重))
    m = AutoModel.from_pretrained(str(权重), dtype=torch.float32)
    m.eval()
    出: list[np.ndarray] = []
    t0 = time.time()
    with torch.no_grad():
        for i, q in enumerate(题, 1):
            批 = t(q, return_tensors="pt", truncation=True, max_length=128)
            h = m(**批).last_hidden_state
            出.append(h.mean(dim=1).squeeze(0).numpy())
            if i % 10 == 0 or i == len(题):
                print(f"    {i}/{len(题)}　{time.time() - t0:.0f}s")
    特征 = np.asarray(出, dtype=np.float64)
    np.savez(缓存, 特征=特征)
    return 特征


def 训逻辑(特征: np.ndarray, y: np.ndarray, 轮: int = 600, lr: float = 0.5, l2: float = 1e-3) -> np.ndarray:
    """手写逻辑回归（本机没有 sklearn，也省一个依赖）"""
    n, d = 特征.shape
    Xb = np.hstack([特征, np.ones((n, 1))])
    w = np.zeros(d + 1)
    for _ in range(轮):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ w, -30, 30)))
        w -= lr * (Xb.T @ (p - y) / n + l2 * w)
    return w


def 主() -> None:
    题, y = 读题库()
    print(f"题库 {len(题)} 题，该动手 {int(y.sum())} / 不该动 {int((1 - y).sum())}")

    print("\n③ 训练窄头（Qwen3-0.6B 隐层 → 逻辑回归，留一交叉验证）")
    特征 = 提特征(题)
    特征 = (特征 - 特征.mean(0)) / (特征.std(0) + 1e-6)

    预测 = np.zeros(len(题))
    for i in range(len(题)):
        留 = [j for j in range(len(题)) if j != i]
        w = 训逻辑(特征[留], y[留])
        p = 1.0 / (1.0 + np.exp(-np.clip(np.append(特征[i], 1.0) @ w, -30, 30)))
        预测[i] = 1.0 if p >= 0.5 else 0.0

    对 = int((预测 == y).sum())
    漏 = [i for i in range(len(题)) if y[i] == 1 and 预测[i] == 0]
    多 = [i for i in range(len(题)) if y[i] == 0 and 预测[i] == 1]
    print(f"\n  留一准确率 {对}/{len(题)} = {对 / len(题) * 100:.1f}%")
    print(f"  该动没动 {len(漏)} 题　不该动却动 {len(多)} 题")

    print("\n══ 三臂对照")
    print("  ① 现有模型实际判断（样本.jsonl 反推）: 49/59 = 83.1%　该动没动 7 题 [19,38,39,42,43,44,45]")
    print("  ② 多数类基线（全答'该动'）        : 35/59 = 59.3%　该动没动 0 题　不该动却动 24 题")
    print(f"  ③ 训练窄头（0.6B 隐层 + 逻辑回归） : {对}/{len(题)} = {对 / len(题) * 100:.1f}%　该动没动 {len(漏)} 题　不该动却动 {len(多)} 题")
    # ★ 用全量训一次并存权（供产品侧的"件"加载）
    权全 = 训逻辑(特征, y)
    np.savez(根 / "习惯头.npz", 权=权全, 均值=特征.mean(0), 标准差=特征.std(0) + 1e-6)
    print(f"\n  存权 → 习惯头.npz（{权全.shape[0]} 个数）")

    救 = 7 - len([i for i in 漏 if i + 1 in (19, 38, 39, 42, 43, 44, 45)])
    print(f"\n★ 关键：现有模型漏的那 7 题里，窄头救回 {救} 题")

    # ④ 互补性：窄头 vs 现有模型逐题对照（决定"多个件协同"值不值）
    现: dict[int, bool] = {}
    import collections
    按题: dict[int, list[bool]] = collections.defaultdict(list)
    for 行 in (根 / "样本.jsonl").read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        s: dict[str, Any] = json.loads(行)
        号值 = s.get("题号")
        if not isinstance(号值, (int, str)):
            continue
        号 = int(号值)
        命令数 = s.get("命令数")
        动了 = bool(s.get("真跑过") is True)
        if not 动了 and isinstance(命令数, (int, str)):
            动了 = int(命令数) > 0
        按题[号].append(动了)
    for 号, 轮 in 按题.items():
        现[号] = sum(1 for m in 轮 if m) * 2 > len(轮)

    都错: list[int] = []
    只现对: list[int] = []
    只窄对: list[int] = []
    都对 = 0
    for i in range(len(题)):
        号 = i + 1
        a = (现.get(号) == (y[i] == 1.0))
        b = (预测[i] == y[i])
        if a and b:
            都对 += 1
        elif a:
            只现对.append(号)
        elif b:
            只窄对.append(号)
        else:
            都错.append(号)
    print(f"\n══ ④ 逐题对照（现有模型 vs 窄头）")
    print(f"  都对 {都对} 题　只现有模型对 {len(只现对)} 题 {只现对}" )
    print(f"  只窄头对 {len(只窄对)} 题 {只窄对}　★两个都错 {len(都错)} 题 {都错}")
    print(f"  ⇒ 合并上限（任一个对就对）: {(都对 + len(只现对) + len(只窄对))}/{len(题)}"
          f" = {(都对 + len(只现对) + len(只窄对)) / len(题) * 100:.1f}%")


if __name__ == "__main__":
    主()
