# -*- coding: utf-8 -*-
"""行为旋钮 · 赫布循环 v2（v1 把信息抹平了，按老板原话修）

v1 结果：他的设计跑出 均衡 20.0% = 正好等于"一律猜多数类"（对照：不打循环 59.1%）→ 信息被循环抹平。
v1 错在哪（两处，都在"感受器继续输入"这句话上）：
  ① **原输入只在第一圈用**，之后被回灌盖掉 → a 反复迭代收敛到 权·权ᵀ 的主特征方向 → 任何输入都被推到同一个吸引子。
     老板原话是"效应器输出然后**感受器继续输入**" ⇒ 每圈都要重新注入原输入。
  ② 全连权重一起饱和（赫布无竞争）→ 效应器输出不分化 ⇒ 需要归一化，而这正是"**激素调节该调节的**"该管的。

对照臂（每臂只加一个机制）：
  A 不打循环（基线）
  B 循环 · 不注入输入（v1 的错版）
  C 循环 · 每圈注入输入
  D C ＋ 效应器归一化
  E D ＋ 激素调回灌增益（扫 0.1 / 0.3 / 0.6）

跑法：~/mineru-env/bin/python 赫布循环2.py     （纯 numpy，CPU，0 元）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

这里 = Path(__file__).parent
维 = 1024
rng = np.random.default_rng(20261007)

# —— ② 那个"唯一的 CNN 单元"：核 3 + 偏置 = 4 个参数，所有位置共用同一套
核 = np.array([0.6, 1.2, 0.6])
偏 = 0.0


def 单元(a: np.ndarray) -> np.ndarray:
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1) + 偏)


def 载数据() -> tuple[np.ndarray, np.ndarray]:
    z = np.load(这里 / "数据集.npz", allow_pickle=True)
    X = np.asarray(z["情境"], dtype=np.float64)
    y = np.asarray([str(v) for v in z["标签"]])
    类 = sorted(set(y.tolist()))
    号 = {c: i for i, c in enumerate(类)}
    return X, np.asarray([号[v] for v in y])


def 跑一条(x: np.ndarray, 权: np.ndarray, 投影: np.ndarray | None, 圈数: int, 学习率: float,
           激素预算: float | None, 回灌: float, 注入: bool, 归一化: bool) -> tuple[np.ndarray, list[float]]:
    a = (x @ 投影) if 投影 is not None else x.copy()
    改动: list[float] = []
    for _ in range(max(1, 圈数)):
        h = 单元(a)                          # CNN 集群传播
        o = h @ 权                           # 效应器输出
        if 归一化:                            # ★ 效应器归一化：防全连一起饱和（激素该管的东西之一）
            o = o / (np.linalg.norm(o) + 1e-9) * np.sqrt(len(o))
        # ★ "感受器继续输入"：每圈都把原输入重新注入，否则回灌会把输入信息抹平
        if 注入:
            a = np.tanh(0.8 * x + 0.3 * a + 回灌 * (权 @ o))
        else:
            a = np.tanh(0.4 * a + 回灌 * (权 @ o))
        d权 = 学习率 * np.outer(h, o) - 学习率 * (o ** 2)[None, :] * 权
        if 激素预算 is not None:
            m = float(np.mean(np.abs(d权))) + 1e-12
            d权 = d权 * min(1.0, 激素预算 / m)
        改动.append(float(np.mean(np.abs(d权))))
        权 = 权 + d权
    return 权 * (1.0 - 0.002), 改动


def 赫布循环(X: np.ndarray, 效应器数: int = 64, 圈数: int = 3, 学习率: float = 0.02,
             激素预算: float | None = 0.01, 回灌: float = 0.6, 注入: bool = True,
             归一化: bool = True, 剪枝阈值: float = 1e-3,
             感受器数: int = 维) -> tuple[np.ndarray, dict[str, float]]:
    投影 = rng.standard_normal((维, 感受器数)) / (维 ** 0.5) if 感受器数 != 维 else None
    权: np.ndarray = rng.standard_normal((感受器数, 效应器数)) * 0.05      # ① 预布线：先撒满
    初边 = int(np.sum(权 != 0))
    全改动: list[float] = []
    for i in range(len(X)):
        权, 改动 = 跑一条(X[i], 权, 投影, 圈数, 学习率, 激素预算, 回灌, 注入, 归一化)
        全改动 += 改动
    存活: np.ndarray = 权.copy()
    存活[np.abs(存活) < 剪枝阈值] = 0.0
    abs权 = np.abs(权).ravel()
    集中度 = float(np.abs(权).max() / (abs权.mean() + 1e-12))    # 峰值/均值：越大=越分化
    return 权, {"初边": 初边, "活边": int(np.sum(存活 != 0)),
                "存活率": float(np.sum(存活 != 0)) / max(1, 初边),
                "集中度": 集中度, "均改动量": float(np.mean(全改动)) if 全改动 else 0.0}


def 表示(X: np.ndarray, 权: np.ndarray, 圈数: int, 注入: bool = True, 归一化: bool = True) -> np.ndarray:
    out = np.zeros((len(X), 权.shape[0]))
    for i in range(len(X)):
        a = X[i].copy()
        for _ in range(max(1, 圈数)):
            h = 单元(a)
            o = h @ 权
            if 归一化:
                o = o / (np.linalg.norm(o) + 1e-9) * np.sqrt(len(o))
            a = np.tanh(0.8 * X[i] + 0.3 * a + 0.6 * (权 @ o)) if 注入 else np.tanh(0.4 * a + 0.6 * (权 @ o))
        out[i] = a
    return out


def 探针(X: np.ndarray, y: np.ndarray, 折: int = 5, 轮: int = 300, 学习率: float = 0.5) -> float:
    n, d = X.shape
    类数 = int(y.max()) + 1
    正 = np.zeros((n, 类数))
    正[np.arange(n), y] = 1.0
    折号 = np.array_split(rng.permutation(n), 折)
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
        per: list[float] = [float((pred[y[测] == c] == c).mean()) for c in range(类数) if int((y[测] == c).sum()) > 0]
        分.append(sum(per) / max(1, len(per)))
    return float(np.mean(分))


if __name__ == "__main__":
    X, y = 载数据()
    名 = sorted(set(y.tolist()))
    print(f"样本 {len(X)} 条 ｜ 行为类别 {len(名)} 个：" + " ".join(f"{名[c]}={int((y == c).sum())}" for c in range(len(名))))
    print(f"  基线（一律猜多数类）均衡 ≈ {1/len(名):.3f}　（5 类里最大类占 {max((y==c).sum() for c in range(len(名)))/len(y)*100:.0f}%）\n")
    print(f"【臂 A】不打循环，原始情境向量直接训探针　　均衡 {探针(X, y)*100:.1f}%")

    K, T = 64, 3
    表 = [
        ("【臂 B】循环 · 不注入输入（v1 错版）", dict(注入=False, 归一化=False)),
        ("【臂 C】循环 · 每圈注入输入", dict(注入=True, 归一化=False)),
        ("【臂 D】C ＋ 效应器归一化", dict(注入=True, 归一化=True)),
    ]
    for 名臂, kw in 表:
        权, st = 赫布循环(X, 效应器数=K, 圈数=T, **kw)
        正 = 探针(表示(X, 权, T, 注入=kw["注入"], 归一化=kw["归一化"]), y)
        print(f"{名臂}　均衡 {正*100:.1f}%　活边 {st['活边']}/{st['初边']}（{st['存活率']*100:.1f}%）　集中度 {st['集中度']:.1f}")

    print("\n【臂 E】D ＋ 激素调回灌增益（这就是「激素调节该调节的」里的那个）")
    for β in (0.1, 0.3, 0.6, 1.2):
        权, st = 赫布循环(X, 效应器数=K, 圈数=T, 回灌=β, 激素预算=0.01, 注入=True, 归一化=True)
        正 = 探针(表示(X, 权, T), y)
        print(f"  回灌增益 {β:4.1f}　均衡 {正*100:5.1f}%　活边 {st['活边']:5d}/{st['初边']}　集中度 {st['集中度']:6.1f}")
