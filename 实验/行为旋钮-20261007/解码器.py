# -*- coding: utf-8 -*-
"""行为旋钮 · 解码器（内部活动 → 文字）+ 用它当"学会没有"的探针

老板："先写解码器吧，这样才能知道模型有没有学会。但是我想起来了，效应器输出的不本来就是文字吗"
⇒ 对，但那是"从外面看"。里面看效应器吐的是**内部活动**，中间那层映射：
     · 我写死的表  → 它只会说我会的几句，而且"学会没有"永远说不清（字是我给的）
     · 学出来的映射 → 字是它自己的，而且**这层映射本身就是探针**
   这版就把这层做成"学出来的"，并拿它当验收仪器。

设计（全部从数据长，不引外部词表）：
  · 字表   ：题目里出现过的字（出现了才有槽，此表随语料长大 → "不限数量"）
  · 词表   ：命令里出现过的词 + <结束>（同上）
  · 感受器 ：三路 —— ① 教入口（题目里的字）② 自省入口（我刚吐出来的词）③ 位置入口
  · 内部   ：感受器 → 唯一 CNN 单元（4 参数）→ h
  · 解码器 ：D: h → 词（用岭回归闭式解从教学对里学，不写死映射）
  · 解码   ：逐词自回归，直到 <结束>

★ 验收分两级（这就是"知道模型有没有学会"）：
  ① 重建：教过的题，能不能解回原命令
  ② 泛化：**没教过的题**（留出），能不能解对 —— 以及解出的命令真跑一遍能不能答到题
    （后一条不用"标准答案"，直接看执行结果命中不命中）

跑法：~/mineru-env/bin/python 解码器.py     （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess

import numpy as np

# ── 语料：命令（词表从它长）+ 题目（字表从它长）──
命令库: dict[str, str] = {
    "查:磁盘": "df -h", "查:内存": "free -h", "查:占用": "du -sh /tmp", "查:端口": "ss -ltn",
    "查:进程": "ps aux", "查:服务": "systemctl list-units --type=service --no-pager",
    "查:日志": "journalctl -n 5 --no-pager", "查:硬件": "lscpu", "查:系统": "uptime",
    "查:时间": "date", "读:内核内存": "cat /proc/meminfo", "网:本地": "ip -brief addr",
    "查:内核": "uname -r",
}
全部题: list[tuple[str, str]] = [
    ("根分区还剩多少", "查:磁盘"), ("内存还剩多少", "查:内存"),
    ("杜子端口有没有在听", "查:端口"), ("现在几点", "查:时间"),
    ("系统跑了多久负载多少", "查:系统"), ("tmp 占多大空间", "查:占用"),
    ("有几个进程在跑", "查:进程"), ("本机 IP 是多少", "网:本地"),
    ("CPU 几核", "查:硬件"), ("内核版本", "查:内核"),
    ("有哪些服务在跑", "查:服务"), ("日志最后几条说了什么", "查:日志"),
]
教题 = 全部题[:8]          # 教的
留出题 = 全部题[8:]        # ★ 没教过的（验收泛化）
判据表: list[tuple[str, re.Pattern[str]]] = [
    ("查:磁盘", re.compile(r"文件系统|Filesystem")), ("查:内存", re.compile(r"Mem:|内存")),
    ("查:端口", re.compile(r":8789")), ("查:时间", re.compile(r"\bCST\b|\bUTC\b")),
    ("查:系统", re.compile(r"load average")), ("查:占用", re.compile(r"[\d.]+[KMGT]\s+/tmp")),
    ("查:进程", re.compile(r"USER\s+PID\s+%CPU")), ("网:本地", re.compile(r"\d+\.\d+\.\d+\.\d+/\d+")),
    ("查:硬件", re.compile(r"^CPU\(s\)", re.M)), ("查:内核", re.compile(r"^\d+\.\d+\.\d+")),
    ("查:服务", re.compile(r"\.service\s+(loaded|active|masked|disabled)")),
    ("查:日志", re.compile(r"^\w{3} \d{2} \d{2}:\d{2}", re.M)),
]
判据 = {f: p for f, p in 判据表}
命令到族 = {令: f for f, 令 in 命令库.items()}

# 字表：题目里出现过的字（不限数量，语料长它就长）
字表: list[str] = []
for _题, _f in 全部题:
    for _字 in _题.replace(" ", ""):
        if _字 not in 字表:
            字表.append(_字)
字号 = {z: i for i, z in enumerate(字表)}

# 词表：命令里出现过的词（同上）
词表: list[str] = ["<结束>"]
for _命 in sorted(命令库):
    for _w in 命令库[_命].split():
        if _w not in 词表:
            词表.append(_w)
词号 = {w: i for i, w in enumerate(词表)}

# ── 感受器：三路入口 ──
字基 = 0
自省基 = len(字表)
位置基 = len(字表) + len(词表)
位置槽数 = 3                      # 首位 / 中间 / 末位（"我现在吐到哪了"）
槽数 = 位置基 + 位置槽数
M = 槽数 * 2                      # 隔一格，防唯一 CNN 单元的核串扰
核对 = np.array([0.6, 1.2, 0.6])


def 单元(a: np.ndarray) -> np.ndarray:
    return np.tanh(核对[0] * np.roll(a, 1) + 核对[1] * a + 核对[2] * np.roll(a, -1))


def 感受器(题目: str, 已吐: list[str], 第几词: int, 词长: int) -> np.ndarray:
    v: np.ndarray = np.zeros(M)
    for 字 in 题目.replace(" ", ""):
        if 字 in 字号:
            v[2 * (字基 + 字号[字])] = 1.0
    if 已吐:
        v[2 * (自省基 + 词号.get(已吐[-1], 0))] = 1.0
    位 = 0 if 第几词 == 0 else (2 if 第几词 >= 词长 - 1 else 1)
    v[2 * (位置基 + 位)] = 1.0
    return v


def 激活(v: np.ndarray) -> np.ndarray:
    a: np.ndarray = np.asarray(v).copy()
    保留 = max(2, int(M * 0.10))
    应删 = len(a) - 保留
    阈 = float(np.partition(np.abs(a), 应删)[应删])
    a[np.abs(a) < 阈] = 0.0
    return 单元(a)


def 执行(族: str) -> tuple[str, str]:
    命令 = 命令库[族]
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return 命令, (果.stdout or "") + (果.stderr or "")
    except (subprocess.TimeoutExpired, OSError):
        return 命令, ""


def 造样本(题目: str, 目标命令: str) -> list[tuple[np.ndarray, int]]:
    """教学：把"题目 + 已吐前缀"逐词对齐到正确词（这是"怎么教的入口"）。"""
    词列 = 目标命令.split()
    得: list[tuple[np.ndarray, int]] = []
    for k in range(len(词列)):
        h = 激活(感受器(题目, 词列[:k], k, len(词列)))
        得.append((h, 词号[词列[k]]))
    得.append((激活(感受器(题目, 词列, len(词列), len(词列))), 词号["<结束>"]))
    return 得


if __name__ == "__main__":
    print(f"字表 {len(字表)} 字（从题目长）｜词表 {len(词表)} 词（从命令长）")
    print(f"感受器 {M} 位（教 {len(字表)} 槽 + 自省 {len(词表)} 槽 + 位置 {位置槽数} 槽）")
    print(f"教 {len(教题)} 题｜★ 留出 {len(留出题)} 题（没教过，用来验收泛化）\n")

    # ① 教学：收集 (h, 目标词)，用岭回归闭式解学解码器 D: h → 词
    样本: list[tuple[np.ndarray, int]] = []
    for 题, 族 in 教题:
        样本.extend(造样本(题, 命令库[族]))
    H = np.stack([h for h, _ in 样本])                    # (N, M)
    Y: np.ndarray = np.zeros((len(样本), len(词表)))
    for i, (_, 位) in enumerate(样本):
        Y[i, 位] = 1.0
    λ = 1e-2
    D: np.ndarray = np.linalg.solve(H.T @ H + λ * np.eye(M), H.T @ Y)   # (M, 词表)
    print(f"教学样本 {len(样本)} 条 ⇒ 解码器 {M}×{len(词表)} = {M*len(词表)} 个数（岭回归闭式解，λ={λ}）\n")

    def 解码(题目: str) -> str:
        已吐: list[str] = []
        for k in range(8):
            h = 激活(感受器(题目, 已吐, k, 8))
            分 = h @ D
            位 = int(np.asarray(np.argmax(分)).item())
            if 位 == 词号["<结束>"]:
                break
            已吐.append(词表[位])
        return " ".join(已吐)

    def 命中(族: str) -> bool:
        _, 文 = 执行(族)
        return bool(判据[族].search(文))

    print(f"  {'':<6s}{'题':<16s}{'答案命令':<34s}{'它吐出来的':<34s} 判定")
    好 = 0
    for 标, 组 in (("教过", 教题), ("留出", 留出题)):
        for 题, 族 in 组:
            吐 = 解码(题)
            对 = (吐 == 命令库[族])
            好 += 1 if 对 else 0
            print(f"  {标:<6s}{题:<16s}{命令库[族]:<34s}{吐:<34s} {'✅对' if 对 else '❌错'}")
    print(f"\n  重建+泛化合计：{好}/{len(全部题)} = {好/len(全部题)*100:.1f}%"
          f"（教对 {sum(1 for 题,族 in 教题 if 解码(题)==命令库[族])}/{len(教题)}"
          f"　留出对 {sum(1 for 题,族 in 留出题 if 解码(题)==命令库[族])}/{len(留出题)}）")

    print("\n  ★ 二级判据：它吐出来的命令，真跑去执行，能不能答到那道题")
    中 = 0
    for 题, 族 in 全部题:
        吐 = 解码(题)
         # 它吐出来的词序列，如果恰好是已知命令就真跑一遍看答不答得到
        # ★ 用**这道题自己的判据**，去看它吐出的命令的输出（不是用命令自己家族的判据）
        文 = 执行(命令到族[吐])[1] if 吐 in 命令到族 else ""
        行 = bool(判据[族].search(文))
        中 += 1 if 行 else 0
        print(f"    {题:<16s} → 「{吐 or '（空）'}」　{'答到了' if 行 else '没答到'}")
    print(f"\n  答到 {中}/{len(全部题)} = {中/len(全部题)*100:.1f}%"
          f"（这一条不用标准答案，只看执行结果）")
