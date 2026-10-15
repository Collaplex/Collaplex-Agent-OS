# -*- coding: utf-8 -*-
"""行为旋钮 · 赫布语言（效应器输出文字 + 激素一组 + 感受器两个入口）

老板 2026-10-07 的三处更正，这版照做：
  ① 激素"有非常多的" ⇒ 这版上 **5 种**，各管一件事：
       DA   多巴胺   —— 学习率（学得快慢）
       5-HT 血清素   —— 改动量预算（稳住 / 冲动）
       NE   去甲肾上腺素 —— 探索率 ε（警觉 / 乱试）
       ACh  乙酰胆碱 —— 激活保留比例（注意闸 / 稀疏度）
       GABA          —— 抑制强度（对没被选中的词压多狠）
  ② 效应器 = "把我们的话输出成文字" ⇒ 不再从固定命令表里选 1 条，而是**逐词拼出一条命令**
  ③ 感受器 = 两个入口，都不限数量：
       a) **怎么教的入口**：题槽（题库长一个就加一个槽，不限数量）
       b) **看效应器怎么动的入口**：自己刚输出的那个词（词表长一个就加一个槽，不限数量）
       另外加一组环境观察槽（有没有命中 / 报错 / 拦截 / 输出长度分档）

循环 = 训练：感受器 → CNN 集群（唯一单元，4 参数，撒满）→ 效应器逐词输出 → 观察
→ 反馈回灌成下一次感受器输入 → 赫布（局部规则，无反向传播）。
奖励延迟到整条命令跑完才回传（信用分配用"痕迹"：生成时每一步的激活都留着）。

跑法：~/mineru-env/bin/python 赫布语言.py     （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess
import time

import numpy as np

# ── 词表（命令词 + 结束符）：不限数量，长一个就多一个感受器槽 / 效应器输出位 ──
命令库: dict[str, str] = {
    "查:磁盘": "df -h", "查:内存": "free -h", "查:占用": "du -sh /tmp", "查:端口": "ss -ltn",
    "查:进程": "ps aux", "查:服务": "systemctl list-units --type=service --no-pager",
    "查:日志": "journalctl -n 5 --no-pager", "查:硬件": "lscpu", "查:系统": "uptime",
    "查:时间": "date", "读:内核内存": "cat /proc/meminfo", "网:本地": "ip -brief addr",
    "查:内核": "uname -r",
}
结束符 = "<结束>"
词表: list[str] = [结束符]
for _命, _令 in sorted(命令库.items()):
    for _w in _令.split():
        if _w not in 词表:
            词表.append(_w)
词号 = {w: i for i, w in enumerate(词表)}

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
题目数 = len(任务集)
环境槽数 = 5

# 感受器 = 教学段(题) + 自我观察段(上一个词) + 环境段；每槽占 2 位（隔开，防唯一 CNN 单元的核串扰）
教学基 = 0
自我基 = 题目数
环境基 = 题目数 + len(词表)
槽数 = 环境基 + 环境槽数
M = 槽数 * 2
核 = np.array([0.6, 1.2, 0.6])


def 单元(a: np.ndarray) -> np.ndarray:
    """那个唯一的 CNN 单元（4 个参数），所有位置共用。"""
    return np.tanh(核[0] * np.roll(a, 1) + 核[1] * a + 核[2] * np.roll(a, -1))


def 感受器(题号: int, 上一个词: str | None, 环境: np.ndarray) -> np.ndarray:
    v: np.ndarray = np.zeros(M)
    v[2 * (教学基 + 题号)] = 1.0
    if 上一个词 is not None and 上一个词 in 词号:
        v[2 * (自我基 + 词号[上一个词])] = 1.0
    for i in range(环境槽数):
        if 环境[i] > 0:
            v[2 * (环境基 + i)] = 环境[i]
    return v


def 环境向量(果: str, 文: str, 命中: bool) -> np.ndarray:
    """看效应器怎么动的入口（环境那一份）：命中／报错／拦截／输出长短。"""
    e: np.ndarray = np.zeros(环境槽数)
    e[0] = 1.0 if 命中 else 0.0
    e[1] = 1.0 if 果 == "报错" else 0.0
    e[2] = 1.0 if 果 == "拦截" else 0.0
    e[3] = 1.0 if len(文) > 200 else 0.0
    e[4] = 1.0 if len(文) <= 200 else 0.0
    return e


合法首词: frozenset[str] = frozenset(令.split()[0] for 令 in 命令库.values())


def 执行(命令: str) -> tuple[str, str]:
    if not 命令 or not re.fullmatch(r"[A-Za-z0-9 _./\-]+", 命令):
        return "拦截", "空或含危险成分"
    首词 = 命令.split()[0]
    if 首词 not in 合法首词:
        return "无效", f"拼错了：{首词} 不是命令"
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return ("成功" if 果.returncode == 0 else "报错"), (果.stdout or "") + (果.stderr or "")
    except subprocess.TimeoutExpired:
        return "报错", "超时"
    except OSError as 错:
        return "报错", f"跑不起来：{错}"


def 生成(v0: np.ndarray, 权: np.ndarray, 激素: dict[str, float], 保留: int,
         r: np.random.Generator) -> tuple[str, list[tuple[np.ndarray, int]]]:
    """★ 效应器：逐词拼出一条命令（不是从表里选）。返回命令 + 痕迹（用于延迟更新）。"""
    词列: list[str] = []
    痕迹: list[tuple[np.ndarray, int]] = []
    上一个词: str | None = None
    for _ in range(8):
        v = v0.copy()
        if 上一个词 is not None:
            v[2 * (自我基 + 词号[上一个词])] = 1.0
        a = 激活(v, 保留)
        h: np.ndarray = 单元(a)
        o: np.ndarray = (权.T @ h) / np.sqrt(float(max(1, 保留)))
        位 = int(r.choice(len(词表))) if r.random() < 激素["NE"] else int(np.asarray(np.argmax(o)).item())
        痕迹.append((np.nonzero(h)[0], 位))
        if 位 == 词号[结束符]:
            break
        词列.append(词表[位])
        上一个词 = 词表[位]
    return " ".join(词列), 痕迹


def 激活(v: np.ndarray, 保留: int) -> np.ndarray:
    """ACh 管这里：只让一部分单元亮（注意闸）。"""
    a = v * 1.0
    if 保留 < len(a):
        阈 = np.partition(np.abs(a), len(a) - 保留)[len(a) - 保留]
        a[np.abs(a) < 阈] = 0.0
    return a


def 跑(轮数: int, 权初: np.ndarray, 激素: dict[str, float], 学习率: float = 0.5) -> tuple[float, float, np.ndarray]:
    权 = 权初.copy()
    保留 = max(4, int(M * 激素["ACh"]))
    中 = 0
    总步 = 0
    for 轮 in range(轮数):
        r = np.random.default_rng(2000 + 轮)
        for 题号, (_任务, 判据) in enumerate(任务集):
            环境: np.ndarray = np.zeros(环境槽数)
            命中 = False
            for _试 in range(3):
                v0 = 感受器(题号, None, 环境)
                命令, 痕迹 = 生成(v0, 权, 激素, 保留, r)
                总步 += 1
                果, 文 = 执行(命令)
                好 = bool(判据.search(文))
                命中 = 命中 or 好
                # ★ 奖励延迟回传：整条命令跑完才知道好不好，再用"痕迹"把信用分给每一步
                信号 = 1.0 if 好 else (-1.0 if 果 == "拦截" else (-0.5 if 果 == "无效" else (-0.2 if 果 == "报错" else -0.25)))
                for 索引, 位 in 痕迹:
                    if len(索引) == 0:
                        continue
                    行: np.ndarray = 权[索引].copy()
                    行[:, 位] += 学习率 * 激素["DA"] * 信号      # DA 管学得快慢
                    行 *= (1.0 - 0.05 * 激素["GABA"])            # GABA：对没被选中的词整体压制
                    步长 = 1.0
                    if 激素["5-HT"] > 0:                        # 5-HT：限制一次改动多大
                        m = float(np.mean(np.abs(行 - 权[索引]))) + 1e-12
                        步长 = min(1.0, 激素["5-HT"] / m)
                    权[索引] = 权[索引] + (行 - 权[索引]) * 步长
                环境 = 环境向量(果, 文, 好)
                if 好:
                    break
            中 += 1 if 命中 else 0
    return 中 / 题目数, 总步 / 题目数, 权


def 做激素(DA: float = 1.0, 血清素: float = 0.0, NE: float = 0.15,
          ACh: float = 0.05, GABA: float = 1.0) -> dict[str, float]:
    return {"DA": DA, "5-HT": 血清素, "NE": NE, "ACh": ACh, "GABA": GABA}


if __name__ == "__main__":
    print(f"感受器 {M} 位（教学 {题目数} 槽 + 自我观察 {len(词表)} 槽 + 环境 {环境槽数} 槽，都隔开）")
    print(f"效应器 {len(词表)} 个词位（逐词拼命令）｜唯一 CNN 单元 4 参数｜激素 5 种")
    权初 = np.random.default_rng(7).standard_normal((M, len(词表))) * 0.02
    print(f"预布线：{M}×{len(词表)} = {M * len(词表)} 条边\n")

    print(f"  {'激素档':<22s} {'命中':>7s} {'步数':>7s} {'耗时':>6s}")
    基准 = 做激素()
    for 名, 档 in [
        ("全部默认（DA1 NE.15）", 基准),
        ("DA 3.0（学快）", 做激素(DA=3.0)),
        ("DA 0.2（学慢）", 做激素(DA=0.2)),
        ("NE 0（不乱试）", 做激素(NE=0.0)),
        ("NE 0.5（多乱试）", 做激素(NE=0.5)),
        ("ACh 0.02（更稀疏）", 做激素(ACh=0.02)),
        ("ACh 0.20（更宽）", 做激素(ACh=0.20)),
        ("5-HT 0.02（限改动）", 做激素(血清素=0.02)),
        ("GABA 0（不压别的词）", 做激素(GABA=0.0)),
        ("GABA 3（狠压别的词）", 做激素(GABA=3.0)),
    ]:
        t0 = time.time()
        _, _, 权训 = 跑(30, 权初, 档)
        命中, 步数, _ = 跑(1, 权训, 做激素(NE=0.0))
        print(f"  {名:<22s} {命中*100:6.1f}% {步数:7.2f} {time.time()-t0:5.0f}s")
    print(f"\n  （对照：从固定命令表里选 1 条的旧机制 75.0%／步数 2.00）")
