# -*- coding: utf-8 -*-
"""路由模型：挑"这题该走哪条路"（对应老板新架构图里的「路由模型」）

老板的话："路由模型挑选的是需要激活哪些专家" —— 在我们的场景里，
第一步能落地、又能直接测的版本就是：**挑该用哪个 skill（走哪条路）**。

数据全现成、0 元、CPU、不碰显存：
  · 输入：59 道题的 Qwen3-0.6B 隐层特征（复用 习惯模型-特征.npz）
  · 标签：题库的 `skill` 字段（linux 22 / math 10 / file 2 / seek 1 / 空 24）
  · 对照：`样本.jsonl` 里模型实际挑中的 skill

★ 重点判据不是总准确率，是 **math（要算的题）能不能认出来** ——
   现有模型在这一类上 10 题错 5 题（50%），是本机最大的短板。
"""
import json
from pathlib import Path
from typing import Any

import numpy as np

根 = Path("/home/lou/桌面/collaplex_agent/实验/小模型对照-20261007")
缓存 = 根 / "习惯模型-特征.npz"


def 读题() -> tuple[list[str], list[str]]:
    题: list[str] = []
    向: list[str] = []
    for 行 in (根 / "题库.jsonl").read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        条: dict[str, Any] = json.loads(行)
        题.append(str(条["题"]))
        s = 条.get("skill")
        向.append(str(s) if s not in (None, "None", "") else "空")
    return 题, 向


def 现有模型挑的() -> dict[int, str]:
    出: dict[int, list[str]] = {}
    for 行 in (根 / "样本.jsonl").read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        s: dict[str, Any] = json.loads(行)
        号值 = s.get("题号")
        if not isinstance(号值, (int, str)):
            continue
        出.setdefault(int(号值), []).append(str(s.get("挑中skill") or "空"))
    return {号: max(set(v), key=v.count) for 号, v in 出.items()}


def 训多类(特征: np.ndarray, y: np.ndarray, 类数: int, 轮: int = 800, lr: float = 0.5, l2: float = 1e-2) -> np.ndarray:
    """手写 softmax 回归（本机没 sklearn）"""
    n, d = 特征.shape
    扩 = np.hstack([特征, np.ones((n, 1))])
    权 = np.zeros((d + 1, 类数))
    独热 = np.zeros((n, 类数))
    独热[np.arange(n), y] = 1.0
    for _ in range(轮):
        z = np.clip(扩 @ 权, -30, 30)
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        权 -= lr * (扩.T @ (p - 独热) / n + l2 * 权)
    return 权


def 主() -> None:
    题, 方向 = 读题()
    旧: Any = np.load(缓存)
    特征 = np.asarray(旧["特征"], dtype=np.float64)
    特征 = (特征 - 特征.mean(0)) / (特征.std(0) + 1e-6)
    print(f"{len(题)} 题，方向分布：{ {d: 方向.count(d) for d in sorted(set(方向))} }")

    现 = 现有模型挑的()

    # ── ① 四类：linux / math / file / seek / 空（用全部 59 题）
    类名 = ["空", "math", "linux", "file", "seek"]
    号到类 = {c: i for i, c in enumerate(类名)}
    y = np.asarray([号到类[方向[i]] for i in range(len(题))])
    预测 = np.zeros(len(题), dtype=int)
    for i in range(len(题)):
        留 = [j for j in range(len(题)) if j != i]
        权 = 训多类(特征[留], y[留], len(类名))
        zh = np.append(特征[i], 1.0) @ 权
        预测[i] = int(np.argmax(zh))

    对 = int((预测 == y).sum())
    现对 = sum(1 for i in range(len(题)) if 现.get(i + 1, "空") == 方向[i])
    print("\n① 五类挑方向（含「空」= 不该动手）")
    print(f"   训练窄头 {对}/{len(题)} = {对 / len(题) * 100:.1f}%")
    print(f"   现有模型 {现对}/{len(题)} = {现对 / len(题) * 100:.1f}%")

    # ── ② 重点：math 能不能认出来
    ism = np.asarray([1 if d == "math" else 0 for d in 方向])
    预m = np.zeros(len(题), dtype=int)
    for i in range(len(题)):
        留 = [j for j in range(len(题)) if j != i]
        # 二分类：拆成两类 softmax，正类是 math
        权 = 训多类(特征[留], ism[留], 2)
        zh = np.append(特征[i], 1.0) @ 权
        预m[i] = int(np.argmax(zh))
    真m = int(ism.sum())
    窄mk = int(((预m == 1) & (ism == 1)).sum())
    现mk = sum(1 for i in range(len(题)) if ism[i] == 1 and 现.get(i + 1) == "math")
    print(f"\n② ★ math 识别（{真m} 题）")
    print(f"   训练窄头认出 {窄mk}/{真m} = {窄mk / 真m * 100:.1f}%")
    print(f"   现有模型认出 {现mk}/{真m} = {现mk / 真m * 100:.1f}%")
    漏的 = [i + 1 for i in range(len(题)) if ism[i] == 1 and 预m[i] != 1]
    print(f"   窄头漏掉的 math 题: {漏的}")

    权m = 训多类(特征, ism, 2)
    权5 = 训多类(特征, y, len(类名))
    np.savez(根 / "路由头.npz", 权math=权m, 权五类=权5, 类名=np.asarray(类名),
             均值=特征.mean(0), 标准差=特征.std(0) + 1e-6)
    print(f"\n  存权 → 路由头.npz（math 头 {权m.shape[0]} 个数 / 五类头 {权5.shape[0]} 个数）")

    print(f"\n③ 合并（math 题：任一个认出来就算）: "
          f"{sum(1 for i in range(len(题)) if ism[i] == 1 and (预m[i] == 1 or 现.get(i + 1) == 'math'))}/{真m}")


if __name__ == "__main__":
    主()
