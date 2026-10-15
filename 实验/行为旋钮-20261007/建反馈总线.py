"""行为旋钮 · 骨架第①层：环境反馈总线

把每一次"动作 → 环境反馈"归一成一条结构化事件，供后面的"婴儿循环"用：
   轮(题号/臂/时间) · 第几条命令 · 动作(命令原文) · 结果(拦截/报错/成功) · 反馈原文 · 该轮判据是否命中

数据来源全是现成的：
  logs/exec/<日期>-<时分秒>-<序号>.txt  ← 每条命令的输出（文件名里的时分秒＝该轮的起始时间）
  样本.jsonl                            ← 每轮的题、判据、命令清单、时间
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent
执行日志 = 项目 / "logs" / "exec"

样 = [json.loads(x) for x in (源 / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
日录 = re.compile(r"^(\d{8})-(\d{6})-(\d+)\.txt$")
拦 = re.compile(r"\(拦下了[:：](.+?)\)")

事件: list[dict[str, Any]] = []
缺日志 = 0
for 行 in 样:
    时 = str(行.get("时间", ""))                       # 2026-10-07 16:34:16
    if len(时) < 19:
        continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", 时)
    if not m:
        continue
    前 = f"{m.group(1)}{m.group(2)}{m.group(3)}-{m.group(4)}{m.group(5)}"
    秒 = f"{m.group(4)}{m.group(5)}{m.group(6)}"
    这份 = sorted(执行日志.glob(f"{前}*.txt")) if 执行日志.exists() else []
    本轮的 = [p for p in 这份 if (mm := 日录.match(p.name)) and mm.group(2)[:4] == 秒[:4]]
    if not 本轮的:
        缺日志 += 1
    命令表: list[list[str]] = []
    原命: Any = 行.get("命令")
    if isinstance(原命, list):
        for x in cast("list[Any]", 原命):
            命令表.append([str(y) for y in cast("list[Any]", x)] if isinstance(x, list) else [str(x)])
    for p in 本轮的:
        mm = 日录.match(p.name)
        if not mm:
            continue
        序 = int(mm.group(3))
        文 = p.read_text(encoding="utf-8", errors="replace")
        首行 = 文.splitlines()[0] if 文.splitlines() else ""
        动作 = 首行[2:] if 首行.startswith("$ ") else ""
        若拦 = 拦.search(文)
        if 若拦:
            结果, 反馈 = "拦截", 若拦.group(1).strip()
        elif "[stderr]" in 文:
            行们 = [l for l in 文.splitlines() if l.strip() and not l.startswith("$") and l != "[stderr]"]
            结果, 反馈 = "报错", (行们[0][:160] if 行们 else "")
        else:
            行们 = [l for l in 文.splitlines() if l.strip() and not l.startswith("$")]
            结果, 反馈 = "成功", (行们[0][:160] if 行们 else "(无输出)")
        if not 动作 and 序 - 1 < len(命令表):
            动作 = " ".join(命令表[序 - 1])
        事件.append({
            "轮": f"{行.get('臂')}{行.get('题号')}-{行.get('遍')}",
            "题号": int(行.get("题号", -1)),
            "臂": str(行.get("臂", "")),
            "时间": 时,
            "序号": 序,
            "动作": 动作,
            "结果": 结果,
            "反馈": 反馈,
            "判据": str(行.get("判据", "")),
            "判据命中": 行.get("判据命中"),
            "类别": str(行.get("层", "")),
        })

(这里 / "反馈总线.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in 事件), encoding="utf-8")

# ── 汇总 ──────────────────────────────────────────────────────
计 = Counter(e["结果"] for e in 事件)
print(f"事件 {len(事件)} 条（{缺日志} 轮没匹配到日志）")
print("结果分布:", dict(计))
按轮: dict[str, list[dict[str, Any]]] = {}
for e in 事件:
    按轮.setdefault(e["轮"], []).append(e)
连拦 = [k for k, v in 按轮.items() if sum(1 for e in v if e["结果"] == "拦截") >= 2]
换路样本 = [k for k, v in 按轮.items() if v and v[-1]["结果"] != "拦截" and sum(1 for e in v if e["结果"] == "拦截") >= 1]
print(f"被拦 ≥2 次的轮: {len(连拦)} 个 ｜ 拦过但最后不是拦截的轮: {len(换路样本)} 个")
print("\n拦截事件举例（前 5 条）:")
for e in [x for x in 事件 if x["结果"] == "拦截"][:5]:
    print(f"  {e['轮']} #{e['序号']}  {e['动作'][:52]}\n      反馈: {e['反馈'][:78]}")

# 顺手看一眼第②层长什么样：任务 + 上一步动作 + 上一步反馈
print("\n第②层情境快照的样子（拿一条被拦后的轮演示）:")
for k in 换路样本[:1]:
    v = 按轮[k]
    for i, e in enumerate(v):
        上 = v[i - 1] if i else None
        print(f"  步{i + 1}: 动作={e['动作'][:40]}")
        if 上:
            print(f"        含上一步反馈({上['结果']}): {上['反馈'][:60]}")
