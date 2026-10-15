# -*- coding: utf-8 -*-
"""读 A/B 结果，逐条打印（供人眼判「该查的有没有去查」）。"""
import json
import sys
from pathlib import Path

产出 = Path(__file__).parent
条件 = sys.argv[1] if len(sys.argv) > 1 else "A"
文件 = 产出 / f"AB-条件{条件}.jsonl"
if not 文件.exists():
    print(f"（还没写：{文件.name}）")
    raise SystemExit(0)

条 = [json.loads(l) for l in 文件.read_text().splitlines() if l.strip()]
print(f"═══ 条件 {条件}｜{len(条)} 条 ═══\n")
for x in 条:
    print(f"── [{x['号']}] {x['题'][:52]}")
    if x.get("过程"):
        print(f"   ★agent: {x['过程'][:110]}")
    print(f"   答：{x['答'][:170]}".replace("\n", " "))
    print()
