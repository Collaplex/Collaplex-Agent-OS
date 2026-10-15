# -*- coding: utf-8 -*-
"""行为旋钮 · 赫布扩展（把预布线拉到 10 万量级）

老板："你试一下预布线 100000 个 cnn 这个体量可能就有效果了"
——按"cnn 只有一个、预布线到非常多"的读法，这里是**把预布线的连接数拉到 10 万量级**：
  感受器 8192 个单元 × 效应器 13 族 = **106,496 条边** ≈ 1e5

扩维不是硬凑：用**稀疏扩展编码**（果蝇蘑菇体那一套）——
  32 个情境槽 → 每个感受器单元只连其中 4 个位、权重 ±1 ⇒ 单元编码的是"少数几个槽的组合"（组合特征）；
  一次只让 ~5% 的单元激活（top-k）⇒ 稀疏。
理论上组合特征 + 稀疏 + 赫布，比 32 维线性强得多（这也是老板说的"激活一片"）。

其余照旧：唯一的 CNN 单元（核 3 + 偏置，4 参数）｜循环＝训练｜赫布（局部，无反向传播）｜激素压改动量。
判据：① 权重结构（题槽→正确族 vs 其他）② 纯利用命中率（ε=0）③ 平均步数

跑法：~/mineru-env/bin/python 赫布扩展.py     （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess
import time

import numpy as np

rng = np.random.default_rng(20261007)

动作库: dict[str, str] = {
    "查:磁盘": "df -h", "查:内存": "free -h", "查:占用": "du -sh /tmp", "查:端口": "ss -ltn",
    "查:进程": "ps aux", "查:服务": "systemctl list-units --type=service --no-pager",
    "查:日志": "journalctl -n 5 --no-pager", "查:硬件": "lscpu", "查:系统": "uptime",
    "查:时间": "date", "读:内核内存": "cat /proc/meminfo", "网:本地": "ip -brief addr",
    "查:内核": "uname -r",
}
族们 = sorted(动作库)
族号 = {f: i for i, f in enumerate(族们)}
K = len(族们)

任务集: list[tuple[str, re.Pattern[str]]] = [
    ("根分区还剩多少", re.compile(r"文件系统|Filesystem")),
    ("内存还剩多少", re.compile(r"Mem:|内存")),
    ("8789 端口有没有在听", re.compile(r":8789")),
    ("现在几点", re.compile(r"\bCST\b|\bUTC\b")),
    ("系统跑了多久、负载多少", re.compile(r"load average")),
    ("/tmp 占多大空间", re.compile(r"[\d.]+[KMGT]\s+/tmp")),
    ("有几个进程在跑", re.compile(r"USER\s+PID\s+%CPU")),
    ("本机 IP 是多少", re.compile(r"\d+\.\d+\.\d+\.\d+/\d+")),
    ("CPU 几核", re.compile(r"^CPU\(s\)", re.M)),
    ("内核版本", re.compile(r"^\d+\.\d+\.\d+")),
    ("有哪些服务在跑", re.compile(r"\.service\s+(loaded|active|masked|disabled)")),
    ("日志最后几条说了什么", re.compile(r"^\w{3} \d{2} \d{2}:\d{2}", re.M)),
]
题词: list[tuple[str, list[str]]] = [
    ("根分区还剩多少", ["分区", "磁盘"]), ("内存还剩多少", ["内存"]),
    ("8789 端口有没有在听", ["端口"]), ("现在几点", ["几点", "什么时间"]),
    ("系统跑了多久、负载多少", ["跑了多久", "负载"]), ("/tmp 占多大空间", ["/tmp"]),
    ("有几个进程在跑", ["进程"]), ("本机 IP 是多少", ["IP"]),
    ("CPU 几核", ["CPU"]), ("内核版本", ["内核"]), ("有哪些服务在跑", ["服务"]),
    ("日志最后几条说了什么", ["日志"]),
]
结果槽 = {"": 0, "成功": 1, "报错": 2, "拦截": 3}
基础槽 = len(题词) + len(结果槽) + 3 + K
基础维 = 基础槽 * 2                      # 32 槽 → 64 维（步长 2，防那个 CNN 单元串扰）
核 = np.array([0.6, 1.2, 0.6])


def 单元(a: np.ndarray) -> np.ndarray:
    """那个唯一的 CNN 单元（4 个参数），所有位置共用。"""
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1))


def 基础向量(任务: str, 上一步结果: str, 被拦数: int, 上一步族: str) -> np.ndarray:
    v: np.ndarray = np.zeros(基础维)
    for i, (名, 词) in enumerate(题词):
        if 名 in 任务 or any(w in 任务 for w in 词):
            v[2 * i] = 1.0
    v[2 * (len(题词) + 结果槽.get(上一步结果, 0))] = 1.0
    v[2 * (len(题词) + len(结果槽) + (0 if 被拦数 == 0 else (1 if 被拦数 == 1 else 2)))] = 1.0
    if 上一步族 in 族号:
        v[2 * (len(题词) + len(结果槽) + 3 + 族号[上一步族])] = 1.0
    return v


def 建扩展(感受器数: int) -> np.ndarray:
    """稀疏扩展编码矩阵 (基础维, 感受器数)：每个单元只连 4 个位，权 ±1。"""
    P: np.ndarray = np.zeros((基础维, 感受器数))
    for j in range(感受器数):
        位 = rng.choice(基础维, size=4, replace=False)
        P[位, j] = rng.choice([-1.0, 1.0], size=4)
    return P


def 执行(族: str) -> tuple[str, str]:
    命令 = 动作库[族]
    if not re.fullmatch(r"[A-Za-z0-9 _./\-]+", 命令):
        return "拒绝", "含危险成分"
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return ("成功" if 果.returncode == 0 else "报错"), (果.stdout or "") + (果.stderr or "")
    except subprocess.TimeoutExpired:
        return "报错", "超时"


def 激活(v: np.ndarray, P: np.ndarray, 保留: int) -> np.ndarray:
    """稀疏扩展 + top-k（只让约 5% 的单元亮）—— 老板说的"先激活一片"。"""
    a = P.T @ v
    if 保留 < len(a):
        阈 = np.partition(np.abs(a), len(a) - 保留)[len(a) - 保留]
        a[np.abs(a) < 阈] = 0.0
    return a


def 跑(感受器数: int, 轮数: int, P: np.ndarray, 权初: np.ndarray, 学习率: float = 0.5,
      激素预算: float | None = 0.02, ε: float = 0.15) -> tuple[float, float, np.ndarray]:
    权 = 权初.copy()
    保留 = max(8, 感受器数 // 20)
    中 = 0
    总步 = 0
    for 轮 in range(轮数):
        r = np.random.default_rng(1000 + 轮)
        for 任务, 判据 in 任务集:
            上一步结果, 上一步族, 被拦数 = "", "", 0
            走过: set[int] = set()
            命中 = False
            for _ in range(5):
                v = 基础向量(任务, 上一步结果, 被拦数, 上一步族)
                a = 激活(v, P, 保留)
                h: np.ndarray = 单元(a)
                o: np.ndarray = (权.T @ h) / np.sqrt(float(保留))
                选 = int(r.choice(K)) if (r.random() < ε) else int(np.asarray(np.argmax(o)).item())
                if 选 in 走过:
                    可选 = [i for i in range(K) if i not in 走过]
                    选 = int(r.choice(可选)) if 可选 else 选
                走过.add(选)
                总步 += 1
                族 = 族们[选]
                上一步结果, 反馈 = 执行(族)
                上一步族 = 族
                if 上一步结果 == "拦截":
                    被拦数 += 1
                好 = bool(判据.search(反馈))
                命中 = 命中 or 好
                信号: np.ndarray = np.zeros(K)
                if 好:
                    信号[选] = 1.0
                elif 上一步结果 == "拦截":
                    信号[选] = -1.0
                elif 上一步结果 == "报错":
                    信号[选] = -0.2
                else:
                    信号[选] = -0.25            # 白干也要弱化（否则干扰族压不下去）
                非零: np.ndarray = np.nonzero(h)[0]     # ★ 稀疏：只更新亮着的那些单元
                未: np.ndarray = 学习率 * np.outer(h[非零], 信号)
                if 激素预算 is not None:
                    m = float(np.mean(np.abs(未))) + 1e-12
                    未 = 未 * min(1.0, 激素预算 / m)
                权[非零] += 未
                if 好:
                    break
            中 += 1 if 命中 else 0
    return 中 / len(任务集), 总步 / len(任务集), 权


def 正确族表() -> dict[str, str]:
    得: dict[str, str] = {}
    for 任务, 判据 in 任务集:
        for f in 族们:
            _, 文 = 执行(f)
            if 判据.search(文):
                得[任务] = f
                break
    return 得


def 查权重(权: np.ndarray, P: np.ndarray, 题表: dict[str, str]) -> float:
    """训完后「题槽 → 正确族」的边 vs 「题槽 → 其他族」（经过扩展矩阵折算回题槽）。"""
    正: list[float] = []
    他: list[float] = []
    for i, (任务, _) in enumerate(任务集):
        if 任务 not in 题表:
            continue
        j = 族号[题表[任务]]
        # 把"扩展空间里的权重"折回题槽：用该题槽连到的那些单元求和
        # ★ 归一化：除以"该题槽连到的单元数"，否则单元越多和越大（假象）
        贡献 = (P[2 * i] @ 权) / max(1.0, float(np.count_nonzero(P[2 * i])))
        正.append(float(贡献[j]))
        他.append(float(np.delete(贡献, j).mean()))
    d = float(np.mean(正)) - float(np.mean(他))
    print(f"  题槽→正确族 {np.mean(正):+.5f}　题槽→其他族 {np.mean(他):+.5f}　差 {d:+.5f}")
    return d


if __name__ == "__main__":
    print(f"感受器基础 {基础维} 维（{基础槽} 槽，步长 2）｜效应器 {K} 族｜唯一 CNN 单元 4 参数")
    题表 = 正确族表()
    print(f"每题真正能命中的族：" + " ".join(f"{t[:6]}→{f}" for t, f in 题表.items()))
    print(f"\n  {'感受器':>7s} {'预布线边数':>10s} {'权重差':>10s} {'纯利用命中':>9s} {'平均步数':>8s} {'耗时':>6s}")
    for N in (64, 512, 2048, 8192):
        t0 = time.time()
        P = np.eye(基础维) if N == 基础维 else 建扩展(N)
        权初 = rng.standard_normal((N, K)) * 0.02
        _, _, 权训 = 跑(N, 40, P, 权初, 激素预算=0.02)
        命中, 步数, _ = 跑(N, 1, P, 权训, 学习率=0.0, 激素预算=None, ε=0.0)
        d = 查权重(权训, P, 题表)
        print(f"  {N:7d} {N*K:10d} {d:+10.5f} {命中*100:8.1f}% {步数:8.2f} {time.time()-t0:5.0f}s")
    print(f"\n  （基线：不学 33.3%／步数 4.33　第⑤层现有机制 75.0%／步数 2.00）")
