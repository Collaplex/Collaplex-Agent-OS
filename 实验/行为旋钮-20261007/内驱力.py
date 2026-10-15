# -*- coding: utf-8 -*-
"""行为旋钮 · 内驱力（不给题目、不给对错，只喂内驱力，看循环能不能自己转起来）

老板问的三件事，这版照我的主张做：
  ① 感受器输入什么 ⇒ **三路入口**：
       世界入口  —— 环境上一步的输出（特征化）
       自省入口  —— 自己上一步做了什么（"刚才那个动作"）
       驱动力入口 —— **内部状态本身**（惊讶 e、学习进展 Δe、无聊 freq、饿）
     驱动力入口是闭环的钥匙：循环必须"感到饿"并把这份饿变成输入，不然闭环断在这儿。
  ② 怎么训练 ⇒ **不用任何外部标签**，奖励全部来自内驱力：
       r = −惊讶(e) + λ×学习进展(Δe) − μ×无聊(该动作近期被选频率)
     惊讶 = 用同一个 h 预测下一步观察的误差（自监督：自己给自己当标签）
     学习进展 = 该动作近期预测误差的下降量（不是"知道得多"，而是"学得快"）
     无聊 = 腺苷式疲劳，同一动作重复就衰减驱动力，逼它换
  ③ 效应器解码成文字 ⇒ 动作 → 命令文本（这一版先保证可读；词向量解码下一版做）

★ 关键：训练全程**不用题目的判据**。判据只在最后**事后**测一次——
   看它自由探索下来，有没有顺带发现"有用的"动作。

跑法：~/mineru-env/bin/python 内驱力.py     （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import deque

import numpy as np

# ── 环境：一组只读命令（动作），执行后拿输出特征 ──
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
观察维 = 8

# ── 感受器：三路入口 ──
自省基 = 0                      # 自省入口：上一步做了什么（K 槽）
世界基 = K                      # 世界入口：环境上一步输出（观察维 槽）
驱动基 = K + 观察维             # 驱动力入口：内部状态（4 槽：惊讶/学习进展/无聊/饿）
驱动槽数 = 4
槽数 = 驱动基 + 驱动槽数
M = 槽数 * 2                    # 每槽隔一格，防那个唯一 CNN 单元的核串扰
核 = np.array([0.6, 1.2, 0.6])


def 单元(a: np.ndarray) -> np.ndarray:
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1))


def 感受器(上一动作: int | None, 上一观察: np.ndarray, 驱动: np.ndarray) -> np.ndarray:
    v: np.ndarray = np.zeros(M)
    if 上一动作 is not None:
        v[2 * (自省基 + 上一动作)] = 1.0
    for i in range(观察维):
        if 上一观察[i] != 0.0:
            v[2 * (世界基 + i)] = 上一观察[i]
    for i in range(驱动槽数):           # ★ 驱动力入口：饿/惊讶/进展/无聊本身进感受器
        v[2 * (驱动基 + i)] = 驱动[i]
    return v


def 观察特征(文: str) -> np.ndarray:
    """把环境输出压成 8 维可观测量（这是"看效应器怎么动的入口"的粗版）。"""
    o: np.ndarray = np.zeros(观察维)
    o[0] = 1.0 if 文 else 0.0
    o[1] = min(1.0, len(文) / 4000.0)
    o[2] = min(1.0, len(re.findall(r"\d+", 文)) / 200.0)
    o[3] = min(1.0, len(re.findall(r"[A-Z]{2,}", 文)) / 50.0)
    o[4] = min(1.0, 文.count("\n") / 100.0)
    o[5] = min(1.0, len(re.findall(r"[KMGT]B?\b", 文)) / 30.0)
    o[6] = 1.0 if re.search(r"错误|error|无法|cannot|denied|No such", 文, re.I) else 0.0
    o[7] = 1.0 if re.search(r"\d+\.\d+", 文) else 0.0
    return o


def 执行(族: str) -> str:
    命令 = 动作库[族]
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return (果.stdout or "") + (果.stderr or "")
    except (subprocess.TimeoutExpired, OSError):
        return ""


if __name__ == "__main__":
    print(f"感受器 {M} 位（自省 {K} 槽 + 世界 {观察维} 槽 + **驱动力 {驱动槽数} 槽**）")
    print(f"效应器 {K} 个动作｜唯一 CNN 单元 4 参数｜★ 训练全程不看任何题目标签\n")

    r = np.random.default_rng(20261007)
    权 = r.standard_normal((M, K + 观察维)) * 0.02        # 前 K 列＝选动作，后 观察维 列＝预测观察
    ε = 0.3        # 随训练退火（见下方）
    误差均值: np.ndarray = np.ones(K) * 0.5               # 每个动作的预测误差历史（算学习进展）
    被选次数: np.ndarray = np.zeros(K)
    近窗: deque[int] = deque(maxlen=40)
    无聊: np.ndarray = np.zeros(K)

    上一步动作: int | None = None
    上一观察: np.ndarray = np.zeros(观察维)
    驱动: np.ndarray = np.array([0.0, 0.0, 0.0, 1.0])     # [惊讶 进展 无聊 饿]（饿初始 =1）
    轨迹熵: list[float] = []
    惊讶史: list[float] = []
    t0 = time.time()

    for 步 in range(3000):
        ε = 0.3 * max(0.06, 1.0 - 步 / 2000.0)      # ★ 退火：后期靠学到的偏好，不靠乱试
        # ① 感受器（三路）
        v = 感受器(上一步动作, 上一观察, 驱动)
        a: np.ndarray = np.asarray(v).copy()
        保留 = max(2, int(M * 0.08))
        应删 = len(a) - 保留
        阈 = float(np.partition(np.abs(a), 应删)[应删])
        a[np.abs(a) < 阈] = 0.0
        h: np.ndarray = 单元(a)
        o: np.ndarray = (权.T @ h) / np.sqrt(float(保留))
        # ② 效应器选动作（探索由"无聊"驱动，不是常数 ε）
        偏好 = o[:K] + 0.5 * 无聊                                    # 无聊的动作被推一把
        选 = int(r.choice(K)) if r.random() < ε else int(np.asarray(np.argmax(偏好)).item())
        # ③ 世界反馈
        文 = 执行(族们[选])
        观察 = 观察特征(文)
        # ④ 内驱力（★ 不用任何外部标签）
        预测 = o[K:]
        e = float(np.mean(np.abs(np.asarray(预测 - 观察))))          # 惊讶
        进展 = float(max(0.0, 误差均值[选] - e))                     # 学习进展（学得快 = 好）
        频率 = float(近窗.count(选)) / max(1.0, float(len(近窗)))
        # ★ 奖励只留"变化量"和"新颖"，不留常数项（−惊讶恒在 0.2 附近 = 常数 = 没有信号）
        新颖 = 1.0 / (1.0 + 被选次数[选] / 50.0)
        奖励 = 4.0 * 进展 + 0.5 * 新颖 - 1.5 * 频率
        # ⑤ 学：预测列做自监督（自己给自己当标签），动作列用内驱力奖励
        非零: np.ndarray = np.nonzero(h)[0]
        if len(非零) > 0:
            权[非零, K:] += 0.3 * np.outer(h[非零], 观察 - 预测)      # 预测编码：减小惊讶
            权[非零, 选] += 0.3 * 奖励 * h[非零]                      # 动作偏好：按内驱力调
        # ⑥ 状态推进
        误差均值[选] = 0.9 * 误差均值[选] + 0.1 * e
        被选次数[选] += 1
        近窗.append(选)
        无聊 = np.array([0.15 * (近窗.count(i) / max(1.0, float(len(近窗)))) for i in range(K)])
        饿 = float(max(0.0, 1.0 - 被选次数.sum() / 900.0))           # 探索得越多，饿越低
        驱动 = np.array([e, 进展, float(近窗.count(选)) / max(1.0, float(len(近窗))), 饿])
        if len(近窗) == 40:
            频 = np.array([近窗.count(i) for i in range(K)], dtype=float) / 40.0
            轨迹熵.append(float(-np.sum(频[频 > 0] * np.log(频[频 > 0]))))
        惊讶史.append(e)
        上一步动作, 上一观察 = 选, 观察

        if (步 + 1) % 1000 == 0:
            print(f"  步 {步+1:5d}｜惊讶 {np.mean(惊讶史[-300:]):.4f}"
                  f"｜行为熵 {轨迹熵[-1]:.3f}（满值 {np.log(K):.3f}）"
                  f"｜饿 {饿:.2f}｜{time.time()-t0:4.0f}s")

    print(f"\n【训练结束】动作被选次数（共 {int(被选次数.sum())} 步）")
    for i, f in enumerate(族们):
        print(f"  {f:<10s} 选了 {int(被选次数[i]):4d} 次　预测误差 {误差均值[i]:.3f}")
    频 = 被选次数 / 被选次数.sum()
    print(f"\n  最终行为熵 {float(-np.sum(频[频 > 0] * np.log(频[频 > 0]))):.3f}"
          f"（均匀分布满值 {np.log(K):.3f}｜只挑一个动作 = 0.000）")
    print(f"  惊讶：开头 300 步均值 {np.mean(惊讶史[:300]):.4f} → 末段 300 步 {np.mean(惊讶史[-300:]):.4f}")

    print("\n【事后测一次·训练时没用过】它摸出来的动作里，有多少是「能答到题」的：")
    判据表: list[tuple[str, str]] = [
        (r"文件系统|Filesystem", "根分区"), (r"Mem:|内存", "内存"), (r":8789", "端口"),
        (r"[\d.]+[KMGT]\s+/tmp", "/tmp 占用"), (r"^CPU\(s\)", "CPU 核数"),
        (r"\d+\.\d+\.\d+\.\d+/\d+", "本机 IP"), (r"load average", "负载"),
        (r"\bCST\b|\bUTC\b", "时间"), (r"\.service\s+(loaded|active)", "服务"),
        (r"^\w{3} \d{2} \d{2}:\d{2}", "日志"), (r"^\d+\.\d+\.\d+", "内核版本"),
    ]
    有用族: set[str] = set()
    for 族 in 族们:
        文 = 执行(族)
        if any(re.search(p, 文, re.M) for p, _ in 判据表):
            有用族.add(族)
    有用次数 = sum(int(被选次数[族号[f]]) for f in 有用族)
    总次 = float(被选次数.sum())
    print(f"  能答到题的动作 {len(有用族)}/{K} 个：" + "、".join(sorted(有用族)))
    占 = 有用次数 / 总次 * 100.0 if 总次 > 0 else 0.0
    print(f"  它们被选中 {有用次数} 次，占 {占:.1f}%"
          f"　｜　随机探索的期望占比 ≈ {len(有用族)/K*100:.1f}%")
    print(f"  ⇒ 高于期望 = 内驱力把它拉向了有用的动作；≈ 期望 = 只是乱试")
