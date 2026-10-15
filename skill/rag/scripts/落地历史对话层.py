# -*- coding: utf-8 -*-
"""落地 rag更新.drawio：把「带时间线的所有历史对话」建成 tier=1。

背景(2026-10-08):
  - 老架构在 PG 里有 5 张中文表(热_对话/冷_原文/冷_概述/冷_知识/冷_别名), 数据全在但**没有代码在用**(孤儿表)。
  - 今早把索引层从 JSON 换成 PG(单表 rag_chunks, 用 tier 区分), 但 tier 只用到 2/3, **tier=1 空着**。
  - 老板的新图: 模型上下文窗口 -> 热层 -> {经验层, 带时间线的所有历史对话}。
    对应 tier:  1=历史对话(底档, 全部原文)  2=热层(当前会话)  3=经验层(提炼)

本脚本只动**元数据, 不碰向量**:
  ① rag_chunks 加三列: 对话id / 对话时间 / 角色
  ② 老表 热_对话 的 1,789 条  -> tier=1, kind='对话' (带 对话id/对话时间/角色)
  ③ 现有 tier=2 的原始切片    -> tier=1, kind='文件' (带 source=文件名)
  ④ tier=3 加指针: source 存它出处 tier=1 的 id

幂等: 重复跑不会重复插(靠 hash 去重, hash 由 tier+文本算, 但这里沿用原 hash 列)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

脚本目录 = Path(__file__).resolve().parent
sys.path.insert(0, str(脚本目录))

import psycopg  # noqa: E402
import refine  # noqa: E402
import store  # noqa: E402
from psycopg import sql  # noqa: E402

# ★ 老的 5 张表在**另一个 PG 实例**（用户级，免密）
老DSN = "host=/home/lou/pgdata/socket dbname=collaplex_agent user=lou"


def 老连接() -> psycopg.Connection[Any]:
    return psycopg.connect(老DSN, autocommit=True)


def 加列(conn: psycopg.Connection[Any], 表: str) -> None:
    """加三列(幂等). 类型: 会话标识/真实时间/说话人."""
    列: list[tuple[str, sql.SQL]] = [
        ("对话id", sql.SQL("text")),
        ("对话时间", sql.SQL("timestamptz")),
        ("角色", sql.SQL("text")),
    ]
    for 名, 型 in 列:
        conn.execute(
            sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} ").format(
                sql.Identifier(表), sql.Identifier(名)
            )
            + 型
        )
    # ★ 指针列：经验层每条记它出处 tier=1 的行 id（逗号分隔，按 source 匹配）
    conn.execute(
        sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} text").format(
            sql.Identifier(表), sql.Identifier("来源id")
        )
    )
    conn.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} ({}, {})").format(
            sql.Identifier(f"{表}_时间线"), sql.Identifier(表), sql.Identifier("对话id"), sql.Identifier("对话时间")
        )
    )
    print(f"  ① 三列 + 时间线索引 ✓ ({表})")


def 历史对话进库(conn: psycopg.Connection[Any], 表: str) -> int:
    """从**用户实例**读老『热_对话』-> 写 tier=1, kind='对话'. 向量一并搬."""
    with 老连接() as 老:
        行们 = 老.execute(
            'SELECT id, 对话, 时间, 角色, 内容, 向量 FROM "热_对话" '
            "WHERE 内容 IS NOT NULL AND 内容 <> '' ORDER BY id"
        ).fetchall()
    print(f"     读到老『热_对话』{len(行们)} 条")

    写 = conn.cursor()
    插入 = 0
    for 序, (旧id, 对话, 时间, 角色, 内容, 向量) in enumerate(行们, 1):
        写.execute(
            sql.SQL(
                "INSERT INTO {} (tier, idx, hash, source, text, kind, embedding, 对话id, 对话时间, 角色) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tier, hash) DO NOTHING"
            ).format(sql.Identifier(表)),
            (1, 序, f"h{旧id}", 对话, 内容, "对话", 向量, 对话, 时间, 角色),
        )
        插入 += 写.rowcount if 写.rowcount > 0 else 0
    print(f"  ② 老『热_对话』-> tier=1 kind='对话' ✓ 新增 {插入} 条")
    return 插入


def 原始切片下沉(conn: psycopg.Connection[Any], 表: str) -> int:
    """现有 tier=2 的原始切片 -> tier=1, kind='文件'（tier=2 留给当前会话）."""
    行 = conn.execute(
        sql.SQL(
            "UPDATE {} SET tier = 1, kind = CASE WHEN kind = '' THEN '文件' ELSE kind END "
            "WHERE tier = 2"
        ).format(sql.Identifier(表))
    )
    n = 行.rowcount if 行.rowcount and 行.rowcount > 0 else 0
    print(f"  ③ tier=2 原始切片 -> tier=1 kind='文件' ✓ {n} 条（tier=2 空出来给热层）")
    return n


def 原文切片归位(conn: psycopg.Connection[Any], 表: str) -> int:
    """tier=3 的 kind='原文' 其实是文件切片 -> 归 tier=1 kind='文件'（经验层只留提炼物）."""
    行 = conn.execute(
        sql.SQL("UPDATE {} SET tier = 1, kind = '文件' WHERE tier = 3 AND kind = '原文'").format(
            sql.Identifier(表)
        )
    )
    n = 行.rowcount if 行.rowcount and 行.rowcount > 0 else 0
    print(f"  ④ tier=3 的『原文』(实为文件切片) -> tier=1 kind='文件' ✓ {n} 条")
    return n


def 回填指针(conn: psycopg.Connection[Any], 表: str) -> int:
    """经验层(tier=3)每条挂上它出处 tier=1 的行 id —— 按 source(文件路径)匹配."""
    行 = conn.execute(
        sql.SQL(
            "UPDATE {} AS t3 SET 来源id = sub.ids "
            "FROM (SELECT source, string_agg(id::text, ',' ORDER BY id) AS ids "
            "      FROM {} WHERE tier = 1 GROUP BY source) AS sub "
            "WHERE t3.tier = 3 AND t3.source = sub.source"
        ).format(sql.Identifier(表), sql.Identifier(表))
    )
    n = 行.rowcount if 行.rowcount and 行.rowcount > 0 else 0
    print(f"  ⑤ 指针回填(经验层 -> tier=1, 按 source 匹配) ✓ {n} 条")
    return n


def main() -> int:
    配置: dict[str, Any] = refine.rag_config()
    if not store.is_pg(配置):
        print("✗ 后端不是 pg")
        return 1
    表 = store.table_name(配置)
    print(f"目标表: {表}\n")

    with store.connect(配置) as conn:
        加列(conn, 表)
        历史对话进库(conn, 表)
        原始切片下沉(conn, 表)
        原文切片归位(conn, 表)
        回填指针(conn, 表)
        conn.commit()

        print("\n══ 结果")
        行 = conn.execute(
            sql.SQL("SELECT tier, kind, count(*) FROM {} GROUP BY tier, kind ORDER BY tier, kind").format(
                sql.Identifier(表)
            )
        ).fetchall()
        for tier, kind, n in 行:
            print(f"  tier={tier}  kind={kind or '(空)':<8} {n} 条")
        会话, 起, 止 = conn.execute(
            sql.SQL(
                "SELECT count(DISTINCT 对话id), to_char(min(对话时间),'MM-DD HH24:MI'), "
                "to_char(max(对话时间),'MM-DD HH24:MI') FROM {} WHERE tier = 1 AND kind = '对话'"
            ).format(sql.Identifier(表))
        ).fetchone() or (0, None, None)
        print(f"\n  历史对话: {会话} 个会话, 时间线 {起} ~ {止}")
        带针 = conn.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE tier = 3 AND 来源id IS NOT NULL AND 来源id <> ''").format(
                sql.Identifier(表)
            )
        ).fetchone()
        print(f"  经验层带指针: {带针[0] if 带针 else 0} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
