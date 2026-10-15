# -*- coding: utf-8 -*-
"""看切片算法的实际产出 —— 找问题用。

关注三件事:
  ① 超长切片(比 chunk_size 大很多) —— 有没有兜底
  ② 过短切片(<100字) —— 检索时的噪声
  ③ 一个会话被切成多少片、切点在哪 —— 是不是切碎了
"""
from __future__ import annotations

import statistics
import sys

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import refine  # noqa: E402
import store  # noqa: E402
from psycopg import sql  # noqa: E402

配置 = refine.rag_config()
conn = store.connect(配置)


def 分布(where: sql.SQL, 名: str) -> None:
    rows = conn.execute(
        sql.SQL("SELECT length(text) FROM rag_chunks WHERE {}").format(where)
    ).fetchall()
    v: list[int] = sorted(int(r[0]) for r in rows)
    if not v:
        print(f"  {名}: 空")
        return
    def 分位(q: float) -> int:
        return v[min(len(v) - 1, int(len(v) * q))]
    print(
        f"  {名:<22} n={len(v):>5}  中位 {statistics.median(v):>6.0f}  "
        f"p90 {分位(0.9):>6}  p99 {分位(0.99):>7}  最大 {v[-1]:>7}"
    )


print("══ 一、长度分布")
分布(sql.SQL("tier = 1 AND kind = '对话'"), "对话(按轮切)")
分布(sql.SQL("tier = 1 AND kind = '文件'"), "文件")
分布(sql.SQL("tier = 3 AND kind = '概述'"), "概述")
分布(sql.SQL("tier = 3 AND kind = '知识'"), "知识")

print("\n══ 二、超长切片（> 2000 字，chunk_size=800 的两倍以上）")
for kind, n, mx in conn.execute(
    "SELECT kind, count(*), max(length(text)) FROM rag_chunks "
    "WHERE tier = 1 AND length(text) > 2000 GROUP BY kind"
).fetchall():
    print(f"  {kind}: {n} 条, 最长 {mx} 字")

print("\n══ 三、最长的三条长什么样")
for 长, src, txt in conn.execute(
    "SELECT length(text), source, left(text, 90) FROM rag_chunks "
    "WHERE tier = 1 ORDER BY length(text) DESC LIMIT 3"
).fetchall():
    print(f"  [{长}字] {str(src)[:56]}")
    print(f"      {txt!r}")

print("\n══ 四、过短切片（<60 字，几乎没有检索价值）")
短 = int(conn.execute("SELECT count(*) FROM rag_chunks WHERE tier = 1 AND length(text) < 60").fetchone()[0])  # type: ignore[index]
总 = int(conn.execute("SELECT count(*) FROM rag_chunks WHERE tier = 1").fetchone()[0])  # type: ignore[index]
print(f"  {短} / {总} 条 = {短 * 100 // max(1, 总)}%")
for kind, n in conn.execute(
    "SELECT kind, count(*) FROM rag_chunks WHERE tier = 1 AND length(text) < 60 GROUP BY kind"
).fetchall():
    print(f"    {kind}: {n} 条")

print("\n══ 五、一个真实会话被切成什么样（切片大小的分布）")
会话 = conn.execute(
    "SELECT 对话id, count(*), sum(length(text)) FROM rag_chunks "
    "WHERE tier = 1 AND kind = '对话' GROUP BY 对话id ORDER BY count(*) DESC LIMIT 3"
).fetchall()
for cid, n, 总字数 in 会话:
    print(f"  『{cid}』{n} 片, 共 {总字数} 字, 平均每片 {总字数 // max(1, n)} 字")
    细节 = conn.execute(
        "SELECT length(text), left(text, 46) FROM rag_chunks "
        "WHERE tier = 1 AND 对话id = %s ORDER BY 对话时间 LIMIT 6",
        (cid,),
    ).fetchall()
    for l, t in 细节:
        print(f"      [{l:>4}字] {t!r}")
    if n > 6:
        print(f"      …（还有 {n - 6} 片）")
