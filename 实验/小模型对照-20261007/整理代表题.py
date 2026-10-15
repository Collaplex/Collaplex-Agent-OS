"""整理"代表题" —— 每题给: 题目原文 / 答案原文(全文不截断) / 命令 / 判据 / 数据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).parent
样本: list[dict[str, Any]] = [
    json.loads(x) for x in (HERE / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()
]

# (小标题, 备注, 臂, 题号, 遍)
案例: list[tuple[str, str, str, int, int]] = [
    ("① 钻牛角尖 · 上文带失败过程", "题7「把 /tmp 整个清空」", "F", 7, 1),
    ("② 钻牛角尖 · 上文只给结论（对照）", "同一题", "F", 7, 2),
    ("③ 检索循环：7 次问同一个 skill 同一句话", "同一题", "G", 7, 1),
    ("④ 让它「总结失败」 → 反而真去硬干 6 条", "同一题", "G", 7, 2),
    ("⑤ 让它「从目标反向推」 → 结构写了、素材还是它自己的", "同一题", "G", 7, 3),
    ("⑥ 首轮（同一题第一次问）→ 570 字 / 1 条命令", "同一题", "B", 7, 1),
    ("⑦ 上下文长了再问同一题 → 5896 字 / 11 条命令 / 141 秒", "同一题", "B", 7, 2),
    ("⑧ 稳定漏 · 现在几点了", "短语题", "C", 19, 1),
    ("⑨ 稳定漏 · 两车相向（本地）", "短语题", "C", 44, 1),
    ("⑩ 稳定漏 · 两车相向（换云端照样漏）", "短语题", "D", 44, 1),
    ("⑪ 稳定漏 · 加盐提浓度", "短语题", "C", 45, 1),
    ("⑫ 桥 · 正例 · 无桥", "题22「详细一点，然后写标准和规范一点」", "H", 22, 1),
    ("⑬ 桥 · 正例 · 有桥", "同一题", "H", 22, 2),
    ("⑭ 桥 · 反例 · 无桥", "题20「看看我们系统健不健康」", "H", 20, 1),
    ("⑮ 桥 · 反例 · 有桥（抄了过期读数）", "同一题", "H", 20, 2),
]


def 找(臂: str, 号: int, 遍: int) -> dict[str, Any] | None:
    for r in 样本:
        if r.get("臂") == 臂 and int(r.get("题号", -1)) == 号 and int(r.get("遍", -1)) == 遍:
            return r
    return None


def 块(t: dict[str, Any], 标: str, 注: str) -> str:
    命中: object = t.get("判据命中")
    命文 = "True" if 命中 is True else "False" if 命中 is False else "—(不需要动手)"
    出: list[str] = [
        f"## {标}",
        "",
        f"*{注}* ｜ 来源：臂 {t.get('臂')} 第 {t.get('遍')} 遍",
        "",
        f"- **题目原文**：{t.get('题')}",
        f"- 该动手：{t.get('该动手')} ｜ 期望 skill：{t.get('期望skill')} ｜ 挑中：{t.get('挑中skill')}",
        f"- 判据：{t.get('判据')} ｜ 命中：{命文}",
        f"- 用时 {t.get('用时')}s ｜ 答案 {t.get('答案长')} 字 ｜ 命令 {t.get('命令数')} 条 ｜ 真跑过：{t.get('真跑过')}",
    ]
    原始命: Any = t.get("命令")
    命: list[list[str]] = []
    if isinstance(原始命, list):
        for x in cast("list[Any]", 原始命):
            命.append([str(y) for y in cast("list[Any]", x)] if isinstance(x, list) else [str(x)])
    if 命:
        出.append("- **命令**：")
        for i, 条 in enumerate(命, 1):
            文 = " ".join(条)
            出.append(f"  {i}. `{文}`")
    else:
        出.append("- **命令**：（没动手）")
    出 += ["", "### 答案原文", "", str(t.get("答案", "")).strip(), "", "---", ""]
    return "\n".join(出)


部: list[str] = [
    "# 代表题 · 问答对照",
    "",
    "每题：题目原文 / 答案原文（全文，未截断）/ 命令清单 / 判据 / 数据。",
    "按「现象」分组，方便一条条对着分析。",
    "",
    "---",
    "",
]
for 标, 注, 臂, 号, 遍 in 案例:
    t = 找(臂, 号, 遍)
    if t is None:
        continue
    部.append(块(t, 标, 注))

# 自动补三类：首发出错 / 该动没动 / 概念题不动手（对）/ 记忆指代（对）
加: list[tuple[str, dict[str, Any]]] = []
首 = [t for t in 样本 if t.get("首发出错") and "carve" in json.dumps(t.get("命令"), ensure_ascii=False)]
if 首:
    加.append(("⑯ 首发出错 · 把命令拼错（carve 参数）", 首[0]))
桌 = [t for t in 样本 if t.get("首发出错") and "Desktop" in json.dumps(t.get("命令"), ensure_ascii=False)]
if 桌:
    加.append(("⑰ 首发出错 · 路径想当然（机器上是 ~/桌面 不是 ~/Desktop）", 桌[0]))
漏 = [t for t in 样本 if t.get("臂") == "C" and t.get("该动手") and t.get("判据命中") is False and t.get("命令数") == 0]
if 漏:
    加.append(("⑱ 该动没动 · 该动手却只在嘴上说", 漏[0]))
概 = [t for t in 样本 if t.get("层") == "概念" and t.get("该动手") is False]
if 概:
    加.append(("⑲ 概念题 · 不动手是对的", 概[0]))
记 = [t for t in 样本 if str(t.get("层", "")).startswith("记忆")]
if 记:
    加.append(("⑳ 记忆/指代题 · 全对", 记[0]))

部.append("# 自动补：另外四类（各取一条代表）\n\n---\n")
for 标, t in 加:
    部.append(块(t, 标, f"{t.get('题号')} 题"))

出 = HERE / "代表题-问答.md"
出.write_text("\n".join(部), encoding="utf-8")
print(f"写好 {出}  {出.stat().st_size} 字节  共 {len(案例) + len(加)} 组")
