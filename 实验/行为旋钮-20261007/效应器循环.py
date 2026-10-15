"""行为旋钮 · 骨架第⑤层：效应器接口（婴儿循环）

闭环一题一题跑，像婴儿一样试错：
    看情境 → 图推荐做法 → 落成命令 → 真执行(只读白名单) → 拿反馈 → 更新边权 → 下一题

安全边界（硬规则）：
  · 动作库全部是**只读**命令，且写死在表里，不由模型生成
  · 危险族（rm / find -delete / sudo …）只在表里存在，永不执行
  · 每条命令 5 秒超时、非交互、不碰任何用户数据

测量：每跑一轮（12 道只读题），看**平均步数**和**判据命中率**有没有随轮数改善。
对照：冷启动（图全空）vs 热启动（先用历史 2343 步的反馈把图喂一遍）
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import 预布线 as 预

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent

# ── 动作库：族 → 只读命令（写死，安全）────────────────────────
动作库: dict[str, str] = {
    "查:磁盘": "df -h",
    "查:内存": "free -h",
    "查:占用": "du -sh /tmp",
    "查:端口": "ss -ltn",
    "查:进程": "ps aux",
    "查:服务": "systemctl list-units --type=service --no-pager",
    "查:日志": "journalctl -n 5 --no-pager",
    "查:硬件": "lscpu",
    "查:系统": "uptime",
    "查:时间": "date",
    "读:内核内存": "cat /proc/meminfo",
    "网:本地": "ip -brief addr",
    "查:内核": "uname -r",
}
危险族 = {"删:递归强制", "删:递归", "删:find带条件", "删:find裸删", "删:点名"}

# ── 任务 + 机械判据（能从输出里直接核）────────────────────────
任务集: list[tuple[str, re.Pattern[str]]] = [
    ("根分区还剩多少", re.compile(r"文件系统|Filesystem")),          # 只有 df 有表头
    ("内存还剩多少", re.compile(r"Mem:|内存")),                      # 只有 free 有
    ("8789 端口有没有在听", re.compile(r":8789")),                   # 只有 ss 有
    ("现在几点", re.compile(r"\bCST\b|\bUTC\b")),                  # 只有 date 带时区名
    ("系统跑了多久、负载多少", re.compile(r"load average")),          # 只有 uptime 有
    ("/tmp 占多大空间", re.compile(r"[\d.]+[KMGT]\s+/tmp")),         # 只有 du 这么打
    ("有几个进程在跑", re.compile(r"USER\s+PID|root\s+\d+")),        # 只有 ps 有表头
    ("本机 IP 是多少", re.compile(r"\d+\.\d+\.\d+\.\d+/\d+")),       # ip -brief 是 地址/掩码 形态
    ("CPU 几核", re.compile(r"^CPU\(s\)", re.M)),                    # 只有 lscpu 有
    ("内核版本", re.compile(r"^\d+\.\d+\.\d+")),                  # 只有 uname -r 是纯版本号
    ("有哪些服务在跑", re.compile(r"\.service")),                   # 只有 systemctl 有
    ("日志最后几条说了什么", re.compile(r"^\w{3} \d{2} \d{2}:\d{2}", re.M)),  # 只有 journalctl 格式
]

# ── 情境节点（用记忆库）───────────────────────────────────────
库原: Any = json.loads((项目 / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
_列: list[Any] = cast("list[Any]", 库原) if isinstance(库原, list) else cast("list[Any]", 库原.get("items", []))
节点文 = [str(cast("dict[str, Any]", x).get("text", "")) for x in _列 if isinstance(x, dict)]
停 = {"这个", "那个", "什么", "怎么", "可以", "不是", "就是", "一个", "现在", "已经", "如果", "因为",
      "所以", "但是", "然后", "还是", "没有", "需要", "能不能", "问题", "结果", "时候", "这里", "我们",
      "本机", "命令", "执行", "输出", "文件", "目录", "用户", "要求", "建议", "使用", "可能", "应该"}
词形 = re.compile(r"[\u4e00-\u9fff]{2,4}|[A-Za-z_][A-Za-z0-9_.\-]{1,15}")


def 关键(文: str) -> set[str]:
    return {w for w in 词形.findall(文) if w not in 停}


节点词 = [关键(t) for t in 节点文]


任务号: dict[str, int] = {t: len(节点文) + i for i, (t, _) in enumerate(任务集)}


def 情境节点(文: str, 上一步结果: str = "", 被拦次数: int = 0) -> list[int]:
    """记忆库节点（词面重叠≥2）＋ 任务节点 ＋ 感受器槽（预布线用）。"""
    词 = 关键(文)
    得 = [i for i, k in enumerate(节点词) if len(k & 词) >= 2][:8]
    for t, i in 任务号.items():
        if t in 文:
            得.append(i)
    类 = 预.判任务类(文)
    if 类:
        得.append(预.任务类号(类))
    if 上一步结果 in 预.上一步槽:
        得.append(预.上一步槽[上一步结果])
    得.append(预.被拦次数槽["0" if 被拦次数 == 0 else ("1" if 被拦次数 == 1 else "多")])
    return 得


def 执行(命令: str) -> tuple[str, str]:
    """只执行白名单里的只读命令；其它一律拒绝。"""
    if 命令 not in set(动作库.values()):
        return "拒绝", "不在白名单"
    if any(x in 命令 for x in ("rm ", "sudo", "-delete", ">", "|", "&&")):
        return "拒绝", "含危险成分"
    try:
        果 = subprocess.run(命令.split(), capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
        文 = (果.stdout or "") + (果.stderr or "")
        # ★ 判据要跑在**完整输出**上：截断只能发生在"给人看/入库"那一层。
        #   实测坑：`ss -ltn` 里 8789 那行、`lscpu` 里 CPU(s) 那行都在 600 字之后，
        #   预先截断 → 判据永远找不到 → 边被罚到负 → 该题永远学不会。
        return ("成功" if 果.returncode == 0 else "报错"), 文
    except subprocess.TimeoutExpired:
        return "报错", "超时"


族们 = sorted(动作库)
族号 = {f: i for i, f in enumerate(族们)}
预元 = 预.边表(族们)["元"]
预边 = 预.边表(族们)["边"]


def 反射偏置(上一步结果: str, 上一步族: str, 被拦次数: int) -> dict[int, float]:
    """预布线里的条件反射：被拦了就压低原路、给别的路加分（不学习也生效）。"""
    偏: dict[int, float] = {}
    if 上一步结果 != "拦截":
        return 偏
    for i in 族号.values():
        偏[i] = float(预元["偏置"]["被拦_换族加分"])
    if 上一步族 in 族号:
        偏[族号[上一步族]] = float(预元["偏置"]["被拦_压原路"])
        if 被拦次数 >= 2:
            偏[族号[上一步族]] += float(预元["偏置"]["被拦多_再压"])
    return 偏


def 一轮(权重: dict[tuple[int, int], float], 轮次: int, 学习率: float, 反射: bool = False) -> tuple[float, float]:
    总步, 中数 = 0, 0
    ε = 0.15
    rng = __import__("random").Random(1000 + 轮次)
    for 任务, 判据 in 任务集:
        走过: list[int] = []                      # 这轮试过哪些族
        走过观: list[list[int]] = []
        上一步结果, 上一步族, 被拦数 = "", "", 0
        命中步 = -1
        for _ in range(5):
            观 = 情境节点(任务, 上一步结果, 被拦数)
            总步 += 1
            # ★ 先天优先：预布线槽（任务类槽）说了算；槽没主意时才听记忆边的
            分槽: defaultdict[int, float] = defaultdict(float)
            分忆: defaultdict[int, float] = defaultdict(float)
            for n in 观:
                if n >= 预.槽起点:
                    for i in 族号.values():
                        分槽[i] = max(分槽[i], 权重.get((n, i), 0.0))
                else:
                    for i in 族号.values():
                        分忆[i] = max(分忆[i], 权重.get((n, i), 0.0))
            分 = 分槽 if any(v > 0 for v in 分槽.values()) else 分忆
            if 反射:
                for i, v in 反射偏置(上一步结果, 上一步族, 被拦数).items():
                    分[i] += v
            可选 = [i for i in 族号.values() if i not in 走过] or list(族号.values())
            若按分 = [i for i in 可选 if 分.get(i, 0.0) > 0]
            if 若按分 and rng.random() >= ε:
                选 = max(若按分, key=lambda i: 分[i])
            else:
                选 = rng.choice(可选)                # 没把握就换个没试过的，别原地打转
            走过.append(选)
            走过观.append(观)
            上一步族 = 族们[选]
            上一步结果, 反馈 = 执行(动作库[上一步族])
            if 上一步结果 == "拦截":
                被拦数 += 1
            if 判据.search(反馈):
                命中步 = len(走过) - 1
                break
        # 延迟奖励：整题跑完回头看——答到了 → 那一步重赏；没答到 → 走过的全罚
        for j, i in enumerate(走过):
            if 命中步 >= 0:
                奖 = 2.0 if j == 命中步 else -0.3
            else:
                奖 = -1.0
            for n in 走过观[j]:
                权重[(n, i)] = 权重.get((n, i), 0.0) + 学习率 * 奖
        中数 += int(命中步 >= 0)
    return 总步 / len(任务集), 中数 / len(任务集)


def 热启动() -> dict[tuple[int, int], float]:
    """用历史 2343 步的反馈先把图喂一遍（不做探索，只按奖励加权）。"""
    快 = [json.loads(x) for x in (这里 / "情境快照.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    权: dict[tuple[int, int], float] = {}
    for x in 快:
        观 = 情境节点(f"{x['任务']} {x['上一步反馈']}")
        f = 粗族(str(x["本步动作"]))
        if f not in 族号:
            continue
        奖 = 1.0 if x["本步结果"] == "成功" else (-1.0 if x["本步结果"] == "拦截" else 0.0)
        for n in 观:
            权[(n, 族号[f])] = 权.get((n, 族号[f]), 0.0) + 0.1 * 奖
    return 权


def 粗族(动: str) -> str:
    d = 动.strip()
    首群 = [x for x in d.split() if x != "sudo"]
    if not 首群:
        return "?"
    首 = 首群[0].split("/")[-1]
    表 = {"df": "查:磁盘", "free": "查:内存", "du": "查:占用", "ss": "查:端口", "netstat": "查:端口",
          "ps": "查:进程", "pgrep": "查:进程", "systemctl": "查:服务", "journalctl": "查:日志",
          "lscpu": "查:硬件", "lshw": "查:硬件", "dmidecode": "查:硬件", "nvidia-smi": "查:硬件",
          "uptime": "查:系统", "date": "查:时间", "cat": "读:内核内存", "ip": "网:本地"}
    if "-delete" in d or d.startswith("rm") or "rm -" in d:
        return "删:递归强制"
    return 表.get(首, "其他")


def 预布线初值() -> dict[tuple[int, int], float]:
    """把预布线表的"本命反射"读成初值（槽号|族名 → 权重）。"""
    权: dict[tuple[int, int], float] = {}
    for k, v in 预边.items():
        槽号, 族名 = k.split("|")
        权[(int(槽号), 族号[族名])] = float(v)
    return 权


方案: list[tuple[str, dict[tuple[int, int], float], float, bool]] = [
    ("A 冷启动      无预布线 · 无反射 · 学习", {}, 0.6, False),
    ("B 只有反射    无预布线 · 有反射 · 学习", {}, 0.6, True),
    ("C 纯先天      有预布线 · 有反射 · 不学习", 预布线初值(), 0.0, True),
    ("D 先天+学习   有预布线 · 有反射 · 学习", 预布线初值(), 0.6, True),
]
print("四档对照（每档只差一个变量；每轮 12 题）")
print(f"  预布线本命反射 {len(预边)} 条（任务类 → 本命做法）")
结果: dict[str, dict[tuple[int, int], float]] = {}
for 名, 初, 率, 反射 in 方案:
    权 = dict(初)
    hits: list[float] = []
    steps: list[float] = []
    for 轮 in range(6):
        步均, 命中 = 一轮(权, 轮, 率, 反射)
        hits.append(命中)
        steps.append(步均)
    结果[名] = 权
    print(f"\n  {名}")
    print("    命中率  " + " ".join(f"{h*100:5.1f}%" for h in hits))
    print("    平均步数 " + " ".join(f"{s:5.2f} " for s in steps))

print("\n每题的首选做法（D 档 先天+学习 跑完 6 轮后）:")
权D = 结果["D 先天+学习   有预布线 · 有反射 · 学习"]
漏了: list[str] = []
for 任务, 判据 in 任务集:
    观 = 情境节点(任务)
    分槽: defaultdict[int, float] = defaultdict(float)
    分忆: defaultdict[int, float] = defaultdict(float)
    for n in 观:
        桶 = 分槽 if n >= 预.槽起点 else 分忆
        for i in 族号.values():
            桶[i] = max(桶[i], 权D.get((n, i), 0.0))
    分 = 分槽 if any(v > 0 for v in 分槽.values()) else 分忆
    好 = max(分.items(), key=lambda kv: kv[1])[0] if 分 else -1
    名 = 族们[好] if 好 >= 0 else "—"
    原文 = 执行(动作库[名])[1] if 名 in 动作库 else ""
    对 = "✓" if 判据.search(原文) else "✗"
    if 对 == "✗":
        漏了.append(f"{任务} → 选了 {名}({动作库.get(名, '—')})")
    print(f"  {任务:22s} → {名:8s} {动作库.get(名, '—'):24s} {对}")
print(f"\n★ 这套预布线判类对不对: {12 - len(漏了)}/12")
for x in 漏了:
    print(f"    漏: {x}")
