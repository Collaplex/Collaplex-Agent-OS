# -*- coding: utf-8 -*-
"""范式件 v2 —— 判「这一步会不会成功」（给 think 循环当方向盘）

v1 的教训（两处都是设计错，不是训练错）：
  ① ★ 输入里**没放 `本步同族`** ⇒ 判"这步会不会成功"却不告诉它"这是同族重试"
     ⇒ 同族被判成功 75.7%（数据里同族 0% 成功，是硬事实）⇒ 关键特征藏起来了。
  ② ★ 拿 0.6B 提特征纯属浪费 —— 提特征 1373s(23 分钟)，而这活是**表格型**的。
     今早刚证过「1050 参数窄头 > 8B」，转头自己犯同一个错 ⇒ **改结构化特征，秒级**。

数据：`情境快照.jsonl`（真实轨迹，每步带动作/结果/反馈/是否同族）。
标签：`本步结果` 是否成功（硬真值）。
判据：★ **分组报**（同族组 / 换族组各自看），外加准确率、失败召回、失败精确。
      —— 只看总准确率会骗人（这里 83% 都是"成功"，全猜成功就有 83%）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

快照 = Path("/home/lou/桌面/collaplex_agent/实验/行为旋钮-20261007/情境快照.jsonl")
种子 = 20261007
结果类 = ["成功", "报错", "拦截", "空"]


def 读数据() -> list[dict[str, Any]]:
    步: list[dict[str, Any]] = []
    for 行 in 快照.read_text().splitlines():
        if 行.strip():
            步.append(json.loads(行))
    return 步


def 结果码(v: object) -> int:
    s = str(v or "空")
    return 结果类.index(s) if s in 结果类 else 3


def 造特征(步: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """返回 (特征, 标签, 同族?, 动作族名表)。特征全是**可解释的符号特征**。"""
    词表: dict[str, int] = {}
    for x in 步:
        首词 = str(x.get("本步动作", "")).split()[0] if str(x.get("本步动作", "")).split() else "无"
        首词 = 首词.lstrip("$").split("/")[-1][:12]
        词表.setdefault(首词, len(词表))
    词数 = min(len(词表), 40)

    行s: list[list[float]] = []
    标签: list[float] = []
    同族: list[float] = []
    栽了记: list[float] = []
    上轮 = None
    窗口: list[float] = []
    for i, x in enumerate(步):
        if x.get("轮") != 上轮:
            窗口 = []
            上轮 = x.get("轮")

        首词 = str(x.get("本步动作", "")).split()[0] if str(x.get("本步动作", "")).split() else "无"
        首词 = 首词.lstrip("$").split("/")[-1][:12]
        idx = 词表.get(首词, 0)
        动作一热 = [0.0] * 词数
        if idx < 词数:
            动作一热[idx] = 1.0

        上果 = 结果码(x.get("上一步结果"))
        上果一热 = [0.0] * 4
        上果一热[上果] = 1.0

        # 最近三步的结果（序列信息：连续失败往往预示继续失败）
        近 = (窗口 + [0.0, 0.0, 0.0])[-3:]

        # ★ v1 漏掉的关键特征
        同 = 1.0 if x.get("本步同族") else 0.0
        被拦 = float(x.get("之前被拦次数") or 0)
        # ★★ v2 漏掉的交互特征 —— 这是"修正假设"的精确定义：
        #   实测"同族"单独不是危险(所有同族步 90.7% 成功)；
        #   但「上一步失败/被拦 之后还同族」= 没修正 = 0% 成功。
        上步栽了 = 1.0 if 上果 in (1, 2) else 0.0
        栽了还同族 = 上步栽了 * 同
        栽了且换族 = 上步栽了 * (1.0 - 同)

        行s.append(
            [float(x.get("序号") or 0), 同, 被拦, float(i) / max(len(步), 1),
             上步栽了, 栽了还同族, 栽了且换族]
            + 上果一热 + 近 + 动作一热
        )
        标签.append(1.0 if str(x.get("本步结果")) == "成功" else 0.0)
        同族.append(同)
        栽了记.append(上步栽了)
        窗口 = (窗口 + [float(上果)])[-3:]

    return (np.array(行s, dtype=np.float32), np.array(标签, dtype=np.float32),
            np.array(同族), np.array(栽了记), list(词表))


def 标准化(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    均 = X.mean(0)
    差 = X.std(0)
    差[差 < 1e-6] = 1.0
    return (X - 均) / 差, 均, 差


def 训(X: np.ndarray, y: np.ndarray, 轮: int = 4000, 率: float = 0.35) -> np.ndarray:
    """纯 numpy 逻辑回归。★ 失败样本加权：81.7% 都是"成功"，
    不加权它只学多数类（v2 的失败召回只有 0.337 就是这么来的）。"""
    n, d = X.shape
    Xa = np.hstack([X, np.ones((n, 1), dtype=np.float32)])
    # 让两个类的总权重相等
    权 = np.where(y > 0.5, 0.5 / max(y.mean(), 1e-6), 0.5 / max(1 - y.mean(), 1e-6)).astype(np.float32)
    w = np.zeros(d + 1, dtype=np.float32)
    for _ in range(轮):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xa @ w, -30, 30)))
        g = Xa.T @ (权 * (p - y)) / n + 0.001 * w
        w -= 率 * g
    return w


def 预测(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    Xa = np.hstack([X, np.ones((X.shape[0], 1), dtype=np.float32)])
    return 1.0 / (1.0 + np.exp(-np.clip(Xa @ w, -30, 30)))


if __name__ == "__main__":
    步 = 读数据()
    X, y, 同, 栽了, 词表 = 造特征(步)
    print(f"样本 {len(步)}，成功 {int(y.sum())} / 失败 {int((1 - y).sum())}，同族 {int(同.sum())}")
    print(f"特征 {X.shape[1]} 维（结构化，秒级；v1 用 0.6B 提特征花了 1373s）")

    # 按轮切分（★ 不能按位置切：同一轮内相邻步高度相关，位置切会泄漏）
    轮s = [str(x.get("轮")) for x in 步]
    独立轮 = sorted(set(轮s), key=lambda r: int(r) if r.isdigit() else 0)
    切 = int(len(独立轮) * 0.8)
    训轮 = set(独立轮[:切])
    训掩 = np.array([r in 训轮 for r in 轮s])
    测掩 = ~训掩

    Xs, 均, 差 = 标准化(X[训掩])
    X测 = (X[测掩] - 均) / 差
    w = 训(Xs, y[训掩])

    p = 预测(X测, w)
    yt = y[测掩]
    同t = 同[测掩]
    预 = (p >= 0.5).astype(np.float32)

    基线 = max(yt.mean(), 1 - yt.mean())
    准 = float((预 == yt).mean())
    真阳 = float(((预 == 1) & (yt == 0)).sum())
    召 = 真阳 / max(float((yt == 0).sum()), 1)
    精 = 真阳 / max(float((预 == 1).sum()), 1)

    print(f"\n═══ 判据（按轮留出 20%，{int(测掩.sum())} 条）═══")
    print(f"  准确率         {准:.4f}   （多数类基线 {基线:.4f}）⇒ {准 - 基线:+.4f}")
    print(f"  失败召回       {召:.4f}   ← 该报警的报出来了吗")
    print(f"  失败精确       {精:.4f}   ← 报了警的真是危险吗")

    栽t = 栽_测 = 栽了[测掩]
    print("\n  ★ 四分组（这才是关键：『修正假设』的考场是「上一步栽了」那两格）")
    for 名, 掩 in [
        ("栽了·还同族 ✗ ", (栽t == 1) & (同t == 1)),
        ("栽了·换族   ✓ ", (栽t == 1) & (同t == 0)),
        ("没栽·同族     ", (栽t == 0) & (同t == 1)),
        ("没栽·换族     ", (栽t == 0) & (同t == 0)),
    ]:
        if int(掩.sum()) == 0:
            print(f"    {名}  0 条")
            continue
        组预, 组真 = 预[掩], yt[掩]
        print(f"    {名} {int(掩.sum()):4d} 条：真实成功率 {组真.mean():.3f}，"
              f"它判成功 {(组预 == 1).mean():.3f}（偏 {组预.mean() - 组真.mean():+.3f}）")

    # ★ 只在上一步栽了的子集上看准不准（这才是它的实际用途）
    if int((栽t == 1).sum()):
        掩 = 栽t == 1
        print(f"\n  ★ 只算「上一步栽了」（{int(掩.sum())} 条，它真正要救的那批）："
              f"准确率 {(预[掩] == yt[掩]).mean():.4f}")
        print(f"    真实成功率 {yt[掩].mean():.3f} —— 若它把同族也判成会成功 ⇒ 救不回那批")
