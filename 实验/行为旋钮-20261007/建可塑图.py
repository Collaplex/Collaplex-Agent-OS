"""行为旋钮 · 骨架第③层：可塑性图层

两种节点：
  情境节点 = 记忆库里的条目（情境文本命中谁）
  行为节点 = 做法族（命令的前两个词，如 "rm -rf" / "df -h" / "cat /proc"）
边 = (情境节点 → 行为节点) 的权重，按环境反馈更新：
  这一步成功了 → 这条边 +学习率；被拦了 → 这条边 −惩罚；整图每段不用就 ×衰减

像是在线喂 2343 步（按时间顺序），后面 30% 当考试：
  考题 = "上一步被拦、下一步该怎么做" —— 看它推的是避开了坑，还是正好是那个成功做法。
三档对照：① 完全不更新（静态）② 只加强不减弱 ③ 成功加强 + 被拦减弱 + 衰减
"""

from __future__ import annotations

import json
import re
from collections import Counter as Counter2, defaultdict
from pathlib import Path
from typing import Any, cast

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent

快照 = [json.loads(x) for x in (这里 / "情境快照.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
快照.sort(key=lambda x: (str(x["轮"]), int(x["序号"])))

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


def 情境节点(文: str) -> list[int]:
    词 = 关键(文)
    return [i for i, k in enumerate(节点词) if len(k & 词) >= 2]


def 行为族(动: str) -> str:
    段 = 动.split()
    if not 段:
        return "?"
    头 = [x for x in 段 if x != "sudo"]
    前 = 头[:2] if 头 else 段[:2]
    前 = [x.split("/")[-1] if len(x) > 24 else x for x in 前]
    return " ".join(前)[:28]


挡 = re.compile(r"rm 带了递归|find \.\.\. -delete|不用 sudo|rm -rf|高危")


def 拦族(馈: str) -> str:
    m = 挡.search(馈)
    return "拦:" + (m.group(0) if m else 馈[:14])


# ── 建事件流 ──────────────────────────────────────────────────
事件: list[dict[str, Any]] = []
for x in 快照:
    情境 = f"{x['任务']} {x['上一步动作']} {x['上一步反馈']}"
    事件.append({
        "轮": str(x["轮"]),
        "序号": int(x["序号"]),
        "情境文": 情境,
        "情境": 情境节点(情境),
        "行为": 行为族(str(x["本步动作"])),
        "拦族": 拦族(str(x["本步反馈"])),
        "结果": str(x["本步结果"]),
        "上一步结果": str(x["上一步结果"]),
    })
切 = int(len(事件) * 0.7)
训, 测 = 事件[:切], 事件[切:]
行为们 = sorted({e["行为"] for e in 事件} | {e["拦族"] for e in 事件})
行为号 = {b: i for i, b in enumerate(行为们)}
print(f"事件 {len(事件)} 步 ｜ 训练 {len(训)} / 测试 {len(测)} ｜ 节点 {len(节点文)} ｜ 行为族 {len(行为们)}")


def 跑一档(模式: str) -> dict[str, Any]:
    权重: defaultdict[tuple[int, int], float] = defaultdict(float)
    学, 罚, 衰 = 0.30, 0.20, 0.90
    for i, e in enumerate(训):
        for n in e["情境"]:
            k = (n, 行为号.get(e["行为"], -1))
            if 模式 == "静态":                    # 不用反馈，只看"一起出现过"
                权重[k] += 1.0
            elif e["结果"] == "成功":
                权重[k] += 学
            elif e["结果"] == "拦截" and 模式 == "完整":
                权重[k] -= 罚
        if 模式 == "完整" and (i + 1) % 300 == 0:
            for k in list(权重):
                权重[k] *= 衰
    # 考试：上一步被拦的步，推一个行为
    对避, 对中, 总 = 0, 0, 0
    推率计: list[float] = []
    for e in 测:
        if e["上一步结果"] != "拦截":
            continue
        总 += 1
        分: defaultdict[int, float] = defaultdict(float)
        for n in e["情境"]:
            本 = [(b, w) for (nn, b), w in 权重.items() if nn == n and w > 0]
            if not 本:
                continue
            b顶 = max(本, key=lambda x: x[1])
            分[b顶[0]] += b顶[1]                       # 每个情境节点自己先选出它最强的做法，再投票
        if not 分:
            continue
        推 = max(分.items(), key=lambda kv: kv[1])[0]
        推名 = 行为们[推] if 0 <= 推 < len(行为们) else "?"
        if 推名 != e["拦族"]:
            对避 += 1
        if 推名 == e["行为"] and e["结果"] == "成功":
            对中 += 1
    # 推荐的做法的"历史成功率"（训练集里该族 成功/(成功+拦截)）
    族成: defaultdict[str, int] = defaultdict(int)
    族拦: defaultdict[str, int] = defaultdict(int)
    for e in 训:
        if e["结果"] == "成功":
            族成[e["行为"]] += 1
        elif e["结果"] == "拦截":
            族拦[e["行为"]] += 1
    for e in 测:
        if e["上一步结果"] != "拦截":
            continue
        分2: defaultdict[int, float] = defaultdict(float)
        for n in e["情境"]:
            本2 = [(b, w) for (nn, b), w in 权重.items() if nn == n and w > 0]
            if 本2:
                b2 = max(本2, key=lambda x: x[1])
                分2[b2[0]] += b2[1]
        if 分2:
            名 = 行为们[max(分2.items(), key=lambda kv: kv[1])[0]]
            成, 挡 = 族成.get(名, 0), 族拦.get(名, 0)
            推率计.append(成 / max(1, 成 + 挡))
    推率 = sum(推率计) / len(推率计) if 推率计 else 0.0
    健 = sum(1 for w in 权重.values() if w > 0)
    return {"模式": 模式, "考步数": 总, "避开坑": round(对避 / max(1, 总), 3),
            "猜中成功做法": round(对中 / max(1, 总), 3), "推荐成功率": round(推率, 3),
            "正边": 健, "总边": len(权重), "族成": dict(族成), "族拦": dict(族拦)}


表 = [跑一档(x) for x in ("静态", "只加强", "完整")]
# 基线：不看情境、一律推训练集里最常见的成功做法
常 = Counter2(e["行为"] for e in 训 if e["结果"] == "成功").most_common(1)
名常 = 常[0][0] if 常 else "?"
成常 = sum(1 for e in 训 if e["行为"] == 名常 and e["结果"] == "成功")
挡常 = sum(1 for e in 训 if e["行为"] == 名常 and e["结果"] == "拦截")
基 = 成常 / max(1, 成常 + 挡常)
print(f"  （基线：一律推训练集最常见的成功做法「{名常}」，它的历史成功率 {基*100:.1f}%）")
for r in 表:
    print(f"  {r['模式']:6s} 考题 {r['考步数']:3d} 步 ｜ 避开坑 {r['避开坑']*100:5.1f}% ｜ 猜中成功做法 {r['猜中成功做法']*100:5.1f}% ｜ 推荐做法历史成功率 {r['推荐成功率']*100:5.1f}% ｜ 正边 {r['正边']}/{r['总边']}")

(这里 / "结果-可塑图.json").write_text(json.dumps(表, ensure_ascii=False, indent=1), encoding="utf-8")

# ── 会忘吗：早期学的边在后期还在不在 ──────────────────────────
print("\n看图里学到的「习惯」例子 (权最高的 8 条情境→做法):")
w: defaultdict[tuple[int, int], float] = defaultdict(float)
for e in 训:
    for n in e["情境"]:
        if e["结果"] == "成功":
            w[(n, 行为号[e["行为"]])] += 1
        elif e["结果"] == "拦截":
            w[(n, 行为号[e["行为"]])] -= 1
for (n, b), v in sorted(w.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {v:+5.1f}  {节点文[n][:40]}  →  {行为们[b]}")
print("\n最该避开的 (权最低 5 条):")
for (n, b), v in sorted(w.items(), key=lambda kv: kv[1])[:5]:
    print(f"  {v:+5.1f}  {节点文[n][:40]}  →  {行为们[b]}")
