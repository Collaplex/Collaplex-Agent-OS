# -*- coding: utf-8 -*-
"""行为旋钮 · 激素层（按"共传递是常态"搭，不是 100 个独立旋钮）

老板给的方向（2026-10-07）：
  · 小分子递质 10~15 种＝**骨架**（快、局部、毫秒级）→ 直接管一个具体参数
  · 神经肽 60~100+ 种＝**修饰**（慢、扩散远、持久）→ 不直接改参数，改的是"骨架激素的效力"
  · **共传递是常态**：一个神经元同时放 2~3 种 ⇒ 不是 100 个独立通道，是 100 种原料按比例**复配**
  · **决定复杂度的不是种数，是受体亚型组合与连接方式** ⇒ 同一激素对不同参数走不同"受体"（增益型/时型）
  · 气体（NO 等）**没有受体**，直接扩散 → 按局部浓度加到邻近单元，不走通道
  · 脂类（内源大麻素）**逆向传递**：突触后→突触前"少放点" ⇒ 由输出侧反过来压输入侧

这版上 14 种（骨架 8 + 修饰 4 + 气体 1 + 逆向 1），照老板的设计接到"从命令表里选"那版
（赫布扩展 N=512，基线 83.3%）上当试验台测：**单因子** vs **共传递复配**。

跑法：~/mineru-env/bin/python 赫布激素.py    （纯 numpy，真执行只读命令，0 元）
"""

from __future__ import annotations

import re
import subprocess
import time

import numpy as np

# ─────────────────────────── 激素层 ───────────────────────────

骨架默认: dict[str, float] = {
    "Glu": 1.0,      # 谷氨酸  兴奋增益（读出整体放大）
    "GABA": 1.0,     # γ-氨基丁酸 抑制（对没被选中的动作压多狠）
    "DA": 1.0,       # 多巴胺  学习率
    "NE": 0.15,      # 去甲肾上腺素 探索率
    "5HT": 0.0,      # 5-羟色胺 单次改动量预算（0 = 不限）
    "ACh": 1.0,      # 乙酰胆碱 激活稀疏闸（乘在保留比例上）
    "His": 1.0,      # 组胺    觉醒度（读出温度）
    "Ado": 0.0,      # 腺苷    疲劳（压学习率）
}
修饰默认: dict[str, float] = {
    "OXT": 0.0,      # 催产素  信任 → 放宽探索广度（放大 NE 的效力）
    "NPY": 0.0,      # 神经肽Y 食欲 → 多试几次
    "CCK": 0.0,      # 胆囊收缩素 饱腹 → 早点收手
    "End": 0.0,      # 内啡肽  奖励基线 → 抬高正信号底线
}
气体默认: dict[str, float] = {
    "NO": 0.0,       # 一氧化氮 无受体，按浓度直接加到邻近单元
}
逆向默认: dict[str, float] = {
    "2AG": 0.0,      # 内源大麻素 逆向：输出差 → 反过来压输入强度
}

激素默认: dict[str, float] = {**骨架默认, **修饰默认, **气体默认, **逆向默认}


def 复配(激素: dict[str, float], 慢速: dict[str, float]) -> dict[str, float]:
    """★ 共传递：每个参数都是多种激素按"受体权重"复配出来的，不是一个激素对一个旋钮。

    慢速 里放的是"修饰层"的当前浓度（有积分、起效慢），体现神经肽的"整体态度"。
    """
    GABA = 激素["GABA"]
    DA = 激素["DA"] * (1.0 + 激素["End"] + 慢速["End"]) * (1.0 - 激素["Ado"])      # DA×内啡肽×腺苷
    NE = 激素["NE"] * (1.0 + 激素["OXT"] + 慢速["OXT"])                            # NE×催产素
    ACh = 激素["ACh"]
    Glu = 激素["Glu"] * (1.0 + 激素["His"] * 0.5)                                  # Glu×组胺
    试探 = max(1, 3 + int(round(激素["NPY"] * 2 + 慢速["NPY"] * 2 - 激素["CCK"] * 2 - 慢速["CCK"] * 2)))
    return {
        "学习率": max(0.0, DA), "探索": max(0.0, NE), "保留": ACh, "抑制": GABA,
        "读出": max(0.05, Glu), "试探": 试探, "预算": 激素["5HT"],
        "NO": 激素["NO"], "2AG": 激素["2AG"],
    }


