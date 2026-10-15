"""量三件事（全用已有样本, 不烧钱）:
  ① RAG 里到底有没有"经验" —— 三层库 kind 分布 + 教训型条目占比
  ② 它会不会"提假设再验证" —— 答案/声明里出现假设句式的比例
  ③ 它"发不发散" —— 同一轮里命令落在几个不同的族（族越少 = 越钻牛角尖）
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

A = Path("/home/lou/桌面/collaplex_agent")
H = A / "实验" / "小模型对照-20261007"

# ── ① RAG 里有没有经验 ─────────────────────────────────────────
_结构: Any = json.loads((A / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
条: list[dict[str, str]] = []
if isinstance(_结构, list):
    条 = cast("list[dict[str, str]]", _结构)
elif isinstance(_结构, dict):
    映射 = cast("dict[str, Any]", _结构)
    内: Any = 映射.get("items", [])
    条 = cast("list[dict[str, str]]", 内) if isinstance(内, list) else []
kind = Counter(str(x["kind"]) for x in 条)
教训 = re.compile(r"不能|不许|别用|避免|要(用|走|先)|必须|注意|坑|踩过|记得")
过程 = re.compile(r"我先|尝试了|被拦|重试|又试|失败了")
经型 = [x for x in 条 if 教训.search(str(x["text"]))]
过型 = [x for x in 条 if 过程.search(str(x["text"]))]
print("① RAG 里的构成")
print(f"   三层库共 {len(条)} 条, kind 分布: {dict(kind)}")
print(f"   含'不能/必须/别用/避免'这类教训措辞的: {len(经型)} 条 ({len(经型) / max(1, len(条)) * 100:.1f}%)")
print(f"   含'我先/尝试了/被拦'这类过程措辞的: {len(过型)} 条")
print(f"   kind 里有没有独立的'经验'类目: {'经验' in kind}")
语料 = sorted((A / "skill/rag/corpus").glob("*.md"))
print(f"   二层语料文件: {len(语料)} 个")
for 路 in 语料[:3]:
    print(f"     {路.name} ({len(路.read_text(encoding='utf-8'))}字)")

# ── ② 会不会"先提假设再验证" ────────────────────────────────────
假设 = re.compile(r"假设|如果.{0,12}那么|推测|猜想|我估计|先验证|验证一下|验证是否|试试看|试一下这种|可能是.{0,10}(导致|因为)|先做个|先测一下")
样: list[dict[str, Any]] = [json.loads(l) for l in (H / "样本.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
有 = [t for t in 样 if 假设.search(str(t.get("答案", "")) + str(t.get("声明", "")))]
print(f"\n② 提假设/先验证的句式")
print(f"   样本 {len(样)} 轮里出现过这类句式的: {len(有)} 轮 ({len(有) / max(1, len(样)) * 100:.1f}%)")
按臂 = Counter(str(t["臂"]) for t in 有)
print(f"   按臂分布: {dict(按臂)}")

# ── ③ 发散度: 同一轮命令落在几个族 ─────────────────────────────
族表 = {
    "删除": re.compile(r"\brm\b|rmtree|shred|unlink"),
    "查看": re.compile(r"\bls\b|\bdu\b|\bdf\b|stat|wc\b|head\b|tail\b"),
    "查找": re.compile(r"\bfind\b|grep|rg\b|locate"),
    "网络": re.compile(r"\bss\b|netstat|lsof|curl|ping|ip\b"),
    "服务": re.compile(r"systemctl|service\b|nohup|kill\b|pkill"),
    "编程": re.compile(r"python|node|bash -c|\bcat\b.*>|tee\b"),
    "检索": re.compile(r"main\.py (find|recall)|skill/"),
    "文本处理": re.compile(r"\bsed\b|\bawk\b|sort\b|uniq\b|tr\b"),
    "权限": re.compile(r"sudo|chmod|chown"),
}


def 几族(命令们: list[str]) -> set[str]:
    出: set[str] = set()
    for c in 命令们:
        for 名, 模 in 族表.items():
            if 模.search(c):
                出.add(名)
    return 出


多轮 = [t for t in 样 if int(t.get("命令数", 0)) >= 3]
print(f"\n③ 发散度（命令 ≥3 条的轮, 共 {len(多轮)} 轮）")
分: list[int] = []
for t in 多轮:
    原始: list[list[str]] = list(t.get("命令") or [])
    命令 = [str(c) for 组 in 原始 for c in 组]
    族们 = 几族(命令)
    分.append(len(族们))
if 分:
    平均 = sum(分) / len(分)
    print(f"   平均落在 {平均:.1f} 个族（人解题一般会跨 2~3 个族: 先看→再动→再验）")
    print(f"   只有 1 个族的轮: {sum(1 for x in 分 if x == 1)}/{len(分)} ({sum(1 for x in 分 if x == 1) / len(分) * 100:.0f}%)")
    print(f"   ≥3 个族的轮: {sum(1 for x in 分 if x >= 3)}/{len(分)} ({sum(1 for x in 分 if x >= 3) / len(分) * 100:.0f}%)")
试7 = [t for t in 样 if int(t["题号"]) == 7]
for t in 试7:
    原始: list[list[str]] = list(t.get("命令") or [])
    命令 = [str(c) for 组 in 原始 for c in 组]
    print(f"   题7 臂{t['臂']}/{t.get('上文形态', '')}: {len(命令)} 条命令 → 族 {sorted(几族(命令))}")
