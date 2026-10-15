# -*- coding: utf-8 -*-
"""行为旋钮 · 赫布婴儿（按老板的设计图，接进真环境）

为什么另起一版：拿"静态数据集 + 监督探针"验"在线无监督循环"是方式错 ——
老板那句「效应器输出然后**感受器继续输入**」在真环境里的意思是：
  做完动作 → 环境反馈回来 → **反馈本身成为下一次感受器的输入** → 再传播…
静态数据集里没有"继续输入"这回事，所以循环只能空转、把信息压平（v1/v2 五臂全 20.0% 就是这个原因）。

四件（老板原话 → 落法）：
  ① 预布线   连接先撒满（感受器 32 维 × 效应器 13 族 全连）
  ② CNN 单元 **只有一个** 1D 卷积（核 3 + 偏置 = 4 个参数），所有位置共用
  ③ 循环     感受器(情境＋上一步反馈) → 单元 → 效应器 13 个神经元 → 选一个 → 真执行
             → 拿反馈 → 反馈继续输入 → …　**这个循环就是训练过程**（赫布，无反向传播）
  ④ 激素     把每步权重改动量压进预算（搬类脑 MVP：U 型，最优区 0.010~0.020）

判据与题库复制自 效应器循环.py（同一套判据，便于跟第⑤层对照）。
跑法：~/mineru-env/bin/python 赫布婴儿.py     （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess
import time

import numpy as np

rng = np.random.default_rng(20261007)

# ── 动作库：族 → 只读命令（写死，安全；与 效应器循环.py 同一套）────────────
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
    ("有几个进程在跑", re.compile(r"USER\s+PID|root\s+\d+")),
    ("本机 IP 是多少", re.compile(r"\d+\.\d+\.\d+\.\d+/\d+")),
    ("CPU 几核", re.compile(r"^CPU\(s\)", re.M)),
    ("内核版本", re.compile(r"^\d+\.\d+\.\d+")),
    ("有哪些服务在跑", re.compile(r"\.service")),
    ("日志最后几条说了什么", re.compile(r"^\w{3} \d{2} \d{2}:\d{2}", re.M)),
]
# 感受器用：题面 → 槽（关键词表，属于"感受器分组"，先天）
题词: list[tuple[str, list[str]]] = [
    ("根分区还剩多少", ["分区", "磁盘"]), ("内存还剩多少", ["内存"]),
    ("8789 端口有没有在听", ["端口"]), ("现在几点", ["几点", "什么时间"]),
    ("系统跑了多久、负载多少", ["跑了多久", "负载"]), ("/tmp 占多大空间", ["/tmp"]),
    ("有几个进程在跑", ["进程"]), ("本机 IP 是多少", ["IP"]),
    ("CPU 几核", ["CPU"]), ("内核版本", ["内核"]), ("有哪些服务在跑", ["服务"]),
    ("日志最后几条说了什么", ["日志"]),
]
结果槽 = {"": 0, "成功": 1, "报错": 2, "拦截": 3}
# ★ 槽位按步长 2 排布：否则那个 CNN 单元（核 0.6/1.2/0.6）会把激活扩散到
#   **相邻槽**，12 个题槽互相串扰 → 权重学对了但 argmax 被邻居带偏（实测纯利用卡 41.7%）
槽数 = len(题词) + len(结果槽) + 3 + K      # 题12 + 结果4 + 被拦次数3 + 上一步族13 = 32
M = 槽数 * 2

# ── ② 那个"唯一的 CNN 单元"：核 3 + 偏置，像单个神经元，所有位置共用同一套
核 = np.array([0.6, 1.2, 0.6])


def 单元(a: np.ndarray) -> np.ndarray:
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1))


def 感受器(任务: str, 上一步结果: str, 被拦数: int, 上一步族: str) -> np.ndarray:
    """情境 + 上一步反馈 → 稀疏激活向量（环境反馈就从这个入口继续输入）。"""
    v: np.ndarray = np.zeros(M)
    for i, (名, 词) in enumerate(题词):
        if 名 in 任务 or any(w in 任务 for w in 词):
            v[2 * i] = 1.0
    v[2 * (len(题词) + 结果槽.get(上一步结果, 0))] = 1.0
    v[2 * (len(题词) + len(结果槽) + (0 if 被拦数 == 0 else (1 if 被拦数 == 1 else 2)))] = 1.0
    if 上一步族 in 族号:
        v[2 * (len(题词) + len(结果槽) + 3 + 族号[上一步族])] = 1.0
    return v


def 执行(族: str) -> tuple[str, str]:
    """真执行（只读白名单，5 秒超时）。危险族不在表里。"""
    命令 = 动作库[族]
    if not re.fullmatch(r"[A-Za-z0-9 _./\-]+", 命令):
        return "拒绝", "含危险成分"
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return ("成功" if 果.returncode == 0 else "报错"), (果.stdout or "") + (果.stderr or "")
    except subprocess.TimeoutExpired:
        return "报错", "超时"


def 跑(臂: str, 权初: np.ndarray, 轮数: int = 6, 学习率: float = 0.5,
       激素预算: float | None = 0.02, ε: float = 0.15) -> tuple[list[tuple[float, float]], np.ndarray]:
    权 = 权初.copy()
    记录: list[tuple[float, float]] = []
    for 轮 in range(轮数):
        中 = 0
        总步 = 0
        r = np.random.default_rng(1000 + 轮)
        for 任务, 判据 in 任务集:
            上一步结果, 上一步族, 被拦数 = "", "", 0
            走过: set[int] = set()
            命中 = False
            for _ in range(5):
                v = 感受器(任务, 上一步结果, 被拦数, 上一步族)     # ← 反馈继续输入
                h: np.ndarray = 单元(v)                            # ← 唯一那个 CNN 单元
                o = 权.T @ h                                       # ← 效应器 13 个神经元
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
                # —— ③ 赫布（局部规则：只用单元激活与环境反馈，不用反向传播）
                信号: np.ndarray = np.zeros(K)
                if 臂 == "打乱反馈":
                    # ★ 破坏"动作→后果"的因果：反馈还是真的，但绑到另一个动作上。
                    #   如果赫布学的是"动作与后果的配对"，这一臂应该学不动。
                    错 = int(r.choice([i for i in range(K) if i != 选]))
                    信号[错] = 1.0 if 好 else -1.0
                else:
                    # ★ 正信号只留「答到题」：命令成功但没答到题 ⇒ 0
                    #   （给 +0.2 会让 48 步里 36 步都变成正信号 → 被选中的族一律被加强 → 学到的是"最近选过什么"）
                    值 = 0.0
                    if 好:
                        值 = 1.0 - (0.1 * (len(走过) - 1) if 臂 == "早命中" else 0.0)
                    elif 上一步结果 == "拦截":
                        值 = -1.0
                    elif 上一步结果 == "报错":
                        值 = -0.2
                    else:
                        # ★ 白干（命令成功但没答到题）也要弱化：只给正信号的话，
                        #   12 个干扰族的初始高分压不下去，argmax 依旧乱选。
                        值 = -0.25
                    信号[选] = 值
                if 臂 == "不学":
                    pass
                else:
                    d权: np.ndarray = 学习率 * np.outer(h, 信号) - 0.05 * 学习率 * 权
                    if 激素预算 is not None:   # —— ④ 激素：压改动量预算（小到会顶天花板才真起作用）
                        m = float(np.mean(np.abs(np.asarray(d权)))) + 1e-12
                        d权 = d权 * min(1.0, 激素预算 / m)
                    权 = 权 + d权
                if 好:
                    break
            中 += 1 if 命中 else 0
        记录.append((中 / len(任务集), 总步 / len(任务集)))
    return 记录, 权


def 正确族表() -> dict[str, str]:
    """每题到底是哪个族能命中判据（真回答，不是猜）。"""
    得: dict[str, str] = {}
    for 任务, 判据 in 任务集:
        for f in 族们:
            _, 文 = 执行(f)
            if 判据.search(文):
                得[任务] = f
                break
    return 得


def 查权重(权: np.ndarray, 题表: dict[str, str]) -> None:
    """★ 直接判据：训练后「题槽 → 正确族」的边，有没有比「题槽 → 其他族」明显粗。"""
    print("\n【直接判据】训练后权重结构（比命中率干净：不看探索噪声）")
    正: list[float] = []
    他: list[float] = []
    for i, (任务, _) in enumerate(任务集):
        if 任务 not in 题表:
            continue
        j = 族号[题表[任务]]
        行 = 权[2 * i]          # ★ 题槽现在是步长 2 排布（2*i），别拿 i 去查
        正.append(float(行[j]))
        他.append(float(np.delete(行, j).mean()))
    print(f"  题槽→正确族 平均 {np.mean(正):+.4f}　题槽→其他族 平均 {np.mean(他):+.4f}"
          f"　差 {np.mean(正)-np.mean(他):+.4f}")
    print("  （差 > 0 且明显 才说明「学到了配对」；≈0 就是没学）")


if __name__ == "__main__":
    print(f"感受器 {M} 维 ｜ 效应器 {K} 族 ｜ 唯一的 CNN 单元 4 个参数 ｜ 预布线 {M}×{K}={M*K} 条")
    # ① 预布线：先撒满（★ 初始幅度必须小：×0.3 的随机偏置会把学习信号淹掉，
    #    实测那样跑出来"打乱因果"那臂反而更高分）
    权初 = rng.standard_normal((M, K)) * 0.02
    方案 = [("A 不学（纯预布线）", "不学", 0.02),
            ("B 赫布", "赫布", 0.02),
            ("C 赫布＋打乱反馈（破坏因果）", "打乱反馈", 0.02),
            ("D 赫布＋早命中更值（细分辨率）", "早命中", 0.02),
            ("E 赫布＋激素 0.005（真顶到天花板）", "赫布", 0.005),
            ("F 赫布＋激素 0.002", "赫布", 0.002)]
    print(f"  {'臂':<30s} " + " ".join(f"第{i+1}轮" for i in range(6)))
    for 名, 码, 预算 in 方案:
        t0 = time.time()
        记, _权训 = 跑(码, 权初, 激素预算=预算)
        命 = " ".join(f"{h*100:5.1f}%" for h, _ in 记)
        步 = " ".join(f"{s:5.2f}" for _, s in 记)
        print(f"  {名:<30s} {命}   ({time.time()-t0:.0f}s)")
        print(f"  {'':<30s} {步}   ← 平均步数")
    print("\n（对照：第⑤层现有机制＝图 argmax＋ε，冷启动 33.3%→75.0%、步数 4.33→2.00）")
    题表 = 正确族表()
    print("\n每题真正能命中的族：" + " ".join(f"{t[:6]}→{f}" for t, f in 题表.items()))
    _, 权训 = 跑("赫布", 权初, 激素预算=0.02)
    print("\n【未训练（预布线随机初值）】")
    查权重(权初, 题表)
    print("\n【训练后（赫布 6 轮）】")
    查权重(权训, 题表)

    # ★ 训练后"纯利用"（ε=0，不再学、不再乱试）—— 这才对应"学久了就会控制手"
    记, _ = 跑("赫布", 权训, 轮数=1, 学习率=0.0, 激素预算=None, ε=0.0)
    print(f"\n【训练 6 轮 → 纯利用】命中 {记[0][0]*100:.1f}%　平均步数 {记[0][1]:.2f}")

    # ★★ "赫布学习一久是不是就找到规律了" —— 直接测"久"
    _, 权久 = 跑("赫布", 权初, 轮数=40, 激素预算=0.02)
    print("\n【训练久一点（赫布 40 轮）】")
    查权重(权久, 题表)
    记2, _ = 跑("赫布", 权久, 轮数=1, 学习率=0.0, 激素预算=None, ε=0.0)
    print(f"  纯利用：命中 {记2[0][0]*100:.1f}%　平均步数 {记2[0][1]:.2f}")
    print(f"  （基线：不学 33.3%/4.33　第⑤层现有机制 75.0%/2.00）")
