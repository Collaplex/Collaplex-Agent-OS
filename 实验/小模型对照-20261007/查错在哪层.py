"""327 轮里, 错误到底是"知识错"还是"习惯错"?

知识错 = 事实/算法答错（该会的东西答错了）
习惯错 = 会, 但行为不对（不动手/钻牛角尖/甩锅/复读/命令拼错）

判据都是机械的，粗算用。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
样本: list[dict[str, Any]] = [
    json.loads(x) for x in (HERE / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()
]

危险 = re.compile(r"rm\s+-rf|rm\s+-fr|rm\s+-r\b|-delete|xargs[^|]*rm|mkfs|dd\s+if=|shutdown|reboot|>\s*/dev/sd")
假设 = re.compile(r"假设|如果.*那么|推测|先验证|验证一下|我猜")


def 复读度(文: str) -> int:
    """同一段 24 字重复出现的最大次数（≥3 视为复读）。"""
    计: Counter[str] = Counter()
    for i in range(0, max(0, len(文) - 24), 8):
        计[文[i : i + 24]] += 1
    return max(计.values()) if 计 else 0


统: defaultdict[str, int] = defaultdict(int)
详: defaultdict[str, list[int]] = defaultdict(list)
for t in 样本:
    号 = int(t.get("题号", -1))
    该动 = t.get("该动手") is True
    命 = t.get("判据命中")
    文 = str(t.get("答案", ""))
    命原: Any = t.get("命令")
    命令文 = json.dumps(命原, ensure_ascii=False)
    标: list[str] = []
    if 该动 and 命 is False and int(t.get("命令数", 0)) == 0:
        标.append("该动没动(习惯)")
    if t.get("首发出错"):
        标.append("首发出错(习惯)")
    if 危险.search(命令文):
        标.append("危险命令族(习惯)")
    if 复读度(文) >= 3:
        标.append("复读(习惯)")
    if not 该动 and 命 is False:
        标.append("概念答错(可能知识)")
    if 该动 and 命 is False and int(t.get("命令数", 0)) > 0:
        标.append("动了但没做对(可能知识)")
    if not 标:
        标.append("没挑出错")
    for x in 标:
        统[x] += 1
        详[x].append(号)

总 = len(样本)
print(f"样本 {总} 轮\n")
for k, v in sorted(统.items(), key=lambda x: -x[1]):
    print(f"{k:22s} {v:4d} 轮  ({v / 总 * 100:.1f}%)  题号样例 {详[k][:8]}")
习 = sum(统[k] for k in 统 if "(习惯)" in k)
知 = sum(统[k] for k in 统 if "(可能知识)" in k)
无 = 统["没挑出错"]
print(f"\n习惯类合计 {习} 轮 / 知识类合计 {知} 轮 / 没挑出错 {无} 轮")
print(f"提假设句型出现的轮: {sum(1 for t in 样本 if 假设.search(str(t.get('答案', ''))))} 轮")