# ─────────────────────────── 环境（照抄赫布扩展那版）───────────────────────────

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
基础维 = 基础槽 * 2
核 = np.array([0.6, 1.2, 0.6])
感受器数 = 512                                  # 赫布扩展实测：512 就到顶（832 边 75%，6,656 边 83.3%）


def 单元(a: np.ndarray) -> np.ndarray:
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


def 建扩展() -> np.ndarray:
    P: np.ndarray = np.zeros((基础维, 感受器数))
    for j in range(感受器数):
        位 = rng.choice(基础维, size=4, replace=False)
        P[位, j] = rng.choice([-1.0, 1.0], size=4)
    return P


def 执行(族: str) -> tuple[str, str]:
    命令 = 动作库[族]
    if not re.fullmatch(r"[A-Za-z0-9 _./\-]+", 命令):
        return "拦截", "含危险成分"
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5)
        return ("成功" if 果.returncode == 0 else "报错"), (果.stdout or "") + (果.stderr or "")
    except subprocess.TimeoutExpired:
        return "报错", "超时"
    except OSError as 错:
        return "报错", f"跑不起来：{错}"


def 激活(v: np.ndarray, P: np.ndarray, 激素参数: dict[str, float]) -> np.ndarray:
    a = P.T @ v
    保留 = max(4, int(感受器数 * 0.05 * 激素参数["保留"]))
    if 保留 < len(a):
        阈 = np.partition(np.abs(a), len(a) - 保留)[len(a) - 保留]
        a[np.abs(a) < 阈] = 0.0
    if 激素参数["NO"] > 0:                       # ★ 气体：无受体，直接扩散到邻近单元
        邻 = (np.roll(a, 1) + np.roll(a, -1)) * 0.5
        a = a + 激素参数["NO"] * 邻 * (a != 0.0)
    return a


def 跑(轮数: int, P: np.ndarray, 权初: np.ndarray, 激素: dict[str, float],
      学习率: float = 0.5, ε: float = 0.15, 打分: bool = False) -> tuple[float, float, np.ndarray]:
    权 = 权初.copy()
    慢速: dict[str, float] = {k: 0.0 for k in 修饰默认}      # 神经肽：慢，每轮朝目标靠一点
    中 = 0
    总步 = 0
    for 轮 in range(轮数):
        for k in 慢速:                                      # ★ 慢递质积分（扩散远、作用持久）
            慢速[k] += 0.15 * (激素[k] - 慢速[k])
        参 = 复配(激素, 慢速)
        r = np.random.default_rng(1000 + 轮)
        for 任务, 判据 in 任务集:
            上一步结果, 上一步族, 被拦数 = "", "", 0
            走过: set[int] = set()
            命中 = False
            线索强度 = 1.0
            for _ in range(int(参["试探"]) + 2):
                v = 基础向量(任务, 上一步结果, 被拦数, 上一步族)
                if 激素["2AG"] > 0:                         # ★ 逆向：输出差 → 压输入强度（少放点）
                    线索强度 = max(0.3, 线索强度 * (1.0 - 激素["2AG"] * 0.3))
                    v = v * 线索强度
                a = 激活(v, P, 参)
                h: np.ndarray = 单元(a)
                o: np.ndarray = (权.T @ h) * 参["读出"] / np.sqrt(float(max(1, int(感受器数 * 0.05))))
                选 = int(r.choice(K)) if (r.random() < 参["探索"]) else int(np.asarray(np.argmax(o)).item())
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
                if 打分:
                    break
                信号: np.ndarray = np.zeros(K)
                if 好:
                    信号[选] = 1.0 + 激素["End"]                # 内啡肽抬高奖励基线
                elif 上一步结果 == "拦截":
                    信号[选] = -1.0
                elif 上一步结果 == "报错":
                    信号[选] = -0.2
                else:
                    信号[选] = -0.25 * 参["抑制"]               # GABA 管压多狠
                非零: np.ndarray = np.nonzero(h)[0]
                if len(非零) == 0:
                    continue
                未: np.ndarray = 学习率 * 参["学习率"] * np.outer(h[非零], 信号)
                if 参["预算"] > 0:
                    m = float(np.mean(np.abs(未))) + 1e-12
                    未 = 未 * min(1.0, 参["预算"] / m)
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


