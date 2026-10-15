# -*- coding: utf-8 -*-
"""行为旋钮 · 赫布循环（按老板的设计图重做）

设计（老板原话）：
  「一边输入然后 cnn 集群网络传播然后效应器输出然后感受器继续输入这么一个循环就是训练过程，
    同时 cnn 只有一个只是像神经元一样，训练开始时会预布线到非常多个然后就是正常的赫布学习，
    同时激素调节该调节的」

落成四件：
  ① 预布线   训练开始时把连接撒到**非常多**（默认全连 M×K 条，可扫稀疏度）
  ② CNN 单元 **只有一个** 1D 卷积（核 3 + 偏置，4 个参数），像单个神经元，被所有位置共享
  ③ 循环    输入 → CNN 传播 → 效应器输出 → 输出回灌感受器 → 再传播…
             **这个循环本身就是训练过程**（一圈一次赫布更新，无标签、无反向传播）
  ④ 激素    调制"该调节的"：把每圈的权重改动量压进预算内（预算取值搬类脑 MVP：U 型，最优区 0.010~0.020）

评估：训完用固定探针（softmax 回归，5 折）在**轮级行为**上测均衡正确率；
     对照臂 = 不打循环、直接用原始情境向量训同一个探针。
报告：训完**活下来多少条边**（剪枝后占比）← 这就是「数量靠训练定」的答案。

跑法：~/mineru-env/bin/python 赫布循环.py     （纯 numpy，CPU，0 元）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

这里 = Path(__file__).parent
维 = 1024
rng = np.random.default_rng(20261007)

# —— ② 那个"唯一的 CNN 单元"：核 3 + 偏置 = 4 个参数，像单个神经元，所有位置共用同一套
核 = np.array([0.6, 1.2, 0.6])
偏 = 0.0


def 单元(a: np.ndarray) -> np.ndarray:
    """CNN 集群的传播：同一个算子在每个位置复用（环状边界）。"""
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1) + 偏)


def 载数据() -> tuple[np.ndarray, np.ndarray]:
    z = np.load(这里 / "数据集.npz", allow_pickle=True)
    X = np.asarray(z["情境"], dtype=np.float64)
    y = np.asarray([str(v) for v in z["标签"]])
    类 = sorted(set(y.tolist()))
    号 = {c: i for i, c in enumerate(类)}
    return X, np.asarray([号[v] for v in y])


def 跑循环(x: np.ndarray, 权: np.ndarray, 投影: np.ndarray | None,
           圈数: int, 学习率: float, 激素预算: float | None, 回灌: float) -> tuple[np.ndarray, list[float]]:
    """一条样本：输入 → 传播 → 输出 → 回灌 → 再传播（这个循环就是训练过程）。"""
    a = (x @ 投影) if 投影 is not None else x.copy()
    改动: list[float] = []
    for _ in range(max(1, 圈数)):
        h = 单元(a)                      # ← CNN 集群传播（唯一那个单元，所有位置共享）
        o = h @ 权                       # ← 效应器输出
        a = np.tanh(0.4 * a + 回灌 * (权 @ o))          # ← 输出回灌感受器（循环）
        d权 = 学习率 * np.outer(h, o) - 学习率 * (o ** 2)[None, :] * 权   # 赫布 + Oja 稳定项
        if 激素预算 is not None:          # ← ④ 激素：把这一圈的改动量压进预算
            m = float(np.mean(np.abs(d权))) + 1e-12
            d权 = d权 * min(1.0, 激素预算 / m)
        改动.append(float(np.mean(np.abs(d权))))
        权 = 权 + d权
    权 = 权 * (1.0 - 0.002)              # 没用到的连接慢慢掉（赫布的"不用就退"）
    return 权, 改动


def 赫布循环(X: np.ndarray, 感受器数: int = 1024, 效应器数: int = 256, 圈数: int = 3,
             密度: float = 1.0, 学习率: float = 0.02, 激素预算: float | None = 0.01,
             回灌: float = 0.6, 剪枝阈值: float = 1e-3) -> tuple[np.ndarray, dict[str, float]]:
    投影 = rng.standard_normal((维, 感受器数)) / (维 ** 0.5) if 感受器数 != 维 else None
    # —— ① 预布线：训练开始就把线撒到非常多
    权: np.ndarray = rng.standard_normal((感受器数, 效应器数)) * 0.05
    if 密度 < 1.0:
        掩: np.ndarray = rng.random((感受器数, 效应器数)) < 密度
        权 = 权 * 掩
    初边 = int(np.sum(权 != 0))
    全改动: list[float] = []
    for i in range(len(X)):
        权, 改动 = 跑循环(X[i], 权, 投影, 圈数, 学习率, 激素预算, 回灌)
        全改动 += 改动
    存活: np.ndarray = 权.copy()
    存活[np.abs(存活) < 剪枝阈值] = 0.0
    统计 = {"初边": 初边, "活边": int(np.sum(存活 != 0)),
            "存活率": float(np.sum(存活 != 0)) / max(1, 初边),
            "均改动量": float(np.mean(全改动)) if 全改动 else 0.0}
    return 权, 统计


def 表示(X: np.ndarray, 权: np.ndarray, 圈数: int) -> np.ndarray:
    """训完的连接上跑一遍循环，取感受器终态当表示（供探针用）。"""
    out = np.zeros((len(X), 权.shape[0]))
    for i in range(len(X)):
        a = X[i].copy()
        for _ in range(max(1, 圈数)):
            h = 单元(a)
            o = h @ 权
            a = np.tanh(0.4 * a + 0.6 * (权 @ o))
        out[i] = a
    return out


def 探针(X: np.ndarray, y: np.ndarray, 折: int = 5, 轮: int = 300, 学习率: float = 0.5) -> float:
    """固定探针：softmax 回归，返回 5 折**均衡正确率**（按类平均，避免多数类灌水）。"""
    n, d = X.shape
    类数 = int(y.max()) + 1
    正 = np.zeros((n, 类数))
    正[np.arange(n), y] = 1.0
    序 = rng.permutation(n)
    折号 = np.array_split(序, 折)
    分: list[float] = []
    for i in range(折):
        测 = 折号[i]
        训 = np.concatenate([折号[j] for j in range(折) if j != i])
        Wp: np.ndarray = np.zeros((d, 类数))
        bp: np.ndarray = np.zeros(类数)
        Xt = X[训] / (np.linalg.norm(X[训], axis=1, keepdims=True) + 1e-9)
        Xv = X[测] / (np.linalg.norm(X[测], axis=1, keepdims=True) + 1e-9)
        正训 = 正[训]
        for _ in range(轮):
            z = Xt @ Wp + bp
            z = z - z.max(axis=1, keepdims=True)
            p: np.ndarray = np.exp(z)
            p = p / p.sum(axis=1, keepdims=True)
            g: np.ndarray = (p - 正训) / len(训)
            Wp = Wp - 学习率 * (Xt.T @ g)
            bp = bp - 学习率 * g.sum(axis=0)
        pred: np.ndarray = (Xv @ Wp + bp).argmax(axis=1)
        per: list[float] = []
        for c in range(类数):
            m = y[测] == c
            if int(m.sum()) > 0:
                per.append(float((pred[m] == c).mean()))
        分.append(sum(per) / max(1, len(per)))
    return float(np.mean(分))


if __name__ == "__main__":
    X, y = 载数据()
    名 = sorted(set(y.tolist()))
    print(f"样本 {len(X)} 条 ｜ 行为类别 {len(名)} 个 ｜ 维度 {X.shape[1]}")
    print("  类别分布：" + " ".join(f"{名[c]}={int((y == c).sum())}" for c in range(len(名))))
    print(f"  基线（一律猜多数类）均衡正确率 ≈ {1/len(名):.3f}\n")

    print(f"【对照 0】不打循环：原始情境向量直接训探针　均衡 {探针(X, y)*100:.1f}%\n")

    print("【他的设计】预布线（全连 感受器×效应器）→ CNN 循环（=训练）→ 激素调制")
    print(f"  {'效应器K':>7s} {'圈数':>4s} {'预算':>6s} {'探针均衡':>9s} {'活边/初边':>13s} {'存活率':>7s}")
    for K in (16, 64, 256):
        for T in (1, 3):
            权, st = 赫布循环(X, 效应器数=K, 圈数=T, 激素预算=0.01)
            正 = 探针(表示(X, 权, T), y)
            print(f"  {K:7d} {T:4d} {0.010:6.3f} {正*100:8.1f}% "
                  f"{st['活边']:7d}/{st['初边']:<5d} {st['存活率']*100:6.1f}%")
