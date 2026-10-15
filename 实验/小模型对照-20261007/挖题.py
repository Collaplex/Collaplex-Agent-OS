"""从三层库/二层语料/网页存档里挖出老板真实问过的问题, 落成一份清单。"""

import json
import re
from pathlib import Path

ROOT = Path("/home/lou/桌面/collaplex_agent")
出 = Path(__file__).parent / "真题-全部.txt"


def 从三层库() -> list[str]:
    路 = ROOT / "skill/rag/scripts/memory-index.json"
    if not 路.exists():
        return []
    数据 = json.loads(路.read_text(encoding="utf-8"))
    条 = 数据 if isinstance(数据, list) else 数据.get("items", [])
    题: list[str] = []
    for x in 条:
        m = re.search(r"# 任务\s*\n+(.+)", str(x.get("text", "")))
        if m:
            题.append(m.group(1).strip())
    return 题


def 从语料() -> list[str]:
    题: list[str] = []
    for f in (ROOT / "skill/rag/corpus").glob("*.md"):
        m = re.search(r"# 任务\s*\n+(.+)", f.read_text(encoding="utf-8", errors="replace"))
        if m:
            题.append(m.group(1).strip())
    return 题


def 从网页存档() -> list[str]:
    路 = ROOT / "state/web-对话.jsonl"
    if not 路.exists():
        return []
    出题: list[str] = []
    for 行 in 路.read_text(encoding="utf-8").splitlines():
        if 行.strip():
            出题.append(str(json.loads(行).get("问", "")).strip())
    return [t for t in 出题 if t]


def 从旧台账() -> list[str]:
    题: list[str] = []
    for 路 in sorted((ROOT / "logs/outsource").glob("*.jsonl")):
        for 行 in 路.read_text(encoding="utf-8").splitlines():
            if not 行.strip():
                continue
            try:
                题.append(str(json.loads(行).get("题", "")).strip())
            except json.JSONDecodeError:
                pass
    return [t for t in 题 if t]


全部: list[str] = []
for 取 in (从三层库, 从语料, 从网页存档, 从旧台账):
    全部.extend(取())

见 = []
for t in 全部:
    if t and t not in 见:
        见.append(t)

出.write_text("\n".join(f"{i+1:>3}. {t}" for i, t in enumerate(见)) + "\n", encoding="utf-8")
print(f"共 {len(见)} 条(去重) → {出}")
for i, t in enumerate(见):
    print(f"{i+1:>3}. {t[:78]}")