def 查权重(权: np.ndarray, P: np.ndarray) -> float:
    题表 = 正确族表()
    正: list[float] = []
    他: list[float] = []
    for i, (任务, _) in enumerate(任务集):
        if 任务 not in 题表:
            continue
        j = 族号[题表[任务]]
        贡献 = (P[2 * i] @ 权) / max(1.0, float(np.count_nonzero(P[2 * i])))
        正.append(float(贡献[j]))
        他.append(float(np.delete(贡献, j).mean()))
    return float(np.mean(正)) - float(np.mean(他))


if __name__ == "__main__":
    print(f"感受器 {基础维} 槽 → 稀疏扩展 {感受器数} 单元｜效应器 {K} 族｜唯一 CNN 单元 4 参数")
    print(f"预布线 {感受器数}×{K} = {感受器数 * K} 条边｜激素 14 种（骨架8 修饰4 气体1 逆向1）\n")
    P = 建扩展()
    权基 = rng.standard_normal((感受器数, K)) * 0.02

    print(f"  {'档':<26s} {'命中':>7s} {'步数':>7s} {'权重差':>9s} {'耗时':>6s}")
    档位: list[tuple[str, dict[str, float]]] = [
        ("基线（骨架默认·修饰0）", dict(激素默认)),
        ("Glu↑ 兴奋增益×3", {**激素默认, "Glu": 3.0}),
        ("GABA↑ 抑制×3", {**激素默认, "GABA": 3.0}),
        ("DA↑ 学习率×3", {**激素默认, "DA": 3.0}),
        ("NE↑ 探索0.5", {**激素默认, "NE": 0.5}),
        ("5HT↑ 改动预算0.02", {**激素默认, "5HT": 0.02}),
        ("ACh↑ 稀疏闸×4", {**激素默认, "ACh": 4.0}),
        ("His↑ 觉醒×3", {**激素默认, "His": 3.0}),
        ("Ado↑ 疲劳0.8", {**激素默认, "Ado": 0.8}),
        ("修饰4种全开", {**激素默认, "OXT": 0.5, "NPY": 0.5, "CCK": 0.3, "End": 0.5}),
        ("NO↑ 气体扩散0.5", {**激素默认, "NO": 0.5}),
        ("2AG↑ 逆向0.5", {**激素默认, "2AG": 0.5}),
        ("★复配 DA+End+Ado", {**激素默认, "DA": 2.0, "End": 0.6, "Ado": 0.5}),
        ("★单打 DA 2.0（对照）", {**激素默认, "DA": 2.0}),
    ]
    for 名, 档 in 档位:
        t0 = time.time()
        _, _, 权训 = 跑(30, P, 权基, 档)
        命中, 步数, _ = 跑(1, P, 权训, 档, ε=0.0, 打分=True)
        d = 查权重(权训, P)
        print(f"  {名:<26s} {命中*100:6.1f}% {步数:7.2f} {d:+9.3f} {time.time()-t0:5.0f}s")
    print(f"\n  （对照：不学 33.3%／4.33　旧机制 75.0%／2.00　赫布扩展 83.3%／1.75）")
