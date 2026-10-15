# -*- coding: utf-8 -*-
"""看这批真实会话进库的效果 —— 切片质量、经验质量、指针覆盖。

判据分三块, 每块都报"分布"而不是一个平均数:
  ① 切片: 长度分布 + 噪声比例(<60字) + 按 kind 分
  ② 经验: 概述/知识 的产出率、抽样
  ③ 指针: 覆盖率（经验里有多少挂上了来源id）+ 顺指针能不能真找回原文
"""
from __future__ import annotations

import statistics
import sys
from collections import Counter
from typing import Any, cast

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import refine  # noqa: E402
import store  # noqa: E402
from psycopg import sql  # noqa: E402

conn = store.connect(refine.rag_config())


def 取数(query: str) -> int:
    """跑一个只返回单值的查询。"""
    row = cast(tuple[Any, ...] | None, conn.execute(sql.SQL(query)).fetchone())  # type: ignore[arg-type]
    return int(row[0]) if row else 0


def 长分布(条件: str, 名: str) -> None:
    rows = conn.execute(
        sql.SQL("SELECT length(text) FROM rag_chunks WHERE {}").format(sql.SQL(条件))  # type: ignore[arg-type]
    ).fetchall()
    v = sorted(int(cast(tuple[Any, ...], r)[0]) for r in rows)
    if not v:
        print(f"  {名:<24} 0 条")
        return
    短 = sum(1 for x in v if x < 60)
    print(
        f"  {名:<24} {len(v):>5} 条  中位 {statistics.median(v):>5.0f}  "
        f"p10 {v[len(v) // 10]:>4}  p90 {v[len(v) * 9 // 10]:>5}  "
        f"<60字 {短:>3} ({短 * 100 // len(v)}%)"
    )


print("══ ① 切片质量")
长分布("tier = 1 AND kind = '对话'", "对话(一问一答)")
长分布("tier = 1 AND kind = '文件'", "文件(按标记/语义)")
长分布("tier = 3 AND kind = '概述'", "概述")
长分布("tier = 3 AND kind = '知识'", "知识")

print()
print("══ ② 经验产出率（每个会话洗出多少条，前 10）")
行 = conn.execute(
    "SELECT source,"
    " count(*) FILTER (WHERE kind = '概述'),"
    " count(*) FILTER (WHERE kind = '知识')"
    " FROM rag_chunks WHERE tier = 3 GROUP BY source ORDER BY count(*) DESC LIMIT 10"
).fetchall()
for r in 行:
    源, 概, 知 = cast(tuple[Any, Any, Any], r)
    print(f"   概述 {int(概):>2} / 知识 {int(知):>2}   {str(源).split('/')[-1][:46]}")
总源 = 取数("SELECT count(DISTINCT source) FROM rag_chunks WHERE tier = 3")
总经验 = 取数("SELECT count(*) FROM rag_chunks WHERE tier = 3")
print(f"   ── {总源} 个会话共 {总经验} 条，平均 {总经验 / max(1, 总源):.1f} 条/会话")

print()
print("══ ③ 指针覆盖")
有 = 取数("SELECT count(*) FROM rag_chunks WHERE tier = 3 AND 来源id IS NOT NULL")
全 = 取数("SELECT count(*) FROM rag_chunks WHERE tier = 3")
print(f"   {有} / {全} 条经验挂了 来源id  ({有 * 100 // max(1, 全)}%)")

print()
print("   顺指针回溯抽样（经验 -> 原文）:")
抽样 = conn.execute(
    "SELECT left(text, 46), 来源id FROM rag_chunks"
    " WHERE tier = 3 AND 来源id IS NOT NULL ORDER BY random() LIMIT 4"
).fetchall()
for r in 抽样:
    文, refs = cast(tuple[Any, Any], r)
    ids = [int(x) for x in str(refs).split(",") if x]
    背 = conn.execute(
        "SELECT left(text, 58) FROM rag_chunks WHERE id = ANY(%s) LIMIT 1", (ids,)
    ).fetchone()
    行文 = str(cast(tuple[Any, ...], 背)[0]) if 背 else "✗ 指针失效（那几行已被重写）"
    print(f"     [{文}]")
    print(f"        -> {行文}")

print()
print("══ ④ 总账")
for r in conn.execute(
    "SELECT tier, kind, count(*) FROM rag_chunks GROUP BY tier, kind ORDER BY tier, kind"
).fetchall():
    t, k, n = cast(tuple[Any, Any, Any], r)
    print(f"   tier={t} kind={str(k):<6} {int(n):>5}")

来源类 = Counter(
    "hermes-history" if "hermes-history" in str(s) else "(项目文件/其它)"
    for (s,) in conn.execute("SELECT DISTINCT source FROM rag_chunks WHERE tier = 1").fetchall()
)
print(f"   tier=1 来源: {dict(来源类.most_common(4))}")
